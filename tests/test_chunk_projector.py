"""The chunk projector is what the graph is drawn from -- and it streams.

Each test pins one clause of the design the user stated: chunks streamed
O(delta) in queue batches into a fitted UMAP projector, transformed in, and
refitted only when the chunk count doubles. Every one has an arm that would
fail if the clause were not true:

* the fit places EVERY drawable chunk, and a duplicate or a merge-group
  member is not a point of its own;
* a chunk streamed in after the fit gets a position without any existing
  position moving -- and the stream reports exactly it, not a new layout;
* a chunk the store lost is reported gone;
* the refit rule fires at 2x and not at 1.99x;
* a pane on an old epoch is told to reload rather than handed a delta in the
  wrong frame;
* a kept fit restores and re-queues only what changed;
* `place` returns the STREAM's position -- planted: a sentinel written into
  the projector must come back verbatim, which a recomputation cannot do.
"""

from types import SimpleNamespace

import numpy as np
import pytest

pytest.importorskip("umap")

from vertiscope.obsidian import projector as P


def _chunk(cid, url, **kw):
    base = dict(cid=cid, url=url, redundant=False, group_of="", md="# " + cid,
                chars=10, dup_n=1, group_n=1, xpath="/html/body/p[%s]" % cid,
                part=0)
    base.update(kw)
    return SimpleNamespace(**base)


class _Store:
    """The four reads the projector makes, over plain dicts."""

    def __init__(self, n=160, dim=24, pages=4, seed=1):
        rng = np.random.default_rng(seed)
        centres = rng.normal(size=(pages, dim)) * 3
        self.chunks, self.vectors = {}, {}
        for i in range(n):
            page = i % pages
            v = centres[page] + rng.normal(size=dim)
            cid = "c%03d" % i
            self.chunks[cid] = _chunk(cid, "https://p%d.test/" % page)
            self.vectors[cid] = list(v / np.linalg.norm(v))
        self.extra = 0

    def lead_vectors(self):
        return [(c, ch.url, self.vectors[c]) for c, ch in self.chunks.items()
                if not ch.redundant and not (ch.group_of and ch.group_of != c)
                and self.vectors.get(c)]

    def chunk_count(self, url=""):
        return len(self.chunks) + self.extra

    def chunks_for_placement(self, cids):
        return [(c, self.chunks.get(c), self.vectors.get(c)) for c in cids]

    def contains_within(self, url, among=None):
        return []


@pytest.fixture(scope="module")
def fitted(tmp_path_factory):
    store = _Store()
    # A duplicate and a merge member: neither may become a point.
    store.chunks["c000"].redundant = True
    store.chunks["c001"].group_of = "c005"
    ws = SimpleNamespace(store=store, path=str(tmp_path_factory.mktemp("ws")))
    proj = P.ChunkProjector(dims=3, sample_cap=100)
    got = proj.fit(ws)
    assert "error" not in got, got
    return ws, proj, got


def test_the_fit_places_every_drawable_chunk_and_only_those(fitted):
    ws, proj, got = fitted
    drawable = {c for c, _u, _v in ws.store.lead_vectors()}
    assert set(proj.pos) == drawable
    assert "c000" not in proj.pos and "c001" not in proj.pos
    # Fitted on a sample; the rest were placed by transform.
    assert got["sample"] == 100 and got["chunks"] == len(drawable)
    assert len(proj.page_pos) == 4


def test_a_streamed_chunk_is_placed_and_nothing_else_moves(fitted):
    ws, proj, _ = fitted
    before = {c: list(p) for c, p in proj.pos.items()}
    seq0, epoch = proj.seq, proj.epoch
    v = np.asarray(ws.store.vectors["c010"]) + 0.01
    ws.store.chunks["new1"] = _chunk("new1", "https://p2.test/")
    ws.store.vectors["new1"] = list(v / np.linalg.norm(v))
    proj.enqueue(["new1"])
    record = proj.drain(ws)
    assert record["placed"] == 1 and record["gone"] == 0
    assert "new1" in proj.pos
    assert all(proj.pos[c] == p for c, p in before.items()), \
        "an existing chunk moved when one new chunk was streamed in"
    delta = proj.delta(seq0, epoch)
    assert not delta["reload"]
    assert set(delta["chunks"]) == {"new1"}, "the stream sent more than the delta"
    assert "https://p2.test/" in delta["pages"]


def test_a_chunk_the_store_lost_is_reported_gone(fitted):
    ws, proj, _ = fitted
    seq0 = proj.seq
    del ws.store.chunks["c020"]
    proj.enqueue(["c020"])
    record = proj.drain(ws)
    assert record["gone"] == 1 and "c020" not in proj.pos
    assert proj.delta(seq0, proj.epoch)["gone"] == ["c020"]


def test_refit_fires_at_twice_the_fitted_chunks_and_not_before(fitted):
    ws, proj, _ = fitted
    base = proj.fitted_chunks
    ws.store.extra = 0
    real = ws.store.chunk_count()
    ws.store.extra = int(1.99 * base) - real
    assert not proj.stale(ws), "refit fired before the corpus doubled"
    ws.store.extra = 2 * base - real
    assert proj.stale(ws), "refit did not fire at 2x"
    ws.store.extra = 0


def test_an_old_epoch_is_told_to_reload(fitted):
    _ws, proj, _ = fitted
    assert proj.delta(0, proj.epoch - 1)["reload"] is True


def test_a_fresh_process_never_reuses_an_epoch(fitted):
    """Planted: a projector starting from zero, as a restarted process does,
    must not hand out the number a pane already holds."""
    ws, proj, _ = fitted
    fresh = P.ChunkProjector(dims=3, sample_cap=100)
    fresh.fit(ws)
    assert fresh.epoch != proj.epoch


def test_place_returns_the_streams_position_verbatim(fitted):
    """Planted: a recomputation could not produce this sentinel."""
    from vertiscope.obsidian.layout import place_projected
    ws, proj, _ = fitted
    sentinel = [123.25, -45.5, 6.75]
    with proj.lock:
        kept = proj.pos["c030"]
        proj.pos["c030"] = sentinel
    try:
        got = place_projected(ws, ["c030"], proj)
    finally:
        with proj.lock:
            proj.pos["c030"] = kept
    node = next(n for n in got["nodes"] if n["cid"] == "c030")
    assert node["pos"] == sentinel
    assert got["timing"]["from_stream"] == 1
    assert got["timing"]["transformed_here"] == 0
    # The page hub rides along, at the projector's page position.
    hub = next(n for n in got["nodes"] if n["level"] == "page")
    assert hub["pos"] == [float(v) for v in proj.page_pos[hub["url"]]]


def test_place_says_which_cids_the_store_does_not_hold(fitted):
    """G-82: a retired cid is `unknown`, not merely `unplaced` -- the pin
    stops waiting for a vector that cannot come. Null arm: a held chunk is
    never called unknown."""
    from vertiscope.obsidian.layout import place_projected
    ws, proj, _ = fitted
    got = place_projected(ws, ["c030", "0000dead0000beef"], proj)
    assert got["unknown"] == ["0000dead0000beef"]
    assert any(n["cid"] == "c030" for n in got["nodes"])
    assert place_projected(ws, ["c030"], proj)["unknown"] == []


def test_a_kept_fit_restores_and_requeues_only_what_changed(fitted):
    ws, proj, _ = fitted
    assert proj.save(ws)
    v = np.asarray(ws.store.vectors["c040"]) * -1.0
    ws.store.vectors["c040"] = list(v)          # its text changed
    back = P.ChunkProjector(dims=3, sample_cap=100)
    assert back.load(ws)
    assert back.pos == proj.pos
    assert back.epoch > proj.epoch, "a pane from before must reload"
    assert set(back.queue) == {"c040"}, sorted(back.queue)[:10]
