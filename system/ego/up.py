#!/usr/bin/env python

import distutils.spawn
import functools
import os
import platform
import random
import subprocess
from typing import AsyncGenerator, Tuple

import asyncclick as click
import trio
from termcolor import COLORS as colors
from termcolor import colored

COLORS = [
    k
    for k in colors.keys()
    if k not in ["light_grey", "light_red"] and k.startswith("light")
]
random.shuffle(COLORS)


def next_color() -> str:
    global COLORS
    col, COLORS = COLORS[0], COLORS[1:] + [COLORS[0]]
    return col


async def sudo_subshell() -> trio.Process:
    return await trio.run_process(["sudo", "-p", "Password: ", "echo", "-n"])


def is_os(os: str) -> bool:
    return platform.system().lower().startswith(os.lower())


def is_exec(cmd: str) -> bool:
    return distutils.spawn.find_executable(cmd) is not None


def dep(cmd: str | None = None, os: str = ""):
    col = next_color()

    def decorator_dep(func):
        @functools.wraps(func)
        async def wrapper_dep(*args, **kwargs):
            if not (is_exec(cmd or func.__name__) and is_os(os)):
                print(colored(f"{func.__name__} is unsupported", col))
                return

            async for p_args, p_kwargs in func(*args, **kwargs):
                if (type(p_args[0]) == list and p_args[0][0] == "sudo") or (
                    type(p_args[0]) == str and p_args[0].startswith("sudo")
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
                    print(
                        colored(data.decode(), col),
                        end="\r",
                    )

        return wrapper_dep

    return decorator_dep


@dep(os="linux")
async def apt() -> AsyncGenerator[Tuple[list, dict], None]:
    apt_env = dict(os.environ, DEBIAN_FRONTEND="noninteractive")
    apt_prefix = [
        "apt",
        "-y",
        "-o",
        "Dpkg::Options::='--force-confdef'",
        "-o",
        "Dpkg::Options::='--force-confold'",
    ]
    yield [apt_prefix + ["update"]], {"env": apt_env}
    yield [apt_prefix + ["upgrade"]], {"env": apt_env}
    yield [apt_prefix + ["dist-upgrade"]], {"env": apt_env},
    yield [apt_prefix + ["autoremove"]], {"env": apt_env}


@dep()
async def brew() -> AsyncGenerator[Tuple[list, dict], None]:
    yield [["brew", "update", "-q"]], {}
    yield [["brew", "upgrade", "-q"]], {}


@dep()
async def managedsoftwareupdate(
    *args, **kwargs
) -> AsyncGenerator[Tuple[list, dict], None]:
    yield [["sudo", "managedsoftwareupdate", "--installonly"]], {}


@dep(cmd="zsh")
async def omz() -> AsyncGenerator[Tuple[list, dict], None]:
    yield ['zsh -c "source $HOME/.zshrc && omz update"'], {"shell": True}


@dep(os="darwin")
async def softwareupdate(*args, **kwargs) -> AsyncGenerator[Tuple[list, dict], None]:
    yield [["softwareupdate", "-i", "-a"]], {}


@dep()
async def yadm() -> AsyncGenerator[Tuple[list, dict], None]:
    yield [["yadm", "pull"]], {}
    yield [["yadm", "submodule", "update", "--init", "--recursive"]], {}
    yield [["yadm", "bootstrap"]], {}


@click.command()
async def up():
    async with trio.open_nursery() as nursery:
        nursery.start_soon(apt)
        nursery.start_soon(brew)
        nursery.start_soon(omz)
        nursery.start_soon(managedsoftwareupdate)
        nursery.start_soon(softwareupdate)
        nursery.start_soon(yadm)
