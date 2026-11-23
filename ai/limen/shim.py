#!/usr/bin/env python3
"""OpenAI-compatible shim in front of a local musegadget service.

Pi (or any OpenAI client) -> POST /v1/chat/completions -> this shim ->
one JSON line on the musegadget Unix socket -> Muse turn (side chat)
-> reply JSON line -> chat.completion JSON back to the client.

v0 notes:
- The conversation is flattened into a single user message per request;
  continuity lives in the Muse side chat named by session_id.
- Message contents are never logged, only lengths, timings and event
  types.

Streaming: with stream=true the shim sends the turn once with the
upstream wait field (see Reply protocol) while it drains a
subscribe-only connection for live deltas, and translates the deltas
into OpenAI SSE chunks as they arrive: delta.text_append becomes a
chunk, delta.message_done carries the full authoritative text
(checked against the accumulated deltas; SSE cannot retract, so on a
mismatch the streamed text stands and only the lengths are logged),
agent.status and task.status are dropped. Live deltas are best
effort: the server emits them only for turns in the primary session,
so a turn in a side chat streams nothing live and the finished wait
text is sent as the reply instead, so the client always gets the
complete answer. Correlation is by order: everything before our
turn's message.user event is history replayed when the subscription
opened and is dropped. With stream=true and "listen_only": true the
shim opens the subscription without sending, so a turn started
elsewhere can be observed live; each message.user event restarts the
correlation.

Model addressing: the model names a Muse and, optionally, a
conversation inside it: "<alias>" for that Muse's main chat,
"<alias>/<uuid>" for one conversation, "<alias>/main" for the main
chat spelled out. There is no default model: at startup the shim
learns the attached Muse's name from the gadget service (one
{"op": "identity"} line on the socket, answered by patch_identity.py
with GET /identity) and serves it as its model. SHIM_MODEL_ALIASES
adds further names for the same Muse and is the fallback when
discovery fails; with neither the shim refuses to start. The
conversation in the model wins over the X-Session-Id header (or the
session_id/user body field); with a bare model the header wins, and
with neither the turn goes to the main chat. Unknown aliases get a
404 model_not_found; a conversation part that is neither "main" nor
a UUID gets a 400. For the main chat the socket request omits
session_id, which the service routes to the main chat, so no
main-chat id is configured anywhere.

Reply protocol: for a non-streaming call the shim asks the service to
wait for the answer (the upstream wait path: the service opens the
/chat/subscribe subscription before sending and returns the finished
reply text in "reply", capped at SHIM_REPLY_WAIT_S seconds and at the
service limit of 600). No file drop is involved. On a wait that yields
no text the shim falls back to the receipt payload. Clients opt out
per request with "wait_reply": false. The reply drop is kept only as
the streaming fallback when the wait send is rejected (the service
refuses a second concurrent wait on the same session): the shim then
sends without the wait field, appends a note to the forwarded prompt
asking the agent to write its reply to
/workspace/replies/<correlation-id>.txt on this device (the gadget
file.write command), then waits up to SHIM_REPLY_WAIT_S seconds for
that file when the subscription yields no assistant text (upstream
issues #87 and #121: subscribe replies sometimes arrive empty).

Auth: when SHIM_API_KEYS is set (comma-separated), /v1/* requires an
"Authorization: Bearer <key>" header matching one of the keys; other
requests get a 403. /healthz stays open. With no keys configured the
shim is open, for trusted networks only.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import socket
import sys
import threading
import time
import uuid
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Literal

SOCKET_PATH = os.environ.get("MUSEGADGET_SOCKET", "/run/musegadget/musegadget.sock")
PORT = int(os.environ.get("SHIM_PORT", "8001"))
TIMEOUT_S = int(os.environ.get("SHIM_TIMEOUT_S", "1800"))
MODEL_ALIASES = [
    a.strip() for a in os.environ.get("SHIM_MODEL_ALIASES", "").split(",") if a.strip()
]
DISCOVERY_WAIT_S = int(os.environ.get("SHIM_DISCOVERY_WAIT_S", "60"))
DISCOVERY_POLL_S = 2.0
REPLIES_DIR = os.environ.get("SHIM_REPLIES_DIR", "/workspace/replies")
REPLY_WAIT_S = int(os.environ.get("SHIM_REPLY_WAIT_S", "600"))
MAX_WAIT_S = 600  # upstream service limit for the "wait" socket field
REPLY_POLL_S = 2.0
API_KEYS = [k.strip() for k in os.environ.get("SHIM_API_KEYS", "").split(",") if k.strip()]


def authorized(headers: Any) -> bool:
    if not API_KEYS:
        return True
    auth = headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return False
    token = auth[len("Bearer ") :]
    return any(secrets.compare_digest(token, key) for key in API_KEYS)


def log(msg: str) -> None:
    print(f"[shim {time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def sanitize_session_id(raw: str) -> str:
    sid = re.sub(r"[^A-Za-z0-9-]", "-", raw).strip("-")
    return sid[:64] or "pi-main"


_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


class ModelRoute:
    """A resolved model address: which Muse, which conversation.

    session_id None means the Muse main chat: the socket request
    omits session_id and the service routes the turn to the main chat.
    A plain class, not a dataclass: the test loader runs this module
    without registering it in sys.modules, where a dataclass would
    fail resolving the annotations.
    """

    def __init__(self, alias: str, session_id: str | None) -> None:
        self.alias = alias
        self.session_id = session_id

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ModelRoute):
            return NotImplemented
        return self.alias == other.alias and self.session_id == other.session_id

    def __repr__(self) -> str:
        return f"ModelRoute(alias={self.alias!r}, session_id={self.session_id!r})"


class ModelAddressError(ValueError):
    """A model string that is not a valid address, with its HTTP status."""

    def __init__(self, message: str, status: int, code: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code


def resolve_model(model: str, session_source: str | None) -> ModelRoute:
    """Resolve a model address to a Muse alias and a conversation.

    "<alias>" names that Muse; "<alias>/<uuid>" names a conversation
    inside it; "<alias>/main" is the explicit main chat. The
    conversation in the model wins over the session source (the
    X-Session-Id header, session_id or user body field); with a bare
    model the session source wins, and with neither the turn goes to
    the main chat.
    """
    name, sep, conversation = model.strip().partition("/")
    if name not in MODEL_ALIASES:
        raise ModelAddressError(f"The model `{model}` does not exist", 404, "model_not_found")
    alias = name
    if not sep:
        session_id = sanitize_session_id(session_source) if session_source else None
        return ModelRoute(alias, session_id)
    if conversation == "main":
        return ModelRoute(alias, None)
    if _UUID_RE.fullmatch(conversation):
        return ModelRoute(alias, str(uuid.UUID(conversation)))
    raise ModelAddressError(
        f"Invalid model `{model}`: expected <alias> or <alias>/<uuid> or <alias>/main",
        400,
        "invalid_model",
    )


def model_list() -> list[dict[str, Any]]:
    """The models this shim serves: the discovered name plus configured aliases."""
    return [
        {"id": alias, "object": "model", "created": 0, "owned_by": "musegadget-shim"}
        for alias in MODEL_ALIASES
    ]


def message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(p for p in parts if p)
    return "" if content is None else str(content)


def build_prompt(messages: list[Any]) -> str:
    lines = []
    for m in messages:
        if not isinstance(m, dict):
            continue
        role = str(m.get("role", "user"))
        text = message_text(m.get("content"))
        if text:
            lines.append(f"{role}: {text}")
    return "\n\n".join(lines)


def extract_text(node: Any, depth: int = 0) -> str:
    """Best-effort extraction of assistant text from a /chat/stream reply."""
    if depth > 8:
        return ""
    if isinstance(node, str):
        stripped = node.strip()
        if stripped.startswith(("{", "[")):
            try:
                return extract_text(json.loads(stripped), depth + 1)
            except ValueError:
                return node
        return node
    if isinstance(node, dict):
        choices = node.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                msg = first.get("message") or {}
                if isinstance(msg, dict) and isinstance(msg.get("content"), str):
                    return str(msg["content"])
                if isinstance(first.get("text"), str):
                    return str(first["text"])
        for key in ("text", "content", "message", "response", "result"):
            value = node.get(key)
            if isinstance(value, str) and value.strip():
                return value
            if isinstance(value, (dict, list)):
                found = extract_text(value, depth + 1)
                if found:
                    return found
        return ""
    if isinstance(node, list):
        parts = [extract_text(item, depth + 1) for item in node]
        return "".join(p for p in parts if p)
    return ""


def ask_muse(prompt: str, session_id: str | None, wait_s: int | None = None) -> dict[str, Any]:
    """Send one turn; with wait_s the service waits for the reply text.

    The service answers a "wait" request with the finished reply in
    "reply" (None when no answer came, "partial" when the wait ran out
    mid-answer). Without it the answer is the delivery receipt only.
    With session_id None the turn goes to the Muse main chat: the
    service routes a request without session_id to the main chat.
    """
    payload: dict[str, Any] = {"message": prompt}
    if session_id is not None:
        payload["session_id"] = session_id
    if wait_s is not None:
        payload["wait"] = wait_s
    return _socket_line(json.dumps(payload).encode() + b"\n")


def _socket_line(request: bytes) -> dict[str, Any]:
    """Send one JSON line on the socket and return the one-line reply."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(TIMEOUT_S)
        sock.connect(SOCKET_PATH)
        sock.sendall(request)
        buf = bytearray()
        while not buf.endswith(b"\n"):
            chunk = sock.recv(65536)
            if not chunk:
                break
            buf += chunk
    reply: dict[str, Any] = json.loads(bytes(buf))
    return reply


def _query_identity_once() -> tuple[str | None, str | None]:
    """One identity query: (name, None) on success, (None, reason) on failure.

    One {"op": "identity"} line on the socket; the service
    (patch_identity.py) answers with the GET /identity payload.
    """
    try:
        reply = _socket_line(json.dumps({"op": "identity"}).encode() + b"\n")
    except (OSError, ValueError) as exc:
        return None, f"{type(exc).__name__}: {exc}"
    if not isinstance(reply, dict) or not reply.get("ok"):
        error = reply.get("error") if isinstance(reply, dict) else "bad reply"
        return None, str(error)
    identity = reply.get("identity")
    name = identity.get("name") if isinstance(identity, dict) else None
    if not isinstance(name, str) or not name.strip():
        return None, "no name in identity"
    return name.strip(), None


def discover_muse_name() -> str | None:
    """Learn the attached Muse's name, retrying until the deadline.

    At startup the service may not be registered yet, so a failed
    query is retried every DISCOVERY_POLL_S seconds for up to
    DISCOVERY_WAIT_S seconds. Returns None when the service never
    answers with a name.
    """
    deadline = time.monotonic() + DISCOVERY_WAIT_S
    reason: str | None = None
    while True:
        name, reason = _query_identity_once()
        if name is not None:
            return name
        if time.monotonic() >= deadline:
            log(f"identity discovery failed after {DISCOVERY_WAIT_S}s: {reason}")
            return None
        time.sleep(DISCOVERY_POLL_S)


def _iter_socket(
    request: bytes,
    ready: threading.Event | None = None,
    stop: threading.Event | None = None,
) -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield ("event", dict) lines then one ("result", dict) from the socket.

    With ready given, the event is set once the request is on the wire,
    so a sender waiting for the subscription can start. With stop
    given, the socket is polled and the iterator ends promptly once
    stop is set, instead of waiting for the service to close the
    subscription.
    """
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5 if stop is not None else TIMEOUT_S)
        sock.connect(SOCKET_PATH)
        sock.sendall(request)
        if ready is not None:
            ready.set()
        buf = bytearray()
        while True:
            try:
                chunk = sock.recv(65536)
            except TimeoutError:
                if stop is None:
                    raise
                if stop.is_set():
                    return
                continue
            if not chunk:
                return
            buf += chunk
            while b"\n" in buf:
                line, _, rest = bytes(buf).partition(b"\n")
                buf = bytearray(rest)
                if not line.strip():
                    continue
                obj = json.loads(line)
                if isinstance(obj, dict) and isinstance(obj.get("event"), dict):
                    yield "event", obj["event"]
                else:
                    yield "result", obj
                    return


def iter_muse_stream(prompt: str, session_id: str | None) -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield ("event", dict) lines then one ("result", dict) from the socket.

    Asks the gadget service for the streaming turn (patch_subscribe.py);
    a service without that patch ignores the flag and yields just the
    result line, the pre-streaming behaviour. With session_id None the
    turn goes to the Muse main chat.
    """
    request_body: dict[str, Any] = {"message": prompt, "subscribe": True}
    if session_id is not None:
        request_body["session_id"] = session_id
    request = json.dumps(request_body).encode() + b"\n"
    yield from _iter_socket(request)


def iter_muse_listen(
    session_id: str | None,
    ready: threading.Event | None = None,
    stop: threading.Event | None = None,
) -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield ("event", dict) lines then one ("result", dict) from the socket.

    Same socket protocol as iter_muse_stream, but the request carries
    "listen": true and no message, so the service forwards the session's
    subscription events without sending anything. With session_id None
    the subscription follows the Muse main chat. ready and stop are
    the hybrid streaming hooks, passed through to _iter_socket.
    """
    request_body: dict[str, Any] = {"subscribe": True, "listen": True}
    if session_id is not None:
        request_body["session_id"] = session_id
    request = json.dumps(request_body).encode() + b"\n"
    yield from _iter_socket(request, ready=ready, stop=stop)


class StreamTranslator:
    """Turns subscribe events into SSE delta texts.

    Live events nest their text under payload; top-level text is
    accepted too. Correlation is by order: nothing is emitted before our turn's
    message.user event (earlier events are history replayed when the
    subscription opened). The Linux server's delta events do not share
    one stable message id, so no id gating is applied: deltas are
    emitted in arrival order. agent.status and task.status are
    dropped by design: Pi shows its own working indicator.
    """

    def __init__(self, follow: bool = False) -> None:
        self.follow = follow
        self.started = False
        self.accumulated = ""
        self.done_text = ""
        self.finished = False

    def feed(self, event: dict[str, Any]) -> str:
        """Return the text to emit as one SSE delta, or "" for none."""
        name = str(event.get("event") or "")
        raw_payload = event.get("payload")
        payload: dict[str, Any] = raw_payload if isinstance(raw_payload, dict) else {}
        text = str(
            event.get("text")
            or payload.get("text")
            or payload.get("display_text")
            or payload.get("content")
            or ""
        )
        if name == "message.user":
            if self.follow:
                self.accumulated = ""
                self.done_text = ""
                self.finished = False
            self.started = True
            return ""
        if not self.started:
            return ""
        if name == "delta.message_start":
            return ""
        if name not in ("delta.text_append", "delta.message_done", "message.assistant"):
            return ""
        if name == "delta.text_append":
            self.accumulated += text
            return text
        self.finished = True
        if name == "delta.message_done":
            self.done_text = text
        if not self.accumulated and text:
            self.accumulated = text
            return text
        return ""


def prepare_replies_dir() -> None:
    """Create the reply drop dir, writable by the gadget command account."""
    try:
        os.makedirs(REPLIES_DIR, exist_ok=True)
        os.chmod(REPLIES_DIR, 0o777)
        cutoff = time.time() - 3600
        for name in os.listdir(REPLIES_DIR):
            path = os.path.join(REPLIES_DIR, name)
            if name.endswith(".txt") and os.path.getmtime(path) < cutoff:
                os.unlink(path)
    except OSError as exc:
        log(f"replies dir not usable ({exc}); reply waiting disabled")
        globals()["REPLY_WAIT_S"] = 0


def reply_footer(cid: str) -> str:
    return (
        "\n\n[limen] This message arrives through the limen OpenAI shim, which is "
        "waiting to complete the API call with your reply. As the last step of "
        f"your answer, write your complete reply text, verbatim, to the file "
        f"{REPLIES_DIR}/{cid}.txt on this device (the gadget file.write command, "
        "absolute path). Write only the reply text, not this note. If you cannot "
        "write files on this device, ignore this note."
    )


def wait_for_reply(cid: str, deadline_s: int) -> str:
    """Poll the reply drop dir until the agent deposits the reply text."""
    path = os.path.join(REPLIES_DIR, f"{cid}.txt")
    deadline = time.monotonic() + deadline_s
    while time.monotonic() < deadline:
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read().strip()
            os.unlink(path)
            if text:
                return text
        except OSError:
            pass
        time.sleep(REPLY_POLL_S)
    return ""


def completion_object(model: str, content: str) -> dict[str, Any]:
    return {
        "id": f"chatcmpl-gadget-{int(time.time())}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: Any) -> None:  # keep stderr logs ours only
        pass

    def _send_json(self, status: int, obj: dict[str, Any]) -> None:
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    @staticmethod
    def _drain(
        items: Iterator[tuple[str, dict[str, Any]]],
        translator: StreamTranslator,
        send_delta: Any,
        state: dict[str, Any],
        started: float,
    ) -> tuple[dict[str, Any] | None, OSError | ValueError | None]:
        """Forward subscribe events as SSE deltas; return (result, error)."""
        result: dict[str, Any] | None = None
        try:
            for kind, obj in items:
                if kind == "result":
                    result = obj
                    break
                if obj.get("event") == "delta.text_append":
                    state["appends"] += 1
                else:
                    log(f"stream event {obj.get('event')}")
                delta = translator.feed(obj)
                if delta:
                    send_delta(delta)
        except (OSError, ValueError) as exc:
            log(f"stream failed after {time.monotonic() - started:.1f}s: {exc}")
            return result, exc
        return result, None

    def _stream_hybrid(
        self,
        prompt: str,
        session_id: str | None,
        translator: StreamTranslator,
        send_delta: Any,
        state: dict[str, Any],
        started: float,
    ) -> Literal["done", "answered", "fallback"]:
        """Best-effort streaming: wait send plus live deltas.

        Sends the turn once with the upstream wait field in a worker
        thread while the main thread drains a subscribe-only connection
        for live deltas. "done" means the reply was reconciled and the
        caller closes the stream; "answered" means a 502 was already
        sent; "fallback" means the wait send was rejected, so the
        caller falls back to the legacy drop path.
        """
        ready = threading.Event()
        stop = threading.Event()
        slot: dict[str, Any] = {}

        def send_with_wait() -> None:
            while not ready.wait(timeout=0.5):
                if stop.is_set():
                    return
            try:
                slot["reply"] = ask_muse(prompt, session_id, min(REPLY_WAIT_S, MAX_WAIT_S))
            except (OSError, ValueError) as exc:
                slot["error"] = exc
            finally:
                stop.set()

        sender = threading.Thread(target=send_with_wait, daemon=True)
        sender.start()
        try:
            _, error = self._drain(
                iter_muse_listen(session_id, ready=ready, stop=stop),
                translator,
                send_delta,
                state,
                started,
            )
        finally:
            stop.set()
        sender.join()
        reply = slot.get("reply")
        if reply is not None and reply.get("ok"):
            waited = reply.get("reply")
            if translator.accumulated:
                if isinstance(waited, str) and waited.strip() and waited != translator.accumulated:
                    log(
                        f"stream wait text differs: deltas_chars={len(translator.accumulated)} "
                        f"wait_chars={len(waited)}"
                    )
                return "done"
            content = ""
            if isinstance(waited, str) and waited.strip():
                content = waited
                if reply.get("partial"):
                    log(
                        f"wait reply partial after {time.monotonic() - started:.1f}s: {reply.get('detail')}"
                    )
                else:
                    log(f"wait reply after {time.monotonic() - started:.1f}s")
            else:
                log(f"wait returned no reply: {reply.get('detail')}")
            if not content:
                content = extract_text(reply.get("response"))
            if content:
                translator.accumulated = content
                send_delta(content)
            return "done"
        if reply is not None:
            log(
                f"stream wait rejected ({reply.get('error') or reply.get('status')}); "
                "falling back to the drop path"
            )
            return "fallback"
        if error is not None and not state["headers"]:
            self._send_json(502, {"error": {"message": f"musegadget unreachable: {error}"}})
            return "answered"
        if not state["headers"]:
            detail = slot.get("error") or "send failed"
            self._send_json(502, {"error": {"message": f"musegadget unreachable: {detail}"}})
            return "answered"
        return "done"

    def _stream_response(
        self,
        prompt: str,
        forwarded: str,
        session_id: str | None,
        model: str,
        cid: str,
        wait: bool,
        started: float,
        listen: bool = False,
    ) -> None:
        """Answer a stream=true request with SSE chunks.

        Best effort: the turn is sent once with the upstream wait field
        while the subscription is drained for live deltas. Deltas stream
        as they arrive; when none arrive the finished wait text is sent
        as the reply instead. The reply drop stays only as the fallback
        when the wait send is rejected.
        """
        comp_id = f"chatcmpl-gadget-{int(time.time())}"
        created = int(time.time())
        translator = StreamTranslator(follow=listen)
        state = {"headers": False, "sent": False, "appends": 0}

        def send_headers() -> None:
            if state["headers"]:
                return
            state["headers"] = True
            self.close_connection = True
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("Connection", "close")
            self.end_headers()

        def send_chunk(delta: dict[str, Any], finish: str | None) -> None:
            send_headers()
            chunk = {
                "id": comp_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
            }
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            self.wfile.flush()

        def send_delta(text: str) -> None:
            delta: dict[str, Any] = {"content": text}
            if not state["sent"]:
                delta = {"role": "assistant", "content": text}
            state["sent"] = True
            send_chunk(delta, None)

        def fail_turn(result: dict[str, Any]) -> bool:
            """502 for a failed turn before any chunk; True when answered."""
            if result.get("ok"):
                return False
            log(f"stream turn not ok: {result.get('error') or result.get('status')}")
            if not state["headers"]:
                self._send_json(
                    502,
                    {"error": {"message": f"Muse turn failed: {result.get('error') or result}"}},
                )
                return True
            return False

        def finish() -> None:
            if translator.done_text and translator.done_text != translator.accumulated:
                log(
                    f"stream done text differs: deltas_chars={len(translator.accumulated)} "
                    f"done_chars={len(translator.done_text)}"
                )
            send_chunk({}, "stop")
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            log(
                f"stream ok in {time.monotonic() - started:.1f}s "
                f"appends={state['appends']} response_chars={len(translator.accumulated)}"
            )

        if listen:
            result, error = self._drain(
                iter_muse_listen(session_id), translator, send_delta, state, started
            )
            if error is not None and not state["headers"]:
                self._send_json(502, {"error": {"message": f"musegadget unreachable: {error}"}})
                return
            if result is not None and fail_turn(result):
                return
            finish()
            return

        if wait:
            outcome = self._stream_hybrid(
                prompt, session_id, translator, send_delta, state, started
            )
            if outcome == "done":
                finish()
                return
            if outcome == "answered":
                return
            # Fallback: the wait send was rejected; use the legacy drop path.
            translator = StreamTranslator()
            state["appends"] = 0

        result, error = self._drain(
            iter_muse_stream(forwarded, session_id), translator, send_delta, state, started
        )
        if error is not None and not state["headers"]:
            self._send_json(502, {"error": {"message": f"musegadget unreachable: {error}"}})
            return
        if result is not None and fail_turn(result):
            return
        if not translator.accumulated:
            content = ""
            if wait:
                content = wait_for_reply(cid, REPLY_WAIT_S)
                if content:
                    log(
                        f"stream fell back to the reply drop after "
                        f"{time.monotonic() - started:.1f}s"
                    )
            if not content and result is not None:
                content = extract_text(result.get("response"))
            if content:
                translator.accumulated = content
                send_delta(content)
        finish()

    def _deny(self) -> None:
        self._send_json(
            403,
            {
                "error": {
                    "message": "invalid api key",
                    "type": "invalid_request_error",
                    "code": "invalid_api_key",
                }
            },
        )

    def do_GET(self) -> None:
        if self.path == "/v1/models":
            if not authorized(self.headers):
                self._deny()
                return
            self._send_json(200, {"object": "list", "data": model_list()})
        elif self.path == "/healthz":
            ok = os.path.exists(SOCKET_PATH)
            self._send_json(200 if ok else 503, {"ok": ok, "socket": SOCKET_PATH})
        else:
            self._send_json(404, {"error": {"message": "not found"}})

    def do_POST(self) -> None:
        if self.path != "/v1/chat/completions":
            self._send_json(404, {"error": {"message": "not found"}})
            return
        if not authorized(self.headers):
            self._deny()
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            self._send_json(400, {"error": {"message": "invalid JSON body"}})
            return

        listen_only = body.get("listen_only") is True
        if listen_only and not body.get("stream"):
            self._send_json(400, {"error": {"message": "listen_only requires stream"}})
            return
        messages = body.get("messages") or []
        prompt = build_prompt(messages)
        if not prompt and not listen_only:
            self._send_json(400, {"error": {"message": "no message content"}})
            return
        model = str(body.get("model") or "").strip()
        if not model:
            self._send_json(400, {"error": {"message": "no model specified"}})
            return
        session_source = (
            body.get("session_id") or body.get("user") or self.headers.get("X-Session-Id")
        )
        try:
            route = resolve_model(model, str(session_source) if session_source else None)
        except ModelAddressError as exc:
            self._send_json(
                exc.status,
                {
                    "error": {
                        "message": str(exc),
                        "type": "invalid_request_error",
                        "param": "model",
                        "code": exc.code,
                    }
                },
            )
            return
        session_id = route.session_id
        cid = uuid.uuid4().hex
        wait = False if listen_only else REPLY_WAIT_S > 0 and body.get("wait_reply") is not False
        forwarded = prompt + reply_footer(cid) if wait else prompt

        started = time.monotonic()
        log(
            f"chat model={model} session={session_id or 'main'} "
            f"prompt_chars={len(prompt)} wait={wait}"
        )
        if body.get("stream"):
            self._stream_response(
                prompt, forwarded, session_id, model, cid, wait, started, listen_only
            )
            return
        try:
            if wait:
                reply = ask_muse(prompt, session_id, min(REPLY_WAIT_S, MAX_WAIT_S))
            else:
                reply = ask_muse(forwarded, session_id)
        except (OSError, ValueError) as exc:
            log(f"chat failed after {time.monotonic() - started:.1f}s: {exc}")
            self._send_json(502, {"error": {"message": f"musegadget unreachable: {exc}"}})
            return
        elapsed = time.monotonic() - started

        if not reply.get("ok"):
            log(f"chat not ok after {elapsed:.1f}s: {reply.get('error') or reply.get('status')}")
            self._send_json(
                502,
                {"error": {"message": f"Muse turn failed: {reply.get('error') or reply}"}},
            )
            return

        content = ""
        if wait:
            waited = reply.get("reply")
            if isinstance(waited, str) and waited.strip():
                content = waited
                if reply.get("partial"):
                    log(
                        f"wait reply partial after {time.monotonic() - started:.1f}s: {reply.get('detail')}"
                    )
                else:
                    log(f"wait reply after {time.monotonic() - started:.1f}s")
            else:
                log(f"wait returned no reply: {reply.get('detail')}")
        if not content:
            content = extract_text(reply.get("response"))
        if not content:
            content = json.dumps(reply.get("response"))[:8000]
        log(f"chat ok in {elapsed:.1f}s response_chars={len(content)}")

        result = completion_object(model, content)
        self._send_json(200, result)


def main() -> None:
    discovered = discover_muse_name()
    if discovered is not None:
        if discovered not in MODEL_ALIASES:
            MODEL_ALIASES.insert(0, discovered)
        log(f"discovered Muse model `{discovered}`")
    if not MODEL_ALIASES:
        raise SystemExit(
            "no Muse model found: identity discovery failed and SHIM_MODEL_ALIASES is not set"
        )
    prepare_replies_dir()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    log(f"listening on :{PORT}, socket={SOCKET_PATH}, timeout={TIMEOUT_S}s")
    if API_KEYS:
        log(f"api key auth enabled ({len(API_KEYS)} key(s))")
    server.serve_forever()


if __name__ == "__main__":
    main()
