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
| 3 | Image+caption / infobox sub-chunking | confirmed (headings); infobox split is the rule | Durham, North Carolina (2026-11-08): its infobox is ~930 tokens (250+235+216+230), so under the reader's rule (a piece joins while the run stays under 1.5x the 256 window) it splits -- the rule working. The real defect found there: a heading's furniture (bracket line, "[Edit section: ...]" link, "See also:" hatnote) counted as content, so "## History" stood alone at 19 tokens instead of heading its 150-token section. markdown._FURNITURE: now joined, 170 tokens with "### Pre-establishment" (live recapture); planted furniture-is-content: 19 tokens alone. Markdown/chunk tests 209 passed. 38 of 394 chunks were under 64 tokens before, many of them page chrome |
| 4 | Chunk views as browser cells, linked to markdown | confirmed | PG-137-chunk-browser run 51: on the chunk rung the LIVE browser stays, framed on the chunk by a clip-path on our webview element (nothing written into the page), re-framed each second as the page reflows; clip = element rect exactly (31.19/103.69 host px), the element at the frame's centre is the chunk's; its markdown beneath as the one editor panel (140a). Planted plantChunkMarkdownOnly: browser hidden. Found on the way: scrollIntoView({behavior:"instant"}) does not scroll in this Electron (rect read 3,400 px off); the store's /chunk is slow while capturing (memoised per cid) |
| 5 | Arrow keys run the search with an empty field | confirmed | reproduced 2026-11-08 by elimination (body, ego cockpit editor, cursor moves, arrows over the 3D view: nothing): focus left in the search bar's k or n box -- Up/Down with the field empty fired onScroll (frontier re-render) and, for n, a run + clear. Now the number changes and nothing renders. PG-137-arrows-empty run 53: clean 0 renders (k 20->21, n 50->51); planted __domvecPlantArrowsEmptyRender: 3 scroll + 1 run + 1 clear |
| 6 | Chunks clumped | confirmed (measured + seen) | two parts. (i) geometry: layout._declump relaxes the placed chunk cloud after each fit -- live 2.1% / 31.1% planted no-declump of nodes inside half the median gap. (ii) the picture: the first visual check showed (i) alone did NOT read clearer -- 60,933 additive halos (>= 12 px each) stack ~7.9 per pixel and sum to white. scenebatch.setViewport now divides the halo by the stacking (k = 3 / 7.95 = 0.377 live). Seen 2026-11-08: build_analytics/halo_clean.png keeps node colours, separate points and edges in clusters; halo_planted.png (__domvecPlantHaloCrowd) burns clusters white. Same session, camera drifted slightly between the two shots |
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
| 18 | One browser tab navigates the others | confirmed (two causes) | (i) new-window links opened nothing (no allowpopups) -- PG-137-new-window run 54. (ii) the REAL "navigates the others": every tab restored the one vault-wide last page on open, so after any reload all tabs showed the last page visited in any tab (seen: B-tree / Shipwreck / Radix_tree all reopened on Rudolf_Bayer). Each tab now keeps its page by leaf id (leaf state alone was not enough: Obsidian rebuilt the background tabs without it on a plugin reload). Live, three tabs over a plugin reload: clean B-tree / Shipwreck / Radix_tree, each restored "own"; planted __domvecPlantSharedLastPage: Shipwreck x3, "shared" x3 |
| 19 | Retrieval re-triggers at high n / on scroll | confirmed | PG-137-rerank-debounce, run 58 |
| 20 | Bandcamp diff-stream saving | confirmed | 2026-11-08, window on screen, bandcamp.com 45 s each arm: clean -- 16 captures, capture p50 1.9 s, lock wait p50 0, store p50 1.6 s, reconcile p50 0.6 s, re-clusters mid-stream 0 (deferred until 8 s without a write); planted aggregate-mid-stream -- 12 captures, capture p50 3.5 s, lock wait p50 0.72 s, 6 re-clusters of ~3.1 s mid-stream. (Session-start profile, other conditions: capture 7.7 s, lock wait 3.7 s.) Earlier: anchor edges 44.9 -> 2.1 ms a row |
| 21 | Push fixes to master | done locally | no git remote configured; `master` moved to each commit |
| 22 | Rotation lag with three browser tabs | measured, not attributable yet | 2026-11-08, Obsidian VISIBLE but UNFOCUSED, three tabs (bandcamp, Shipwreck, Radix_tree), 1,407 nodes: rotation 5-8 fps. Not the scene: no long tasks, 5 draw calls, 4,754 triangles at 1130x767 on the Intel UHD (hardware ANGLE/D3D11); halo off and webviews hidden moved it inconsistently (5-15 fps). A BARE rAF loop -- no rotation, no work -- ran 35-800 ms a frame: the whole window is paced slowly while unfocused (CPU 19-29% total). Needs a measurement with Obsidian FOCUSED; earlier on-screen readings were 131 fps |
| 23 | Ego retrieval controls vs the search bar; remove the slider | confirmed | PG-137-search-linked, run 82 |
| 24 | Dragging the graph tab breaks the app | confirmed (clean arm) | after the restart: 0 errors on a move (was 8 from orphaned views). Planted arm vacuous post-restart |
| 25 | Link navigation very slow | measured: the site, not the plugin | 2026-11-08: real link clicks in the 2D cell on Wikipedia: dom-ready 200-370 ms, loaded <= 560 ms. In a right-hand tab, a DuckDuckGo result to oceanbeachbulletin.com took ~4 s; loaded directly with no click (null arm) the same page took 5.3 s to its first response (did-navigate, before the plugin sees the page) while Wikipedia took 260 ms. The delay is that server's. DuckDuckGo image tiles open DDG's own preview, not a navigation |
| 26 | archive.org nested shadow DOM; DuckDuckGo image search; "More results" not pressed | confirmed | archive.org: M-10 run 55 -- 229/229 deep links in the trie at their EXACT shadow depth (max depth 7), 0 missing (run 18 had missed 4 of 219); planted strip 8 exact, planted drop 0. "More results": G-176 run 2 (598 results; planted cap 3). DuckDuckGo image search "shipwrecks": 29 chunks, 248 image lines, 222 distinct images for 100 tiles once the refused-drain queue was cleared (PG-137-refused-queue run 12) |

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
| 138 new DuckDuckGo searches (shipwrecks) | confirmed | G-158/G-176 pass; the "shipwrecks" image search captured 29 chunks / 222 distinct images for 100 tiles (see 137(26)) |
| 139(a) richardmille.com broken | confirmed | PG-139-richardmille, run 9 |
| 139(b) flickering links | confirmed | PG-138-no-flicker |

## Earlier items still open

| Item | Status |
|---|---|
| G-21 / G-93 / G-94 coincident nodes | superseded in part by 138 (no long links); overlap ruling still the reader's |
| G-120 hover popup linked | confirmed (linking + 3D link); keeping = Q.002 above |
| G-198 grey markdown first | confirmed | run 67: on a purged page the first grey node appeared 1.8 s after navigation; its hover panel showed markdown at 173 ms, the page form at 283 ms, the chunk not yet placed -- markdown first, page form after, placement last; planted no-force-panel: no markdown. Run 60 (10.6 s to the first grey, everything at 81 ms) was a slow capture after a reload, not repeated |
| G-231 retrieval as the reader uses it | confirmed | G-231 run 58: n=200 -> 200 hits from 7 pages, top-2 share 0.40 (run 56: 174 hits, 5 pages -- a page handed back fewer chunks than it counted and nothing past the count cut was asked). Pages past the cut are now a reserve, asked in rank order while the set is short of n (planted plantNoReserve); planted plantUncappedShare: 5 pages, 0.67 |
| D-36 / G-82 | resolved into 135(b); G-82 to be marked superseded |
| PG-134-drop-plane | confirmed (run 84) |
| G-4 discernible, not a clump | built; at its ceiling, the bar is the reader's | cause found and fixed 2026-11-08: the plugin's chunk relax never finished a run at 1 Hz frames (8 ms slices, 62k nodes x 40 iterations) -- it now takes 250 ms slices when frames are >100 ms apart (planted plantRelaxFrameBound), and the G-4 check waits for a FINISHED relax before its census. Runs 65/66: pages 97.4% clear, pages rebuilt 97.3-97.5%, chunk view 94.2% (40 iterations) / 94.4% (80 -- not worth double the time, kept 40), planted raw points 43.1%. Same ceiling as 2026-10-30 (94.7%): dense cores of near-duplicate chunks the leash cannot open. The 95% bar was MY reading of "most", recorded as such in the PRD -- whether 94% is "most" is the reader's call |
| R-C5 chunks at the context window | partial (code fixed) | 2026-11-08 store sweep (928 pages, window 256): largest chunk was content_tagger.py at 6,368 tokens (25x) -- a class's code value held every method's source, emitted again per method, and long docstrings / JS files were single values. source.py now emits a node's OWN lines (nested defs are their own addresses), cuts bodies at lines and docstrings at paragraphs to ~256 tokens (planted PLANT_WHOLE_BODIES). Re-indexed 31 repo modules and the html/http/json/urllib stdlib packages (POST /package): pages with a chunk over 1.5x went 77 -> 38; code 40 -> 1 (sensor.js, 626, which /source refuses as non-Python). Left: web 36 pages (worst 872, reddit), 1 pdf (1,407). Source tests 110 passed. The worst left are SINGLE over-long lines -- reddit's faceplate-loader `concat:` id list (798 chars, one line), the GPT-3 PDF's flattened results table (2,359 chars, one paragraph line). A line is one trie address, so cutting inside a line changes what an address is: the reader's ruling, with D-2/T-1 |
| G-145 tens of thousands of nodes without a freeze (PRD DEFECT) | reproduced | 2026-11-08 long-task census over a switch to the 62.7k-node chunk view (window visible, unfocused): two freezes of 2.8 s and 2.5 s, ~30 tasks of 400-500 ms, the view not at 50k nodes within 60 s. Found and fixed on the way: the relax's 250 ms background slice fired on any frame gap > 100 ms, so an unfocused visible window took 95 stalls > 200 ms in 45 s; now only at > 900 ms gaps (the minimized 1 Hz signature). CPU profile of 60 s from the switch (webContents.debugger, 1 ms sampling), self time: d3 forces over all nodes each tick (w4 wrapper, 3.4 s) + force re-initialize on data changes (initialize/force.initialize ~4 s); per-node look/colour (baseLook/lookOf/colour ~5.9 s); edge build + covered-set bookkeeping (addEdges, expandedUrls, collapseCovered ~5.6 s); GC 3.1 s. The motion recorder is gated (forceBefore returns at once). Built: the zero-strength link force is skipped in chunk view (planted plantLinkForceAtZero). Measured, 60 s after the switch each arm: stalls >200 ms 77 vs 108 planted, but blocked time 44.4 s vs 45.2 s of 60 -- the main thread is busy ~74% of the minute either way. The link force was not the main cost; Then found the real driver: applyForceDelta, per STREAMED delta, copies all ~62k nodes, filters ~52k links, maps every node, and hands 3d-force-graph whole new data -- a full force re-initialize per delta. Built: a batch of deltas shares one rebuild, large graphs wait 400 ms to gather (planted plantDeltaPerApply). At 400 ms it did not help (244 rebuilds, 14 merged -- deltas arrive spread out); over 20k nodes they now gather 2 s: 60 s after the switch, rebuilds 21 vs 71 planted, blocked 36.4 s vs 45.5 s, stalls >200 ms 54 vs 85. G-198 still passes at page level (grey 1.4 s, markdown 194 ms). Still ~60% busy: Next (a core change): a delta must cost O(delta) -- streamed nodes kept out of the 62k-node graphData (their own small layer / straight into the scene batch), so one delta never re-initializes the whole graph |
| ~60 PRD rows in **Partly** | see `build_analytics/design_state.md` |
