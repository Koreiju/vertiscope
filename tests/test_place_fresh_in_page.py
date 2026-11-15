"""A chunk the stream has not placed yet is drawn in its page's neighbourhood.

`/place` (`place_projected`) answered a chunk the projector's stream had not
reached with its RAW transform, which lands nearest its own page 19-23% of the
time. G-94 run 133 (2026-11-15): Radix_tree re-captured and open, 29 of its 40
drawn chunks nearer another page, cloud spread 91.9, the farthest 26.6
page-distances off -- until the stream re-placed them. Fresh chunks now go
through the page projector's own `_place_chunks`.

Planted `PLANT_PLACE_RAW`: the raw transform, which must scatter them.
"""
from types import SimpleNamespace

import numpy as np

from domvec.obsidian import layout as L

from test_page_projector_default import PAGES, _fit, _rows


class _Chunk(SimpleNamespace):
    pass


def _fresh(seed=5, spread=4.0, per=6):
    """New chunks for every page, as a re-capture brings: same pages, new
    cids, noisy vectors (individually nearer other pages, as measured)."""
    rows = _rows(seed=0, spread=spread)
    centres = {}
    for cid, url, v in rows:
        centres.setdefault(url, []).append(np.asarray(v))
    rng = np.random.default_rng(seed)
    out = []
    for url, vs in centres.items():
        c = np.mean(vs, axis=0)
        for k in range(per):
            v = c + rng.normal(size=c.shape) * spread
            out.append(("fresh_%s_%d" % (url.split("//")[1].split(".")[0], k), url, v.astype(np.float32).tolist()))
    return rows, out


class _Store:
    def __init__(self, fresh):
        self.fresh = {c: (u, v) for c, u, v in fresh}

    def chunks_for_placement(self, batch):
        for c in batch:
            if c in self.fresh:
                u, v = self.fresh[c]
                yield c, _Chunk(cid=c, url=u, md="text " + c, chars=10, dup_n=1, group_n=1,
                                redundant=False, group_of="", dup_of=""), v

    def chunk_count(self, url):
        return 1

    def contains_within(self, page, among=None):
        return []


def _own_share(proj, nodes):
    urls = sorted(proj.page_pos)
    P = np.asarray([proj.page_pos[u][:3] for u in urls])
    chunks = [n for n in nodes if n.get("level") == "chunk"]
    hit = sum(urls[int(np.argmin(np.linalg.norm(P - np.asarray(n["pos"]), axis=1)))] == n["url"] for n in chunks)
    return hit / max(len(chunks), 1), len(chunks)


def _place(monkeypatch, planted):
    rows, fresh = _fresh()
    proj = _fit(rows)
    proj.enqueue = lambda cids: list(cids)          # the stream is not running here
    monkeypatch.setattr(L, "PLANT_PLACE_RAW", [planted])
    ws = SimpleNamespace(store=_Store(fresh))
    got = L.place_projected(ws, [c for c, _u, _v in fresh], proj)
    return _own_share(proj, got["nodes"]), got.get("timing", {})


def test_fresh_chunks_are_drawn_beside_their_own_page(monkeypatch):
    (share, n), timing = _place(monkeypatch, False)
    assert n == PAGES * 6, n
    assert timing.get("placed_in_page") == n, timing
    assert share >= 0.95, share


def test_planted_raw_transform_scatters_them(monkeypatch):
    (share, n), timing = _place(monkeypatch, True)
    assert n == PAGES * 6, n
    assert share < 0.8, share
