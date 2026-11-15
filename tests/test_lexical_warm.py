"""tf-idf is rebuilt in the background once the matrix is quiet.

2026-11-15, live at full speed: tier 1's lexical phase read 0.78-0.94 s for
the first search after a capture (the rebuild) and 20 ms at rest. The embed
worker's idle loop now rebuilds it once the matrix has been unchanged for a
moment. Planted `PLANT_NO_LEXICAL_WARM`: the search pays, as before.
"""
import time

import domvec.obsidian.sidecar as sc
from domvec.vectors import FreqMatrix


class _WS:
    def __init__(self):
        self.freq = FreqMatrix()
        for i in range(50):
            self.freq.add(f"c{i}", f"alpha beta word{i}")


def _settle(ws, planted):
    sc.PLANT_NO_LEXICAL_WARM[0] = planted
    sc._LEX_WARM.update(version=None, since=0.0)
    try:
        ws.freq.add("late", "a write the search would otherwise pay for")
        assert ws.freq._tfidf is None
        first = sc._warm_lexical(ws, quiet_s=0.05)     # sees the new version
        time.sleep(0.08)
        second = sc._warm_lexical(ws, quiet_s=0.05)    # quiet: warms
        return first, second, ws.freq._tfidf is not None
    finally:
        sc.PLANT_NO_LEXICAL_WARM[0] = False


def test_a_quiet_matrix_is_warmed_before_any_search():
    first, second, built = _settle(_WS(), False)
    assert (first, second, built) == (False, True, True)


def test_a_matrix_still_changing_is_left_alone():
    ws = _WS()
    sc._LEX_WARM.update(version=None, since=0.0)
    sc._warm_lexical(ws, quiet_s=0.05)
    time.sleep(0.08)
    ws.freq.add("another", "a write between the two looks")
    assert sc._warm_lexical(ws, quiet_s=0.05) is False and ws.freq._tfidf is None


def test_planted_the_search_pays():
    first, second, built = _settle(_WS(), True)
    assert (first, second, built) == (False, False, False)
