"""A restart restores the map that was drawn, not the last FULL fit (2026-11-15).

The reader: "the 3D map keeps changing its layout frequently, seems like a
degradation of some kind". Measured live through the MCP harness: two idle
minutes moved 0 of 1,039 pages (the null arm); one sidecar restart moved
1,012 of them, median 38 units, p90 83, max 333 (a link is ~62). The
projector saved `projector.pkl` after full fits only, so a restart reloaded
an old fit and re-trained every page changed since, in a new order.

Here: fit, one page arrives and is trained online, the idle loop's save runs,
and a NEW projector loaded from the same directory holds every page where
the old one had it. Planted `PLANT_NO_ONLINE_SAVE`: the reload holds the
post-fit state, and the trained page is not where it was drawn.

Trie framing: geometry is a peripheral keyed by address (CLAUDE.md 5); this
keeps that peripheral a stable function of the addresses across a restart.
"""
import numpy as np
import pytest

import domvec.obsidian.projector as P
from domvec.obsidian.projector import PageProjector
from umap_fakes import Store, make_rows, wait_for, workspace

NEW = "https://p13.test/"


@pytest.mark.parametrize("planted", [False, True])
def test_a_reload_holds_every_page_where_the_online_update_put_it(monkeypatch, tmp_path, planted):
    pytest.importorskip("torch")
    monkeypatch.setattr(PageProjector, "ONLINE_DEBOUNCE_S", 0.05)
    monkeypatch.setattr(P, "PLANT_NO_ONLINE_SAVE", [planted])
    rows = make_rows()
    ws = workspace([r for r in rows if r[1] != NEW])
    ws.path = str(tmp_path)
    proj = PageProjector(dims=3, centroid="semantic", seed=0, engine="parametric", umap_scope="auto")
    if proj.engine != "parametric":
        pytest.skip("no CUDA/torch: the parametric engine is what has an online update")
    got = proj.fit(ws)
    assert "error" not in got and "skipped" not in got, got
    assert (tmp_path / PageProjector.FILE).exists(), "a full fit saves, as before"
    fitted = {u: list(v) for u, v in proj.page_pos.items()}

    ws.store = Store(rows)
    proj.enqueue([r[0] for r in rows if r[1] == NEW])
    assert proj.drain(ws) is not None
    assert wait_for(lambda: proj.online_updates), "no online update ran"
    assert wait_for(lambda: not proj._pending_online)
    live = {u: list(v) for u, v in proj.page_pos.items()}
    assert NEW in live and NEW not in fitted
    # The idle loop's save, its quiet period elapsed.
    saved = proj.save_if_dirty(ws, force=True)
    assert saved is (not planted)

    again = PageProjector(dims=3, centroid="semantic", seed=0, engine="parametric", umap_scope="auto")
    assert again.load(ws)
    if planted:
        assert NEW not in again.page_pos, "planted: the reload is the post-fit state"
        return
    worst = max(float(np.linalg.norm(np.asarray(again.page_pos[u]) - np.asarray(v))) for u, v in live.items())
    assert worst < 1e-6, worst
    assert set(again.page_pos) == set(live)
    assert again.save_stats == {} and proj.save_stats["ok"] and proj._dirty_at == 0.0


def test_the_save_waits_for_the_online_work_to_go_quiet(tmp_path):
    proj = PageProjector(dims=3, centroid="semantic", seed=0)
    ws = workspace([])
    ws.path = str(tmp_path)
    assert not proj.save_if_dirty(ws), "nothing changed: no save"
    proj.mark_dirty()
    assert not proj.save_if_dirty(ws), "dirty a moment ago: still settling"
    proj._dirty_at -= proj.SAVE_QUIET_S + 1
    proj._pending_online.add("https://x.test/")
    assert not proj.save_if_dirty(ws), "an online update is pending"
