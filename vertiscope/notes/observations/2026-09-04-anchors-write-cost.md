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

---

## Update: COPY is not the answer for nodes either, and 10 ms is not reachable this way

**COPY into a NODE table is 4.4x SLOWER than MERGE.** Same real rows, same
fresh store:

    MERGE into Address     65.5 ms/page
    COPY into Address     287.8 ms/page      0.2x

The asymmetry with the rel table makes sense in hindsight. COPY beat MERGE on
`Anchors` by 109x because a rel MERGE resolves two endpoints by scan, which
is the entire bug. A node MERGE has no endpoints to resolve, so COPY saves
nothing and pays CSV parsing on top.

For the record, since they would have mattered had it been faster: re-COPYing
the same primary keys **raises** `Found duplicated primary key value` rather
than silently duplicating, and COPY after DELETE **survives** -- node tables
do not have the rel table's crash.

## What the store costs, and why 10 ms is out of reach on this path

Fresh store, 24 pages, 41 KB median, nothing else running, after the
zero-vector fix:

    parse    3.0    tag   3.2    trie  11.2
    render  39.1    leaves 0.6   store 141.5      TOTAL 198.6 ms/page

Every mechanism available has now been measured:

| lever | effect |
|---|---|
| drop the zero embedding | store -28%, page -22%  (**landed**) |
| COPY for rel edges | 109x on that statement, **segfaults kuzu 0.11.3** |
| COPY for node tables | **0.2x** -- slower |
| one transaction per page | 1.15x |
| bigger batches per statement | none; cost is per row |
| trimming Address columns | ~14% of that statement; `akey` is 5.6 ms |
| rewriting the Anchors MATCH | four variants, all >= current |

Per-row node MERGE is ~0.12 ms/row and nothing in kuzu goes faster for this
shape. A page writes ~535 addresses, ~15 chunks and ~385 anchors. **Even with
the store at zero the remaining pipeline is 56 ms**, still 5.6x above a 10 ms
target.

So 10 ms/page requires that the ingest path not write to kuzu per page at
all -- deferring graph materialisation the way `flush_vectors` already defers
vectorisation. That is an architectural decision, not an optimisation, and it
is open.

## A harness flaw worth not repeating

The column-breakdown benchmark did not dedupe `aid` before writing, so it
wrote more rows than a page has and reported 227.8 ms/page where production
measures 69 and a deduped harness measures 65.5. Its *ratios* stand; its
absolute figures do not. Cross-check every isolated harness against the
end-to-end number before quoting it.

---

## 2026-09-05: dedup, and a caution about which pipeline you are looking at

`--corpus` over 135 pages, one verified run (see `analytics/runs.py`):

    collapsed 46,886   under_dedup 11,641   over_dedup 670
    recall 80.11%   precision 98.59%   correctness 93.77%

**The recall figure is inherited policy, not a regression.** A matched A/B on
identical pages, labels off vs on, came back byte-identical -- and the arms
DO differ in output, verified separately, so the label work changes what a
line SAYS without changing how many lines a lineage draws, which is what
dedup counts. The 17:1 bias toward noise over loss is what `DedupScore`
argues for: over-dedup is unrecoverable, under-dedup is survivable.

Raising recall means folding harder, in the direction that once made every
search-result title vanish. The way out is not a threshold but making
collapse non-destructive -- carrying absorbed addresses the way `line.inline`
already does -- so that folding stops meaning losing. Unbuilt.

**`_dedupe` is not where the loss is.** It is element-scoped, so a dropped
unit's xpath survives on the unit that kept it; navigation is intact. The
measured `over_dedup` is a LINEAGE collapse -- ancestor/descendant, no line
surviving at any member's owner -- which comes from the render's suppression
and consumption rules, not from `_dedupe`.

**The caution.** Chasing the 670, the `over_dedup_sample` showed AP headline
anchors -- `Western Europe sets new temperature record` -- that were verified
elsewhere in this session to draw correctly. That looks like a metric
artifact, and the obvious next step is to reproduce it offline.

Do not. `--corpus` measures the SENSOR path: a live browser, after the page's
scripts have run. Reproducing with `ContentTagger` measures the TAGGER path:
a static parse of the saved html. AP's footer is JS-built, so
`/html/body/footer/div/div/div/div/a` exists in the live DOM and has NOTHING
beneath it in the static parse. The two disagree for reasons that have
nothing to do with dedup, and comparing them proves nothing either way.

Diagnosing over_dedup needs the sensor's own rendered set from the live run,
not a static re-render. Everything else in this file's history is the same
mistake in a different costume: reasoning about one path from the other
path's output.

## Non-destructive collapse: attempted, reverted, and why

**The idea.** `over_dedup` is dangerous because collapse is terminal: the
surviving unit keeps the element's xpath so navigation holds, but the dropped
address key is gone and nothing can say the render accounted for it. That
asymmetry is what justifies tuning 17:1 toward leaving noise. If a line named
what it collapsed, folding harder would stop meaning losing and recall could
rise.

**Built:** `MarkdownLine.absorbed`, alongside `inline` and distinct from it --
`inline` is MERGED (words visibly in the line, actionable there), `absorbed`
is DROPPED (an `aria-label` beside the text it duplicates, an href hidden
because the anchor speaks; not separately visible, only findable). `_dedupe`
reports what it dropped, `hidden` counts as a collapse too, and `covered`
accounts for both.

**Measured, on 20 pages:** 4,411 collapses named across 3,484 lines, `covered`
29,021 -> 33,432, `anchors` unchanged at 21,785. The breakdown is the right
shape -- text.visible 2,397, urls.external 687, text.accessible 451,
text.metadata 334: the alternate spellings of one fact.

**Reverted.** It makes the covered set depend on the context window, and
`test_no_address_is_lost_when_the_window_changes` exists for exactly that
property: 4 addresses differ at window 200.

The cause is structural, not a detail. `absorbed_at` collects drops during
one `_render_sized` call, but that function runs SPECULATIVELY at every level
`_size_of` and `_descend` consider, and is memoised. Which call observes a
drop, and whether the line that would claim it is in the emitted chunk,
depends on how the chunker descended -- which is what the window changes.
Switching the attachment from `pop` (first line wins) to `get` (every line at
the element) removed one source of nondeterminism and did not fix it.

**What a working version needs:** the absorbed set must be a property of the
ELEMENT, derived from the units at that element, computed independently of
which render call happened to see them -- the same discipline the fold pass
needed when it had to be hoisted out of the descent for cost. Collect it from
the trie, not at render time.

Two lessons banked either way:

* the field was a silent no-op at first. `_dedupe` reported 76,502 drops, the
  owners were collected, the attachment fired, and ZERO survived, because
  four places RECONSTRUCT `MarkdownLine` and none carried the new field --
  `_join_labels`, `_fold_links_into_prose`, `_inline_flow`, `_clone_chunk`.
  `_clone_chunk`'s own docstring warns about this for `inline`. Reading the
  code would not have caught it; measuring did.
* coverage must not move with the window, and any per-element bookkeeping
  added at render time will move with it unless it is derived from the trie.
