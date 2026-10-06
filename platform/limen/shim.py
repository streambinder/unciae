#!/usr/bin/env python3
"""OpenAI-compatible shim in front of a local musegadget service.

Pi (or any OpenAI client) -> POST /v1/chat/completions -> this shim ->
one JSON line on the musegadget Unix socket -> Muse turn (side chat)
-> reply JSON line -> chat.completion JSON back to the client.

v0 notes:
- Non-streaming semantics; stream=true gets a single-chunk SSE reply.
- The conversation is flattened into a single user message per request;
  continuity lives in the Muse side chat named by session_id.
- Message contents are never logged, only lengths and timings.
"""

from __future__ import annotations

import json
import os
import re
import socket
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SOCKET_PATH = os.environ.get("MUSEGADGET_SOCKET", "/run/musegadget/musegadget.sock")
PORT = int(os.environ.get("SHIM_PORT", "8001"))
TIMEOUT_S = int(os.environ.get("SHIM_TIMEOUT_S", "1800"))
MODEL_ID = os.environ.get("SHIM_MODEL_ID", "tiro")


def log(msg: str) -> None:
    print(f"[shim {time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def sanitize_session_id(raw: str) -> str:
    sid = re.sub(r"[^A-Za-z0-9-]", "-", raw).strip("-")
    return sid[:64] or "pi-main"


def message_text(content) -> str:
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


def build_prompt(messages: list) -> str:
    lines = []
    for m in messages:
        if not isinstance(m, dict):
            continue
        role = str(m.get("role", "user"))
        text = message_text(m.get("content"))
        if text:
            lines.append(f"{role}: {text}")
    return "\n\n".join(lines)


def extract_text(node, depth: int = 0) -> str:
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
                    return msg["content"]
                if isinstance(first.get("text"), str):
                    return first["text"]
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


def ask_muse(prompt: str, session_id: str) -> dict:
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
    return json.loads(bytes(buf))


def completion_object(model: str, content: str) -> dict:
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

    def log_message(self, fmt, *args):  # keep stderr logs ours only
        pass

    def _send_json(self, status: int, obj: dict) -> None:
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/v1/models":
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

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            self._send_json(404, {"error": {"message": "not found"}})
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

        started = time.monotonic()
        log(f"chat session={session_id} prompt_chars={len(prompt)}")
        try:
            reply = ask_muse(prompt, session_id)
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

        content = extract_text(reply.get("response"))
        if not content:
            content = json.dumps(reply.get("response"))[:8000]
        log(f"chat ok in {elapsed:.1f}s response_chars={len(content)}")

        result = completion_object(model, content)
        if body.get("stream"):
            chunk = {
                "id": result["id"],
                "object": "chat.completion.chunk",
                "created": result["created"],
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant", "content": content},
                        "finish_reason": None,
                    }
                ],
            }
            final = {
                "id": result["id"],
                "object": "chat.completion.chunk",
                "created": result["created"],
                "model": model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            }
            payload = (
                f"data: {json.dumps(chunk)}\n\ndata: {json.dumps(final)}\n\ndata: [DONE]\n\n"
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        else:
            self._send_json(200, result)


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    log(f"listening on :{PORT}, socket={SOCKET_PATH}, timeout={TIMEOUT_S}s")
    server.serve_forever()


if __name__ == "__main__":
    main()
