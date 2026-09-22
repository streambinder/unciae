#!/usr/bin/env python3
"""Delete on-disk originals for trashed Immich assets, prune orphans, then empty trash.

NOTE: the reusable `immich` client gained `iter_metadata`/`trash_assets`/`libraries`
after the revision pinned in uv.lock, so main.py only relies on the long-stable
client surface (search_metadata, empty_trash) and does its own paging + raw HTTP
for the rest.
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from collections.abc import Iterator
from datetime import datetime
from typing import Any, cast

from immich import Asset, Immich

UNITS = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")

PAGE_SIZE = 1000
GUARD_SAMPLE_SIZE = 200
GUARD_MIN_EXIST_FRACTION = 0.05
TRASH_BATCH_SIZE = 1000
HTTP_TIMEOUT = 30.0


def human_size(num_bytes: float) -> str:
    unit_index = 0
    while num_bytes > 1024 and unit_index < len(UNITS) - 1:
        num_bytes /= 1024
        unit_index += 1
    return f"{num_bytes:.2f}{UNITS[unit_index]}"


def api_base() -> str:
    return (os.environ.get("IMMICH_API_BASE") or "http://localhost:2283").rstrip("/")


def api_key() -> str:
    key = os.environ.get("IMMICH_API_KEY")
    if not key:
        raise SystemExit("error: IMMICH_API_KEY not set")
    return key


def api_request(method: str, path: str, data: Any = None) -> Any:
    """Raw Immich API call for endpoints missing from the pinned client."""
    body = json.dumps(data).encode() if data is not None else None
    request = urllib.request.Request(
        f"{api_base()}/api{path}",
        data=body,
        headers={"Content-Type": "application/json", "x-api-key": api_key()},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
            raw = response.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"error: {method} {path} failed: HTTP {exc.code}") from exc


def get_libraries() -> list[dict[str, Any]]:
    return cast("list[dict[str, Any]]", api_request("GET", "/libraries"))


def trash_assets(ids: list[str]) -> None:
    """Move assets to trash via DELETE /assets (soft delete; purge with empty_trash)."""
    api_request("DELETE", "/assets", {"ids": ids})


def paged_search(immich: Immich, **filters: Any) -> Iterator[Asset]:
    """Yield every asset matching filters, paging through result pages.

    The pinned client only returns the first page, so page through here.
    """
    seen: set[str] = set()
    page = 1
    while True:
        batch = immich.search_metadata(page=page, size=PAGE_SIZE, **filters)
        fresh = [asset for asset in batch if asset.id not in seen]
        if not fresh:
            break
        yield from fresh
        seen.update(asset.id for asset in fresh)
        if len(batch) < PAGE_SIZE:
            break
        page += 1


def external_libraries() -> list[dict[str, Any]]:
    """Libraries backed by on-disk import paths (upload library has none)."""
    return [lib for lib in get_libraries() if lib.get("importPaths")]


def check_mount_guard(immich: Immich) -> list[dict[str, Any]]:
    """Abort unless the external library roots are really accessible.

    A missing or unmounted disk must never trigger mass deletion.
    """
    libraries = external_libraries()
    for library in libraries:
        paths = library.get("importPaths", [])
        if not any(os.path.isdir(path) for path in paths):
            raise SystemExit(
                f"error: no import path accessible for library {library.get('name')!r} "
                f"({paths}); aborting to avoid mass deletion"
            )
    sampled = 0
    existing = 0
    for library in libraries:
        for asset in paged_search(immich, libraryId=library["id"]):
            sampled += 1
            if os.path.isfile(asset.original_path):
                existing += 1
            if sampled >= GUARD_SAMPLE_SIZE:
                break
        if sampled >= GUARD_SAMPLE_SIZE:
            break
    if sampled and existing / sampled < GUARD_MIN_EXIST_FRACTION:
        raise SystemExit(
            f"error: only {existing}/{sampled} sampled files exist on disk; "
            "the library storage looks unmounted or empty, aborting"
        )
    return libraries


def find_orphans(immich: Immich, libraries: list[dict[str, Any]]) -> list[Asset]:
    """Non-trashed assets in external libraries whose original file is gone."""
    orphans: list[Asset] = []
    for library in libraries:
        for asset in paged_search(immich, libraryId=library["id"]):
            if not os.path.isfile(asset.original_path):
                orphans.append(asset)
    return orphans


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-prune-orphans",
        action="store_true",
        help="skip orphan pruning; only delete on-disk originals of trashed assets",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print what would be deleted/trashed without changing anything",
    )
    args = parser.parse_args()

    cutoff = datetime.now().astimezone().isoformat()
    with Immich() as immich:
        libraries: list[dict[str, Any]] = []
        if not args.no_prune_orphans:
            libraries = check_mount_guard(immich)

        print("Deleting originals on disk...")
        size_total = 0
        deleted = 0
        for asset in paged_search(immich, trashedBefore=cutoff, isOffline=False):
            path = asset.original_path
            if not os.path.isfile(path):
                continue
            size = os.path.getsize(path)
            if args.dry_run:
                print(f"would delete {human_size(size)} {path}")
            else:
                print(f"{human_size(size)} {path}")
                os.remove(path)
            size_total += size
            deleted += 1
        print(
            f"{human_size(size_total)} from {deleted} files{' (dry run)' if args.dry_run else ''}\n"
        )

        if not args.no_prune_orphans:
            print("Pruning orphan assets...")
            orphans = find_orphans(immich, libraries)
            for asset in orphans:
                print(f"{'would trash' if args.dry_run else 'trashing'} {asset.original_path}")
            if orphans and not args.dry_run:
                ids = [asset.id for asset in orphans]
                for i in range(0, len(ids), TRASH_BATCH_SIZE):
                    trash_assets(ids[i : i + TRASH_BATCH_SIZE])
            print(f"{len(orphans)} orphan assets{' (dry run)' if args.dry_run else ''}\n")
        elif args.dry_run:
            print("orphan pruning disabled (--no-prune-orphans)\n")

        print("Emptying trash on Immich...")
        if args.dry_run:
            print("would empty trash")
        else:
            count = immich.empty_trash()
            if count:
                print(f"unregistered {count} assets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
