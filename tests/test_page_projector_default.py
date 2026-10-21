"""The page-centroid UMAP places pages AND every chunk (2026-09-27 default).

"make the page-centroid UMAP the default projector" -- with Addendum IX's
requirement kept: every chunk has UMAP coordinates through the current fit.

Measured on the real corpus the same day (14,382 chunks, 126 pages): a
chunk's own transform through the page fit lands nearest its OWN page only
19-23% of the time -- a nav block or a reference list means something nearer
other pages than its page's mean -- so drawn raw, every page scatters across
the map. Chunks are therefore DRAWN at their page plus their UMAP offset
scaled into the page's neighbourhood, and their true coordinates are kept in
`raw_pos`.

Planted arm: no neighbourhood scaling (raw offsets) -- the measured scatter --
must fail the own-page test.
"""

from types import SimpleNamespace

import numpy as np

from vertiscope.obsidian.projector import PageProjector

PAGES, PER, DIM = 14, 9, 32


def _rows(seed=0, spread=0.4):
    rng = np.random.default_rng(seed)
    centres = rng.normal(size=(PAGES, DIM)) * 3.0
    rows = []
    for p in range(PAGES):
        for k in range(PER):
            v = centres[p] + rng.normal(size=DIM) * spread
            rows.append(("c%d_%d" % (p, k), "https://p%d.test/" % p, v.astype(np.float32).tolist()))
    return rows


class _Store:
    def __init__(self, rows):
        self.rows = rows

    def lead_vectors(self):
        return self.rows

    def chunk_count(self):
        return len(self.rows)


def _fit(rows, centroid="semantic"):
    ws = SimpleNamespace(store=_Store(rows), path=None)
    proj = PageProjector(dims=3, centroid=centroid, seed=0)
    got = proj.fit(ws)
    assert "error" not in got and "skipped" not in got, got
    return proj


def _own_page_share(proj, rows):
    """Share of chunks whose nearest PAGE (as drawn) is their own page."""
    urls = sorted(proj.page_pos)
    P = np.asarray([proj.page_pos[u] for u in urls])
    hit = 0
    for cid, url, _v in rows:
        d = np.linalg.norm(P - np.asarray(proj.pos[cid]), axis=1)
        hit += urls[int(np.argmin(d))] == url
    return hit / len(rows)


def test_pages_and_every_chunk_are_placed():
    rows = _rows()
    proj = _fit(rows)
    assert len(proj.page_pos) == PAGES
    assert len(proj.pos) == len(rows)
    assert proj.status()["projected"] == len(rows)


def test_a_drawn_chunk_sits_in_its_own_pages_neighbourhood():
    # Noisy chunks (spread 2.0: individually closer to other pages, as the
    # corpus measured) still draw beside their own page.
    rows = _rows(spread=2.0)
    proj = _fit(rows)
    assert _own_page_share(proj, rows) >= 0.95
    # ...and their true UMAP coordinates are kept (Addendum IX).
    assert len(proj.raw_pos) == len(rows)


def test_planted_raw_placement_scatters_pages(monkeypatch):
    monkeypatch.setattr(PageProjector, "NEIGHBOURHOOD", 1e6)
    rows = _rows(spread=2.0)
    proj = _fit(rows)
    assert _own_page_share(proj, rows) < 0.95


def test_the_triple_centroid_leaves_chunks_to_the_tree():
    rows = _rows()
    proj = _fit(rows, centroid="triple")
    assert proj.pos == {}


def _online_refit(landmark_weight):
    import pytest
    torch = pytest.importorskip("torch")
    rows = _rows(spread=0.6)
    first = [r for r in rows if not r[1].startswith(("https://p12.", "https://p13."))]
    ws = SimpleNamespace(store=_Store(first), path=None)
    proj = PageProjector(dims=3, centroid="semantic", seed=0, engine="parametric")
    proj.fit(ws)
    proj.pumap.landmark_weight = landmark_weight
    before = dict(proj.page_pos)
    ws.store = _Store(rows)               # two new pages arrive
    got = proj.fit(ws)
    assert got.get("online") is True, got
    P = np.asarray(list(before.values()))
    spacing = float(np.median(np.linalg.norm(P[:, None] - P[None], axis=2)))
    moved = [np.linalg.norm(np.asarray(proj.page_pos[u]) - np.asarray(before[u])) for u in before]
    return float(np.median(moved)) / spacing, proj


def test_an_online_refit_trains_the_diff_and_holds_the_old_pages():
    share, proj = _online_refit(10.0)
    # Measured 4.3-8.5% here across runs (GPU training is not bit-reproducible;
    # 12 -> 14 pages), 0.7% on the real corpus (100 -> 126); planted: 22%+.
    assert share < 0.10, share                      # old pages stay put
    assert len(proj.page_pos) == PAGES               # the new ones are placed


def test_planted_no_landmark_moves_the_old_pages():
    share, _proj = _online_refit(0.0)
    assert share > 0.12, share                      # measured 22%


def test_the_stream_trains_online_on_pages_the_model_has_not_learned(monkeypatch):
    """Continuous: pages the stream placed but the model never trained on are
    trained in the background, earlier pages held (2026-09-27)."""
    import time
    import pytest
    pytest.importorskip("torch")
    monkeypatch.setattr(PageProjector, "ONLINE_DEBOUNCE_S", 0.05)
    rows = _rows(spread=0.6)
    first = [r for r in rows if not r[1].startswith(("https://p12.", "https://p13."))]
    ws = SimpleNamespace(store=_Store(first), path=None)
    proj = PageProjector(dims=3, centroid="semantic", seed=0, engine="parametric")
    proj.fit(ws)
    before = dict(proj.page_pos)
    # The stream: two new pages arrive, are placed through transform, and
    # are handed to the online worker.
    for u in ("https://p12.test/", "https://p13.test/"):
        mine = [r for r in rows if r[1] == u]
        for c, _u, v in mine:
            proj.vec[c] = np.asarray(v, dtype=np.float32)
            proj.url_of[c] = u
            proj.by_url.setdefault(u, set()).add(c)
        proj.page_vec[u] = proj._semantic_centroid([c for c, _u, _v in mine], proj.vec)
        where, _col = proj.projection.place(np.asarray([proj.page_vec[u]]))
        proj.page_pos[u] = [float(x) for x in where[0][:3]]
    proj._schedule_online(["https://p12.test/", "https://p13.test/"])
    for _ in range(600):
        if proj.online_updates:
            break
        time.sleep(0.1)
    assert proj.online_updates, "no online update ran"
    rec = proj.online_updates[-1]
    assert rec["pages_trained"] == 2
    assert {"https://p12.test/", "https://p13.test/"} <= proj.trained
    P = np.asarray(list(before.values()))
    spacing = float(np.median(np.linalg.norm(P[:, None] - P[None], axis=2)))
    moved = np.median([np.linalg.norm(np.asarray(proj.page_pos[u]) - np.asarray(before[u])) for u in before])
    assert moved / spacing < 0.08


def test_an_online_update_leaves_every_other_page_exactly_where_it_was(monkeypatch):
    """'assume previous fits are fixed': only the pages trained on move."""
    import time
    import pytest
    pytest.importorskip("torch")
    monkeypatch.setattr(PageProjector, "ONLINE_DEBOUNCE_S", 0.05)
    rows = _rows(spread=0.6)
    first = [r for r in rows if r[1] != "https://p13.test/"]
    ws = SimpleNamespace(store=_Store(first), path=None)
    proj = PageProjector(dims=3, centroid="semantic", seed=0, engine="parametric")
    proj.fit(ws)
    before = {u: list(v) for u, v in proj.page_pos.items()}
    u = "https://p13.test/"
    mine = [r for r in rows if r[1] == u]
    for c, _u, v in mine:
        proj.vec[c] = np.asarray(v, dtype=np.float32)
        proj.url_of[c] = u
        proj.by_url.setdefault(u, set()).add(c)
    proj.page_vec[u] = proj._semantic_centroid([c for c, _u, _v in mine], proj.vec)
    proj._schedule_online([u])
    for _ in range(600):
        if proj.online_updates:
            break
        time.sleep(0.1)
    rec = proj.online_updates[-1]
    assert rec["pages_moved"] <= 1, rec
    assert all(proj.page_pos[k] == v for k, v in before.items())
    assert u in proj.page_pos
