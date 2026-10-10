"""Unit tests for the limen OpenAI shim.

The shim module is loaded from its file path, the same way the
existing streaming tests loaded it. HTTP handler tests run a real
server on an ephemeral loopback port; the Muse socket is a real
Unix socket served by a test thread.
"""

import http.client
import importlib.util
import json
import os
import socket
import threading
import time
from pathlib import Path

import pytest

LIMEN = Path(__file__).resolve().parent


def load_shim():
    spec = importlib.util.spec_from_file_location("limen_shim", LIMEN / "shim.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


shim = load_shim()


def event(name, mid="", text="", reply_to=""):
    return {
        "event": name,
        "message_id": mid,
        "reply_to": reply_to,
        "text": text,
        "seq": None,
    }


# pure helpers


def test_authorized_without_keys_is_open(monkeypatch):
    monkeypatch.setattr(shim, "API_KEYS", [])
    assert shim.authorized({})


def test_authorized_with_keys(monkeypatch):
    monkeypatch.setattr(shim, "API_KEYS", ["k1", "k2"])

    class Headers(dict):
        def get(self, key, default=""):
            return super().get(key, default)

    assert not shim.authorized(Headers())
    assert not shim.authorized(Headers(Authorization="Token k1"))
    assert not shim.authorized(Headers(Authorization="Bearer wrong"))
    assert shim.authorized(Headers(Authorization="Bearer k2"))


def test_sanitize_session_id():
    assert shim.sanitize_session_id("abc-123") == "abc-123"
    assert shim.sanitize_session_id("My Session!") == "My-Session"
    assert shim.sanitize_session_id("!!!") == "pi-main"
    assert shim.sanitize_session_id("") == "pi-main"
    assert shim.sanitize_session_id("x" * 100) == "x" * 64
    assert shim.sanitize_session_id("--lead-trail--") == "lead-trail"


def test_message_text_variants():
    assert shim.message_text("plain") == "plain"
    content = [
        {"type": "text", "text": "one"},
        {"type": "image", "text": "ignored"},
        "two",
        {"type": "text", "text": ""},
        42,
    ]
    assert shim.message_text(content) == "one\ntwo"
    assert shim.message_text(None) == ""
    assert shim.message_text(7) == "7"


def test_build_prompt_skips_empty_and_non_dict():
    messages = [
        {"role": "system", "content": "rules"},
        {"content": "hello"},
        {"role": "user", "content": ""},
        "not-a-dict",
        {"role": "user", "content": [{"type": "text", "text": "parts"}]},
    ]
    assert shim.build_prompt(messages) == "system: rules\n\nuser: hello\n\nuser: parts"
    assert shim.build_prompt([]) == ""


def test_extract_text_variants():
    assert shim.extract_text("plain") == "plain"
    assert shim.extract_text("deep", depth=9) == ""
    assert shim.extract_text('{"text": "json hi"}') == "json hi"
    assert shim.extract_text("{broken json") == "{broken json"
    assert shim.extract_text({"choices": [{"message": {"content": "c"}}]}) == "c"
    assert shim.extract_text({"choices": [{"text": "t"}]}) == "t"
    assert shim.extract_text({"choices": [{"message": {"content": 1}}]}) == ""
    assert shim.extract_text({"choices": "nope", "text": "fallback"}) == "fallback"
    assert shim.extract_text({"text": "  ", "response": "r"}) == "r"
    assert shim.extract_text({"content": {"text": "nested"}}) == "nested"
    assert shim.extract_text({"message": "m"}) == "m"
    assert shim.extract_text({"result": ["a", {"text": "b"}]}) == "ab"
    assert shim.extract_text(["a", "b"]) == "ab"
    assert shim.extract_text(None) == ""
    assert shim.extract_text(42) == ""
    assert shim.extract_text({}) == ""


def test_completion_object_shape():
    obj = shim.completion_object("model-x", "body")
    assert obj["object"] == "chat.completion"
    assert obj["model"] == "model-x"
    choice = obj["choices"][0]
    assert choice["message"] == {"role": "assistant", "content": "body"}
    assert choice["finish_reason"] == "stop"
    assert obj["usage"]["total_tokens"] == 0


def test_reply_footer_names_drop_file(monkeypatch, tmp_path):
    monkeypatch.setattr(shim, "REPLIES_DIR", str(tmp_path))
    footer = shim.reply_footer("cid42")
    assert f"{tmp_path}/cid42.txt" in footer
    assert "limen" in footer


# stream translator (moved from test_streaming.py)


def test_translator_drops_history_before_our_user_event():
    translator = shim.StreamTranslator()
    assert translator.feed(event("delta.text_append", "old", "stale")) == ""
    assert translator.feed(event("message.assistant", "old", "stale")) == ""
    assert translator.feed(event("message.user", "note-1")) == ""
    assert translator.feed(event("agent.status")) == ""
    assert translator.feed(event("delta.text_append", "a1", "Wor")) == "Wor"
    assert translator.feed(event("delta.text_append", "a1", "ld")) == "ld"
    assert translator.accumulated == "World"


def test_translator_ignores_other_messages_and_uses_done_text_when_no_deltas():
    translator = shim.StreamTranslator()
    translator.feed(event("message.user", "note-1"))
    translator.feed(event("delta.message_start", "a1"))
    assert translator.feed(event("delta.text_append", "other", "no")) == ""
    assert translator.feed(event("delta.message_done", "a1", "full text")) == "full text"
    assert translator.finished
    assert translator.done_text == "full text"


def test_translator_done_mismatch_keeps_streamed_text():
    translator = shim.StreamTranslator()
    translator.feed(event("message.user", "note-1"))
    assert translator.feed(event("delta.text_append", "a1", "abc")) == "abc"
    assert translator.feed(event("delta.message_done", "a1", "abX")) == ""
    assert translator.accumulated == "abc"
    assert translator.done_text == "abX"


def test_translator_assistant_message_without_deltas():
    translator = shim.StreamTranslator()
    translator.feed(event("message.user", "note-1"))
    assert translator.feed(event("message.assistant", "a1", "whole")) == "whole"
    assert translator.finished


# reply drop directory


def test_prepare_replies_dir_prunes_old_files(monkeypatch, tmp_path):
    monkeypatch.setattr(shim, "REPLIES_DIR", str(tmp_path))
    old = tmp_path / "old.txt"
    old.write_text("x")
    past = time.time() - 7200
    os.utime(old, (past, past))
    fresh = tmp_path / "fresh.txt"
    fresh.write_text("x")
    other = tmp_path / "old.bin"
    other.write_text("x")
    os.utime(other, (past, past))
    shim.prepare_replies_dir()
    assert not old.exists()
    assert fresh.exists()
    assert other.exists()


def test_prepare_replies_dir_failure_disables_waiting(monkeypatch, tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("not a dir")
    monkeypatch.setattr(shim, "REPLIES_DIR", str(blocker / "sub"))
    shim.prepare_replies_dir()
    assert shim.REPLY_WAIT_S == 0


def test_wait_for_reply_returns_deposited_text(monkeypatch, tmp_path):
    monkeypatch.setattr(shim, "REPLIES_DIR", str(tmp_path))
    (tmp_path / "cid.txt").write_text("  answer \n")
    assert shim.wait_for_reply("cid", 5) == "answer"
    assert not (tmp_path / "cid.txt").exists()


def test_wait_for_reply_polls_until_file_appears(monkeypatch, tmp_path):
    monkeypatch.setattr(shim, "REPLIES_DIR", str(tmp_path))
    monkeypatch.setattr(shim, "REPLY_POLL_S", 0.01)

    def deposit():
        time.sleep(0.05)
        (tmp_path / "cid.txt").write_text("late")

    threading.Thread(target=deposit).start()
    assert shim.wait_for_reply("cid", 5) == "late"


def test_wait_for_reply_timeout_and_empty_file(monkeypatch, tmp_path):
    monkeypatch.setattr(shim, "REPLIES_DIR", str(tmp_path))
    monkeypatch.setattr(shim, "REPLY_POLL_S", 0.01)
    assert shim.wait_for_reply("absent", 0) == ""
    (tmp_path / "empty.txt").write_text("   ")
    assert shim.wait_for_reply("empty", 0.1) == ""


# gadget socket protocol


def _unix_server(tmp_path, chunks, received):
    path = str(tmp_path / "gadget.sock")
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(path)
    server.listen(1)

    def serve():
        conn, _ = server.accept()
        with conn:
            received.append(conn.recv(65536))
            for chunk in chunks:
                conn.sendall(chunk)
        server.close()

    threading.Thread(target=serve, daemon=True).start()
    return path


def test_ask_muse_roundtrip(monkeypatch, tmp_path):
    received = []
    path = _unix_server(tmp_path, [b'{"ok": true, "response": "hi"}\n'], received)
    monkeypatch.setattr(shim, "SOCKET_PATH", path)
    reply = shim.ask_muse("prompt text", "sess-1")
    assert reply == {"ok": True, "response": "hi"}
    sent = json.loads(received[0])
    assert sent == {"message": "prompt text", "session_id": "sess-1"}


def test_iter_muse_stream_yields_events_then_result(monkeypatch, tmp_path):
    lines = [
        b"\n",
        json.dumps({"event": event("message.user", "n1")}).encode() + b"\n",
        json.dumps({"event": event("delta.text_append", "a1", "Hi")}).encode() + b"\n",
        json.dumps({"ok": True, "response": "done"}).encode() + b"\n",
    ]
    received = []
    path = _unix_server(tmp_path, lines, received)
    monkeypatch.setattr(shim, "SOCKET_PATH", path)
    results = list(shim.iter_muse_stream("p", "s"))
    assert [kind for kind, _ in results] == ["event", "event", "result"]
    assert results[0][1]["event"] == "message.user"
    assert results[-1][1]["ok"] is True
    assert json.loads(received[0])["subscribe"] is True


def test_iter_muse_stream_ends_on_close_without_result(monkeypatch, tmp_path):
    lines = [json.dumps({"event": event("message.user", "n1")}).encode() + b"\n"]
    path = _unix_server(tmp_path, lines, [])
    monkeypatch.setattr(shim, "SOCKET_PATH", path)
    results = list(shim.iter_muse_stream("p", "s"))
    assert [kind for kind, _ in results] == ["event"]


# HTTP handler


@pytest.fixture()
def server():
    httpd = shim.ThreadingHTTPServer(("127.0.0.1", 0), shim.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd.server_address[1]
    finally:
        httpd.shutdown()
        httpd.server_close()


def _request(port, method, path, body=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    payload = body if isinstance(body, (str, bytes)) or body is None else json.dumps(body)
    conn.request(method, path, body=payload, headers=headers or {})
    response = conn.getresponse()
    raw = response.read()
    conn.close()
    return response.status, response.getheader("Content-Type"), raw


def _json_body(raw):
    return json.loads(raw)


def test_get_models_open(server, monkeypatch):
    monkeypatch.setattr(shim, "API_KEYS", [])
    status, _, raw = _request(server, "GET", "/v1/models")
    assert status == 200
    assert _json_body(raw)["data"][0]["id"] == shim.MODEL_ID


def test_get_models_auth(server, monkeypatch):
    monkeypatch.setattr(shim, "API_KEYS", ["k1", "k2"])
    status, _, raw = _request(server, "GET", "/v1/models")
    assert status == 403
    assert _json_body(raw)["error"]["code"] == "invalid_api_key"
    status, _, _ = _request(server, "GET", "/v1/models", headers={"Authorization": "Bearer wrong"})
    assert status == 403
    status, _, _ = _request(server, "GET", "/v1/models", headers={"Authorization": "Bearer k2"})
    assert status == 200


def test_healthz_reflects_socket_presence(server, monkeypatch, tmp_path):
    sock = tmp_path / "present.sock"
    sock.write_text("")
    monkeypatch.setattr(shim, "SOCKET_PATH", str(sock))
    status, _, raw = _request(server, "GET", "/healthz")
    assert status == 200
    assert _json_body(raw) == {"ok": True, "socket": str(sock)}
    monkeypatch.setattr(shim, "SOCKET_PATH", str(tmp_path / "absent.sock"))
    status, _, raw = _request(server, "GET", "/healthz")
    assert status == 503
    assert _json_body(raw)["ok"] is False


def test_unknown_paths_are_404(server):
    assert _request(server, "GET", "/nope")[0] == 404
    assert _request(server, "POST", "/nope", body={})[0] == 404


def test_post_invalid_json_is_400(server, monkeypatch):
    monkeypatch.setattr(shim, "API_KEYS", [])
    status, _, raw = _request(server, "POST", "/v1/chat/completions", body="{not json")
    assert status == 400
    assert "invalid JSON" in _json_body(raw)["error"]["message"]


def test_post_without_content_is_400(server, monkeypatch):
    monkeypatch.setattr(shim, "API_KEYS", [])
    status, _, _ = _request(server, "POST", "/v1/chat/completions", body={"messages": []})
    assert status == 400


def test_post_denied_without_key(server, monkeypatch):
    monkeypatch.setattr(shim, "API_KEYS", ["k1"])
    status, _, _ = _request(
        server, "POST", "/v1/chat/completions", body={"messages": [{"content": "hi"}]}
    )
    assert status == 403


def _patch_ask(monkeypatch, reply=None, error=None):
    calls = []

    def fake_ask(prompt, session_id):
        calls.append((prompt, session_id))
        if error is not None:
            raise error
        return reply

    monkeypatch.setattr(shim, "ask_muse", fake_ask)
    return calls


def test_post_completion_uses_response_text(server, monkeypatch):
    monkeypatch.setattr(shim, "API_KEYS", [])
    calls = _patch_ask(monkeypatch, reply={"ok": True, "response": "plain answer"})
    status, _, raw = _request(
        server,
        "POST",
        "/v1/chat/completions",
        body={
            "messages": [{"role": "user", "content": "hi"}],
            "wait_reply": False,
            "model": "custom",
        },
        headers={"X-Session-Id": "My Session!"},
    )
    assert status == 200
    body = _json_body(raw)
    assert body["model"] == "custom"
    assert body["choices"][0]["message"]["content"] == "plain answer"
    assert calls == [("user: hi", "My-Session")]


def test_post_completion_prefers_reply_drop(server, monkeypatch):
    monkeypatch.setattr(shim, "API_KEYS", [])
    monkeypatch.setattr(shim, "REPLY_WAIT_S", 30)
    calls = _patch_ask(monkeypatch, reply={"ok": True, "response": "receipt"})
    monkeypatch.setattr(shim, "wait_for_reply", lambda cid, deadline: "dropped text")
    status, _, raw = _request(
        server,
        "POST",
        "/v1/chat/completions",
        body={"messages": [{"role": "user", "content": "hi"}], "user": "bob"},
    )
    assert status == 200
    assert _json_body(raw)["choices"][0]["message"]["content"] == "dropped text"
    prompt, session_id = calls[0]
    assert session_id == "bob"
    assert "[limen]" in prompt


def test_post_completion_falls_back_when_drop_empty(server, monkeypatch):
    monkeypatch.setattr(shim, "API_KEYS", [])
    monkeypatch.setattr(shim, "REPLY_WAIT_S", 30)
    _patch_ask(
        monkeypatch,
        reply={
            "ok": True,
            "response": {"choices": [{"message": {"content": "nested"}}]},
        },
    )
    monkeypatch.setattr(shim, "wait_for_reply", lambda cid, deadline: "")
    status, _, raw = _request(
        server,
        "POST",
        "/v1/chat/completions",
        body={"messages": [{"role": "user", "content": "hi"}]},
    )
    assert status == 200
    assert _json_body(raw)["choices"][0]["message"]["content"] == "nested"


def test_post_completion_unextractable_response_is_json_dumped(server, monkeypatch):
    monkeypatch.setattr(shim, "API_KEYS", [])
    _patch_ask(monkeypatch, reply={"ok": True, "response": None})
    status, _, raw = _request(
        server,
        "POST",
        "/v1/chat/completions",
        body={"messages": [{"role": "user", "content": "hi"}], "wait_reply": False},
    )
    assert status == 200
    assert _json_body(raw)["choices"][0]["message"]["content"] == "null"


def test_post_completion_socket_failure_is_502(server, monkeypatch):
    monkeypatch.setattr(shim, "API_KEYS", [])
    _patch_ask(monkeypatch, error=OSError("no socket"))
    status, _, raw = _request(
        server,
        "POST",
        "/v1/chat/completions",
        body={"messages": [{"role": "user", "content": "hi"}]},
    )
    assert status == 502
    assert "unreachable" in _json_body(raw)["error"]["message"]


def test_post_completion_failed_turn_is_502(server, monkeypatch):
    monkeypatch.setattr(shim, "API_KEYS", [])
    _patch_ask(monkeypatch, reply={"ok": False, "error": "bad turn"})
    status, _, raw = _request(
        server,
        "POST",
        "/v1/chat/completions",
        body={"messages": [{"role": "user", "content": "hi"}]},
    )
    assert status == 502
    assert "bad turn" in _json_body(raw)["error"]["message"]


def _patch_stream(monkeypatch, items=None, error=None):
    def fake_iter(prompt, session_id):
        if error is not None:
            raise error
        yield from items or []

    monkeypatch.setattr(shim, "iter_muse_stream", fake_iter)


def _stream_request(server, **extra):
    body = {"messages": [{"role": "user", "content": "hi"}], "stream": True}
    body.update(extra)
    return _request(server, "POST", "/v1/chat/completions", body=body)


def test_stream_completion_emits_sse_deltas(server, monkeypatch):
    monkeypatch.setattr(shim, "API_KEYS", [])
    _patch_stream(
        monkeypatch,
        items=[
            ("event", event("message.user", "n1")),
            ("event", event("delta.text_append", "a1", "Wor")),
            ("event", event("delta.text_append", "a1", "ld")),
            ("event", event("delta.message_done", "a1", "World")),
            ("result", {"ok": True}),
        ],
    )
    status, content_type, raw = _stream_request(server)
    assert status == 200
    assert content_type == "text/event-stream"
    text = raw.decode()
    assert '"content": "Wor"' in text
    assert '"content": "ld"' in text
    assert '"finish_reason": "stop"' in text
    assert "data: [DONE]" in text


def test_stream_result_failure_before_headers_is_502(server, monkeypatch):
    monkeypatch.setattr(shim, "API_KEYS", [])
    _patch_stream(monkeypatch, items=[("result", {"ok": False, "error": "nope"})])
    status, _, raw = _stream_request(server)
    assert status == 502
    assert "nope" in _json_body(raw)["error"]["message"]


def test_stream_socket_failure_before_headers_is_502(server, monkeypatch):
    monkeypatch.setattr(shim, "API_KEYS", [])
    _patch_stream(monkeypatch, error=OSError("down"))
    status, _, raw = _stream_request(server)
    assert status == 502
    assert "unreachable" in _json_body(raw)["error"]["message"]


def test_stream_falls_back_to_reply_drop(server, monkeypatch):
    monkeypatch.setattr(shim, "API_KEYS", [])
    monkeypatch.setattr(shim, "REPLY_WAIT_S", 30)
    _patch_stream(
        monkeypatch,
        items=[("event", event("message.user", "n1")), ("result", {"ok": True})],
    )
    monkeypatch.setattr(shim, "wait_for_reply", lambda cid, deadline: "fallback text")
    status, _, raw = _stream_request(server)
    assert status == 200
    assert '"content": "fallback text"' in raw.decode()


def test_stream_no_drop_and_no_result_text(server, monkeypatch):
    monkeypatch.setattr(shim, "API_KEYS", [])
    _patch_stream(
        monkeypatch,
        items=[("event", event("message.user", "n1")), ("result", {"ok": True})],
    )
    status, _, raw = _stream_request(server, wait_reply=False)
    assert status == 200
    assert "data: [DONE]" in raw.decode()


def test_stream_done_text_mismatch_still_completes(server, monkeypatch):
    monkeypatch.setattr(shim, "API_KEYS", [])
    _patch_stream(
        monkeypatch,
        items=[
            ("event", event("message.user", "n1")),
            ("event", event("delta.text_append", "a1", "abc")),
            ("event", event("delta.message_done", "a1", "abX")),
            ("result", {"ok": True}),
        ],
    )
    status, _, raw = _stream_request(server)
    assert status == 200
    assert '"content": "abc"' in raw.decode()


def test_stream_failure_after_headers_still_finishes(server, monkeypatch):
    monkeypatch.setattr(shim, "API_KEYS", [])
    _patch_stream(
        monkeypatch,
        items=[
            ("event", event("message.user", "n1")),
            ("event", event("delta.text_append", "a1", "partial")),
            ("result", {"ok": False, "error": "late failure"}),
        ],
    )
    status, _, raw = _stream_request(server)
    assert status == 200
    assert '"content": "partial"' in raw.decode()
    assert "data: [DONE]" in raw.decode()


def test_stream_extracts_result_text_when_no_deltas(server, monkeypatch):
    monkeypatch.setattr(shim, "API_KEYS", [])
    _patch_stream(
        monkeypatch,
        items=[
            ("event", event("message.user", "n1")),
            ("result", {"ok": True, "response": "whole reply"}),
        ],
    )
    status, _, raw = _stream_request(server, wait_reply=False)
    assert status == 200
    assert '"content": "whole reply"' in raw.decode()


def test_main_starts_server(monkeypatch, tmp_path):
    monkeypatch.setattr(shim, "REPLIES_DIR", str(tmp_path))
    monkeypatch.setattr(shim, "API_KEYS", ["k1"])
    served = {}

    class FakeServer:
        def __init__(self, address, handler):
            served["address"] = address
            served["handler"] = handler

        def serve_forever(self):
            served["started"] = True

    monkeypatch.setattr(shim, "ThreadingHTTPServer", FakeServer)
    shim.main()
    assert served["started"] is True
    assert served["handler"] is shim.Handler
