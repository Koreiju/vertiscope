"""The term matrix is rebuilt from the rows that changed, not from all of them.

2026-11-15: every mutation of the frequency matrix dropped its CSR, and the
next read rebuilt it in a Python loop over every count of every row -- the
4.7 s the first lexical snapshot held after a restart, and a cost the next
search paid after any write, one ego note's save included. `_matrix` now
splices the changed rows into the last CSR built. Planted
`PLANT_FULL_CSR_REBUILD`: the whole rebuild, as before.
"""

import random
import time

import numpy as np

from domvec import vectors
from domvec.vectors import FreqMatrix

WORDS = [f"w{i}" for i in range(400)]


def _text(rng, n=12):
    return " ".join(rng.choice(WORDS) for _ in range(n))


def _whole(m):
    """The same counts built whole, for comparison."""
    vectors.PLANT_FULL_CSR_REBUILD[0] = True
    try:
        m._csr = None
        m._base, m._dirty = None, set()
        return m._matrix().copy()
    finally:
        vectors.PLANT_FULL_CSR_REBUILD[0] = False


def _same(a, b):
    assert a.shape == b.shape
    assert np.array_equal(a.indptr, b.indptr)
    assert np.array_equal(a.indices, b.indices)
    assert np.array_equal(a.data, b.data)


def test_a_splice_equals_a_whole_build_through_adds_removes_and_reuse():
    rng = random.Random(7)
    m = FreqMatrix()
    for i in range(300):
        m.add(f"c{i}", _text(rng))
    m._matrix()                                  # the base
    for step in range(200):
        op = rng.random()
        cid = f"c{rng.randrange(400)}"
        if op < 0.5:
            m.add(cid, _text(rng, rng.randrange(0, 20)))     # replace, or a new row
        elif op < 0.8:
            m.remove(cid)                                   # tombstone
        else:
            m.add(f"new{step}", _text(rng) + f" fresh{step}")   # a new column too
        if step % 7 == 0:
            got = m._matrix().copy()
            _same(got, _whole(m))
    assert m.csr_builds["spliced"] > 20
    _same(m._matrix().copy(), _whole(m))


def test_a_loaded_matrix_splices_too(tmp_path):
    rng = random.Random(3)
    m = FreqMatrix()
    for i in range(50):
        m.add(f"c{i}", _text(rng))
    m.save(tmp_path / "freq")
    back = FreqMatrix.load(tmp_path / "freq")
    back.add("c3", "an entirely different text")
    back.add("late", "a row past the end")
    got = back._matrix().copy()
    assert back.csr_builds == {"whole": 0, "spliced": 1, "rows_spliced": 2}
    _same(got, _whole(back))


def test_forgetting_vocabulary_rebuilds_whole():
    m = FreqMatrix()
    m.add("a", "alpha beta")
    m.add("b", "gamma delta")
    m._matrix()
    m.remove("b")
    m.forget_vocabulary()                        # columns renumbered: whole
    before = m.csr_builds["whole"]
    m._matrix()
    assert m.csr_builds["whole"] == before + 1


def _one_write_then_read(planted, rows=20000):
    rng = random.Random(11)
    m = FreqMatrix()
    for i in range(rows):
        m.add(f"c{i}", _text(rng, 40))
    m._matrix()
    vectors.PLANT_FULL_CSR_REBUILD[0] = planted
    try:
        m.add("c17", "one chunk's text changed, as a note's save does")
        t0 = time.perf_counter()
        m._matrix()
        return (time.perf_counter() - t0) * 1000
    finally:
        vectors.PLANT_FULL_CSR_REBUILD[0] = False


def test_one_write_costs_a_splice_not_a_rebuild():
    spliced = _one_write_then_read(False)
    whole = _one_write_then_read(True)
    print(f"read after one write, 20k rows: spliced {spliced:.1f} ms, whole {whole:.1f} ms")
    assert spliced * 3 < whole
