"""Containment written without a relationship MERGE per pair.

discourse's /latest, 2026-10-24: one list chunk is the parent of every topic,
and `MERGE (a)-[:Contains]->(b)` scanned the parent's edges once per pair --
a settle of 364 chunks held the write lock and the interpreter ~100 s. The
parents' edges are read once and only the missing ones created. The
postcondition is MERGE's: one edge per (parent, child), however often the
page is written. Planted `PLANT_MERGE_CONTAINS`: the MERGE, which must give
the same edges.
"""

import time

from domvec import graphstore
from domvec.address import ContentAddress
from domvec.graphstore import GraphStore
from domvec.markdown import MarkdownChunk, MarkdownLine

URL = "https://example.org/feed"


def _feed(n):
    """A list chunk with `n` topic chunks rooted below it."""
    def chunk(xpath, text):
        a = ContentAddress(url=URL, xpath=xpath + "/text()[1]", tag="text.p", accessor="text")
        return MarkdownChunk(url=URL, xpath=xpath, lines=[MarkdownLine(depth=0, text=text, address=a)]), a
    out = [chunk("/html/body/main", "Latest topics")]
    out += [chunk("/html/body/main/div[%d]" % (i + 1), "Topic number %d about tries" % i) for i in range(n)]
    return [c for c, _a in out], [(a, c.lines[0].text, "") for c, a in out]


def _edges(store):
    return sorted((a, b) for a, b in store._rows(
        "MATCH (a:Chunk {url: $u})-[:Contains]->(b:Chunk) RETURN a.cid, b.cid", {"u": URL}))


def _write_twice(tmp_path, name, n):
    store = GraphStore(tmp_path / name)
    chunks, addrs = _feed(n)
    t0 = time.perf_counter()
    store.ingest(URL, addrs, chunks, complete=False)
    # The same page again, and a write that adds one topic: no edge doubles.
    store.ingest(URL, addrs, chunks, complete=False)
    more, more_addrs = _feed(n + 1)
    store.ingest(URL, more_addrs, more, complete=False)
    ms = (time.perf_counter() - t0) * 1000
    return _edges(store), ms


def test_one_edge_per_pair_however_often_written(tmp_path):
    edges, _ms = _write_twice(tmp_path, "g.kuzu", 300)
    assert len(edges) == 301
    assert len(set(edges)) == len(edges)
    assert len({a for a, _b in edges}) == 1          # every topic under the list


def test_planted_merge_writes_the_same_edges(tmp_path):
    fast, fast_ms = _write_twice(tmp_path, "a.kuzu", 300)
    graphstore.PLANT_MERGE_CONTAINS[0] = True
    try:
        slow, slow_ms = _write_twice(tmp_path, "b.kuzu", 300)
    finally:
        graphstore.PLANT_MERGE_CONTAINS[0] = False
    assert fast == slow
    print("contains write: read-then-create %.0f ms, MERGE %.0f ms" % (fast_ms, slow_ms))


def test_the_cheaper_path_as_measured(tmp_path):
    """A COPY costs the checkpoint it forces; under it, statements win.

    6.5 s for 240 edges by COPY on the live store against ~10 ms an edge by
    statement (2026-10-24). With a COPY measured at 5 s, a 240-edge write
    goes by statement and a 1,000-edge one by COPY; planted
    `PLANT_ALWAYS_COPY`, both by COPY.
    """
    store = GraphStore(tmp_path / "c.kuzu")
    store._rel_cost["copy_ms"] = 5000.0
    assert not store._bulk_cheaper("Contains", 240)
    assert store._bulk_cheaper("Contains", 1000)
    assert not store._bulk_cheaper("Anchors", 200)        # 23 ms a row: 4.6 s < 5 s
    assert store._bulk_cheaper("Anchors", 300)
    GraphStore.PLANT_ALWAYS_COPY[0] = True
    try:
        assert store._bulk_cheaper("Contains", 240)
    finally:
        GraphStore.PLANT_ALWAYS_COPY[0] = False
    # And the write says which it took, and what it measured.
    chunks, addrs = _feed(240)
    store.ingest(URL, addrs, chunks, complete=False)
    assert store.last_contains["by"] == "statement"
    assert store.last_contains["new"] == 240
    assert store._rel_cost["row_ms"]["Contains"] > 0
