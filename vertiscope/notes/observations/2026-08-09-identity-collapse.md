# OBSERVATION — 9% of rendered instances collapse into shared identifiers

**Date** 2026-08-09 · **Bears on** THM-22.5.7, REM-22.5.9, MODEL §8.3 ·
**Command** in-process probe over three archived pages; store counts read back
from SQLite

## What was measured

THM-22.5.7 says a reshuffle-stable identifier must assign content-identical
siblings the same value. Whether that bites depends on whether such siblings
occur. This counts them, and then checks whether the collapse loses information.

## Result

| page | rendered | distinct ids | collapsed | sibling groups |
|---|---:|---:|---:|---:|
| wikipedia | 672 | 610 | 62 (9.2%) | 7 |
| census | 105 | 93 | 12 (11.4%) | 3 |
| fixture | 43 | 43 | 0 | 0 |
| **total** | **820** | **746** | **74 (9.0%)** | **10** |

End-to-end through the store: 672 rendered, **610 rows**, 62 lost. The record
table has no multiplicity column — `char_count` is a text length, not a count of
occurrences.

## Reading

The hard case of THM-22.5.7 is not hypothetical. Roughly one rendered instance
in eleven shares its identifier with another, and ten of those groups are actual
siblings under a common parent.

By REM-22.5.9 the collapse is lossless **iff** the multiplicity is retained. It
is not, so 9% of the extraction's cardinality is discarded. PROP-10.2 states the
extraction is a *multiset* — multiplicity carries information — and the store
represents it as a set.

The fixture shows 0%, which is why this went unnoticed: the offline suite runs
against markup with no duplicate siblings, so every test passes on a page where
the phenomenon cannot occur.

## A second defect, found while measuring

`IngestReport.instances_written` reported **672** while the store held **610**.
`Store.upsert_instances` returned `len(records)` rather than the number of rows
written, so the count was of records *offered*. Every instance figure quoted from
this pipeline — including in earlier summaries in this workspace — was the
rendered count, not the stored count.

Fixed: the method now returns the number of distinct identifiers, and the report
carries `instances_rendered`, `instances_written` and `instances_collapsed`, with
a test requiring `rendered == written + collapsed` and `written` to equal the row
count read back from SQLite.

## Caveats

- Three pages, two of them archived real sites and one synthetic.
- The sibling-group count uses parent-of-address equality, which undercounts
  siblings separated by intervening wrappers.
- No claim that collapsing is *wrong*. Two identical cards may well be one thing
  for retrieval. The claim is only that the count is discarded rather than
  recorded, and so the choice is not recoverable downstream.
