#!/usr/bin/env python

import distutils.spawn
import functools
import os
import platform
import random
import subprocess
from typing import AsyncGenerator

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

            async for process in func(
                *args,
                **kwargs | {"stdout": subprocess.PIPE, "stderr": subprocess.STDOUT},
            ):
                while data := await process.stdout.receive_some():
                    print(
                        colored(data.decode(), col),
                        end="\r",
                    )

        return wrapper_dep

    return decorator_dep


@dep(os="linux")
async def apt(*args, **kwargs) -> AsyncGenerator[trio.Process, None]:
    apt_env = dict(os.environ, DEBIAN_FRONTEND="noninteractive")
    apt_prefix = [
        "apt",
        "-y",
        "-o",
        "Dpkg::Options::='--force-confdef'",
        "-o",
        "Dpkg::Options::='--force-confold'",
    ]
    yield await trio.lowlevel.open_process(
        apt_prefix + ["update"],
        env=apt_env,
        *args,
        **kwargs,
    )
    yield await trio.lowlevel.open_process(
        apt_prefix + ["upgrade"],
        env=apt_env,
        *args,
        **kwargs,
    )
    yield await trio.lowlevel.open_process(
        apt_prefix + ["dist-upgrade"],
        env=apt_env,
        *args,
        **kwargs,
    )
    yield await trio.lowlevel.open_process(
        apt_prefix + ["autoremove"],
        env=apt_env,
        *args,
        **kwargs,
    )


@dep()
async def brew(*args, **kwargs) -> AsyncGenerator[trio.Process, None]:
    yield await trio.lowlevel.open_process(
        ["brew", "update"],
        *args,
        **kwargs,
    )
    yield await trio.lowlevel.open_process(
        ["brew", "upgrade"],
        *args,
        **kwargs,
    )


@dep()
async def managedsoftwareupdate(*args, **kwargs) -> AsyncGenerator[trio.Process, None]:
    yield await trio.lowlevel.open_process(
        ["sudo", "managedsoftwareupdate", "--installonly"],
        *args,
        **kwargs,
    )


@dep(cmd="zsh")
async def omz(*args, **kwargs) -> AsyncGenerator[trio.Process, None]:
    yield await trio.lowlevel.open_process(
        'zsh -c "source $HOME/.zshrc && omz update"',
        shell=True,
        *args,
        **kwargs,
    )


@dep(os="darwin")
async def softwareupdate(*args, **kwargs) -> AsyncGenerator[trio.Process, None]:
    yield await trio.lowlevel.open_process(
        ["softwareupdate", "-i", "-a"],
        *args,
        **kwargs,
    )


@dep()
async def yadm(*args, **kwargs) -> AsyncGenerator[trio.Process, None]:
    yield await trio.lowlevel.open_process(
        ["yadm", "pull"],
        *args,
        **kwargs,
    )
    yield await trio.lowlevel.open_process(
        ["yadm", "submodule", "update", "--init", "--recursive"],
        *args,
        **kwargs,
    )
    yield await trio.lowlevel.open_process(
        ["yadm", "bootstrap"],
        *args,
        **kwargs,
    )


@click.command()
async def up():
    async with trio.open_nursery() as nursery:
        nursery.start_soon(apt)
        nursery.start_soon(brew)
        nursery.start_soon(omz)
        nursery.start_soon(managedsoftwareupdate)
        nursery.start_soon(softwareupdate)
        nursery.start_soon(yadm)
