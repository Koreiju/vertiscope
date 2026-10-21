"""Incremental scanning, without a browser.

`scripts/probe_live_delta.py` exercises this against a real site, which is the
only way to know it works on real change. But a live probe cannot be run in a
suite, cannot construct the awkward cases, and cannot fail deterministically.
These drive :class:`StreamingScan` with hand-built snapshots so the awkward
cases — a page that shrinks, one that only reorders, a first pass with nothing
to compare against — are covered at all.
"""

import pytest

from vertiscope.capture import Snapshot
from vertiscope.stream import ScanUpdate, StreamingScan

URL = "https://x.test/p"


def page(items, extra=""):
    """A minimal document whose item list is easy to grow and shrink."""
    lis = "".join(f"<li><a href='/i/{i}'>item {i}</a></li>" for i in items)
    return (f"<html><head><title>t</title></head><body><main>"
            f"<ul>{lis}</ul>{extra}</main></body></html>")


# --- the first pass ---------------------------------------------------------


def test_the_first_pass_is_all_addition():
    scan = StreamingScan(URL)
    update = scan.push(page([1, 2, 3]))
    assert update.changed == len(update.delta.added) > 0
    assert update.delta.removed == [] and update.delta.changed == []


def test_the_first_pass_claims_no_pruning():
    """A 100% prune ratio on the first pass would be flattering nonsense.

    There is nothing to prune against, so the honest number of comparisons
    avoided is zero — and reporting otherwise would make every summary that
    averages prune ratios overstate the saving.
    """
    scan = StreamingScan(URL)
    update = scan.push(page([1, 2]))
    assert update.visited == 0
    assert scan.summary()["passes"] == 1


# --- growth, the case that matters ------------------------------------------


def test_growth_is_reported_as_additions():
    scan = StreamingScan(URL)
    scan.push(page([1, 2]))
    update = scan.push(page([1, 2, 3, 4]))
    assert len(update.delta.added) > 0
    assert update.delta.removed == []


def test_an_unchanged_pass_costs_one_comparison():
    scan = StreamingScan(URL)
    scan.push(page(range(50)))
    update = scan.push(page(range(50)))
    assert update.changed == 0
    assert update.visited == 1, "an unchanged page should prune at the root"


def test_the_cost_of_an_unchanged_pass_is_flat_in_page_size():
    """The O(delta) claim in its sharpest form."""
    small = StreamingScan(URL)
    small.push(page(range(5)))
    small_cost = small.push(page(range(5))).visited

    large = StreamingScan(URL)
    large.push(page(range(500)))
    large_cost = large.push(page(range(500))).visited

    assert small_cost == large_cost == 1


def test_a_changed_pass_visits_far_less_than_the_trie():
    scan = StreamingScan(URL)
    scan.push(page(range(100)))
    update = scan.push(page(list(range(100)) + [100]))
    assert update.changed > 0
    assert update.visited < update.nodes // 2, (
        f"visited {update.visited} of {update.nodes} nodes for one new item"
    )


# --- shrinkage and reordering ------------------------------------------------


def test_removal_is_reported():
    scan = StreamingScan(URL)
    scan.push(page([1, 2, 3]))
    update = scan.push(page([1, 2]))
    assert len(update.delta.removed) > 0


def test_reordering_is_a_change_not_a_no_op():
    """Sibling order is part of the document, so it must move the hashes."""
    scan = StreamingScan(URL)
    scan.push(page([1, 2, 3]))
    update = scan.push(page([3, 2, 1]))
    assert update.changed > 0


def test_a_page_that_returns_to_a_previous_state_is_unchanged_again():
    scan = StreamingScan(URL)
    scan.push(page([1, 2]))
    scan.push(page([1, 2, 3]))
    update = scan.push(page([1, 2]))
    assert len(update.delta.removed) > 0
    again = scan.push(page([1, 2]))
    assert again.changed == 0


# --- dirty chunks ------------------------------------------------------------


def test_only_touched_chunks_are_dirty():
    scan = StreamingScan(URL, context_window=200)
    scan.push(page(range(40)))
    update = scan.push(page(list(range(40)) + [99]))
    dirty = scan.dirty_chunks(update)

    from vertiscope.markdown import render_trie
    total = len(render_trie(update.trie, context_window=200))
    assert 0 < len(dirty) < total, (
        f"{len(dirty)} dirty of {total} — re-rendering must follow the delta"
    )


def test_an_unchanged_pass_has_nothing_to_re_render():
    scan = StreamingScan(URL)
    scan.push(page(range(10)))
    update = scan.push(page(range(10)))
    assert scan.dirty_chunks(update) == []


# --- transport accounting ----------------------------------------------------


def test_a_snapshot_carries_its_wire_cost_through():
    scan = StreamingScan(URL)
    html = page(range(10))
    scan.push(Snapshot(html=html, stats={"bytes": len(html), "pruned": 0}))
    update = scan.push(Snapshot(html=html,
                                stats={"bytes": 40, "pruned": 7}))
    assert update.wire_bytes == 40
    assert update.pruned_subtrees == 7
    assert update.wire_ratio < 0.5


def test_a_bare_string_reports_a_full_transfer():
    """A caller that has no transport information must not report a saving."""
    scan = StreamingScan(URL)
    html = page(range(5))
    update = scan.push(html)
    assert update.wire_bytes == len(html)
    assert update.wire_ratio == 1.0


def test_the_summary_totals_the_stream():
    scan = StreamingScan(URL)
    scan.push(page(range(10)))
    scan.push(page(range(10)))
    scan.push(page(range(12)))
    summary = scan.summary()
    assert summary["passes"] == 3
    assert summary["total_visited"] < summary["total_nodes_if_rescanned"]
    assert 0.0 <= summary["mean_prune_ratio"] <= 1.0


def test_the_summary_of_an_empty_scan_is_empty():
    assert StreamingScan(URL).summary() == {}


# --- timings -----------------------------------------------------------------


def test_tagging_and_trie_costs_are_reported_separately():
    """Tagging is the one stage that is still proportional to page size.

    Keeping its time separate is what stops that term hiding inside a total
    and making the whole pass look incremental.
    """
    scan = StreamingScan(URL)
    update = scan.push(page(range(20)))
    assert update.tag_ms > 0
    assert update.trie_ms > 0
    assert "tag" in ScanUpdate.header()
