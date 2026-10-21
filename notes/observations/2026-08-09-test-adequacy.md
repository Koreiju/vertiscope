# OBSERVATION — what the suite covers, and whether its assertions have teeth

**Date** 2026-08-09 · **Bears on** MODEL §4, PROCESS §7 ·
**Commands** `python -m coverage run --source=vertiscope -m pytest tests -q; python -m coverage report`
and `python -m pytest tests/test_invariant_adequacy.py -q`

Prompted by a direct question — are there rigorous tests proving completeness?
The answer was no, and this measures how far from it we are.

## 1. Coverage

```
TOTAL                                   4982 stmts   2427 miss   51%
```

The distribution matters more than the total:

| module | cover | reading |
|---|---:|---|
| `core/trie_persistence` | 96% | exercised by every pipeline run |
| `core/signal_fields` | 94% | |
| `store`, `ingest`, `config` | 88–91% | the storage layer is well covered |
| `core/global_tfidf_store` | 84% | |
| `pipeline` | 81% | |
| `core/content_tagger` | 61% | **the domain's own implementation** |
| `core/chunk_builder` | 53% | |
| `core/shadow_html_parser` | 37% | |
| `capture`, `browser` | 36%, 28% | |
| `cli`, `shell` | 15%, 14% | |
| `core/scanner` | 12% | the live-scrape path |
| `__main__` | 0% | |

**The layer the model interprets is well covered; the layer the theory is
grounded in is not.** `content_tagger` implements the detectable-content space
that bounds every semantic claim in the workspace, and 39% of it is unexecuted
by any test. The live-scrape path is effectively untested at 12–36%, verified
only by manual runs against the internet.

## 2. Adequacy — do the assertions have teeth?

Coverage says lines ran, not that a wrong answer would be caught. The
representation invariant was extracted into callable predicates
(`vertiscope/invariants.py`) and each clause mutation-tested: perturb a store into a
state violating that clause, require the predicate to report it.

All five clauses fire on a state that violates them. None is vacuous.

**Finding: the clauses are not independent.** The first version of these tests
demanded that a mutation trip exactly one clause. It failed twice:

```
RI-2 mutation (duplicate identifier)  also trips RI-4
RI-4 mutation (swapped metadata)      also trips RI-5
```

RI-2, RI-4 and RI-5 are all keyed off **row position**, so a perturbation of the
identifier sequence propagates to metadata alignment and thence to the digest
map. RI-1 and RI-3 are independent of that chain.

The consequence is operational: when RI fails on live state, the set of firing
clauses does **not** localise the cause — a digest-map complaint may originate
three clauses upstream. The coupling is now recorded in MODEL §4.2 and asserted
by `test_the_coupling_map_is_as_documented`, so a later change to either the
clauses or the coupling is caught.

## 3. What this does not establish

Completeness is not shown by any of it, and no claim here should be read that
way.

- Coverage measures execution, not correctness, and 51% is not high.
- Mutation testing was applied to the **five RI clauses only** — not to the
  commuting obligations, not to the pipeline tests.
- All tests remain **example-based**, over one synthetic fixture and one
  archived page. No generated inputs; `hypothesis` is not installed.
- Of 83 theory results, 4 are cited by a test.
- The extraction stage has no interpretation at all, so its obligations are
  neither stated nor checked.

## Caveats

- Coverage was measured over the offline suite; the live path would score
  higher under a real scrape but is not measured here.
- The mutation set is hand-chosen. A mutation the author did not think of is
  not covered, which is the standing limitation of the technique.
