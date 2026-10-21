"""Rendered-DOM fixtures, replayed — the tier the frozen corpus cannot reach.

`tests/corpus` holds raw HTTP. For a single-page application that is a `<div
id="app">` and a script tag, so youtube, amazon and portal.azure.com sit in
the corpus scoring well while contributing nothing: what is being tested is
our handling of an empty div.

Measured 2026-08-15 on `quotes.toscrape.com/js`, whose whole content is
written by JavaScript:

    frozen HTTP     5,806 chars ->  14 lines   (nav chrome and stylesheets)
    rendered DOM    6,964 chars ->  43 lines   (the quotes, authors and tags)

Fourteen lines of furniture, and the audit scored it as fine.

These tests read captures made by `scripts/snapshot_pages.py`, which stores
the post-hydration DOM once per settle pass that differed. Offline and
deterministic, so they can assert rather than observe.
"""

from __future__ import annotations

import pytest

from vertiscope.markdown import render_trie
from vertiscope.pipeline import run_pipeline
from vertiscope.snapshots import available, load, load_meta, mutating
from vertiscope.stream import StreamingScan
from vertiscope.trie import AddressTrie

SLUGS = available()

pytestmark_snapshots = pytest.mark.skipif(
    not SLUGS, reason="no captures; run scripts/snapshot_pages.py")


def _lines(html: str, url: str):
    trie = AddressTrie.from_tagged(run_pipeline(html, url).tagged, url)
    return [ln for chunk in render_trie(trie, context_window=1200)
            for ln in chunk.lines]


@pytestmark_snapshots
@pytest.mark.parametrize("slug", SLUGS)
def test_a_rendered_capture_yields_content(slug):
    """A hydrated page must produce more than its own furniture.

    Deliberately not a threshold on a specific number of lines: these are real
    pages and they differ. The claim is only that a captured DOM produces
    text, which is exactly what the raw-HTTP version of a JavaScript page
    fails to do.
    """
    meta, htmls = load(slug)
    assert htmls, f"{slug} has metadata but no stored DOM"

    lines = _lines(htmls[0], meta["url"])
    assert lines, f"{slug} produced no lines at all"
    assert any(len(ln.text.split()) >= 4 for ln in lines), (
        f"{slug} produced only fragments — no line with four words, which is "
        f"what an unhydrated shell looks like")


@pytestmark_snapshots
@pytest.mark.parametrize("slug", SLUGS)
def test_every_stored_snapshot_is_distinct(slug):
    """The capture deduplicates settled passes, so this must hold by design.

    It matters beyond tidiness: a replay over repeated snapshots would report
    delta work of zero and look like a triumph of incrementality, when in fact
    nothing had changed between the inputs.
    """
    _meta, htmls = load(slug)
    assert len(set(htmls)) == len(htmls), (
        f"{slug} stored {len(htmls)} snapshots but only "
        f"{len(set(htmls))} are distinct")


@pytestmark_snapshots
@pytest.mark.parametrize("slug", SLUGS)
def test_replaying_a_capture_through_the_streaming_scan_is_stable(slug):
    """Folding the sequence in must leave the trie holding the final DOM.

    The streaming path and a single cold parse of the last snapshot should
    agree about what is on the page. If they do not, incremental tagging is
    keeping something the page no longer has — the stale-content failure the
    delta machinery exists to avoid.
    """
    # Scoped to the one capture that actually fails. A blanket `xfail` on the
    # whole parametrisation marked five healthy pages as expected-to-fail —
    # they reported XPASS, which reads as noise — and it would have swallowed
    # a real regression on any of them silently. An expectation of failure
    # belongs on the case that fails, not on its neighbours.
    if slug == "archive-org-search-query-university-library":
        pytest.xfail(
            "OPEN BUG, found by this tier 2026-08-15: replay loses 44 of "
            "3,310 addresses a cold parse finds. Localised to incremental "
            "reuse — a single push of the final snapshot finds all 3,310 — "
            "but the mechanism is NOT established, and it has not yet been "
            "re-confirmed on the live engine path (this replays saved "
            "snapshots through StreamingScan, which is not how the scanner "
            "runs). See notes/benchmark-apparatus.md.")

    meta, htmls = load(slug)
    scan = StreamingScan(meta["url"], context_window=1200)
    for passno, html in enumerate(htmls):
        update = scan.push(html, passno=passno)

    assert scan.trie is not None
    streamed = {str(a) for a in scan.trie.addresses()}
    cold = {str(ln.address) for ln in _lines(htmls[-1], meta["url"])
            if ln.address is not None}

    missing = cold - streamed
    assert not missing, (
        f"{slug}: {len(missing)} addresses the cold parse found are absent "
        f"after replay, e.g. {sorted(missing)[:3]}")


@pytest.mark.skipif(not mutating(),
                    reason="no capture with more than one distinct DOM; "
                           "capture a page that mutates (infinite scroll, "
                           "lazy comments) to exercise the delta path")
@pytest.mark.parametrize("slug", mutating() or ["none"])
def test_a_later_pass_walks_far_less_than_the_whole_tree(slug):
    """The O(delta) claim, on a real mutation, without a browser.

    The claim is that *work* tracks change rather than page size, so the
    quantity to assert on is `visited` — how many nodes the diff walked —
    against `nodes`, how many the tree holds. Measured on the infinite-scroll
    capture, where the page roughly doubles between passes:

        pass  chars    changed  visited  nodes  pruned
        0     7,022         76        0    250    100%
        1    14,518         68      101    464     78%

    Note what the first draft of this test asserted instead: that a later
    pass's `changed` was no larger than the first's, i.e. 68 <= 76. That held,
    but barely, and for no principled reason — `changed` is the size of the
    delta, which has no reason to shrink when a page grows. It would have gone
    green while the diff walked every node of the tree, which is precisely the
    failure it was supposed to catch.
    """
    meta, htmls = load(slug)
    scan = StreamingScan(meta["url"], context_window=1200)
    updates = [scan.push(html, passno=n) for n, html in enumerate(htmls)]

    assert updates[0].changed > 0, "the first pass changed nothing?"
    for update in updates[1:]:
        assert update.visited < update.nodes, (
            f"{slug} pass {update.passno}: walked {update.visited} of "
            f"{update.nodes} nodes — the diff is touching the whole tree, "
            f"which is a full re-parse wearing an incremental costume")


# --- end-to-end latency -----------------------------------------------------


def _timed_passes(slugs):
    """Replay every capture, timing the whole loop including the re-render."""
    out = []
    for slug in slugs:
        meta, htmls = load(slug)
        scan = StreamingScan(meta["url"], context_window=1200)
        for passno, html in enumerate(htmls):
            update = scan.push(html, passno=passno)
            scan.dirty_chunks(update)
            if update.changed:
                out.append(update)
    return out


@pytestmark_snapshots
def test_the_diff_itself_is_a_small_share_of_latency():
    """The incremental core is doing its job, and cheaply.

    Measured 2026-08-15 over 12 passes: the diff is 0.7% of end-to-end
    latency. Pinned loosely at 10% because one machine's timings are not a
    distribution — the point is that the diff is not the cost, which is what
    makes the next test's failure a statement about everything around it.
    """
    passes = _timed_passes(SLUGS)
    assert passes, "no capture changed anything; nothing to time"

    total = sum(u.total_ms for u in passes)
    diff = sum(u.diff_ms for u in passes)
    assert diff / total < 0.10, (
        f"the diff is {diff/total:.1%} of end-to-end latency — it used to be "
        f"0.7%, so something has made the incremental core expensive")


# The end-to-end latency test that used to live here has been removed, not
# weakened. It asserted that latency tracks change rather than page size, and
# was marked xfail on the strength of a measurement taken through
# `StreamingScan` over saved snapshots — full `deep_serialize` output with no
# `known` hashes, which is the mode the serializer's own docstring calls the
# naive transport. That path is not how the scanner runs, so the number it
# produced (a scroll costing 0.99 of a full rebuild) described the harness,
# not the design.
#
# Driven properly the same page saves 85.7% of bytes on the wire and an
# unchanged pass visits one node. The stages that genuinely are O(page) —
# tagging, trie construction, commit, and the REPL's open — are measured by
# `scripts/sweep_live.py` against the live path, where the claim can be
# falsified honestly. A test asserting a retracted premise is worse than no
# test: it looks like coverage of a known gap while measuring something else.
