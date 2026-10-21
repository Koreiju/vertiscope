"""Shared fakes for the online-UMAP tests: a store that can answer `drain`.

`PageProjector.drain` reads `store.chunks_for_placement(cids)` -> rows of
(cid, chunk-or-None, vector); `fit` reads `store.lead_vectors()` and
`store.chunk_count()`. Nothing else of the workspace is touched with the
semantic centroid, so a few lines stand in for the whole store.
"""

from types import SimpleNamespace

import numpy as np

PAGES, PER, DIM = 14, 9, 32


def make_rows(seed=0, spread=0.6, pages=PAGES, per=PER, dim=DIM):
    rng = np.random.default_rng(seed)
    centres = rng.normal(size=(pages, dim)) * 3.0
    rows = []
    for p in range(pages):
        for k in range(per):
            v = centres[p] + rng.normal(size=dim) * spread
            rows.append(("c%d_%d" % (p, k), "https://p%d.test/" % p, v.astype(np.float32).tolist()))
    return rows


class _Chunk:
    def __init__(self, url):
        self.url = url
        self.redundant = False
        self.group_of = None


class Store:
    def __init__(self, rows):
        self.rows = list(rows)

    def lead_vectors(self):
        return self.rows

    def chunk_count(self):
        return len(self.rows)

    def chunks_for_placement(self, cids):
        by = {c: (u, v) for c, u, v in self.rows}
        return [(c, _Chunk(by[c][0]), by[c][1]) if c in by else (c, None, None) for c in cids]


def workspace(rows):
    return SimpleNamespace(store=Store(rows), path=None)


def wait_for(pred, seconds=60.0):
    import time
    end = time.time() + seconds
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.05)
    return False
