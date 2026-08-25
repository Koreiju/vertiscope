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
interprets CSS; `domvec.style` reads the rects and this arranges them.

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

__all__ = ["Cell", "render_wireframe", "visual_text", "DEFAULT_WIDTH"]

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


def render_wireframe(
    leaves: Sequence[Tuple[ContentAddress, str, str]],
    styles: StyleMap,
    *,
    width: int = DEFAULT_WIDTH,
    unicode: bool = False,
    gap: int = 1,
) -> List[WireLine]:
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
        out: List[WireLine] = []
        for _owner, units in by_path.items():
            for address, text, _kind in units:
                out.append(WireLine(text=visual_text(text)[:width],
                                    addresses=[address]))
        return out

    lines: List[WireLine] = []
    for band in rows_of(boxed_items):
        cells: List[Cell] = []
        for owner, box in band:
            for address, text, kind in by_path.get(owner, []):
                cells.append(Cell(text=visual_text(text), address=address,
                                  width=box.w,
                                  bold=box.bold, boxed=box.boxed, kind=kind))
        if not cells:
            continue

        if len(cells) == 1:
            cell = cells[0]
            body = _emphasise(cell)
            if cell.kind == "rule":
                lines.append(WireLine(text=art["rule"] * width))
                continue
            for i, piece in enumerate(_wrap(body, width)):
                lines.append(WireLine(
                    text=piece,
                    addresses=[cell.address] if cell.address else [],
                    spans=[(0, len(piece))]))
                if cell.kind == "heading" and i == 0:
                    lines.append(WireLine(text=art["head"] * min(len(piece), width)))
            continue

        # A row. Columns at the page's own proportions, each wrapped inside
        # its own width, then stacked so the row is as tall as its tallest
        # column and every column stays in its lane.
        widths = _allocate(cells, width, gap)
        columns = [_wrap(_emphasise(c), w) for c, w in zip(cells, widths)]
        height = max(len(col) for col in columns)
        for row_index in range(height):
            parts: List[str] = []
            spans: List[Tuple[int, int]] = []
            column_start = 0
            for col, w in zip(columns, widths):
                piece = col[row_index] if row_index < len(col) else ""
                parts.append(piece.ljust(w))
                spans.append((column_start, column_start + w))
                column_start += w + gap
            lines.append(WireLine(
                text=(" " * gap).join(parts).rstrip(),
                addresses=[c.address for c in cells if c.address],
                spans=spans))
    return lines
