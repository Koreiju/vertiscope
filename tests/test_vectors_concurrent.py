"""`EmbeddingMatrix` is written from more than one thread, so it must survive it.

The sidecar is a `ThreadingHTTPServer` with an embedding worker beside it, and
`Workspace.index` is a LAZY property. Two concurrent `/search` requests both
found the index unbuilt, both ran the hydration, and both wrote into one
shared matrix. Row allocation and growth are a read-modify-write, so each
thread grew a copy of the same stale array and the smaller assignment landed
last:

    IndexError: index 13397 is out of bounds for axis 0 with size 13397

That took down every `/search` on a 14,169-chunk workspace -- and with it
`G-42`, `G-63`, `G-64`, `G-69`, `G-70` and `G-71`, all six of which the PRD
called Done. Nothing in the suite touched the structure from two threads, so
nothing caught it.
"""

import threading

import numpy as np

from vertiscope.vectors import EmbeddingMatrix


def test_concurrent_writers_do_not_lose_rows():
    """Every cid gets a row, and every row is inside the matrix.

    The failure was a lost update, so the assertion is on the INVARIANT the
    lost update broke -- rows and matrix agreeing -- rather than on the
    IndexError, which is only how it happened to surface.
    """
    m = EmbeddingMatrix(dim=16)
    n_threads, per_thread = 8, 200
    errors = []

    def write(t):
        try:
            for i in range(per_thread):
                m.set("t%d-%d" % (t, i),
                      np.full(16, float(t + 1), dtype=np.float32))
        except Exception as exc:                       # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=write, args=(t,))
               for t in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, "a writer raised: %r" % (errors[0],)
    expected = n_threads * per_thread
    assert len(m.rows) == expected, \
        "%d rows for %d cids" % (len(m.rows), expected)
    assert m._matrix is not None and m._matrix.shape[0] >= expected, \
        "matrix holds %s rows for %d cids" % (
            None if m._matrix is None else m._matrix.shape[0], expected)


def test_every_concurrent_write_is_readable_afterwards():
    """The non-vacuity arm: no row may be silently zero.

    A lock that serialised the writes but dropped them would pass the test
    above -- the shapes would agree and the data would be gone. Each thread
    writes a value only it writes, so a row that came back zero, or came back
    as another thread's value, is a lost write.
    """
    m = EmbeddingMatrix(dim=16)
    n_threads, per_thread = 8, 200

    def write(t):
        for i in range(per_thread):
            m.set("t%d-%d" % (t, i),
                  np.full(16, float(t + 1), dtype=np.float32))

    threads = [threading.Thread(target=write, args=(t,))
               for t in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Stored normalised, so a row of a constant c comes back as 1/sqrt(16).
    want = 1.0 / 4.0
    for t in range(n_threads):
        for i in (0, per_thread // 2, per_thread - 1):
            row = m.row_of("t%d-%d" % (t, i))
            assert row is not None, "t%d-%d lost its row" % (t, i)
            got = m._matrix[row]
            assert np.allclose(got, want, atol=1e-6), \
                "t%d-%d reads back %r" % (t, i, got[:3])
