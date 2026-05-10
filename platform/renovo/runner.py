#!/usr/bin/env python3

from __future__ import annotations

import asyncio
import functools
import hashlib
import os
import platform
import shutil
from collections.abc import AsyncGenerator, Callable, Coroutine
from getpass import getpass
from typing import Any, cast

import anyio
import asyncclick as click
from termcolor import colored

CommandSpec = tuple[list[str], dict[str, Any]]
CommandGenerator = AsyncGenerator[CommandSpec, None]
DepFn = Callable[[], Coroutine[Any, Any, None]]

DEP_FNS: set[DepFn] = set()
SHELL_COLORS = [
    "green",
    "yellow",
    "blue",
    "magenta",
    "cyan",
    "light_green",
    "light_yellow",
    "light_blue",
    "light_magenta",
    "light_cyan",
]


def color_by_name(keyword: str) -> str:
    return SHELL_COLORS[sum(hashlib.md5(keyword.encode()).hexdigest().encode()) % len(SHELL_COLORS)]


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


def print_line(program: str, line: str, color: str | None = None) -> None:
    if not line:
        return

    color = color if color else color_by_name(program)
    print(
        colored(program, color, attrs=["bold"]),
        colored(line, color),
        flush=True,
    )


async def spawn(*args: Any, **kwargs: Any) -> asyncio.subprocess.Process:
    return await asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        **kwargs,
    )


async def print_stream(
    stream: asyncio.StreamReader, program: str, color: str | None = None
) -> None:
    while line := await stream.readline():
        print_line(program, line.decode().rstrip(), color)


async def write_stdin(stdin: asyncio.StreamWriter | None = None) -> None:
    if not stdin:
        return

    stdin.write(get_pass().encode("utf-8") + b"\n")
    await stdin.drain()
    stdin.close()


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
        async def wrapper_dep(*args: Any, **kwargs: Any) -> None:
            if not (valid_cmd and valid_os and valid_env):
                print_line(program, "is unsupported")
                return

            print_line(program, "upgrading...")
            async for p_args, p_kwargs in func():
                sudo = p_args[0] == "sudo"
                if sudo:
                    p_args.insert(1, "-S")

                if process := await spawn(*p_args, **p_kwargs):
                    assert process.stdout is not None
                    assert process.stderr is not None
                    await asyncio.gather(
                        write_stdin(process.stdin if sudo else None),
                        print_stream(process.stdout, program),
                        print_stream(process.stderr, program, "red"),
                    )

            print_line(program, "upgrade complete.")

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


async def sudo() -> None:
    if await is_sudo_required():

        async def raise_on_auth_error(stream: asyncio.StreamReader) -> None:
            while line := await stream.readline():
                if "incorrect password" in line.decode().rstrip().lower():
                    raise click.ClickException("Authentication failed. Please try again.")

        if process := await spawn("sudo", "-S", "echo", "-n"):
            assert process.stderr is not None
            await asyncio.gather(
                write_stdin(process.stdin),
                raise_on_auth_error(process.stderr),
            )


@click.command()
async def renovo() -> None:
    if await is_sudo_required():
        await sudo()

    async with asyncio.TaskGroup() as upgrades:
        for fn in DEP_FNS:
            upgrades.create_task(fn())


if __name__ == "__main__":
    anyio.run(renovo.main)
