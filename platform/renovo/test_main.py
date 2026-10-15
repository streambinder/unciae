"""Unit tests for the renovo command runner.

Process execution is faked at the module boundary where a test needs
deterministic exit codes; the stream and terminate tests use real
short-lived child processes.
"""

from __future__ import annotations

import asyncio
import os
import signal
import stat
import sys
from collections.abc import AsyncGenerator
from typing import Any, ClassVar, Self

import main
import pytest


class FakeStream:
    def __init__(self, lines: list[bytes]) -> None:
        self._lines = list(lines)

    async def readline(self) -> bytes:
        return self._lines.pop(0) if self._lines else b""


class FakeLot:
    def __init__(self, alias: str) -> None:
        self.alias = alias
        self.messages: list[str] = []
        self.closed_with: str | None = None

    def print(self, message: str) -> None:
        self.messages.append(message)

    def close(self, message: str) -> None:
        self.closed_with = message


class FakeWindow:
    instances: ClassVar[list[FakeWindow]] = []

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        self.printed: list[str] = []
        self.anchored: list[str] = []
        self.lots: dict[str, FakeLot] = {}
        self.plain = False
        self.close_calls: list[bool] = []
        FakeWindow.instances.append(self)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close_calls.append(exc[0] is not None)

    def printf(self, fmt: str, *args: object) -> None:
        self.printed.append(fmt % args if args else fmt)

    def anchor_printf(self, fmt: str, *args: object) -> None:
        self.anchored.append(fmt % args if args else fmt)

    def lot(self, alias: str) -> FakeLot:
        return self.lots.setdefault(alias, FakeLot(alias))

    def enable_plain_mode(self) -> None:
        self.plain = True

    def close(self, interrupted: bool = False) -> None:
        self.close_calls.append(interrupted)


@pytest.fixture(autouse=True)
def _registry(monkeypatch: pytest.MonkeyPatch) -> None:
    snapshot = set(main.DEP_FNS)
    FakeWindow.instances = []
    monkeypatch.setattr(main, "_cached_pass", None)
    yield
    main.DEP_FNS.clear()
    main.DEP_FNS.update(snapshot)


def run(coro: Any) -> Any:
    return asyncio.run(coro)


async def _collect(gen: AsyncGenerator[Any, None]) -> list[Any]:
    return [item async for item in gen]


# password helpers


def test_get_pass_prompts_until_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    prompts: list[str] = []

    def fake_getpass(prompt: str) -> str:
        prompts.append(prompt)
        return "pw"

    monkeypatch.setattr(main, "getpass", fake_getpass)
    assert main.get_pass("brew") == "pw"
    assert prompts == ["Authenticate for brew: "]
    assert main.get_pass() == "pw"
    assert prompts[-1] == "Authenticate: "
    main.accept_pass("cached")
    assert main.get_pass("brew") == "cached"
    assert len(prompts) == 2


def test_is_os_and_is_exec() -> None:
    assert main.is_os("lin")
    assert not main.is_os("plan9")
    assert main.is_exec("sh")
    assert not main.is_exec("renovo-cmd-that-does-not-exist")


# spawn / terminate / streams


def test_spawn_runs_real_process() -> None:
    async def scenario() -> int:
        process = await main.spawn(sys.executable, "-c", "pass")
        assert process.stdout is not None
        await process.stdout.read()
        returncode = await process.wait()
        await main.terminate(process)
        return returncode

    assert run(scenario()) == 0


def test_terminate_kills_running_process() -> None:
    async def scenario() -> int:
        process = await main.spawn(sys.executable, "-c", "import time; time.sleep(60)")
        await main.terminate(process)
        return await process.wait()

    assert run(scenario()) == -signal.SIGTERM


class _FakeProc:
    def __init__(self, pid: int) -> None:
        self.returncode: int | None = None
        self.pid = pid
        self.killed = False

    async def wait(self) -> int:
        if self.killed:
            return -signal.SIGKILL
        await asyncio.sleep(30)
        return 0


def test_terminate_unknown_pid_returns(monkeypatch: pytest.MonkeyPatch) -> None:
    run(main.terminate(_FakeProc(pid=2**22)))  # type: ignore[arg-type]


def test_terminate_killpg_lookup_error_returns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "getpgid", lambda pid: 4242)

    def missing_group(pgid: int, sig: int) -> None:
        raise ProcessLookupError

    monkeypatch.setattr(os, "killpg", missing_group)
    run(main.terminate(_FakeProc(pid=123)))  # type: ignore[arg-type]


def test_terminate_escalates_to_sigkill(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "_TERM_GRACE_SECONDS", 0.05)
    monkeypatch.setattr(os, "getpgid", lambda pid: 4242)
    sent: list[int] = []
    proc = _FakeProc(pid=123)

    def killpg(pgid: int, sig: int) -> None:
        sent.append(sig)
        if sig == signal.SIGKILL:
            proc.killed = True

    monkeypatch.setattr(os, "killpg", killpg)
    run(main.terminate(proc))  # type: ignore[arg-type]
    assert sent == [signal.SIGTERM, signal.SIGKILL]


def test_stream_to_lot_skips_blank_lines() -> None:
    lot = FakeLot("job")
    run(main.stream_to_lot(FakeStream([b"one\n", b"\n", b" two \n"]), lot))  # type: ignore[arg-type]
    assert lot.messages == ["one", " two"]


def test_stream_to_anchor_reports_lines() -> None:
    lot = FakeLot("job")
    window = FakeWindow()
    stream = FakeStream([b"warn\n", b"\n"])
    run(main.stream_to_anchor(stream, lot, window, "prog"))  # type: ignore[arg-type]
    assert lot.messages == ["warn"]
    assert window.anchored == ["prog: warn"]


def test_askpass_helper_lifecycle() -> None:
    with main.askpass_helper("s3cret word") as path:
        helper = os.path.join(os.path.dirname(path), "askpass.sh")
        assert path == helper
        with open(path, encoding="utf-8") as handle:
            content = handle.read()
        assert "s3cret word" in content
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o700
        assert stat.S_IMODE(os.stat(os.path.dirname(path)).st_mode) == 0o700
    assert not os.path.exists(path)
    assert not os.path.exists(os.path.dirname(path))


# dep decorator


def test_dep_unsupported_platform() -> None:
    @main.dep(platform_name="plan9")
    async def plan9tool() -> AsyncGenerator[Any, None]:
        yield ["plan9tool"], {}

    window = FakeWindow()
    run(plan9tool(window))  # type: ignore[arg-type]
    assert window.printed == ["plan9tool is unsupported"]


def test_dep_missing_env() -> None:
    @main.dep(cmd="sh", env=["RENOVO_ENV_THAT_IS_NOT_SET"])
    async def envtool() -> AsyncGenerator[Any, None]:
        yield ["sh"], {}

    window = FakeWindow()
    run(envtool(window))  # type: ignore[arg-type]
    assert window.printed == ["envtool is unsupported"]


def test_dep_missing_command() -> None:
    @main.dep(cmd="renovo-cmd-that-does-not-exist")
    async def ghosttool() -> AsyncGenerator[Any, None]:
        yield ["ghost"], {}

    window = FakeWindow()
    run(ghosttool(window))  # type: ignore[arg-type]
    assert window.printed == ["ghosttool is unsupported"]


def test_dep_runs_real_command() -> None:
    @main.dep(cmd="sh")
    async def echotool() -> AsyncGenerator[Any, None]:
        yield ["sh", "-c", "echo hello-from-dep"], {}

    window = FakeWindow()
    run(echotool(window))  # type: ignore[arg-type]
    lot = window.lots["echotool"]
    assert "hello-from-dep" in lot.messages
    assert lot.closed_with == "upgraded"


class _StubProc:
    def __init__(self, returncode: int) -> None:
        self.returncode: int | None = returncode
        self.stdout = FakeStream([])
        self.stderr = FakeStream([])


def test_dep_sudo_inserts_askpass_flag_and_reports_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spawned: list[list[str]] = []

    async def fake_spawn(*args: Any, **kwargs: Any) -> _StubProc:
        spawned.append(list(args))
        return _StubProc(returncode=3)

    monkeypatch.setattr(main, "spawn", fake_spawn)

    @main.dep(cmd="sh")
    async def sudotool() -> AsyncGenerator[Any, None]:
        yield ["sudo", "tool", "arg"], {}

    window = FakeWindow()
    run(sudotool(window))  # type: ignore[arg-type]
    assert spawned == [["sudo", "-A", "tool", "arg"]]
    assert window.lots["sudotool"].closed_with == "failed"
    assert any("exited with code 3" in line for line in window.anchored)


def test_dep_spawn_returning_none_still_upgrades(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_spawn(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(main, "spawn", fake_spawn)

    @main.dep(cmd="sh")
    async def nonetool() -> AsyncGenerator[Any, None]:
        yield ["sh", "-c", "true"], {}

    window = FakeWindow()
    run(nonetool(window))  # type: ignore[arg-type]
    assert window.lots["nonetool"].closed_with == "upgraded"


def test_dep_exception_closes_lot_as_raised() -> None:
    @main.dep(cmd="sh")
    async def raisetool() -> AsyncGenerator[Any, None]:
        raise ValueError("boom")
        yield ["sh"], {}

    window = FakeWindow()
    run(raisetool(window))  # type: ignore[arg-type]
    assert window.lots["raisetool"].closed_with == "raised"
    assert any("boom" in line for line in window.anchored)


# bundled dep generators


def test_bundled_dep_command_specs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZSH", "/zsh")
    apt = run(_collect(main.apt.__wrapped__()))  # type: ignore[attr-defined]
    assert len(apt) == 4
    assert all(args[:3] == ["sudo", "apt-get", "-y"] for args, _ in apt)
    assert apt[0][1]["env"]["DEBIAN_FRONTEND"] == "noninteractive"
    assert run(_collect(main.dnf.__wrapped__()))[0][0] == [  # type: ignore[attr-defined]
        "sudo",
        "dnf",
        "upgrade",
        "-y",
    ]
    brew = run(_collect(main.brew.__wrapped__()))  # type: ignore[attr-defined]
    assert [args[1] for args, _ in brew] == ["update", "upgrade"]
    msc = run(_collect(main.msc.__wrapped__()))  # type: ignore[attr-defined]
    assert msc[0][0][1] == "managedsoftwareupdate"
    omz = run(_collect(main.omz.__wrapped__()))  # type: ignore[attr-defined]
    assert omz[0][0] == ["/zsh/tools/upgrade.sh"]
    yadm = run(_collect(main.yadm.__wrapped__()))  # type: ignore[attr-defined]
    assert len(yadm) == 3
    nix = run(_collect(main.nix.__wrapped__()))  # type: ignore[attr-defined]
    assert nix[0][0] == ["nix-env", "-u", "*"]
    npm = run(_collect(main.npm.__wrapped__()))  # type: ignore[attr-defined]
    assert npm[0][0] == ["npm", "update", "-g"]
    pi = run(_collect(main.pi.__wrapped__()))  # type: ignore[attr-defined]
    assert len(pi) == 2


def test_is_sudo_required_detects_sudo() -> None:
    assert run(main.is_sudo_required()) is True


def test_is_sudo_required_without_sudo_deps(monkeypatch: pytest.MonkeyPatch) -> None:
    @main.dep(cmd="sh")
    async def plaintool() -> AsyncGenerator[Any, None]:
        yield ["sh", "-c", "true"], {}

    monkeypatch.setattr(main, "DEP_FNS", {plaintool})
    assert run(main.is_sudo_required()) is False
    monkeypatch.setattr(main, "DEP_FNS", set())
    assert run(main.is_sudo_required()) is False


# verify_sudo


class _SudoProc:
    def __init__(self, valid_input: bytes | None) -> None:
        self.returncode: int | None = None
        self._valid_input = valid_input

    async def wait(self) -> int:
        return 0

    async def communicate(self, input: bytes | None = None) -> tuple[bytes, bytes]:
        self.returncode = 0 if input == self._valid_input else 1
        return b"", b""


def _patch_sudo(monkeypatch: pytest.MonkeyPatch, passwords: list[str]) -> list[str]:
    calls: list[str] = []

    async def fake_create(*args: Any, **kwargs: Any) -> _SudoProc:
        calls.append(args[1] if len(args) > 1 else "")
        if args == ("sudo", "-k"):
            return _SudoProc(None)
        return _SudoProc(b"good\n")

    monkeypatch.setattr(main.asyncio, "create_subprocess_exec", fake_create)
    remaining = iter(passwords)
    monkeypatch.setattr(main, "getpass", lambda prompt="": next(remaining))
    return calls


def test_verify_sudo_accepts_good_password(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_sudo(monkeypatch, ["good"])
    assert run(main.verify_sudo()) is True
    assert main.get_pass() == "good"


def test_verify_sudo_retries_then_succeeds(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_sudo(monkeypatch, ["bad", "good"])
    assert run(main.verify_sudo()) is True
    assert "Sorry, try again." in capsys.readouterr().err


def test_verify_sudo_gives_up_after_three_attempts(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_sudo(monkeypatch, ["bad", "bad", "bad"])
    assert run(main.verify_sudo()) is False
    assert "sudo: authentication failed" in capsys.readouterr().err


# the click command body, invoked through its callback


async def _no_sudo() -> bool:
    return False


async def _yes_sudo() -> bool:
    return True


async def _verify_ok() -> bool:
    return True


async def _verify_bad() -> bool:
    return False


def _patch_command(monkeypatch: pytest.MonkeyPatch, ran: list[bool]) -> None:
    async def fake_dep(window: Any) -> None:
        ran.append(True)

    monkeypatch.setattr(main, "Window", FakeWindow)
    monkeypatch.setattr(main, "DEP_FNS", {fake_dep})
    monkeypatch.setattr(main, "is_sudo_required", _no_sudo)


def test_command_runs_deps_in_plain_mode_when_not_tty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ran: list[bool] = []
    _patch_command(monkeypatch, ran)
    run(main.renovo.callback(None))
    assert ran == [True]
    assert FakeWindow.instances[0].plain is True


def test_command_anchor_flag_skips_plain_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[bool] = []
    _patch_command(monkeypatch, ran)
    run(main.renovo.callback(True))
    assert FakeWindow.instances[0].plain is False


def test_command_no_anchor_forces_plain_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[bool] = []
    _patch_command(monkeypatch, ran)
    run(main.renovo.callback(False))
    assert FakeWindow.instances[0].plain is True


def test_command_aborts_when_sudo_verification_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ran: list[bool] = []
    _patch_command(monkeypatch, ran)
    monkeypatch.setattr(main, "is_sudo_required", _yes_sudo)
    monkeypatch.setattr(main, "verify_sudo", _verify_bad)
    run(main.renovo.callback(True))
    assert ran == []
    assert FakeWindow.instances == []


def test_command_with_verified_sudo_uses_askpass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ran: list[bool] = []
    _patch_command(monkeypatch, ran)
    monkeypatch.setattr(main, "is_sudo_required", _yes_sudo)
    monkeypatch.setattr(main, "verify_sudo", _verify_ok)
    main.accept_pass("good")
    monkeypatch.delenv("SUDO_ASKPASS", raising=False)
    run(main.renovo.callback(True))
    assert ran == [True]
    assert os.environ.get("SUDO_ASKPASS", "").endswith("askpass.sh")
    monkeypatch.delenv("SUDO_ASKPASS", raising=False)
