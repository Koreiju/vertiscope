"""The lexical matrix under a write and searches at once (2026-10-18: a
search's tf-idf built while a capture added vocabulary raised "inconsistent
shapes" and the request died). Locked: no error. Planted (unlocked): the
race is reproduced -- the check can fail."""
import threading
import time

import vertiscope.vectors as V
from vertiscope.vectors import FreqMatrix


def _stress(seconds=3.0):
    f = FreqMatrix()
    for i in range(3000):
        f.add("c%d" % i, "word%d common term%d" % (i, i % 50))
    stop = [False]
    errs = []

    def writer():
        i = 3000
        while not stop[0]:
            f.add("c%d" % i, "new%d fresh%d common" % (i, i))
            i += 1

    def reader():
        while not stop[0]:
            try:
                f.similarities("common term3")
            except Exception as exc:                 # noqa: BLE001
                errs.append(repr(exc))
    ts = [threading.Thread(target=writer)] + [threading.Thread(target=reader) for _ in range(3)]
    for t in ts:
        t.start()
    time.sleep(seconds)
    stop[0] = True
    for t in ts:
        t.join()
    return errs


def test_searches_during_writes_never_see_two_moments():
    assert _stress() == []


def test_planted_unlocked_matrix_races():
    V._PLANT_NO_LOCK[0] = True
    try:
        assert _stress(), "the unlocked matrix raised nothing: this check cannot fail"
    finally:
        V._PLANT_NO_LOCK[0] = False
