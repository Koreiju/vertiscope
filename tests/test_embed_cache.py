"""The query-side embedding matrix is cached, so a restart need not wait for it.

The first search after a sidecar restart waited 32.3 s (2026-11-15), 21.8 s of
it reading 86k x 768 vectors back out of the store. `EmbeddingMatrix.load`
reads a saved copy instead; `Workspace._reconcile_embeddings` checks it against
the store off the request path, so the copy can be wrong only about what was
embedded after its last save, and only until that lands.

Planted arms: a STALE vector planted in the saved file must be replaced by
the store's after the reconcile, and must stay stale with the reconcile
planted off (`PLANT_NO_EMBED_RECONCILE`) -- else the check could not fail.
"""
import numpy as np

from domvec.vectors import EmbeddingMatrix
from domvec.workspace import Workspace

from test_obsidian_layout import _StubEmbedder


def _pages():
    return {"https://%s.test/" % k: "<html><body><main>" + "".join(
        "<p>%s words here %d</p>" % (k, i) for i in range(30)) + "</main></body></html>"
        for k in ("a", "b", "c")}


def _build(path):
    with Workspace(path, embedder=_StubEmbedder()) as w:
        for url, html in _pages().items():
            w.index_html(html, url)
        w.flush_vectors()
        w._hydrate_embeddings()
        assert w.save_embeddings()
        stored = dict(w.store._rows("MATCH (c:Chunk) RETURN c.cid, c.embedding"))
    return {c: np.asarray(v, dtype=np.float32) for c, v in stored.items() if v is not None and any(v)}


def test_a_saved_matrix_round_trips_and_a_torn_pair_is_refused(tmp_path):
    m = EmbeddingMatrix(dim=8)
    g = np.random.default_rng(0)
    for i in range(5):
        m.set("c%d" % i, g.normal(size=8))
    EmbeddingMatrix.write_snapshot(tmp_path / "embeddings", m.snapshot())
    back = EmbeddingMatrix.load(tmp_path / "embeddings")
    assert back.rows == m.rows and np.allclose(back.matrix, m.matrix)
    # A json from one save beside an npy from another: refused, not misaligned.
    m.set("c5", g.normal(size=8))
    np.save(tmp_path / "embeddings.npy", m.snapshot()["matrix"])
    assert EmbeddingMatrix.load(tmp_path / "embeddings") is None


def _plant_stale(path, cid):
    m = EmbeddingMatrix.load(path / "embeddings")
    m.set(cid, np.ones(m.dim, dtype=np.float32))
    EmbeddingMatrix.write_snapshot(path / "embeddings", m.snapshot())


def _reopen(path):
    w = Workspace(path)
    got = w._hydrate_embeddings(backfill=False)
    t = getattr(w, "_embed_reconciler", None)
    if t is not None:
        t.join(timeout=60)
    return w, got


def test_a_restart_reads_the_saved_matrix_and_the_store_corrects_it(tmp_path):
    path = tmp_path / "ws"
    stored = _build(path)
    assert len(stored) >= 2, len(stored)
    cid = sorted(stored)[len(stored) // 2]
    _plant_stale(path, cid)
    w, got = _reopen(path)
    try:
        assert got.get("cached") == len(stored), got
        row = w.embeddings.row_of(cid)
        want = stored[cid] / np.linalg.norm(stored[cid])
        assert np.allclose(w.embeddings.matrix[row], want, atol=1e-5)
        assert w.embed_reconciled["changed"] == 1, w.embed_reconciled
    finally:
        w.close()


def test_planted_no_reconcile_keeps_the_stale_vector(tmp_path, monkeypatch):
    path = tmp_path / "ws"
    stored = _build(path)
    assert len(stored) >= 2, len(stored)
    cid = sorted(stored)[len(stored) // 2]
    _plant_stale(path, cid)
    monkeypatch.setattr(Workspace, "PLANT_NO_EMBED_RECONCILE", [True])
    w, got = _reopen(path)
    try:
        row = w.embeddings.row_of(cid)
        stale = np.ones(w.embeddings.dim, dtype=np.float32) / np.sqrt(w.embeddings.dim)
        assert np.allclose(w.embeddings.matrix[row], stale, atol=1e-5)
    finally:
        w.close()


def test_planted_no_cache_reads_every_vector_from_the_store(tmp_path, monkeypatch):
    path = tmp_path / "ws"
    stored = _build(path)
    monkeypatch.setattr(Workspace, "PLANT_NO_EMBED_CACHE", [True])
    w, got = _reopen(path)
    try:
        assert "cached" not in got and got["loaded"] == len(stored), got
    finally:
        w.close()
