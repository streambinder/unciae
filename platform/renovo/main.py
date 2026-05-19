#!/usr/bin/env python3

from __future__ import annotations

import asyncio
import functools
import os
import platform
import shlex
import shutil
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


def only_once(func: Callable[..., Any]) -> Callable[..., Any]:
    _run_attr = "_run"
    _value_attr = "_value"

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        if getattr(func, _run_attr, False):
            return getattr(func, _value_attr, None)

        value = func(*args, **kwargs)
        setattr(func, _value_attr, value)
        setattr(func, _run_attr, True)
        return value

    return wrapper


@only_once
def get_pass(program: str | None = None) -> str:
    return getpass(f"Authenticate{' for ' + program if program else ''}: ")


def is_os(os_name: str) -> bool:
    return platform.system().lower().startswith(os_name.lower())


def is_exec(cmd: str) -> bool:
    return shutil.which(cmd) is not None


async def spawn(*args: Any, **kwargs: Any) -> asyncio.subprocess.Process:
    return await asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        **kwargs,
    )


async def stream_to_lot(stream: asyncio.StreamReader, lot: Lot) -> None:
    while line := await stream.readline():
        decoded = line.decode().rstrip()
        if decoded:
            lot.print(decoded)


async def stream_to_anchor(stream: asyncio.StreamReader, window: Window, program: str) -> None:
    while line := await stream.readline():
        decoded = line.decode().rstrip()
        if decoded:
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
                        await asyncio.gather(
                            stream_to_lot(process.stdout, lot),
                            stream_to_anchor(process.stderr, window, program),
                        )
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
    yield ["yadm", "pull"], {}
    yield ["yadm", "submodule", "update", "--init", "--recursive"], {}
    yield ["yadm", "bootstrap"], {}


@dep(cmd="nix-env")
async def nix() -> CommandGenerator:
    yield ["nix-env", "-u", "*"], {}


async def is_sudo_required() -> bool:
    for fn in DEP_FNS:
        # underlying generator function lives on __wrapped__ via functools.wraps
        gen_fn = cast(Callable[[], CommandGenerator], fn.__wrapped__)  # type: ignore[attr-defined]
        async for p_args, _ in gen_fn():
            if p_args and p_args[0] == "sudo":
                return True
    return False


async def verify_sudo(window: Window) -> bool:
    # validate password by running sudo -A -v; helper returns wrong creds → false
    proc = await asyncio.create_subprocess_exec(
        "sudo",
        "-A",
        "-v",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        window.anchor_printf(f"sudo: {stderr.decode().strip() or 'authentication failed'}")
        return False
    return True


@click.command()
@click.option(
    "--anchor/--no-anchor",
    default=None,
    help="Force anchored TUI on/off. Default: auto (on if stdout is a tty).",
)
async def renovo(anchor: bool | None) -> None:
    with Window(Red) as window:
        if anchor is False or (anchor is None and not sys.stdout.isatty()):
            window.enable_plain_mode()

        async def run_all() -> None:
            async with asyncio.TaskGroup() as upgrades:
                for fn in DEP_FNS:
                    upgrades.create_task(fn(window))

        if not await is_sudo_required():
            await run_all()
            return

        with askpass_helper(get_pass()) as helper:
            os.environ["SUDO_ASKPASS"] = helper
            if not await verify_sudo(window):
                return
            await run_all()


if __name__ == "__main__":
    anyio.run(renovo.main)
