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

Streaming: with stream=true the shim asks the gadget service to open a
/chat/subscribe subscription (see patch_subscribe.py) and translates
its events into OpenAI SSE chunks as they arrive: delta.text_append
becomes a chunk, delta.message_done carries the full authoritative
text (checked against the accumulated deltas; SSE cannot retract, so
on a mismatch the streamed text stands and only the lengths are
logged), agent.status and task.status are dropped. Correlation is by
order: everything before our turn's message.user event is history
replayed when the subscription opened and is dropped; the gadget
service already buffers events until the chat ack names our note and
forwards only from that event on.

Reply protocol: the gadget chat API answers with a delivery receipt
only, never the assistant's text. To still complete the call, the shim
appends a note to the forwarded prompt asking the agent to write its
reply to /workspace/replies/<correlation-id>.txt on this device (the
gadget file.write command), then waits up to SHIM_REPLY_WAIT_S seconds
for that file and returns its content. On timeout it falls back to the
receipt payload, the pre-protocol behaviour. Clients opt out per
request with "wait_reply": false. The reply drop stays the fallback
for streaming too: when the subscription yields no assistant text
(upstream issues #87 and #121: subscribe replies sometimes arrive
empty), the shim waits for the drop before finishing the SSE stream.

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
import time
import uuid
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

SOCKET_PATH = os.environ.get("MUSEGADGET_SOCKET", "/run/musegadget/musegadget.sock")
PORT = int(os.environ.get("SHIM_PORT", "8001"))
TIMEOUT_S = int(os.environ.get("SHIM_TIMEOUT_S", "1800"))
MODEL_ID = os.environ.get("SHIM_MODEL_ID", "tiro")
REPLIES_DIR = os.environ.get("SHIM_REPLIES_DIR", "/workspace/replies")
REPLY_WAIT_S = int(os.environ.get("SHIM_REPLY_WAIT_S", "600"))
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


def ask_muse(prompt: str, session_id: str) -> dict[str, Any]:
    request = json.dumps({"message": prompt, "session_id": session_id}).encode() + b"\n"
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


def iter_muse_stream(prompt: str, session_id: str) -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield ("event", dict) lines then one ("result", dict) from the socket.

    Asks the gadget service for the streaming turn (patch_subscribe.py);
    a service without that patch ignores the flag and yields just the
    result line, the pre-streaming behaviour.
    """
    request = (
        json.dumps({"message": prompt, "session_id": session_id, "subscribe": True}).encode()
        + b"\n"
    )
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(TIMEOUT_S)
        sock.connect(SOCKET_PATH)
        sock.sendall(request)
        buf = bytearray()
        while True:
            chunk = sock.recv(65536)
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


class StreamTranslator:
    """Turns flattened subscribe events into SSE delta texts.

    Correlation is by order: nothing is emitted before our turn's
    message.user event (earlier events are history replayed when the
    subscription opened), and deltas from any message other than the
    first reply message are ignored. agent.status and task.status are
    dropped by design: Pi shows its own working indicator.
    """

    def __init__(self) -> None:
        self.started = False
        self.owner = ""
        self.accumulated = ""
        self.done_text = ""
        self.finished = False

    def feed(self, event: dict[str, Any]) -> str:
        """Return the text to emit as one SSE delta, or "" for none."""
        name = str(event.get("event") or "")
        mid = str(event.get("message_id") or "")
        text = str(event.get("text") or "")
        if name == "message.user":
            self.started = True
            return ""
        if not self.started:
            return ""
        if name == "delta.message_start":
            self.owner = self.owner or mid
            return ""
        if name not in ("delta.text_append", "delta.message_done", "message.assistant"):
            return ""
        if self.owner and mid and mid != self.owner:
            return ""
        self.owner = self.owner or mid
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

    def _stream_response(
        self, forwarded: str, session_id: str, model: str, cid: str, wait: bool, started: float
    ) -> None:
        """Answer a stream=true request with SSE chunks from /chat/subscribe."""
        comp_id = f"chatcmpl-gadget-{int(time.time())}"
        created = int(time.time())
        translator = StreamTranslator()
        state = {"headers": False, "sent": False, "appends": 0}

        def send_headers() -> None:
            if state["headers"]:
                return
            state["headers"] = True
            self.close_connection = True
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
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

        result: dict[str, Any] | None = None
        try:
            for kind, obj in iter_muse_stream(forwarded, session_id):
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
            if not state["headers"]:
                self._send_json(502, {"error": {"message": f"musegadget unreachable: {exc}"}})
                return
        if result is not None and not result.get("ok"):
            log(f"stream turn not ok: {result.get('error') or result.get('status')}")
            if not state["headers"]:
                self._send_json(
                    502,
                    {"error": {"message": f"Muse turn failed: {result.get('error') or result}"}},
                )
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
        elif translator.done_text and translator.done_text != translator.accumulated:
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
            self._send_json(
                200,
                {
                    "object": "list",
                    "data": [
                        {
                            "id": MODEL_ID,
                            "object": "model",
                            "created": 0,
                            "owned_by": "musegadget-shim",
                        }
                    ],
                },
            )
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

        messages = body.get("messages") or []
        prompt = build_prompt(messages)
        if not prompt:
            self._send_json(400, {"error": {"message": "no message content"}})
            return
        session_raw = (
            body.get("session_id")
            or body.get("user")
            or self.headers.get("X-Session-Id")
            or "pi-main"
        )
        session_id = sanitize_session_id(str(session_raw))
        model = str(body.get("model") or MODEL_ID)
        cid = uuid.uuid4().hex
        wait = REPLY_WAIT_S > 0 and body.get("wait_reply") is not False
        forwarded = prompt + reply_footer(cid) if wait else prompt

        started = time.monotonic()
        log(f"chat session={session_id} prompt_chars={len(prompt)} wait={wait}")
        if body.get("stream"):
            self._stream_response(forwarded, session_id, model, cid, wait, started)
            return
        try:
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
            content = wait_for_reply(cid, REPLY_WAIT_S)
            if content:
                log(f"reply deposited after {time.monotonic() - started:.1f}s")
            else:
                log(f"no reply deposited within {REPLY_WAIT_S}s; receipt fallback")
        if not content:
            content = extract_text(reply.get("response"))
        if not content:
            content = json.dumps(reply.get("response"))[:8000]
        log(f"chat ok in {elapsed:.1f}s response_chars={len(content)}")

        result = completion_object(model, content)
        self._send_json(200, result)


def main() -> None:
    prepare_replies_dir()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    log(f"listening on :{PORT}, socket={SOCKET_PATH}, timeout={TIMEOUT_S}s")
    if API_KEYS:
        log(f"api key auth enabled ({len(API_KEYS)} key(s))")
    server.serve_forever()


if __name__ == "__main__":
    main()
