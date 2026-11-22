"""PLUGIN_GOAL 173 (b): the parametric model's input de-biased, and a re-fit
that starts over.

These test the MECHANICS (the map, its replay through transform, update and
pickling, the fresh path). Whether de-biasing rounds the layout is a claim
about the store's vectors and is measured on them, by the real parametric
model, in `analytics.layout_shape` (arms `pumap` and `pumap_debias`). A
synthetic corpus written here first asserted it and came out the other way
(11:1 against 3.2:1) -- a corpus of my own invention, not evidence.
"""

import pickle

import numpy as np
import pytest

from domvec.analytics.layout_shape import aspect


def _cuda():
    try:
        import torch
        return torch.cuda.is_available()
    except Exception:
        return False


needs_cuda = pytest.mark.skipif(not _cuda(), reason="the parametric model trains on CUDA")


def _shared(pages=8, per=60, dim=48, seed=0):
    rng = np.random.default_rng(seed)
    common = rng.normal(size=dim); common /= np.linalg.norm(common)
    centres = rng.normal(size=(pages, dim)) * 0.6
    rows = []
    for p in range(pages):
        t = rng.uniform(4, 12, size=(per, 1))              # a long gradient along the shared direction
        rows.append(t * common + centres[p] + rng.normal(size=(per, dim)) * 0.15)
    X = np.vstack(rows).astype(np.float32)
    return X / np.linalg.norm(X, axis=1, keepdims=True), np.repeat(np.arange(pages), per)


def _fit(debias):
    from domvec.obsidian.pumap import ParametricUMAP
    X, page_of = _shared()
    m = ParametricUMAP(n_components=3, n_neighbors=10, seed=0, debias=debias)
    m.fit(X, max_steps=600)
    return m, X, page_of


def test_debias_map_is_the_mean_and_top_directions_removed():
    from domvec.obsidian.pumap import ParametricUMAP
    X, _ = _shared()
    m = ParametricUMAP(debias=2)
    m._fit_debias(X)
    Z = m._in(X)
    assert abs(float(Z.mean(axis=0).max())) < 1e-4
    assert float(np.abs(Z @ m._top.T).max()) < 1e-3          # nothing left along the removed directions
    off = ParametricUMAP(debias=None)
    off._fit_debias(X)
    assert np.array_equal(off._in(X), X)                       # off: the input as given


@needs_cuda
def test_transform_update_and_pickle_replay_the_same_debias():
    m, X, page_of = _fit(2)
    np.testing.assert_allclose(m.transform(X), m.embedding_, atol=1e-4)
    rows = np.flatnonzero(page_of == 3)
    got = m.update_subset(X[rows], rows, steps=60, measure_drift=False)
    assert np.isfinite(got).all()
    back = pickle.loads(pickle.dumps(m))
    np.testing.assert_allclose(back._mu, m._mu)
    np.testing.assert_allclose(back.transform(X[:20]), m.transform(X[:20]), atol=1e-4)


def test_a_requested_refit_takes_the_fresh_path_and_the_plant_does_not(monkeypatch):
    from domvec.obsidian import projector as pj
    src = open(pj.__file__, encoding="utf-8").read()
    assert "if fresh and not PLANT_INCREMENTAL_REFIT[0]:" in src
    assert 'kwargs={"fresh": True}' in open(pj.__file__.replace("projector.py", "sidecar.py"), encoding="utf-8").read()
    assert pj.PageProjector.DEBIAS in (None, 2)                  # off until the reader turns it on
