# The Anchors write, and why COPY is not the fix

## What the statement costs

`GraphStore.ingest` writes chunk-to-address edges with

    UNWIND $rows AS r
    MATCH (c:Chunk {cid: r.cid}), (a:Address {aid: r.aid})
    MERGE (c)-[e:Anchors]->(a) SET e.ord = r.ord

It carries **84.5% of the ingest degradation**: 0.92s -> 36.09s, x39.4,
between a 40-page and a 400-page store, with the statement count flat at
128 -> 129 per batch.

`cid` and `aid` ARE the declared primary keys. The planner still does not
turn a per-row `UNWIND` variable into an index lookup: `EXPLAIN` at 400 pages
shows SCAN_NODE_TABLE over Address (219,144 rows) and Chunk, CROSS_PRODUCT,
and SCAN_REL_TABLE over Anchors. Cost is ~22 ms per ROW at that size, and the
per-row cost grows with the store.

## Five things that are not the fix, each measured

Timed on a real 400-page store, 2,000 rows, every variant doing identical
work on edges that already exist:

| variant | time |
|---|---|
| current, comma MATCH | 31.68s |
| two MATCH clauses | 28.45s |
| endpoints via WHERE | 44.04s |
| MATCH the edge, SET only (no MERGE) | 57.09s |

The last is the informative one: **dropping MERGE entirely is slower**, so
MERGE was never the cost -- resolving the endpoints is. Rewriting this
statement does not help and is not worth trying again.

Batching is not the fix either. Cost is per ROW, not per statement:

    10 rows    0.82s   81.7 ms/row
    100 rows   2.57s   25.7 ms/row
    1000 rows 21.65s   21.7 ms/row
    4000 rows 87.92s   22.0 ms/row

Flat once the ~0.6s per-statement overhead amortises, so bigger statements
buy nothing.

## COPY is 109x faster and CRASHES KUZU

    COPY Anchors FROM (LOAD FROM $dataframe ...)   0.22s / 2,000 rows
    COPY Anchors FROM 'temp.csv'                   0.29s / 2,000 rows
    the MERGE it replaces                         31.68s / 2,000 rows

End to end it took the growth factor from x6.09 to x1.46 and the 400-page
per-page cost from 6268 ms to 2371 ms.

**It also segfaults.** `Windows fatal exception: access violation` inside
`kuzu/connection.py:131` during the COPY, on kuzu 0.11.3, caught by
`test_store_invariants.py::test_retired_rows_are_reclaimed_not_leaked`.

The crash is at exactly the point that seemed to make COPY safe. COPY does
not deduplicate, and it does not have to, because `_reconcile` clears every
written chunk's anchors first -- for a correctness reason that predates any
of this, since lines pair with anchors by position and one stale anchor
misattributes every line after it. COPY into a rel table with deleted slots
is what breaks.

An isolated benchmark did delete-then-COPY and did not crash, so a green
prototype said nothing about the case the suite covers. **Prototype, then run
the whole suite before believing it.**

If someone retries this: it needs a kuzu version where COPY tolerates a rel
table that has had deletions, and the test above is the gate.

## The cost is probably not here at all

Ten statements per page -- 4 MATCH, 3 UNWIND, 2 MERGE, 1 COPY -- and
`graphstore.py` contains no `BEGIN TRANSACTION` anywhere and reuses no
prepared statements. Every one auto-commits: ten WAL flushes and ten
statement preparations to write one page.

Meanwhile parse + tag + trie + render together are ~145 ms/page and get
FASTER as the store grows. The store phase is 1.3-2.1s. The target is ~10 ms.

Making one of ten statements 109x faster cannot reach that while the other
nine each pay an fsync. This was optimising the slope while the constant was
two orders of magnitude too high.

Also: several timings in this session were taken while a full test suite ran
on the same machine. Ratios within one run are sound; absolute per-page
figures from those runs are upper bounds, not measurements.
