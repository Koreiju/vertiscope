"""The page layout is fitted at 2x growth, and placed into in between.

Two defects this pins down.

**`stale` was judged in the wrong unit.** The page-level fit recorded
`fitted_n = len(urls)` -- pages -- and `stale()` was handed the corpus CHUNK
count. 112 pages against 14,787 chunks is a ratio of 132 on a threshold of 2,
so the fit read stale permanently and "fit is stale, refit" was lit the whole
time and meant nothing. Any refit wired to it would have fired on every
capture.

**Every new page refit the corpus and moved the whole map.** The layout was
keyed on a hash of the Page table, so capturing one page made the next
request refit: 14 -> 1,189 ms, and all 113 existing pages moved, the median
by 348 units -- 54% of the cloud. The fit is now kept and new pages are
placed into it; a refit happens only once the chunk corpus has doubled.
"""

import os
import time

import pytest

from vertiscope.obsidian.layout import Projection

LIVE = os.environ.get("VERTISCOPE_LIVE") == "1"


def _projection(fitted_n, fitted_chunks=None):
    # `stale()` reads only the counts; the reducer and svd are not touched.
    return Projection(svd=None, reducer=object(), dims=3, hsv=False,
                      hsv_bands=None, spread_cdf=None, frame=None,
                      fitted_n=fitted_n, fitted_chunks=fitted_chunks)


def test_stale_is_judged_in_chunks_not_in_fitted_points():
    """112 pages fitted over a corpus of 14,787 chunks is NOT stale."""
    p = _projection(fitted_n=112, fitted_chunks=14787)
    assert not p.stale(14787)
    assert not p.stale(20000)
    assert p.stale(2 * 14787), "the corpus doubled and it did not say so"


def test_the_old_unit_would_have_been_stale_forever():
    """The planted arm: judged in pages, the same corpus reads stale at once.

    If this ever stops being true, the test above is not distinguishing the
    two units and has stopped measuring anything.
    """
    judged_in_pages = _projection(fitted_n=112)      # no chunk count given
    assert judged_in_pages.stale(14787), (
        "with fitted_chunks defaulting to fitted_n, 14,787 >= 2 x 112 must "
        "read stale -- that was the defect")


def test_a_chunk_level_fit_is_unchanged():
    """The chunk-level fit always recorded chunks, and still does."""
    p = _projection(fitted_n=5000)
    assert not p.stale(9999) and p.stale(10000)


# --- live: the map does not move when a page is added -----------------------


@pytest.mark.skipif(not LIVE, reason="needs VERTISCOPE_LIVE=1, the sidecar and Obsidian")
def test_a_new_page_is_placed_into_the_fit_and_nothing_else_moves():
    import math

    from vertiscope.obsidian.live import Live

    live = Live()

    def layout(q=""):
        got = live.get("/layout?space=semantic" + q)
        return got, {n["url"]: n["pos"][:3] for n in got["nodes"]
                     if n.get("level") == "page"}

    layout("&refit=1")                       # one fit, made in this process
    first, before = layout()
    assert first.get("incremental"), "the kept fit was not used"

    have = set(live.get("/pages").get("urls") or [])
    fresh = next((u for u in (
        "https://books.toscrape.com/catalogue/page-%d.html" % i
        for i in range(12, 50)) if u not in have), None)
    if fresh is None:
        pytest.skip("no fresh page left to capture")
    live.act("navigate", fresh)
    time.sleep(3)
    live.act("scan")
    time.sleep(4)

    after_layout, after = layout()
    assert after_layout.get("incremental"), (
        "a new page triggered a refit instead of a placement")
    assert not after_layout.get("stale")
    assert fresh in after, "the new page is not in the layout"
    moved = max(math.dist(before[u], after[u]) for u in before if u in after)
    assert moved < 1e-3, (
        "adding one page moved an existing page %.1f units -- the map is "
        "being refit, not placed into" % moved)
