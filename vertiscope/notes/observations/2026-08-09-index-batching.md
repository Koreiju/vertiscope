# OBSERVATION — index insertion is sensitive to batching

**Date** 2026-08-09 · **Bears on** PROP-14.3 · **Raised** MODEL O-1

## What was measured

Whether the concrete index's `df` is the homomorphism out of the free
commutative monoid on documents that PROP-14.3 describes. A homomorphism out of
a free *commutative* monoid is insensitive to the order and the grouping of its
generators, so indexing the same two documents in one call and in two calls must
give the same result.

## Method

```python
from vertiscope.core.global_tfidf_store import GlobalTfidfStore, ChunkMeta
T = "shared navigation home about contact"
def mk(cid, url):
    return ChunkMeta(chunk_id=cid, url=url, snapshot_id="s", text_preview=T[:80])

s1 = GlobalTfidfStore(tempfile.mkdtemp())
s1.add_chunks([T, T], [mk("a", "u/1"), mk("b", "u/2")])      # one batch

s2 = GlobalTfidfStore(tempfile.mkdtemp())
s2.add_chunks([T], [mk("a", "u/1")])                          # two batches
s2.add_chunks([T], [mk("b", "u/2")])
```

## Result

```
ONE batch,  two identical texts  ->  doc_count = 1   urls = ['u/1']
TWO batches, two identical texts ->  doc_count = 2   urls = ['u/1']

_content_to_row populated: 1 entry  (maintained on write, never consulted
                                     for the cross-call merge decision)
```

A separate run over three documents — two identical, one distinct — gave
`doc_count = 3` and `df('navigation') = 2`, i.e. the two-batch path agrees with
the abstract definition while the one-batch path does not.

## Reading

The images under $\alpha$ differ, so insertion is not a homomorphism out of the
free commutative monoid. Grouping is observable.

Mechanism, located in `add_chunks`: within a single call, candidates are
deduplicated against a batch-local digest map; across calls, dispatch is on
`chunk_id` via the identifier-to-row map, and the persistent digest-to-row map
is written on every insertion but never read for that decision. The module's own
documentation describes cross-corpus content deduplication as case 2 of the
insertion path; what is realised is batch-local deduplication only.

Because `df` depends on grouping, so does `idf`, so does every score. Two runs
indexing identical content with different batch sizes rank differently.

## Caveats

- Synthetic inputs, not a frozen corpus; the effect is structural rather than
  corpus-dependent, but the magnitude on real pages is unmeasured.
- Only the index was probed. Whether the record store shows a corresponding
  sensitivity is untested.
- No claim is made here about which behaviour is *desirable*. The observation is
  that the concrete behaviour and PROP-14.3 disagree, and that the disagreement
  is grouping-sensitivity.
