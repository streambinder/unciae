#!/usr/bin/env python3
"""Build-time patch for musegadget: add POST /chat/subscribe streaming.

The Linux SDK only knows POST /chat/stream, whose response is a delivery
receipt; the assistant's text never comes back on that request. The Muse
VM also offers POST /chat/subscribe, a long-lived NDJSON event stream
(agent.status, delta.text_append, delta.message_done, message.*), which
upstream implements only in the ESP32 firmware. Community PR
facebookincubator/muse-gadget-sdk#100 proved the same approach on Linux
against a real Muse, side chats included; this patch adapts that design
to our image, kept as small as a build-time patch allows:

* link_client.py gains parse_chat_event (flatten one NDJSON row),
  ReplyTracker (which event ends our turn; correlation is by order, see
  its docstring), a _Subscription stream object registered in the
  existing LinkSession._requests map (the stock read loop already
  dispatches frames to it one by one), and subscribe/close_subscription
  methods on LinkSession.
* service.py gains a streaming mode for the local socket: a request with
  "subscribe": true opens the subscription before send_chat, forwards
  each event as its own JSON line ({"event": ...}) while the turn runs,
  and finishes with the usual result line as the last line. Requests
  without it keep the exact one-line behaviour.

Fails the build loudly if upstream changes an expected line. An optional
first argument overrides the musegadget package directory (for tests).
"""

import glob
import sys

LINK_PATCHES = [
    (
        "separate ``POST /chat/stream`` requests on the same session.\n",
        (
            "separate ``POST /chat/stream`` requests on the same session. Replies "
            "arrive\non ``POST /chat/subscribe``, a live NDJSON event stream.\n"
        ),
    ),
    (
        "import asyncio\nimport enum\n",
        "import asyncio\nimport collections\nimport enum\n",
    ),
    (
        'CHAT_PATH = "/chat/stream"\n',
        (
            'CHAT_PATH = "/chat/stream"\nSUBSCRIBE_PATH = "/chat/subscribe"\n'
            "MAX_EVENT_LINE = 1024 * 1024\n"
        ),
    ),
    (
        "        self._requests: dict[int, _Request] = {}\n",
        "        self._requests: dict[int, _Request | _Subscription] = {}\n",
    ),
    (
        """            for request in self._requests.values():
                if not request.done.done():
                    request.done.set_exception(ConnectionError("session ended"))
""",
        """            for request in self._requests.values():
                request.abort()
""",
    ),
    (
        "    # -- Sending --------------------------------------------------------------\n",
        '''    # -- Replies: POST /chat/subscribe ----------------------------------------

    async def subscribe(self, session_id: str | None, sink) -> "_Subscription":
        """Open a /chat/subscribe stream for one chat and feed events to sink.

        ``session_id`` selects a side chat; without it the subscription is
        for the main chat. The stream stays open until close_subscription
        or the end of the session.
        """
        body = json.dumps({"session_id": session_id}).encode() if session_id else b"{}"
        headers = [
            Header("Content-Type", "application/json"),
            Header("Accept", "application/x-ndjson"),
            Header("x-request-id", str(uuid.uuid4())),
            Header("x-app-id", APP_ID),
        ]
        encrypted = self._transport.encrypt_http_request(
            "POST", SUBSCRIBE_PATH, body, headers=headers)
        subscription = _Subscription(encrypted.stream_id, sink)
        self._requests[encrypted.stream_id] = subscription
        await self._send_frames(encrypted.frames)
        return subscription

    async def close_subscription(self, subscription: "_Subscription") -> None:
        self._requests.pop(subscription.stream_id, None)
        if subscription.closed.is_set():
            return
        subscription.abort()
        try:
            await self._send_frames(self._transport.encrypt_reset(subscription.stream_id))
        except Exception as exc:
            log.debug("could not reset the subscribe stream: %s", exc)

    # -- Sending --------------------------------------------------------------
''',
    ),
    (
        """    def on_frame(self, frame) -> None:
        if self.done.done():
            return
""",
        """    def abort(self) -> None:
        if not self.done.done():
            self.done.set_exception(ConnectionError("session ended"))

    def on_frame(self, frame) -> None:
        if self.done.done():
            return
""",
    ),
    (
        "\nclass _NoRequest:\n",
        '''

def parse_chat_event(line: bytes) -> dict | None:
    """Flatten one /chat/subscribe row into event, ids and text, or None.

    Rows that are not events (the subscription acknowledgement, heartbeats)
    and malformed rows return None. Text precedence follows the ESP32
    firmware: display_text, then content, then text (the incremental chunk
    on delta.text_append, the full text on delta.message_done).
    """
    try:
        row = json.loads(line)
    except ValueError:
        return None
    if not isinstance(row, dict) or row.get("type") != "event":
        return None
    payload = row.get("payload")
    fields = {**row, **(payload if isinstance(payload, dict) else {})}
    text = next((fields[k] for k in ("display_text", "content", "text")
                 if isinstance(fields.get(k), str)), "")
    return {
        "event": fields.get("event_name") or fields.get("event") or "",
        "message_id": fields.get("message_id") or fields.get("id") or "",
        # An explicit reply_to wins even when empty: the Muse leaves it
        # empty and sets parent_message_id to the message's own id.
        "reply_to": (fields["reply_to_message_id"]
                     if isinstance(fields.get("reply_to_message_id"), str)
                     else fields.get("parent_message_id") or ""),
        "text": text,
        "seq": fields.get("seq") if isinstance(fields.get("seq"), int) else None,
    }


class ReplyTracker:
    """Tells whether a subscribe event ends the turn for one posted note.

    Correlation is by order, not by id: reply_to_message_id is empty on
    replies and parent_message_id is the reply's own id. So the answer is
    the first assistant message that completes after the message.user
    event for our note (history replayed when the subscription opens
    comes before it), or any completing message that names our note in
    reply_to. The note id is known only once the /chat/stream ack
    returns, so feed() comes in two phases around set_note_id().
    """

    def __init__(self) -> None:
        self.note_id = ""
        self._own_user_seen = False
        self._owner = ""

    def set_note_id(self, note_id: str) -> None:
        self.note_id = note_id

    def feed(self, event: dict) -> bool:
        """True when event completes our reply; False while it runs."""
        name, mid = event["event"], event["message_id"]
        if name == "message.user":
            if self.note_id and mid == self.note_id:
                self._own_user_seen = True
            return False
        if name.startswith("delta.") and mid:
            self._owner = self._owner or mid
        if name not in ("delta.message_done", "message.assistant"):
            return False
        if self.note_id and event["reply_to"] == self.note_id:
            return True
        if not self._own_user_seen:
            return False
        return not (self._owner and mid and mid != self._owner)


class _Subscription:
    """One /chat/subscribe stream, decoded into events for a sink.

    Body bytes are buffered and split into NDJSON lines as they arrive;
    each complete line is parsed and handed to the sink immediately, not
    at end_body. Repeated seq numbers are dropped.
    """

    def __init__(self, stream_id: int, sink) -> None:
        self.stream_id = stream_id
        self.closed = asyncio.Event()
        self._sink = sink
        self._buffer = b""
        self._seen: collections.deque = collections.deque(maxlen=256)

    def abort(self) -> None:
        self.closed.set()

    def on_frame(self, frame) -> None:
        if self.closed.is_set():
            return
        if frame.kind == "reset":
            self.closed.set()
            return
        if frame.kind == "response":
            if frame.value.status >= 400:
                log.warning("/chat/subscribe refused: HTTP %d", frame.value.status)
                self.closed.set()
                return
            data, ended = frame.value.body, frame.value.end_body
        else:
            data, ended = frame.value.data, frame.value.end_body
        self._buffer += data
        *lines, self._buffer = self._buffer.split(b"\\n")
        if len(self._buffer) > MAX_EVENT_LINE:
            log.warning("/chat/subscribe line too long; closing the stream")
            self.closed.set()
            return
        for line in lines:
            event = parse_chat_event(line) if line.strip() else None
            if event is None:
                continue
            key = (event["event"], event["seq"], event["message_id"])
            if event["seq"] is not None and key in self._seen:
                continue
            self._seen.append(key)
            self._sink(event)
        if ended:
            self.closed.set()


class _NoRequest:
''',
    ),
]

SERVICE_PATCHES = [
    (
        "MAX_LOCAL_REQUEST = 64 * 1024\n",
        "MAX_LOCAL_REQUEST = 64 * 1024\nSTREAM_WAIT_S = 660\nSTREAM_QUIET_S = 15\n",
    ),
    (
        """    async def _handle_local(self, reader, writer) -> None:
        try:
            line = await asyncio.wait_for(reader.readline(), 10)
            reply = await self._local_request(line)
        except Exception as exc:
            reply = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        writer.write(json.dumps(reply).encode() + b"\\n")
        try:
            await writer.drain()
        finally:
            writer.close()
""",
        """    async def _handle_local(self, reader, writer) -> None:
        try:
            line = await asyncio.wait_for(reader.readline(), 10)
            if self._wants_subscribe(line):
                await self._local_stream_request(line, writer)
                return
            reply = await self._local_request(line)
        except Exception as exc:
            reply = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        writer.write(json.dumps(reply).encode() + b"\\n")
        try:
            await writer.drain()
        finally:
            writer.close()

    @staticmethod
    def _wants_subscribe(line: bytes) -> bool:
        try:
            request = json.loads(line)
        except ValueError:
            return False
        return isinstance(request, dict) and request.get("subscribe") is True

    async def _local_stream_request(self, line: bytes, writer) -> None:
        \"\"\"One chat turn with /chat/subscribe events streamed to the socket.

        Each event goes out as its own JSON line, {"event": ...} (event
        types only are logged here, never contents), and the usual result
        line is written last. The subscription opens before send_chat so
        no early event is missed; events are buffered until the chat ack
        names our note, then only events from our message.user on are
        forwarded (history replayed on subscribe is dropped). The stream
        ends when ReplyTracker sees the reply complete, the subscription
        closes, or STREAM_WAIT_S elapses.
        \"\"\"
        from musegadget.link_client import ReplyTracker

        request = json.loads(line)
        message = request.get("message") if isinstance(request, dict) else None
        if not isinstance(message, str) or not message.strip():
            reply = {"ok": False, "error": "expected {\\"message\\": \\"...\\"}"}
            writer.write(json.dumps(reply).encode() + b"\\n")
            await writer.drain()
            return
        session_id = request.get("session_id")
        if session_id is not None and not (
            isinstance(session_id, str) and _SESSION_ID_RE.fullmatch(session_id)
        ):
            reply = {"ok": False, "error": "session_id must be letters, digits and dashes"}
            writer.write(json.dumps(reply).encode() + b"\\n")
            await writer.drain()
            return
        session = self._current
        if session is None or session.registered_at is None:
            reply = {"ok": False, "error": "not connected to the Muse"}
            writer.write(json.dumps(reply).encode() + b"\\n")
            await writer.drain()
            return
        log.info("forwarding a %d-character message to the Muse (subscribed)",
                 len(message))
        events: asyncio.Queue = asyncio.Queue()
        subscription = await session.subscribe(session_id, events.put_nowait)
        tracker = ReplyTracker()
        buffered: list[dict] = []
        result: dict | None = None
        forwarding = False
        try:
            post = asyncio.ensure_future(session.send_chat(message, session_id))
            deadline = time.monotonic() + STREAM_WAIT_S
            last_event = time.monotonic()
            done = False
            while not done and time.monotonic() < deadline:
                try:
                    event = await asyncio.wait_for(events.get(), 0.2)
                except asyncio.TimeoutError:
                    event = None
                if event is not None:
                    last_event = time.monotonic()
                    log.info("subscribe event %s", event["event"])
                    if forwarding:
                        writer.write(json.dumps({"event": event}).encode() + b"\\n")
                        await writer.drain()
                        done = tracker.feed(event)
                    else:
                        buffered.append(event)
                if post.done() and result is None:
                    result = post.result()
                    response = result.get("response")
                    note_id = ""
                    if isinstance(response, dict):
                        note_id = str(response.get("message_id") or "")
                    tracker.set_note_id(note_id)
                    while not events.empty():
                        buffered.append(events.get_nowait())
                    # History replayed when the subscription opened sits in
                    # the buffer before our note; forward only from our own
                    # message.user event on (or a reply naming our note).
                    # Anything at all is forwarded when the ack carries no
                    # message id, so a live turn is never starved.
                    forwarding = True
                    live = not note_id
                    for past in buffered:
                        if not live:
                            if past["event"] == "message.user" and (
                                past["message_id"] == note_id
                            ):
                                live = True
                            elif past["reply_to"] == note_id and past["event"] != (
                                "message.user"
                            ):
                                live = True
                            else:
                                continue
                        writer.write(json.dumps({"event": past}).encode() + b"\\n")
                        await writer.drain()
                        if tracker.feed(past):
                            done = True
                            break
                if subscription.closed.is_set() and events.empty() and post.done():
                    break
                if post.done() and time.monotonic() - last_event > STREAM_QUIET_S:
                    break
            if result is None:
                if post.done():
                    result = post.result()
                else:
                    post.cancel()
                    result = {"ok": False, "error": "subscribe wait timed out"}
        finally:
            await session.close_subscription(subscription)
        writer.write(json.dumps(result).encode() + b"\\n")
        await writer.drain()
""",
    ),
]


def patch_file(path: str, patches: list[tuple[str, str]]) -> None:
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    for needle, replacement in patches:
        if needle not in text:
            sys.exit(f"{path}: expected line not found; upstream changed, patch needs review")
        text = text.replace(needle, replacement, 1)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    print(f"patched {path}")


def main() -> None:
    if len(sys.argv) > 1:
        package_dirs = [sys.argv[1]]
    else:
        package_dirs = glob.glob("/opt/musegadget/venv/lib/python3.*/site-packages/musegadget")
    if len(package_dirs) != 1:
        sys.exit(f"musegadget package dir not found uniquely: {package_dirs}")
    base = package_dirs[0]
    patch_file(f"{base}/link_client.py", LINK_PATCHES)
    patch_file(f"{base}/service.py", SERVICE_PATCHES)


if __name__ == "__main__":
    main()
