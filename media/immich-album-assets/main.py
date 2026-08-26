#!/usr/bin/env python3
"""List original paths of all assets in given Immich albums."""

from __future__ import annotations

import sys

from immich import Immich


def main(album_ids: list[str]) -> int:
    if not album_ids:
        print("usage: main.py <album_id> [<album_id> ...]", file=sys.stderr)
        return 2
    with Immich() as immich:
        for album_id in album_ids:
            for asset in immich.album_assets(album_id):
                print(asset.original_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
