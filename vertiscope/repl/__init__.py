"""The interactive REPL — the third data checkpoint.

External to the pipeline: it consumes the trie, the markdown chunks and the
index, and never builds them. Importable as a package or run from the command
line.

Three layers, deliberately separated so that all but one are testable without
a terminal or a mouse:

``model``
    A pure state machine. Events in, state out, no I/O. Clicks, drags,
    scrolling, cursor placement and text editing are all functions on this
    object, so every one of them can be proved by feeding synthetic events
    and reading the state back.

``terminal``
    Decoding real input into those events, and painting state onto a screen.
    The mouse arrives as xterm SGR escape sequences, so the decoder is an
    ordinary parser over bytes and is exhaustively testable — the physical
    mouse is the terminal's problem, not ours.

``app``
    The loop: commands, retrieval, and web navigation through Selenium using
    the absolute xpath the address already carries.
"""

from .model import (  # noqa: F401
    Buffers,
    Document,
    Event,
    KeyEvent,
    MouseEvent,
    ReplState,
    Widget,
    WidgetKind,
)

__all__ = [
    "Buffers",
    "Document",
    "Event",
    "KeyEvent",
    "MouseEvent",
    "ReplState",
    "Widget",
    "WidgetKind",
]
