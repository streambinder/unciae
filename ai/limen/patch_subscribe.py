#!/usr/bin/env python3
"""Build-time patch for musegadget: stream replies on the local socket.

Upstream's LinkSession now speaks POST /chat/subscribe itself
(subscribe_chat yields the NDJSON event rows), but the local command
socket in service.py still answers one request line with one result
line, so the shim cannot see a reply before the turn ends. This patch
adds the streaming mode to service.py only:

* _flatten_chat_event flattens one event row into the event, ids and
  text the shim consumes; _ReplyTracker tells which event ends our
  turn (correlation is by order, see its docstring).
* A socket request with "subscribe": true opens the subscription
  before send_chat, forwards each event as its own JSON line
  ({"event": ...}) while the turn runs, and finishes with the usual
  result line as the last line. Requests without it keep the exact
  one-line behaviour.

Fails the build loudly if upstream changes an expected line. An
optional first argument overrides the musegadget package directory
(for tests).
"""

import glob
import sys

SERVICE_PATCHES = [
    (
        "import asyncio\nimport base64\nimport json\n",
        "import asyncio\nimport collections\nimport base64\nimport json\n",
    ),
    (
        "MAX_LOCAL_REQUEST = 4 * 1024 * 1024  # room for a 2 MiB image in base64\n",
        (
            "MAX_LOCAL_REQUEST = 4 * 1024 * 1024  # room for a 2 MiB image in base64\n"
            "STREAM_WAIT_S = 660\nSTREAM_QUIET_S = 15\n"
        ),
    ),
    (
        "@dataclass\nclass Service:\n",
        '''def _flatten_chat_event(row: dict) -> dict | None:
    """Flatten one /chat/subscribe row into event, ids and text, or None.

    Rows that are not events return None. Text precedence follows the
    ESP32 firmware: display_text, then content, then text (the
    incremental chunk on delta.text_append, the full text on
    delta.message_done).
    """
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


class _ReplyTracker:
    """Tells whether a subscribe event ends the turn for one posted note.

    Correlation is by order, not by id: reply_to_message_id is empty on
    replies and parent_message_id is the reply's own id. So the answer
    is the first assistant message that completes after the
    message.user event for our note (history replayed when the
    subscription opens comes before it), or any completing message
    that names our note in reply_to. The note id is known only once
    the /chat/stream ack returns, so feed() comes in two phases around
    set_note_id().
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


@dataclass
class Service:
''',
    ),
    (
        """    async def _handle_local(self, reader, writer) -> None:
        too_long = False
        try:
            try:
                line = await asyncio.wait_for(reader.readline(), 10)
            except ValueError:  # the line is over the stream limit
                too_long = True
                reply = {"ok": False,
                         "error": f"the request is over {MAX_LOCAL_REQUEST // (1024 * 1024)} MiB"}
            else:
                reply = await self._local_request(line)
        except Exception as exc:
            reply = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        writer.write(json.dumps(reply).encode() + b"\\n")
        try:
            await writer.drain()
            if too_long:
                # Closing with unread input resets the connection, which can
                # lose the reply before the sender reads it.
                await _discard_line(reader)
        finally:
            writer.close()
""",
        """    async def _handle_local(self, reader, writer) -> None:
        too_long = False
        try:
            try:
                line = await asyncio.wait_for(reader.readline(), 10)
            except ValueError:  # the line is over the stream limit
                too_long = True
                reply = {"ok": False,
                         "error": f"the request is over {MAX_LOCAL_REQUEST // (1024 * 1024)} MiB"}
            else:
                if self._wants_subscribe(line):
                    await self._local_stream_request(line, writer)
                    return
                reply = await self._local_request(line)
        except Exception as exc:
            reply = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        writer.write(json.dumps(reply).encode() + b"\\n")
        try:
            await writer.drain()
            if too_long:
                # Closing with unread input resets the connection, which can
                # lose the reply before the sender reads it.
                await _discard_line(reader)
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
        ends when _ReplyTracker sees the reply complete, the subscription
        ends, or STREAM_WAIT_S elapses. A subscription that fails or ends
        early never fails the turn: the result line still goes out and
        the shim falls back to its file drop.
        \"\"\"
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
        seen: collections.deque = collections.deque(maxlen=256)

        async def pump() -> None:
            try:
                async for row in session.subscribe_chat(session_id):
                    event = _flatten_chat_event(row)
                    if event is None:
                        continue
                    key = (event["event"], event["seq"], event["message_id"])
                    if event["seq"] is not None and key in seen:
                        continue
                    seen.append(key)
                    events.put_nowait(event)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("chat subscription ended early: %s", exc)

        pump_task = asyncio.ensure_future(pump())
        tracker = _ReplyTracker()
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
                if pump_task.done() and events.empty() and post.done():
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
            pump_task.cancel()
            try:
                await pump_task
            except asyncio.CancelledError:
                pass
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
    patch_file(f"{package_dirs[0]}/service.py", SERVICE_PATCHES)


if __name__ == "__main__":
    main()
