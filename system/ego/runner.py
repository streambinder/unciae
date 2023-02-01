#!/usr/bin/env python

import platform

import asyncclick as click
import trio


async def yadm():
    await trio.run_process(["yadm", "pull"])
    await trio.run_process(["yadm", "submodule", "update", "--init", "--recursive"])
    await trio.run_process(["yadm", "bootstrap"])


async def brew():
    await trio.run_process(["brew", "update"])
    await trio.run_process(["brew", "upgrade"])


async def softwareupdate():
    if platform.system() == "Darwin":
        await trio.run_process(["softwareupdate", "-i", "-a"])


async def omz():
    await trio.run_process('zsh -c "source $HOME/.zshrc && omz update"', shell=True)


@click.group()
async def ego():
    ...


@ego.command()
async def upgrade():
    async with trio.open_nursery() as nursery:
        nursery.start_soon(yadm)
        nursery.start_soon(brew)
        nursery.start_soon(softwareupdate)
        nursery.start_soon(omz)


if __name__ == "__main__":
    ego(_anyio_backend="trio")
