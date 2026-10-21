"""The REPL's state machine. Pure: events in, state out, no terminal.

Everything the interactive surface does — clicking, releasing, dragging,
scrolling, placing a cursor, typing into a field, ticking a checkbox — is a
method on :class:`ReplState` taking an event. Nothing here reads stdin or
writes stdout, which is what makes the whole interaction model provable
without a terminal and without a mouse: construct a state, feed it the events
a mouse would have produced, and read the result.

The one thing that cannot be proved this way is that a physical mouse produces
those events. That is the terminal's job (see :mod:`vertiscope.repl.terminal`),
and it is exactly the boundary the spec anticipated.

Click and declick
-----------------
A click is two events, and they are kept apart because the difference is
observable. Press *arms* a widget and records where the pointer went down;
release *activates* it, but only if the pointer is still on the same widget.
Pressing on a link and releasing elsewhere cancels — which is what every
graphical interface does and what a user relies on to back out of a misclick.
Collapsing them into one "click" event would make that impossible to express.

Coordinates
-----------
Screen coordinates are 1-based (the terminal's own convention, so no
translation on the hot path) and document coordinates are 0-based line
indices. :meth:`ReplState.hit` is the only place the two meet.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from ..address import ContentAddress

__all__ = [
    "WidgetKind",
    "Widget",
    "Document",
    "Buffers",
    "Event",
    "MouseEvent",
    "KeyEvent",
    "ReplState",
]


class WidgetKind(str, Enum):
    TEXT = "text"
    LINK = "link"
    BUTTON = "button"
    INPUT = "input"
    CHECKBOX = "checkbox"
    IMAGE = "image"
    FORM = "form"

    @property
    def interactive(self) -> bool:
        return self is not WidgetKind.TEXT


# The content tag decides the widget. A flat lookup, because the tag set is
# flat (THEORY Def. 10.1): eighteen labels with no order and no operation.
_KIND_BY_TAG = {
    "interactive.inputs": WidgetKind.INPUT,
    "interactive.buttons": WidgetKind.BUTTON,
    # A form is not a button. Mapping it to one made the widget re-wrap a
    # line the renderer had already marked up, printing "( === form === )".
    "interactive.forms": WidgetKind.FORM,
    "interactive.links": WidgetKind.LINK,
    "interactive.elements": WidgetKind.BUTTON,
    "interactive.event_handlers": WidgetKind.BUTTON,

    # The render classes, from the live path. A widget has to know a button
    # from a paragraph to let a reader act on it, and after the address's
    # taxonomy slot became the render class every one of these fell through
    # to TEXT -- so the page drew its controls and the REPL treated them as
    # prose. `vertiscope.aam.RENDER_CLASS` is the authority for what these are;
    # this maps them onto the widget vocabulary the terminal already has.
    "link": WidgetKind.LINK,
    "button": WidgetKind.BUTTON,
    "field": WidgetKind.INPUT,
    "slider": WidgetKind.INPUT,
    "choice": WidgetKind.INPUT,
    "check": WidgetKind.CHECKBOX,
    "image": WidgetKind.IMAGE,
    "media": WidgetKind.IMAGE,
}


#: A rendered link inside a drawn line: `[words](target)`.
_LINK_SPAN = re.compile(r"\[(?P<words>[^\]]*)\]\((?P<target>[^)]*)\)")


def kind_for(address: Optional[ContentAddress]) -> WidgetKind:
    """The widget a line becomes. A line without an address is prose.

    Melded rows -- a stored chunk drawn into a live page's row shape -- can
    reach here, and a line that names no node is not a control however it is
    spelled.
    """
    if address is None:
        return WidgetKind.TEXT
    explicit = _KIND_BY_TAG.get(address.tag)
    if explicit is not None:
        return explicit
    if address.category == "urls":
        return WidgetKind.LINK
    if address.category == "media":
        return WidgetKind.IMAGE
    return WidgetKind.TEXT


@dataclass
class Widget:
    """One addressable thing on one document line."""

    line: int
    kind: WidgetKind
    label: str
    address: Optional[ContentAddress] = None
    depth: int = 0

    #: The columns this widget occupies, when it is one of several on a line.
    #: `(0, 0)` means the whole line, which is what every widget in
    #: `Document.lines` is: those own their line and render it. A widget with
    #: a real span is a HIT TARGET only -- it never renders, because the line
    #: it sits in is already drawn by the widget that owns it.
    col: int = 0
    end: int = 0

    @property
    def spans_line(self) -> bool:
        return self.end <= self.col

    # interaction state
    checked: bool = False
    value: str = ""
    cursor: int = 0
    armed: bool = False
    # `"### "` when this control is also a heading, so `render` can put it
    # back. Kept apart from `label` because the label is what a reader and
    # `classify_controls` want, and the marker is presentation.
    heading: str = ""

    @property
    def interactive(self) -> bool:
        return self.kind.interactive

    def render(self) -> str:
        """The line as it should appear, reflecting current state."""
        pad = "  " * self.depth + self.heading
        if self.kind is WidgetKind.CHECKBOX:
            return f"{pad}[{'x' if self.checked else ' '}] {self.label}"
        if self.kind is WidgetKind.INPUT:
            # The field and its name are two things, and the markdown form
            # already says so ("[ ] Quick search"). Rendering `value or label`
            # inside the brackets conflated them: an empty field showed its
            # name as though that were its contents, and typing into it made
            # the name disappear — so the moment a form had two fields filled
            # in, nothing on screen said which was which.
            return f"{pad}[{self.value or ' '}]" + (f" {self.label}"
                                                    if self.label else "")
        if self.kind is WidgetKind.BUTTON:
            return f"{pad}( {self.label} )"
        if self.kind is WidgetKind.FORM:
            return f"{pad}=== {self.label} ==="
        return f"{pad}{self.label}"

    # -- text editing ------------------------------------------------------
    def insert(self, text: str) -> None:
        self.cursor = max(0, min(self.cursor, len(self.value)))
        self.value = self.value[:self.cursor] + text + self.value[self.cursor:]
        self.cursor += len(text)

    def backspace(self) -> None:
        if self.cursor > 0:
            self.value = self.value[:self.cursor - 1] + self.value[self.cursor:]
            self.cursor -= 1

    def delete(self) -> None:
        if self.cursor < len(self.value):
            self.value = self.value[:self.cursor] + self.value[self.cursor + 1:]

    def move_cursor(self, delta: int) -> None:
        self.cursor = max(0, min(len(self.value), self.cursor + delta))

    def place_cursor(self, column: int) -> None:
        """Put the cursor where a click landed, clamped to the text.

        Clamping rather than rejecting an out-of-range column: clicking past
        the end of a field means "the end", which is what every editor does,
        and refusing would make the field feel broken at exactly the place
        users aim for.
        """
        self.cursor = max(0, min(len(self.value), column))


@dataclass
class Document:
    """The lines the REPL is showing, with their widgets.

    Built from markdown chunks, so a document line is a chunk line, and its
    address is the anchor that chunk recorded. That is the whole link between
    what is on screen and where it came from — no second index.
    """

    lines: List[Widget] = field(default_factory=list)
    title: str = ""
    url: str = ""

    #: line number -> the controls sharing that line, left to right.
    #:
    #: `lines` stays one widget per line, indexed by line number, because
    #: eight call sites read `document.lines[n]` that way and rendering,
    #: scrolling and key handling all depend on it. A line that draws a
    #: sentence with two links in it still has ONE widget that owns and
    #: renders it; the links are additional hit targets with column spans.
    #:
    #: Without this a folded link is reachable only through `line.inline`,
    #: which `live.read()` consults and the REPL could not: the controls
    #: listing lost them entirely.
    inline: Dict[int, List[Widget]] = field(default_factory=dict)

    def controls(self) -> List[Widget]:
        """Every interactive widget, line-owning and inline, in reading order."""
        out: List[Widget] = []
        for n, widget in enumerate(self.lines):
            if widget.interactive:
                out.append(widget)
            out.extend(w for w in self.inline.get(n, ()) if w.interactive)
        return out

    def __len__(self) -> int:
        return len(self.lines)

    @classmethod
    def from_chunks(cls, chunks: Sequence, *, url: str = "", title: str = "") -> "Document":
        widgets: List[Widget] = []
        for chunk in chunks:
            for line in chunk.lines:
                address = line.address
                kind = kind_for(address)
                label = line.text
                # Strip the rendering marks back off: the widget re-adds them
                # from its own state, so a checkbox that gets ticked repaints
                # as ticked instead of keeping the mark it was printed with.
                #
                # The heading marker comes off first. A control inside a
                # heading renders as `##### ( Products )`, so every strip
                # below — each of which tests a *leading* mark — stopped
                # firing, and the button's label became the whole rendered
                # string, repainted as `( ##### ( Products ) )`. Kept on the
                # widget so nothing is lost, and re-added by `render`.
                heading_mark = ""
                if kind is not WidgetKind.TEXT and label.startswith("#"):
                    body = label.lstrip("#")
                    if body.startswith(" "):
                        heading_mark = label[: len(label) - len(body) + 1]
                        label = body[1:]

                if kind is WidgetKind.BUTTON and label.startswith("( "):
                    label = label[2:-2] if label.endswith(" )") else label[2:]
                elif kind is WidgetKind.FORM and label.startswith("=== "):
                    label = label[4:-4] if label.endswith(" ===") else label[4:]
                elif kind is WidgetKind.INPUT and label.startswith("[ ] "):
                    # `_render_unit` writes "[ ] <label>". Stripping "[ " and
                    # then rstripping "]" removed a bracket that is not there
                    # — the `]` is at the *front* of what is left — so every
                    # input in the REPL was labelled "] Quick search", and
                    # re-rendered as "[] Quick search]".
                    label = label[4:].strip()
                elif kind is WidgetKind.INPUT and label.startswith("[ "):
                    label = label[2:].strip("] ").strip()
                widgets.append(Widget(
                    line=len(widgets), kind=kind, label=label,
                    address=address, depth=line.depth,
                    value="" if kind is not WidgetKind.INPUT else "",
                    heading=heading_mark,
                ))
        # The controls a line drew inside itself.
        #
        # `_inline_flow` and the prose fold put several addresses on one line:
        # a sentence with two links in it is one line for a reader and three
        # addresses for anyone who wants to act on it. The line-owning widget
        # above is built from `line.address`, so those merged addresses had
        # nowhere to go and dropped out of the controls listing.
        #
        # Located by finding each rendered `[words](target)` in the drawn
        # text, left to right, and pairing it with the merged addresses in
        # the order `inline` records them -- which is reading order, by
        # `MarkdownLine.inline`'s contract.
        inline: Dict[int, List[Widget]] = {}
        row = 0
        for chunk in chunks:
            for line in chunk.lines:
                merged = tuple(getattr(line, "inline", ()) or ())
                if merged:
                    spans = list(_LINK_SPAN.finditer(line.text))
                    # Elements this line already offers as something to press.
                    #
                    # `inline` used to hold folded links and nothing else, so
                    # pairing it positionally with the drawn `[words](target)`
                    # spans was the whole story. It now also carries an
                    # element's affordance when the render addressed the line
                    # as something else -- Wikimedia's
                    # `<button aria-label="...">` draws as `text.accessible`,
                    # because the aria-label subsumes the button's own words --
                    # and those have no span to pair with. Zipping simply
                    # dropped them, so the words were drawn and the button was
                    # not pressable: visible and inert.
                    covered = set()
                    owner = widgets[row].address
                    if widgets[row].interactive and owner is not None:
                        covered.add(owner.xpath.split("/text()")[0])
                    for address, hit in zip(merged, spans):
                        covered.add(address.xpath.split("/text()")[0])
                        inline.setdefault(row, []).append(Widget(
                            line=row, kind=kind_for(address),
                            # The whole rendered form, `[words](target)`,
                            # not just the words. `nav._split_rendered` wants
                            # both halves -- a pager is identified by its
                            # href -- and the address cannot supply the
                            # target, which is a leaf VALUE and not one of
                            # the four address components. Substring
                            # matching for `press <name>` still finds the
                            # words inside it.
                            label=hit.group(0),
                            address=address, depth=line.depth,
                            col=hit.start(), end=hit.end(),
                        ))
                    # An affordance with no span of its own targets the whole
                    # line, because that is what a reader would click. Only
                    # where nothing already offers that element: a sentence
                    # holding two links carries both their url addresses AND
                    # both their `interactive.links` ones, and the second pair
                    # names controls the spans above already cover.
                    for address in merged:
                        if not address.is_control:
                            continue
                        element = address.xpath.split("/text()")[0]
                        if element in covered:
                            continue
                        covered.add(element)
                        inline.setdefault(row, []).append(Widget(
                            line=row, kind=kind_for(address),
                            label=line.text.strip(),
                            address=address, depth=line.depth,
                            col=0, end=len(line.text),
                        ))
                row += 1
        return cls(lines=widgets, url=url, title=title, inline=inline)


@dataclass
class Buffers:
    """The REPL's memory. Held on the object, not in globals.

    ``history`` is what was typed, ``trail`` is where the session has been,
    ``status`` is the last message, ``marks`` are addresses the user kept.
    Bounded on purpose — an unbounded scrollback in a long crawl is a slow
    leak, and truncating the oldest is the only policy that does not require
    the user to think about it.
    """

    limit: int = 500
    history: List[str] = field(default_factory=list)
    trail: List[str] = field(default_factory=list)
    status: str = ""
    marks: List[ContentAddress] = field(default_factory=list)
    log: List[str] = field(default_factory=list)

    def _push(self, target: List, item) -> None:
        target.append(item)
        if len(target) > self.limit:
            del target[: len(target) - self.limit]

    def remember(self, command: str) -> None:
        if command and (not self.history or self.history[-1] != command):
            self._push(self.history, command)

    def visited(self, url: str) -> None:
        self._push(self.trail, url)

    def note(self, message: str) -> None:
        self.status = message
        self._push(self.log, message)

    def mark(self, address: ContentAddress) -> None:
        """Keep an address. Says so when keeping it costs an older one.

        `history` and `trail` are logs and truncating them silently is right —
        nobody asked for the five-hundredth command back. `marks` are not a
        log: each one is something the user chose to keep, so dropping the
        oldest to make room is a small loss of their work, and a loss nobody
        is told about is the pattern this codebase keeps finding at the bottom
        of its defects.
        """
        evicted = self.marks[0] if len(self.marks) >= self.limit else None
        self._push(self.marks, address)
        if evicted is not None:
            self.status = (f"marked; dropped the oldest mark "
                           f"({evicted.xpath[:40]}) — the buffer holds "
                           f"{self.limit}")


# --- events -----------------------------------------------------------------


@dataclass
class Event:
    """Base event."""


@dataclass
class MouseEvent(Event):
    """A mouse action in 1-based screen coordinates."""

    action: str          # 'press' | 'release' | 'move' | 'wheel_up' | 'wheel_down'
    x: int = 1
    y: int = 1
    button: int = 0      # 0 left, 1 middle, 2 right


@dataclass
class KeyEvent(Event):
    """A key. Printable keys carry their character; others a name."""

    key: str


# --- state ------------------------------------------------------------------


@dataclass
class ReplState:
    """Viewport, document, focus and buffers. The whole interactive surface."""

    document: Document = field(default_factory=Document)
    buffers: Buffers = field(default_factory=Buffers)

    rows: int = 24
    cols: int = 80
    top: int = 0                       # first visible document line
    # First visible *column*. A wireframe is as wide as the page it draws,
    # and a page is routinely wider than a terminal -- a three-column layout
    # at the page's own proportions does not fit in 80 columns and should
    # not be squeezed until it does. Reading sideways is how a browser
    # handles the same thing.
    left: int = 0
    focus: Optional[int] = None        # focused widget's line index
    hover: Optional[int] = None
    pressed: Optional[int] = None      # widget the pointer went down on
    header_rows: int = 1
    footer_rows: int = 1

    # Set by the app; called when a link or button is activated.
    on_activate: Optional[Callable[[Widget], None]] = None

    # -- viewport ----------------------------------------------------------
    @property
    def body_rows(self) -> int:
        return max(1, self.rows - self.header_rows - self.footer_rows)

    @property
    def max_top(self) -> int:
        return max(0, len(self.document) - self.body_rows)

    def visible(self) -> List[Widget]:
        return self.document.lines[self.top: self.top + self.body_rows]

    def scroll(self, delta: int) -> int:
        """Scroll by ``delta`` lines, clamped. Returns the new top.

        Clamped rather than wrapped: a viewport that wraps past the end makes
        "am I at the bottom" unanswerable, and the bottom is where a reader
        decides whether to page or to navigate.
        """
        self.top = max(0, min(self.max_top, self.top + delta))
        return self.top

    def scroll_to_line(self, line: int) -> int:
        """Bring a document line into view, centred if it is off-screen."""
        if line < self.top:
            self.top = max(0, line)
        elif line >= self.top + self.body_rows:
            self.top = max(0, min(self.max_top, line - self.body_rows + 1))
        return self.top

    def row_of(self, line: int) -> Optional[int]:
        """The 1-based screen row showing a document line, if it is visible."""
        if self.top <= line < self.top + self.body_rows:
            return line - self.top + self.header_rows + 1
        return None

    # -- hit testing -------------------------------------------------------
    def hit(self, x: int, y: int) -> Optional[int]:
        """The document line under a 1-based screen coordinate, if any."""
        body_start = self.header_rows + 1
        if y < body_start or y >= body_start + self.body_rows:
            return None
        line = self.top + (y - body_start)
        if 0 <= line < len(self.document) and 1 <= x <= self.cols:
            return line
        return None

    def widget_at(self, x: int, y: int) -> Optional[Widget]:
        line = self.hit(x, y)
        if line is None:
            return None
        # A control inside the line wins over the line that owns it, because
        # clicking the words of a link in a sentence means the link. The
        # column is measured in the same coordinates the line was drawn in:
        # `x` is 1-based and `left` is the first visible column.
        column = (x - 1) + self.left
        for widget in self.document.inline.get(line, ()):
            if widget.col <= column < widget.end:
                return widget
        return self.document.lines[line]

    # -- events ------------------------------------------------------------
    def handle(self, event: Event) -> Optional[Widget]:
        if isinstance(event, MouseEvent):
            return self._mouse(event)
        if isinstance(event, KeyEvent):
            return self._key(event)
        return None

    def _mouse(self, event: MouseEvent) -> Optional[Widget]:
        if event.action == "wheel_up":
            self.scroll(-3)
            return None
        if event.action == "wheel_down":
            self.scroll(3)
            return None
        if event.action == "none":
            # A horizontal wheel tick. Reported so the decoder stays a total
            # function over what a terminal can send, and ignored here because
            # lines are truncated rather than panned.
            return None

        line = self.hit(event.x, event.y)

        if event.action == "move":
            self.hover = line
            return None

        if event.action == "press":
            self._disarm()
            self.pressed = line
            if line is None:
                return None
            widget = self.document.lines[line]
            widget.armed = True
            self.focus = line
            if widget.kind is WidgetKind.INPUT:
                # Cursor placement: the click column, less the indent and the
                # opening bracket the field is drawn with.
                offset = 2 * widget.depth + 1
                widget.place_cursor(event.x - 1 - offset)
            return widget

        if event.action == "release":
            armed = self.pressed
            self._disarm()
            self.pressed = None
            if armed is None or armed != line:
                # Released somewhere else: the press is cancelled, not applied.
                return None
            return self._activate(self.document.lines[armed])

        return None

    def _disarm(self) -> None:
        if self.pressed is not None and 0 <= self.pressed < len(self.document):
            self.document.lines[self.pressed].armed = False

    def _activate(self, widget: Widget) -> Widget:
        if widget.kind is WidgetKind.CHECKBOX:
            widget.checked = not widget.checked
            self.buffers.note(
                f"{'checked' if widget.checked else 'unchecked'} {widget.label}")
        elif widget.kind in (WidgetKind.LINK, WidgetKind.BUTTON, WidgetKind.IMAGE):
            if self.on_activate is not None:
                self.on_activate(widget)
            else:
                self.buffers.note(f"activate {widget.label}")
        return widget

    def _key(self, event: KeyEvent) -> Optional[Widget]:
        key = event.key
        if key in ("up", "down", "pageup", "pagedown", "home", "end") and (
            self.focus is None
            or self.document.lines[self.focus].kind is not WidgetKind.INPUT
        ):
            self._navigate(key)
            return None

        if self.focus is None:
            return None
        widget = self.document.lines[self.focus]

        if widget.kind is WidgetKind.INPUT:
            if key == "backspace":
                widget.backspace()
            elif key == "delete":
                widget.delete()
            elif key == "left":
                widget.move_cursor(-1)
            elif key == "right":
                widget.move_cursor(1)
            elif key == "home":
                widget.cursor = 0
            elif key == "end":
                widget.cursor = len(widget.value)
            elif len(key) == 1 and key.isprintable():
                widget.insert(key)
            return widget

        if key in (" ", "enter") and widget.interactive:
            return self._activate(widget)
        return None

    def _navigate(self, key: str) -> None:
        if key == "up":
            self.scroll(-1)
        elif key == "down":
            self.scroll(1)
        elif key == "pageup":
            self.scroll(-self.body_rows)
        elif key == "pagedown":
            self.scroll(self.body_rows)
        elif key == "home":
            self.top = 0
        elif key == "end":
            self.top = self.max_top

    # -- selection ---------------------------------------------------------
    def focus_next(self, step: int = 1) -> Optional[Widget]:
        """Move focus to the next interactive widget, scrolling it into view.

        Keyboard focus exists alongside the mouse rather than instead of it:
        a session over ssh may have no mouse reporting at all, and the whole
        surface has to stay reachable.
        """
        n = len(self.document)
        if not n:
            return None
        start = self.focus if self.focus is not None else -1 if step > 0 else n
        for offset in range(1, n + 1):
            index = (start + step * offset) % n
            if self.document.lines[index].interactive:
                self.focus = index
                self.scroll_to_line(index)
                return self.document.lines[index]
        return None

    def checked_widgets(self) -> List[Widget]:
        return [w for w in self.document.lines
                if w.kind is WidgetKind.CHECKBOX and w.checked]

    def snapshot(self) -> Dict[str, object]:
        """The state a test or a status line wants, in one call."""
        return {
            "lines": len(self.document),
            "top": self.top,
            "body_rows": self.body_rows,
            "focus": self.focus,
            "hover": self.hover,
            "pressed": self.pressed,
            "checked": len(self.checked_widgets()),
            "url": self.document.url,
            "status": self.buffers.status,
        }
