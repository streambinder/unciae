#!/usr/bin/env python3

from __future__ import annotations

import asyncio
import functools
import os
import platform
import shlex
import shutil
import signal
import sys
import tempfile
from collections.abc import AsyncGenerator, Callable, Coroutine, Iterator
from contextlib import contextmanager
from getpass import getpass
from pathlib import Path
from typing import Any, cast

import anyio
import asyncclick as click
from anchor import Lot, Red, Window

CommandSpec = tuple[list[str], dict[str, Any]]
CommandGenerator = AsyncGenerator[CommandSpec, None]
DepFn = Callable[[Window], Coroutine[Any, Any, None]]

DEP_FNS: set[DepFn] = set()


_cached_pass: str | None = None


def get_pass(program: str | None = None) -> str:
    if _cached_pass is not None:
        return _cached_pass
    return getpass(f"Authenticate{' for ' + program if program else ''}: ")


def accept_pass(password: str) -> None:
    """cache password only after it's been verified"""
    global _cached_pass
    _cached_pass = password


def is_os(os_name: str) -> bool:
    return platform.system().lower().startswith(os_name.lower())


def is_exec(cmd: str) -> bool:
    return shutil.which(cmd) is not None


_TERM_GRACE_SECONDS = 5.0


async def spawn(*args: Any, **kwargs: Any) -> asyncio.subprocess.Process:
    kwargs.setdefault("env", os.environ)
    return await asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        # own session/process group so we can signal the whole tree — brew
        # forks curl/sudo, apt forks dpkg; signalling just the child orphans them
        start_new_session=True,
        **kwargs,
    )


async def terminate(process: asyncio.subprocess.Process) -> None:
    """SIGTERM the child's process group, grace period, then SIGKILL the group.
    Called from the cancellation path — must not itself be interrupted, so the
    wait is shielded. Group-signalling (killpg) reaches grandchildren; a bare
    process.terminate() would leave brew's curl/dpkg running."""
    if process.returncode is not None:
        return
    try:
        # child is its own group leader (start_new_session), so pgid == pid.
        # asyncio holds the zombie until we wait(), so no pid reuse in between.
        pgid = os.getpgid(process.pid)
    except ProcessLookupError:
        return
    for sig, timeout in ((signal.SIGTERM, _TERM_GRACE_SECONDS), (signal.SIGKILL, None)):
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            return  # already gone
        if timeout is None:
            await asyncio.shield(process.wait())
            return
        try:
            await asyncio.shield(asyncio.wait_for(process.wait(), timeout))
            return
        except TimeoutError:
            continue  # survived SIGTERM, escalate to SIGKILL


async def stream_to_lot(stream: asyncio.StreamReader, lot: Lot) -> None:
    while line := await stream.readline():
        decoded = line.decode().rstrip()
        if decoded:
            lot.print(decoded)


async def stream_to_anchor(
    stream: asyncio.StreamReader, lot: Lot, window: Window, program: str
) -> None:
    while line := await stream.readline():
        decoded = line.decode().rstrip()
        if decoded:
            lot.print(decoded)
            window.anchor_printf(f"{program}: {decoded}")


@contextmanager
def askpass_helper(password: str) -> Iterator[str]:
    # tmp dir 0700, helper script prints password to stdout for SUDO_ASKPASS
    # both brew's child sudo invocations and ours pick this up via env
    tmp = Path(tempfile.mkdtemp(prefix="renovo-"))
    tmp.chmod(0o700)
    helper = tmp / "askpass.sh"
    helper.write_text(f"#!/bin/sh\nprintf %s {shlex.quote(password)}\n")
    helper.chmod(0o700)
    try:
        yield str(helper)
    finally:
        try:
            helper.unlink()
        finally:
            tmp.rmdir()


def dep(
    cmd: str | None = None,
    platform_name: str = "",
    env: list[str] | None = None,
) -> Callable[[Callable[[], CommandGenerator]], DepFn]:
    valid_os = is_os(platform_name)
    valid_env = len([e for e in (env or []) if e not in os.environ]) == 0

    def decorator_dep(func: Callable[[], CommandGenerator]) -> DepFn:
        program = func.__name__
        valid_cmd = is_exec(cmd or program)

        @functools.wraps(func)
        async def wrapper_dep(window: Window) -> None:
            if not (valid_cmd and valid_os and valid_env):
                window.printf(f"{program} is unsupported")
                return

            lot = window.lot(program)
            lot.print("upgrading...")
            try:
                async for p_args, p_kwargs in func():
                    # SUDO_ASKPASS in env; -A makes sudo call helper for password (no tty needed)
                    if p_args[0] == "sudo":
                        p_args.insert(1, "-A")

                    if process := await spawn(*p_args, **p_kwargs):
                        assert process.stdout is not None
                        assert process.stderr is not None
                        try:
                            await asyncio.gather(
                                stream_to_lot(process.stdout, lot),
                                stream_to_anchor(process.stderr, lot, window, program),
                            )
                        finally:
                            # ctrl+c cancels us mid-gather: the child keeps running
                            # with its pipes open. tear the whole group down before
                            # unwinding so nothing is orphaned past loop shutdown.
                            await terminate(process)
                        if process.returncode and process.returncode != 0:
                            window.anchor_printf(
                                f"{program}: exited with code {process.returncode}"
                            )
                            lot.close("failed")
                            return
            except Exception as exc:
                # logic/runtime errors share the sticky error tier with stderr
                window.anchor_printf(f"{program}: {exc}")
                lot.close("failed")
                return
            lot.close("upgrade complete.")

        wrapped = cast(DepFn, wrapper_dep)
        DEP_FNS.add(wrapped)
        return wrapped

    return decorator_dep


@dep(platform_name="linux")
async def apt() -> CommandGenerator:
    kwargs = {"env": dict(os.environ, DEBIAN_FRONTEND="noninteractive")}
    apt_get = ["sudo", "apt-get", "-y"]
    yield apt_get + ["update"], kwargs
    yield apt_get + ["upgrade"], kwargs
    yield apt_get + ["dist-upgrade"], kwargs
    yield apt_get + ["autoremove"], kwargs


@dep(platform_name="linux")
async def dnf() -> CommandGenerator:
    yield ["sudo", "dnf", "upgrade", "-y"], {}


@dep()
async def brew() -> CommandGenerator:
    yield ["brew", "update", "-q"], {}
    yield ["brew", "upgrade", "-q", "--greedy"], {}


@dep(cmd="managedsoftwareupdate")
async def msc() -> CommandGenerator:
    yield ["sudo", "managedsoftwareupdate", "--installonly", "--quiet"], {}


@dep(cmd="zsh", env=["ZSH"])
async def omz() -> CommandGenerator:
    yield [f"{os.getenv('ZSH')}/tools/upgrade.sh"], {}


@dep(platform_name="darwin", cmd="softwareupdate")
async def macos() -> CommandGenerator:
    yield ["sudo", "softwareupdate", "-iaR"], {}


@dep()
async def yadm() -> CommandGenerator:
    yield ["yadm", "pull", "--rebase"], {}
    yield ["yadm", "submodule", "update", "--init", "--recursive"], {}
    yield ["yadm", "bootstrap"], {}


@dep(cmd="nix-env")
async def nix() -> CommandGenerator:
    yield ["nix-env", "-u", "*"], {}


@dep()
async def npm() -> CommandGenerator:
    yield ["npm", "update", "-g"], {}


@dep(cmd="pi")
async def pi() -> CommandGenerator:
    yield ["pi", "update", "--all"], {}


async def is_sudo_required() -> bool:
    for fn in DEP_FNS:
        # underlying generator function lives on __wrapped__ via functools.wraps
        gen_fn = cast(Callable[[], CommandGenerator], fn.__wrapped__)  # type: ignore[attr-defined]
        async for p_args, _ in gen_fn():
            if p_args and p_args[0] == "sudo":
                return True
    return False


_MAX_AUTH_ATTEMPTS = 3


async def verify_sudo() -> bool:
    # runs before the TUI window exists — plain stderr for feedback.
    # uses -S (stdin) instead of -A (askpass) so sudo reads the password once
    # and can't retry with the same wrong value when stdin hits EOF.
    # invalidate any cached credential first so we actually test the password.
    await (await asyncio.create_subprocess_exec("sudo", "-k")).wait()
    for attempt in range(_MAX_AUTH_ATTEMPTS):
        password = get_pass()
        proc = await asyncio.create_subprocess_exec(
            "sudo",
            "-S",
            "-p",
            "",
            "-v",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.communicate(input=f"{password}\n".encode())
        if proc.returncode == 0:
            accept_pass(password)
            return True
        print(
            "Sorry, try again."
            if attempt < _MAX_AUTH_ATTEMPTS - 1
            else "sudo: authentication failed",
            file=sys.stderr,
        )
    return False


@click.command()
@click.option(
    "--anchor/--no-anchor",
    default=None,
    help="Force anchored TUI on/off. Default: auto (on if stdout is a tty).",
)
async def renovo(anchor: bool | None) -> None:
    needs_sudo = await is_sudo_required()
    if needs_sudo and not await verify_sudo():
        return

    with Window(Red) as window:
        if anchor is False or (anchor is None and not sys.stdout.isatty()):
            window.enable_plain_mode()

        async def run_all() -> None:
            async with asyncio.TaskGroup() as upgrades:
                for fn in DEP_FNS:
                    upgrades.create_task(fn(window))

        # run the upgrades in a task we can cancel cooperatively from a signal
        # handler. relying on the default KeyboardInterrupt-on-SIGINT tears the
        # loop down WITHOUT running the dep tasks' `finally: terminate()` — the
        # children get orphaned. an installed handler cancels through the loop,
        # so every finally runs and every process group is killed.
        loop = asyncio.get_running_loop()

        async def guarded() -> None:
            if not needs_sudo:
                await run_all()
                return
            # password verified and cached; rebuild helper for the upgrade tasks
            with askpass_helper(get_pass()) as helper:
                os.environ["SUDO_ASKPASS"] = helper
                await run_all()

        task = asyncio.ensure_future(guarded())
        for signame in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(signame, task.cancel)
        try:
            await task
        except asyncio.CancelledError:
            # interrupted: the dep tasks' finally already killed their process
            # groups on the way out. freeze the still-open provider lots and add
            # an umbrella `(upgrader) stopped`; swallow so we exit without a trace.
            window.lot("upgrader").stop()
            window.close(interrupted=True)
        finally:
            for signame in (signal.SIGINT, signal.SIGTERM):
                loop.remove_signal_handler(signame)


if __name__ == "__main__":
    anyio.run(renovo.main)
