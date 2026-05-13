"""Tests mirror spotitube/sys/anchor/window_test.go.

Output stream redirected to StringIO; stdin patched for `reads`. Assertions
check substrings — exact ANSI sequences differ between go's `cursor` lib and
this port, so verifying *what was written* (not byte-for-byte) is the right
contract.
"""

from __future__ import annotations

import io
import sys
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from anchor import Normal, Window


@contextmanager
def _stdin(text: str) -> Iterator[None]:
    saved = sys.stdin
    sys.stdin = io.StringIO(text)
    try:
        yield
    finally:
        sys.stdin = saved


def test_window() -> None:
    buf = io.StringIO()
    window = Window(Normal, stream=buf)
    lot = window.lot("lot")
    lot.printf("lot text 1")
    window.printf("default text 1")
    window.anchor_printf("anchor text")
    window.printf("default text 2")
    window.lot("lot").printf("lot text 2")
    lot.wipe()
    lot.close("closure")

    with _stdin("input\n"):
        value = window.reads("prompt:")

    output = buf.getvalue()
    assert "lot text 1" in output
    assert "default text 1" in output
    assert "anchor text" in output
    assert "default text 2" in output
    assert "lot text 2" in output
    assert "closure" in output
    assert "prompt" in output
    assert value == "input"


def test_window_plain() -> None:
    buf = io.StringIO()
    window = Window(Normal, stream=buf)
    lot = window.lot("lot")
    window.enable_plain_mode()
    lot.printf("lot text 1")
    window.printf("default text 1")
    window.anchor_printf("anchor text")

    output = buf.getvalue()
    assert "lot text 1" in output
    assert "default text 1" in output
    assert "anchor text" in output


def test_lot_dedupe() -> None:
    """Same alias returns same Lot instance — caller can reach the slot
    without holding the original reference."""
    window = Window(stream=io.StringIO())
    first = window.lot("worker")
    second = window.lot("worker")
    assert first is second


def test_close_freezes_style() -> None:
    """Closed lots render with idle color regardless of subsequent mutation."""
    window = Window(stream=io.StringIO())
    lot = window.lot("job")
    lot.print("running")
    lot.close()
    assert lot._closed


def test_anchored_state_after_first_render() -> None:
    """Window starts unanchored; first render saves cursor + sets _anchored."""
    window = Window(stream=io.StringIO())
    assert not window._anchored
    window.lot("x")
    assert window._anchored


def test_flowing_lines_keep_block_count_stable() -> None:
    """printf is flowing — new line goes ABOVE the block, lots stay same count.
    Ensures we don't accidentally pin every flowing line as anchor."""
    window = Window(stream=io.StringIO())
    window.lot("x")
    lots_before = len(window._lots)
    anchors_before = len(window._anchors)
    for i in range(5):
        window.printf("flow %d", i)
    assert len(window._lots) == lots_before
    assert len(window._anchors) == anchors_before


def test_reads_returns_stripped() -> None:
    buf = io.StringIO()
    window = Window(stream=buf)
    with _stdin("  spaced input  \r\n"):
        value = window.reads("?")
    assert value == "spaced input"


@pytest.mark.parametrize("color", [Normal, "\x1b[31m", "\x1b[32m"])
def test_anchor_printf_accepts_any_color(color: str) -> None:
    window = Window(color, stream=io.StringIO())
    window.anchor_printf("hello %s", "world")


def test_no_extra_blank_lines_between_lot_prints() -> None:
    """Regression: lot.print called repeatedly must not accumulate blank rows.
    With the save/restore-cursor model, each redraw = N-1 \\n separators
    (rows joined by \\n, no trailing). For 20 redraws of 2 lots: 20 newlines."""
    buf = io.StringIO()
    window = Window(stream=buf)
    lot_a = window.lot("a")
    lot_b = window.lot("b")
    baseline_newlines = buf.getvalue().count("\n")
    for i in range(10):
        lot_a.print(f"a-{i}")
        lot_b.print(f"b-{i}")
    after_newlines = buf.getvalue().count("\n")
    delta = after_newlines - baseline_newlines
    assert delta == 20, f"expected 20 newlines from 20 redraws of 2 lots, got {delta}"
