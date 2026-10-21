"""The semantic factor must score the chunk it is multiplied with.

Retrieval is a strict product over FREQUENCY rows. The semantic factor came
from `EmbeddingMatrix.similarities`, which answers in the embedding matrix's
OWN row order -- the order vectors arrived in -- and was then read as if it
were in frequency-row order. The two orders agree on a corpus built in one
pass and nowhere else: the frequency matrix reclaims retired rows and gets
rows added by repair, while the embedding matrix appends. Wherever they
diverged, a chunk was scored with another chunk's similarity: pages captured
live were unreachable by their own name, and "Ternary search tree" ranked
coinmarketcap above the page about ternary search trees.

Planted here by building the two matrices in opposite orders. A search for
the exact meaning of one chunk must return that chunk first.
"""

import numpy as np

from vertiscope.search import ThreeFormIndex
from vertiscope.vectors import EmbeddingMatrix, FreqMatrix


class _Chunk:
    def __init__(self, cid, url):
        self.cid, self.url, self.xpath = cid, url, "/html/body/p"
        self.md = "chunk " + cid       # distinct, so collapse keeps each


class _Store:
    def __init__(self, cids):
        self._chunks = [_Chunk(c, "https://t.test/" + c) for c in cids]

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


def _index(freq_order, emb_order, dim=8):
    rng = np.random.default_rng(0)
    vectors = {c: rng.normal(size=dim) for c in freq_order}
    freq = FreqMatrix()
    for c in freq_order:
        freq.add(c, "shared words about %s" % c)
    emb = EmbeddingMatrix(dim=dim)
    for c in emb_order:
        emb.set(c, vectors[c])
    table = {"meaning of " + c: vectors[c] for c in freq_order}
    idx = ThreeFormIndex(_Store(freq_order), freq, emb,
                         embedder=_Embedder(table)).build()
    return idx


def test_the_semantic_factor_follows_the_chunk_not_the_row():
    cids = ["a", "b", "c", "d", "e", "f"]
    idx = _index(cids, list(reversed(cids)))       # the orders disagree
    for target in cids:
        hits = idx.search("meaning of " + target, k=1)
        assert hits, "no hit for %s" % target
        assert hits[0].cid == target, (
            "searching for %s's meaning returned %s" % (target, hits[0].cid))


def test_a_chunk_with_no_vector_scores_zero_not_a_neighbours_similarity():
    cids = ["a", "b", "c"]
    idx = _index(cids, ["c", "a"])                  # "b" has no vector
    sims, available = idx._semantic("meaning of a", len(idx.freq.rows))
    assert available
    assert sims[idx.freq.row_of("b")] == 0.0
    assert sims[idx.freq.row_of("a")] > 0.99
