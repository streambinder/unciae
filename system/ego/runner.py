#!/usr/bin/env python

import asyncclick as click
from id import id as ego_id
from up import up as ego_up


@click.group()
async def ego():
    ...


ego.add_command(ego_id)
ego.add_command(ego_up)

if __name__ == "__main__":
    ego(_anyio_backend="trio")
