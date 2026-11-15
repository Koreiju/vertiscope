"""A lexical save holds the matrix's lock for the snapshot only.

2026-11-15, the search field: concurrent search calls stalled together for
7-16 s, and the sidecar's `/profile` ring showed `lexical_save` taking 16.3,
11.2 and 10.0 s in exactly that window. The save held `_WORK_LOCK` and the
matrix's own lock -- which every search's `similarities` takes -- across
compressing 25.7 MB of npz and dumping 53.9 MB of JSON. Now only a snapshot is
taken under the lock and the write happens outside it. Planted
`PLANT_LEXICAL_SAVE_LOCKED`: the whole save under the lock, as before.
"""

import threading
import time

import numpy as np

from domvec import vectors
from domvec.vectors import FreqMatrix

WRITE_S = 0.6


def _matrix():
    m = FreqMatrix()
    for i in range(40):
        m.add(f"c{i}", f"alpha beta gamma word{i} shared text number {i}")
    m.remove("c3")                       # a tombstone and a free row to persist
    return m


def _search_wait_during_save(tmp_path, monkeypatch, planted):
    """Seconds a search waited while a save was writing."""
    m = _matrix()
    real = FreqMatrix._write
    writing = threading.Event()

    def slow(path, snap):
        writing.set()
        time.sleep(WRITE_S)              # stands in for 10-16 s of compression
        real(path, snap)

    monkeypatch.setattr(FreqMatrix, "_write", staticmethod(slow))
    vectors.PLANT_LEXICAL_SAVE_LOCKED[0] = planted
    try:
        t = threading.Thread(target=m.save, args=(tmp_path / "freq",))
        t.start()
        assert writing.wait(5)
        started = time.perf_counter()
        sims = m.similarities("alpha word7")
        waited = time.perf_counter() - started
        t.join()
    finally:
        vectors.PLANT_LEXICAL_SAVE_LOCKED[0] = False
    assert sims.shape[0] == len(m.rows)
    return waited


def test_a_search_does_not_wait_for_the_write(tmp_path, monkeypatch):
    waited = _search_wait_during_save(tmp_path, monkeypatch, planted=False)
    print(f"search during save: waited {waited * 1000:.0f} ms")
    assert waited < WRITE_S / 3


def test_planted_the_search_waits_for_the_whole_write(tmp_path, monkeypatch):
    waited = _search_wait_during_save(tmp_path, monkeypatch, planted=True)
    print(f"search during planted save: waited {waited * 1000:.0f} ms")
    assert waited > WRITE_S * 0.6


def test_the_saved_files_round_trip(tmp_path):
    m = _matrix()
    m.save(tmp_path / "freq")
    back = FreqMatrix.load(tmp_path / "freq")
    assert back.vocab == m.vocab and back.rows == m.rows and back._free == m._free
    a, b = m._matrix(), back._matrix()
    assert a.shape == b.shape
    assert np.array_equal(a.toarray(), b.toarray())


def test_a_snapshot_is_the_state_it_was_taken_at(tmp_path):
    m = _matrix()
    snap = m.snapshot()
    m.add("late", "a row added after the snapshot was taken")
    assert m.write_snapshot(tmp_path / "freq", snap)
    back = FreqMatrix.load(tmp_path / "freq")
    assert "late" not in back.rows
    assert back._matrix().shape == tuple(snap["shape"])


def test_an_older_snapshot_never_lands_over_a_newer_one(tmp_path):
    m = _matrix()
    old = m.snapshot()
    m.add("newer", "the newer state of the matrix")
    assert m.write_snapshot(tmp_path / "freq", m.snapshot())
    assert not m.write_snapshot(tmp_path / "freq", old)     # refused
    assert "newer" in FreqMatrix.load(tmp_path / "freq").rows
