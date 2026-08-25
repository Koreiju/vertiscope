"""The style peripheral: layout facts kept beside the trie, never in it.

The fold reads no layout. That is not an accident of implementation — it is
what keeps a mutation's cost proportional to the mutation, because
`getBoundingClientRect` forces the browser to settle layout and doing that
per changed node would make every keystroke pay for the whole page.

So geometry is read separately, on demand, for the window a reader is
actually looking at, and held in a map keyed by address. Same shape as the
memoised binding on a trie leaf: a fact about a node that the node's identity
does not carry, maintained alongside rather than inside.

Geometry, not CSS
-----------------
Which elements form a row is answerable from where they are: overlapping
vertically, disjoint horizontally. That is one measurement. The alternative
is reading `display`, `flex-direction`, `grid-template-columns`, `float` and
`inline-block` and assembling a rule that approximates the same answer, then
disagrees with it on any site doing something unusual. The browser has
already solved the layout; the rect is that solution, read back.

What this is for
----------------
Markdown is the semantic projection — what a chunk means, for indexing and
retrieval. This is what the *visual* projection needs to draw a page as a
page: which things sit side by side, how wide they are, what is emphasised,
what is boxed. Neither projection is derived from the other; both are
derived from the trie, and this map is the extra input the visual one needs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

__all__ = ["Box", "StyleMap", "rows_of"]


@dataclass
class Box:
    """One element's geometry and emphasis, as the page actually renders it."""

    x: int = 0
    y: int = 0
    w: int = 0
    h: int = 0
    display: str = ""
    bold: bool = False
    italic: bool = False
    underline: bool = False
    size: int = 16
    align: str = ""
    boxed: bool = False
    visible: bool = True

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h

    def overlaps_vertically(self, other: "Box", slack: int = 4) -> bool:
        """Whether two elements share a band of the page.

        Slack because a row's items rarely align to the pixel — a taller
        button beside a line of text is still that row.
        """
        return (self.y < other.bottom - slack
                and other.y < self.bottom - slack)

    def beside(self, other: "Box", slack: int = 4) -> bool:
        """Same band, no horizontal overlap. That is a row."""
        if not self.overlaps_vertically(other, slack):
            return False
        return self.right <= other.x + slack or other.right <= self.x + slack


@dataclass
class StyleMap:
    """xpath -> Box, for as much of a page as has been asked about."""

    boxes: Dict[str, Box] = field(default_factory=dict)
    viewport_w: int = 0
    viewport_h: int = 0
    document_w: int = 0

    def __len__(self) -> int:
        return len(self.boxes)

    def get(self, xpath: str) -> Optional[Box]:
        """The box for an element, or for the element a text node sits in.

        A text node has no geometry of its own worth having — it inherits the
        band its element occupies — so an address ending in a text step
        resolves to its parent.
        """
        box = self.boxes.get(xpath)
        if box is not None:
            return box
        return self.boxes.get(xpath.split("/text()")[0])

    def missing(self, xpaths: Iterable[str]) -> List[str]:
        """Which of these have not been measured yet.

        The caller measures a window at a time; this is what keeps a second
        look at the same window free.
        """
        out: List[str] = []
        for xpath in xpaths:
            owner = xpath.split("/text()")[0]
            if owner not in self.boxes:
                out.append(owner)
        return out

    def absorb(self, xpaths: Sequence[str], payload: dict) -> int:
        """Fold one measurement in. Returns how many boxes it added."""
        raw = (payload or {}).get("styles") or []
        added = 0
        for xpath, item in zip(xpaths, raw):
            if not item:
                continue
            self.boxes[xpath] = Box(
                x=int(item.get("x", 0)), y=int(item.get("y", 0)),
                w=int(item.get("w", 0)), h=int(item.get("h", 0)),
                display=str(item.get("d", "")),
                bold=bool(item.get("b")), italic=bool(item.get("i")),
                underline=bool(item.get("u")),
                size=int(item.get("s", 16)), align=str(item.get("a", "")),
                boxed=bool(item.get("box")), visible=bool(item.get("vis", 1)),
            )
            added += 1
        self.viewport_w = int((payload or {}).get("vw", 0)) or self.viewport_w
        self.viewport_h = int((payload or {}).get("vh", 0)) or self.viewport_h
        self.document_w = int((payload or {}).get("doc", 0)) or self.document_w
        return added

    def forget(self, prefix: str) -> int:
        """Drop everything under a subtree. A page that left takes its geometry."""
        gone = [k for k in self.boxes if k == prefix or k.startswith(prefix + "/")]
        for k in gone:
            self.boxes.pop(k, None)
        return len(gone)


def rows_of(items: Sequence[Tuple[str, Box]],
            slack: int = 4) -> List[List[Tuple[str, Box]]]:
    """Group items into the horizontal bands the page puts them in.

    Sorted by where they are, then cut wherever the next item starts a new
    band rather than continuing the current one. Items within a row keep
    left-to-right order, which is reading order for the terminal too.

    This is the whole of the row detection. A nav bar's five links share a
    band and sit side by side; a paragraph following them does not overlap
    that band at all. No rule about flex or float is consulted, because the
    positions already answer it.
    """
    live = [(p, b) for p, b in items if b.visible and b.w > 0 and b.h > 0]
    if not live:
        return []
    live.sort(key=lambda pb: (pb[1].y, pb[1].x))

    rows: List[List[Tuple[str, Box]]] = []
    current: List[Tuple[str, Box]] = [live[0]]
    band = live[0][1]
    for path, box in live[1:]:
        if box.overlaps_vertically(band, slack) and all(
                box.beside(other, slack) for _, other in current):
            current.append((path, box))
            # The band is the union: a tall item beside short ones keeps the
            # row open for anything else in its span.
            band = Box(x=min(band.x, box.x), y=min(band.y, box.y),
                       w=max(band.right, box.right) - min(band.x, box.x),
                       h=max(band.bottom, box.bottom) - min(band.y, box.y))
        else:
            current.sort(key=lambda pb: pb[1].x)
            rows.append(current)
            current = [(path, box)]
            band = box
    current.sort(key=lambda pb: pb[1].x)
    rows.append(current)
    return rows
