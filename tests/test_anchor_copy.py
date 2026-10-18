"""Anchors written by kuzu's bulk COPY equal those the statement form
writes (2026-10-18: the statement cost 23 ms a row; COPY 0.37 ms). A row
whose endpoint is gone falls back to the statement, which skips it -- no
partial COPY, no duplicate."""
import os
import tempfile

from domvec.graphstore import GraphStore


def _store():
    gs = GraphStore(os.path.join(tempfile.mkdtemp(), "g.kuzu"))
    for i in range(10):
        gs._execute("CREATE (:Chunk {cid: $c, url: 'u'})", {"c": "c%d" % i})
    for i in range(50):
        gs._execute("CREATE (:Address {aid: $a})", {"a": "a%d" % i})
    return gs


def _edges(gs):
    return sorted(tuple(r) for r in gs._rows("MATCH (c:Chunk)-[e:Anchors]->(a:Address) RETURN c.cid, a.aid, e.ord"))


ROWS = [{"cid": "c%d" % (i % 10), "aid": "a%d" % i, "ord": i} for i in range(50)]


def test_copy_and_statement_write_the_same_edges():
    a = _store(); a._create_anchors(ROWS)
    b = _store()
    GraphStore._PLANT_ANCHOR_MATCH[0] = True
    try:
        b._create_anchors(ROWS)
    finally:
        GraphStore._PLANT_ANCHOR_MATCH[0] = False
    assert _edges(a) == _edges(b) and len(_edges(a)) == 50


def test_a_missing_endpoint_falls_back_without_duplicates():
    gs = _store()
    gs._create_anchors(ROWS[:10] + [{"cid": "gone", "aid": "a1", "ord": 7}])
    assert len(_edges(gs)) == 10
