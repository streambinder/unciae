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


@pytest.fixture(autouse=True)
def configured_aliases(monkeypatch):
    monkeypatch.setattr(shim, "MODEL_ALIASES", ["tiro"])


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


# model addressing


def test_resolve_model_default_id_is_unknown():
    with pytest.raises(shim.ModelAddressError) as exc:
        shim.resolve_model("limen", None)
    assert exc.value.status == 404
    assert exc.value.code == "model_not_found"


def test_resolve_model_bare_alias_uses_header_session():
    assert shim.resolve_model("tiro", "sess-9") == shim.ModelRoute("tiro", "sess-9")


def test_resolve_model_bare_alias_without_header_is_main():
    assert shim.resolve_model("tiro", None) == shim.ModelRoute("tiro", None)


def test_resolve_model_slash_uuid_wins_over_header():
    route = shim.resolve_model("tiro/12345678-1234-1234-1234-1234567890AB", "sess-9")
    assert route == shim.ModelRoute("tiro", "12345678-1234-1234-1234-1234567890ab")


def test_resolve_model_slash_main_is_main_even_with_header():
    assert shim.resolve_model("tiro/main", "sess-9") == shim.ModelRoute("tiro", None)


def test_resolve_model_unknown_alias_is_404():
    with pytest.raises(shim.ModelAddressError) as exc:
        shim.resolve_model("nope", None)
    assert exc.value.status == 404
    assert exc.value.code == "model_not_found"


def test_resolve_model_bad_conversation_is_400():
    for bad in (
        "tiro/not-a-uuid",
        "tiro/",
        "tiro/12345678-1234-1234-1234-1234567890ab/extra",
        "tiro/12345678",
    ):
        with pytest.raises(shim.ModelAddressError) as exc:
            shim.resolve_model(bad, None)
        assert exc.value.status == 400
        assert exc.value.code == "invalid_model"


def test_resolve_model_header_is_sanitized():
    assert shim.resolve_model("tiro", "My Session!") == shim.ModelRoute("tiro", "My-Session")


def test_model_route_equality_and_repr():
    route = shim.ModelRoute("tiro", None)
    assert route == shim.ModelRoute("tiro", None)
    assert route != shim.ModelRoute("tiro", "sess-9")
    assert route != "tiro"
    assert repr(route) == "ModelRoute(alias='tiro', session_id=None)"


def test_model_list_lists_configured_aliases(monkeypatch):
    monkeypatch.setattr(shim, "MODEL_ALIASES", ["tiro", "other"])
    assert [m["id"] for m in shim.model_list()] == ["tiro", "other"]
    monkeypatch.setattr(shim, "MODEL_ALIASES", ["tiro"])
    assert [m["id"] for m in shim.model_list()] == ["tiro"]


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


def test_translator_emits_deltas_with_unshared_message_ids():
    # Regression: the Linux server's delta events do not share one
    # message id across message_start, appends and done; gating on it
    # dropped every live delta.
    translator = shim.StreamTranslator()
    translator.feed(event("message.user", "note-1"))
    translator.feed(event("delta.message_start", "start-id"))
    assert translator.feed(event("delta.text_append", "append-id", "ab")) == "ab"
    assert translator.feed(event("delta.text_append", "other-id", "cd")) == "cd"
    assert translator.feed(event("delta.message_done", "done-id", "abcd")) == ""
    assert translator.accumulated == "abcd"
    assert translator.finished
    assert translator.done_text == "abcd"


def nested_event(name, mid="", text="", key="text"):
    # Live subscribe events nest their text under payload.
    return {"event": name, "message_id": mid, "payload": {key: text}}


def test_translator_reads_text_from_payload():
    translator = shim.StreamTranslator()
    translator.feed(event("message.user", "note-1"))
    assert translator.feed(nested_event("delta.text_append", "a1", "ab")) == "ab"
    assert translator.feed(nested_event("delta.text_append", "a2", "cd")) == "cd"
    assert translator.feed(nested_event("delta.message_done", "a3", "abcd", "display_text")) == ""
    assert translator.accumulated == "abcd"


def test_translator_nested_done_text_used_when_no_deltas():
    translator = shim.StreamTranslator()
    translator.feed(event("message.user", "note-1"))
    assert (
        translator.feed(nested_event("delta.message_done", "a1", "full text", "display_text"))
        == "full text"
    )
    assert translator.finished
    assert translator.done_text == "full text"


def test_translator_done_text_used_when_no_deltas():
    translator = shim.StreamTranslator()
    translator.feed(event("message.user", "note-1"))
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


def test_ask_muse_sends_wait_field(monkeypatch, tmp_path):
    received = []
    path = _unix_server(tmp_path, [b'{"ok": true, "reply": "hi"}\n'], received)
    monkeypatch.setattr(shim, "SOCKET_PATH", path)
    reply = shim.ask_muse("prompt text", "sess-1", 120)
    assert reply == {"ok": True, "reply": "hi"}
    sent = json.loads(received[0])
    assert sent == {"message": "prompt text", "session_id": "sess-1", "wait": 120}


def test_ask_muse_omits_session_id_for_main(monkeypatch, tmp_path):
    received = []
    path = _unix_server(tmp_path, [b'{"ok": true, "response": "hi"}\n'], received)
    monkeypatch.setattr(shim, "SOCKET_PATH", path)
    assert shim.ask_muse("prompt text", None) == {"ok": True, "response": "hi"}
    assert json.loads(received[0]) == {"message": "prompt text"}


def test_ask_muse_omits_session_id_for_main_with_wait(monkeypatch, tmp_path):
    received = []
    path = _unix_server(tmp_path, [b'{"ok": true, "reply": "hi"}\n'], received)
    monkeypatch.setattr(shim, "SOCKET_PATH", path)
    shim.ask_muse("prompt text", None, 120)
    assert json.loads(received[0]) == {"message": "prompt text", "wait": 120}


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


def test_iter_socket_sets_ready_and_stops_on_event(monkeypatch, tmp_path):
    # The hybrid hooks: ready is set once the request is on the wire,
    # and the iterator ends promptly once stop is set instead of
    # waiting for the service to close the subscription.
    path = str(tmp_path / "gadget.sock")
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(path)
    server.listen(1)

    def serve():
        conn, _ = server.accept()
        with conn:
            conn.recv(65536)
            conn.sendall(json.dumps({"event": event("agent.status")}).encode() + b"\n")
            time.sleep(5)
        server.close()

    threading.Thread(target=serve, daemon=True).start()
    monkeypatch.setattr(shim, "SOCKET_PATH", path)
    ready = threading.Event()
    stop = threading.Event()
    items = shim._iter_socket(b'{"session_id": "s"}\n', ready=ready, stop=stop)
    first = next(items)
    assert first == ("event", event("agent.status"))
    assert ready.is_set()
    stop.set()
    started = time.monotonic()
    assert list(items) == []
    assert time.monotonic() - started < 2


def test_iter_muse_stream_omits_session_id_for_main(monkeypatch, tmp_path):
    lines = [json.dumps({"ok": True}).encode() + b"\n"]
    received = []
    path = _unix_server(tmp_path, lines, received)
    monkeypatch.setattr(shim, "SOCKET_PATH", path)
    assert list(shim.iter_muse_stream("p", None)) == [("result", {"ok": True})]
    assert json.loads(received[0]) == {"message": "p", "subscribe": True}


def test_translator_follow_mode_restarts_on_each_user_event():
    translator = shim.StreamTranslator(follow=True)
    assert translator.feed(event("message.user", "n0")) == ""
    assert translator.feed(event("delta.text_append", "a0", "old")) == "old"
    assert translator.feed(event("delta.message_done", "a0", "old")) == ""
    assert translator.feed(event("message.user", "n1")) == ""
    assert translator.feed(event("delta.text_append", "a1", "new")) == "new"


def test_iter_muse_listen_sends_listen_request(monkeypatch, tmp_path):
    lines = [
        json.dumps({"event": event("message.user", "n1")}).encode() + b"\n",
        json.dumps({"ok": True}).encode() + b"\n",
    ]
    received = []
    path = _unix_server(tmp_path, lines, received)
    monkeypatch.setattr(shim, "SOCKET_PATH", path)
    results = list(shim.iter_muse_listen("s"))
    assert [kind for kind, _ in results] == ["event", "result"]
    assert json.loads(received[0]) == {"session_id": "s", "subscribe": True, "listen": True}


def test_iter_muse_listen_omits_session_id_for_main(monkeypatch, tmp_path):
    lines = [json.dumps({"ok": True}).encode() + b"\n"]
    received = []
    path = _unix_server(tmp_path, lines, received)
    monkeypatch.setattr(shim, "SOCKET_PATH", path)
    assert list(shim.iter_muse_listen(None)) == [("result", {"ok": True})]
    assert json.loads(received[0]) == {"subscribe": True, "listen": True}


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
    assert [m["id"] for m in _json_body(raw)["data"]] == ["tiro"]


def test_get_models_lists_configured_aliases(server, monkeypatch):
    monkeypatch.setattr(shim, "API_KEYS", [])
    monkeypatch.setattr(shim, "MODEL_ALIASES", ["tiro", "other"])
    status, _, raw = _request(server, "GET", "/v1/models")
    assert status == 200
    assert [m["id"] for m in _json_body(raw)["data"]] == ["tiro", "other"]


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

    def fake_ask(prompt, session_id, wait_s=None):
        calls.append((prompt, session_id, wait_s))
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
            "model": "tiro",
        },
        headers={"X-Session-Id": "My Session!"},
    )
    assert status == 200
    body = _json_body(raw)
    assert body["model"] == "tiro"
    assert body["choices"][0]["message"]["content"] == "plain answer"
    assert calls == [("user: hi", "My-Session", None)]


def test_post_completion_uses_wait_reply_text(server, monkeypatch):
    # Non-streaming takes the reply from the service wait path: no
    # footer in the prompt and no reply drop involved.
    monkeypatch.setattr(shim, "API_KEYS", [])
    monkeypatch.setattr(shim, "REPLY_WAIT_S", 30)
    calls = _patch_ask(
        monkeypatch, reply={"ok": True, "reply": "waited text", "response": "receipt"}
    )
    monkeypatch.setattr(
        shim,
        "wait_for_reply",
        lambda cid, deadline: (_ for _ in ()).throw(AssertionError("no drop on wait path")),
    )
    status, _, raw = _request(
        server,
        "POST",
        "/v1/chat/completions",
        body={"messages": [{"role": "user", "content": "hi"}], "model": "tiro", "user": "bob"},
    )
    assert status == 200
    assert _json_body(raw)["choices"][0]["message"]["content"] == "waited text"
    prompt, session_id, wait_s = calls[0]
    assert session_id == "bob"
    assert "[limen]" not in prompt
    assert wait_s == 30


def test_post_completion_accepts_partial_wait_reply(server, monkeypatch):
    monkeypatch.setattr(shim, "API_KEYS", [])
    monkeypatch.setattr(shim, "REPLY_WAIT_S", 30)
    _patch_ask(
        monkeypatch,
        reply={
            "ok": True,
            "reply": "partial text",
            "partial": True,
            "detail": "no answer within 30 seconds",
            "response": "receipt",
        },
    )
    status, _, raw = _request(
        server,
        "POST",
        "/v1/chat/completions",
        body={"messages": [{"role": "user", "content": "hi"}], "model": "tiro"},
    )
    assert status == 200
    assert _json_body(raw)["choices"][0]["message"]["content"] == "partial text"


def test_post_completion_falls_back_when_wait_empty(server, monkeypatch):
    monkeypatch.setattr(shim, "API_KEYS", [])
    monkeypatch.setattr(shim, "REPLY_WAIT_S", 30)
    _patch_ask(
        monkeypatch,
        reply={
            "ok": True,
            "reply": None,
            "detail": "no answer within 30 seconds",
            "response": {"choices": [{"message": {"content": "nested"}}]},
        },
    )
    monkeypatch.setattr(
        shim,
        "wait_for_reply",
        lambda cid, deadline: (_ for _ in ()).throw(AssertionError("no drop on wait path")),
    )
    status, _, raw = _request(
        server,
        "POST",
        "/v1/chat/completions",
        body={"messages": [{"role": "user", "content": "hi"}], "model": "tiro"},
    )
    assert status == 200
    assert _json_body(raw)["choices"][0]["message"]["content"] == "nested"


def _completion_request(server, body, headers=None):
    return _request(server, "POST", "/v1/chat/completions", body=body, headers=headers)


def test_post_model_tiro_with_header_keeps_header_session(server, monkeypatch):
    monkeypatch.setattr(shim, "API_KEYS", [])
    monkeypatch.setattr(shim, "REPLY_WAIT_S", 30)
    calls = _patch_ask(monkeypatch, reply={"ok": True, "reply": "text", "response": "r"})
    status, _, raw = _completion_request(
        server,
        {"messages": [{"role": "user", "content": "hi"}], "model": "tiro"},
        headers={"X-Session-Id": "sess-9"},
    )
    assert status == 200
    assert _json_body(raw)["model"] == "tiro"
    assert calls == [("user: hi", "sess-9", 30)]


def test_post_model_slash_uuid_wins_over_header(server, monkeypatch):
    monkeypatch.setattr(shim, "API_KEYS", [])
    monkeypatch.setattr(shim, "REPLY_WAIT_S", 30)
    calls = _patch_ask(monkeypatch, reply={"ok": True, "reply": "text", "response": "r"})
    status, _, _ = _completion_request(
        server,
        {
            "messages": [{"role": "user", "content": "hi"}],
            "model": "tiro/12345678-1234-1234-1234-1234567890ab",
        },
        headers={"X-Session-Id": "sess-9"},
    )
    assert status == 200
    assert calls == [("user: hi", "12345678-1234-1234-1234-1234567890ab", 30)]


def test_post_bare_model_without_header_goes_to_main(server, monkeypatch):
    monkeypatch.setattr(shim, "API_KEYS", [])
    monkeypatch.setattr(shim, "REPLY_WAIT_S", 30)
    calls = _patch_ask(monkeypatch, reply={"ok": True, "reply": "text", "response": "r"})
    status, _, _ = _completion_request(
        server, {"messages": [{"role": "user", "content": "hi"}], "model": "tiro"}
    )
    assert status == 200
    assert calls == [("user: hi", None, 30)]


def test_post_missing_model_is_400(server, monkeypatch):
    monkeypatch.setattr(shim, "API_KEYS", [])
    status, _, raw = _completion_request(server, {"messages": [{"role": "user", "content": "hi"}]})
    assert status == 400
    assert "no model specified" in _json_body(raw)["error"]["message"]


def test_post_unknown_model_is_404(server, monkeypatch):
    monkeypatch.setattr(shim, "API_KEYS", [])
    calls = _patch_ask(monkeypatch, reply={"ok": True, "reply": "text"})
    status, _, raw = _completion_request(
        server, {"messages": [{"role": "user", "content": "hi"}], "model": "nope"}
    )
    assert status == 404
    assert _json_body(raw)["error"]["code"] == "model_not_found"
    assert calls == []


def test_post_bad_model_conversation_is_400(server, monkeypatch):
    monkeypatch.setattr(shim, "API_KEYS", [])
    calls = _patch_ask(monkeypatch, reply={"ok": True, "reply": "text"})
    status, _, raw = _completion_request(
        server, {"messages": [{"role": "user", "content": "hi"}], "model": "tiro/not-a-uuid"}
    )
    assert status == 400
    assert _json_body(raw)["error"]["code"] == "invalid_model"
    assert calls == []


def test_post_completion_unextractable_response_is_json_dumped(server, monkeypatch):
    monkeypatch.setattr(shim, "API_KEYS", [])
    _patch_ask(monkeypatch, reply={"ok": True, "response": None})
    status, _, raw = _request(
        server,
        "POST",
        "/v1/chat/completions",
        body={
            "messages": [{"role": "user", "content": "hi"}],
            "model": "tiro",
            "wait_reply": False,
        },
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
        body={"messages": [{"role": "user", "content": "hi"}], "model": "tiro"},
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
        body={"messages": [{"role": "user", "content": "hi"}], "model": "tiro"},
    )
    assert status == 502
    assert "bad turn" in _json_body(raw)["error"]["message"]


def _patch_stream(monkeypatch, items=None, error=None):
    calls = []

    def fake_iter(prompt, session_id):
        calls.append((prompt, session_id))
        if error is not None:
            raise error
        yield from items or []

    monkeypatch.setattr(shim, "iter_muse_stream", fake_iter)
    return calls


def _stream_request(server, **extra):
    body = {"messages": [{"role": "user", "content": "hi"}], "stream": True, "model": "tiro"}
    body.update(extra)
    return _request(server, "POST", "/v1/chat/completions", body=body)


def test_stream_completion_emits_sse_deltas(server, monkeypatch):
    # Hybrid: deltas stream live from the subscription and the finished
    # wait text is the closing confirmation only, never re-emitted.
    monkeypatch.setattr(shim, "API_KEYS", [])
    monkeypatch.setattr(shim, "REPLY_WAIT_S", 30)
    calls = _patch_ask(monkeypatch, reply={"ok": True, "reply": "World", "response": "receipt"})
    _patch_listen_hybrid(
        monkeypatch,
        items=[
            ("event", event("message.user", "n1")),
            ("event", event("delta.text_append", "a1", "Wor")),
            ("event", event("delta.text_append", "a1", "ld")),
            ("event", event("delta.message_done", "a1", "World")),
        ],
    )
    monkeypatch.setattr(
        shim,
        "wait_for_reply",
        lambda cid, deadline: (_ for _ in ()).throw(AssertionError("no drop on hybrid path")),
    )
    status, content_type, raw = _stream_request(server)
    assert status == 200
    assert content_type == "text/event-stream"
    text = raw.decode()
    assert '"content": "Wor"' in text
    assert '"content": "ld"' in text
    assert '"content": "World"' not in text
    assert '"finish_reason": "stop"' in text
    assert "data: [DONE]" in text
    prompt, session_id, wait_s = calls[0]
    assert session_id is None  # no model, no session source: main chat
    assert "[limen]" not in prompt
    assert wait_s == 30


def test_stream_hybrid_emits_wait_text_when_no_deltas(server, monkeypatch):
    # No live deltas (side chat): the finished wait text is the reply.
    monkeypatch.setattr(shim, "API_KEYS", [])
    monkeypatch.setattr(shim, "REPLY_WAIT_S", 30)
    calls = _patch_ask(
        monkeypatch, reply={"ok": True, "reply": "waited full text", "response": "receipt"}
    )
    _patch_listen_hybrid(monkeypatch, items=[("event", event("message.user", "n1"))])
    monkeypatch.setattr(
        shim,
        "wait_for_reply",
        lambda cid, deadline: (_ for _ in ()).throw(AssertionError("no drop on hybrid path")),
    )
    status, _, raw = _stream_request(server)
    assert status == 200
    text = raw.decode()
    assert '"content": "waited full text"' in text
    assert '"finish_reason": "stop"' in text
    assert "data: [DONE]" in text
    prompt, session_id, wait_s = calls[0]
    assert session_id is None  # no model, no session source: main chat
    assert "[limen]" not in prompt
    assert wait_s == 30


def test_stream_hybrid_accepts_partial_wait_reply(server, monkeypatch):
    monkeypatch.setattr(shim, "API_KEYS", [])
    monkeypatch.setattr(shim, "REPLY_WAIT_S", 30)
    _patch_ask(
        monkeypatch,
        reply={
            "ok": True,
            "reply": "partial text",
            "partial": True,
            "detail": "no answer within 30 seconds",
            "response": "receipt",
        },
    )
    _patch_listen_hybrid(monkeypatch, items=[("event", event("message.user", "n1"))])
    monkeypatch.setattr(
        shim,
        "wait_for_reply",
        lambda cid, deadline: (_ for _ in ()).throw(AssertionError("no drop on hybrid path")),
    )
    status, _, raw = _stream_request(server)
    assert status == 200
    assert '"content": "partial text"' in raw.decode()


def test_stream_result_failure_before_headers_is_502(server, monkeypatch):
    # The wait send is rejected, so the legacy path runs and its
    # failing result still answers 502 before any chunk.
    monkeypatch.setattr(shim, "API_KEYS", [])
    monkeypatch.setattr(shim, "REPLY_WAIT_S", 30)
    _patch_ask(monkeypatch, reply={"ok": False, "error": "wait rejected"})
    _patch_listen_hybrid(monkeypatch, items=[("event", event("message.user", "n1"))])
    _patch_stream(monkeypatch, items=[("result", {"ok": False, "error": "nope"})])
    status, _, raw = _stream_request(server)
    assert status == 502
    assert "nope" in _json_body(raw)["error"]["message"]


def test_stream_hybrid_wait_text_differs_keeps_streamed_text(server, monkeypatch):
    # Deltas streamed "abc" but the finished wait text says something
    # else: the streamed text stands, the wait text is not re-emitted.
    monkeypatch.setattr(shim, "API_KEYS", [])
    monkeypatch.setattr(shim, "REPLY_WAIT_S", 30)
    _patch_ask(monkeypatch, reply={"ok": True, "reply": "different", "response": "receipt"})
    _patch_listen_hybrid(
        monkeypatch,
        items=[
            ("event", event("message.user", "n1")),
            ("event", event("delta.text_append", "a1", "abc")),
            ("event", event("delta.message_done", "a1", "abc")),
        ],
    )
    status, _, raw = _stream_request(server)
    assert status == 200
    text = raw.decode()
    assert '"content": "abc"' in text
    assert '"content": "different"' not in text
    assert "data: [DONE]" in text


def test_stream_hybrid_empty_wait_falls_back_to_receipt(server, monkeypatch):
    # The wait yields no text: the receipt payload is the reply.
    monkeypatch.setattr(shim, "API_KEYS", [])
    monkeypatch.setattr(shim, "REPLY_WAIT_S", 30)
    _patch_ask(
        monkeypatch,
        reply={
            "ok": True,
            "reply": None,
            "detail": "no answer within 30 seconds",
            "response": "receipt text",
        },
    )
    _patch_listen_hybrid(monkeypatch, items=[("event", event("message.user", "n1"))])
    status, _, raw = _stream_request(server)
    assert status == 200
    assert '"content": "receipt text"' in raw.decode()


def test_stream_hybrid_send_failure_after_deltas_finishes(server, monkeypatch):
    # Deltas streamed but the wait send failed: the stream still
    # finishes with what streamed instead of failing the request.
    monkeypatch.setattr(shim, "API_KEYS", [])
    monkeypatch.setattr(shim, "REPLY_WAIT_S", 30)
    calls = _patch_ask(monkeypatch, error=OSError("down"))
    _patch_listen_hybrid(
        monkeypatch,
        items=[
            ("event", event("message.user", "n1")),
            ("event", event("delta.text_append", "a1", "abc")),
            ("event", event("delta.message_done", "a1", "abc")),
        ],
    )
    status, _, raw = _stream_request(server)
    assert status == 200
    text = raw.decode()
    assert '"content": "abc"' in text
    assert "data: [DONE]" in text
    assert len(calls) == 1


def test_stream_hybrid_subscription_never_opens_is_502(server, monkeypatch):
    # The subscription never opens, so the sender gives up without
    # sending and the request fails instead of hanging.
    monkeypatch.setattr(shim, "API_KEYS", [])
    monkeypatch.setattr(shim, "REPLY_WAIT_S", 30)
    calls = _patch_ask(monkeypatch, reply={"ok": True, "reply": "never sent"})
    _patch_listen_hybrid(monkeypatch, items=[], set_ready=False)
    status, _, raw = _stream_request(server)
    assert status == 502
    assert "unreachable" in _json_body(raw)["error"]["message"]
    assert calls == []


def test_stream_socket_failure_before_headers_is_502(server, monkeypatch):
    monkeypatch.setattr(shim, "API_KEYS", [])
    monkeypatch.setattr(shim, "REPLY_WAIT_S", 30)
    _patch_ask(monkeypatch, error=OSError("down"))
    _patch_listen_hybrid(monkeypatch, error=OSError("down"))
    status, _, raw = _stream_request(server)
    assert status == 502
    assert "unreachable" in _json_body(raw)["error"]["message"]


def test_stream_falls_back_to_reply_drop(server, monkeypatch):
    # The wait send is rejected (concurrent wait on the same session),
    # so the legacy path runs: send without wait, subscription, drop.
    monkeypatch.setattr(shim, "API_KEYS", [])
    monkeypatch.setattr(shim, "REPLY_WAIT_S", 30)
    calls = _patch_ask(monkeypatch, reply={"ok": False, "error": "wait locked"})
    _patch_listen_hybrid(monkeypatch, items=[("event", event("message.user", "n1"))])
    stream_calls = _patch_stream(
        monkeypatch,
        items=[("event", event("message.user", "n1")), ("result", {"ok": True})],
    )
    monkeypatch.setattr(shim, "wait_for_reply", lambda cid, deadline: "fallback text")
    status, _, raw = _stream_request(server)
    assert status == 200
    assert '"content": "fallback text"' in raw.decode()
    prompt, session_id, wait_s = calls[0]
    assert session_id is None  # no model, no session source: main chat
    assert "[limen]" not in prompt
    assert wait_s == 30
    assert "[limen]" in stream_calls[0][0]


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
    monkeypatch.setattr(shim, "REPLY_WAIT_S", 30)
    _patch_ask(monkeypatch, reply={"ok": True, "reply": "abc", "response": "receipt"})
    _patch_listen_hybrid(
        monkeypatch,
        items=[
            ("event", event("message.user", "n1")),
            ("event", event("delta.text_append", "a1", "abc")),
            ("event", event("delta.message_done", "a1", "abX")),
        ],
    )
    monkeypatch.setattr(
        shim,
        "wait_for_reply",
        lambda cid, deadline: (_ for _ in ()).throw(AssertionError("no drop on hybrid path")),
    )
    status, _, raw = _stream_request(server)
    assert status == 200
    assert '"content": "abc"' in raw.decode()


def test_stream_failure_after_headers_still_finishes(server, monkeypatch):
    # The wait send is rejected, so the legacy path runs; its late
    # result failure still finishes the stream with what streamed.
    monkeypatch.setattr(shim, "API_KEYS", [])
    monkeypatch.setattr(shim, "REPLY_WAIT_S", 30)
    _patch_ask(monkeypatch, reply={"ok": False, "error": "wait rejected"})
    _patch_listen_hybrid(monkeypatch, items=[("event", event("message.user", "n1"))])
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


def test_stream_uses_resolved_session_from_model(server, monkeypatch):
    monkeypatch.setattr(shim, "API_KEYS", [])
    seen = []

    def fake_iter(prompt, session_id):
        seen.append((prompt, session_id))
        yield ("event", event("message.user", "n1"))
        yield ("event", event("delta.text_append", "a1", "hi"))
        yield ("result", {"ok": True})

    monkeypatch.setattr(shim, "iter_muse_stream", fake_iter)
    status, _, raw = _stream_request(
        server,
        wait_reply=False,
        model="tiro/12345678-1234-1234-1234-1234567890ab",
    )
    assert status == 200
    assert seen == [("user: hi", "12345678-1234-1234-1234-1234567890ab")]
    assert '"content": "hi"' in raw.decode()


def _patch_listen(monkeypatch, items=None, error=None):
    def fake_listen(session_id):
        if error is not None:
            raise error
        yield from items or []

    monkeypatch.setattr(shim, "iter_muse_listen", fake_listen)


def _patch_listen_hybrid(monkeypatch, items=None, error=None, set_ready=True):
    """Fake iter_muse_listen for the hybrid path: sets ready, yields items.

    The fake models events that arrived before the wait completed, so
    it yields every scripted item without checking stop. With
    set_ready False the subscription never opens, so the sender waits
    and gives up once the drain ends.
    """

    def fake_listen(session_id, ready=None, stop=None):
        if set_ready and ready is not None:
            ready.set()
        if error is not None:
            raise error
        yield from items or []

    monkeypatch.setattr(shim, "iter_muse_listen", fake_listen)


def test_stream_legacy_socket_failure_is_502(server, monkeypatch):
    # wait_reply False skips the hybrid; the legacy socket failure is a 502.
    monkeypatch.setattr(shim, "API_KEYS", [])
    _patch_stream(monkeypatch, error=OSError("down"))
    status, _, raw = _stream_request(server, wait_reply=False)
    assert status == 502
    assert "unreachable" in _json_body(raw)["error"]["message"]


def test_stream_listen_socket_failure_is_502(server, monkeypatch):
    monkeypatch.setattr(shim, "API_KEYS", [])
    _patch_listen(monkeypatch, error=OSError("down"))
    status, _, raw = _request(
        server,
        "POST",
        "/v1/chat/completions",
        body={"stream": True, "listen_only": True, "model": "tiro", "session_id": "sess-1"},
    )
    assert status == 502
    assert "unreachable" in _json_body(raw)["error"]["message"]


def test_stream_listen_result_failure_is_502(server, monkeypatch):
    monkeypatch.setattr(shim, "API_KEYS", [])
    _patch_listen(monkeypatch, items=[("result", {"ok": False, "error": "nope"})])
    status, _, raw = _request(
        server,
        "POST",
        "/v1/chat/completions",
        body={"stream": True, "listen_only": True, "model": "tiro", "session_id": "sess-1"},
    )
    assert status == 502
    assert "nope" in _json_body(raw)["error"]["message"]


def test_stream_listen_only_observes_live_turn_without_drop(server, monkeypatch):
    monkeypatch.setattr(shim, "API_KEYS", [])
    monkeypatch.setattr(
        shim,
        "wait_for_reply",
        lambda cid, deadline: (_ for _ in ()).throw(AssertionError("no drop in listen mode")),
    )
    _patch_listen(
        monkeypatch,
        items=[
            ("event", event("message.user", "n0")),
            ("event", event("delta.text_append", "a0", "old")),
            ("event", event("message.user", "n1")),
            ("event", event("delta.text_append", "a1", "live")),
            ("event", event("delta.message_done", "a1", "live")),
            ("result", {"ok": True}),
        ],
    )
    status, _, raw = _request(
        server,
        "POST",
        "/v1/chat/completions",
        body={"stream": True, "listen_only": True, "model": "tiro", "session_id": "sess-1"},
    )
    assert status == 200
    text = raw.decode()
    assert '"content": "live"' in text
    assert "data: [DONE]" in text


def test_stream_response_disables_proxy_buffering(server, monkeypatch):
    monkeypatch.setattr(shim, "API_KEYS", [])
    _patch_listen(
        monkeypatch,
        items=[
            ("event", event("message.user", "n1")),
            ("event", event("delta.text_append", "a1", "live")),
            ("event", event("delta.message_done", "a1", "live")),
            ("result", {"ok": True}),
        ],
    )
    conn = http.client.HTTPConnection("127.0.0.1", server, timeout=10)
    conn.request(
        "POST",
        "/v1/chat/completions",
        body=json.dumps(
            {"stream": True, "listen_only": True, "model": "tiro", "session_id": "sess-1"}
        ),
        headers={"Content-Type": "application/json"},
    )
    response = conn.getresponse()
    assert response.getheader("X-Accel-Buffering") == "no"
    raw = response.read()
    conn.close()
    assert response.status == 200
    assert '"content": "live"' in raw.decode()


def test_listen_only_without_stream_is_400(server, monkeypatch):
    monkeypatch.setattr(shim, "API_KEYS", [])
    status, _, raw = _request(server, "POST", "/v1/chat/completions", body={"listen_only": True})
    assert status == 400
    assert "listen_only requires stream" in raw.decode()


def test_main_starts_server(monkeypatch, tmp_path):
    monkeypatch.setattr(shim, "REPLIES_DIR", str(tmp_path))
    monkeypatch.setattr(shim, "API_KEYS", ["k1"])
    monkeypatch.setattr(shim, "discover_muse_name", lambda: None)
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


def test_main_refuses_start_without_aliases(monkeypatch):
    monkeypatch.setattr(shim, "MODEL_ALIASES", [])
    monkeypatch.setattr(shim, "discover_muse_name", lambda: None)
    with pytest.raises(SystemExit, match="SHIM_MODEL_ALIASES"):
        shim.main()


def _patch_socket(monkeypatch, replies):
    """Answer AF_UNIX sockets with `replies` in order (bytes or Exception)."""
    real_socket = socket.socket
    queue = list(replies)
    sent: list[bytes] = []

    class FakeSocket:
        def __init__(self):
            item = queue.pop(0) if queue else b""
            if isinstance(item, Exception):
                raise item
            self._reply = item

        def settimeout(self, timeout):
            pass

        def connect(self, path):
            pass

        def sendall(self, data):
            sent.append(data)

        def recv(self, size):
            reply, self._reply = self._reply, b""
            return reply

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def factory(family, *args, **kwargs):
        if family == socket.AF_UNIX:
            return FakeSocket()
        return real_socket(family, *args, **kwargs)

    monkeypatch.setattr(socket, "socket", factory)
    return sent


def test_query_identity_once_returns_name(monkeypatch):
    sent = _patch_socket(monkeypatch, [b'{"ok": true, "identity": {"name": "Tiro"}}\n'])
    assert shim._query_identity_once() == ("Tiro", None)
    assert sent == [b'{"op": "identity"}\n']


def test_query_identity_once_returns_none_when_not_connected(monkeypatch):
    _patch_socket(monkeypatch, [b'{"ok": false, "error": "not connected to the Muse"}\n'])
    assert shim._query_identity_once() == (None, "not connected to the Muse")


def test_query_identity_once_returns_none_on_unparseable_reply(monkeypatch):
    _patch_socket(monkeypatch, [b"not json\n"])
    name, reason = shim._query_identity_once()
    assert name is None
    assert "JSONDecodeError" in reason


def test_query_identity_once_returns_none_on_socket_error(monkeypatch):
    _patch_socket(monkeypatch, [FileNotFoundError("no socket")])
    name, reason = shim._query_identity_once()
    assert name is None
    assert "FileNotFoundError" in reason


def test_discover_muse_name_retries_then_succeeds(monkeypatch):
    calls = []

    def fake_query():
        calls.append(1)
        return ("Tiro", None) if len(calls) == 3 else (None, "not connected")

    monkeypatch.setattr(shim, "_query_identity_once", fake_query)
    monkeypatch.setattr(shim, "DISCOVERY_POLL_S", 0)
    assert shim.discover_muse_name() == "Tiro"
    assert len(calls) == 3


def test_discover_muse_name_returns_none_after_deadline(monkeypatch):
    monkeypatch.setattr(shim, "_query_identity_once", lambda: (None, "down"))
    monkeypatch.setattr(shim, "DISCOVERY_WAIT_S", 0)
    assert shim.discover_muse_name() is None


def _fake_main_server(monkeypatch):
    """Stub the HTTP server and the replies dir so main() returns."""
    monkeypatch.setattr(shim, "prepare_replies_dir", lambda: None)

    class FakeServer:
        def __init__(self, address, handler):
            pass

        def serve_forever(self):
            return None

    monkeypatch.setattr(shim, "ThreadingHTTPServer", FakeServer)


def test_main_registers_discovered_name_first(monkeypatch):
    monkeypatch.setattr(shim, "MODEL_ALIASES", ["other"])
    monkeypatch.setattr(shim, "discover_muse_name", lambda: "Tiro")
    _fake_main_server(monkeypatch)
    shim.main()
    assert shim.MODEL_ALIASES == ["Tiro", "other"]


def test_main_does_not_duplicate_discovered_name(monkeypatch):
    monkeypatch.setattr(shim, "MODEL_ALIASES", ["Tiro"])
    monkeypatch.setattr(shim, "discover_muse_name", lambda: "Tiro")
    _fake_main_server(monkeypatch)
    shim.main()
    assert shim.MODEL_ALIASES == ["Tiro"]


def test_main_falls_back_to_env_aliases_when_discovery_fails(monkeypatch):
    monkeypatch.setattr(shim, "MODEL_ALIASES", ["tiro"])
    monkeypatch.setattr(shim, "discover_muse_name", lambda: None)
    _fake_main_server(monkeypatch)
    shim.main()
    assert shim.MODEL_ALIASES == ["tiro"]
