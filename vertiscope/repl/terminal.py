"""Terminal I/O: decode real input into events, paint state onto a screen.

The mouse
---------
Terminals report the mouse as escape sequences on stdin. In SGR mode (xterm
1006) a press is::

    ESC [ < b ; x ; y M          release is the same with a trailing 'm'

where ``b`` packs the button and modifiers, and ``x``/``y`` are 1-based
columns and rows. So the mouse arrives as *bytes*, and turning a physical
click into a :class:`~vertiscope.repl.model.MouseEvent` is an ordinary parser over
those bytes — exhaustively testable, no mouse required. The physical device is
the terminal's problem.

SGR (1006) rather than the original X10 encoding, which packs coordinates into
single bytes as ``value + 32`` and therefore cannot address a column past 223.
A wide terminal would silently mis-report clicks on the right of the screen.

Wheel events come through the same sequence with bit 6 set, so scrolling needs
no separate mechanism.

A sequence does not have to arrive all at once, though, and a click is a dozen
bytes. :func:`decode` is a pure function of one chunk, which is the right shape
for a test that hands it a whole sequence and the wrong one for a loop reading
whatever showed up: split anywhere inside, ``ESC [ < 0 ; 10 ; 5 M`` decoded as
the keystrokes ``;105M`` and typed them into the focused field.
:func:`decode_stream` is the same parser with the unterminated tail carried to
the next chunk, and it is what the loop uses.

Raw mode
--------
Mouse reporting and key-by-key input both need the terminal out of line mode.
:class:`RawTerminal` enables it, and restores on the way out *including on an
exception* — a crash that leaves a terminal in raw mode with mouse reporting
on leaves the user's shell unusable, which is a much worse failure than the
one that caused it.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from typing import Iterator, List, Optional, Sequence, Tuple

from .model import Event, KeyEvent, MouseEvent, ReplState, Widget, WidgetKind

__all__ = ["decode", "decode_stream", "RawTerminal", "paint",
           "ENABLE_MOUSE", "DISABLE_MOUSE"]

# 1000 = report press/release, 1002 = also report drag, 1006 = SGR encoding.
ENABLE_MOUSE = "\x1b[?1000h\x1b[?1002h\x1b[?1006h"
DISABLE_MOUSE = "\x1b[?1006l\x1b[?1002l\x1b[?1000l"
HIDE_CURSOR = "\x1b[?25l"
SHOW_CURSOR = "\x1b[?25h"
ALT_SCREEN = "\x1b[?1049h"
MAIN_SCREEN = "\x1b[?1049l"

_SGR_MOUSE = re.compile(r"\x1b\[<(\d+);(\d+);(\d+)([Mm])")

_KEYS = {
    "\x1b[A": "up", "\x1b[B": "down", "\x1b[C": "right", "\x1b[D": "left",
    "\x1b[H": "home", "\x1b[F": "end",
    "\x1b[5~": "pageup", "\x1b[6~": "pagedown",
    "\x1b[3~": "delete",
    "\r": "enter", "\n": "enter",
    "\x7f": "backspace", "\x08": "backspace",
    "\t": "tab", "\x1b[Z": "shifttab",
    # SS3: the same keys as terminals send them in *application cursor mode*
    # (`ESC O A` rather than `ESC [ A`). Without these, `_skip_escape` consumed
    # `ESC O` and left the final byte to be emitted as printable text — so an
    # arrow key typed a literal "A" into whatever field had focus, which is
    # precisely the behaviour the decoder's docstring says it avoids. A
    # terminal left in application mode by a previous program is enough.
    "\x1bOA": "up", "\x1bOB": "down", "\x1bOC": "right", "\x1bOD": "left",
    "\x1bOH": "home", "\x1bOF": "end", "\x1bOM": "enter",
    "\x1b": "escape",
}


# A sequence held back must not grow without bound: if a terminal sends an ESC
# that is never completed, the buffer would swallow everything after it.
_MAX_PENDING = 64


def _incomplete_tail(data: str) -> int:
    """Index where an unterminated escape sequence begins, else ``len(data)``.

    Input arrives in whatever chunks the terminal hands over, and a click is
    a dozen bytes: ``\\x1b[<0;10;5M`` split after the fifth character decoded
    as the six keystrokes ``;105M``, typed into whatever field had focus.

    A lone trailing ``ESC`` **is** held, which is the case that matters most:
    where the reader cannot batch, every sequence arrives one character at a
    time and the split is always here. It is also the one genuine ambiguity —
    the Escape key and the start of a sequence are the same byte until the
    next one arrives, and real terminals resolve it with a timer. There is no
    timer here, so :func:`decode_stream` resolves it on the next chunk: if
    what follows does not continue a sequence, Escape fires then, one
    keystroke late and with the following character intact.
    """
    start = data.rfind("\x1b")
    if start < 0:
        return len(data)
    if start == len(data) - 1:
        return start
    lead = data[start + 1]
    if lead == "[":
        for ch in data[start + 2:]:
            if "@" <= ch <= "~":
                return len(data)        # terminated: nothing to hold
        return start
    if lead == "O":
        return len(data) if len(data) - start >= 3 else start
    return len(data)


def decode_stream(data: str, pending: str = "") -> Tuple[List[Event], str]:
    """Decode a chunk, returning the events and any unterminated tail.

    The tail is what the caller must prepend to the next chunk. `decode`
    is this with no memory, which is right for a test feeding a whole
    sequence and wrong for a loop reading whatever has arrived.
    """
    events: List[Event] = []
    if pending == "\x1b" and data[:1] not in ("[", "O"):
        # A held ESC that the next chunk does not continue. Emitting it here
        # rather than letting it merge is what keeps the next character: as
        # `\x1b` + `x` the pair decodes as one unknown sequence and *both*
        # bytes are dropped, so a user who pressed Escape and kept typing
        # would lose a letter.
        events.append(KeyEvent("escape"))
        pending = ""

    data = pending + data
    cut = _incomplete_tail(data)
    if len(data) - cut > _MAX_PENDING:
        cut = len(data)                 # never completed; let it decode as-is
    events.extend(decode(data[:cut]))
    return events, data[cut:]


def decode(data: str) -> List[Event]:
    """Turn a chunk of terminal input into events.

    Order is preserved and unrecognised escape sequences are dropped rather
    than surfaced as text — emitting the raw bytes of an unknown sequence
    would type garbage into whatever field has focus, which is worse than
    ignoring a key nobody bound.

    Stateless, so a sequence split across two calls is mis-decoded; the loop
    that reads from a terminal uses :func:`decode_stream` instead.
    """
    events: List[Event] = []
    i = 0
    n = len(data)
    while i < n:
        match = _SGR_MOUSE.match(data, i)
        if match:
            events.append(_mouse_event(match))
            i = match.end()
            continue

        matched = False
        for seq, name in _KEYS.items():
            if data.startswith(seq, i):
                # A bare ESC is only ESC when nothing follows it; otherwise it
                # is the start of a sequence we do not know, and swallowing it
                # alone would leak the remainder as literal text.
                if seq == "\x1b" and i + 1 < n:
                    continue
                events.append(KeyEvent(name))
                i += len(seq)
                matched = True
                break
        if matched:
            continue

        if data[i] == "\x1b":
            i = _skip_escape(data, i)
            continue

        char = data[i]
        if char.isprintable():
            events.append(KeyEvent(char))
        i += 1
    return events


def _mouse_event(match: "re.Match[str]") -> MouseEvent:
    code, x, y, final = int(match.group(1)), int(match.group(2)), \
        int(match.group(3)), match.group(4)
    if code & 64:                       # wheel
        # The low two bits select the axis and direction: 0 up, 1 down, and
        # 2/3 the *horizontal* wheel a trackpad emits during any diagonal
        # swipe. `up if bits == 0 else down` folded both horizontal codes onto
        # scroll-down, so a sideways gesture scrolled the document — the more
        # sideways the swipe, the more it scrolled. There is nothing to scroll
        # horizontally here (lines are truncated, not panned), so the right
        # answer is to report nothing.
        direction = code & 3
        if direction > 1:
            return MouseEvent("none", x, y)
        return MouseEvent("wheel_up" if direction == 0 else "wheel_down", x, y)
    if code & 32:                       # motion while held
        return MouseEvent("move", x, y, code & 3)
    return MouseEvent("press" if final == "M" else "release", x, y, code & 3)


def _skip_escape(data: str, i: int) -> int:
    """Advance past an escape sequence we do not handle.

    Past *all* of it. A CSI sequence runs to its final byte, and an SS3
    sequence (`ESC O` plus one byte) is three characters — skipping only the
    first two left the third to be emitted as text, so an unbound function key
    typed a letter into the focused field.
    """
    j = i + 1
    if j < len(data) and data[j] == "[":
        j += 1
        while j < len(data) and not ("@" <= data[j] <= "~"):
            j += 1
        return min(j + 1, len(data))
    if j < len(data) and data[j] == "O":
        return min(j + 2, len(data))
    return j + 1 if j < len(data) else len(data)


class RawTerminal:
    """Raw mode with mouse reporting, restored unconditionally on exit.

    On Windows the POSIX termios path does not exist; the class still works as
    a context manager and simply does not switch modes, so the REPL degrades
    to line-buffered keyboard input rather than refusing to start.
    """

    def __init__(self, stream=None, *, mouse: bool = True,
                 alt_screen: bool = True) -> None:
        self.stream = stream or sys.stdout
        self.mouse = mouse
        self.alt_screen = alt_screen
        self._fd: Optional[int] = None
        self._saved = None
        self.raw = False
        # Console-at-a-time reading on Windows, where `termios` is absent.
        self._win = False

    def __enter__(self) -> "RawTerminal":
        try:
            import termios
            import tty

            self._fd = sys.stdin.fileno()
            self._saved = termios.tcgetattr(self._fd)
            tty.setraw(self._fd)
            self.raw = True
        except Exception:
            self.raw = False        # not a tty, or Windows: try msvcrt below
        if not self.raw:
            # Windows has no `termios`, and for a long time that meant no
            # arrow keys, no single-key scrolling, and no way to move about a
            # page except by typing line numbers at a prompt.
            #
            # `msvcrt` reads the console one keystroke at a time with no mode
            # change, which is all raw mode was wanted for here. Special keys
            # arrive as a lead byte (0xE0 or NUL) followed by a code, so they
            # are translated into the escape sequences xterm sends and
            # everything downstream -- decode_stream, the key table, the
            # widgets -- stays exactly as it is.
            #
            # The mouse is NOT available this way: it needs the console input
            # mode changed and events read as records, a different mechanism.
            # Saying so is honest, and the key path is what makes a page
            # navigable.
            try:
                import msvcrt            # noqa: F401 - probing for it
                if sys.stdin.isatty():
                    self._win = True
                    self.raw = True
                    self.mouse = False
            except Exception:
                self._win = False
        out = ""
        if self.alt_screen:
            out += ALT_SCREEN
        if self.mouse:
            out += ENABLE_MOUSE
        out += HIDE_CURSOR
        self._write(out)
        return self

    def __exit__(self, *exc: object) -> None:
        out = SHOW_CURSOR
        if self.mouse:
            out += DISABLE_MOUSE
        if self.alt_screen:
            out += MAIN_SCREEN
        self._write(out)
        if self._saved is not None and self._fd is not None:
            try:
                import termios
                termios.tcsetattr(self._fd, termios.TCSADRAIN, self._saved)
            except Exception:
                pass

    def _write(self, text: str) -> None:
        try:
            self.stream.write(text)
            self.stream.flush()
        except Exception:
            pass

    def size(self) -> Tuple[int, int]:
        try:
            size = os.get_terminal_size()
            return size.lines, size.columns
        except OSError:
            return 24, 80

    def read(self) -> str:
        """Read whatever is available. Blocks for at least one character.

        May return part of an escape sequence: `_drain` needs `select`, which
        does not work on a console handle, so on the POSIX non-tty path this
        can yield one character per call. The caller reassembles — see
        :func:`decode_stream`.

        On Windows it reads the console through `msvcrt` and translates the
        special-key encoding into the escape sequences the rest of this file
        already understands.
        """
        if self._win:
            return _read_console()
        try:
            return sys.stdin.read(1) + _drain(sys.stdin)
        except Exception:
            return ""

    def read_line(self) -> str:
        """One typed line, echoed, for the `:` command prompt.

        Read through `msvcrt` on Windows rather than `sys.stdin.readline()`:
        the console is being read a keystroke at a time by `read`, and mixing
        the two buffers drops characters. Backspace and Escape are handled
        here because at this level nothing else will.
        """
        if not self._win:
            return sys.stdin.readline()
        import msvcrt

        out = []
        while True:
            ch = msvcrt.getwch()
            if ch in ("\r", "\n"):
                self.stream.write("\n")
                self.stream.flush()
                return "".join(out)
            if ch in ("\x03", "\x1b"):          # ctrl-c or escape: abandon
                return ""
            if ch in ("\x08", "\x7f"):          # backspace
                if out:
                    out.pop()
                    self.stream.write("\b \b")
                    self.stream.flush()
                continue
            if ch in ("\x00", "\xe0"):          # a special key: ignore it
                msvcrt.getwch()
                continue
            out.append(ch)
            self.stream.write(ch)
            self.stream.flush()


#: Windows console special keys, as the escape sequences xterm would send.
#: Translating here means `decode_stream` and the key table never learn that
#: Windows exists.
_WIN_KEYS = {
    "H": "\x1b[A", "P": "\x1b[B", "M": "\x1b[C", "K": "\x1b[D",
    "G": "\x1b[H", "O": "\x1b[F", "I": "\x1b[5~", "Q": "\x1b[6~",
    "S": "\x1b[3~",
}


def _read_console() -> str:
    """Block for one keystroke, then take whatever else is already typed."""
    import msvcrt

    out = []
    first = True
    while first or msvcrt.kbhit():
        first = False
        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):
            out.append(_WIN_KEYS.get(msvcrt.getwch(), ""))
        elif ch == "\r":
            out.append("\n")
        else:
            out.append(ch)
    return "".join(out)


def _drain(stream) -> str:
    """Non-blocking read of anything else already buffered.

    A single mouse event is a dozen bytes and a fast wheel produces several at
    once; reading one character per loop would render a frame per byte and
    make scrolling visibly lag the wheel.
    """
    try:
        import select

        out = []
        while select.select([stream], [], [], 0)[0]:
            char = stream.read(1)
            if not char:
                break
            out.append(char)
        return "".join(out)
    except Exception:
        return ""


# --- painting ---------------------------------------------------------------

_RESET = "\x1b[0m"
_DIM = "\x1b[2m"
_BOLD = "\x1b[1m"
_REVERSE = "\x1b[7m"
_UNDERLINE = "\x1b[4m"


def _style(widget: Widget, focused: bool, hovered: bool) -> Tuple[str, str]:
    if focused:
        return _REVERSE, _RESET
    if hovered and widget.interactive:
        return _BOLD, _RESET
    if widget.kind is WidgetKind.LINK:
        return _UNDERLINE, _RESET
    if widget.kind is WidgetKind.IMAGE:
        return _DIM, _RESET
    return "", ""


def paint(state: ReplState, *, colour: bool = True) -> List[str]:
    """Render the state as a list of screen lines.

    Returns lines rather than writing them, so a test can assert on exactly
    what would appear without a terminal attached — the same reason the state
    machine takes events instead of reading stdin.
    """
    width = max(10, state.cols)
    out: List[str] = []

    title = state.document.title or state.document.url or "vertiscope"
    position = f"{state.top + 1}-{min(state.top + state.body_rows, len(state.document))}" \
        f"/{len(state.document)}"
    header = f" {title[:width - len(position) - 4]} "
    out.append((header + " " * width)[:width - len(position) - 1] + position + " ")

    for offset, widget in enumerate(state.visible()):
        line = state.top + offset
        prefix, suffix = ("", "")
        if colour:
            prefix, suffix = _style(widget, line == state.focus, line == state.hover)
        body = widget.render()
        if widget.kind is WidgetKind.INPUT and line == state.focus:
            body = _with_cursor(widget, colour=colour)
            out.append(body[:width + 8])   # +8 for the caret's escape codes
            continue
        out.append(prefix + body[:width] + suffix)

    while len(out) < state.rows - state.footer_rows:
        out.append("")

    status = state.buffers.status or "click to open · scroll to move · tab to focus"
    out.append(status[:width])
    return out


def _with_cursor(widget: Widget, *, colour: bool = True) -> str:
    """Draw the cursor inside a focused field.

    With colour, by reversing the character *under* the cursor — which is how
    a terminal draws its own cursor, costs no column, and needs no glyph. The
    first attempt inserted a box-drawing bar, which is not encodable in the
    Windows console's cp1252 default and crashed the paint call outright.

    Without colour, an ASCII bar, accepting that it shifts the text by one
    column: a plain-text render is for tests and logs, where an unambiguous
    marker beats exact column alignment.
    """
    pad = "  " * widget.depth
    text = widget.value
    at = max(0, min(widget.cursor, len(text)))
    # The label rides along, exactly as in `Widget.render`. Without it a field
    # lost its name the moment it took focus, which is when knowing the name
    # matters most.
    tail = f" {widget.label}" if widget.label else ""
    if not colour:
        return f"{pad}[{text[:at]}|{text[at:]}]{tail}"
    under = text[at] if at < len(text) else " "
    return (f"{pad}[{text[:at]}{_REVERSE}{under}{_RESET}{text[at + 1:]}]"
            f"{tail}")
