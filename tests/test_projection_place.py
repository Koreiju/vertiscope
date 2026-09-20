"""A newcomer must land where it belongs, not on the frame.

Reported by the user: "opening a few pages re-sets all the UMAP embeddings
for the main page chunks... they all seem jumbled in the center."

Two defects underneath it, and the first is the reason nothing caught it.

`_spread` kept the fit's empirical distribution so a later point could be
ranked against it. `column = out[:, axis]` is a numpy VIEW, and the next line
overwrote that view with the ranked values -- so what got stored was the
POST-spread column, 0..1, instead of the raw coordinates. `_spread_apply`
then compared a raw UMAP coordinate (measured: -3.42 .. 5.39) against a
distribution spanning 0 .. 1. Every placed point fell entirely below or
entirely above, ranked to 0 or 1, and framed to exactly -300 or +300. Every
unfold, every live capture and every hit list put its nodes on a corner:
measured on RFC 9110, 26 chunks at one point, 762 units from their own page.

Then `np.interp`/`searchsorted` clamp outside the support, so points past the
fit's range still collapsed onto the boundary -- 101 of 200 chunks on one
axis of one page. The fit is over 96 page-means and the points it places are
individual chunks, so falling outside is the ORDINARY case here.
"""

import numpy as np
import pytest

from domvec.obsidian.layout import _frame_apply, _framed, _spread, _spread_apply


def _fit(n=200, seed=0):
    rng = np.random.default_rng(seed)
    coords = rng.normal(0.0, 2.0, (n, 3)).astype(np.float32)
    spread, cdf = _spread(coords.copy(), 3), None
    # `_spread` returns the spread coords and leaves the cdf on _LAST_FIT.
    from domvec.obsidian import layout as L
    cdf = L._LAST_FIT.get("spread_cdf")
    return coords, spread, cdf


def test_the_kept_distribution_is_the_raw_one_not_the_ranked_one():
    """The aliasing. Everything else follows from this."""
    coords, spread, cdf = _fit()
    assert cdf, "_spread kept no distribution"
    for axis in range(3):
        kept = np.asarray(cdf[axis], dtype=np.float32)
        raw = coords[:, axis]
        assert abs(float(kept.min()) - float(raw.min())) < 1e-4, (
            "axis %d kept a distribution starting at %.3f, raw starts at %.3f"
            % (axis, kept.min(), raw.min()))
        assert abs(float(kept.max()) - float(raw.max())) < 1e-4, (
            "axis %d kept a distribution ending at %.3f, raw ends at %.3f"
            % (axis, kept.max(), raw.max()))
        # The tell: a ranked column spans exactly 0..1.
        assert not (abs(float(kept.min())) < 1e-6
                    and abs(float(kept.max()) - 1.0) < 1e-6), \
            "axis %d kept the RANKED column, which is the defect" % axis


def test_a_point_from_the_same_cloud_lands_inside_the_frame():
    """The symptom a reader sees.

    Held out of the fit rather than taken from it, so this is a placement and
    not a lookup of something already there.
    """
    from domvec.obsidian import layout as L

    rng = np.random.default_rng(7)
    coords = rng.normal(0.0, 2.0, (200, 3)).astype(np.float32)
    _spread(coords.copy(), 3)
    cdf = L._LAST_FIT["spread_cdf"]

    newcomers = rng.normal(0.0, 2.0, (50, 3)).astype(np.float32)
    placed = _spread_apply(newcomers, 3, cdf)
    framed = _frame_apply(placed, 3, 0.5, 600.0)

    # EXACTLY on the frame, not merely near it.
    #
    # A point genuinely at the top of the distribution ranks to ~0.9999
    # and frames to ~299.9, which is correct and must not fail here. The
    # clamp produced exactly 1.0 and therefore exactly 300.000, so
    # EXACTNESS is what separates the defect from the ordinary case -- a
    # tolerance of 0.5 failed on two points that were doing the right
    # thing.
    on_the_edge = int(np.sum(np.abs(np.abs(framed[:, :3]) - 300.0) < 1e-3))
    assert on_the_edge == 0, \
        "%d of %d coordinates landed exactly on the frame" % (
            on_the_edge, framed[:, :3].size)

    # And they are not all in ONE place, which is what the reader saw.
    for axis in range(3):
        assert float(np.std(framed[:, axis])) > 1.0, \
            "axis %d placed 50 points with a spread of %.4f" % (
                axis, float(np.std(framed[:, axis])))


def test_order_survives_past_the_ends_of_the_fit():
    """Outside the support, ORDER still has to hold.

    `_spread`'s whole contract is that the order along an axis is preserved
    and only the gaps change. Clamping breaks it for exactly the points that
    most need placing: three chunks well beyond the fit's range all came back
    at the same coordinate, so the picture said they were identical.
    """
    from domvec.obsidian import layout as L

    rng = np.random.default_rng(3)
    coords = rng.normal(0.0, 1.0, (120, 3)).astype(np.float32)
    _spread(coords.copy(), 3)
    cdf = L._LAST_FIT["spread_cdf"]

    top = float(np.asarray(cdf[0]).max())
    far = np.zeros((4, 3), dtype=np.float32)
    far[:, 0] = [top + 0.5, top + 1.5, top + 3.0, top + 6.0]
    placed = _spread_apply(far, 3, cdf)[:, 0]
    assert np.all(np.diff(placed) > 0), \
        "four points in increasing order came back as %r" % (placed,)


def test_the_fit_itself_is_unchanged():
    """The non-vacuity arm for the copy.

    `_spread` still has to SPREAD -- the fix must not have turned the
    transform into a no-op by copying the wrong thing.
    """
    rng = np.random.default_rng(11)
    coords = rng.normal(0.0, 2.0, (300, 3)).astype(np.float32)
    out = _spread(coords.copy(), 3)
    for axis in range(3):
        col = out[:, axis]
        assert abs(float(col.min())) < 1e-6 and abs(float(col.max()) - 1.0) < 1e-6, \
            "axis %d was not spread onto 0..1: %.3f..%.3f" % (
                axis, col.min(), col.max())
        # Order preserved exactly, which is the other half of the contract.
        assert np.array_equal(np.argsort(col), np.argsort(coords[:, axis])), \
            "axis %d changed the order of the points" % axis
