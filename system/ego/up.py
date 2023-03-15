#!/usr/bin/env python

import distutils.spawn
import functools
import os
import platform

import asyncclick as click
import trio


def is_os(os: str) -> bool:
    return platform.system().lower().startswith(os.lower())


def is_exec(cmd: str) -> bool:
    return distutils.spawn.find_executable(cmd) is not None


def dep(cmd: str | None = None, os: str = ""):
    def decorator_dep(func):
        @functools.wraps(func)
        async def wrapper_dep(*args, **kwargs):
            if is_exec(cmd if cmd else func.__name__) and is_os(os):
                return await func(*args, **kwargs)
            print(f"{func.__name__} is unsupported")

        return wrapper_dep

    return decorator_dep


@dep(os="linux")
async def apt():
    apt_env = dict(os.environ, DEBIAN_FRONTEND="noninteractive")
    apt_prefix = [
        "apt",
        "-y",
        "-o",
        "Dpkg::Options::='--force-confdef'",
        "-o",
        "Dpkg::Options::='--force-confold'",
    ]
    await trio.run_process(apt_prefix + ["update"], env=apt_env)
    await trio.run_process(apt_prefix + ["upgrade"], env=apt_env)
    await trio.run_process(apt_prefix + ["dist-upgrade"], env=apt_env)
    await trio.run_process(apt_prefix + ["autoremove"], env=apt_env)


@dep()
async def brew():
    await trio.run_process(["brew", "update"])
    await trio.run_process(["brew", "upgrade"])


@dep()
async def managedsoftwareupdate():
    await trio.run_process(["sudo", "managedsoftwareupdate", "--installonly"])


@dep(cmd="zsh")
async def omz():
    await trio.run_process('zsh -c "source $HOME/.zshrc && omz update"', shell=True)


@dep(os="darwin")
async def softwareupdate():
    await trio.run_process(["softwareupdate", "-i", "-a"])


@dep()
async def yadm():
    await trio.run_process(["yadm", "pull"])
    await trio.run_process(["yadm", "submodule", "update", "--init", "--recursive"])
    await trio.run_process(["yadm", "bootstrap"])


@click.command()
async def up():
    async with trio.open_nursery() as nursery:
        nursery.start_soon(apt)
        nursery.start_soon(brew)
        nursery.start_soon(omz)
        nursery.start_soon(managedsoftwareupdate)
        nursery.start_soon(softwareupdate)
        nursery.start_soon(yadm)
