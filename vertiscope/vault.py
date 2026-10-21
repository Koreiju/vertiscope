"""A vault note, addressed like a page.

`T-5` asks for the local vault inside the patricia trie. The trie is keyed on
`url : xpath : taxonomy : content`, and a note has neither a url nor an xpath,
so both have to be *defined* rather than assumed — and defined so that
everything already reading the trie keeps working, because the point of putting
notes in the trie is to reuse the chunker, the vectoriser and retrieval rather
than to grow a second pipeline beside them.

**The url.** ``vault://<vault>/<relative/path.md>``. `address.url_steps` splits
on `urlsplit`, so this gives ``("vault://<vault>", "relative", "path.md")`` —
the vault as origin and the path as segments, which is the shape a global trie
wants: notes group by vault before they group by folder. A non-http scheme is
not new here; `Workspace.index_html` already addresses local files as
``file://``.

**The xpath.** Markdown's own tree, in the sensor's own spelling. Every step is
``name[ordinal]`` counted per parent and per kind — exactly what
`core/js/sensor.js::stepFor` does for DOM children — so
`ContentAddress.shape` works unchanged (it strips ``[n]`` to group repeats) and
a note's addresses read alongside a page's rather than in a second dialect.

A heading opens an explicit ``section``, and **the heading and the blocks it
introduces are siblings inside it**:

    # Notes            ->  /section[1]/h1[1]
    a paragraph        ->  /section[1]/p[1]
    ## Analysis        ->  /section[1]/section[1]/h2[1]
    a paragraph        ->  /section[1]/section[1]/p[1]
    ```python          ->  /section[1]/section[1]/code[1]
    ## Results         ->  /section[1]/section[2]/h2[1]

**The `section` wrapper is load-bearing, not decoration.** The obvious scheme
hangs the blocks *under* the heading step — ``/h1[1]/p[1]`` — and it renders
every paragraph as a heading. `markdown.py`'s walk carries a heading label down
to its children on purpose:

    if is_element and label in _HEADINGS and child_label not in _HEADINGS:
        child_label = label

and it is right to, for HTML: ``<h3><div>Technology</div></h3>`` means the div
IS heading text, and 124 of the Guardian's 181 headings depend on that rule. But
markdown's heading does not *contain* the section it opens — it *names* it. The
two models disagree, HTML's is the one the trie implements, and nesting blocks
under a heading asserts containment that markdown never meant. The wrapper says
sectioning in the vocabulary the renderer already reads, which is what HTML5's
own ``<section>`` is for. Measured before and after on one note: prose drawn as
``# Prose about…`` at every level, versus prose drawn as prose.

Inline links and images likewise get their **own element step** —
``/section[1]/p[1]/a[1]`` — because in HTML an anchor is an element with its own
xpath, and a `urls.*` detection sharing its block's address made the renderer
draw the whole paragraph as one link label:
``[see [[Vortex Lattice]]](Vortex Lattice)``.

**What it is NOT.** These addresses are not evaluable XPath, and nothing should
try to resolve one against a DOM. That is not a new compromise either:
`sensing._xpath` already emits ``#shadow-root`` steps which are *deliberately*
not legal XPath, because no XPath crosses a shadow boundary. A vault address is
resolvable by re-parsing the note, which is the same contract.

**The taxonomy.** Existing categories only. `address._CLASS_BY_CATEGORY` gives
every address a class from its category, so a new *subcategory* under a known
category degrades correctly and a new *category* would not. Prose is
``text.visible`` because that is what it is; a fence is ``text.code``, which
falls back to class ``text`` — imperfect, since `_CANONICAL_CLASS` reaches
class ``code`` only through ``json_data``, and noted here rather than fixed by
inventing a category.

Block-level only, and that is the whole job: the trie addresses *units*, and a
unit is a block. Inline links and images are pulled out as their own
detections, because `urls` and `media` are what retrieval and the graph edges
read.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Dict, List, Optional, Tuple

from .core.content_tagger import ContentTag

__all__ = ["note_url", "note_path_of", "tag_note", "chunk_preview",
           "VAULT_SCHEME"]

#: The scheme that says "this came from the vault, not the web".
VAULT_SCHEME = "vault"

#: An ATX heading: one to six hashes, a space, then the text. Setext headings
#: (underlined with `===`) are not matched, and that is a known gap rather
#: than an oversight — Obsidian writes ATX, and a heading form we do not parse
#: degrades to a paragraph rather than to a wrong address.
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")

#: A fence opener: three or more backticks or tildes, then an optional info
#: string. The closing fence must use the same character and be at least as
#: long, which is what lets a fence contain a shorter fence.
_FENCE = re.compile(r"^(\s*)(`{3,}|~{3,})\s*(\S*)")

#: A list item marker. The captured indent decides nesting.
_ITEM = re.compile(r"^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$")

#: A blockquote line.
_QUOTE = re.compile(r"^\s*>\s?(.*)$")

#: A table row: starts and ends with a pipe, loosely.
_TABLE = re.compile(r"^\s*\|.*\|\s*$")

#: An HTML comment, opening and closing. Markdown hides these and so does
#: Obsidian, so they are not content -- see `tag_note`.
_COMMENT_OPEN = re.compile(r"^\s*<!--")
_COMMENT_CLOSE = re.compile(r"-->\s*$")

#: A stored cell output's opening marker (`outputs.ts`). Recognised by
#: name, because its content is an OUTPUT and not prose or source -- see
#: `tag_note`.
_NB_OUTPUT = re.compile(r"^\s*<!--\s*nb-output\b")
_NB_OUTPUT_CLOSE = re.compile(r"^\s*<!--\s*/nb-output\b")

#: Inline image, then inline link. Image first: `![a](b)` also matches the link
#: pattern, and taking links first would address every image as a link and
#: lose the media class.
_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)[^)]*\)")
_LINK = re.compile(r"(?<!!)\[([^\]]*)\]\(([^)\s]+)[^)]*\)")
#: An Obsidian wikilink, embed form included.
_WIKILINK = re.compile(r"(!?)\[\[([^\]|#]+)(?:[#|][^\]]*)?\]\]")


def note_url(vault: str, rel_path: str) -> str:
    """``vault://<vault>/<rel_path>``, with the path POSIX-spelled.

    Windows paths arrive with backslashes and a url may not carry them, so the
    separator is normalised here rather than at every call site. A leading
    separator is dropped so the path is genuinely relative: ``urlsplit`` would
    otherwise read ``//notes`` as a netloc.
    """
    rel = str(rel_path).replace("\\", "/").lstrip("/")
    return f"{VAULT_SCHEME}://{vault}/{rel}"


def note_path_of(url: str) -> Optional[Tuple[str, str]]:
    """``(vault, rel_path)`` from a note url, or None if it is not one.

    The inverse matters: a chunk read back out of the store carries only its
    url, and a panel opening the note behind it needs the path again.
    """
    prefix = f"{VAULT_SCHEME}://"
    if not url.startswith(prefix):
        return None
    rest = url[len(prefix):]
    vault, _, rel = rest.partition("/")
    if not vault or not rel:
        return None
    return vault, str(PurePosixPath(rel))


class _Addresser:
    """Per-parent, per-kind ordinals — `sensor.js::stepFor`'s rule.

    Kept as a class because the counters are state the walk threads through,
    and a closure over a dict hid that the section stack and the counters have
    to move *together*.
    """

    def __init__(self) -> None:
        #: Open sections, as (heading level, path). Level 0 is the implicit
        #: root section, which exists so that content before the first heading
        #: has somewhere to live: a note may open with prose, and a frontmatter
        #: block always precedes every heading.
        self.stack: List[Tuple[int, str]] = [(0, "")]
        #: Ordinals per parent path, keyed (parent, kind).
        self.counts: Dict[Tuple[str, str], int] = {}

    @property
    def path(self) -> str:
        return self.stack[-1][1]

    def step(self, kind: str, parent: Optional[str] = None) -> str:
        """Next address for `kind` under `parent` (default: the open section)."""
        parent = self.path if parent is None else parent
        key = (parent, kind)
        self.counts[key] = self.counts.get(key, 0) + 1
        return f"{parent}/{kind}[{self.counts[key]}]"

    def open_section(self, level: int) -> str:
        """Close sections at or below `level`, open one, return its path.

        Closing drops the closed sections' counters. A heading never reopens a
        section, so those keys are unreachable; keeping them would only let a
        later sibling section inherit a stale ordinal and collide.
        """
        while len(self.stack) > 1 and self.stack[-1][0] >= level:
            dead = self.stack.pop()[1]
            for key in [k for k in self.counts
                        if k[0] == dead or k[0].startswith(dead + "/")]:
                del self.counts[key]
        section = self.step("section")
        self.stack.append((level, section))
        return section


def _inline(text: str, block: str, addr: "_Addresser",
            out: List[ContentTag]) -> None:
    """Pull links and images out of one block, each as its own element.

    They get a child step of the block (``…/p[1]/a[1]``) rather than the
    block's own address, because in HTML an anchor IS an element with its own
    xpath and the renderer reads them that way. Sharing the block's address
    made a `urls.internal` detection consume the whole paragraph as its link
    label.

    `sub` is the match's index among that mechanism's hits in this block, which
    is **intrinsic** as `ContentTag` requires: re-parsing the block yields the
    same order, so the address is re-derivable by anyone holding it and does
    not depend on the order these regexes happen to run in.
    """
    for i, m in enumerate(_IMAGE.finditer(text)):
        out.append(ContentTag(xpath=addr.step("img", parent=block),
                              category="media", subcategory="images",
                              value=m.group(2), source_attr="md_image",
                              sub=f"[{i}]"))
    for i, m in enumerate(_LINK.finditer(text)):
        target = m.group(2)
        kind = "external" if re.match(r"^[a-zA-Z][\w+.-]*:", target) else "internal"
        out.append(ContentTag(xpath=addr.step("a", parent=block),
                              category="urls", subcategory=kind,
                              value=target, source_attr="md_link", sub=f"[{i}]"))
    for i, m in enumerate(_WIKILINK.finditer(text)):
        # A wikilink always points inside the vault, so it is internal whatever
        # it looks like. The embed form (`![[x]]`) is still a link to a note,
        # not a media url: the media is the note's, and calling it media here
        # would put a markdown path in the image graph.
        out.append(ContentTag(xpath=addr.step("a", parent=block),
                              category="urls", subcategory="internal",
                              value=m.group(2).strip(),
                              source_attr="md_wikilink", sub=f"[{i}]"))


def tag_note(text: str, *,
             lines_at: Optional[Dict[str, Tuple[int, int]]] = None,
             ) -> List[ContentTag]:
    """Block-level parse of one note into addressed detections.

    Returns tags in document order. The order is the contract `from_tags`
    relies on when no `doc_pos` map is supplied: it records arrival, and
    arrival is document order here because this is a single forward pass.

    ``lines_at``, when given, is filled with ``xpath -> (first_line,
    last_line)``, both 0-based and inclusive. It is an OUT-PARAMETER rather
    than a second return value so that every existing caller keeps working
    unchanged; the map is wanted by exactly one of them.

    What it is for: `P-N8` asks the panel to show where the chunker cut, and a
    chunk knows its addresses but not the source lines they came from. Only
    this pass knows both, because only this pass is looking at the text.
    """
    lines = text.splitlines()
    addr = _Addresser()
    out: List[ContentTag] = []
    i = 0
    n = len(lines)

    def mark(xpath: str, first: int, last: int) -> None:
        """Record a block's line span, if anyone asked for the map."""
        if lines_at is not None:
            lines_at[xpath] = (first, last)

    # YAML frontmatter, when it opens on the very first line. Addressed as
    # metadata rather than skipped: it holds tags and aliases that retrieval
    # should see, and dropping it would make the note's own properties the one
    # part of the vault the trie cannot reach.
    if i < n and lines[i].strip() == "---":
        j = i + 1
        while j < n and lines[j].strip() != "---":
            j += 1
        if j < n:                                # closed; an unclosed `---` is a rule
            body = "\n".join(lines[i + 1:j]).strip()
            if body:
                xpath = addr.step("frontmatter")
                mark(xpath, i, j)
                out.append(ContentTag(xpath=xpath,
                                      category="text", subcategory="metadata",
                                      value=body, source_attr="yaml"))
            i = j + 1

    para: List[str] = []
    #: Source line the buffered paragraph began on. A paragraph is the one
    #: block whose extent is not known when it starts, so its start is carried
    #: rather than derived.
    para_from = 0
    #: True between a stored output's markers, so the fence inside one is
    #: labelled `output` rather than `code`. See the comment branch below.
    in_output = False

    def flush(upto: int = -1) -> None:
        """Emit the buffered paragraph, if any.

        `upto` is the line AFTER the paragraph, so the span ends at `upto - 1`;
        callers pass the index they are about to dispatch.
        """
        if not para:
            return
        value = "\n".join(para).strip()
        held = len(para)
        para.clear()
        if not value:
            return
        xpath = addr.step("p")
        end = (upto - 1) if upto >= 0 else (para_from + held - 1)
        mark(xpath, para_from, max(para_from, end))
        out.append(ContentTag(xpath=xpath, category="text",
                              subcategory="visible", value=value,
                              source_attr=""))
        _inline(value, xpath, addr, out)

    while i < n:
        line = lines[i]

        fence = _FENCE.match(line)
        if fence:
            # A fence ends the paragraph before it, then consumes to its close.
            # Scanned rather than split on the next fence-looking line, because
            # the content of a code block is verbatim and a `#` inside it is
            # not a heading.
            flush(i)
            marker, info = fence.group(2), fence.group(3)
            j = i + 1
            body: List[str] = []
            while j < n:
                close = _FENCE.match(lines[j])
                if (close and close.group(2)[0] == marker[0]
                        and len(close.group(2)) >= len(marker)):
                    break
                body.append(lines[j])
                j += 1
            xpath = addr.step("output" if in_output else "code")
            mark(xpath, i, min(j, n - 1))
            out.append(ContentTag(
                xpath=xpath, category="text",
                subcategory="output" if in_output else "code",
                value="\n".join(body),
                source_attr="nb-output" if in_output else (info or "code")))
            i = j + 1
            continue

        head = _HEADING.match(line)
        if head:
            flush(i)
            level = len(head.group(1))
            addr.open_section(level)
            xpath = addr.step(f"h{level}")
            mark(xpath, i, i)
            out.append(ContentTag(xpath=xpath, category="text",
                                  subcategory="visible", value=head.group(2),
                                  source_attr="heading"))
            _inline(head.group(2), xpath, addr, out)
            i += 1
            continue

        if _COMMENT_OPEN.match(line):
            # An HTML comment is not content, and skipping it is not tidiness.
            #
            # Every markdown renderer hides these, Obsidian included, so by the
            # affine-map rule -- what you see is what you get -- a comment is
            # not something the reader sees and must not become visible text.
            # It arrived as a real problem rather than a principle: step 4
            # stores a cell's output between `<!-- nb-output … -->` markers, and
            # tagging those as paragraphs put `hash=…`, `count=…`, `status=ok`
            # into the chunk's own text. Measured on one note: a search for
            # "nb-output hash status" retrieved it, and every notebook note's
            # vector carried the same bookkeeping tokens, which is exactly the
            # in-chunk quality `M-11` says decides how representative the
            # embedding is.
            #
            # The output's CONTENT is untouched -- it sits between the markers,
            # not inside them. And nothing is lost: `vault.py`'s addresses are
            # resolvable by re-parsing the note, so a caller wanting `hash` or
            # `status` reads the file, rather than the index carrying a second
            # copy of it.
            flush(i)
            # A cell's OUTPUT is neither prose nor source, and saying which it
            # is turned out to be necessary rather than decorative.
            #
            # Dropping the markers made the output's fence an immediate `code`
            # sibling of the cell's own fence, and `markdown.py` merges adjacent
            # same-label runs -- so the source and the result came out as ONE
            # line: `print("…") critical current density 4.2e6 A/cm2`. The
            # markers had been separators as well as metadata. A distinct label
            # restores the separation AND names the thing: §3 of
            # NOTEBOOK_PANEL_DESIGN lists `output` among a note's content
            # classes, and this is one.
            if _NB_OUTPUT.match(line):
                in_output = True
            elif _NB_OUTPUT_CLOSE.match(line):
                in_output = False
            j = i
            while j < n and not _COMMENT_CLOSE.search(lines[j]):
                j += 1
            if j >= n:
                # Unclosed. Skip THIS LINE only, and let the rest of the note be
                # read as content.
                #
                # Consuming to the end is the tempting reading of "a comment runs
                # until it closes", and it costs the whole document: a truncated
                # write or a hand-edit that lost a `-->` would silently delete
                # every address below it from the trie, so the note would be
                # indexed as its first paragraph and nothing else. `outputs.ts`
                # takes the same view of an unclosed block for the same reason.
                # An unclosed marker is a defect in one line; it must not be
                # allowed to be a defect in the note.
                in_output = False
                i += 1
                continue
            i = (j + 1) if j < n else n
            continue

        item = _ITEM.match(line)
        if item:
            flush(i)
            xpath = addr.step("li")
            mark(xpath, i, i)
            out.append(ContentTag(xpath=xpath, category="text",
                                  subcategory="visible", value=item.group(3),
                                  source_attr="list_item"))
            _inline(item.group(3), xpath, addr, out)
            i += 1
            continue

        if _TABLE.match(line):
            flush(i)
            j = i
            rows: List[str] = []
            while j < n and _TABLE.match(lines[j]):
                rows.append(lines[j].strip())
                j += 1
            xpath = addr.step("table")
            mark(xpath, i, max(i, j - 1))
            value = "\n".join(rows)
            out.append(ContentTag(xpath=xpath, category="text",
                                  subcategory="visible", value=value,
                                  source_attr="table"))
            _inline(value, xpath, addr, out)
            i = j
            continue

        quote = _QUOTE.match(line)
        if quote:
            flush(i)
            j = i
            body = []
            while j < n and (m := _QUOTE.match(lines[j])):
                body.append(m.group(1))
                j += 1
            xpath = addr.step("blockquote")
            mark(xpath, i, max(i, j - 1))
            value = "\n".join(body).strip()
            out.append(ContentTag(xpath=xpath, category="text",
                                  subcategory="visible", value=value,
                                  source_attr="blockquote"))
            _inline(value, xpath, addr, out)
            i = j
            continue

        if not line.strip():
            flush(i)
            i += 1
            continue

        if not para:
            para_from = i
        para.append(line)
        i += 1

    flush()
    return out


def chunk_preview(text: str, rel_path: str, *, vault: str = "vault",
                  context_window: Optional[int] = None) -> List[Dict]:
    """Where the chunker WOULD cut this text, as source line spans.

    `P-N8`: *the panel draws where the chunker cut.* Not decoration -- at a
    256-token window the cuts are frequent, and they are the only explanation a
    reader has for why retrieval returned half a section.

    **Computed from the text in hand, not read back from the store**, and that
    is the deliberate half. The design said "read straight from the trie", which
    is right for a note nobody is editing and wrong for the one on screen: a
    stored boundary is stale from the first keystroke, and a gutter mark that
    is confidently in the wrong place is worse than an absent one -- it answers
    "why did my section split" with last week's answer.

    What makes that safe is that this is the SAME pipeline `Workspace.index_note`
    runs -- `tag_note`, `AddressTrie.from_tags`, `render_trie` -- with the store
    write left out. So the preview agrees with what indexing would produce by
    construction rather than by intention, and
    `test_preview_agrees_with_what_indexing_stores` is the arm that keeps it
    that way.

    Returns one entry per chunk: its index, its 0-based inclusive line span, its
    token count against the window, and the address of its root.
    """
    from .markdown import DEFAULT_CONTEXT_WINDOW, render_trie
    from .trie import AddressTrie
    from . import tokens as _tokens

    window = context_window or DEFAULT_CONTEXT_WINDOW
    lines_at: Dict[str, Tuple[int, int]] = {}
    tags = tag_note(text, lines_at=lines_at)
    url = note_url(vault, rel_path)
    chunks = render_trie(AddressTrie.from_tags(tags, url),
                         context_window=window)

    def span(xpath: str) -> Optional[Tuple[int, int]]:
        """The lines an address covers, walking UP when it is an inline one.

        `…/p[1]/a[1]` is a link inside a paragraph and has no line of its own --
        only blocks are marked. Its parent is where it is written, so the walk
        trims one step at a time rather than giving up, which would drop every
        chunk whose first line happens to be a link.
        """
        at = xpath
        while at:
            if at in lines_at:
                return lines_at[at]
            cut = at.rfind("/")
            if cut <= 0:
                return None
            at = at[:cut]
        return None

    out: List[Dict] = []
    for index, chunk in enumerate(chunks):
        spans = [s for s in (span(line.address.xpath) for line in chunk.lines)
                 if s is not None]
        if not spans:
            # A chunk whose every address is unmappable would draw a mark
            # nowhere. Skipped rather than clamped to line 0, where it would sit
            # on top of the note's first line and claim to explain it.
            continue
        body = chunk.markdown
        out.append({
            "index": index,
            "start_line": min(a for a, _ in spans),
            "end_line": max(b for _, b in spans),
            "xpath": chunk.xpath,
            "part": chunk.part,
            "tokens": _tokens.budget(body),
            "window": window,
            "over_window": _tokens.budget(body) > window,
        })
    # By first line, because that is the order a reader meets them in -- the
    # chunker emits by trie descent, which is not the same thing.
    out.sort(key=lambda c: (c["start_line"], c["end_line"]))
    return out
