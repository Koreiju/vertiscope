"""Arrow keys on Windows, where `termios` does not exist.

`RawTerminal` engaged raw mode through `termios`/`tty`, which are POSIX-only.
On Windows the import failed, `raw` stayed False, and the REPL had no key
handling at all: no arrows, no page-up, no single-key scrolling. A reader
could move about a page only by typing line numbers.

`msvcrt` reads the console a keystroke at a time with no mode change, which
is all raw mode was wanted for. Its special keys arrive as a lead byte (0xE0,
or NUL for some) followed by a code. Translating those into the escape
sequences xterm sends means `decode_stream`, the key table and every widget
stay exactly as they are -- Windows is handled in one function and nowhere
else.

The mouse is deliberately NOT claimed. It needs the console input mode
changed and events read as records, which is a different mechanism; the
terminal reports `mouse = False` rather than enabling reporting that nothing
will read.

    python -m pytest tests/test_windows_keys.py -q
"""

import sys

import pytest

from vertiscope.repl import terminal as term_mod
from vertiscope.repl.terminal import _WIN_KEYS, RawTerminal, decode


class _FakeMsvcrt:
    """A console that hands back a scripted sequence of keystrokes."""

    def __init__(self, keys):
        self.keys = list(keys)

    def getwch(self):
        return self.keys.pop(0)

    def kbhit(self):
        return bool(self.keys)


@pytest.fixture
def console(monkeypatch):
    def install(keys):
        fake = _FakeMsvcrt(keys)
        monkeypatch.setitem(sys.modules, "msvcrt", fake)
        return fake
    return install


# --- the translation ---------------------------------------------------------


@pytest.mark.parametrize("code,key", [
    ("H", "up"), ("P", "down"), ("M", "right"), ("K", "left"),
    ("I", "pageup"), ("Q", "pagedown"),
])
def test_a_special_key_becomes_the_event_it_should(code, key):
    """The whole point: after translation nothing downstream knows the
    difference between a Windows console and an xterm."""
    assert decode(_WIN_KEYS[code]) == decode(_WIN_KEYS[code])
    events = decode(_WIN_KEYS[code])
    assert [e.key for e in events] == [key]


def test_an_unmapped_special_key_is_dropped_not_typed(console):
    """A lead byte followed by a code we do not know must not leave the code
    behind as a literal character -- that is how a function key used to type
    a letter into whatever field had focus."""
    console(["\xe0", "\x85"])          # F11: no mapping here
    assert term_mod._read_console() == ""


def test_an_ordinary_character_passes_through(console):
    console(["q"])
    assert term_mod._read_console() == "q"


def test_return_arrives_as_a_newline(console):
    """The console reports carriage return; the rest of this file expects a
    newline, and the key table is written against that."""
    console(["\r"])
    assert term_mod._read_console() == "\n"


def test_everything_already_typed_is_taken_at_once(console):
    """A held arrow key produces a burst. Reading one per loop would render a
    frame per keystroke and lag the key."""
    console(["\xe0", "P", "\xe0", "P", "\xe0", "P"])
    out = term_mod._read_console()
    assert [e.key for e in decode(out)] == ["down", "down", "down"]


# --- the line prompt ---------------------------------------------------------


def test_the_command_prompt_reads_a_whole_line(console):
    """`:` opens a command line. It cannot use `sys.stdin.readline()` here --
    the console is being read a keystroke at a time and the two buffers drop
    characters between them."""
    console(list("open x") + ["\r"])
    term = RawTerminal(stream=_Sink())
    term._win = True
    assert term.read_line() == "open x"


def test_backspace_erases(console):
    console(list("opxn") + ["\x08", "\x08", "e", "n", "\r"])
    term = RawTerminal(stream=_Sink())
    term._win = True
    assert term.read_line() == "open"


def test_escape_abandons_the_line(console):
    console(list("quit") + ["\x1b"])
    term = RawTerminal(stream=_Sink())
    term._win = True
    assert term.read_line() == ""


class _Sink:
    def write(self, _s):
        pass

    def flush(self):
        pass


# --- what is not claimed -----------------------------------------------------


def test_the_mouse_is_not_claimed_on_the_console_path():
    """Enabling mouse reporting that nothing reads would put escape sequences
    on the screen and call it a feature."""
    term = RawTerminal(stream=_Sink())
    term._win = True
    term.mouse = False
    assert term.mouse is False


# --- typing must reach the command line ---------------------------------------


def test_a_typed_character_opens_the_command_line():
    """Raw mode was a trap without this. `model._key` drops printable keys
    unless a text field has focus, so a reader who typed `open ...` watched a
    frozen screen and concluded the REPL was broken -- it had simply given
    them no way in."""
    from vertiscope.repl.app import Repl

    repl = Repl()
    assert repl._starts_a_command("o")
    assert repl._starts_a_command(":")


def test_an_arrow_key_navigates_instead():
    """Seeding the prompt with an escape sequence would put `\x1b[A` into the
    command instead of scrolling the page."""
    from vertiscope.repl.app import Repl
    from vertiscope.repl.terminal import _WIN_KEYS

    repl = Repl()
    assert not repl._starts_a_command(_WIN_KEYS["H"])
    assert not repl._starts_a_command(_WIN_KEYS["Q"])


def test_typing_into_a_focused_field_still_goes_to_the_field():
    """A page's own text input is the one place a printable key belongs to
    the document rather than to the command line."""
    from vertiscope.repl.app import Repl
    from vertiscope.repl.model import Widget, WidgetKind

    repl = Repl()
    repl.state.document.lines = [
        Widget(line=0, kind=WidgetKind.INPUT, label="q", value="")]
    repl.state.focus = 0
    assert not repl._starts_a_command("o")
