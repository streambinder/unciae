#!/usr/bin/env python

import platform

import asyncclick as click
import trio

yadm_update_chan_send, yadm_update_chan_recv = trio.open_memory_channel(0)
brew_update_chan_send, brew_update_chan_recv = trio.open_memory_channel(0)


async def yadm_pull():
    await trio.run_process(["yadm", "pull"])
    await yadm_update_chan_send.send(True)


async def yadm_bootstrap():
    async with yadm_update_chan_recv:
        async for event in yadm_update_chan_recv:
            if event:
                await trio.run_process(["yadm", "bootstrap"])
                break


async def brew_update():
    await trio.run_process(["brew", "update"])
    await brew_update_chan_send.send(True)


async def brew_upgrade():
    async with brew_update_chan_recv:
        async for event in brew_update_chan_recv:
            if event:
                await trio.run_process(["brew", "upgrade"])
                break


async def softwareupdate():
    if platform.system() == "Darwin":
        await trio.run_process(["softwareupdate", "-i", "-a"])


async def omz_update():
    await trio.run_process('zsh -c "source $HOME/.zshrc && omz update"', shell=True)


@click.group()
async def ego():
    ...


@ego.command()
async def upgrade():
    async with trio.open_nursery() as nursery:
        nursery.start_soon(yadm_pull)
        nursery.start_soon(yadm_bootstrap)
        nursery.start_soon(brew_update)
        nursery.start_soon(brew_upgrade)
        nursery.start_soon(softwareupdate)
        nursery.start_soon(omz_update)


if __name__ == "__main__":
    ego(_anyio_backend="trio")
