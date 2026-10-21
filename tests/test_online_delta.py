"""Do the online UMAP update's position changes reach `delta()`? (2026-10-04)

The user's suspicion: "UMAP fit updates I don't know/think are persisting to
the UI." The UI polls `/projector/delta?since=&epoch=` once a second
(`graph.ts` `pullDelta`) and applies what `PageProjector.delta` returns; that
is built from `self.log`. So the question this file answers is exactly: after
a fit and an online update, does the log -- and therefore the delta -- name
every chunk and page whose drawn position changed?

What is proved here is the SERVER half: replaying the delta onto a client that
held the post-fit picture reproduces the server's positions to within the
log's own threshold (`_online_worker` logs a move only above 0.25 -- about
0.05% of the median page spacing on this fixture, 455). The plugin half
(`pullDelta` -> `glide`) is read, not run: Obsidian must not be started from
this worktree.

Planted arm: the same flow with the log swapped for one that drops appends
must FAIL the replay check by two orders of magnitude -- and the new page must
really have moved, or the arm could not tell a missing log from nothing to
log.
"""

from collections import deque

import numpy as np
import pytest

from vertiscope.obsidian.projector import PageProjector
from umap_fakes import Store, make_rows, wait_for, workspace

NEW = "https://p13.test/"
THRESHOLD = 0.25            # `_online_worker`'s logging threshold


def _setup(monkeypatch, scope, debounce=0.05):
    pytest.importorskip("torch")
    monkeypatch.setattr(PageProjector, "ONLINE_DEBOUNCE_S", debounce)
    rows = make_rows()
    first = [r for r in rows if r[1] != NEW]
    ws = workspace(first)
    proj = PageProjector(dims=3, centroid="semantic", seed=0, engine="parametric")
    if proj.engine != "parametric":
        pytest.skip("no CUDA/torch: the parametric engine is what has an online update")
    if scope == "pages":
        proj.SCOPE_BUDGET_MS = 1.0
    got = proj.fit(ws)
    assert "error" not in got and "skipped" not in got, got
    assert proj.scope == scope, proj.scope_record
    return proj, ws, rows


def _arrive(proj, ws, rows):
    """The new page's chunks are stored, queued and drained (placed by transform)."""
    ws.store = Store(rows)
    new = [r[0] for r in rows if r[1] == NEW]
    proj.enqueue(new)
    assert proj.drain(ws) is not None
    return new


def _replay(proj, since, snap_pos, snap_page):
    """What a client holding the picture at `since` has after applying the delta."""
    d = proj.delta(since, proj.epoch)
    assert d["reload"] is False
    cp, pp = dict(snap_pos), dict(snap_page)
    for c, got in d["chunks"].items():
        cp[c] = got["pos"]
    for u, got in d["pages"].items():
        pp[u] = got["pos"]
    for c in d["gone"]:
        cp.pop(c, None)
    return d, cp, pp


def _worst_error(proj, cp, pp):
    errs = [np.linalg.norm(np.asarray(cp[c]) - np.asarray(v)) for c, v in proj.pos.items()]
    errs += [np.linalg.norm(np.asarray(pp[u]) - np.asarray(v)) for u, v in proj.page_pos.items()]
    return float(max(errs))


def _poll(proj, since, cp, pp):
    """One pane poll: apply `delta(since)` to the client's view; return the new view and seq."""
    d = proj.delta(since, proj.epoch)
    assert d["reload"] is False
    cp, pp = dict(cp), dict(pp)
    for c, got in d["chunks"].items():
        cp[c] = got["pos"]
    for u, got in d["pages"].items():
        pp[u] = got["pos"]
    for c in d["gone"]:
        cp.pop(c, None)
    return d, cp, pp


def _worst_error(proj, cp, pp):
    errs = [np.linalg.norm(np.asarray(cp[c]) - np.asarray(v)) for c, v in proj.pos.items()]
    errs += [np.linalg.norm(np.asarray(pp[u]) - np.asarray(v)) for u, v in proj.page_pos.items()]
    return float(max(errs))


def _two_polls(proj, ws, rows, between=None, debounce_hook=None):
    """The production order: the pane polls after the DRAIN (the page is drawn
    at its transform position), then again after the online update (2 s of
    debounce later in production, one poll a second)."""
    seq0 = proj.seq
    cp = {c: list(v) for c, v in proj.pos.items()}
    pp = {u: list(v) for u, v in proj.page_pos.items()}
    new = _arrive(proj, ws, rows)
    d1, cp, pp = _poll(proj, seq0, cp, pp)
    assert NEW in d1["pages"] and set(new) <= set(d1["chunks"])      # drain logged them
    drained_page = list(proj.page_pos[NEW])
    if between:
        between()
    assert wait_for(lambda: proj.online_updates), "no online update ran"
    moved = float(np.linalg.norm(np.asarray(proj.page_pos[NEW]) - np.asarray(drained_page)))
    d2, cp, pp = _poll(proj, d1["seq"], cp, pp)
    return new, moved, d2, cp, pp


@pytest.mark.parametrize("scope", ["chunks", "pages"])
def test_an_online_update_reaches_the_delta(monkeypatch, scope):
    proj, ws, rows = _setup(monkeypatch, scope)
    new, moved, d2, cp, pp = _two_polls(proj, ws, rows)
    rec = proj.online_updates[-1]
    # Non-vacuity: training really relocated the new page (measured ~90 of a
    # 455 spacing), so there IS something for the log to carry.
    assert moved > 1.0, (moved, rec)
    assert NEW in d2["pages"], "the moved page is not in the second delta"
    assert set(new) <= set(d2["chunks"]), "the trained page's chunks are not in the second delta"
    assert rec["pages_moved"] >= 1 and rec["chunks_moved"] >= 1
    assert _worst_error(proj, cp, pp) <= THRESHOLD + 1e-6
    # ...and the epoch did not change: the pane keeps applying deltas.
    assert d2["epoch"] == proj.epoch and not d2["reload"]


def test_planted_a_log_that_drops_online_moves_fails_the_replay(monkeypatch):
    class NullLog(deque):
        def append(self, item):         # the variant that "skips logging"
            pass

    proj, ws, rows = _setup(monkeypatch, "chunks", debounce=0.6)
    _new, moved, d2, cp, pp = _two_polls(
        proj, ws, rows,
        between=lambda: setattr(proj, "log", NullLog(proj.log, maxlen=proj.log.maxlen)))
    assert moved > 1.0
    assert d2["chunks"] == {} and d2["pages"] == {}
    # The client holds the transform position, the server the trained one.
    assert _worst_error(proj, cp, pp) > 10 * THRESHOLD


# -- what a page IS in the map ---------------------------------------------------

def _unit(v):
    return v / np.linalg.norm(v)


def test_a_page_is_the_unweighted_unit_mean_of_its_chunk_vectors(monkeypatch):
    """`_semantic_centroid` (projector.py): `block.mean(axis=0)`, normalised."""
    proj, _ws, rows = _setup(monkeypatch, "chunks")
    mine = [r for r in rows if r[1] == "https://p3.test/"]
    vecs = np.asarray([r[2] for r in mine], dtype=np.float32)
    want = _unit(vecs.mean(axis=0))
    got = proj._semantic_centroid([r[0] for r in mine], proj.vec)
    np.testing.assert_allclose(got, want, atol=1e-6)
    # What the fit was made of is that same vector...
    np.testing.assert_allclose(proj.page_vec["https://p3.test/"], want, atol=1e-5)
    # ...and a weighted mean (what the triple centroid's PageRank weights
    # give) is a DIFFERENT point, so the equality above could have failed.
    w = np.linspace(1, 9, len(mine))
    w = w / w.sum()
    weighted = proj._semantic_centroid([r[0] for r in mine], proj.vec, w)
    assert float(np.linalg.norm(weighted - want)) > 1e-3
