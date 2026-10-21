"""A buffer-pool refusal poisons the connection (2026-10-18).

The working store's sidecar died ~50 times in an hour: a `COPY Anchors FROM df`
was refused with "Buffer manager exception: Unable to allocate memory! The
buffer pool is full and no memory could be freed!", and the fallback
statement that followed it on the same connection segfaulted kuzu -- found by
dumping every statement of the replayed capture (`VERTISCOPE_DUMP_ROWS=1`). Now
the refusal marks the store poisoned, nothing further runs on it, and the
sidecar restarts the process (`_poison_watch`). Anchors use the statement
form by default; COPY is opt-in (`VERTISCOPE_ANCHOR_COPY=1`).
"""
import os
import tempfile

import pytest

from vertiscope.graphstore import GraphStore, StorePoisoned


class _Refusing:
    """A connection whose next statement is refused like a full buffer pool."""
    def __init__(self, real):
        self.real, self.armed = real, True
    def execute(self, q, p=None):
        if self.armed:
            self.armed = False
            raise RuntimeError("Buffer manager exception: Unable to allocate memory! "
                               "The buffer pool is full and no memory could be freed!")
        return self.real.execute(q, p or {})


def _store():
    return GraphStore(os.path.join(tempfile.mkdtemp(), "g.kuzu"))


def test_a_refused_pool_poisons_and_nothing_further_runs():
    gs = _store()
    gs.conn = _Refusing(gs.conn)
    with pytest.raises(RuntimeError):
        gs._execute("CREATE (:Chunk {cid: 'a', url: 'u'})")
    assert gs.poisoned.startswith("RuntimeError: Buffer manager exception")
    # The very next statement -- the one that segfaulted -- never reaches kuzu.
    with pytest.raises(StorePoisoned):
        gs._execute("CREATE (:Chunk {cid: 'b', url: 'u'})")
    with pytest.raises(StorePoisoned):
        gs._rows("MATCH (c:Chunk) RETURN count(c)")


def test_planted_no_poison_runs_the_next_statement():
    GraphStore._PLANT_NO_POISON[0] = True
    try:
        gs = _store()
        gs.conn = _Refusing(gs.conn)
        with pytest.raises(RuntimeError):
            gs._execute("CREATE (:Chunk {cid: 'a', url: 'u'})")
        assert gs.poisoned == ""
        gs._execute("CREATE (:Chunk {cid: 'b', url: 'u'})")      # what crashed the sidecar
    finally:
        GraphStore._PLANT_NO_POISON[0] = False


def test_an_ordinary_error_does_not_poison():
    gs = _store()
    with pytest.raises(RuntimeError):
        gs._execute("MATCH (x:NoSuchTable) RETURN x")
    assert gs.poisoned == ""
    gs._execute("CREATE (:Chunk {cid: 'c', url: 'u'})")


def test_anchor_copy_is_opt_in():
    assert GraphStore._ANCHOR_COPY[0] is (os.environ.get("VERTISCOPE_ANCHOR_COPY") == "1")
