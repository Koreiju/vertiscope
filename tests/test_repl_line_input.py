"""Without raw mode the REPL must read a LINE, not a character.

`RawTerminal.read()` returns `stdin.read(1) + _drain(stdin)`, and `_drain`
needs `select`, which does not work on a Windows console handle -- so it
returns "" and the read is exactly one character. Its docstring says so.

The run loop's non-raw branch called that same `read()` and treated the
result as a typed line. Its comment said so. Two comments, one file apart,
contradicting each other, and the code believed the wrong one.

The effect on Windows -- where raw mode never engages, because `termios` is
not in the standard library there -- was that every command was dispatched
letter by letter:

    help  ->  h, e, l, p     four unknown commands and no help
    quit  ->  q, u, i, t     the session could not be closed

The second one is what made it more than an annoyance. A session that cannot
quit keeps the kuzu lock on its store, so the *next* launch died with
"held by another process" and the user had two broken things to explain
instead of one.

    python -m pytest tests/test_repl_line_input.py -q
"""

import io

from vertiscope.repl.app import Repl


class _FakeTerm:
    """A terminal that never entered raw mode -- Windows, or a pipe."""

    raw = False

    def __init__(self):
        self.reads = 0

    def size(self):
        return 24, 80

    def read(self):
        # One character, which is all the real one can give here. If the loop
        # calls this at all on the non-raw path, the test fails by design.
        #
        # Bounded, and that is not incidental: the old loop consumed this
        # forever and never reached its own exit, so reverting the fix hung
        # the suite instead of failing it. A regression that wedges the run
        # is worse than one that reports, so the fake refuses after a few.
        self.reads += 1
        if self.reads > 4:
            raise AssertionError(
                "the non-raw path is reading characters, not lines")
        return "h"

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _run(monkeypatch, typed):
    """Drive `Repl.run` with `typed` on stdin and a non-raw terminal."""
    import vertiscope.repl.app as app

    term = _FakeTerm()
    monkeypatch.setattr(app, "RawTerminal", lambda **kw: term)
    monkeypatch.setattr(app.sys, "stdin", io.StringIO(typed))
    monkeypatch.setattr(app.sys, "stdout", io.StringIO())
    repl = Repl()
    seen = []
    real = repl.command
    repl.command = lambda line: (seen.append(line), real(line))[1]
    repl.run()
    return seen, term


def test_a_typed_command_arrives_whole(monkeypatch):
    """`help` is one command, not four."""
    seen, _term = _run(monkeypatch, "help\nquit\n")
    assert seen[0] == "help"


def test_the_session_can_be_quit(monkeypatch):
    """`quit` dispatched as q/u/i/t left a session that held its store lock
    open, which broke the *next* launch as well."""
    seen, _term = _run(monkeypatch, "quit\n")
    assert seen == ["quit"]


def test_the_character_read_is_not_used_without_raw_mode(monkeypatch):
    """The precise defect: the non-raw branch must not call `read()` at all,
    because one character is all it can return here."""
    _seen, term = _run(monkeypatch, "help\nquit\n")
    assert term.reads == 0


def test_end_of_input_ends_the_session(monkeypatch):
    """A closed pipe is not an empty command repeated forever."""
    seen, _term = _run(monkeypatch, "")
    assert seen == []
