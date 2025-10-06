#!/usr/bin/env python

import getpass
import hashlib
import os
from typing import Tuple, Union

import asyncclick as click
import pykeepass as kpx
import pyperclip


def capitalize_alpha(payload: str) -> str:
    for i, c in enumerate(payload):
        if c.isalpha():
            return payload[:i] + payload[i:].capitalize()
    return payload


async def keepass(payload: str, secret: str) -> Union[Tuple[str, str], None]:
    db_paths = os.environ.get("KPX_DB")
    if not db_paths:
        return None

    for path in db_paths.split(":"):
        try:
            db = kpx.PyKeePass(path, password=secret, keyfile=os.environ.get("KPX_KEY"))
            if entry := db.find_entries(title=payload, regex=True, first=True):
                return (entry.username, entry.password)
            if entry := db.find_entries(notes=payload, regex=True, first=True):
                return (entry.username, entry.password)
        except kpx.exceptions.CredentialsError:
            pass

    return None


async def gen(payload: str, secret: str, iteration: int, length: int) -> Tuple[str, str]:
    raw = f"{payload}@{secret}{str('+') * (iteration - 1)}"
    hashsum = f"#{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"
    return ("", capitalize_alpha(hashsum[:length]))


@click.command(name="id")
@click.argument("payload")
@click.option("-u", "--username", is_flag=True, default=False)
@click.option("-i", "--iteration", type=int, default=1)
@click.option("-l", "--length", type=int, default=16)
@click.option("-g", "--generate", is_flag=True, default=False)
async def cmd_id(payload: str, username: bool, iteration: int, length: int, generate: bool):
    if iteration > 1:
        generate = True
    secret = getpass.getpass()
    data = (await keepass(payload, secret) if not generate else None) or await gen(payload, secret, iteration, length)
    pyperclip.copy(data[0] if username else data[1])
