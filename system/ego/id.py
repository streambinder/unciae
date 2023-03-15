#!/usr/bin/env python

import getpass
import hashlib
import os
import pyperclip
from typing import Tuple, Union

import asyncclick as click
import pykeepass as kpx


def capitalize_alpha(payload: str) -> str:
    for i, c in enumerate(payload):
        if c.isalpha():
            return payload[:i] + payload[i:].capitalize()
    return payload


async def keepass(payload: str, secret: str) -> Union[Tuple[str, str], None]:
    try:
        db = kpx.PyKeePass(
            os.environ.get("KPX_DB"), password=secret, keyfile=os.environ.get("KPX_KEY")
        )
        entry = db.find_entries(title=payload, first=True)
        return (entry.username, entry.password) if entry else None
    except kpx.exceptions.CredentialsError:
        return None


async def gen(payload: str, secret: str, iteration: int, length: int) -> Tuple[str, str]:
    raw = f"{payload}@{secret}{str('+') * (iteration - 1)}"
    hash = f"#{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"
    return ("", capitalize_alpha(hash[: length]))


@click.command()
@click.argument("payload")
@click.option("-u", "--username", is_flag=True, default=False)
@click.option("-i", "--iteration", type=int, default=1)
@click.option("-l", "--length", type=int, default=16)
async def id(payload: str, username: bool, iteration: int, length: int):
    secret = getpass.getpass("")
    data = await keepass(payload, secret) or await gen(
        payload, secret, iteration, length
    )
    pyperclip.copy(data[0] if username else data[1])
