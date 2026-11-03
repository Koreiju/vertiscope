"""The slate grammar: a node's record as one pure-print text tree, and back.

The mothership's dialect (`docs/RESERVOIR_DESIGN.md` §3.1, `G-277`; the
mothership's verbatim N.7, N.10, O.20, M.3, N.5, R.5): a slate is one text
surface whose structure is TABS AND NEWLINES ONLY.

* A line is ``<tabs><key>[<TAB><value>]``. The key may hold spaces -- names
  are discerned by structure, never by splitting on spaces; an inner tab is
  the one separator between a key and its inline value.
* ``{ref}`` is the only markup: a memory reference to another node. The text
  beside it is an optional label. ``{}`` is a new field's on-ramp, unbound.
* A key whose children are all bare leaves holds a MULTILINE value: the
  consistently indented block beneath it. One canonical form, so a node with
  leaf-only children and a node with a multiline value print alike -- in the
  dialect they are the same thing, "rendered purely structurally".
* ``- `` and ``1. `` mark positional (keyless) children, as markdown lists do;
  they restructure the graph like any other line (R.5).
* An API object renders TYPED, read-only: ``key : Type = value`` (M.3). A
  user node renders type-stripped (N.5); types live under the hood.

`print_slate(fields) -> str` and `parse_slate(text) -> [Field]` are inverse
on canonical records (`tests/test_slate.py` holds the identities).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

REF = re.compile(r"\{([^{}]*)\}")
_MARKER = re.compile(r"^(- |\d+\. )")
_TYPED = re.compile(r"^(.*?) : (.+?)(?: = (.*))?$")


@dataclass
class Field:
    """One line of a slate, and what is indented beneath it."""

    key: str
    value: Optional[str] = None          # inline (one line) or multiline (with \n)
    children: List["Field"] = field(default_factory=list)
    type: Optional[str] = None           # typed API rendering only
    marker: str = ""                     # "- " / "1. " for positional children

    def refs(self) -> List[str]:
        """Every `{ref}` named in this field and beneath it ('' = an on-ramp)."""
        out = REF.findall(self.key) + (REF.findall(self.value) if self.value else [])
        for c in self.children:
            out += c.refs()
        return out


def _line(f: Field, depth: int, typed: bool) -> List[str]:
    pad = "\t" * depth
    head = pad + f.marker + f.key
    multiline = f.value is not None and "\n" in f.value
    if typed and f.type is not None:
        head += " : " + f.type
        if f.value is not None and not multiline:
            head += " = " + f.value
    elif f.value is not None and not multiline:
        head += "\t" + f.value
    out = [head]
    if multiline:
        out += ["\t" * (depth + 1) + v for v in f.value.split("\n")]
    for c in f.children:
        out += _line(c, depth + 1, typed)
    return out


def print_slate(fields: List[Field], typed: bool = False) -> str:
    """The slate's text: one line per field, tabs for depth."""
    out: List[str] = []
    for f in fields:
        out += _line(f, 0, typed)
    return "\n".join(out)


def _indent_unit(lines: List[str]) -> int:
    """Spaces per level when the text is space-indented (an editor may do
    that); the smallest non-zero leading run. Tabs count one level each."""
    runs = [len(l) - len(l.lstrip(" ")) for l in lines if l.strip() and l.startswith(" ")]
    return min(runs) if runs else 4


def _depth(line: str, unit: int) -> int:
    tabs = len(line) - len(line.lstrip("\t"))
    rest = line[tabs:]
    spaces = len(rest) - len(rest.lstrip(" "))
    return tabs + spaces // max(1, unit)


#: Planted (G-277): a parse that splits a field's name at its first space.
PLANT_SPACE_SPLIT = [False]


def parse_slate(text: str, typed: bool = False) -> List[Field]:
    """The fields a slate's text holds. Blank lines carry nothing."""
    lines = [l for l in text.split("\n") if l.strip()]
    unit = _indent_unit(lines)
    root = Field(key="")
    stack: List[tuple] = [(-1, root)]
    for raw in lines:
        d = _depth(raw, unit)
        body = raw.lstrip(" \t")
        m = _MARKER.match(body)
        marker = m.group(1) if m else ""
        if marker:
            body = body[len(marker):]
        f = Field(key=body, marker=marker)
        if typed:
            t = _TYPED.match(body)
            if t:
                f.key, f.type, f.value = t.group(1), t.group(2), t.group(3)
        if f.type is None and PLANT_SPACE_SPLIT[0] and " " in body.replace("\t", " "):
            # Planted (G-277): the first word is the name, as a space-leaning
            # parse reads a slate -- names with spaces break.
            f.key, f.value = body.replace("\t", " ").split(" ", 1)
        elif f.type is None and "\t" in body:
            f.key, f.value = body.split("\t", 1)
        while stack and stack[-1][0] >= d:
            stack.pop()
        stack[-1][1].children.append(f)
        stack.append((d, f))
    _fold_multiline(root)
    return root.children


def _fold_multiline(f: Field) -> None:
    """A key whose children are ALL bare leaves holds a multiline value."""
    for c in f.children:
        _fold_multiline(c)
    if (len(f.children) >= 2 and f.value is None and f.type is None
            and all(not c.children and c.value is None and not c.marker and c.type is None
                    for c in f.children)):
        f.value = "\n".join(c.key for c in f.children)
        f.children = []


def refs(text: str) -> List[str]:
    """Every `{ref}` a slate's text names, in order ('' for an on-ramp)."""
    return REF.findall(text)
