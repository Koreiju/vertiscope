"""The first search after a restart answers from a SAVED index build.

`ThreeFormIndex.build` reads every chunk's markdown and every edge: 10.5-36.8 s
on the working store (2026-11-15), and with the embedding hydrate cached it is
what the first search still waited on. A full build's per-row state is saved
with the cid each row held; at start a saved row counts only while the
lexical matrix still holds that cid at that row, every other row is re-read
as a delta, and the background full build replaces the lot.

Planted: a saved row recorded under ANOTHER cid -- a row that changed hands --
must be caught and re-read (its meta the store's, not the file's); and
`PLANT_NO_INDEX_CACHE` builds in full, as before.
"""
import json
import time

from domvec.search import ThreeFormIndex
from domvec.workspace import Workspace

from test_obsidian_layout import _StubEmbedder


def _pages():
    words = {"a": "orchid pollen bee", "b": "granite basalt quartz", "c": "violin cello bow", "d": "comet orbit perihelion"}
    return {"https://%s.test/" % k: "<html><body><main>" + "".join(
        "<h2>%s %d</h2><p>%s notes number %d here</p>" % (w, i, w, i) for i in range(12)) + "</main></body></html>"
        for k, w in words.items()}


def _build(path):
    with Workspace(path, embedder=_StubEmbedder()) as w:
        for url, html in _pages().items():
            w.index_html(html, url)
        w.flush_vectors()
        w._index = None
        idx = w.index
        for _ in range(100):
            if getattr(w, "index_saved", None):
                break
            time.sleep(0.05)
        assert w.index_saved and "error" not in w.index_saved, getattr(w, "index_saved", None)
        return [(h.cid, h.url) for h in w.search("granite quartz", k=5)], idx.snapshot()["n"]


def _first_search(path):
    w = Workspace(path, embedder=_StubEmbedder())
    hits = [(h.cid, h.url) for h in w.search("granite quartz", k=5)]
    return w, hits, w.index_builds[0]


def test_a_restart_answers_from_the_saved_build(tmp_path):
    path = tmp_path / "ws"
    want, n = _build(path)
    w, got, rec = _first_search(path)
    try:
        assert rec["from_saved"] is True and rec["redo"] == 0, rec
        assert got == want, (got, want)
    finally:
        w.close()


def test_planted_row_that_changed_hands_is_reread(tmp_path):
    path = tmp_path / "ws"
    want, n = _build(path)
    meta_path = path / "index_cache.json"
    info = json.loads(meta_path.read_text(encoding="utf-8"))
    row = next(r for r, m in enumerate(info["meta"]) if m)
    real = info["meta"][row][0]
    info["meta"][row] = ["0000deadbeef0000", "https://elsewhere.test/", "/html/body"]
    meta_path.write_text(json.dumps(info), encoding="utf-8")
    w, got, rec = _first_search(path)
    try:
        assert rec["from_saved"] is True and rec["redo"] >= 1, rec
        assert w.index._meta[row][0] == real, w.index._meta.get(row)
        assert got == want, (got, want)
    finally:
        w.close()


def test_planted_no_cache_builds_in_full(tmp_path, monkeypatch):
    path = tmp_path / "ws"
    _build(path)
    monkeypatch.setattr(Workspace, "PLANT_NO_INDEX_CACHE", [True])
    w, got, rec = _first_search(path)
    try:
        assert rec["from_saved"] is False, rec
    finally:
        w.close()


def test_a_torn_save_is_refused(tmp_path):
    path = tmp_path / "ws"
    _build(path)
    meta_path = path / "index_cache.json"
    info = json.loads(meta_path.read_text(encoding="utf-8"))
    info["meta"] = info["meta"][:-1]
    meta_path.write_text(json.dumps(info), encoding="utf-8")
    w = Workspace(path)
    try:
        idx, redo = ThreeFormIndex.load_saved(path / "index_cache", w.store, w.freq)
        assert idx is None and redo is None
    finally:
        w.close()


def test_a_row_the_build_left_dark_is_not_reread_while_its_cid_holds(tmp_path):
    # 19,585 of 112,054 rows on the working store are in the lexical matrix
    # and not in the store; the build leaves them dark. Re-reading them all
    # at every start cost 20 s and found nothing (2026-11-15).
    path = tmp_path / "ws"
    _build(path)
    meta_path = path / "index_cache.json"
    info = json.loads(meta_path.read_text(encoding="utf-8"))
    row = next(r for r, m in enumerate(info["meta"]) if m)
    info["meta"][row] = None                       # as the build left it: dark
    meta_path.write_text(json.dumps(info), encoding="utf-8")
    w = Workspace(path)
    try:
        idx, redo = ThreeFormIndex.load_saved(path / "index_cache", w.store, w.freq)
        assert idx is not None and redo == [] and idx._live[row] == 0.0, redo
        # ...and the same dark row recorded under ANOTHER cid is re-read.
        info["cids"][row] = "0000deadbeef0000"
        meta_path.write_text(json.dumps(info), encoding="utf-8")
        idx, redo = ThreeFormIndex.load_saved(path / "index_cache", w.store, w.freq)
        assert redo == [w.freq.rows[row]], redo
    finally:
        w.close()
