# Open work — tracked against PLUGIN_GOAL and the PRD

Kept by hand at the reader's request (PLUGIN_GOAL 138: "keep careful track of
all features/builds/tasks unstarted up until now with the full spec/docs/prd in
mind"). Each row names its verbatim item, its status, and the evidence. Status
words: **confirmed** (live check with a planted arm passed), **built** (code in,
not yet confirmed live), **partial**, **not started**, **needs the reader**.
The PRD's own computed status lives in `build_analytics/design_state.md`; this
file is the working list for items 130–139 and what they reopened.

Last updated 2026-11-07 late. A native store crash at CHECKPOINT (D-23 class, also at 18:11 before today's store change) was restarted by the supervisor.

## PLUGIN_GOAL 137 — the 26 reported glitches

| # | What | Status | Evidence / next step |
|---|---|---|---|
| 1 | Panel collapses while its markdown renders | confirmed (measured + screenshot) | head one row (29 px), body 270 px; `a6e6136`. No planted check yet |
| 2 | Chunk panels under the browser | confirmed | PG-137-panels-over, run 61 |
| 3 | Image+caption / infobox sub-chunking (Gay, NC) | needs the reader | store holds the box as ONE 18-line chunk; a live hover resolves to it. Not reproduced |
| 4 | Chunk views as browser cells, linked to markdown | confirmed | PG-137-chunk-browser run 51: on the chunk rung the LIVE browser stays, framed on the chunk by a clip-path on our webview element (nothing written into the page), re-framed each second as the page reflows; clip = element rect exactly (31.19/103.69 host px), the element at the frame's centre is the chunk's; its markdown beneath as the one editor panel (140a). Planted plantChunkMarkdownOnly: browser hidden. Found on the way: scrollIntoView({behavior:"instant"}) does not scroll in this Electron (rect read 3,400 px off); the store's /chunk is slow while capturing (memoised per cid) |
| 5 | Arrow keys run the search with an empty field | needs the reader | synthetic arrow press runs nothing; need the steps |
| 6 | Chunks clumped | confirmed (measured live); visual check owed | per-cluster rescale measured first and rejected (dense clusters are not small: r75 ~60 like sparse ones; the crowding is inside them). Built: a bounded relaxation (layout._declump) run over the whole placed chunk cloud after each fit, in the fit that serves the 3D view. Live, refits on 60,926 chunks: nodes inside half the median gap 2.1% clean / 31.1% planted no-declump / 2.2% clean again; p10 gap 0.645 / 0.121 / 0.609; 1.1-1.3 s per fit. Offline: true 10-NN kept 85.8%, largest move 2.3 on radius 418. Found on the way: the fit crashed on projections restored from state (no `declump` attribute) and the old layout kept being served |
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
| 26 | archive.org nested shadow DOM; DuckDuckGo image search; "More results" not pressed | partial | "More results": G-176 confirmed run 2 (598 results; planted cap 3 rounds). G-158 clean passes (submit). archive.org M-10: the "Web Sites" miss was the CHECK (its pattern cut an href at a space); fixed. Run 18: 215/219 deep links, the 4 missed now differ run to run (collection facets at depth 8) -- render timing, to be pinned down. DuckDuckGo image search ("shipwrecks"): captured once the queue was unblocked -- 29 chunks, 248 image lines / 222 distinct images for 100 tiles. It had been blocked by 110 refused bandcamp drains after a sidecar restart; fixed (PG-137-refused-queue, run 12) |

## PLUGIN_GOAL 135–136

| Item | Status | Next step |
|---|---|---|
| 135(a) `[]()` retrieval = plain triple retrieval + PageRank, no level heuristics | confirmed | PG-135-gesture-plain run 30: clean asks coarse=0, 10 hits; planted asks coarse on. Runs 22-29 failed because the check fired before the reloaded plugin reached the sidecar (no request made; also misread as "sidecar died") -- the check now waits for the plugin's own client to answer |
| 135(b) panel views by SOURCE; one markdown interface everywhere | partial | one markdown panel confirmed for billboards, code, chats, slate, hover; source-specific views (browser chunk view) = item 137(4) |
| 135(b) markdown+browser pair pulls apart into two nodes with a solid link | confirmed | PG-135-pull-apart run 34: the ⇹ control offsets the browser out of its card (same DOM parent, so 0 reloads, same URL), 50 px gap, kept inside the plane, a solid link edge to edge; right-click 0.95 -> 0.25; again rejoins. Planted plantPairNoLink: no link. Screenshots app_20261107_231537/231622. Seen alongside: the 2D browser cell showed about:blank under a slate reading frutigeraeroarchive.org -- fixed, PG-137-slate-url run 40 (clean shows the slate's url; planted plantNoRestoreUrl stays about:blank) |
| 135(b) one gesture flips panel form <-> graph form | confirmed | PG-135-flip run 39: a double-click on bare ground (the 3D canvas under the click-through plane) folds the panels within 700 px to their nodes and draws an undirected edge between each linked/magnetized pair (1 edge for a [[link]]); the same gesture flips back. Planted plantFlipNoLinks: 0 edges. Screenshot app_20261107_232303. Seen: folded nodes keep their panels' corners and can overlap -- spreading them is not built |
| 135(c) chat code outputs become pickable magnetic nodes with solid links | confirmed (cells + magnet) | PG-135-code-cells run 21: 2 code blocks -> 2 cells chained under the reply, both in the chat's context; planted none. Solid link drawing on the 2D plane: not yet |
| 135(d) solid links toggle on/off by right-click (solid/translucent) | confirmed (3D view) | PG-135-link-toggle run 20: on 0.95, off 0.05; planted 0.14 unchanged. Not yet: persisted across reloads; tied to compiled function-object calls; the 2D plane's panel links |
| 135(e) panel page view draws the page's own pictures | confirmed | desktop width (PG-135-desktop-width) + per-host native fallback (PG-139-richardmille) |
| 135(f) Q.002: keep hover panes after they close | confirmed | Q-002 run 11: the closed VHS pane's text kept (as a version) after close and revisit; planted retire-in-session + no-versions: gone |
| 136 magnetizing never creates links | confirmed by inspection | snapping records neighbours only |

## PLUGIN_GOAL 140

| Item | Status | Evidence |
|---|---|---|
| 140(a) one unified markdown panel; the fenced domvec block is deprecated | confirmed (chunk rung) | PG-140 run 52: the chunk's markdown is an editor leaf on domvec/chunks/<cid>.md; planted plantChunkFencedBlock: the old block. Swept 2026-11-08: no code writes the fenced block any more (the planted arm only); no vault note outside .trash holds one; the read-side processor stays for old notes |
| 140(b) graph forms are on the 2D plane, not contained by their panels; convert back | confirmed | PG-140 run 52: a slate in graph form loses its card's box, clip, head and browser half (transparent, overflow visible); flipping back restores the panel. Planted body.domvec-plant-graph-boxed. Screenshot app_20261107_235721 |
| reload artefact | not reproduced | seen once (raw slate, no graph form after many reloads and flips); two reload cycles 2026-11-08 (cell open across the reload, and opened after it) both drew variable nodes and entered graph form. The graph form's clipped 'forward false' label is whole (screenshot app_20261108_000716) |

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
