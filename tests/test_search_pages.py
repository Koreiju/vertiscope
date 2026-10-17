"""Tier 1 of a tiered search (G-210): url nodes ranked by their semantic
centroid -- the normalised mean of their chunks' unit vectors. Built in the
two matrices' OPPOSITE row orders (the alignment trap of
test_semantic_row_alignment), so a centroid built from the wrong rows would
rank the wrong page first. Null arm: a query meaning page B ranks B, not A."""
import numpy as np

from domvec.search import ThreeFormIndex
from domvec.vectors import EmbeddingMatrix, FreqMatrix


class _Chunk:
    def __init__(self, cid, url):
        self.cid, self.url, self.xpath, self.md = cid, url, "/html/body/p", "chunk " + cid


class _Store:
    def __init__(self, chunks):
        self._chunks = chunks

    def edges(self):
        return []

    def chunks(self):
        return list(self._chunks)

    def chunk(self, cid):
        return next((c for c in self._chunks if c.cid == cid), None)


class _Embedder:
    def __init__(self, table):
        self.table = table

    def embed_query(self, query):
        return self.table[query]


def test_pages_ranked_by_their_chunks_centroid():
    dim = 16
    rng = np.random.default_rng(3)
    axis = {u: rng.normal(size=dim) for u in ("A", "B", "C")}
    chunks, vec = [], {}
    for u in ("A", "B", "C"):
        for i in range(4):
            cid = "%s%d" % (u, i)
            chunks.append(_Chunk(cid, "https://t.test/" + u))
            vec[cid] = axis[u] + 0.3 * rng.normal(size=dim)
    freq = FreqMatrix()
    for c in chunks:
        freq.add(c.cid, "words " + c.cid)
    emb = EmbeddingMatrix(dim=dim)
    for c in reversed(chunks):                  # the opposite row order
        emb.set(c.cid, vec[c.cid])
    table = {"about " + u: axis[u] for u in axis}
    index = ThreeFormIndex(_Store(chunks), freq, emb, embedder=_Embedder(table)).build()
    for u in ("A", "B", "C"):
        got = index.search_pages("about " + u, k=3)
        assert got[0][0] == "https://t.test/" + u, got
        assert len(got) == 3
    urls1, c1 = index.page_centroids()
    assert index.page_centroids()[1] is c1           # cached
    freq.add("A9", "words A9")                       # content changed: rebuilt
    assert index.page_centroids()[1] is not c1
