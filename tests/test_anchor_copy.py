"""Anchors written by kuzu's bulk COPY equal those the statement form
writes (2026-10-18: the statement cost 23 ms a row; COPY 0.37 ms). A row
whose endpoint is gone falls back to the statement, which skips it -- no
partial COPY, no duplicate."""
import os
import tempfile

from vertiscope.graphstore import GraphStore


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


def _copy(gs, rows):
    """The opt-in COPY arm (`VERTISCOPE_ANCHOR_COPY=1`; off by default --
    `graphstore._ANCHOR_COPY` says why)."""
    was = GraphStore._ANCHOR_COPY[0]
    GraphStore._ANCHOR_COPY[0] = True
    try:
        gs._create_anchors(rows)
    finally:
        GraphStore._ANCHOR_COPY[0] = was


def test_copy_and_statement_write_the_same_edges():
    a = _store(); _copy(a, ROWS)
    b = _store()
    GraphStore._PLANT_ANCHOR_MATCH[0] = True
    try:
        b._create_anchors(ROWS)
    finally:
        GraphStore._PLANT_ANCHOR_MATCH[0] = False
    assert _edges(a) == _edges(b) and len(_edges(a)) == 50


def test_a_missing_endpoint_falls_back_without_duplicates():
    gs = _store()
    _copy(gs, ROWS[:10] + [{"cid": "gone", "aid": "a1", "ord": 7}])
    assert len(_edges(gs)) == 10


def test_copy_holds_the_readers_lock_while_it_commits():
    """COPY into a populated rel table checkpoints at its commit, and a
    checkpoint waits for the reader connection's transactions: unlocked, 3 of
    30 capture-sized COPYs on a 4.3 GB store timed out (2026-10-18). The lock
    is held for the statement. Planted `_PLANT_COPY_NO_READ_LOCK`: not held."""
    seen = {}
    for planted in (False, True):
        gs = _store()
        if gs._read_conn is None:
            import pytest
            pytest.skip("shared reads: no reader connection to lock out")
        real = gs.conn.execute

        def spy(q, *a, _real=real, _gs=gs, **k):
            if str(q).startswith("COPY Anchors"):
                seen[planted] = _gs._read_lock.locked()
            return _real(q, *a, **k)

        gs.conn.execute = spy
        GraphStore._PLANT_COPY_NO_READ_LOCK[0] = planted
        try:
            _copy(gs, ROWS[:20])
        finally:
            GraphStore._PLANT_COPY_NO_READ_LOCK[0] = False
            gs.conn.execute = real
    assert seen == {False: True, True: False}, seen
