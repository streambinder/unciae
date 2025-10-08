#!/usr/bin/env python

import anyio
import asyncclick as click
from id import cmd_id
from up import cmd_up


@click.group()
async def ego(): ...


ego.add_command(cmd_id)
ego.add_command(cmd_up)

if __name__ == "__main__":
    anyio.run(ego.main)
