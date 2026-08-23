# OBSERVATION — benchmark over 54 structurally varied pages

**Date** 2026-08-10 · **Bears on** MODEL §4, §8.3, THEORY §22.5.10, ERRATA C7 ·
**Commands** `python scripts/fetch_corpus.py` then `python scripts/benchmark.py`

## Corpus

54 pages, 13.7 MB, frozen to `tests/corpus/` with a manifest recording status,
byte count and SHA-1. Selected for *structural* variety: wikis (including
right-to-left, CJK and Cyrillic), documentation, generated API references, news
in heavy and text-only variants, forums, standards, government portals, academic
listings and abstracts, package registries, scraping-practice sites,
deliberately-unstyled pages, and a plain-text file served as a page. Six sites
refused (403/404/202) and are recorded as failures rather than dropped.

Fetched **without JavaScript execution**, so script-rendered pages appear thin.
That is a real class of input and was kept.

## Metrics

| | metric | result |
|---|---|---|
| M1 | coverage of tagged xpaths | min 0.111 · median 0.898 · max 1.000 |
| M2 | chunk roots pairwise non-nested | **6 / 54 pages clean; 16,720 violations** |
| M3 | collapse rate | min 0.000 · median 0.157 · **max 0.873** |
| M4 | coherence, `im(α) ⊆ 𝒦` | 0 incoherent rows |
| M5 | representation invariant | **4 / 54 pages clean** |
| M6 | RI-R1, pattern derivable | 54 / 54 |
| M7 | containment, indexed ⊆ recorded | 54 / 54 |
| M8 | determinism | 54 / 54 |
| M9 | subcategories exercised | 17 / 18 (`json_data.inline` never — it has no detector) |
| — | throughput | 12.8 MB in 10.9 s (≈1.2 MB/s) |

## Finding 1 — the representation invariant fails on 93% of real pages

Only **RI-2** (identifier uniqueness) fails, on 50 of 54 pages. It has held on
the fixture since it was written, and mutation tests proved it non-vacuous —
against a page that cannot exhibit the fault.

Mechanism, traced on `apnews.com`: identity is
`sha1(url | pattern | sha1(html_raw))`, and **352 of 3,460 instances (10.2%)
render to empty `html_raw`**. `sha1("")` is constant, so every empty-HTML
instance sharing a pattern receives one identifier. The largest such class holds
**96 instances with 96 distinct addresses**.

This is COR-22.5.11 exactly: a content digest is the most discriminating input
available *except where content is absent*, where it is maximally constant. The
identity scheme has its worst behaviour on the instances carrying no content.

The index then admits duplicate identifiers because `add_chunks` deduplicates
new rows by *content digest* within a batch, not by identifier, so records
sharing an identifier but differing in text are each appended.

Distinct from THM-22.5.7's collapse, which concerns content-*identical*
siblings. This is degeneracy, not indistinguishability.

## Finding 2 — instance sets are heavily nested

M2 counts pairs where one instance's address is a strict ancestor of another's.
Only 6 pages are clean; 16,720 violating pairs overall. So the instance set is
not an antichain, and content is indexed both alone and inside its ancestors,
inflating document frequency for the nested terms.

No live claim is contradicted — the current THEORY does not assert that our
chunk sets are cuts — but the containment filter exists to enforce roughly this,
and on real pages it does not.

## Finding 3 — what does hold

Coherence, pattern-derivability, containment and determinism hold on **every**
page. These were previously verified on one fixture; they now have 54 witnesses.

## Caveats

- One snapshot per page; no page is sampled twice, so temporal variation is
  unmeasured.
- No JavaScript, so SPA-heavy pages are thin and their true structure unmeasured.
- M2's pair count is quadratic in instances per page and dominated by the
  largest pages; the per-page clean/unclean count is the more comparable figure.
