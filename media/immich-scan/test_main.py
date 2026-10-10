"""Unit tests for the immich-scan runner."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, ClassVar, Self

import main
import pytest
from immich import ImmichError


class FakeImmich:
    library_list: ClassVar[list[dict[str, Any]]] = []
    queue_reads: ClassVar[list[dict[str, int]]] = []
    scanned: ClassVar[list[str]] = []

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def libraries(self) -> list[dict[str, Any]]:
        return FakeImmich.library_list

    def scan_library(self, library_id: str) -> None:
        FakeImmich.scanned.append(library_id)

    def queue_status(self, queue: str) -> dict[str, int]:
        assert queue == main.QUEUE
        return FakeImmich.queue_reads.pop(0)


def _stats(active: int = 0, waiting: int = 0, delayed: int = 0, failed: int = 0) -> dict[str, int]:
    return {"active": active, "waiting": waiting, "delayed": delayed, "failed": failed}


@pytest.fixture(autouse=True)
def _fake(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeImmich.library_list = []
    FakeImmich.queue_reads = []
    FakeImmich.scanned = []
    monkeypatch.setattr(main, "Immich", FakeImmich)
    monkeypatch.setattr(main.time, "sleep", lambda _seconds: None)


def test_resolve_library_exact_and_ancestor_match(tmp_path: Path) -> None:
    photo_dir = tmp_path / "photos"
    photo_dir.mkdir()
    FakeImmich.library_list = [
        {"id": "plain", "name": "plain", "importPaths": []},
        {"id": "lib", "name": "photos", "importPaths": [str(tmp_path)]},
    ]
    immich = FakeImmich()
    assert main.resolve_library(immich, str(tmp_path))["id"] == "lib"
    assert main.resolve_library(immich, str(photo_dir))["id"] == "lib"


def test_resolve_library_without_covering_library_raises(tmp_path: Path) -> None:
    FakeImmich.library_list = [{"id": "x", "importPaths": ["/somewhere/else"]}]
    with pytest.raises(ImmichError, match="no external library covers"):
        main.resolve_library(FakeImmich(), str(tmp_path))


def test_wait_for_queue_returns_after_two_idle_reads(
    capsys: pytest.CaptureFixture[str],
) -> None:
    FakeImmich.queue_reads = [_stats(active=1), _stats(), _stats()]
    main.wait_for_queue(FakeImmich(), timeout_s=60.0)
    assert "active=1" in capsys.readouterr().err


def test_wait_for_queue_times_out() -> None:
    FakeImmich.queue_reads = [_stats(active=1)]
    with pytest.raises(TimeoutError, match="did not drain"):
        main.wait_for_queue(FakeImmich(), timeout_s=0.0)


def test_main_scans_waits_and_runs_hook(tmp_path: Path) -> None:
    FakeImmich.library_list = [{"id": "lib", "name": "photos", "importPaths": [str(tmp_path)]}]
    FakeImmich.queue_reads = [_stats(), _stats()]
    target = tmp_path / "sub"
    target.mkdir()
    rc = main.main([str(target), "--hook", "true"])
    assert rc == 0
    assert FakeImmich.scanned == ["lib"]


def test_main_without_hook(tmp_path: Path) -> None:
    FakeImmich.library_list = [{"id": "lib", "name": "photos", "importPaths": [str(tmp_path)]}]
    FakeImmich.queue_reads = [_stats(), _stats()]
    assert main.main([str(tmp_path)]) == 0


def test_main_reports_queue_timeout(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    FakeImmich.library_list = [{"id": "lib", "name": "photos", "importPaths": [str(tmp_path)]}]
    FakeImmich.queue_reads = [_stats(active=2)]
    rc = main.main([str(tmp_path), "--timeout", "0"])
    assert rc == 1
    assert "FAIL" in capsys.readouterr().err


def test_main_hook_uses_subprocess(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    FakeImmich.library_list = [{"id": "lib", "name": "photos", "importPaths": [str(tmp_path)]}]
    FakeImmich.queue_reads = [_stats(), _stats()]
    calls: list[tuple[Any, ...]] = []

    def fake_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(main.subprocess, "run", fake_run)
    assert main.main([str(tmp_path), "--hook", "echo done"]) == 0
    assert calls and calls[0][0] == "echo done"
