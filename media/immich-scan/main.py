#!/usr/bin/env python3
"""Trigger an Immich external-library scan covering the given path, wait for completion, run optional hook."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from typing import Any

from immich import Immich, ImmichError

QUEUE = "library"
POLL_INTERVAL_S = 5.0
DEFAULT_TIMEOUT_S = 30 * 60


def resolve_library(immich: Immich, target: str) -> dict[str, Any]:
    # an external library "covers" target if any of its importPaths is target or an ancestor
    target_abs = os.path.realpath(target)
    for library in immich.libraries():
        for import_path in library.get("importPaths", []):
            import_abs = os.path.realpath(import_path)
            if target_abs == import_abs or target_abs.startswith(import_abs + os.sep):
                return library
    raise ImmichError(f"no external library covers {target_abs}")


def wait_for_queue(immich: Immich, timeout_s: float) -> None:
    # require two consecutive idle reads to avoid racing the queue between the scan POST and the first fan-out job
    deadline = time.monotonic() + timeout_s
    idle_streak = 0
    while time.monotonic() < deadline:
        stats = immich.queue_status(QUEUE)
        pending = stats["active"] + stats["waiting"] + stats["delayed"]
        if pending == 0:
            idle_streak += 1
            if idle_streak >= 2:
                return
        else:
            idle_streak = 0
        print(
            f"  queue={QUEUE} active={stats['active']} waiting={stats['waiting']} "
            f"delayed={stats['delayed']} failed={stats['failed']}",
            file=sys.stderr,
        )
        time.sleep(POLL_INTERVAL_S)
    raise TimeoutError(f"queue {QUEUE} did not drain within {timeout_s:.0f}s")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", help="filesystem path under an external library importPath")
    parser.add_argument(
        "--hook",
        default=None,
        help='shell command to run on successful scan completion (e.g. "systemctl restart foo.service")',
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_S,
        help=f"max seconds to wait for {QUEUE} queue to drain (default: {DEFAULT_TIMEOUT_S})",
    )
    args = parser.parse_args(argv)

    with Immich() as immich:
        print(f"Resolving library for {args.path}... ", end="", file=sys.stderr)
        library = resolve_library(immich, args.path)
        print(f"{library['name']} ({library['id']})", file=sys.stderr)

        # the scan endpoint walks every importPath of the library, not just the requested subpath:
        # the API has no subpath filter (verified against OpenAPI on main). this CLI exists to
        # standardize the "scan + wait + hook" dance, not to scope the scan itself.
        print("Triggering scan... ", end="", file=sys.stderr)
        immich.scan_library(library["id"])
        print("queued", file=sys.stderr)

        print(
            f"Waiting for {QUEUE} queue to drain (timeout {args.timeout:.0f}s)...", file=sys.stderr
        )
        try:
            wait_for_queue(immich, args.timeout)
        except TimeoutError as exc:
            print(f"FAIL: {exc}", file=sys.stderr)
            return 1
        print("Scan complete", file=sys.stderr)

    if args.hook:
        print(f"Running hook: {args.hook}", file=sys.stderr)
        # shell=True is intentional — hook is operator-supplied, not user-tainted input
        subprocess.run(args.hook, shell=True, check=True)  # noqa: S602

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
