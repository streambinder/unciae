"""Tests for the limen subscribe patch script.

The patcher unit tests build scratch files from the needle strings
the script itself declares. The SDK tests need the pinned upstream
sources: set MUSEGADGET_SDK_SRC to the extracted SDK tree (the
directory holding linux/src/musegadget) and they apply the patch to a
scratch copy before importing the patched modules.
"""

import asyncio
import glob
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import patch_subscribe
import pytest

LIMEN = Path(__file__).resolve().parent


def test_patch_file_applies_every_replacement(tmp_path):
    target = tmp_path / "mod.py"
    target.write_text("alpha\nbeta\n", encoding="utf-8")
    patch_subscribe.patch_file(str(target), [("alpha", "gamma"), ("beta", "delta")])
    assert target.read_text(encoding="utf-8") == "gamma\ndelta\n"


def test_patch_file_missing_needle_exits(tmp_path):
    target = tmp_path / "mod.py"
    target.write_text("alpha\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="expected line not found"):
        patch_subscribe.patch_file(str(target), [("absent", "x")])


def _fake_package(tmp_path):
    package = tmp_path / "musegadget"
    package.mkdir()
    service = "\n".join(needle for needle, _ in patch_subscribe.SERVICE_PATCHES)
    (package / "service.py").write_text(service + "\n", encoding="utf-8")
    return package


def test_main_patches_package_dir_from_argv(monkeypatch, tmp_path):
    package = _fake_package(tmp_path)
    monkeypatch.setattr(sys, "argv", ["patch_subscribe.py", str(package)])
    patch_subscribe.main()
    service_text = (package / "service.py").read_text(encoding="utf-8")
    assert "def _flatten_chat_event" in service_text
    assert "class _ReplyTracker" in service_text
    assert "_local_stream_request" in service_text
    assert "subscribe_chat" in service_text
    assert "STREAM_WAIT_S" in service_text


def test_main_patches_package_dir_from_glob(monkeypatch, tmp_path):
    package = _fake_package(tmp_path)
    monkeypatch.setattr(sys, "argv", ["patch_subscribe.py"])
    monkeypatch.setattr(glob, "glob", lambda pattern: [str(package)])
    patch_subscribe.main()
    assert "_local_stream_request" in (package / "service.py").read_text(encoding="utf-8")


@pytest.mark.parametrize("found", [[], ["one", "two"]])
def test_main_rejects_ambiguous_package_dir(monkeypatch, found):
    monkeypatch.setattr(sys, "argv", ["patch_subscribe.py"])
    monkeypatch.setattr(glob, "glob", lambda pattern: found)
    with pytest.raises(SystemExit, match="not found uniquely"):
        patch_subscribe.main()


# upstream SDK tests (moved from test_streaming.py)


SDK_SRC = os.environ.get("MUSEGADGET_SDK_SRC")


@pytest.fixture(scope="module")
def patched_sdk(tmp_path_factory):
    if not SDK_SRC:
        pytest.skip("MUSEGADGET_SDK_SRC not set; SDK patch tests skipped")
    root = tmp_path_factory.mktemp("sdk")
    package = root / "musegadget"
    shutil.copytree(Path(SDK_SRC) / "linux" / "src" / "musegadget", package)
    subprocess.run(
        [sys.executable, str(LIMEN / "patch_subscribe.py"), str(package)],
        check=True,
        capture_output=True,
        text=True,
    )
    sys.path.insert(0, str(root))
    from musegadget import service

    return service


def test_flatten_chat_event_flattens_payload(patched_sdk):
    row = {
        "type": "event",
        "seq": 7,
        "payload": {
            "event": "delta.message_done",
            "message_id": "m1",
            "reply_to_message_id": "",
            "parent_message_id": "m1",
            "display_text": "shown",
            "content": "raw",
        },
    }
    parsed = patched_sdk._flatten_chat_event(row)
    assert parsed["event"] == "delta.message_done"
    assert parsed["text"] == "shown"
    assert parsed["reply_to"] == ""
    assert parsed["seq"] == 7
    assert patched_sdk._flatten_chat_event({"type": "ack"}) is None


def test_reply_tracker_matches_by_order_not_reply_to(patched_sdk):
    tracker = patched_sdk._ReplyTracker()
    history = {
        "event": "message.assistant",
        "message_id": "old",
        "reply_to": "",
        "text": "x",
    }
    assert not tracker.feed(history)
    tracker.set_note_id("note-1")
    assert not tracker.feed({**history, "event": "message.user", "message_id": "note-1"})
    delta = {
        "event": "delta.text_append",
        "message_id": "a1",
        "reply_to": "",
        "text": "Hi",
    }
    assert not tracker.feed(delta)
    assert tracker.feed({**delta, "event": "delta.message_done"})


class _FakeWriter:
    def __init__(self):
        self.lines = []

    def write(self, data):
        self.lines.append(data)

    async def drain(self):
        pass


class _FakeSession:
    registered_at = 1.0

    def __init__(self):
        self.sent = None

    async def subscribe_chat(self, session_id=None):
        def row(seq, payload):
            return {"type": "event", "seq": seq, "payload": payload}

        # History replay first, then this turn's events, one duplicated.
        yield row(1, {"event": "message.assistant", "message_id": "old", "text": "history"})
        yield row(2, {"event": "message.user", "message_id": "note-1", "text": "hi"})
        yield row(3, {"event": "delta.text_append", "message_id": "a1", "text": "Wor"})
        yield row(3, {"event": "delta.text_append", "message_id": "a1", "text": "Wor"})
        yield row(4, {"event": "delta.text_append", "message_id": "a1", "text": "ld"})
        yield row(
            5,
            {
                "event": "delta.message_done",
                "message_id": "a1",
                "reply_to_message_id": "",
                "parent_message_id": "a1",
                "display_text": "World",
            },
        )

    async def send_chat(self, message, session_id=None):
        self.sent = (message, session_id)
        return {"ok": True, "status": 200, "response": {"message_id": "note-1"}}


def test_local_stream_request_streams_events_then_result(patched_sdk):
    svc = object.__new__(patched_sdk.Service)
    session = _FakeSession()
    svc._current = session
    writer = _FakeWriter()
    line = json.dumps({"message": "hello", "session_id": "chat-1", "subscribe": True}).encode()
    asyncio.run(svc._local_stream_request(line, writer))
    assert session.sent == ("hello", "chat-1")
    objs = [json.loads(data) for data in writer.lines]
    events = [o["event"] for o in objs if "event" in o]
    results = [o for o in objs if "event" not in o]
    # History is dropped, the duplicated seq is dropped, result is last.
    assert [e["event"] for e in events] == [
        "message.user",
        "delta.text_append",
        "delta.text_append",
        "delta.message_done",
    ]
    assert [e["text"] for e in events if e["event"] == "delta.text_append"] == ["Wor", "ld"]
    assert results == [{"ok": True, "status": 200, "response": {"message_id": "note-1"}}]
    assert objs[-1] is results[0]


def test_local_stream_request_rejects_missing_message(patched_sdk):
    svc = object.__new__(patched_sdk.Service)
    svc._current = _FakeSession()
    writer = _FakeWriter()
    asyncio.run(svc._local_stream_request(b'{"subscribe": true}', writer))
    objs = [json.loads(data) for data in writer.lines]
    assert objs == [{"ok": False, "error": 'expected {"message": "..."}'}]
    assert patched_sdk.Service._wants_subscribe(b'{"subscribe": true}')
    assert not patched_sdk.Service._wants_subscribe(b'{"message": "x"}')
    assert not patched_sdk.Service._wants_subscribe(b"not json")
