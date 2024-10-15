#!/usr/bin/env python

import asyncio
import functools
import hashlib
import os
import platform
import shutil
from getpass import getpass
from typing import Any, AsyncGenerator, List, Optional, Tuple

import asyncclick as click
from termcolor import colored

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
    return SHELL_COLORS[
        sum(hashlib.md5(keyword.encode()).hexdigest().encode()) % len(SHELL_COLORS)
    ]


def only_once(func):
    _run_attr = "_run"
    _value_attr = "_value"

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        if getattr(func, _run_attr, False):
            return getattr(func, _value_attr, None)

        value = func(*args, **kwargs)
        setattr(func, _value_attr, value)
        setattr(func, _run_attr, True)
        return value

    return wrapper


@only_once
def get_pass(program: Optional[str] = None) -> str:
    return getpass(f"Authenticate{' for ' + program if program else ''}: ")


def is_os(os_name: str) -> bool:
    return platform.system().lower().startswith(os_name.lower())


def is_exec(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def print_line(program: str, line: str, color: Optional[str] = None) -> None:
    color = color if color else color_by_name(program)
    print(
        colored(program, color, attrs=["bold"]),
        colored(line, color),
        flush=True,
    )


async def print_stream(stream, program, color: Optional[str] = None) -> None:
    while line := await stream.readline():
        print_line(program, line.decode().strip(), color)


async def write_stdin(stdin: Optional[asyncio.StreamWriter] = None) -> None:
    if not stdin:
        return

    stdin.writelines([get_pass().encode("utf-8") + b"\n"] * 100)
    await stdin.drain()


def dep(
    cmd: str | None = None,
    platform_name: str = "",
    env: Optional[List[str]] = None,
):
    valid_os = is_os(platform_name)
    valid_env = len([e for e in (env or []) if e not in os.environ]) == 0

    def decorator_dep(func):
        program = func.__name__
        valid_cmd = is_exec(cmd or program)

        @functools.wraps(func)
        async def wrapper_dep(*args: Any, **kwargs: Any):
            if not (valid_cmd and valid_os and valid_env):
                print_line(program, "is unsupported")
                return

            print_line(program, "upgrading...")
            async for p_args, p_kwargs in func(*args, **kwargs):
                sudo = p_args[0] == "sudo"
                if sudo:
                    get_pass(program)
                    p_args.insert(1, "-S")

                process = await asyncio.create_subprocess_exec(
                    *p_args,
                    stdin=asyncio.subprocess.PIPE if sudo else None,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    **p_kwargs,
                )
                await asyncio.gather(
                    write_stdin(process.stdin if sudo else None),
                    print_stream(process.stdout, program),
                    print_stream(process.stderr, program, "red"),
                )

            print_line(program, "upgrade complete.")

        return wrapper_dep

    return decorator_dep


@dep(platform_name="linux")
async def apt() -> AsyncGenerator[Tuple[list, dict], None]:
    kwargs = {"env": dict(os.environ, DEBIAN_FRONTEND="noninteractive")}
    apt_get = [
        "sudo",
        "apt-get",
        "-y",
    ]
    yield apt_get + ["update"], kwargs
    yield apt_get + ["upgrade"], kwargs
    yield apt_get + ["dist-upgrade"], kwargs
    yield apt_get + ["autoremove"], kwargs


@dep()
async def brew() -> AsyncGenerator[Tuple[list, dict], None]:
    yield ["brew", "update", "-q"], {}
    yield ["brew", "upgrade", "-q", "--greedy"], {}


@dep()
async def managedsoftwareupdate() -> AsyncGenerator[Tuple[list, dict], None]:
    yield ["sudo", "managedsoftwareupdate", "--installonly"], {}


@dep(cmd="zsh", env=["ZSH"])
async def omz() -> AsyncGenerator[Tuple[list, dict], None]:
    yield [f"{os.getenv('ZSH')}/tools/upgrade.sh"], {}


@dep(platform_name="darwin")
async def softwareupdate() -> AsyncGenerator[Tuple[list, dict], None]:
    yield ["sudo", "softwareupdate", "-iaR"], {}


@dep()
async def yadm() -> AsyncGenerator[Tuple[list, dict], None]:
    yield ["yadm", "pull"], {}
    yield ["yadm", "submodule", "update", "--init", "--recursive"], {}
    yield ["yadm", "bootstrap"], {}


@dep(cmd="nix-env")
async def nixenv() -> AsyncGenerator[Tuple[list, dict], None]:
    yield ["nix-env", "-u", "*"], {}


@click.command(name="up")
async def cmd_up():
    async with asyncio.TaskGroup() as upgrades:
        upgrades.create_task(apt())
        upgrades.create_task(brew())
        upgrades.create_task(omz())
        upgrades.create_task(managedsoftwareupdate())
        upgrades.create_task(softwareupdate())
        upgrades.create_task(yadm())
        upgrades.create_task(nixenv())
