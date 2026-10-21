# OBSERVATION — correcting the generalization map re-keys 65% of identities

**Date** 2026-08-09 · **Bears on** COR-22.5.5, MODEL §3.3, ERRATA E1/B5 ·
**Command** counterfactual probe, `scratchpad/blast_radius.py` (applies the
correction in-process; nothing is written)

## What was measured

`instance_id = sha1(url | pattern | content_hash)` and `pattern = g(address)`.
PROP-12.4 requires $g$ to be region-anchored; the implementation strips all
indices. So correcting $g$ changes `pattern`, which changes `instance_id`. The
question is how much.

The probe implements the region-anchored map of `REAL_TIME_SCAN_UPDATE` §7.8 —
landmark prefix verbatim, remainder generalized, landmarks being `main`, `nav`,
`header`, `footer`, `aside`, `article`, `section` — and recomputes both.

## Result

| | wikipedia | fixture |
|---|---:|---:|
| instances | 610 | 43 |
| pattern changes | 397 (65.1%) | 30 (69.8%) |
| **`instance_id` re-keyed** | **397 (65.1%)** | **30 (69.8%)** |
| distinct patterns before | 157 | 17 |
| distinct patterns after | 177 (+20) | 35 (+18) |

**Total: 653 instances, 427 re-keyed (65.4%).**

## Reading

Two things at once, and they pull in the same direction.

**The correction is needed.** Distinct pattern count rises by 20 and 18 — the
region-anchored map *separates classes the current map conflates*. That is the
nav-versus-content collision predicted by PROP-12.4 and observed in retrieval as
navigation fragments outranking prose. The current map is not merely different;
it is merging things that are not the same.

**The correction is expensive in exactly the wrong currency.** It re-keys 65% of
identity. Identity is what the index rows, the record rows, and content-hash
deduplication all key on, so a correction to a *structural* map propagates into
the *identity* of two thirds of stored state.

This is COR-22.5.5 instantiated: `instance_id`'s dependency closure contains a
provisional map, so it is not a persistent identifier across the revision. And by
PROP-22.5.4 the cost is measured over the closure — `instance_id` never mentions
`generalize_xpath`, it reaches it through `pattern`, and it is invalidated just
as thoroughly as `pattern` itself.

## The test that does not test this

`test_instances_have_stable_ids_across_runs` asserts identifier stability and
passes. It runs the pipeline twice **with the map held fixed**, so it measures
determinism, not persistence. The invariance that matters — stability across a
*change* of map — is unobservable in any fixed-map experiment, so the passing
test gives no assurance about it.

This is not a defect in the test; it is a case of a test measuring a different
invariance from the one its name suggests. Recorded because the two are easy to
conflate, and because the conflation is what would let a correction land without
anyone anticipating a 65% re-key.

## Caveats

- Two pages. The percentage will vary with markup; the *mechanism* will not.
- The region-anchored map used here is one reading of §7.8. The shipped in-page
  engine anchors at the deepest anchor tag with a slightly different tag set, so
  the exact figure depends on which correction is adopted — but every variant
  that separates regions will re-key a large fraction, since that is what
  separating regions means.
- `content_hash` was recomputed from `html_raw`, matching the production
  derivation.
