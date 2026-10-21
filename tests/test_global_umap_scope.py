"""VERTISCOPE_UMAP_SCOPE=global: ONE model over every chunk; a page's diff retrains
only that page's rows (2026-10-04).

The user: "a UMAP model applied to *all* scanned chunks from all URLs
(noting diff updates on chunk mutations; revectorization; and re-mapping), but
the re-fit update is only on the set of URL chunks."

In the trie's terms: the model's rows are the leaves of `url : xpath` (a chunk
id is the hash of that span) and one centroid per url; a page's diff is the
set of leaves under one url prefix whose content_hash changed; the update
reads exactly those rows from the trie's projection and writes their
positions back, holding every other leaf where it was.

Planted arms: landmarks off must DRIFT the held rows; the chunk scope must NOT
retrain a mutated chunk (the contrast the global scope exists to remove); the
existing `update()` must train on every row (the cost the subset removes).
All need a CUDA device for the model (CPU torch would pass but take minutes).
"""

import time

import numpy as np
import pytest

from vertiscope.obsidian.projector import PageProjector, _RowMap
from vertiscope.obsidian.refitscope import RefitCost, choose_scope
from umap_fakes import DIM, PAGES, PER, Store, make_rows, wait_for, workspace

torch = pytest.importorskip("torch")
needs_cuda = pytest.mark.skipif(not torch.cuda.is_available(),
                                reason="the global model's update is measured on CUDA")


# -- the decision (pure) ---------------------------------------------------------

def test_global_is_chosen_only_when_asked_and_only_for_parametric_semantic():
    cost = RefitCost()
    assert choose_scope(159, 16189, cost, 5000.0)["scope"] == "pages"          # today's default
    got = choose_scope(159, 16189, cost, 5000.0, want_global=True)
    assert got["scope"] == "global" and "bounded" in got["why"]
    assert choose_scope(159, 16189, cost, 5000.0, engine="umap", want_global=True)["scope"] == "pages"
    assert choose_scope(159, 16189, cost, 5000.0, centroid="triple", want_global=True)["scope"] == "pages"


# -- the row map (pure) ----------------------------------------------------------

def _page(n, v=1.0):
    return np.full(4, v, np.float32), {"%s%d" % ("c", i): np.full(4, v, np.float32) for i in range(n)}


def test_row_map_gives_a_page_its_rows_and_reuses_retired_ones():
    m = _RowMap()
    cent, chunks = _page(3)
    plan = m.plan(0, {"u": (cent, chunks)})
    assert sorted(plan["idx"]) == [0, 1, 2, 3] and plan["appended"] == 4 and not len(plan["remove"])
    m.commit(plan)
    assert m.of_url["u"] == {"page:u", "c0", "c1", "c2"}
    # The page loses a chunk: its row is retired, then reused by a newcomer.
    plan = m.plan(4, {"u": (cent, {k: v for k, v in chunks.items() if k != "c1"})})
    assert len(plan["remove"]) == 1 and plan["drop"] == ["c1"]
    m.commit(plan)
    assert len(m.free) == 1 and "c1" not in m.row_of
    plan = m.plan(4, {"u": (cent, {"c0": chunks["c0"], "c2": chunks["c2"], "new": chunks["c0"]})})
    assert plan["appended"] == 0 and len(m.free) == 1 and plan["free"] == []
    m.commit(plan)
    assert m.free == [] and set(m.row_of.values()) == {0, 1, 2, 3}      # no growth


def test_row_map_planted_a_page_with_no_chunks_retires_every_row():
    m = _RowMap()
    cent, chunks = _page(2)
    m.commit(m.plan(0, {"u": (cent, chunks)}))
    plan = m.plan(3, {"u": (None, {})})
    assert len(plan["idx"]) == 0 and len(plan["remove"]) == 3
    m.commit(plan)
    assert m.of_url["u"] == set() and sorted(m.free) == [0, 1, 2]


def test_row_map_a_chunk_moved_between_pages_keeps_its_row():
    m = _RowMap()
    ca, a = _page(2)
    cb, b = _page(1)
    m.commit(m.plan(0, {"A": (ca, a), "B": (cb, b)}))
    row = m.row_of["c1"]
    plan = m.plan(5, {"A": (ca, {"c0": a["c0"]}), "B": (cb, {"c0": b["c0"], "c1": a["c1"]})})
    m.commit(plan)
    assert m.row_of["c1"] == row and m.row_url["c1"] == "B" and "c1" not in m.of_url["A"]


# -- the model's subset update --------------------------------------------------

def _blobs(pages=8, per=60, dim=32, seed=0):
    rng = np.random.default_rng(seed)
    centres = rng.normal(size=(pages, dim)) * 3.0
    X = np.vstack([centres[p] + rng.normal(size=(per, dim)) * 0.5 for p in range(pages)])
    return X.astype(np.float32), np.repeat(np.arange(pages), per)


def _fitted(pages=8, per=60, **kw):
    from vertiscope.obsidian.pumap import ParametricUMAP
    X, page_of = _blobs(pages, per)
    m = ParametricUMAP(n_components=6, n_neighbors=10, seed=0, **kw)
    m.fit(X, max_steps=400)
    return m, X, page_of


@needs_cuda
def test_update_subset_replaces_rows_in_place_and_holds_the_rest():
    m, X, page_of = _fitted()
    before = m.embedding_.copy()
    rows = np.flatnonzero(page_of == 2)
    new = X[rows] * 0.4 + X[np.flatnonzero(page_of == 5)[:len(rows)]] * 0.6
    got = m.update_subset(new, rows, steps=120)
    assert len(m._raw) == len(X), "a mutated chunk must keep its row, not append a second one"
    np.testing.assert_allclose(m._raw[rows], new)
    assert got.shape == (len(rows), 6) and np.isfinite(got).all()
    others = np.setdiff1d(np.arange(len(X)), rows)
    assert np.array_equal(m.embedding_[others], before[others]), "held rows were rewritten"
    assert m.stats["trained_rows"] <= len(rows) + 1024


@needs_cuda
def test_update_subset_holds_the_net_planted_no_landmarks_drifts():
    def drift(landmark_weight, **kw):
        m, X, page_of = _fitted(landmark_weight=landmark_weight)
        rows = np.flatnonzero(page_of == 2)
        new = X[np.flatnonzero(page_of == 5)[:len(rows)]]
        before = m.embedding_.copy()
        m.update_subset(new, rows, steps=200, **kw)
        others = np.setdiff1d(np.arange(len(X)), rows)
        d = np.linalg.norm(m.transform(m._raw[others])[:, :3] - before[others][:, :3], axis=1)
        spread = float(np.median(np.linalg.norm(before[:200, None, :3] - before[None, :200, :3], axis=2)))
        return float(np.median(d)) / spread
    held = drift(10.0)
    planted = drift(0.0, knn=0, random_landmarks=0)
    assert held < 0.05, held
    assert planted > 3 * held and planted > 0.05, (held, planted)


@needs_cuda
def test_update_subset_appends_and_retires_and_rejects_a_gap():
    m, X, _ = _fitted()
    n = len(X)
    new = X[:5] + 0.01
    got = m.update_subset(new, np.arange(n, n + 5), steps=40)
    assert len(m._raw) == n + 5 and got.shape == (5, 6) and m._alive.all()
    m.update_subset(X[:1] + 0.02, np.array([3]), remove=np.array([10, 11]), steps=40)
    assert not m._alive[10] and not m._alive[11] and m._alive[3]
    with pytest.raises(ValueError):
        m.update_subset(new, np.arange(n + 9, n + 14))              # not contiguous


@needs_cuda
def test_the_subset_cost_is_bounded_by_the_page_the_old_update_by_the_corpus():
    small, Xs, ps = _fitted(pages=4, per=60)
    large, Xl, pl = _fitted(pages=20, per=60)
    for m, X, p in ((small, Xs, ps), (large, Xl, pl)):
        rows = np.flatnonzero(p == 1)
        m.update_subset(X[rows] + 0.05, rows, steps=30)
    # Rows trained: the page plus landmarks, however big the corpus.
    assert large.stats["trained_rows"] <= 60 + 1024
    assert large.stats["trained_rows"] < len(Xl)
    # The planted contrast: update() trains every row it has.
    large.update_epochs = 1
    large.update(Xl[:3] + 0.1)
    assert large.stats["rows"] == len(Xl) + 3 and large.stats["update_rows"] == 3


# -- the projector ----------------------------------------------------------------

def _global(monkeypatch, scope="global", debounce=0.05):
    monkeypatch.setattr(PageProjector, "ONLINE_DEBOUNCE_S", debounce)
    rows = make_rows()
    ws = workspace(rows)
    proj = PageProjector(dims=3, centroid="semantic", seed=0, engine="parametric", umap_scope=scope)
    if proj.engine != "parametric":
        pytest.skip("no CUDA/torch")
    got = proj.fit(ws)
    assert "error" not in got and "skipped" not in got, got
    return proj, ws, rows


@needs_cuda
def test_the_global_fit_trains_one_model_on_every_chunk_and_page(monkeypatch):
    proj, _ws, rows = _global(monkeypatch)
    assert proj.scope == "global", proj.scope_record
    assert proj.pumap._raw.shape[0] == PAGES + len(rows)
    assert len(proj.rows.row_of) == PAGES + len(rows) and len(proj.trained_chunks) == len(rows)
    assert len(proj.pos) == len(rows)                       # drawing unchanged: every chunk placed
    st = proj.status()
    assert st["scope"] == "global" and st["global_rows"] == PAGES + len(rows)


def _mutate(rows, ws, proj, url, toward):
    """Revectorise a page: its chunks now mean something nearer another page."""
    mine = {c: v for c, u, v in rows if u == url}
    target = np.mean([v for c, u, v in rows if u == toward], axis=0)
    rng = np.random.default_rng(1)
    new_rows = []
    for c, u, v in rows:
        if c in mine:
            v = (0.3 * np.asarray(v) + 0.7 * target + rng.normal(size=DIM) * 0.05).astype(np.float32).tolist()
        new_rows.append((c, u, v))
    ws.store = Store(new_rows)
    proj.enqueue(list(mine))
    return new_rows, list(mine)


@needs_cuda
def test_a_mutated_page_retrains_its_own_rows_and_nothing_else_moves(monkeypatch):
    proj, ws, rows = _global(monkeypatch)
    url = "https://p3.test/"
    raw_rows = proj.pumap._raw.shape[0]
    held_pos = {u: list(v) for u, v in proj.page_pos.items() if u != url}
    held_chunks = {c: list(v) for c, v in proj.pos.items() if proj.url_of[c] != url}
    seq0 = proj.seq
    old_page = list(proj.page_pos[url])
    _new_rows, mine = _mutate(rows, ws, proj, url, "https://p9.test/")
    assert proj.drain(ws) is not None
    assert wait_for(lambda: proj.online_updates), "a mutated page was not retrained"
    rec = proj.online_updates[-1]
    assert rec["scope"] == "global" and rec["pages_trained"] == 1
    assert rec["global"]["update_rows"] == PER + 1            # the page's chunks and its centroid
    assert rec["global"]["trained_rows"] < raw_rows + 1       # bounded by landmarks, here all there are
    assert proj.pumap._raw.shape[0] == raw_rows, "revectorising appended rows instead of replacing them"
    # Held: every other page and chunk is exactly where it was.
    assert all(proj.page_pos[u] == v for u, v in held_pos.items())
    assert all(proj.pos[c] == v for c, v in held_chunks.items())
    # The mutated page moved, and the delta says so.
    assert np.linalg.norm(np.asarray(proj.page_pos[url]) - np.asarray(old_page)) > 1.0
    d = proj.delta(seq0, proj.epoch)
    assert url in d["pages"] and set(mine) <= set(d["chunks"])
    assert set(d["chunks"]) <= set(mine) and set(d["pages"]) == {url}


@needs_cuda
def test_planted_the_chunk_scope_never_retrains_a_mutated_chunk(monkeypatch):
    """The contrast the global scope exists to remove (projector.py, drain: only
    pages / chunks the model has never seen are scheduled)."""
    proj, ws, rows = _global(monkeypatch, scope="")
    assert proj.scope == "chunks"
    _mutate(rows, ws, proj, "https://p3.test/", "https://p9.test/")
    assert proj.drain(ws) is not None
    assert not wait_for(lambda: proj.online_updates, seconds=2.0), "the chunk scope retrained"
    assert not proj._pending_online


@needs_cuda
def test_a_new_page_appends_rows_and_a_retired_chunk_frees_one_for_reuse(monkeypatch):
    monkeypatch.setattr(PageProjector, "ONLINE_DEBOUNCE_S", 0.05)
    rows = make_rows()
    held_back = [r for r in rows if r[1] == "https://p13.test/"]
    ws = workspace([r for r in rows if r[1] != "https://p13.test/"])
    proj = PageProjector(dims=3, centroid="semantic", seed=0, engine="parametric", umap_scope="global")
    if proj.engine != "parametric":
        pytest.skip("no CUDA/torch")
    proj.fit(ws)
    n0 = proj.pumap._raw.shape[0]
    ws.store = Store(rows)
    proj.enqueue([r[0] for r in held_back])
    proj.drain(ws)
    assert wait_for(lambda: len(proj.online_updates) >= 1)
    assert proj.pumap._raw.shape[0] == n0 + PER + 1
    assert "https://p13.test/" in proj.trained and len(proj.rows.of_url["https://p13.test/"]) == PER + 1
    # Three chunks of p2 leave the store.
    gone = [r[0] for r in rows if r[1] == "https://p2.test/"][:3]
    ws.store = Store([r for r in rows if r[0] not in gone])
    proj.enqueue(gone)
    proj.drain(ws)
    assert wait_for(lambda: len(proj.online_updates) >= 2)
    assert len(proj.rows.free) == 3 and int((~proj.pumap._alive).sum()) == 3
    assert all(c not in proj.pos for c in gone)
    n1 = proj.pumap._raw.shape[0]
    # They come back (or three new ones arrive): the freed rows are reused.
    ws.store = Store(rows)
    proj.enqueue(gone)
    proj.drain(ws)
    assert wait_for(lambda: len(proj.online_updates) >= 3)
    assert proj.pumap._raw.shape[0] == n1 and proj.rows.free == [] and proj.pumap._alive.all()


@needs_cuda
def test_the_refit_path_retrains_only_the_pages_that_differ(monkeypatch):
    proj, ws, rows = _global(monkeypatch)
    new_rows, _mine = _mutate(rows, ws, proj, "https://p3.test/", "https://p9.test/")
    got = proj.fit(ws)
    assert got["online"] is True and got["scope"]["scope"] == "global", got
    assert got["global_refit"]["pages"] == 1 and got["global_refit"]["groups"] == 1
    assert proj.pumap._raw.shape[0] == PAGES + len(rows)
    # An identical store: nothing differs, nothing is retrained.
    again = proj.fit(ws)
    assert again["global_refit"]["pages"] == 0
