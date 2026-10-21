"""The tf-idf matrix is built once per mutation batch, not per query.

It was rebuilt on every `similarities` call -- the fixed ~0.8 s of every
search (2026-10-17). Non-vacuity: a cache that survived a mutation would
answer with the old matrix, and the post-mutation scores below would not
move.
"""
import numpy as np

from vertiscope.vectors import FreqMatrix


def _fm():
    fm = FreqMatrix()
    fm.add("a", "patricia trie radix tree")
    fm.add("b", "zucchini recipe bread")
    fm.add("c", "radix sort buckets")
    return fm


def test_built_once_between_mutations():
    fm = _fm()
    assert fm.tfidf() is fm.tfidf()


def test_a_mutation_rebuilds_it():
    fm = _fm()
    before = fm.similarities("radix").copy()
    first = fm.tfidf()
    fm.add("d", "radix radix radix")
    assert fm.tfidf() is not first
    after = fm.similarities("radix")
    assert after.shape[0] == before.shape[0] + 1 and after[3] > 0
    fresh = FreqMatrix()
    for cid, text in (("a", "patricia trie radix tree"), ("b", "zucchini recipe bread"),
                      ("c", "radix sort buckets"), ("d", "radix radix radix")):
        fresh.add(cid, text)
    assert np.allclose(after, fresh.similarities("radix"))
    fm.remove("d")
    cached = fm.similarities("radix")
    fm._tfidf = None                      # the same matrix, built afresh
    assert np.allclose(cached, fm.similarities("radix"))
    assert cached[3] == 0                 # the removed row matches nothing
