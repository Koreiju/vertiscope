"""The search index takes a capture's DELTA instead of a rebuild per search
(2026-10-18, PLUGIN_GOAL 152): a chunk written after the build is found, a
retired one is not, a new row is not vetoed by a zero PageRank, and the
result equals a full rebuild's. Null arm: without the delta the index does
not know the new chunk."""
from vertiscope.search import ThreeFormIndex
from vertiscope.vectors import FreqMatrix


class _C:
    def __init__(self, cid, url, md):
        self.cid, self.url, self.xpath, self.md = cid, url, "/html/body/p", md


class _Store:
    def __init__(self, chunks):
        self.by = {c.cid: c for c in chunks}

    def edges(self):
        return []

    def chunks(self):
        return list(self.by.values())

    def chunk(self, cid):
        return self.by.get(cid)


def _setup():
    store = _Store([_C("a", "u1", "cowboy hat"), _C("b", "u1", "saddle horn")])
    freq = FreqMatrix()
    for c in store.chunks():
        freq.add(c.cid, c.md)
    return store, freq


def test_a_written_chunk_is_found_and_a_retired_one_is_not():
    store, freq = _setup()
    index = ThreeFormIndex(store, freq).build()
    store.by["c"] = _C("c", "u2", "cowboy boots")
    freq.add("c", "cowboy boots")
    assert {h.cid for h in index.search("cowboy", 10, include_markdown=False)} == {"a"}   # null arm: stale
    index.apply_delta(["c"])
    assert {h.cid for h in index.search("cowboy", 10, include_markdown=False)} == {"a", "c"}
    # retire a
    del store.by["a"]; freq.remove("a")
    index.apply_delta(["a"])
    got = {h.cid for h in index.search("cowboy", 10, include_markdown=False)}
    assert got == {"c"}
    fresh = ThreeFormIndex(store, freq).build()
    assert got == {h.cid for h in fresh.search("cowboy", 10, include_markdown=False)}


def test_a_reused_row_takes_its_new_chunk():
    store, freq = _setup()
    index = ThreeFormIndex(store, freq).build()
    del store.by["b"]; freq.remove("b")
    store.by["d"] = _C("d", "u3", "saddle soap")
    freq.add("d", "saddle soap")                # takes b's freed row
    index.apply_delta(["b", "d"])
    assert [h.cid for h in index.search("saddle", 10, include_markdown=False)] == ["d"]
