#!/usr/bin/env python

import anyio
import asyncclick as click
from up import cmd_up


@click.group()
async def ego(): ...


ego.add_command(cmd_up)

if __name__ == "__main__":
    anyio.run(ego.main)
