# Global UMAP, page-subset update -- verified facts and measurements (2026-10-06)

The user's design (2026-10-04, verbatim in the task): one UMAP over ALL chunks
from all URLs; a page's diff re-fits only that page's chunk rows; 3D coordinate
streaming as a switch between force-directed and UMAP. Line numbers are in
`vertiscope/obsidian/projector.py` / `pumap.py` as committed with this note.

## 1. Verified facts

| Claim | Verdict | Where |
|---|---|---|
| Page position = unweighted unit mean of chunk vectors | TRUE for `centroid="semantic"` (what the chunk/global scopes need): `block.mean(axis=0)` then `_unit`. The `triple` centroid is PageRank-weighted instead. The vectors averaged are *lead* vectors (a merge group's 512-token vector stands for its members). | projector.py:867-869, used at :892 (fit) and by `drain` via `_page_rows`; test `test_a_page_is_the_unweighted_unit_mean_of_its_chunk_vectors` (with a weighted-mean planted arm) |
| `update()` trains on all rows | TRUE. `X = vstack([self._raw, X_new])`; every row ever trained is in every update, old ones landmark-pinned. Cost = corpus: 22-38 s at 2,050 rows here (refitscope SEED_CURVE says 15.9 s at 2,000; GPU is shared with the live app). | pumap.py:266 |
| What each scope trains on | `pages`: page centroids only. `chunks`: centroids + every chunk, but a chunk is appended once and **never retrained when its vector changes** (`c not in trained_chunks`; `drain` schedules only never-trained pages/chunks). `update()` also appends a changed *page* centroid as a new row while the old row stays pinned. | projector.py `_online_worker`, `drain` (`untrained = ...`) |
| Online-update moves reach the delta log | TRUE for pages and chunks. `drain` logs every placed chunk/page/gone; the online worker logs every chunk/page whose position moved > 0.25 (0.05% of the 455 median page spacing on the test fixture; the trained new page moved ~90). Replaying `delta()` onto a client holding the post-drain picture reproduces the server to <= 0.25. Planted arm (log that drops appends) leaves the client ~90 off. | projector.py:1040-1060 (online), :1558-1567 (drain), :690 (`delta`); tests/test_online_delta.py (chunks and pages scope) |
| Plugin half | Read, not run (Obsidian must not start): `pullDelta` polls `/projector/delta` each second, applies `d.chunks` to open nodes and `d.pages` to page nodes through `glide`; the epoch does not change on an online update so no reload. | obsidian-plugin/src/graph.ts:585, :1470; sidecar.ts:123; sidecar.py:1772 |
| "Fit updates are not persisting" | **Disk: TRUE.** `save()` is called only at the end of `fit()` (projector.py:1479). Neither `drain` nor the online worker saves, so online-trained weights, positions and `trained` sets are lost on restart and re-derived (changed pages re-queued, re-trained). UI/delta: false -- they do reach it. A second, smaller gap: a mutated chunk of an already-trained page is only moved by `transform` and never retrained (chunk scope). |  |

## 2. Measurements (RTX 4070 laptop, torch 2.6 cu124; synthetic 768-d, topics->pages->chunks, 100 chunks/page; `python -m vertiscope.analytics.global_umap`)

`update_subset(steps=300, lr=1e-3, 8-NN + 256 random landmarks, cap 1,024)`, CUDA graph for the step loop. Diff of d chunks on one page (mutated 60% toward another page's chunk; d>100 also appends). 6 trials each, applied in sequence. Latency is wall time of `update_subset` (deep copy of the model, 7-32 ms, reported separately in the JSON). The GPU is shared and timings drifted ~25% between two runs (a first run gave p95 384 ms for the same 15k/d=10 cell; this one 545), so read p95 as "about half a second".

| rows | diff | p50 ms | p95 ms | rows trained | held drift p50 (% of spread) | held rows drifting >5% | overlap10 subset | stale (no train) | base ceiling | random | planted drift (no landmarks) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2k | 10 | 485 | 503 | 341 | 0.41% | 1.2% | 0.238 | 0.073 | 0.317 | 0.007 | 73% |
| 2k | 50 | 554 | 578 | 559 | 0.49% | 2.3% | 0.308 | 0.130 | 0.315 | 0.024 | 63% |
| 2k | 200 | 567 | 579 | 899 | 0.46% | 1.2% | 0.126 | 0.064 | 0.321 | 0.014 | 57% |
| 8k | 10 | 476 | 499 | 342 | 0.69% | 0.9% | 0.168 | 0.055 | 0.200 | 0.003 | 51% |
| 8k | 50 | 495 | 526 | 636 | 0.74% | 2.0% | 0.183 | 0.098 | 0.207 | 0.012 | 36% |
| 8k | 200 | 533 | 543 | 1126 | 0.68% | 2.0% | 0.101 | 0.079 | 0.203 | 0.009 | 53% |
| 15k | 10 | 499 | 545 | 345 | 0.85% | 1.0% | 0.118 | 0.023 | 0.174 | 0.000 | 80% |
| 15k | 50 | 510 | 519 | 667 | 0.77% | 1.5% | 0.131 | 0.076 | 0.183 | 0.007 | 34% |
| 15k | 200 | 556 | 579 | 1194 | 0.74% | 1.6% | 0.093 | 0.064 | 0.170 | 0.005 | 30% |

* **Cost scales with the page, not the corpus**: p95 519-579 ms from 2k to 15k rows. The existing `update()` (every row, 10/50/200 new rows) took 22.3 / 34.2 / 29.3 s at 2,010-2,200 rows (one trial each, shared GPU).
* **Held drift** is *latent*: the net's output on rows it did not train on, now vs. stored. The stored positions (what the UI shows) are untouched by construction -- asserted exactly in `test_a_mutated_page_retrains_its_own_rows_and_nothing_else_moves`. Median 0.4-0.9% of the median pairwise distance; ~1-2% of held rows drift >5% of it; the max is 2-18 units against a spread of ~8-9 (a handful of rows far from any landmark). Planted arm (landmark weight 0, no landmarks): median drift 30-80% of spread, ~100% of rows >5% -- the metric can fail.
* **Neighbourhood quality** (10-NN overlap, input vs 6-d embedding, on the page's rows): d=10/50 the update recovers 66-98% of the pre-diff ceiling (`base`), 2-5x the no-training `stale` arm, 20-100x the random null. **d=200 is weak** (50-60% of the ceiling, close to `stale`): more steps (300 -> 1500) and lr changes did not move it (0.10 -> 0.13), so it is not a step budget problem. Against the full `update()` at 2k rows: subset wins at d=10 (0.238 vs 0.210) and d=50 (0.308 vs 0.254), loses at d=200 (0.126 vs 0.293). Absolute overlaps are low because the benchmark's base fit is capped at 4,000 steps; the ceiling arm is the fair denominator.

Whole `PageProjector(umap_scope="global")` path (enqueue -> drain draws the page by transform -> online worker: `update_subset` + placing the page and its chunks -> delta carries trained positions), debounce set to 0 (production holds the *retrain* back 2 s; the page is drawn at once by the transform, ~4-14 ms):

| rows | diff | drain ms p50 | train ms p50 | place ms p50 | edit->trained in delta p50 / p95 ms |
|---|---|---|---|---|---|
| 2k | 10 | 3.7 | 399 | 4.1 | 414 / 449 |
| 2k | 50 | 5.6 | 423 | 4.5 | 443 / 467 |
| 8k | 10 | 7.9 | 535 | 7.9 | 569 / 584 |
| 8k | 50 | 11.0 | 770 | 8.3 | 811 / 855 |
| 15k | 10 | 10.9 | 609 | 7.7 | 657 / 665 |
| 15k | 50 | 13.6 | 595 | 8.3 | 639 / 687 |

The user's bar (< 1 s p95 for a 50-chunk page diff at 15k rows) is met: 687 ms end to end, 519 ms for the model alone.

## 3. What was built

* `ParametricUMAP.update_subset(X_rows, idx, remove=...)` (pumap.py): replace/append the page's rows, landmark-pin a bounded sample (k-NN of the page's rows in input space + random), UMAP loss over edges touching the page, all random draws pre-sampled and the step replayed as a CUDA graph (5.6 -> ~0.5 ms/step). `fit(X, max_steps=)` caps a first fit.
* `PageProjector(umap_scope="global")` / `VERTISCOPE_UMAP_SCOPE=global` (projector.py): `scope == "global"`, a `_RowMap` of chunk id / `page:url` -> model row (retired rows reused), `drain` schedules every touched page (so mutations retrain), `_online_worker` retrains the page's rows, `fit()` reconciles changed pages by `_refit_global`. Drawing (`_place_chunks`, neighbourhood rule), the delta log, epochs: unchanged. Default behaviour unchanged (env unset).
* `choose_scope(..., want_global=)` (refitscope.py).
* Tests: tests/test_online_delta.py, tests/test_global_umap_scope.py (GPU-skipped without CUDA), helpers tests/umap_fakes.py.

## 4. Open

* Persist online updates (`save()` after an online update, off the hot path) -- not done; pickle of `vec` at 15k x 768 is ~46 MB.
* d >= ~100 changed chunks (a page re-scraped wholesale): fall back to a page-group refit or to the full `update()` on a schedule? Quality, not latency, is the limit.
* First fit over 15k rows is capped at `GLOBAL_FIT_STEPS = 4000` (20-35 s); real-corpus quality at that cap is unmeasured (synthetic only; no stores were opened).
* Latent drift tail (~1-2% of held rows >5% of the spread): harmless while stored positions are held, but a later full `transform` of the corpus would show it. A periodic re-place (epoch change) is the existing mechanism.
* Force-directed <-> UMAP switch and the right-click URL-node gesture are plugin work, not touched.
