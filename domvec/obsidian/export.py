"""Render stored chunks as vault notes whose links are the page's links.

The point of the export is not to put markdown in a folder -- the store
already holds the markdown. It is to make Obsidian's graph view show the WEB
graph, and Obsidian builds its graph from one thing only: wikilinks that
appear in a note's prose.

So the export's real work is a rewrite. A chunk's markdown already carries
``[words](https://target)`` for every link the distiller resolved; wherever
that target is a page we also exported, the link becomes ``[[note|words]]``.
The sentence a reader sees is unchanged, and the edge becomes real.

Two things this deliberately does NOT do.

It does not put links inside the fenced ``domvec`` block. Obsidian does not
parse links in code fences, so an edge written there is invisible to the
graph. The fence carries the address payload the plugin renders; the prose
above it carries the graph.

It does not walk the workspace. ``Workspace.mirror_path`` names its files by
digest because "a listing that names the pages is the browsing history in
plain sight", and a vault is a listable directory of readable names shown by
name in the graph. The export reverses that on purpose, so the caller names
the pages it wants.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence
from urllib.parse import urlsplit

from .. import tokens
from ..graphstore import canonical_url

#: ``[words](target)`` as the renderer draws it. The target stops at the first
#: whitespace or paren so a trailing markdown title does not join the url.
_LINK = re.compile(r"\[([^\]]*)\]\(([^)\s]+)\)")

#: ``<target>`` -- the bare autolink form, used where a link has no words.
_AUTOLINK = re.compile(r"<((?:https?:)?//[^>\s]+)>")

_UNSAFE = re.compile(r"[^A-Za-z0-9 \-_.]+")


def _slug(text: str, limit: int = 48) -> str:
    """A basename Obsidian can hold and a person can recognise.

    Obsidian shows the BASENAME in the graph, so an unreadable name makes the
    graph unreadable -- which is the whole feature. The cid is appended by the
    caller for uniqueness rather than substituted for the words.
    """
    text = _UNSAFE.sub(" ", (text or "").replace("/", " "))
    text = " ".join(text.split())[:limit].strip()
    # Never a leading dot. Obsidian ignores dot-prefixed files and folders
    # outright, so such a note is written, indexed by nothing, invisible in
    # the vault, and any wikilink pointing at it dangles.
    #
    # It is not a corner case: a chunk whose first words are a relative url
    # names itself after them, and `../../static/oscar/js/bootstrap.min.js`
    # becomes `.. .. static oscar js bootstrap.min.js`. Two of the ninety-eight
    # notes in the toscrape export were hidden this way, and the count still
    # said ninety-eight -- the files existed, the vault just never saw them.
    #
    # Trailing dots and spaces go too: Windows silently strips them from a
    # filename, so `page.` and `page` are one file and the second export
    # overwrites the first.
    text = text.lstrip(". ").rstrip(". ")
    return text or "chunk"


#: A leading list marker or heading, which names a level and not the content.
_MARKER = re.compile(r"^\s*(?:[-*+]|#{1,6}|\d+[.)])\s+")


def _title_of(md: str) -> str:
    """The chunk's own first words, for the note name."""
    for raw in (md or "").splitlines():
        line = _MARKER.sub("", raw).strip()
        # Strip link markup so a note that opens with a link is named for the
        # words rather than for the url.
        line = _LINK.sub(r"\1", line)
        line = _AUTOLINK.sub("", line).strip()
        if line:
            return line
    return ""


def _reflow(md: str, per_level: int = 2) -> str:
    """Re-indent by nesting LEVEL rather than by the distiller's column.

    This is load-bearing, not cosmetic. The renderer indents by depth in the
    DOM, so a chunk rooted a few elements down opens at column 10 -- and in
    CommonMark any line indented four or more spaces is an indented CODE
    BLOCK. Obsidian parses no links inside one.

    Measured on the six-page toscrape export before this existed: 82 of 98
    notes had a minimum body indent of 4 or more, and every one of the seven
    wikilinks the rewrite produced sat on such a line. The export looked
    finished, the notes looked right in a text editor, and the graph would
    have been empty -- the same shape as the link defect that dropped three
    quarters of the store's edges unnoticed.

    Distinct indents are ranked and re-spaced at two columns per level, so the
    hierarchy the distiller found survives while the markdown stays list
    nesting instead of turning into code.
    """
    lines = (md or "").splitlines()
    widths = sorted({len(l) - len(l.lstrip(" "))
                     for l in lines if l.strip()})
    level = {w: i for i, w in enumerate(widths)}
    out = []
    for line in lines:
        if not line.strip():
            out.append("")
            continue
        width = len(line) - len(line.lstrip(" "))
        out.append(" " * (per_level * level[width]) + line.strip())
    return "\n".join(out)


def _page_slug(url: str) -> str:
    parts = urlsplit(url)
    host = (parts.netloc or "page").replace(":", "-")
    return _slug(host, 40)


@dataclass
class VaultExport:
    """What one export wrote, so a caller can assert on it."""

    root: Path
    notes: Dict[str, Path] = field(default_factory=dict)   # cid -> file
    wikilinks: int = 0          # link markup rewritten into a vault edge
    unresolved: int = 0         # link markup left pointing at the web
    pages: List[str] = field(default_factory=list)

    @property
    def note_count(self) -> int:
        return len(self.notes)


def _first_chunk_by_page(chunks: Sequence) -> Dict[str, str]:
    """url -> the cid a link to that page should land on.

    The store makes the same choice for its own hyperlink edges: a link
    contributes ONE edge, to the target page's first chunk, rather than
    fanning out over every chunk of the page it points at. Keeping the vault
    consistent with that is what lets the two graphs be compared at all.
    """
    best: Dict[str, tuple] = {}
    for c in chunks:
        rank = (c.row, c.part)
        if c.url not in best or rank < best[c.url][0]:
            best[c.url] = (rank, c.cid)
    return {url: cid for url, (_, cid) in best.items()}


def export_vault(workspace,
                 root: Path,
                 *,
                 urls: Optional[Sequence[str]] = None,
                 folder: str = "domvec") -> VaultExport:
    """Write the chosen pages' chunks into ``root`` as linked notes.

    ``urls`` is required in spirit and defaulted only for convenience in a
    workspace the caller built themselves: passing None exports every page,
    which is exactly the browsing-history-in-plain-sight case the module
    docstring warns about.
    """
    root = Path(root)
    store = workspace.store
    pages = list(urls) if urls else list(store.page_urls())

    chunks = [c for url in pages for c in store.chunks(url)]
    target_cid = _first_chunk_by_page(chunks)

    # Canonical spelling -> the cid a link lands on. Targets are canonicalised
    # before comparison because a page is stored under the url it was scanned
    # with and `canonical_url` does not always return that -- the same
    # mismatch that once dropped three quarters of the store's own resolvable
    # edges without anything noticing.
    by_canonical: Dict[str, str] = {}
    for url, cid in target_cid.items():
        by_canonical.setdefault(canonical_url(url) or url, cid)

    # Names first: a rewrite cannot point at a note whose name is not decided.
    names: Dict[str, str] = {}
    used: set = set()
    for c in chunks:
        stem = "%s-%s" % (_slug(_title_of(c.md) or _page_slug(c.url)), c.cid[:6])
        while stem in used:                # cid[:6] collision, vanishingly rare
            stem += "x"
        used.add(stem)
        names[c.cid] = stem

    out = VaultExport(root=root, pages=pages)
    folder_path = root / folder
    folder_path.mkdir(parents=True, exist_ok=True)

    for c in chunks:
        body, hits, misses = _rewrite_links(_reflow(c.md), c.url,
                                            by_canonical, names)
        out.wikilinks += hits
        out.unresolved += misses
        path = folder_path / ("%s.md" % names[c.cid])
        path.write_text(_note(c, body), encoding="utf-8")
        out.notes[c.cid] = path

    return out


def _rewrite_links(md: str,
                   base: str,
                   by_canonical: Dict[str, str],
                   names: Dict[str, str]) -> tuple:
    """Turn web links into vault edges wherever the target was exported.

    Returns the rewritten markdown, the number of links that became an edge,
    and the number left pointing at the web. Both counts are reported because
    a rewrite that silently resolved nothing looks exactly like one that
    worked, and this project has already shipped a link pass that resolved
    almost nothing while appearing to.
    """
    hits = 0
    misses = 0

    def resolve(target: str) -> Optional[str]:
        canon = canonical_url(target, base)
        if not canon:
            return None
        cid = by_canonical.get(canon)
        return names.get(cid) if cid else None

    def sub_link(m: "re.Match") -> str:
        nonlocal hits, misses
        words, target = m.group(1), m.group(2)
        note = resolve(target)
        if note is None:
            misses += 1
            # An unresolved link is made ABSOLUTE rather than left alone.
            #
            # Obsidian treats `[words](relative/path)` as an INTERNAL link and
            # puts it in the graph, so a page's own relative hrefs arrived as
            # links to vault files that do not exist. Measured in the running
            # app on the 98-note export: 13 real edges and **263 dangling
            # ones**, which is the graph view showing a few hundred phantom
            # nodes around the real ones.
            #
            # Worse, some of them RESOLVED by accident. `docs/index.html`
            # matched `obsidian-plugin/node_modules/polished/docs/index.html`,
            # so a book catalogue linked into a javascript dependency -- an
            # edge that is not merely useless but false.
            #
            # An absolute url is unambiguous: Obsidian leaves it as an
            # external link, the reader can still follow it, and it stays out
            # of the graph, which is the truth -- that page was never scanned.
            absolute = canonical_url(target, base)
            return "[%s](%s)" % (words, absolute) if absolute else m.group(0)
        hits += 1
        # `[[note|words]]` keeps the sentence reading as it did while making
        # the edge real. An empty label would draw the raw note name instead.
        return "[[%s|%s]]" % (note, words) if words.strip() else "[[%s]]" % note

    def sub_auto(m: "re.Match") -> str:
        nonlocal hits, misses
        note = resolve(m.group(1))
        if note is None:
            misses += 1
            return m.group(0)
        hits += 1
        return "[[%s]]" % note

    return _AUTOLINK.sub(sub_auto, _LINK.sub(sub_link, md or "")), hits, misses


def _note(chunk, body: str) -> str:
    """Frontmatter, the plugin's payload, then the rewritten prose.

    The fence holds only the cid. Everything the plugin needs in order to
    render the surface it looks up from the store by that cid, so the note
    never carries a second copy of state that can drift.

    The fence comes FIRST, and that is a change. It used to be last, which put
    the panel below however much prose the chunk held -- and Obsidian renders
    a reading view's sections lazily, so on a long note the surface did not
    even mount until someone scrolled to the bottom. At the top it takes the
    place the properties block used to occupy, which is where the goal asks
    for the markdown/shadow-DOM switch to live.

    The prose is FOLDED into a collapsed callout under it, and that is the
    change this docstring used to argue against.

    The argument was that the prose has to stay because Obsidian's graph reads
    links from the markdown body and not from anything a plugin draws. That is
    still true. What was wrong was the conclusion: the note showed the same
    chunk twice, once as the panel and once as prose underneath, and a reader
    looking at it sees a page that repeats itself.

    A callout is a blockquote, so everything that made the prose necessary
    survives being inside one -- the wikilinks are still parsed into
    `resolvedLinks`, Obsidian's search still finds the words, `grep` still
    finds the file. The `-` suffix on the callout type is what collapses it by
    default, so the reader gets one folded line instead of a second copy, and
    can open it when they want the plain reading or a link to click.

    Deleting the prose outright was the other option and costs more than it
    saves: the graph would lose every edge unless the links were moved into
    frontmatter, and the vault would stop being a plain-text archive of what
    was scanned. Folding costs one line.
    """
    head = [
        "---",
        "domvec: chunk",
        "cid: %s" % chunk.cid,
        'url: "%s"' % chunk.url,
        'xpath: "%s"' % chunk.xpath,
        "part: %d" % chunk.part,
        # In the unit the chunker's window is stated in, so a reader can see
        # from the note whether chunks are anywhere near the window they were
        # cut against. They were not: the window was 1200 CHARACTERS and the
        # notes it produced held a median of 165 tokens, 8% of a 2048-token
        # one. A number nobody can see is a number nobody checks.
        "tokens: %d" % tokens.count(chunk.md if hasattr(chunk, "md")
                                    else chunk.markdown),
        "chars: %d" % chunk.chars,
        "---",
        "",
    ]
    fence = "```domvec\ncid: %s\n```\n\n" % chunk.cid
    return "\n".join(head) + fence + _folded(body) + "\n"


#: The callout the prose is folded into. `-` is what makes Obsidian render it
#: collapsed; `[!quote]` reads as "this is the source text" rather than as a
#: warning or a note.
_FOLD = "> [!quote]- distilled markdown"


def _folded(body: str) -> str:
    """``body`` as a collapsed callout, or nothing when there is no body.

    Every line takes the blockquote marker, blank lines included -- a bare
    blank line ENDS a callout, so the rest of the prose would fall out of it
    and render below the fold, which is the thing being fixed.
    """
    lines = body.rstrip().splitlines()
    if not any(line.strip() for line in lines):
        return ""
    quoted = "\n".join(("> " + line) if line.strip() else ">"
                        for line in lines)
    return "%s\n%s\n" % (_FOLD, quoted)


def link_targets(workspace, urls: Optional[Sequence[str]] = None) -> List[dict]:
    """Where a link to each page should land, in both spellings.

    The `/` retrieval gesture inserts a passage into a note, and that passage
    carries the page's own links. Turning those into vault edges needs exactly
    what `export_vault` needs -- the cid a link to a page lands on -- and it
    has to be the SAME cid, or the gesture and the export would write two
    different edges for one link and the graph would show both.

    So the rule lives here, next to the export that established it, and the
    plugin asks rather than reimplementing it. `canonical` is sent alongside
    the stored url because a page is stored under the url it was scanned with
    and `canonical_url` does not always return that; matching on the stored
    spelling alone dropped three quarters of the store's own resolvable edges
    once.
    """
    store = workspace.store
    pages = list(urls) if urls else list(store.page_urls())
    chunks = [c for url in pages for c in store.chunks(url)]
    out = []
    for url, cid in _first_chunk_by_page(chunks).items():
        out.append({"url": url,
                    "canonical": canonical_url(url) or url,
                    "cid": cid})
    return out
