# Task ledger

**The tasks now live in `docs/PLUGIN_PRD.md` as numbered rows** (2026-10-07:
the user: "I think our PRD might be where the new set of tasks are supposed
to go"), and their progress is the generated `build_analytics/design_state.md`.
This file is the working index from tonight's items to those rows:

| ledger | PRD row |
|---|---|
| A1, A3, C1-C3 | D-46, G-114, G-117 |
| A2 | G-114 (one image per element), M.5.1 at the source still open |
| A4 | G-118 (`app_anomalies`); store churn found: D-47 |
| A5 | G-54 (page click), re-check after D-47 |
| A6 | D-44 |
| A7, A8, A9, A12 | D-45 |
| A10 | D-43, G-113 (latency) |
| A11 | G-117 |
| B1 | G-116 |
| B2, B5 | G-115 |
| B3 | G-112 |
| B4 | G-113 |
| C4 | G-111 |
| D1, D2 | G-106 / the global UMAP scope; chunking speed open |
| D3 | G-109 |
| D7, D8 | G-117, G-119 |

The detail below is kept as the evening's record.


Every open item from the user's messages, in one place, worked in order.
The user's words are in `docs/PLUGIN_GOAL.md` (2026-10-04 and 2026-10-06
addenda; the numbers below are that file's "Read as" items). A row is DONE
only when it was seen working in the running app, with the evidence named;
BUILT means code and tests exist but it has not been seen live; OPEN means
not started.

Status words: **DONE** (seen live) · **BUILT** (tested, not seen live) ·
**PARTLY** · **OPEN** · **DROPPED** (by the user).

Last updated: 2026-10-06 (evening session).

## A. Regressions and defects the user saw

| # | item | status | evidence / next step |
|---|---|---|---|
| A1 | Clicked panel renders empty (10, 17, 18) | PARTLY | Cause 1: thumbor/Wikipedia urls cut at the first `)` -- fixed in every parser (`tests/test_paren_urls.py`, 6 incl. planted). Cause 2: the page form served a held snapshot forever -- now re-read on open and on every diff. Seen live: page form shows an allrecipes card's image (loaded). NEXT: the user to confirm on image-billboard nodes; `app_anomalies` reports empty panels. |
| A2 | Duplicate images in nodes/panels (3) | PARTLY | Markdown form keeps one image per element (src + alt detections drew the same jpg twice). NEXT: the same at the source (`markdown.py` live path, PRD §M.5.1) so the 3D picture and every view agree. |
| A3 | Images missing from nodes (1) | PARTLY | Found: relative urls (johnwick `assets/img/...`) absolutised for the markdown form; video/audio now players; CSS background images are NOT detected (3 on johnwick, incl. the hero). One picture per chunk node is the G-81 design. NEXT: a read-only background-image peripheral; per-node picture choice reviewed. |
| A4 | Phantom / stale nodes and links, render lag (6) | PARTLY | Census tool (`__vertiscope.anomalies`, MCP `app_anomalies`): 0 phantoms, 0 dangling links, 0 stale link endpoints in samples taken; render frame p50 8 ms. Fans of long lines = real containment edges across UMAP positions (see B3). NEXT: the anomaly recorder's hour of samples summarised; frame-stall recorder summarised. |
| A5 | Page-node click does nothing (20) | PARTLY | The handler works (ar.wikipedia 0 -> 770 chunks); a real click on archive.org navigated but drew 0. NEXT: reproduce with the recorder on; suspect a revisit diff retiring the unfolded nodes. |
| A6 | archive.org not picked up (21) | BUILT | Late-attached shadow roots were never observed. Fixed (held hosts re-checked; `:defined`). Fixture A/B (`tests/fixtures/late_shadow.html`): 3/3 leaves vs 0/3 planted. Live cell on archive.org: 157 sensor chunks / 407 observers vs 17 / 33 before. NEXT: the user to see overlays and 3D nodes on archive.org. |
| A7 | Overlay slides off the page (11) | BUILT | `boxFrame` subtracted the parent's offset from `position: fixed` boxes (64 px up). Fixed: offset only for a real containing block. NEXT: see it live. |
| A8 | Overlays stay put while scrolling (johnwick) | BUILT, loaded | Scrolls mutate nothing, so nothing re-measured. Sensor now pushes `scroll` (scroll + wheel listeners, passive) and a style/class observer catches transform-based smooth scrolling (johnwick: scrollY stays 0); host re-measures pins and diff boxes per frame. Live: 8 real wheel events -> 248 re-measure signals (the page's own animation also sends ~450 a session; cheap while nothing is outlined). NEXT: the user to see boxes follow. |
| A9 | Hovering the johnwick header logos shows no chunk | BUILT | The chunk's root had an empty box (`box: null`); `runBox` now unions its descendants' boxes (peripheral, not the fold; c2 tests pass). NEXT: see it live. |
| A10 | Overlay latency single-digit ms (5) | PARTLY | Push restored on console-wrapping pages (isolated world): mutation->host 2-17 ms on johnwick, 3-4 ms on the latency fixture (was ~1.1 s). drain->overlay measured 690-890 ms on the fixture in both arms -- the next stage. NEXT: profile drain->overlay. |

| A11 | Audio detected (johnwick) | PARTLY | The page has no `<audio>` and no audio url in any attribute; its sound is the trailer `<video>` (muted, 0 audio bytes decoded), captured as a `media` line. Audio played from script (`new Audio(url)`) is invisible to DOM observers; resource timing (`performance.getEntriesByType('resource')`, read-only, readable from the isolated world: 144 entries) lists what the page fetched. NEXT: a page-level media peripheral from resource timing. |

## B. Layout and the 3D view

| # | item | status | evidence / next step |
|---|---|---|---|
| B1 | Streamed chunks start on a sphere, not the trie (8) | OPEN | Measured: 33/33 streamed nodes hang on the page node; 0/33 trie parents drawn; radius CV 0.24. NEXT: draw the parent chain (or reparent to the nearest drawn ancestor) so the stream grows as a tree. |
| B2 | UMAP clusters small and packed; telescope radially (7, 23) | BUILT | `telescope()`: direction and distance ratios kept, inner minimum, 90th percentile at 0.85 of the bound, clamp beyond; bound = max(0.45 x nearest page, 0.35 x scene radius); chunks grow into their room up to 2.5x. A/B so far inconclusive (the bound was the cramp); NEXT: re-measure and look. |
| B3 | Full patricia tree rendered clearly (22, 11 of 10-04) | PARTLY | `treeVerdict` over every edge (`tests/tree_guard.test.mjs`, 4 planted). Found one defect live: `ddg/` and `ddg/#chat` as two page nodes. NEXT: fragment-normalise page nodes; a tree view of an open page. |
| B4 | Hover an overlay -> camera focuses the chunk and follows it | BUILT | `focusOn`: 200 ms dwell, 400 ms flight, follows the node's displacement each frame, released by the reader's own camera gesture. NEXT: see it live. |
| B5 | Voronoi | DROPPED | The user: "Removing voronoi might be the move"; the telescope's inner minimum and outer bound replace it. |
| B6 | Right-click page toggle | DONE | G-110 PASS in the Verifier with its planted arm. |

## C. Panels

| # | item | status | evidence / next step |
|---|---|---|---|
| C1 | Two forms: page rendering + Obsidian markdown; no shadow-DOM switch (13) | DONE | Seen live: an allrecipes chunk opened in the page form with its image loaded, switched to markdown. |
| C2 | Header = the chunk's full trie address (14) | DONE | Seen live: `https://www.allrecipes.com/recipes/ : /html/body/main/section/div[2]/section`. |
| C3 | Markdown form larger; resize about the centre (15) | BUILT | Sizes per form (340 / 500 px); `switchForm` keeps the centre. NEXT: see it. |
| C4 | Interactive panels act on the live page (G-111) | PARTLY | Verifier: click and refusal and navigation pass; the text field had no address in the card. NEXT: fix the input's address in the snapshot, rerun G-111. |

## D. Pipeline, speed, tests

| # | item | status | evidence / next step |
|---|---|---|---|
| D1 | Chunking speed profiled and improved (12) | OPEN | NEXT: per-stage profile from the recorder (fold, render, store) on the user's pages; cut the largest. |
| D2 | UMAP fit speed from the in-app latency (9) | PARTLY | Global per-page subset refit (behind `VERTISCOPE_UMAP_SCOPE=global`): ~0.5 s p95 at 2k-15k rows vs 22-34 s for the full update. NEXT: measure the online update in the app, then decide the default. |
| D3 | Central diff check G-109 non-vacuous | PARTLY | Clean arm passes; planted arm reads stale 0 (the fixture's renames cycle). NEXT: redesign the measure. |
| D4 | Tests that would have caught tonight's regressions | PARTLY | Added: paren urls, late shadow roots (fixture A/B), tree verdict, billboard log, anomalies. NEXT: a Verifier check that opens a panel and asserts it rendered (images loaded, non-empty). |
| D5 | MCP as observant as the reader (`app_anomalies`) | BUILT | Phantoms, orphans, dangling links, tree, stream star, panels (empty/broken/duplicate), overlay bounds, latency. NEXT: call it through the MCP once loaded. |
| D6 | Git-history adapter (minimal) | DONE | `vertiscope-git` MCP: queries run on git, vector cache only; 17 tests; measured 205-500 ms warm. |

| A12 | Overlays too large for a chunk (29) | OPEN | NEXT: measure the in-page unit the overlay outlines vs the stored chunk (256-token window) on johnwick; make them the same unit. |
| D7 | Visual media coverage: screenshot + account for every visible picture/video/background against the chunks (27) | PARTLY | `python -m vertiscope.analytics.media_coverage` (store addresses resolved in the page, every media element enumerated incl. shadow roots, screenshot outlined green/red). johnwick: images 154/156, video 2/2, inline svg 0/37, CSS backgrounds 0/3. NEXT: svg graphics and CSS backgrounds detected; archive.org run. |
| D8 | johnwick.movie and archive.org as the test pages for every feature (28) | OPEN | NEXT: run each ledger item's check on both pages, panel page-form on dynamic renders included. |

## E. Housekeeping

| # | item | status | next step |
|---|---|---|---|
| E1 | Commit with measurements; `confirm.mjs`; `design_state.md` | PARTLY | Commit after each load-and-see; regenerate design_state at the end of the session. |
| E2 | Test pages in the reader's store (purge?) | WAITING | The user's call. |
| E3 | Q.002 (does the store keep page history) | WAITING | The user's call. |
