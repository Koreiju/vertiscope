"""G-218: the store compacts itself when it has outgrown its last compaction.

Writing a vector into an existing row grows a kuzu file by 4-5.5x the vector
(33x on the working store) and nothing gives the pages back, so the sidecar
asks its supervisor (exit 76) to rebuild the store by EXPORT/IMPORT once it is
3x its last compacted size and the reader has been away 10 minutes.
"""
import json
import sys

import kuzu
import numpy as np

from vertiscope.obsidian import compact as C
from vertiscope.obsidian import sidecar
from vertiscope.obsidian import supervise as S


def _bloated(ws, n=2048):
    db = kuzu.Database(str(ws / "graph.kuzu")); c = kuzu.Connection(db)
    c.execute("CREATE NODE TABLE Chunk(cid STRING, embedding DOUBLE[], PRIMARY KEY (cid))")
    c.execute("UNWIND range(0, %d) AS i CREATE (:Chunk {cid: 'c' + string(i)})" % (n - 1))
    v = np.random.default_rng(0).standard_normal((n, 768))
    for rnd in range(3):                       # the embedder writing into existing rows
        for i in range(0, n, 64):
            c.execute("UNWIND $rows AS r MATCH (c:Chunk {cid: r.cid}) SET c.embedding = r.e",
                      {"rows": [{"cid": "c%d" % j, "e": (v[j] + rnd).tolist()} for j in range(i, min(n, i + 64))]})
        c.execute("CHECKPOINT")
    del c, db


def test_a_bloated_store_compacts_smaller_with_every_count_kept(tmp_path):
    _bloated(tmp_path)
    before = (tmp_path / "graph.kuzu").stat().st_size
    got = C.compact(tmp_path, log=lambda *_: None)
    assert got["swapped"] and got["counts_before"] == got["counts_after"] == {"Chunk": 2048}
    assert (tmp_path / "graph.kuzu").stat().st_size < before / 2
    assert (tmp_path / C.AUTO_KEEP).exists()
    assert json.loads((tmp_path / C.MARK).read_text())["after_mb"] == got["after_mb"]
    # A second compaction replaces the kept file: ONE is ever kept.
    C.compact(tmp_path, log=lambda *_: None)
    assert len(list(tmp_path.glob("graph.kuzu.prev-auto*"))) == 1


def test_counts_that_differ_swap_nothing(tmp_path, monkeypatch):
    _bloated(tmp_path, n=256)
    before = (tmp_path / "graph.kuzu").stat().st_size
    seq = iter([{"Chunk": 256}, {"Chunk": 255}])
    monkeypatch.setattr(C, "counts", lambda conn: next(seq))
    got = C.compact(tmp_path, log=lambda *_: None)
    assert not got["swapped"] and got["why_not"] == "counts differ"
    assert (tmp_path / "graph.kuzu").stat().st_size == before
    assert not (tmp_path / C.AUTO_KEEP).exists()


def test_the_supervisor_compacts_on_76_and_starts_again(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(C, "compact", lambda ws, **k: called.append(ws) or {"before_mb": 9, "after_mb": 1, "swapped": True})
    flag = tmp_path / "once"
    child = [sys.executable, "-c",
             "import os,sys; p=r'%s'; sys.exit(0 if os.path.exists(p) else (open(p,'w').close() or 76))" % flag]
    assert S.supervise(tmp_path, [], command=child, pause=0) == 0
    assert called == [tmp_path]
    rec = json.loads((tmp_path / "store_growth.log").read_text().splitlines()[-1])
    assert rec["compacted"]["swapped"] is True


def test_due_only_when_outgrown_quiet_and_supervised():
    due = sidecar._compact_due
    assert due(4600, 1440, now=1000, last_request=0, supervised=True)
    assert not due(4600, 1440, now=1000, last_request=900, supervised=True)    # reader active
    assert not due(2800, 1440, now=1000, last_request=0, supervised=True)      # not 2x yet
    assert not due(4600, 1440, now=1000, last_request=0, supervised=False)     # nobody to act on 76
    assert not due(1200, 300, now=1000, last_request=0, supervised=True)       # under the floor
    sidecar._PLANT_NO_AUTOCOMPACT[0] = True
    try:
        assert not due(46000, 1440, now=1000, last_request=0, supervised=True)
    finally:
        sidecar._PLANT_NO_AUTOCOMPACT[0] = False


def test_due_when_the_plugin_reports_the_reader_idle_though_requests_continue():
    """The app's polling never left the sidecar request-quiet, so compaction
    never ran (1.6 -> 8.8 GB, 2026-10-18). The plugin's report of the reader
    idle in Obsidian counts as away -- if nothing was captured for two
    minutes. Planted `_PLANT_REQUEST_QUIET_ONLY`: the request clock alone."""
    due = sidecar._compact_due
    busy = dict(now=10000, last_request=9999, supervised=True)
    assert due(4600, 1440, reader_idle_s=900, last_write=9000, **busy)            # idle reader, no capture for 1000 s
    assert not due(4600, 1440, reader_idle_s=900, last_write=9950, **busy)        # a capture 50 s ago
    assert not due(4600, 1440, reader_idle_s=60, last_write=0, **busy)            # the reader is here
    assert not due(4600, 1440, reader_idle_s=0, last_write=0, **busy)             # no report
    sidecar._PLANT_REQUEST_QUIET_ONLY[0] = True
    try:
        assert not due(4600, 1440, reader_idle_s=900, last_write=9000, **busy)
    finally:
        sidecar._PLANT_REQUEST_QUIET_ONLY[0] = False
