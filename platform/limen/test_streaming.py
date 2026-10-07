"""Tests for the limen streaming prototype.

Shim-side tests run anywhere. SDK-side tests need the pinned upstream
sources: set MUSEGADGET_SDK_SRC to the extracted SDK tree (the directory
holding linux/src/musegadget) and they apply patch_subscribe.py to a
scratch copy before importing the patched modules.
"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

LIMEN = Path(__file__).resolve().parent


def load_shim():
    spec = importlib.util.spec_from_file_location("limen_shim", LIMEN / "shim.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


shim = load_shim()


def event(name, mid="", text="", reply_to=""):
    return {"event": name, "message_id": mid, "reply_to": reply_to, "text": text, "seq": None}


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
    from musegadget import link_client

    return link_client


def test_parse_chat_event_flattens_payload(patched_sdk):
    row = json.dumps(
        {
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
    ).encode()
    parsed = patched_sdk.parse_chat_event(row)
    assert parsed["event"] == "delta.message_done"
    assert parsed["text"] == "shown"
    assert parsed["reply_to"] == ""
    assert parsed["seq"] == 7
    assert patched_sdk.parse_chat_event(b'{"type": "ack"}') is None
    assert patched_sdk.parse_chat_event(b"not json") is None


def test_subscription_splits_ndjson_across_frames_and_dedupes(patched_sdk):
    events = []
    subscription = patched_sdk._Subscription(1, events.append)

    def row(seq, text):
        return json.dumps(
            {"type": "event", "seq": seq, "payload": {"event": "delta.text_append", "text": text}}
        ).encode()

    first = row(1, "Wor") + b"\n" + row(2, "ld")[:10]
    rest = row(2, "ld")[10:] + b"\n" + row(2, "ld") + b"\n"
    subscription.on_frame(
        SimpleNamespace(
            kind="response", value=SimpleNamespace(status=200, body=first, end_body=False)
        )
    )
    subscription.on_frame(
        SimpleNamespace(kind="body_chunk", value=SimpleNamespace(data=rest, end_body=False))
    )
    assert [e["text"] for e in events] == ["Wor", "ld"]


def test_reply_tracker_matches_by_order_not_reply_to(patched_sdk):
    tracker = patched_sdk.ReplyTracker()
    history = {"event": "message.assistant", "message_id": "old", "reply_to": "", "text": "x"}
    assert not tracker.feed(history)
    tracker.set_note_id("note-1")
    assert not tracker.feed({**history, "event": "message.user", "message_id": "note-1"})
    delta = {"event": "delta.text_append", "message_id": "a1", "reply_to": "", "text": "Hi"}
    assert not tracker.feed(delta)
    assert tracker.feed({**delta, "event": "delta.message_done"})
