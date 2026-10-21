"""Reads answer while a write holds the store (2026-10-10: "retrieval breakdown
during a scan over a large page"). A capture holds the statement lock for as
long as a statement runs -- 77.9 s of anchors on legislation.gov.uk -- and every
search on the one shared connection waited it out.

A thread holds the store's statement lock for 2 s, standing in for that write;
a read must come back well inside it. The planted arm (VERTISCOPE_SHARED_READS=1,
the old single connection) must wait for the release."""

import threading
import time

from vertiscope.workspace import Workspace

HTML = "<html><body><h1>Title</h1>" + "".join(
    "<p>para %d with enough words to chunk</p>" % i for i in range(40)) + "</body></html>"


def _read_while_held(tmp_path, monkeypatch, shared: bool) -> float:
    if shared:
        monkeypatch.setenv("VERTISCOPE_SHARED_READS", "1")
    else:
        monkeypatch.delenv("VERTISCOPE_SHARED_READS", raising=False)
    with Workspace(tmp_path) as ws:
        ws.index_html(HTML, "http://a.test/p")
        store = ws.store
        held = threading.Event()

        def writer():
            with store._db_lock:
                held.set()
                time.sleep(2.0)

        t = threading.Thread(target=writer)
        t.start()
        held.wait(5)
        t0 = time.perf_counter()
        rows = store._rows("MATCH (c:Chunk) RETURN count(c)")
        waited = time.perf_counter() - t0
        t.join()
        assert rows and rows[0][0] > 0
        return waited


def test_a_read_answers_while_a_write_holds_the_store(tmp_path, monkeypatch):
    assert _read_while_held(tmp_path, monkeypatch, shared=False) < 0.5


def test_planted_shared_connection_waits_for_the_write(tmp_path, monkeypatch):
    assert _read_while_held(tmp_path, monkeypatch, shared=True) > 1.5


def test_writes_still_go_through_the_writer(tmp_path, monkeypatch):
    from vertiscope.graphstore import GraphStore
    w = GraphStore._WRITES
    # Every write keyword routes to the writer's connection; plain reads do not.
    for q in ("MATCH (c:Chunk) SET c.part = 1", "MERGE (p:Page {url: $u})", "CHECKPOINT",
              "MATCH (a) DETACH DELETE a", "CALL auto_checkpoint=false", "CREATE (c:Chunk {cid: 'x'})"):
        assert w.search(q), q
    for q in ("MATCH (c:Chunk) RETURN count(c)", "MATCH (a:Address {url: $u}) RETURN a.akey ORDER BY a.akey"):
        assert not w.search(q), q
    monkeypatch.delenv("VERTISCOPE_SHARED_READS", raising=False)
    with Workspace(tmp_path) as ws:
        ws.index_html(HTML, "http://a.test/p")
        before = ws.store.read_stats["split"]
        assert ws.store._rows("MATCH (c:Chunk) RETURN c.cid LIMIT 1")
        assert ws.store.read_stats["split"] >= before + 1
        assert ws.store.read_stats["fallback"] == 0
        assert ws.store.checkpoint() >= 0
