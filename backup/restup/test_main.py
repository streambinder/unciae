"""Unit tests for the restup backup runner.

subprocess is replaced by a recording fake, so the tests drive the
runner logic (validation, hooks, retention) without a restic binary.
"""

from __future__ import annotations

import runpy
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Self

import main
import pytest
from main import Restup


class FakePipe:
    """Stand-in for a Popen used as a pipeline stage."""

    def __init__(self, args: list[str], out: bytes = b"", err: bytes | None = None) -> None:
        self.args = args
        self.stdout = object()
        self._out = out
        self._err = err
        self.stdin: Any = None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def communicate(self) -> tuple[bytes, bytes | None]:
        return self._out, self._err


class FakeSubprocess:
    def __init__(self) -> None:
        self.popen_calls: list[tuple[list[str], dict[str, Any]]] = []
        self.run_calls: list[str] = []
        self.run_failures: set[str] = set()
        self.communicate_results: list[tuple[bytes, bytes | None]] = []
        self.lock = threading.Lock()

    def popen(self, args: list[str], **kwargs: Any) -> FakePipe:
        with self.lock:
            self.popen_calls.append((args, kwargs))
            if args and args[0] == "restic":
                out, err = self.communicate_results.pop(0)
                return FakePipe(args, out, err)
            return FakePipe(args, out=b"password")

    def run(self, command: str, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        with self.lock:
            self.run_calls.append(command)
        if command in self.run_failures:
            raise subprocess.CalledProcessError(1, command)
        return subprocess.CompletedProcess(command, 0)


@pytest.fixture()
def fake_subprocess(monkeypatch: pytest.MonkeyPatch) -> FakeSubprocess:
    fake = FakeSubprocess()
    monkeypatch.setattr(main.subprocess, "Popen", fake.popen)
    monkeypatch.setattr(main.subprocess, "run", fake.run)
    return fake


def _task(tmp_path: Path, **extra: Any) -> dict[str, Any]:
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    task: dict[str, Any] = {
        "repository": str(repo),
        "password": "secret",
        "path": str(data),
    }
    task.update(extra)
    return task


def _restup(tmp_path: Path, **extra: Any) -> Restup:
    return Restup({"tasks": [_task(tmp_path, **extra)]})


def test_empty_config_has_no_tasks() -> None:
    restup = Restup({})
    assert restup.tasks == []
    assert "tasks" in str(restup)


@pytest.mark.parametrize("missing", ["repository", "password", "path"])
def test_missing_mandatory_key_rejected(tmp_path: Path, missing: str) -> None:
    task = _task(tmp_path)
    del task[missing]
    with pytest.raises(RuntimeError, match=f"{missing} key is mandatory"):
        Restup({"tasks": [task]})


def test_none_mandatory_value_rejected(tmp_path: Path) -> None:
    task = _task(tmp_path)
    task["password"] = None
    with pytest.raises(RuntimeError, match="password key is mandatory"):
        Restup({"tasks": [task]})


def test_missing_retention_warns(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _restup(tmp_path)
    assert "has not retention token" in capsys.readouterr().err


def test_nonexistent_repository_path_rejected(tmp_path: Path) -> None:
    task = _task(tmp_path)
    task["repository"] = str(tmp_path / "nope")
    with pytest.raises(RuntimeError, match="does not exist"):
        Restup({"tasks": [task]})


def test_nonexistent_hook_path_rejected(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="does not exist"):
        _restup(tmp_path, retention="1d", prespawn=str(tmp_path / "nope.sh"))


def test_run_backs_up_and_prints_output(tmp_path: Path, fake_subprocess: FakeSubprocess) -> None:
    fake_subprocess.communicate_results = [(b"snapshot saved", None)]
    _restup(tmp_path, retention="7d").run()
    restic = [c for c in fake_subprocess.popen_calls if c[0][0] == "restic"]
    assert restic[0][0][1:4] == ["-r", str(tmp_path / "repo"), "backup"]


def test_run_applies_retention_and_hooks(tmp_path: Path, fake_subprocess: FakeSubprocess) -> None:
    pre = tmp_path / "pre.sh"
    pre.write_text("#!/bin/sh\n")
    post = tmp_path / "post.sh"
    post.write_text("#!/bin/sh\n")
    fake_subprocess.communicate_results = [(b"backup", None), (b"pruned", None)]
    _restup(
        tmp_path,
        retention="7d",
        prespawn=str(pre),
        postspawn=str(post),
        regexes=["*.tmp"],
    ).run()
    commands = [args for args, _ in fake_subprocess.popen_calls]
    assert any("--iexclude" in args for args in commands)
    forget = [args for args in commands if "forget" in args]
    assert forget and forget[0][-2:] == ["--keep-within", "7d"]
    assert fake_subprocess.run_calls == [str(pre), str(post)]


def test_pre_hook_failure_skips_backup(
    tmp_path: Path, fake_subprocess: FakeSubprocess, capsys: pytest.CaptureFixture[str]
) -> None:
    pre = tmp_path / "pre.sh"
    pre.write_text("#!/bin/sh\n")
    fake_subprocess.run_failures = {str(pre)}
    _restup(tmp_path, prespawn=str(pre)).run()
    assert not any(args[0] == "restic" for args, _ in fake_subprocess.popen_calls)
    assert "exited abnormally" in capsys.readouterr().err


def test_post_hook_failure_is_reported_not_fatal(
    tmp_path: Path, fake_subprocess: FakeSubprocess, capsys: pytest.CaptureFixture[str]
) -> None:
    post = tmp_path / "post.sh"
    post.write_text("#!/bin/sh\n")
    fake_subprocess.run_failures = {str(post)}
    fake_subprocess.communicate_results = [(b"backup", None)]
    _restup(tmp_path, postspawn=str(post)).run()
    assert "Post-task" in capsys.readouterr().err


def test_backup_error_output_stops_task(
    tmp_path: Path, fake_subprocess: FakeSubprocess, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_subprocess.communicate_results = [(b"", b"boom")]
    _restup(tmp_path).run()
    assert "Unable to backup" in capsys.readouterr().err


def test_retention_error_output_is_reported(
    tmp_path: Path, fake_subprocess: FakeSubprocess, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_subprocess.communicate_results = [(b"backup", None), (b"", b"boom")]
    _restup(tmp_path, retention="7d").run()
    assert "Unable to apply retention" in capsys.readouterr().err


def test_run_processes_every_task(tmp_path: Path, fake_subprocess: FakeSubprocess) -> None:
    fake_subprocess.communicate_results = [(b"one", None), (b"two", None)]
    restup = Restup({"tasks": [_task(tmp_path), _task(tmp_path)]})
    restup.run()
    backups = [args for args, _ in fake_subprocess.popen_calls if "backup" in args]
    assert len(backups) == 2


def test_main_block_runs_config_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config = tmp_path / "cfg.yml"
    config.write_text("tasks: []\n")
    monkeypatch.setattr(sys, "argv", ["main.py", str(config)])
    monkeypatch.chdir(tmp_path)
    runpy.run_path(str(Path(main.__file__)), run_name="__main__")


def test_main_block_reports_unreadable_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["main.py", str(tmp_path / "missing.yml")])
    monkeypatch.chdir(tmp_path)
    runpy.run_path(str(Path(main.__file__)), run_name="__main__")
    assert "missing.yml" in capsys.readouterr().err


def test_main_block_uses_default_config_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sys, "argv", ["main.py"])
    monkeypatch.chdir(tmp_path)
    runpy.run_path(str(Path(main.__file__)), run_name="__main__")
