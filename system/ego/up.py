#!/usr/bin/env python

import functools
import hashlib
import os
import platform
import shutil
import subprocess
from typing import AsyncGenerator, List, Optional, Tuple

import asyncclick as click
import trio
from termcolor import COLORS as colors
from termcolor import colored

COLORS = list(colors.keys())


def color_by_name(keyword: str) -> str:
    return COLORS[sum(hashlib.md5(keyword.encode()).hexdigest().encode()) % len(COLORS)]


async def sudo_subshell() -> trio.Process:
    return await trio.run_process(["sudo", "-p", "Password: ", "echo", "-n"])


def is_os(os_name: str) -> bool:
    return platform.system().lower().startswith(os_name.lower())


def is_exec(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def dep(
    cmd: str | None = None, platform_name: str = "", envs: Optional[List[str]] = None
):
    has_os = is_os(platform_name)
    has_envs = len([env for env in (envs or []) if env not in os.environ]) == 0

    def decorator_dep(func):
        has_cmd = is_exec(cmd or func.__name__)
        color = color_by_name(func.__name__)

        @functools.wraps(func)
        async def wrapper_dep(*args, **kwargs):
            if not (has_cmd and has_os and has_envs):
                print(
                    colored(func.__name__, color, attrs=["bold"]),
                    colored("is unsupported", color),
                )
                return

            print(
                colored(func.__name__, color, attrs=["bold"]),
                colored("upgrading...", color),
                flush=True,
            )

            async for p_args, p_kwargs in func(*args, **kwargs):
                if (isinstance(p_args[0], list) and p_args[0][0] == "sudo") or (
                    isinstance(p_args[0], str) and p_args[0].startswith("sudo")
                ):
                    await sudo_subshell()

                process = await trio.lowlevel.open_process(
                    *p_args,
                    **(
                        p_kwargs
                        | {"stdout": subprocess.PIPE, "stderr": subprocess.STDOUT}
                    ),
                )

                while data := await process.stdout.receive_some():
                    for line in data.decode().splitlines():
                        if line := line.strip():
                            print(
                                colored(func.__name__, color, attrs=["bold"]),
                                colored(line, color),
                                flush=True,
                            )
            print(
                colored(func.__name__, color, attrs=["bold"]),
                colored("done.", color),
                flush=True,
            )

        return wrapper_dep

    return decorator_dep


@dep(platform_name="linux")
async def apt() -> AsyncGenerator[Tuple[list, dict], None]:
    apt_env = dict(os.environ, DEBIAN_FRONTEND="noninteractive")
    apt_prefix = [
        "sudo",
        "apt-get",
        "-y",
    ]
    yield [apt_prefix + ["update"]], {"env": apt_env}
    yield [apt_prefix + ["upgrade"]], {"env": apt_env}
    yield (
        [apt_prefix + ["dist-upgrade"]],
        {"env": apt_env},
    )
    yield [apt_prefix + ["autoremove"]], {"env": apt_env}


@dep()
async def brew() -> AsyncGenerator[Tuple[list, dict], None]:
    yield [["brew", "update", "-q"]], {}
    yield [["brew", "upgrade", "-q", "--greedy"]], {}


@dep()
async def managedsoftwareupdate() -> AsyncGenerator[Tuple[list, dict], None]:
    yield [["sudo", "managedsoftwareupdate", "--installonly"]], {}


@dep(cmd="zsh", envs=["ZSH"])
async def omz() -> AsyncGenerator[Tuple[list, dict], None]:
    yield [[f"{os.getenv('ZSH')}/tools/upgrade.sh"]], {}


@dep(platform_name="darwin")
async def softwareupdate() -> AsyncGenerator[Tuple[list, dict], None]:
    yield [["softwareupdate", "-i", "-a"]], {}


@dep()
async def yadm() -> AsyncGenerator[Tuple[list, dict], None]:
    yield [["yadm", "pull"]], {}
    yield [["yadm", "submodule", "update", "--init", "--recursive"]], {}
    yield [["yadm", "bootstrap"]], {}


@dep(cmd="nix-env")
async def nixenv() -> AsyncGenerator[Tuple[list, dict], None]:
    yield [["nix-env", "-u", "*"]], {}


@click.command(name="up")
async def cmd_up():
    async with trio.open_nursery() as nursery:
        nursery.start_soon(apt)
        nursery.start_soon(brew)
        nursery.start_soon(omz)
        nursery.start_soon(managedsoftwareupdate)
        nursery.start_soon(softwareupdate)
        nursery.start_soon(yadm)
        nursery.start_soon(nixenv)
