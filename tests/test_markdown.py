"""The markdown checkpoint: trie -> chunks -> JSONL -> back.

The chunk is what retrieval returns and what the REPL renders, so two
properties carry the weight:

* **the anchors are real** — every markdown line names an address that exists
  in the trie, so a hit can always be traced to a place in the document;
* **the file round-trips** — a chunk written to JSONL and read back is the
  chunk, indentation and anchors included, because the JSONL is the artifact
  everything downstream consumes.
"""

import json
import pathlib

import pytest

from vertiscope import tokens
from vertiscope.address import ContentAddress
from vertiscope.markdown import (
    DEFAULT_CONTEXT_WINDOW,
    MarkdownChunk,
    RenderReport,
    read_jsonl,
    render_trie,
    write_jsonl,
)
from vertiscope.pipeline import run_pipeline
from vertiscope.trie import AddressTrie

CORPUS = pathlib.Path(__file__).parent / "corpus"
MANIFEST = CORPUS / "manifest.json"


def _pages(limit=6):
    if not MANIFEST.exists():
        return []
    pages = [p for p in json.loads(MANIFEST.read_text())["pages"] if p.get("ok")]
    return [p for p in pages if (CORPUS / f"{p['slug']}.html").exists()][:limit]


@pytest.fixture(scope="module")
def rendered():
    out = []
    for p in _pages():
        html = (CORPUS / f"{p['slug']}.html").read_text(
            encoding="utf-8", errors="replace")
        result = run_pipeline(html, p["url"], render=False)
        trie = AddressTrie.from_tagged(result.tagged, p["url"])
        report = RenderReport()
        chunks = render_trie(trie, context_window=DEFAULT_CONTEXT_WINDOW,
                             report=report)
        out.append({"page": p["slug"], "url": p["url"], "trie": trie,
                    "chunks": chunks, "report": report})
    if not out:
        pytest.skip("frozen corpus absent; run scripts/fetch_corpus.py")
    return out


# --- anchors ---------------------------------------------------------------


def test_every_anchor_is_an_address_in_the_trie(rendered):
    """A retrieval hit must always be traceable to a place in the document."""
    for m in rendered:
        known = {a.key() for a in m["trie"].addresses()}
        for chunk in m["chunks"]:
            for key in chunk.anchors:
                assert key in known, f"{m['page']}: anchor not in trie: {key[:90]}"


def test_anchors_align_with_lines(rendered):
    for m in rendered:
        for chunk in m["chunks"]:
            assert len(chunk.anchors) == len(chunk.lines)


def test_chunks_partition_the_rendered_addresses(rendered):
    """No address appears in two chunks: the descent splits, never overlaps.

    Overlap would double-count a unit in the frequency vectors and let one
    edit invalidate two chunks, so it matters beyond tidiness.
    """
    for m in rendered:
        seen = set()
        for chunk in m["chunks"]:
            for key in chunk.anchors:
                assert key not in seen, f"{m['page']}: {key[:80]} in two chunks"
                seen.add(key)


def test_accounting_balances_on_every_page(rendered):
    """rendered + deduped + suppressed + empty == addresses."""
    for m in rendered:
        assert m["report"].unaccounted == 0, (
            f"{m['page']}: {m['report'].summary()}"
        )


# --- the context window ----------------------------------------------------


@pytest.mark.parametrize("window", [
    # `D-10`: at these two windows one ar.wikipedia table row measures 302
    # against a window of 300 and holds twelve splittable children. NEW under
    # `tokens.budget` and not a weakening of the rule -- `budget` is smaller
    # than `count`, so the descent now stops at a node it used to split
    # through, and that node lands two tokens the wrong side of the cap.
    #
    # `strict=True` deliberately: the day it is fixed this test fails until
    # the marker comes off, which is the only way a known defect does not
    # quietly become an accepted one.
    #
    # Ruled out, each by measurement rather than by reading: the sibling merge
    # (forcing it to render and measure every candidate changed nothing), the
    # own-unit run splitter (`_emit_runs` emits no such chunk), `_level_page`
    # (it *shrinks* this chunk, 304 -> 302), `_carry_affordance` (disabling it
    # leaves 302), and `_clone_chunk` (a field-for-field copy). `_descend`
    # never returns the chunk over the window, and it is over the window by
    # the time the page-global passes see it, so the growth is between those
    # two points and is not any of the named passes.
    #
    # **Superseded 2026-09-26, and not by a fix.** The contract moved: the
    # user's lenient rule (`markdown.LENIENCY`, G-86) lets a run take the piece
    # that crosses the window while it stays under 1.5x, so 302 against 300
    # is inside the bound this test now states. The growth past `_descend`
    # named above is still unexplained; it is simply no longer a violation.
    300,
    600,
    DEFAULT_CONTEXT_WINDOW,
    2400,
])
def test_oversized_chunks_are_indivisible_not_lazy(window, rendered):
    """A chunk over the window must be one element with no element children.

    The window is a hyperparameter, not a guarantee: a *single unit* larger
    than the window is emitted whole, because cutting one value would leave a
    chunk whose root address claims more than the chunk holds. What must not
    happen is a chunk overflowing while still containing a splittable subtree.

    Note the rule is now "one unit", not "one element". Several units on one
    element *are* split into parts — see
    `test_many_units_on_one_element_respect_the_window`, which is what a
    `text/plain` document is made of.

    Swept across windows, because the default is where overflow is *rarest*
    and a claim about a case is worth least where the case barely occurs.
    Measured over four corpus pages:

        window   chunks   over the window
           300      977   198  (20%)
           600      627    63
          1200      371     7
          2400      170     1

    Every one of the 198 is a single element, so 20% overflow is the rule
    working rather than failing — but at the default only seven chunks
    exercise it at all, which is thin evidence for a structural claim.

    "Over the window" is asked in `tokens.budget`, the unit the chunker
    actually spends, and that distinction is load-bearing here rather than
    pedantic. apnews' `/html/head` is thirty `<link href=…>` elements: 1,705
    tokens of rendered markdown and almost none of it words. Asked in
    `tokens.count` it reads as a 1,705-token chunk the chunker lazily refused
    to split, when the chunker had correctly seen it fit the window and left
    it alone. Scoring a splitting decision in a unit the splitter never used
    indicts it for arithmetic nobody did.
    """
    for m in rendered:
        chunks = (m["chunks"] if window == DEFAULT_CONTEXT_WINDOW
                  else render_trie(m["trie"], context_window=window))
        for chunk in chunks:
            # Measured the way the chunker measures. `len` is characters and
            # the window is tokens: comparing them says a 666-character chunk
            # overflows a 300-token window when it is 214 tokens and fits.
            # Over the LENIENT bound, not the window (`markdown.LENIENCY`,
            # G-86): a run may take the piece that crosses the window.
            from vertiscope.markdown import LENIENCY
            if tokens.budget(chunk.markdown) <= LENIENCY * window:
                continue
            roots = {line.address.xpath for line in chunk.lines}
            assert len(roots) == 1, (
                f"{m['page']}: oversized chunk "
                f"({tokens.budget(chunk.markdown)} {tokens.name()}, "
                f"window {window}) at {chunk.xpath} spans {len(roots)} "
                f"elements — it could have been split and was not"
            )


@pytest.mark.parametrize("window", [200, 600, 4000])
def test_smaller_windows_produce_more_chunks(window, rendered):
    """The hyperparameter has to actually control the partition."""
    m = rendered[0]
    small = render_trie(m["trie"], context_window=window)
    assert small, "no chunks produced"
    if window < DEFAULT_CONTEXT_WINDOW:
        assert len(small) >= len(m["chunks"])
    else:
        assert len(small) <= len(m["chunks"])


def test_no_address_is_lost_when_the_window_changes(rendered):
    """Re-chunking must repartition the same units, not drop some.

    Asked of `covered` rather than `anchors`. A line that puts a sentence's
    inline markup back together accounts for several addresses, and whether
    two fragments end up on one line depends on whether the chunker cut
    between them -- which is exactly what the window changes. Counting only
    the first address of each line therefore reported 589 addresses "lost"
    at window 200 that were sitting in the line beside it.

    `anchors` stays one-per-line for the callers that zip it against lines;
    the question here is coverage, and that is what `covered` answers.
    """
    m = rendered[0]
    base = {k for c in m["chunks"] for k in c.covered}
    for window in (200, 4000):
        other = {k for c in render_trie(m["trie"], context_window=window)
                 for k in c.covered}
        assert other == base, (
            f"window {window} changed the covered set by "
            f"{len(base ^ other)} address(es)"
        )


# --- JSONL -----------------------------------------------------------------


def test_jsonl_round_trips(tmp_path, rendered):
    m = rendered[0]
    path = tmp_path / "chunks.jsonl"
    n = write_jsonl(m["chunks"], path)
    assert n == len(m["chunks"])

    back = list(read_jsonl(path))
    assert len(back) == len(m["chunks"])
    for before, after in zip(m["chunks"], back):
        assert after.url == before.url
        assert after.xpath == before.xpath
        assert after.cid == before.cid
        assert after.markdown == before.markdown
        assert after.anchors == before.anchors
        assert [l.depth for l in after.lines] == [l.depth for l in before.lines]


def test_jsonl_is_one_object_per_line(tmp_path, rendered):
    """Appendable and streamable: each line must parse alone."""
    path = tmp_path / "chunks.jsonl"
    write_jsonl(rendered[0]["chunks"], path)
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                json.loads(line)


def test_chunk_ids_are_unique_within_a_page(rendered):
    """Several chunks can share a root xpath; their ids must still differ."""
    for m in rendered:
        cids = [c.cid for c in m["chunks"]]
        assert len(cids) == len(set(cids)), f"{m['page']}: duplicate chunk id"


def test_indentation_recovers_depth(rendered):
    """claim: THEORY Cor. 17.4 — indentation is a complete encoding.

    Round-tripping through the printed form must give back the depth
    sequence, or the markdown is not a faithful rendering of the tree.
    """
    for m in rendered:
        for chunk in m["chunks"][:20]:
            restored = MarkdownChunk.from_json(chunk.to_json())
            assert [l.depth for l in restored.lines] == [
                l.depth for l in chunk.lines
            ], f"{m['page']}: depth lost in the printed form"


def test_many_units_on_one_element_respect_the_window(rendered):
    """The window has to mean something even when there is no element to split.

    `_descend` treated "no element children" as indivisible, which is right for
    *one* oversized unit and wrong for many. A `text/plain` document addresses
    every paragraph under `/html/body/pre`, so RFC 791's 505 units came out as
    one 65,890-character chunk **at every window setting** — the hyperparameter
    had no effect at all on that shape of document.

    Splitting is safe by the argument the sibling merge already relies on: the
    chunk stays rooted at the element and `anchors` names exactly what is
    inside, so it under-claims rather than over-claims.
    """
    from vertiscope.pipeline import run_pipeline
    from vertiscope.trie import AddressTrie

    text = "\n\n".join(f"Paragraph number {i} with enough words to take up "
                       f"a measurable amount of room on the line."
                       for i in range(60))
    trie = AddressTrie.from_tagged(
        run_pipeline(text, "https://x.test/doc.txt").tagged,
        "https://x.test/doc.txt")

    counts = {}
    for window in (400, 1000, 4000):
        chunks = render_trie(trie, context_window=window)
        counts[window] = len(chunks)
        assert len({c.cid for c in chunks}) == len(chunks), \
            f"window {window}: two chunks share an id"
        from vertiscope.markdown import LENIENCY
        oversized = [c for c in chunks if tokens.count(c.markdown) > LENIENCY * window
                     and len(c.lines) > 1]
        assert not oversized, (
            f"window {window}: {len(oversized)} multi-line chunk(s) over the "
            f"window")

    assert counts[400] > counts[1000] > counts[4000], counts


def test_splitting_one_element_loses_no_address(rendered):
    """Runs partition the units; none may be dropped or shared."""
    from vertiscope.pipeline import run_pipeline
    from vertiscope.trie import AddressTrie

    text = "\n\n".join(f"Paragraph {i} " + "word " * 20 for i in range(40))
    trie = AddressTrie.from_tagged(
        run_pipeline(text, "https://x.test/doc.txt").tagged,
        "https://x.test/doc.txt")

    base = {k for c in render_trie(trie, context_window=8000) for k in c.anchors}
    for window in (300, 900):
        got = [k for c in render_trie(trie, context_window=window)
               for k in c.anchors]
        assert len(got) == len(set(got)), "an address landed in two chunks"
        assert set(got) == base, (
            f"window {window} changed the covered set by "
            f"{len(base ^ set(got))} address(es)")


# --- one element, said once --------------------------------------------------


def _lines(html, url="https://x.test/"):
    from vertiscope.pipeline import run_pipeline
    from vertiscope.trie import AddressTrie

    trie = AddressTrie.from_tagged(run_pipeline(html, url).tagged, url)
    return [l.text for c in render_trie(trie, context_window=4000) for l in c.lines]


def test_a_control_and_its_own_text_are_one_line():
    """`( Add to basket )` and `Add to basket`, 19 times on one catalogue page.

    `_dedupe` compares the raw values — "button" and "Add to basket" — and
    correctly keeps both on what it can see. The duplication appears later,
    when `_render_unit` draws the control *using* the text unit's value. The
    control keeps its line, because the marks are what make it clickable in
    the REPL; the plain repeat goes.
    """
    html = ("<html><body><form><button>Add to basket</button></form>"
            "</body></html>")
    lines = _lines(html)
    assert "( Add to basket )" in lines
    assert "Add to basket" not in lines


def test_a_links_text_survives_because_its_control_is_suppressed():
    """`interactive.links` is not drawn, so its text is the content.

    Dropping it as "consumed" would lose the line rather than de-duplicate it
    — the failure the narrower rule exists to avoid.
    """
    html = "<html><body><p><a href='/a'>Alpha Beta</a></p></body></html>"
    joined = " ".join(_lines(html))
    assert "Alpha Beta" in joined


def test_a_media_placeholder_does_not_invent_a_target():
    """`![images](svg)` reads as an image located at "svg". 384 times on one page.

    Some detections carry the element's tag as their value because the element
    *is* the finding. There is no target to name, so none is named.
    """
    html = "<html><body><svg viewBox='0 0 1 1'></svg></body></html>"
    for line in _lines(html):
        assert "(svg)" not in line, line


def test_the_placeholder_stays_but_stops_inventing_a_target():
    """An `<img>` yields two detections, and draws one line.

    Dropping one of them outright looks obviously right — one image, described
    twice — and it was tried. `test_suppressed_units_are_a_deliberate_choice_
    not_a_leak` failed on 20 units and was correct to: those are two *addresses*
    with different accessors (`text()` and `src`), and a url/media address
    vanishing from the output is exactly what that guard is for.

    The answer is to MERGE rather than to drop (`_join_media`, D-8): one line
    carrying both the caption and the target, with the second address recorded
    as `inline` because its words are visibly in that line. The leak guard
    passes, because nothing vanished.

    It is named for the PICTURE, not for the taxonomy that found it. This
    asserted `![images]` when the alt on that very element said "A Book" --
    which is the caption a reader needs and the caption an embedding of this
    chunk should carry. The property under test is that the placeholder
    survives and names no target; what it is *called* is a separate question,
    and answering it "images" was never the intent.
    """
    html = "<html><body><img src='/media/cache/x.jpg' alt='A Book'></body></html>"
    lines = _lines(html)
    assert any("/media/cache/x.jpg" in l for l in lines)
    assert not any("(img)" in l for l in lines)
    assert not any("![images]" in l for l in lines), lines

    # One image is ONE line, and it carries both the caption and the target.
    #
    # This used to require a BARE `![A Book]` beside the targeted line -- two
    # lines for one `<img>` -- and the reason given was that dropping one loses
    # an address: `test_suppressed_units_are_a_deliberate_choice_not_a_leak`
    # failed on 20 units when it was tried, and was right to.
    #
    # `_join_media` (D-8) merges them instead, and the address is not lost: the
    # alt's words are visibly in the merged line, so it is recorded as `inline`
    # -- which is what `covered` counts, and what that leak guard asks with. The
    # guard passes. So the property the old shape was protecting still holds,
    # by a mechanism that does not make a reader read one picture twice.
    #
    # Why the old shape had to go: on a live-scanned page BOTH detections at an
    # `<img>` are tagged `image`, so the two lines were `![](url)` and
    # `![alt](url)` -- the same url twice, with the caption on one line and the
    # link on the other. 365 of 835 media-bearing chunks carried such a pair,
    # and the line a reader could click was the one with no words on it.
    merged = [l for l in lines if "![A Book](/media/cache/x.jpg)" in l]
    assert merged, lines
    # And exactly one line draws this picture.
    assert len([l for l in lines if "![A Book]" in l]) == 1, lines


def test_a_heading_built_from_parts_is_still_a_heading():
    """`<h3><div>kicker</div><span>headline</span></h3>` — the Guardian's idiom.

    The branch that handles an element with block children emits only that
    element's *own* text, so a heading delegating all of its text to children
    produced no heading line at all: 124 of the Guardian's 181 headings
    arrived as ordinary text, with every word present and no structure.

    Everything inside a heading is part of that heading, so the label carries
    down to its children. A nested heading takes over, which is the one case
    where the inner one is the truer answer.
    """
    html = ("<html><body><h3><div>Technology</div>"
            "<span>The backlash against smartglasses</span></h3></body></html>")
    lines = _lines(html)
    heads = [l for l in lines if l.startswith("#")]
    assert len(heads) == 2, lines
    assert any("Technology" in h for h in heads)
    assert any("backlash" in h for h in heads)


def test_a_nested_heading_wins_over_its_ancestor():
    html = ("<html><body><h1><div>Outer</div><h4>Inner</h4></div>"
            "</h1></body></html>")
    lines = _lines(html)
    inner = [l for l in lines if "Inner" in l]
    assert inner and inner[0].startswith("#### "), inner


def test_ordinary_nesting_does_not_become_a_heading():
    """The label carries down from headings only, not from any element."""
    html = "<html><body><div><p>Just a paragraph</p></div></body></html>"
    assert not any(l.startswith("#") for l in _lines(html))


def test_a_heading_that_is_a_control_keeps_both_facts():
    """34% of the corpus's headings contain a control or a link.

    Where the control's own rendering consumed the text — a footer accordion
    whose `<h5>` holds a toggle — the heading marker was the casualty:
    `( Products )`, with nothing saying it heads a section. It is a level-N
    heading *and* a button, and the line can say both.
    """
    html = ("<html><body><h5><button>Products</button></h5>"
            "<h2><a href='/c'>Contact us</a></h2></body></html>")
    lines = _lines(html)
    assert any(l.startswith("##### (") and "Products" in l for l in lines), lines
    assert any(l.startswith("## ") and "Contact us" in l for l in lines), lines


def test_a_control_outside_a_heading_gains_no_marker():
    html = "<html><body><form><button>Add to basket</button></form></body></html>"
    for line in _lines(html):
        assert not line.startswith("#"), line


ESC = chr(92) + "#"


def test_a_value_that_opens_with_a_hash_is_not_a_heading():
    """`<meta name="theme-color" content="#14181C">` rendered as a heading.

    Two hex colours sat at the top of letterboxd.com's output as `#14181C`
    and `#445566`, indexed and read as headings by anything keying on
    `startswith("#")`. Hashtags, `#1 bestseller` and `#include` are the same
    shape.
    """
    html = ('<html><head><meta name="theme-color" content="#14181C">'
            '</head><body><p>#1 bestseller</p></body></html>')
    lines = _lines(html)
    assert not any(l.startswith("#") and not l.startswith(ESC)
                   for l in lines), lines
    assert any(l == ESC + "14181C" for l in lines), lines
    assert any(l.startswith(ESC + "1 bestseller") for l in lines), lines


def test_a_real_heading_still_opens_with_a_hash():
    lines = _lines("<html><body><h2>A Real Heading</h2></body></html>")
    assert any(l == "## A Real Heading" for l in lines), lines
