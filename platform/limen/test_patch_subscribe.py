"""Tests for the limen subscribe patch script.

The patcher unit tests build scratch files from the needle strings
the script itself declares. The SDK tests need the pinned upstream
sources: set MUSEGADGET_SDK_SRC to the extracted SDK tree (the
directory holding linux/src/musegadget) and they apply the patch to a
scratch copy before importing the patched modules.
"""

import glob
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

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
    link = "\n".join(needle for needle, _ in patch_subscribe.LINK_PATCHES)
    service = "\n".join(needle for needle, _ in patch_subscribe.SERVICE_PATCHES)
    (package / "link_client.py").write_text(link + "\n", encoding="utf-8")
    (package / "service.py").write_text(service + "\n", encoding="utf-8")
    return package


def test_main_patches_package_dir_from_argv(monkeypatch, tmp_path):
    package = _fake_package(tmp_path)
    monkeypatch.setattr(sys, "argv", ["patch_subscribe.py", str(package)])
    patch_subscribe.main()
    link_text = (package / "link_client.py").read_text(encoding="utf-8")
    service_text = (package / "service.py").read_text(encoding="utf-8")
    assert "def parse_chat_event" in link_text
    assert "class ReplyTracker" in link_text
    assert "SUBSCRIBE_PATH" in link_text
    assert "_local_stream_request" in service_text
    assert "STREAM_WAIT_S" in service_text


def test_main_patches_package_dir_from_glob(monkeypatch, tmp_path):
    package = _fake_package(tmp_path)
    monkeypatch.setattr(sys, "argv", ["patch_subscribe.py"])
    monkeypatch.setattr(glob, "glob", lambda pattern: [str(package)])
    patch_subscribe.main()
    assert "def parse_chat_event" in (package / "link_client.py").read_text(encoding="utf-8")


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
            {
                "type": "event",
                "seq": seq,
                "payload": {"event": "delta.text_append", "text": text},
            }
        ).encode()

    first = row(1, "Wor") + b"\n" + row(2, "ld")[:10]
    rest = row(2, "ld")[10:] + b"\n" + row(2, "ld") + b"\n"
    subscription.on_frame(
        SimpleNamespace(
            kind="response",
            value=SimpleNamespace(status=200, body=first, end_body=False),
        )
    )
    subscription.on_frame(
        SimpleNamespace(kind="body_chunk", value=SimpleNamespace(data=rest, end_body=False))
    )
    assert [e["text"] for e in events] == ["Wor", "ld"]


def test_reply_tracker_matches_by_order_not_reply_to(patched_sdk):
    tracker = patched_sdk.ReplyTracker()
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
