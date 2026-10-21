"""Where a chunk ends, and why it matters to the phase after the render.

The greedy merge accumulated siblings until the context window was crossed,
which packs the window well and has one bad property: a boundary is a function
of everything before it. Insert one sibling and every boundary after it shifts,
the phase never comes back, and every chunk downstream holds text it did not
hold before. `VectorQueue` gates on the digest of the markdown, so those chunks
are all genuinely new to it and all get embedded again — an O(page) cost in the
asynchronous phase for an O(1) change to the page, which is the thing the whole
design exists to avoid.

Content-defined boundaries let the piece decide. The cut fires with probability
``piece_chars / window`` from a hash of the piece's own rendered text, so the
expected content between two cuts is one window's worth with no target to tune,
and a boundary cannot be moved by an insertion that does not touch it.

Two things had to be got right, and the first was got wrong first:

* **The oracle must be address-free.** `TrieNode.exact_hash` was the obvious
  choice and is the wrong one — it folds in the node's address, so an insertion
  changes every sibling's hash and no boundary survives. Measured: the re-embed
  ratio did not move off 1.0. `subtree_hash` fails identically, its Merkle
  folding in a segment that carries the sibling ordinal. The rendered text is
  the thing a boundary should depend on, and it is what decides whether a chunk
  needs embedding at all.
* **The fill threshold is a trade, not a free parameter.** It reads the running
  total, so it is the one accumulation-dependent input left. Raising it packs
  better and re-synchronises worse, and past 0.5 it spends more than it buys.
"""

import statistics

import pytest

import vertiscope.markdown as md
from vertiscope import tokens
from vertiscope.markdown import RenderMemo, RenderReport, render_trie
from vertiscope.stream import StreamingScan

#: In TOKENS, which is the unit the chunker's window is now stated in. This
#: was 1200 when the window was characters; 400 tokens is the same physical
#: size (about 1,200 characters of this fixture's text), which keeps every
#: figure in this module's docstrings comparable to the ones measured when
#: they were written. The property under test is about where cuts land
#: relative to the fixture, so the fixture and the window have to keep their
#: proportions -- at 1200 tokens a 400-row page makes a third as many chunks
#: and the non-vacuity check below stops being able to see the defect.
WINDOW = 400


def _rows(pairs):
    body = "".join(
        '<li><h3>Item {}</h3><p>{}</p>'
        '<a href="https://e.test/{}">open {}</a></li>'.format(i, text, i, i)
        for i, text in pairs)
    return ("<html><body><header><h1>Catalogue</h1></header>"
            "<main><ul>{}</ul></main></body></html>".format(body))


def _uniform(n):
    return [(i, "body text for row {} here".format(i)) for i in range(n)]


def _varied(n, seed=5):
    import random

    rng = random.Random(seed)
    words = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta"]
    return [(i, " ".join(rng.choice(words) for _ in range(rng.randint(4, 45))))
            for i in range(n)]


def _render(html, url="https://cdc.test/p", window=WINDOW, report=None):
    scan = StreamingScan(url, context_window=window)
    return render_trie(scan.push(html, passno=0).trie, context_window=window,
                       report=report)


def _new_text(before_html, after_html, window=WINDOW):
    """Chunks in the second render holding text no chunk held in the first.

    Keyed on the text rather than on the chunk id on purpose: the id is
    address-keyed and every address below an insertion genuinely moves, so id
    churn is a separate question. What the embedder is asked to do is embed
    text it has not embedded, and that is this.
    """
    url = "https://cdc.test/p"
    scan = StreamingScan(url, context_window=window)
    memo = RenderMemo()
    first = render_trie(scan.push(before_html, passno=0).trie,
                        context_window=window, memo=memo)
    seen = {c.markdown for c in first}
    second = render_trie(scan.push(after_html, passno=1).trie,
                         context_window=window, memo=memo)
    return sum(1 for c in second if c.markdown not in seen)


@pytest.fixture
def running_total(monkeypatch):
    monkeypatch.setattr(md, "CONTENT_BOUNDARIES", False)


# --- the property the change exists for -------------------------------------


@pytest.mark.parametrize("n", [400, 1600, 6400])
def test_an_insertion_costs_a_constant_number_of_new_chunks(n):
    """Constant in the page, which is the whole claim."""
    rows = _uniform(n)
    fresh = _new_text(_rows(rows), _rows([(-1, "inserted at the head")] + rows))
    assert fresh <= 8, "{} new chunks at N={}".format(fresh, n)


@pytest.mark.parametrize("n", [400, 1600])
def test_the_running_total_does_not_have_that_property(running_total, n):
    """Non-vacuity: the defect is real and this measurement can see it.

    Without it the test above would pass on any chunker that happened to be
    fast, and there would be no evidence the boundaries are what changed.
    """
    rows = _uniform(n)
    fresh = _new_text(_rows(rows), _rows([(-1, "inserted at the head")] + rows))
    # n // 25, not n // 20: the lenient cut (`markdown.LENIENCY`, G-86) ends a
    # run slightly later, and measured 21 -> 20 new chunks at N=400 and
    # 86 -> 81 at N=1600 -- still linear in the page, against a constant 2
    # with content boundaries. The arm's claim is the linearity.
    assert fresh >= n // 25, (
        "expected an insertion to invalidate most of the page, got {} at "
        "N={}".format(fresh, n))


def test_a_middle_insertion_is_also_bounded():
    rows = _varied(1600)
    grown = rows[:800] + [(-1, "inserted in the middle")] + rows[800:]
    assert _new_text(_rows(rows), _rows(grown)) <= 8


def test_the_boundary_oracle_ignores_where_a_piece_sits():
    """The mistake that cost the first attempt.

    A hash that folds in the address changes for every sibling below an
    insertion, and then no boundary can survive one. `_piece_hash` reads the
    rendered text and nothing else.
    """
    from vertiscope.markdown import MarkdownChunk, MarkdownLine
    from vertiscope.address import ContentAddress

    def chunk(xpath):
        return MarkdownChunk(
            url="u", xpath=xpath,
            lines=[MarkdownLine(depth=1, text="the same words",
                                address=ContentAddress("u", xpath, "text",
                                                       "text()[1]"))])

    assert md._piece_hash(chunk("/html/body/li[2]")) == \
        md._piece_hash(chunk("/html/body/li[9]"))

    # ...and different words must give a different verdict, or the oracle is
    # constant and every boundary decision is the same decision.
    other = chunk("/html/body/li[2]")
    other.lines[0].text = "quite different words"
    assert md._piece_hash(other) != md._piece_hash(chunk("/html/body/li[2]"))


# --- what it must not cost --------------------------------------------------


@pytest.mark.parametrize("n", [200, 800])
def test_the_page_is_still_partitioned(n):
    """Every unit once, no chunk over the window. The chunker's contract.

    The window is counted in the unit the chunker spends it in, and that is
    now `tokens.budget` -- the render with link targets removed -- because
    the budget bounds what a MODEL is given and a target is a machine address
    the model never reads. This test asserted `tokens.count` and caught the
    change as 19 chunks "over the window" that are not over it: they are over
    the length of a string nobody was budgeting.

    Which makes the second assertion the load-bearing one. A chunk whose
    render exceeds the window is only acceptable while the whole of the
    excess is addressing, so the overshoot is measured and required to vanish
    under `for_model`. Without that arm this test would accept a chunker that
    let real prose past the window and blamed the links.
    """
    report = RenderReport()
    chunks = _render(_rows(_varied(n)), report=report)
    anchors = [a for c in chunks for a in c.anchors]
    assert len(anchors) == len(set(anchors)), "an address reached two chunks"
    assert anchors, "nothing was chunked"
    # The cap is the LENIENT bound, not the window: a run may take the piece
    # that crosses the window while it stays under 1.5x (`markdown.LENIENCY`,
    # G-86 -- the user's rule of 2026-09-26).
    over = [c for c in chunks
            if tokens.budget(c.markdown) > md.LENIENCY * WINDOW and len(c.lines) > 1]
    assert not over, "{} chunk(s) over the window".format(len(over))

    # Whatever the render carries past the window must be link targets and
    # nothing else.
    # (Past the LENIENT bound: prose may run to 1.5x the window by design.)
    cap = md.LENIENCY * WINDOW
    fat = [c for c in chunks
           if tokens.count(c.markdown) > cap and len(c.lines) > 1]
    smuggled = [c for c in fat if tokens.budget(c.markdown) > cap]
    assert not smuggled, (
        "{} chunk(s) carry PROSE past the window, not just addresses"
        .format(len(smuggled)))


@pytest.mark.parametrize("rows", [_uniform(400), _varied(400)])
def test_coverage_and_dedup_are_the_same_either_way(rows, monkeypatch):
    """Boundaries move; what is drawn does not.

    The chunker decides where to cut, not what survives. If a dedup decision
    changed with the cut points, the two would be entangled and the metric
    suite would be measuring the chunker.
    """
    html = _rows(rows)

    monkeypatch.setattr(md, "CONTENT_BOUNDARIES", False)
    a_report = RenderReport()
    a = _render(html, report=a_report)

    monkeypatch.setattr(md, "CONTENT_BOUNDARIES", True)
    b_report = RenderReport()
    b = _render(html, report=b_report)

    assert [l.text for c in a for l in c.lines] == \
        [l.text for c in b for l in c.lines]
    assert sorted(x for c in a for x in c.anchors) == \
        sorted(x for c in b for x in c.anchors)
    assert (a_report.deduped, a_report.empty, a_report.suppressed) == \
        (b_report.deduped, b_report.empty, b_report.suppressed)


def test_the_window_is_still_mostly_full():
    """Content boundaries buy delta cost with packing, and the price is capped.

    Without the fill threshold the cut fires from the first sibling and sizes
    come out exponentially distributed -- 65 chunks of median 587 where the
    running total gave 46 of 755. With it the median is within a few percent
    of the running total's, which is what makes the trade worth taking.
    """
    html = _rows(_uniform(1600))

    md.CONTENT_BOUNDARIES = False
    try:
        running = [c.chars for c in _render(html)]
    finally:
        md.CONTENT_BOUNDARIES = True
    content = [c.chars for c in _render(html)]

    assert statistics.median(content) >= 0.85 * statistics.median(running)
    assert len(content) <= 1.25 * len(running)


def test_the_fill_threshold_is_load_bearing(monkeypatch):
    """Drop it and the packing collapses, which is why it is there."""
    html = _rows(_uniform(800))
    with_fill = [c.chars for c in _render(html)]
    monkeypatch.setattr(md, "MIN_FILL", 0.0)
    without = [c.chars for c in _render(html)]
    assert statistics.median(without) < statistics.median(with_fill)
    assert len(without) > len(with_fill)


def test_a_boundary_needs_the_buffer_to_be_full_enough():
    assert not md._content_boundary(0, 100, 1200, buffered=0)
    assert not md._content_boundary(0, 100, 1200, buffered=100)
    # At the threshold the hash decides; `0 % window == 0 < chars` fires.
    assert md._content_boundary(0, 100, 1200, buffered=600)


def test_an_empty_piece_is_never_a_boundary():
    assert not md._content_boundary(12345, 0, 1200, buffered=1200)


# --- the same page must chunk the same way tomorrow -------------------------


def test_boundaries_do_not_move_between_processes():
    """A boundary is persisted the moment a chunk id is written down.

    The first version of the oracle used Python's `hash`, which is randomised
    per process. Boundaries then fell in different places in different runs:
    the same page chunked differently under different ids every restart, and a
    stored index would disagree with the next scan of the same page. It showed
    up as a test that passed alone and failed in the suite, which is a lucky
    way to find it.

    Run in subprocesses with different `PYTHONHASHSEED`, because that is the
    only way to observe it -- within one process the randomisation is fixed
    and everything looks stable.
    """
    import hashlib
    import os
    import subprocess
    import sys

    program = (
        "import hashlib;"
        "from vertiscope.stream import StreamingScan;"
        "from vertiscope.markdown import render_trie;"
        "from vertiscope.analytics.projection import _page;"
        "ch=render_trie(StreamingScan('https://d.test/p')"
        ".push(_page(400),passno=0).trie, context_window=1200);"
        "print(len(ch), hashlib.sha1(('|'.join(c.markdown for c in ch))"
        ".encode()).hexdigest()[:16])"
    )

    seen = set()
    for seed in ("0", "1", "12345"):
        env = dict(os.environ, PYTHONHASHSEED=seed)
        out = subprocess.run([sys.executable, "-c", program], env=env,
                             capture_output=True, text=True, timeout=300)
        assert out.returncode == 0, out.stderr[-800:]
        seen.add(out.stdout.strip())
    assert len(seen) == 1, "the page chunked differently per process: {}".format(
        seen)
    assert hashlib  # the import is used by the subprocess program


def test_the_oracle_is_deterministic_for_the_same_text():
    from vertiscope.markdown import MarkdownChunk, MarkdownLine
    from vertiscope.address import ContentAddress

    def chunk():
        return MarkdownChunk(
            url="u", xpath="/html/body/p",
            lines=[MarkdownLine(depth=0, text="stable words here",
                                address=ContentAddress("u", "/html/body/p",
                                                       "text", "text()[1]"))])

    assert md._piece_hash(chunk()) == md._piece_hash(chunk())
    # A known value, so a change of algorithm is a deliberate act: it would
    # re-chunk every stored page.
    assert md._piece_hash(chunk()) == 456105809
