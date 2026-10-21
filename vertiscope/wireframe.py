"""The visual projection: a page drawn as a page, in ASCII.

The second renderer over the trie. `markdown.py` is the semantic one — what
a chunk *means*, flattened for indexing and retrieval, one unit per line.
This one answers a different question: what the page *looks like*. Same
leaves, same addresses, same kinds; different output, because the two jobs
pull opposite ways and a single format doing both does neither.

    trie leaves  ──┬──►  markdown   (semantic, chunked, indexed)
                   └──►  wireframe  (visual, boxed, columnar)
                            ▲
                       StyleMap (geometry, read on demand)

What makes it a wireframe rather than an indented list is the geometry.
Elements that share a horizontal band and do not overlap are a row, and a
row is drawn as columns — so a nav bar reads as a nav bar and a card grid
reads as a grid, at the widths the page actually gave them. Nothing here
interprets CSS; `vertiscope.style` reads the rects and this arranges them.

Terminal width is the only knob, and it is a real one: the same page drawn
at 80 columns and at 200 is the same structure at two resolutions, because
column widths are allocated in proportion to the page's own.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .address import ContentAddress
from .style import Box, StyleMap, rows_of

__all__ = ["Band", "Cell", "Wireframe", "render_wireframe",
           "visual_text", "DEFAULT_WIDTH"]

_MD_TARGET = re.compile(r"\]\((?:[^()\s]|\([^()]*\))*\)")


def visual_text(text: str) -> str:
    """A markdown unit as the page shows it.

    The two projections differ here and only here at the unit level: the
    semantic one keeps `[love](/tag/love/)` because a chunk leaving for the
    index has to say where it pointed, and the visual one shows `[love]`
    because that is what is on the screen. A browser does not print hrefs
    into the page, and printing them made a nav bar of five links wrap to
    three lines of url.

    The target is not lost. It is on the line's address, which is what a
    reader enacts.
    """
    return _MD_TARGET.sub("]", text)


DEFAULT_WIDTH = 100

# Drawn with ASCII rather than box-drawing characters by default: a terminal
# that cannot render `┌` renders `+`, and a wireframe that turns into mojibake
# is worse than one that is plain. `unicode=True` opts in.
_ASCII = {"h": "-", "v": "|", "tl": "+", "tr": "+", "bl": "+", "br": "+",
          "rule": "-", "head": "="}
_UNICODE = {"h": "─", "v": "│", "tl": "┌", "tr": "┐",
            "bl": "└", "br": "┘", "rule": "─", "head": "═"}


@dataclass
class Cell:
    """One drawn unit: its text, where it came from, and how wide it wants to be."""

    text: str
    address: Optional[ContentAddress] = None
    width: int = 0          # the page's own width, in css pixels
    bold: bool = False
    boxed: bool = False
    kind: str = "text"

    @property
    def enactable(self) -> bool:
        from .aam import INTERACTIVE
        return self.address is not None and self.kind in INTERACTIVE


@dataclass
class Band:
    """One horizontal band of the page: its lines, and what they came from.

    The unit of repaint. A delta touches some addresses; the bands holding
    them are redrawn and the rest of the page is not, which is the same
    property the fold and the trie already have carried up to the screen.
    """

    owners: List[str] = field(default_factory=list)
    lines: List["WireLine"] = field(default_factory=list)
    shape: str = "band"


@dataclass
class Wireframe:
    """A drawn page, addressable by band."""

    bands: List[Band] = field(default_factory=list)
    width: int = 0

    @property
    def lines(self) -> List["WireLine"]:
        return [line for band in self.bands for line in band.lines]

    def touching(self, owners) -> List[int]:
        """Which bands hold any of these elements."""
        wanted = set(owners)
        return [i for i, band in enumerate(self.bands)
                if wanted.intersection(band.owners)]


@dataclass
class WireLine:
    """One rendered row of the wireframe, and what a reader can act on in it."""

    text: str
    addresses: List[ContentAddress] = field(default_factory=list)
    # Column spans, so a click at a screen column knows which cell it hit.
    spans: List[Tuple[int, int]] = field(default_factory=list)


def _wrap(text: str, width: int) -> List[str]:
    """Break a run to a column width, on spaces where there are any.

    A long unbroken token — a url, a hash — is cut rather than allowed to
    push the column out, because a wireframe whose columns move is not
    showing the page's shape any more.
    """
    if width <= 0:
        return [""]
    words = text.split()
    if not words:
        return [""]
    out: List[str] = []
    line = ""
    for word in words:
        while len(word) > width:
            if line:
                out.append(line)
                line = ""
            out.append(word[:width])
            word = word[width:]
        if not line:
            line = word
        elif len(line) + 1 + len(word) <= width:
            line += " " + word
        else:
            out.append(line)
            line = word
    if line:
        out.append(line)
    return out


def _allocate(cells: Sequence[Cell], width: int, gap: int) -> List[int]:
    """Split the terminal across a row in proportion to the page's own widths.

    Proportional rather than equal, because a page that gives its sidebar a
    fifth of the screen and its article four fifths is saying something, and
    equal columns would throw exactly that away. Every column is guaranteed a
    floor so a narrow one is still readable rather than a vertical stack of
    single letters.
    """
    n = len(cells)
    if n == 0:
        return []
    if n == 1:
        return [width]
    inner = width - gap * (n - 1)
    if inner < n:
        return [max(1, inner // n)] * n
    floor = max(6, min(12, inner // (n * 2))) if inner >= n * 6 else 1
    weights = [max(c.width, 1) for c in cells]
    total = sum(weights)
    spare = inner - floor * n
    widths = [floor + int(spare * w / total) for w in weights]
    # Hand any rounding remainder to the widest column, which is the one a
    # reader is most likely to be reading.
    drift = inner - sum(widths)
    if drift:
        widths[weights.index(max(weights))] += drift
    return widths


def _emphasise(cell: Cell) -> str:
    """Bold, in a medium with no weights.

    Upper-casing a heading is what a typewriter did and it reads as emphasis
    without needing colour, which a piped or logged terminal may not keep.
    Only for short runs: a shouted paragraph is unreadable.
    """
    if cell.bold and cell.text and len(cell.text) <= 60:
        return cell.text.upper()
    return cell.text


def _column_signature(band: Sequence[Tuple[str, Box]],
                      tolerance: int = 24) -> Optional[Tuple[int, ...]]:
    """Where this band's columns start, rounded, or None if it has one cell.

    Two rows belong to the same table when their columns begin in the same
    places. Rounding to a tolerance is what makes that survive a real page:
    a cell with a wider border or a longer word starts a pixel or two off
    its neighbours above, and a table whose rows disagree by two pixels is
    still a table.
    """
    if len(band) < 2:
        return None
    return tuple(round(box.x / tolerance) for _path, box in band)


def _group_tables(bands: List[List[Tuple[str, Box]]]
                  ) -> List[Tuple[str, List[List[Tuple[str, Box]]]]]:
    """Consecutive bands sharing a column signature are one table.

    A table is not detected from the `<table>` tag, and deliberately so: the
    tag is the least reliable thing about tabular layout on the modern web,
    where a price list is as likely to be a grid of divs. What makes rows a
    table is that they line up, which is a fact about where they are.

    Returns ("table", [band, ...]) for a run of two or more matching bands
    and ("band", [band]) for everything else, in document order.
    """
    out: List[Tuple[str, List[List[Tuple[str, Box]]]]] = []
    run: List[List[Tuple[str, Box]]] = []
    signature: Optional[Tuple[int, ...]] = None
    for band in bands:
        current = _column_signature(band)
        if current is not None and current == signature:
            run.append(band)
            continue
        if len(run) > 1:
            out.append(("table", run))
        elif run:
            out.append(("band", run))
        run = [band]
        signature = current
    if len(run) > 1:
        out.append(("table", run))
    elif run:
        out.append(("band", run))
    return out


def _is_menu(cells: Sequence[Cell]) -> bool:
    """A row of nothing but controls is a menu bar.

    Drawn with separators rather than padded columns, because that is what a
    nav bar looks like and padding five links across a terminal turns a menu
    into a sparse table.
    """
    if len(cells) < 3:
        return False
    return all(c.kind in ("link", "button") and len(c.text) <= 40
               for c in cells)


def render_wireframe(
    leaves: Sequence[Tuple[ContentAddress, str, str]],
    styles: StyleMap,
    *,
    width: int = DEFAULT_WIDTH,
    unicode: bool = False,
    gap: int = 1,
) -> Wireframe:
    """Draw the page.

    `leaves` is (address, drawn text, render kind) — the same units markdown
    renders, already through the glyph table, so a control looks like a
    control in both projections and only the arrangement differs.
    """
    art = _UNICODE if unicode else _ASCII
    boxed_items: List[Tuple[str, Box]] = []
    by_path: Dict[str, List[Tuple[ContentAddress, str, str]]] = {}
    for address, text, kind in leaves:
        if not (text or "").strip():
            continue
        owner = address.xpath.split("/text()")[0]
        by_path.setdefault(owner, []).append((address, text, kind))
    for owner in by_path:
        box = styles.get(owner)
        if box is not None and box.visible:
            boxed_items.append((owner, box))

    if not boxed_items:
        # No geometry: fall back to reading order, which is still the page's
        # order. A wireframe with no measurements is a list, and saying so is
        # better than drawing columns that are not there.
        fallback: List[Band] = []
        for owner, units in by_path.items():
            fallback.append(Band(owners=[owner], shape="text", lines=[
                WireLine(text=visual_text(text)[:width], addresses=[address])
                for address, text, _kind in units]))
        return Wireframe(bands=fallback, width=width)

    def cells_of(band):
        out: List[Cell] = []
        for owner, box in band:
            for address, text, kind in by_path.get(owner, []):
                out.append(Cell(text=visual_text(text), address=address,
                                width=box.w, bold=box.bold,
                                boxed=box.boxed, kind=kind))
        return out

    def draw_row(cells: List[Cell], widths: List[int]) -> List[WireLine]:
        columns = [_wrap(_emphasise(c), w) for c, w in zip(cells, widths)]
        height = max((len(col) for col in columns), default=1)
        drawn: List[WireLine] = []
        for index in range(height):
            parts: List[str] = []
            spans: List[Tuple[int, int]] = []
            at = 0
            for col, w in zip(columns, widths):
                piece = col[index] if index < len(col) else ""
                parts.append(piece.ljust(w))
                spans.append((at, at + w))
                at += w + gap
            drawn.append(WireLine(
                text=(" " * gap).join(parts).rstrip(),
                addresses=[c.address for c in cells if c.address],
                spans=spans))
        return drawn

    bands: List[Band] = []

    def emit(shape: str, group, drawn: List[WireLine]) -> None:
        bands.append(Band(
            owners=[owner for band in group for owner, _b in band],
            lines=drawn, shape=shape))

    for shape, group in _group_tables(rows_of(boxed_items)):
        if shape == "table":
            # One set of column widths for the whole table, taken from the
            # widest cell in each column rather than row by row. Allocating
            # per row is what makes a table stop looking like one: every row
            # gets its own margins and nothing lines up down the page.
            rows_cells = [cells_of(band) for band in group]
            rows_cells = [r for r in rows_cells if r]
            if not rows_cells:
                continue
            columns = max(len(r) for r in rows_cells)
            template = [
                Cell(text="", width=max((r[i].width for r in rows_cells
                                         if i < len(r)), default=1))
                for i in range(columns)
            ]
            widths = _allocate(template, width, gap)
            drawn: List[WireLine] = []
            for index, cells in enumerate(rows_cells):
                padded = cells + [Cell(text="")] * (columns - len(cells))
                drawn.extend(draw_row(padded, widths))
                if index == 0 and len(rows_cells) > 2:
                    # A rule under the first row, which is where a header is
                    # if there is one. Two rows are a coincidence; three are
                    # a table with a heading.
                    drawn.append(WireLine(text=(" " * gap).join(
                        art["h"] * w for w in widths)))
            emit("table", group, drawn)
            continue

        band = group[0]
        cells = cells_of(band)
        if not cells:
            continue

        if len(cells) == 1:
            cell = cells[0]
            body = _emphasise(cell)
            if cell.kind == "rule":
                emit("rule", group, [WireLine(text=art["rule"] * width)])
                continue
            drawn = []
            for i, piece in enumerate(_wrap(body, width)):
                drawn.append(WireLine(
                    text=piece,
                    addresses=[cell.address] if cell.address else [],
                    spans=[(0, len(piece))]))
                if cell.kind == "heading" and i == 0:
                    drawn.append(WireLine(
                        text=art["head"] * min(len(piece), width)))
            emit(cell.kind, group, drawn)
            continue

        if _is_menu(cells):
            # A nav bar, drawn as one.
            text = (" " + art["v"] + " ").join(c.text for c in cells)
            spans: List[Tuple[int, int]] = []
            at = 0
            for c in cells:
                spans.append((at, at + len(c.text)))
                at += len(c.text) + 3
            drawn = [WireLine(text=piece,
                              addresses=[c.address for c in cells if c.address],
                              spans=spans)
                     for piece in (_wrap(text, width) or [""])]
            emit("menu", group, drawn)
            continue

        emit("row", group, draw_row(cells, _allocate(cells, width, gap)))
    return Wireframe(bands=bands, width=width)
