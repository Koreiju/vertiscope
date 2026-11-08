# Open work — tracked against PLUGIN_GOAL and the PRD

Kept by hand at the reader's request (PLUGIN_GOAL 138: "keep careful track of
all features/builds/tasks unstarted up until now with the full spec/docs/prd in
mind"). Each row names its verbatim item, its status, and the evidence. Status
words: **confirmed** (live check with a planted arm passed), **built** (code in,
not yet confirmed live), **partial**, **not started**, **needs the reader**.
The PRD's own computed status lives in `build_analytics/design_state.md`; this
file is the working list for items 130–139 and what they reopened.

Last updated 2026-11-07, commit `c4216e2`.

## PLUGIN_GOAL 137 — the 26 reported glitches

| # | What | Status | Evidence / next step |
|---|---|---|---|
| 1 | Panel collapses while its markdown renders | confirmed (measured + screenshot) | head one row (29 px), body 270 px; `a6e6136`. No planted check yet |
| 2 | Chunk panels under the browser | confirmed | PG-137-panels-over, run 61 |
| 3 | Image+caption / infobox sub-chunking (Gay, NC) | needs the reader | store holds the box as ONE 18-line chunk; a live hover resolves to it. Not reproduced |
| 4 | Chunk views as browser cells, linked to markdown through a few abstract graph nodes | **not started** | design item; largest open build |
| 5 | Arrow keys run the search with an empty field | needs the reader | synthetic arrow press runs nothing; need the steps |
| 6 | Chunks clumped | partial | the layout keeps UMAP exactly (drift 0); the fit packs clusters tight. Refit run 2026-11-07 with min_dist 0.6 (pumap + umap): median nearest spacing / cloud radius 0.0029 -> 0.0026, i.e. **no effect** (the fit is reframed after); reverted. Next: a density-equalising step (densMAP, or rescaling each cluster about its centre) -- a design choice |
| 7 | Code link opens the Microsoft Store | confirmed | PG-137-fixes, run 55 |
| 8 | Booleans: no "go"; false, hover true, click applies | confirmed | PG-137-fixes + PG-137-action-hover, run 75 |
| 9 | Plain text highlighted as variables | confirmed | PG-137-prose-plain, run 71 |
| 10 | `[]()` gesture does not work | confirmed | PG-137-gesture-spaced, run 72 (spaced form) |
| 11 | Control markdown reloads a temp page | confirmed (clean arm) | PG-137-fixes; planted arm vacuous on a fresh note |
| 12 | Yellow dot follows the mouse | confirmed | PG-134-polar, run 70 |
| 13 | Links open nothing / open DuckDuckGo outside | confirmed (clean arm) | PG-137-fixes |
| 14 | No exit on a 2D browser cell | confirmed | PG-137-fixes |
| 15 | Page/chunk switch closes nodes | confirmed | PG-137-switch-keeps, run 73 |
| 16 | Duplicate page nodes from a trailing "#" | confirmed | PG-137-fixes |
| 17 | Exploding spider web / flickering links | confirmed | PG-138-no-long-links + PG-138-no-flicker, run 6 (after restart) |
| 18 | One browser tab navigates the others | partial | likely the window-open path, now kept in the cell; not confirmed |
| 19 | Retrieval re-triggers at high n / on scroll | confirmed | PG-137-rerank-debounce, run 58 |
| 20 | Bandcamp diff-stream saving | partial (big win) | anchor edges 44.9 -> 2.1 ms a row live (`4a81f2a`); remaining: reconcile 0.6-2.6 s, lock wait up to 6 s. Earlier note: versions still saved (102 live); captures 4–9 s, anchor writes ~20 ms each on a 1.8M-address store. Per-branch timing now in; sidecar restarted — **read it next** |
| 21 | Push fixes to master | done locally | no git remote configured; `master` moved to each commit |
| 22 | Rotation lag with three browser tabs | partial | 131 fps measured with tabs on one page; G-101 showed ~1 fps frames when the panes were mis-arranged; orphan views (24) likely contributed. Re-measure after the restart |
| 23 | Ego retrieval controls vs the search bar; remove the slider | confirmed | PG-137-search-linked, run 82 |
| 24 | Dragging the graph tab breaks the app | confirmed (clean arm) | after the restart: 0 errors on a move (was 8 from orphaned views). Planted arm vacuous post-restart |
| 25 | Link navigation very slow | needs the reader | 320 ms on Wikipedia; need the page |
| 26 | archive.org nested shadow DOM; DuckDuckGo image search; "More results" not pressed | partial | "More results": G-176 confirmed run 2 (598 results; planted cap 3 rounds). G-158 clean passes (submit). archive.org M-10: 188/189 deep links (1 missing: web.archive.org "Web Sites"). **DuckDuckGo image search: not started** |

## PLUGIN_GOAL 135–136

| Item | Status | Next step |
|---|---|---|
| 135(a) `[]()` retrieval = plain triple retrieval + PageRank, no level heuristics | **not started** | read `domvec/search.py` ranking; route the gesture through it with the PageRank term |
| 135(b) panel views by SOURCE; one markdown interface everywhere | partial | one markdown panel confirmed for billboards, code, chats, slate, hover; source-specific views (browser chunk view) = item 137(4) |
| 135(b) markdown+browser pair pulls apart into two nodes with a solid link | **not started** | |
| 135(b) one gesture flips panel form <-> graph form | **not started** | |
| 135(c) chat code outputs become pickable magnetic nodes with solid links | **not started** | |
| 135(d) solid links toggle on/off by right-click (solid/translucent) | **not started** | |
| 135(e) panel page view draws the page's own pictures | confirmed | desktop width (PG-135-desktop-width) + per-host native fallback (PG-139-richardmille) |
| 135(f) Q.002: keep hover panes after they close | confirmed | Q-002 run 11: the closed VHS pane's text kept (as a version) after close and revisit; planted retire-in-session + no-versions: gone |
| 136 magnetizing never creates links | confirmed by inspection | snapping records neighbours only |

## PLUGIN_GOAL 138–139

| Item | Status | Evidence |
|---|---|---|
| 138 no long links | confirmed | PG-138-no-long-links |
| 138 UMAP refit | run, no effect, reverted | see 137(6) |
| 138 new DuckDuckGo searches (shipwrecks) | partial | G-158/G-176 pass on their queries; a "shipwrecks" image-search run is next with 137(26) |
| 139(a) richardmille.com broken | confirmed | PG-139-richardmille, run 9 |
| 139(b) flickering links | confirmed | PG-138-no-flicker |

## Earlier items still open

| Item | Status |
|---|---|
| G-21 / G-93 / G-94 coincident nodes | superseded in part by 138 (no long links); overlap ruling still the reader's |
| G-120 hover popup linked | confirmed (linking + 3D link); keeping = Q.002 above |
| G-198 grey markdown first | partial (104 ms; ordering of page form/projection unmeasured) |
| G-231 retrieval as the reader uses it | partial (page breadth confirmed) |
| D-36 / G-82 | resolved into 135(b); G-82 to be marked superseded |
| PG-134-drop-plane | confirmed (run 84) |
| ~60 PRD rows in **Partly** | see `build_analytics/design_state.md` |
