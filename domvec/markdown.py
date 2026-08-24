"""Trie -> markdown chunks -> JSONL. The second data checkpoint.

Retrieval happens first and rendering second: the trie is parsed as a
*detection* structure, and only then is its content rendered. So this module
takes the trie as given and never touches the DOM. Everything it needs —
structure, kind, provenance, value — is already in the addresses.

What it produces mirrors the trie:

* one markdown chunk per subtree that fits the context window;
* inside a chunk, one markdown line per surviving content unit, indented by
  its depth below the chunk root;
* an ``anchors`` array parallel to the lines, giving each line's address.

The anchors are the link back. A retrieval hit is a chunk; a chunk line is an
address; an address is an absolute xpath into the source document. Nothing in
the chain needs a second lookup structure.

Why indentation is enough
-------------------------
THEORY Thm. 17.3 gives the classical bijection between well-formed depth
sequences and ordered forests, and Cor. 17.4 concludes that indentation is a
**complete** encoding of ordered tree structure — the tree can be read back
off the markdown exactly. Prop. 17.5 states the precondition: the printing map
is faithful only when distinct nodes print distinctly. Here they do, because
each line carries its own anchor, so two identically-worded lines at the same
depth remain distinguishable even though their text is not.

The chunking hyperparameter
---------------------------
``context_window`` is the only knob. The descent is top-down: a subtree whose
rendered size fits becomes one chunk; otherwise it splits into its children
and each is tried in turn. A leaf that alone exceeds the window is emitted
whole rather than cut, because cutting it would produce a chunk whose address
does not describe its content — the address would over-claim.

This is deliberately the opposite direction from the leaf-up budget walk in
``core.chunk_builder``. Top-down keeps every chunk rooted at a real element,
so a chunk root is always something the address scheme can name and the REPL
can navigate to. Bottom-up merging produces chunks spanning sibling sets with
no common element root, which have no address.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

from .address import ContentAddress, url_steps
from .trie import AddressTrie, TrieNode, token_multiset

__all__ = [
    "MarkdownChunk",
    "MarkdownLine",
    "render_trie",
    "write_jsonl",
    "read_jsonl",
    "DEFAULT_CONTEXT_WINDOW",
]

DEFAULT_CONTEXT_WINDOW = 1200
"""Characters per chunk. The same default the shipped chunker uses."""

# Element labels that carry markdown meaning. Everything else is a container
# and contributes indentation only.
_HEADINGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
_LIST_ITEMS = {"li", "dt", "dd"}
_QUOTES = {"blockquote", "q"}
_CODE = {"code", "pre", "kbd", "samp"}


# --- lines ------------------------------------------------------------------


@dataclass
class MarkdownLine:
    """One rendered content unit and the address it came from."""

    depth: int
    text: str
    address: ContentAddress

    def render(self) -> str:
        return "  " * self.depth + self.text


# --- chunks -----------------------------------------------------------------


@dataclass
class MarkdownChunk:
    """A subtree rendered as markdown, addressed by its root element."""

    url: str
    xpath: str          # the chunk root's absolute xpath
    lines: List[MarkdownLine] = field(default_factory=list)
    part: int = 0       # distinguishes several chunks sharing a root xpath

    @property
    def markdown(self) -> str:
        return "\n".join(line.render() for line in self.lines)

    @property
    def anchors(self) -> List[str]:
        """Address keys, one per line, in line order."""
        return [line.address.key() for line in self.lines]

    @property
    def chars(self) -> int:
        return len(self.markdown)

    @property
    def cid(self) -> str:
        """Chunk id: the hash of (url, root xpath, part).

        Keyed on position rather than on content for the reason recorded in
        ERRATA B10 — a content-keyed id degenerates wherever content is
        absent, and empty chunks are exactly the ones nobody inspects.
        """
        return hashlib.sha1(
            f"{self.url}|{self.xpath}|{self.part}".encode("utf-8")
        ).hexdigest()[:16]

    def to_json(self) -> dict:
        return {
            "cid": self.cid,
            "url": self.url,
            "xpath": self.xpath,
            "part": self.part,
            "lines": len(self.lines),
            "chars": self.chars,
            "md": self.markdown,
            "anchors": self.anchors,
        }

    @staticmethod
    def from_json(obj: dict) -> "MarkdownChunk":
        md_lines = obj["md"].split("\n") if obj["md"] else []
        anchors = obj["anchors"]
        if len(anchors) != len(md_lines):
            # Lines and anchors are paired *by position*, so a length mismatch
            # does not lose the tail — it misattributes every line from the
            # first surplus anchor onward, and `zip` would do that silently.
            # This has happened: a re-scanned page that shrank kept its old
            # anchors, so a 7-line chunk carried 21 and every line pointed at
            # the wrong element. Fixed at the source (GraphStore._reconcile);
            # loud here so the next cause cannot hide.
            raise ValueError(
                f"chunk {obj.get('cid', '?')}: {len(md_lines)} markdown line(s) "
                f"but {len(anchors)} anchor(s) — lines are paired with anchors "
                f"by position, so this would misattribute addresses"
            )
        lines = []
        for raw, anchor in zip(md_lines, anchors):
            stripped = raw.lstrip(" ")
            depth = (len(raw) - len(stripped)) // 2
            lines.append(MarkdownLine(
                depth=depth, text=stripped, address=ContentAddress.parse(anchor)
            ))
        return MarkdownChunk(url=obj["url"], xpath=obj["xpath"],
                             lines=lines, part=obj.get("part", 0))


# --- rendering one node -----------------------------------------------------


def _label_of(segment: str) -> str:
    return segment.split("[", 1)[0].lower()


def _is_tag_name(value: str) -> bool:
    """Whether a detection's value is an element name rather than content.

    Some detections carry the tag as their value — `_add('media', cat, xpath,
    tag, '')` — because the element *is* the finding and there is nothing else
    to record. A url never looks like this: it has a slash, a dot or a colon.
    """
    value = value.strip()
    return bool(value) and len(value) <= 12 and value.isalpha()


# Interactive detections whose *value* is the element's tag name rather than
# any content — `_add('interactive', 'links', xpath, tag, '')`. For links that
# is pure noise: the same node already yields the href as a `urls.*` unit and
# its text as a `text.visible` one, so rendering it would print "[a]" beside
# them. Controls are different — an input or a button has no other
# representation, and the REPL has to be able to see it — so those survive,
# rendered with the element's own text when it has any.
_SUPPRESSED_TAGS = frozenset({"interactive.links", "interactive.elements"})


def _heading_mark(label: str) -> str:
    return "#" * _HEADINGS.get(label, 2) + " "


# One ASCII form per render class. Minimalist and structural: nothing here
# needs a colour, a box-drawing character, or anything markdown cannot say.
# The reader acts on these directly, so a control has to look like a control
# without anyone having decided what it is for.
_RENDER_FORM = {
    "link":    lambda v, t, l: f"[{t or v}]",
    "button":  lambda v, t, l: f"< {t or v} >",
    "field":   lambda v, t, l: f"[{v}]" if v else "[ ]",
    "choice":  lambda v, t, l: f"{t or v} v",
    "check":   lambda v, t, l: f"[ ] {t or v}",
    "heading": lambda v, t, l: _heading_mark(l) + (v or t),
    "item":    lambda v, t, l: f"- {v or t}",
    "row":     lambda v, t, l: f"| {v or t}",
    "cell":    lambda v, t, l: (v or t),
    "quote":   lambda v, t, l: f"> {v or t}",
    "code":    lambda v, t, l: f"`{v or t}`",
    "image":   lambda v, t, l: (f"![{t}]({v})" if v and not _is_tag_name(v)
                                else f"![{t or 'image'}]"),
    "media":   lambda v, t, l: (f"({t or 'media'}) <{v}>" if v
                                and not _is_tag_name(v) else f"({t or 'media'})"),
    "rule":    lambda v, t, l: "---",
    "group":   lambda v, t, l: (v or ""),
    "text":    lambda v, t, l: ("\\" + v if v.startswith("#") else v),
    "none":    lambda v, t, l: None,
}


def _render_unit(
    address: ContentAddress,
    value: str,
    label: str,
    text_at_node: str = "",
) -> Optional[str]:
    """One address plus its value as one markdown line, or None to suppress.

    The content tag decides the markdown form. That is the whole of the
    mapping: THEORY Def. 10.1's `K` is a flat eighteen-label set with no
    order and no operation, so a lookup is the only thing that can be done
    with it, and anything richer would be reading structure into a label set
    that does not carry any.
    """
    value = " ".join(value.split())
    cat = address.category

    if address.tag in _SUPPRESSED_TAGS:
        return None

    # A render class, from the live path. It is drawn as what it *is*, with
    # no branch anywhere below asking what it might have meant: a search box
    # is a field because it is a field, and a pager is links because they are
    # links. The tagger's category vocabulary follows underneath, unchanged,
    # for the offline path that still speaks it.
    if address.tag in _RENDER_FORM:
        return _RENDER_FORM[address.tag](value, text_at_node or value, label)
    if cat == "media":
        # A media detection whose value is the element's *tag name* — an
        # inline `<svg>`, a `<source>` whose url was picked up elsewhere —
        # rendered as `![images](svg)`, which reads as an image located at
        # "svg". Associated Press's front page said it 384 times. There is no
        # target to name, so none is named.
        if _is_tag_name(value):
            return f"![{address.subcategory}]"
        return f"![{address.subcategory}]({value})"
    if cat == "urls":
        return f"<{value}>"
    if cat == "json_data":
        return f"`{value}`"
    if cat == "interactive":
        # A control renders as what it is, so the REPL can find it by reading
        # the markdown rather than by consulting a second index. The label is
        # the element's own text where it has one, since the detection's value
        # is only the tag name.
        shown = text_at_node or value
        sub = address.subcategory
        # A control that *is* a heading keeps both facts. 34% of the corpus's
        # headings contain a control or a link, and where the control's own
        # rendering consumed the text — a footer accordion whose `<h5>` holds
        # a toggle — the heading marker was the casualty: `( Products )` with
        # nothing saying it heads a section. It is a level-N heading and it is
        # a button; the line can say so.
        mark = "#" * _HEADINGS[label] + " " if label in _HEADINGS else ""
        if sub == "inputs":
            return f"{mark}[ ] {shown}"
        if sub in ("buttons", "event_handlers"):
            # An element carrying an `onclick` is a button in every way that
            # matters here: `kind_for` classifies it as one, and the REPL
            # clicks it like one. It used to fall through to the `[shown]`
            # form below, which meant two things, both bad. It read as an
            # empty input field — `[div[onclick]]` next to a real input's
            # `[ ] Search` — and because the widget repainted it as a button,
            # every one of them came back `( [div[onclick]] )`. That was 495
            # lines over 24 of the 136 corpus pages, and it is the third time
            # a renderer and this parser disagreed about a control's form, so
            # the fix is to have one form fewer rather than one kind more.
            return f"{mark}( {shown} )"
        if sub == "forms":
            return f"{mark}=== {shown} ==="
        return f"{mark}[{shown}]"

    # text.*
    if label in _HEADINGS:
        return "#" * _HEADINGS[label] + " " + value
    if label in _LIST_ITEMS:
        return "- " + value
    if label in _QUOTES:
        return "> " + value
    if label in _CODE:
        return f"`{value}`"
    # A value that opens with `#` *is* a markdown heading, and some are not:
    # `<meta name="theme-color" content="#14181C">` put two hex colours at the
    # top of letterboxd.com's output as `#14181C` and `#445566`, indexed and
    # rendered as headings. Hashtags, `#1 bestseller` and `#include` are the
    # same shape. Escaped so the line reads as text and the reader that keys
    # on `startswith("#")` is not fooled.
    if value.startswith("#"):
        return "\\" + value
    return value


def _dedupe(units: List[Tuple[ContentAddress, str, str]]) -> List[Tuple[ContentAddress, str, str]]:
    """Token-multiset subsumption, scoped to a single element.

    A hash can only say two units are equal (THEORY Prop. 19.3), so it cannot
    choose between them. Subsumption is a *partial order*, so it can: when one
    unit's tokens are a strict subset of another's, the superset is the better
    rendering and the subset goes. That is what collapses an ``aria-label``,
    a ``title`` attribute and the element's own text — three spellings of one
    fact — into a single line, keeping the fullest.

    URLs never collapse against prose and dedupe only on exact equality: a
    link and its label are different data even when the strings coincide.

    **Scope.** The original rule was chunk-scoped, and that was right when a
    chunk was one card: the repeated spellings it targets all live on one
    element. Once chunks merge siblings, chunk scope starts deleting *distinct
    nodes* that happen to share a string — every card in a grid carrying the
    same placeholder image collapses to one line, and with it every card's
    image address but the first. Since the address is the only link back to
    the document, that loses navigation, not just repetition.

    So the scope is the element. Repeated spellings of one fact are the same
    element by construction; the same text appearing on two elements is two
    facts about two places, and removing cross-element repetition is
    boilerplate stripping — a different mechanism, deliberately kept separate
    so the two cannot compound into content loss.
    """
    by_node: Dict[str, List[int]] = {}
    for i, (addr, _v, _l) in enumerate(units):
        by_node.setdefault(addr.xpath, []).append(i)

    dropped = set()
    for indices in by_node.values():
        if len(indices) < 2:
            continue
        textual = [
            (i, token_multiset(units[i][1]))
            for i in indices
            if units[i][0].category not in ("urls", "media")
        ]
        # multiset -> token set for the subset test; multiplicity stays in the
        # key so "buy buy" and "buy" are not merged by the exact-match branch.
        as_sets = {i: frozenset(t for t, _ in ms) for i, ms in textual}
        seen_exact: Dict[Tuple, int] = {}
        for i, ms in textual:
            if not ms:
                continue        # digits/punctuation only: no basis to compare
            if ms in seen_exact:
                dropped.add(i)
                continue
            seen_exact[ms] = i
            for j, other in textual:
                if j == i or j in dropped or not other:
                    continue
                if as_sets[i] < as_sets[j]:
                    dropped.add(i)
                    break

        # A media unit naming only the element's tag was dropped here when a
        # real url existed at the same element — the `<img>` yielding both
        # `![images](img)` and `![images](media/cache/…)` looked like one image
        # described twice. `test_suppressed_units_are_a_deliberate_choice_not_
        # a_leak` disagreed, on 20 units, and it is right: those are two
        # *addresses* with different accessors (`text()` and `src`), and a
        # url/media address disappearing from the output is the one thing that
        # guard exists to prevent. Making the rendering honest — `![images]`,
        # with no invented target — was the half that was actually wrong.
        seen_urls = set()
        for i in indices:
            addr, value, _ = units[i]
            if addr.category not in ("urls", "media"):
                continue
            if value in seen_urls:
                dropped.add(i)
            else:
                seen_urls.add(value)

    return [u for i, u in enumerate(units) if i not in dropped]


def _collect(node: TrieNode, url_depth: int) -> List[Tuple[ContentAddress, str, str, int]]:
    """Every content unit under ``node`` as (address, value, label, depth).

    Depth is measured in *element* steps, so the tag and accessor segments —
    which are addressing machinery, not document structure — do not indent.
    """
    out: List[Tuple[ContentAddress, str, str, int]] = []

    def walk(n: TrieNode, label: str, depth: int) -> None:
        if n.is_leaf and n.address is not None:
            out.append((n.address, n.value, label, depth))
            return
        for child in n.ordered_children():
            # A child two levels from a leaf is the tag segment; below that is
            # the accessor. Neither is an element, so neither adds depth.
            is_element = child.depth > url_depth and not _is_terminal_pair(child)
            child_label = _label_of(child.segment) if is_element else label
            # A heading whose text lives entirely in child elements produced
            # no heading line at all, because the branch that handles an
            # element with block children emits only that element's *own*
            # text. The Guardian's headlines are
            #
            #     <h3><div>Technology</div><span>The backlash…</span></h3>
            #
            # so 124 of its 181 headings arrived as ordinary text. The words
            # were never lost — every one of them was in the output — but the
            # structure was, which is what a heading is for.
            #
            # Everything inside a heading is part of that heading, so the
            # label carries down. A nested heading takes over, which is the
            # only case where the inner one is the truer answer.
            if is_element and label in _HEADINGS and child_label not in _HEADINGS:
                child_label = label
            walk(child, child_label, depth + 1 if is_element else depth)

    walk(node, _label_of(node.segment), 0)
    return out


def _is_terminal_pair(node: TrieNode) -> bool:
    """True for the tag and accessor segments at the bottom of a path."""
    if node.is_leaf:
        return True
    kids = list(node.children.values())
    return bool(kids) and all(k.is_leaf for k in kids)


def _render_node(node: TrieNode, url: str, url_depth: int) -> MarkdownChunk:
    units = _collect(node, url_depth)
    xpath = _xpath_of(node, url)
    if not units:
        return MarkdownChunk(url=url, xpath=xpath, lines=[])

    base = min(d for _, _, _, d in units)
    depth_of = {a.key(): d for a, _, _, d in units}

    # A control's own text, for labelling it. Taken before dedup so that a
    # label surviving only as part of a longer sibling still names its button.
    text_at: Dict[str, str] = {}
    for a, v, _lbl, _d in units:
        if a.category == "text" and v.strip():
            text_at.setdefault(a.xpath, " ".join(v.split()))

    # Elements whose control rendering will *consume* the text below. The
    # control and its text are two units at one element with unrelated raw
    # values ("button" and "Add to basket"), so `_dedupe` compares them and
    # keeps both — correctly, on what it can see. The duplication appears
    # later, when `_render_unit` draws the control using the text unit's
    # value, and the page ends up saying
    #
    #     ( Add to basket )
    #     Add to basket
    #
    # 19 times on one catalogue page. The control keeps its line, because the
    # marks are what make it a button in the REPL and what makes it clickable;
    # the plain repeat goes.
    # Only a control that will actually be drawn: `interactive.links` and
    # `interactive.elements` are suppressed, and there the text *is* the
    # content, so dropping it would lose the line rather than de-duplicate it.
    consumed = {
        a.xpath for a, _v, _lbl, _d in units
        if a.category == "interactive"
        and a.tag not in _SUPPRESSED_TAGS
        and text_at.get(a.xpath)
    }

    kept = _dedupe([(a, v, lbl) for a, v, lbl, _ in units])

    lines = []
    for a, v, lbl in kept:
        if not v.strip():
            continue
        if (a.category == "text" and a.xpath in consumed
                and " ".join(v.split()) == text_at.get(a.xpath)):
            continue
        rendered = _render_unit(a, v, lbl, text_at.get(a.xpath, ""))
        if rendered is None:
            continue
        lines.append(MarkdownLine(
            depth=depth_of[a.key()] - base, text=rendered, address=a
        ))
    return MarkdownChunk(url=url, xpath=xpath, lines=lines)


def _xpath_of(node: TrieNode, url: str) -> str:
    """Reconstruct the chunk root's absolute xpath from its trie path."""
    return getattr(node, "_xpath_cache", "") or "/"


# --- the recursive descent --------------------------------------------------


@dataclass
class RenderReport:
    """Where every addressed unit went.

    Rendering silently losing units is the failure mode that a chunk count
    cannot show, so the accounting is returned rather than logged:
    ``rendered + deduped + suppressed + empty == addresses`` is an identity
    a caller can assert. Anything not in one of those four buckets is a bug,
    and ``unaccounted`` is what names it.
    """

    addresses: int = 0
    rendered: int = 0
    deduped: int = 0
    suppressed: int = 0
    empty: int = 0

    @property
    def unaccounted(self) -> int:
        return self.addresses - (
            self.rendered + self.deduped + self.suppressed + self.empty
        )

    def summary(self) -> Dict[str, int]:
        return {
            "addresses": self.addresses,
            "rendered": self.rendered,
            "deduped": self.deduped,
            "suppressed": self.suppressed,
            "empty": self.empty,
            "unaccounted": self.unaccounted,
        }


def render_trie(
    trie: AddressTrie,
    *,
    context_window: int = DEFAULT_CONTEXT_WINDOW,
    report: Optional[RenderReport] = None,
) -> List[MarkdownChunk]:
    """Render every page in the trie into context-window-sized chunks.

    The descent is top-down and greedy: take the largest subtree that fits.
    A subtree that does not fit splits into its children; a single leaf that
    does not fit is emitted whole, because a cut leaf would be described by
    an address that over-claims what the chunk contains.

    Pass a :class:`RenderReport` to find out where every unit went.
    """
    chunks: List[MarkdownChunk] = []

    for url in trie.urls():
        steps = url_steps(url)
        page = trie.node_at(steps)
        if page is None:
            continue
        _annotate_xpaths(page, steps, url)
        _descend(page, url, len(steps), context_window, chunks)

    if report is not None:
        # Computed after the fact rather than accumulated during the descent:
        # _render_node runs speculatively to test whether a subtree fits, so
        # counting inside it would tally the same unit at every level it was
        # considered at. The descent partitions the leaves, so comparing the
        # emitted anchors against the trie is exact.
        _fill_report(trie, chunks, report)
    return chunks


def _fill_report(
    trie: AddressTrie, chunks: Sequence[MarkdownChunk], report: RenderReport
) -> None:
    """Add this render's tallies to ``report``.

    Accumulates every field, including ``addresses`` and ``rendered``. An
    earlier version assigned those two and accumulated the rest, so a report
    reused across pages compared the last page's address count against every
    page's dedup count and reported a *negative* unaccounted figure — which is
    at least a loud way to fail, since the quantity is a count and cannot be
    negative for any real reason.
    """
    emitted = {key for chunk in chunks for key in chunk.anchors}
    report.addresses += len(trie)
    report.rendered += sum(len(c.lines) for c in chunks)
    for leaf in trie.leaves():
        if leaf.address is None or leaf.address.key() in emitted:
            continue
        if not (leaf.value or "").strip():
            report.empty += 1
        elif leaf.address.tag in _SUPPRESSED_TAGS:
            report.suppressed += 1
        else:
            report.deduped += 1


def _annotate_xpaths(page: TrieNode, url_path: Sequence[str], url: str) -> None:
    """Cache each element node's absolute xpath, once, for chunk roots.

    Recomputing it per candidate chunk would be quadratic in depth, and the
    descent asks for it at every level.
    """
    def walk(node: TrieNode, prefix: str) -> None:
        node._xpath_cache = prefix or "/"
        for child in node.ordered_children():
            if child.is_leaf or _is_terminal_pair(child):
                continue
            walk(child, f"{prefix}/{child.segment}")

    page._xpath_cache = "/"
    for child in page.ordered_children():
        if child.is_leaf or _is_terminal_pair(child):
            continue
        walk(child, f"/{child.segment}")


def _descend(
    node: TrieNode,
    url: str,
    url_depth: int,
    window: int,
    out: List[MarkdownChunk],
) -> None:
    """Emit chunks for ``node``'s subtree. Leaves are partitioned, never shared."""
    chunk = _render_node(node, url, url_depth)
    if not chunk.lines:
        return
    if chunk.chars <= window:
        out.append(chunk)
        return

    element_children = [
        c for c in node.ordered_children()
        if not c.is_leaf and not _is_terminal_pair(c)
    ]
    if not element_children:
        # No element to descend into. If the overflow is *one* unit, it is
        # genuinely indivisible: cutting a single value would leave a chunk
        # whose address over-claims, and that is the rule.
        #
        # Several units are a different case, and treating them the same made
        # the window stop meaning anything on a document whose content hangs
        # off one element. A `text/plain` RFC addresses every paragraph under
        # `/html/body/pre`, so 505 units came out as **one 65,890-character
        # chunk at every window setting**. Splitting them is safe by the same
        # argument the sibling merge already relies on: the chunk stays rooted
        # at this element and `anchors` says exactly which addresses are
        # inside, so it under-claims, never over-claims.
        if len(chunk.lines) <= 1:
            out.append(chunk)
            return
        _emit_runs(chunk, window, out)
        return

    # Split, then re-merge adjacent siblings up to the window. Without the
    # merge a page whose root overflows shatters into one chunk per child —
    # measured at 83 chunks averaging 40 characters against a 1200-character
    # window, which wastes the window and buries each line's context.
    #
    # A merged chunk is rooted at *this* element and holds a contiguous run of
    # its children. That under-claims — the root names more than the chunk
    # holds — which is safe, because `anchors` says exactly which addresses
    # are inside. The direction matters: a chunk that over-claimed would let a
    # retrieval hit point at content it does not contain.
    pieces: List[Tuple[str, object]] = []
    own = _own_units_chunk(node, url, url_depth)
    if own is not None and own.lines:
        pieces.append(("fits", own))
    for child in element_children:
        rendered = _render_node(child, url, url_depth)
        if not rendered.lines:
            continue
        pieces.append(("fits" if rendered.chars <= window else "split",
                       rendered if rendered.chars <= window else child))

    buffer: List[MarkdownChunk] = []

    def flush() -> None:
        if not buffer:
            return
        out.append(_merge(buffer, url, chunk.xpath, len(out)))
        buffer.clear()

    for kind, piece in pieces:
        if kind == "split":
            flush()
            _descend(piece, url, url_depth, window, out)  # type: ignore[arg-type]
            continue
        # +len(buffer) for the newlines _merge inserts between parts. Omitting
        # them let a chunk exceed the window by one character per merged part,
        # which is small but is exactly the kind of drift that makes a
        # hyperparameter stop meaning what it says.
        size = sum(c.chars for c in buffer) + len(buffer) + piece.chars  # type: ignore[union-attr]
        if buffer and size > window:
            flush()
        buffer.append(piece)  # type: ignore[arg-type]
    flush()


def _emit_runs(
    chunk: MarkdownChunk, window: int, out: List[MarkdownChunk]
) -> None:
    """Split one element's own units into window-sized runs, in order.

    Each run keeps the element's xpath and takes a distinct ``part``, which is
    what that field is for — several chunks sharing a root already collide on
    their id without it. A line longer than the window on its own becomes its
    own run rather than being cut.
    """
    run: List[MarkdownLine] = []
    size = 0
    for line in chunk.lines:
        cost = len(line.text) + 2 * line.depth
        if run and size + cost + 1 > window:
            out.append(_part_of(chunk, run, len(out)))
            run, size = [], 0
        run.append(line)
        size += cost + 1
    if run:
        out.append(_part_of(chunk, run, len(out)))


def _part_of(
    chunk: MarkdownChunk, lines: Sequence[MarkdownLine], ordinal: int
) -> MarkdownChunk:
    piece = MarkdownChunk(url=chunk.url, xpath=chunk.xpath, part=ordinal)
    piece.lines.extend(lines)
    return piece


def _merge(
    parts: Sequence[MarkdownChunk], url: str, xpath: str, ordinal: int
) -> MarkdownChunk:
    """Join sibling chunks into one rooted at their parent.

    Several merged chunks can share a root xpath, so the chunk id mixes in an
    ordinal — otherwise two distinct chunks of one long article would collide
    on their identifier and the second would overwrite the first.
    """
    if len(parts) == 1:
        return parts[0]
    merged = MarkdownChunk(url=url, xpath=xpath)
    merged.part = ordinal
    for part in parts:
        merged.lines.extend(part.lines)
    return merged


def _own_units_chunk(
    node: TrieNode, url: str, url_depth: int
) -> Optional[MarkdownChunk]:
    """The units hanging directly off ``node``, excluding element children."""
    direct = TrieNode(segment=node.segment, depth=node.depth)
    direct._xpath_cache = getattr(node, "_xpath_cache", "/")
    for seg, child in node.children.items():
        if child.is_leaf or _is_terminal_pair(child):
            direct.children[seg] = child
    if not direct.children:
        return None
    return _render_node(direct, url, url_depth)


# --- JSONL ------------------------------------------------------------------


def write_jsonl(chunks: Iterable[MarkdownChunk], path) -> int:
    """Write chunks as JSON lines, one chunk per line, in document order.

    JSONL rather than one JSON document so the file is appendable and
    streamable: a scan that is still running can flush chunks as it produces
    them, and a reader can start before the scan finishes. A single JSON array
    would have to be closed before it parsed at all.
    """
    n = 0
    with open(path, "w", encoding="utf-8") as fh:
        for chunk in chunks:
            fh.write(json.dumps(chunk.to_json(), ensure_ascii=False) + "\n")
            n += 1
    return n


def read_jsonl(path) -> Iterator[MarkdownChunk]:
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield MarkdownChunk.from_json(json.loads(line))
