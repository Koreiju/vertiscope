"""G-106: the online UMAP trains on every chunk while that is affordable, on
page centroids once it is not -- decided by what an update costs on this GPU.

"Depending on GPU runtimes, perhaps update with the full set of chunks, or
just the centroided pages, or the former for few pages and the latter for
tens to hundreds." (2026-09-28)

Planted arms: a budget of 1 ms must force pages on a small store; a budget of
1e9 must force chunks on a store the default budget sends to pages. The fit
test checks what the model was TRAINED on (`pumap._raw`), not what it
reports, and that drawing did not change with the scope.
"""

from types import SimpleNamespace

import numpy as np
import pytest

from vertiscope.obsidian.refitscope import RefitCost, WHOLE_FORWARD_ROWS, choose_scope


# -- the decision -------------------------------------------------------------

def test_a_small_store_trains_on_chunks_a_large_one_on_pages():
    cost = RefitCost()
    small = choose_scope(13, 400, cost, 5000.0)
    large = choose_scope(159, 16189, cost, 5000.0)
    assert small["scope"] == "chunks", small
    assert large["scope"] == "pages", large
    assert "predicted" in small["why"] and small["predicted_ms"] <= 5000.0


def test_planted_budgets_move_the_decision_both_ways():
    cost = RefitCost()
    assert choose_scope(13, 400, cost, 1.0)["scope"] == "pages"
    # 159 pages + 2,000 chunks is pages at 5 s and chunks when money is no object.
    assert choose_scope(159, 2000, cost, 5000.0)["scope"] == "pages"
    assert choose_scope(159, 2000, cost, 1e9)["scope"] == "chunks"


def test_past_the_whole_forward_limit_no_budget_buys_chunks():
    got = choose_scope(10, WHOLE_FORWARD_ROWS, RefitCost(), 1e12)
    assert got["scope"] == "pages" and str(WHOLE_FORWARD_ROWS) in got["why"]


def test_engines_and_centroids_that_cannot_train_on_chunks_stay_on_pages():
    cost = RefitCost()
    assert choose_scope(13, 40, cost, 1e9, engine="umap")["scope"] == "pages"
    assert choose_scope(13, 40, cost, 1e9, centroid="triple")["scope"] == "pages"


# -- the cost model -----------------------------------------------------------

def test_the_seed_curve_predicts_the_measured_points_roughly():
    cost = RefitCost()
    assert cost.seeded
    assert 4000 < cost.predict(1000) < 9000          # measured 6,580 ms
    assert cost.predict(2000) > cost.predict(500)


def test_this_machines_own_updates_replace_the_seed():
    cost = RefitCost()
    cost.observe(rows=200, ms=400.0)
    assert cost.seeded                               # one row count is not a line
    cost.observe(rows=1200, ms=1400.0)
    assert not cost.seeded
    assert cost.predict(700) == pytest.approx(900.0, abs=1.0)
    # A faster GPU than the seed's: the same store now fits the budget.
    assert choose_scope(159, 2000, cost, 5000.0)["scope"] == "chunks"


# -- a real fit ---------------------------------------------------------------

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


def _fit(rows, budget=None):
    from vertiscope.obsidian.projector import PageProjector
    proj = PageProjector(dims=3, centroid="semantic", seed=0)
    if proj.engine != "parametric":
        pytest.skip("no CUDA/torch: the parametric engine is what has an update() to scope")
    if budget is not None:
        proj.SCOPE_BUDGET_MS = budget
    got = proj.fit(SimpleNamespace(store=_Store(rows), path=None))
    assert "error" not in got and "skipped" not in got, got
    return proj, got


def _own_page_share(proj, rows):
    urls = sorted(proj.page_pos)
    P = np.asarray([proj.page_pos[u] for u in urls])
    hit = sum(urls[int(np.argmin(np.linalg.norm(P - np.asarray(proj.pos[c]), axis=1)))] == u
              for c, u, _v in rows)
    return hit / len(rows)


def test_chunk_scope_trains_the_model_on_every_chunk():
    rows = _rows()
    proj, record = _fit(rows)
    assert proj.scope == "chunks", proj.scope_record
    assert record["scope"]["scope"] == "chunks"
    # What the model LEARNED: 14 page centroids and all 126 chunk vectors.
    assert proj.pumap._raw.shape[0] == PAGES + len(rows)
    assert len(proj.trained_chunks) == len(rows)
    st = proj.status()
    assert st["scope"] == "chunks" and st["scope_why"] and st["trained_chunks"] == len(rows)
    # Demand 4: drawing did not change -- chunks still beside their page.
    assert _own_page_share(proj, _rows()) >= 0.9


def test_planted_budget_trains_on_pages_only():
    rows = _rows()
    proj, record = _fit(rows, budget=1.0)
    assert proj.scope == "pages", proj.scope_record
    assert proj.pumap._raw.shape[0] == PAGES
    assert proj.trained_chunks == set()
    assert _own_page_share(proj, rows) >= 0.9


# -- an empty workspace's first page (2026-10-04) ------------------------------

def test_one_page_fits_over_its_chunks():
    # The user story from an empty workspace: one page stored, 9 chunks with
    # vectors. The page fit needs 4 pages; the chunk fit needs only chunks.
    rows = [r for r in _rows() if r[1] == "https://p0.test/"]
    proj, record = _fit(rows)
    assert proj.scope == "chunks", proj.scope_record
    assert "fewer than the 4" in proj.scope_record["why"]
    assert len(proj.page_pos) == 1 and len(proj.pos) == len(rows)
    assert proj.pumap._raw.shape[0] == 1 + len(rows)


def test_one_page_fits_over_its_chunks_with_umap_learn_too():
    # No CUDA (torch 2.14.1+cpu was found installed on 2026-10-04): the first
    # page must still be drawn.
    from vertiscope.obsidian.projector import PageProjector
    rows = [r for r in _rows() if r[1] == "https://p0.test/"]
    proj = PageProjector(dims=3, centroid="semantic", seed=0, engine="umap")
    got = proj.fit(SimpleNamespace(store=_Store(rows), path=None))
    assert "error" not in got and "skipped" not in got, got
    assert proj.scope == "chunks" and len(proj.pos) == len(rows) and len(proj.page_pos) == 1


def test_planted_one_page_with_the_triple_centroid_still_refuses():
    # The triple centroid has no chunk-vector counterpart: no chunk fit.
    from vertiscope.obsidian.projector import PageProjector
    rows = [r for r in _rows() if r[1] == "https://p0.test/"]
    proj = PageProjector(dims=3, centroid="triple", seed=0, engine="umap")
    got = proj.fit(SimpleNamespace(store=_Store(rows), path=None))
    assert got.get("skipped") == "too few pages" and proj.fit_skip["chunks"] == len(rows)
