#!/usr/bin/env python3
"""Trigger refresh-metadata + regenerate-thumbnail jobs for given Immich assets."""

from __future__ import annotations

import os
import sys

from immich import Immich

JOBS = ("refresh-metadata", "regenerate-thumbnail")


def resolve_asset_id(immich: Immich, fname: str) -> str | None:
    dirname = os.path.realpath(os.path.dirname(fname))
    basename = os.path.basename(fname)
    fullname = os.path.join(dirname, basename)
    for asset in immich.search_metadata(originalFileName=basename, originalPath=dirname):
        if asset.original_path == fullname:
            return asset.id
    return None


def main(fnames: list[str]) -> int:
    if not fnames:
        print("usage: runner.py <file> [<file> ...]", file=sys.stderr)
        return 2
    with Immich() as immich:
        for fname in fnames:
            basename = os.path.basename(fname)
            dirname = os.path.realpath(os.path.dirname(fname))
            print(f"Processing {basename} at {dirname}...")

            print("Fetching asset ID... ", end="")
            asset_id = resolve_asset_id(immich, fname)
            if not asset_id:
                print("FAIL")
                continue
            print(asset_id)

            for job in JOBS:
                print(f"Launching {job} job... ", end="")
                immich.run_asset_jobs([asset_id], job)
                print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
