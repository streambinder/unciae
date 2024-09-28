#!/usr/bin/env python

import asyncio
import functools
import hashlib
import os
import platform
import shutil
from typing import Any, AsyncGenerator, List, Optional, Tuple

import asyncclick as click
from termcolor import COLORS as colors
from termcolor import colored

COLORS = [color for color in colors.keys() if color not in ["black", "grey", "red"]]


def color_by_name(keyword: str) -> str:
    return COLORS[sum(hashlib.md5(keyword.encode()).hexdigest().encode()) % len(COLORS)]


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


def dep(
    cmd: str | None = None, platform_name: str = "", envs: Optional[List[str]] = None
):
    has_os = is_os(platform_name)
    has_envs = len([env for env in (envs or []) if env not in os.environ]) == 0

    def decorator_dep(func):
        program = func.__name__
        has_cmd = is_exec(cmd or program)

        @functools.wraps(func)
        async def wrapper_dep(*args: Any, **kwargs: Any):
            if not (has_cmd and has_os and has_envs):
                print_line(program, "is unsupported")
                return

            print_line(program, "upgrading...")

            async for p_args, p_kwargs in func(*args, **kwargs):
                if p_args[0].startswith("sudo"):
                    await asyncio.create_subprocess_exec(
                        "sudo", "-p", "Password: ", "echo", "-n"
                    )

                process = await asyncio.create_subprocess_exec(
                    *p_args,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    **p_kwargs,
                )

                await asyncio.gather(
                    print_stream(process.stdout, program),
                    print_stream(process.stderr, program, "red"),
                )

            print_line(program, "done.")

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


@dep(cmd="zsh", envs=["ZSH"])
async def omz() -> AsyncGenerator[Tuple[list, dict], None]:
    yield [f"{os.getenv('ZSH')}/tools/upgrade.sh"], {}


@dep(platform_name="darwin")
async def softwareupdate() -> AsyncGenerator[Tuple[list, dict], None]:
    yield ["softwareupdate", "-i", "-a"], {}


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
