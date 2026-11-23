"""Tests for the limen identity patch script.

The patcher unit tests build scratch files from the needle strings
the script itself declares. The SDK tests need the pinned upstream
sources: set MUSEGADGET_SDK_SRC to the extracted SDK tree (the
directory holding linux/src/musegadget) and they apply the patch to a
scratch copy before importing the patched service module under its
own name, so the musegadget package imported by other test modules
is left alone.
"""

import asyncio
import glob
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import patch_identity
import pytest

LIMEN = Path(__file__).resolve().parent


def test_patch_file_applies_every_replacement(tmp_path):
    target = tmp_path / "mod.py"
    target.write_text("alpha\nbeta\n", encoding="utf-8")
    patch_identity.patch_file(str(target), [("alpha", "gamma"), ("beta", "delta")])
    assert target.read_text(encoding="utf-8") == "gamma\ndelta\n"


def test_patch_file_missing_needle_exits(tmp_path):
    target = tmp_path / "mod.py"
    target.write_text("alpha\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="expected line not found"):
        patch_identity.patch_file(str(target), [("absent", "x")])


def _fake_package(tmp_path):
    package = tmp_path / "musegadget"
    package.mkdir()
    service = "\n".join(needle for needle, _ in patch_identity.SERVICE_PATCHES)
    (package / "service.py").write_text(service + "\n", encoding="utf-8")
    return package


def test_main_patches_package_dir_from_argv(monkeypatch, tmp_path):
    package = _fake_package(tmp_path)
    monkeypatch.setattr(sys, "argv", ["patch_identity.py", str(package)])
    patch_identity.main()
    service_text = (package / "service.py").read_text(encoding="utf-8")
    assert "def _local_identity" in service_text
    assert 'request.get("op") == "identity"' in service_text
    assert 'session.request("GET", "/identity")' in service_text


def test_main_patches_package_dir_from_glob(monkeypatch, tmp_path):
    package = _fake_package(tmp_path)
    monkeypatch.setattr(sys, "argv", ["patch_identity.py"])
    monkeypatch.setattr(glob, "glob", lambda pattern: [str(package)])
    patch_identity.main()
    assert "_local_identity" in (package / "service.py").read_text(encoding="utf-8")


@pytest.mark.parametrize("found", [[], ["one", "two"]])
def test_main_rejects_ambiguous_package_dir(monkeypatch, found):
    monkeypatch.setattr(sys, "argv", ["patch_identity.py"])
    monkeypatch.setattr(glob, "glob", lambda pattern: found)
    with pytest.raises(SystemExit, match="not found uniquely"):
        patch_identity.main()


# upstream SDK tests


SDK_SRC = os.environ.get("MUSEGADGET_SDK_SRC")


@pytest.fixture(scope="module")
def patched_service(tmp_path_factory):
    if not SDK_SRC:
        pytest.skip("MUSEGADGET_SDK_SRC not set; SDK patch tests skipped")
    root = tmp_path_factory.mktemp("sdk-identity")
    package = root / "musegadget"
    shutil.copytree(Path(SDK_SRC) / "linux" / "src" / "musegadget", package)
    # Same order as the Dockerfile: the identity needle matches the
    # _handle_local text patch_subscribe.py leaves behind.
    for patch in ("patch_subscribe.py", "patch_identity.py"):
        subprocess.run(
            [sys.executable, str(LIMEN / patch), str(package)],
            check=True,
            capture_output=True,
            text=True,
        )
    sys.path.insert(0, str(root))
    try:
        spec = importlib.util.spec_from_file_location(
            "patched_identity_service", package / "service.py"
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        # dataclasses resolves string annotations through sys.modules,
        # so the module must be registered before it executes.
        sys.modules["patched_identity_service"] = module
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.path.remove(str(root))
        # The import cached this scratch copy as the musegadget
        # package; evict it so other test modules import their own.
        for name in [n for n in sys.modules if n == "musegadget" or n.startswith("musegadget.")]:
            del sys.modules[name]
        sys.modules.pop("patched_identity_service", None)


class _FakeSession:
    """A registered LinkSession whose request() answers from a script."""

    def __init__(self, result=None, error=None):
        self.registered_at = 123.0
        self._result = result
        self._error = error
        self.calls: list[tuple[str, str]] = []

    async def request(self, method, path, body=b"", **kwargs):
        self.calls.append((method, path))
        if self._error is not None:
            raise self._error
        return self._result


def _service_with(patched_service, session):
    service = object.__new__(patched_service.Service)
    service._current = session
    return service


def test_local_identity_returns_name(patched_service):
    session = _FakeSession(
        result={
            "ok": True,
            "status": 200,
            "response": {"name": "Tiro", "tagline": "Sharp, calm, precise and concise."},
        }
    )
    service = _service_with(patched_service, session)
    reply = asyncio.run(service._local_identity())
    assert reply == {
        "ok": True,
        "identity": {"name": "Tiro", "tagline": "Sharp, calm, precise and concise."},
    }
    assert session.calls == [("GET", "/identity")]


def test_local_identity_refuses_when_not_connected(patched_service):
    service = _service_with(patched_service, None)
    reply = asyncio.run(service._local_identity())
    assert reply == {"ok": False, "error": "not connected to the Muse"}


def test_local_identity_reports_request_failure(patched_service):
    session = _FakeSession(error=ConnectionError("down"))
    service = _service_with(patched_service, session)
    reply = asyncio.run(service._local_identity())
    assert reply["ok"] is False
    assert "ConnectionError" in reply["error"]


def test_local_identity_reports_gateway_error(patched_service):
    session = _FakeSession(result={"ok": False, "status": 403, "response": None})
    service = _service_with(patched_service, session)
    reply = asyncio.run(service._local_identity())
    assert reply == {"ok": False, "error": "identity request failed (status 403)"}


def test_local_identity_rejects_non_object_response(patched_service):
    session = _FakeSession(result={"ok": True, "status": 200, "response": "Tiro"})
    service = _service_with(patched_service, session)
    reply = asyncio.run(service._local_identity())
    assert reply == {"ok": False, "error": "identity is not an object"}


class _FakeWriter:
    def __init__(self):
        self.written: list[bytes] = []
        self.closed = False

    def write(self, data: bytes) -> None:
        self.written.append(data)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


def test_handle_local_routes_identity_op(patched_service):
    session = _FakeSession(result={"ok": True, "status": 200, "response": {"name": "Tiro"}})
    service = _service_with(patched_service, session)

    async def _run():
        # StreamReader needs a running loop at construction.
        reader = asyncio.StreamReader()
        reader.feed_data(b'{"op": "identity"}\n')
        reader.feed_eof()
        writer = _FakeWriter()
        await service._handle_local(reader, writer)
        return writer

    writer = asyncio.run(_run())
    assert len(writer.written) == 1
    reply = json.loads(writer.written[0])
    assert reply == {"ok": True, "identity": {"name": "Tiro"}}
    assert session.calls == [("GET", "/identity")]
