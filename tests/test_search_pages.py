"""Tier 1 of a tiered search (G-210): url nodes ranked by their semantic
centroid -- the normalised mean of their chunks' unit vectors. Built in the
two matrices' OPPOSITE row orders (the alignment trap of
test_semantic_row_alignment), so a centroid built from the wrong rows would
rank the wrong page first. Null arm: a query meaning page B ranks B, not A."""
import numpy as np

from vertiscope.search import ThreeFormIndex
from vertiscope.vectors import EmbeddingMatrix, FreqMatrix


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


def test_count_only_gives_the_corpus_match_count_and_reads_nothing():
    """PLUGIN_GOAL 154: the k/n fields are bounded by what MATCHES in the
    corpus. `count_only` returns no hits and reads no chunk, and its count is
    the full ranking's own `survivors` -- not the sum over the top pages."""
    from vertiscope.search import SearchDiagnostics
    chunks = [_Chunk("c%d" % i, "https://t.test/%d" % (i % 3)) for i in range(9)]
    freq = FreqMatrix()
    for i, c in enumerate(chunks):
        freq.add(c.cid, ("cowboy hat " if i % 2 == 0 else "saddle ") + c.cid)

    class _NoRead(_Store):
        def chunk(self, cid):
            raise AssertionError("count_only read a chunk")
    index = ThreeFormIndex(_NoRead(chunks), freq, None, embedder=None).build()
    d = SearchDiagnostics()
    assert index.search("cowboy", 1, diagnostics=d, count_only=True) == []
    assert d.survivors == 5, d.survivors          # the five "cowboy" chunks, across all three pages
    # null arm: a word nothing holds counts nothing
    d2 = SearchDiagnostics()
    index.search("zucchini", 1, diagnostics=d2, count_only=True)
    assert d2.survivors == 0


def test_tier_one_ranks_pages_by_what_they_hold():
    """A page close in meaning but holding no lexical match ranks NOWHERE in
    tier 1 by what it holds (tier 2 would return nothing there); the
    centroid ranking puts it first. Null arm: the centroid ranking."""
    from vertiscope.search import SearchDiagnostics
    dim = 8
    rng = np.random.default_rng(5)
    q = rng.normal(size=dim)
    chunks = [_Chunk("n0", "https://t.test/near"), _Chunk("n1", "https://t.test/near"),
              _Chunk("h0", "https://t.test/holds"), _Chunk("h1", "https://t.test/holds")]
    freq = FreqMatrix()
    freq.add("n0", "challenge page please wait")
    freq.add("n1", "verifying you are human")
    freq.add("h0", "the cowboy rode west")
    freq.add("h1", "a cowboy hat")
    emb = EmbeddingMatrix(dim=dim)
    emb.set("n0", q + 0.01 * rng.normal(size=dim)); emb.set("n1", q + 0.01 * rng.normal(size=dim))
    emb.set("h0", q + 1.2 * rng.normal(size=dim)); emb.set("h1", q + 1.2 * rng.normal(size=dim))
    index = ThreeFormIndex(_Store(chunks), freq, emb, embedder=_Embedder({"cowboy": q})).build()
    d = SearchDiagnostics()
    held = index.search_pages_matching("cowboy", 2, diagnostics=d)
    assert [u for u, _ in held] == ["https://t.test/holds"], held
    assert d.survivors == 2
    assert index.search_pages("cowboy", 2)[0][0] == "https://t.test/near"   # the defect, by centroid


def test_chunks_with_lost_markdown_are_not_one_duplicate():
    """The store lost most chunks' markdown; their lexical rows survived.
    Keyed on the stored markdown they were ALL one duplicate (a page with 457
    matches returned 1). Keyed on the index's token rows they are distinct;
    true copies still collapse. Planted: the stored-markdown key."""
    import vertiscope.search as S

    class _Lost(_Chunk):
        def __init__(self, cid, url):
            super().__init__(cid, url); self.md = ""
    chunks = [_Lost("a", "u"), _Lost("b", "u"), _Lost("c", "u"), _Lost("d", "u")]
    freq = FreqMatrix()
    freq.add("a", "the cowboy rode west"); freq.add("b", "the horse ran east")
    freq.add("c", "the cowboy rode west")          # a true copy of a
    freq.add("d", "the river")
    def run():
        return ThreeFormIndex(_Store(chunks), freq, None, embedder=None).build().search("the", 10, include_markdown=False)
    assert len(run()) == 3                          # a/c collapse; b, d stand
    S._PLANT_MD_DIGEST[0] = True
    try:
        assert len(run()) == 1                      # the defect: all one "duplicate"
    finally:
        S._PLANT_MD_DIGEST[0] = False
