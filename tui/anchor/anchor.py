"""Three-tier TUI line manager.

Port of github.com/streambinder/spotitube/sys/anchor.

Three line categories layered in a terminal window, bottom-anchored stack:

    1. Default stdout lines — flow normally upward as new lines arrive.
    2. Anchor lines — sticky between stdout flow and lots block. Persist once
       printed; new default output scrolls past them but they stay re-rendered
       at their slot on every redraw.
    3. Lots — named, mutable single-line slots at the very bottom. `Lot.print`
       overwrites in place; closing a lot freezes its content with idle style.

Redraw model: the `(anchors + lots)` block is positioned via relative
cursor-up (CUU) movement, matching the Go original. We track how many rows
the block currently occupies; on redraw we CUU that many rows, clear each
line, then rewrite all rows top-to-bottom. For flowing lines (printf): erase
the block, write data + \\n (pushing it into scrollback), then redraw.

This avoids DECSC/DECRC (save/restore cursor), which uses absolute positions
that desync when terminal scrolling pushes content into the scrollback — a
problem that manifests after CTRL+C or when the cursor starts near the
viewport bottom.

Plain mode disables cursor manipulation and color — every print becomes a
plain `print` line, useful for non-tty / log-capture contexts.
"""

from __future__ import annotations

import re
import shutil
import sys
import threading
from typing import TextIO

from colorama import Fore, Style
from colorama import init as _colorama_init

_colorama_init()

__all__ = [
    "Black",
    "Blue",
    "Cyan",
    "Green",
    "Lot",
    "Magenta",
    "Normal",
    "Red",
    "White",
    "Window",
    "Yellow",
]

# style sentinels — opaque tokens, formatted via _style()
Black = Fore.BLACK
Blue = Fore.BLUE
Cyan = Fore.CYAN
Green = Fore.GREEN
Magenta = Fore.MAGENTA
Normal = ""
Red = Fore.RED
White = Fore.WHITE
Yellow = Fore.YELLOW

_BOLD = Style.BRIGHT
_RESET = Style.RESET_ALL
_IDLE_COLOR = Fore.WHITE
_IDLE = "idle"
_DEFAULT_DONE = "done"

_ESC = "\x1b["
# per-line clear: move up 1, erase the line, carriage return
_UP_AND_CLEAR = f"{_ESC}1A{_ESC}2K\r"
_CLEAR_LINE = f"{_ESC}2K"
_CURSOR_DOWN = f"{_ESC}1B"

# strips ANSI SGR sequences for visible-width measurement
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _style(color: str, bold: bool, text: str) -> str:
    if not color and not bold:
        return text
    return f"{_BOLD if bold else ''}{color}{text}{_RESET}"


def _visible_len(text: str) -> int:
    return len(_ANSI_RE.sub("", text))


def _truncate(text: str, max_width: int) -> str:
    """Cut to max_width visible chars, preserving ANSI styling. Naive: walks
    the string char-by-char skipping ANSI runs. Adequate for single-line
    status output; not a full Unicode width handler (no East-Asian wide chars,
    no combining marks)."""
    if _visible_len(text) <= max_width:
        return text
    out: list[str] = []
    visible = 0
    i = 0
    while i < len(text) and visible < max_width:
        match = _ANSI_RE.match(text, i)
        if match:
            out.append(match.group(0))
            i = match.end()
            continue
        out.append(text[i])
        visible += 1
        i += 1
    # close any open SGR with reset to avoid bleeding style into next line
    out.append(_RESET)
    return "".join(out)


class Window:
    """Bottom-anchored line manager.

    `anchor_color` styles `anchor_printf` output. Lots use bold by default for
    their alias prefix; the data segment inherits the lot's current style
    (bold while active, idle-white once closed).
    """

    def __init__(self, anchor_color: str = Normal, stream: TextIO | None = None) -> None:
        self._anchors: list[str] = []
        self._lots: list[Lot] = []
        self._aliases: dict[str, int] = {}
        self._anchor_color = anchor_color
        self._lot_header_bold = True
        self._lock = threading.RLock()
        self._plain = False
        self._stream = stream if stream is not None else sys.stdout
        # how many rows the block currently occupies on screen. the cursor
        # always sits at the end of the last row (bottom of the block).
        self._block_rows = 0

    def enable_plain_mode(self) -> None:
        self._anchor_color = Normal
        self._lot_header_bold = False
        self._plain = True

    def lot(self, alias: str) -> Lot:
        with self._lock:
            existing_id = self._aliases.get(alias)
            if existing_id is not None:
                return self._lots[existing_id]
            new_lot = Lot(
                window=self,
                lot_id=len(self._lots),
                alias=alias,
                bold=self._lot_header_bold,
            )
            self._aliases[alias] = len(self._lots)
            self._lots.append(new_lot)
            if not self._plain:
                self._redraw_block()
            return new_lot

    def printf(self, fmt: str, *args: object) -> None:
        self._emit_flowing(fmt % args if args else fmt, sticky=False)

    def anchor_printf(self, fmt: str, *args: object) -> None:
        rendered = fmt % args if args else fmt
        self._emit_flowing(_style(self._anchor_color, False, rendered), sticky=True)

    def reads(self, label: str, *args: object) -> str:
        """Prompt + read a line of input. Repaints stack after entry."""
        with self._lock:
            if self._plain:
                self._stream.write((label % args if args else label) + " ")
                self._stream.flush()
                return sys.stdin.readline().strip().rstrip("\r\n")

            # erase block to make room for the prompt
            self._erase_block()
            prompt = (label % args if args else label) + " "
            self._stream.write(prompt)
            self._stream.flush()
            value = sys.stdin.readline().strip().rstrip("\r\n")
            # readline's trailing \n moved cursor to next line; redraw block
            self._redraw_block()
            return value

    def close(self) -> None:
        """Drop cursor below the block so the next external write (shell prompt
        on program exit, follow-up print, etc.) starts on a fresh line. Safe to
        call multiple times."""
        with self._lock:
            if self._plain or not self._block_rows:
                return
            self._stream.write("\r\n")
            self._block_rows = 0
            self._stream.flush()

    def __enter__(self) -> Window:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # internals

    def _erase_block(self) -> None:
        """Move to block start and clear each line; resets _block_rows to 0.
        After this, the cursor is at column 0 of what was the first block row."""
        if not self._block_rows:
            return
        # cursor is at end of last row. move up (block_rows - 1) times to
        # reach the first row, clearing each line we pass through.
        buf = [_CLEAR_LINE]  # clear the current (bottom) row
        for _ in range(self._block_rows - 1):
            buf.append(_UP_AND_CLEAR)
        buf.append("\r")  # ensure column 0
        self._stream.write("".join(buf))
        self._block_rows = 0

    def _redraw_block(self) -> None:
        """Erase existing block, rewrite all rows from the current cursor.
        Uses relative cursor movement — immune to scroll desync."""
        self._erase_block()

        max_w = self._max_width()
        rows = [_truncate(line, max_w) for line in self._anchors]
        rows.extend(_truncate(lot._render(), max_w) for lot in self._lots)
        self._block_rows = len(rows)
        if rows:
            self._stream.write("\r\n".join(rows))
        self._stream.flush()

    def _emit_flowing(self, data: str, sticky: bool) -> None:
        with self._lock:
            if self._plain:
                self._stream.write(data + "\n")
                self._stream.flush()
                return
            if sticky:
                self._anchors.append(data)
                self._redraw_block()
                return
            # flowing line: erase block, write data to scrollback, redraw
            self._erase_block()
            self._stream.write(_truncate(data, self._max_width()) + "\r\n")
            self._redraw_block()

    def _max_width(self) -> int:
        try:
            return max(1, shutil.get_terminal_size().columns - 1)
        except OSError:
            return 80


class Lot:
    """Mutable single-line slot anchored at the bottom of the window."""

    def __init__(self, window: Window, lot_id: int, alias: str, bold: bool) -> None:
        self._window = window
        self._id = lot_id
        self._alias = alias
        self._bold = bold
        self._data = ""
        self._closed = False

    def print(self, message: str) -> None:
        with self._window._lock:
            self._data = message
            if self._window._plain:
                self._window._stream.write(f"{self._alias} {message}\n")
                self._window._stream.flush()
                return
            self._window._redraw_block()

    def printf(self, fmt: str, *args: object) -> None:
        self.print(fmt % args if args else fmt)

    def wipe(self) -> None:
        self.print(_IDLE)

    def close(self, message: str | None = None) -> None:
        if not self._window._plain:
            self._closed = True
        self.print(message if message is not None else _DEFAULT_DONE)

    def _render(self) -> str:
        if self._closed:
            return _style(_IDLE_COLOR, False, _format_alias(self._alias) + self._data)
        header = _style(Normal, self._bold, _format_alias(self._alias))
        if self._data == _IDLE:
            body = _style(_IDLE_COLOR, False, self._data)
        else:
            body = _style(Normal, False, self._data)
        return header + body


def _format_alias(alias: str) -> str:
    return f"({alias}) "
