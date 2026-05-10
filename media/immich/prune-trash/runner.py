#!/usr/bin/env python3
"""Delete on-disk originals for trashed Immich assets, then empty trash."""

from __future__ import annotations

import os
from datetime import datetime

from immich import Immich

UNITS = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")


def human_size(num_bytes: float) -> str:
    unit_index = 0
    while num_bytes > 1024 and unit_index < len(UNITS) - 1:
        num_bytes /= 1024
        unit_index += 1
    return f"{num_bytes:.2f}{UNITS[unit_index]}"


def main() -> int:
    cutoff = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    with Immich() as immich:
        print("Deleting originals on disk...")
        size_total = 0
        for asset in immich.search_metadata(trashedBefore=cutoff, isOffline=False):
            path = asset.original_path
            if not os.path.isfile(path):
                continue
            size = os.path.getsize(path)
            print(f"{human_size(size)} {path}")
            os.remove(path)
            size_total += size
        print(f"{human_size(size_total)} saved on disk\n")

        print("Emptying trash on Immich...")
        count = immich.empty_trash()
        if count:
            print(f"unregistered {count} assets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
