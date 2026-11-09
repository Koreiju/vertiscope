# Open work — tracked against PLUGIN_GOAL and the PRD

Kept by hand at the reader's request (PLUGIN_GOAL 138: "keep careful track of
all features/builds/tasks unstarted up until now with the full spec/docs/prd in
mind"). Each row names its verbatim item, its status, and the evidence. Status
words: **confirmed** (live check with a planted arm passed), **built** (code in,
not yet confirmed live), **partial**, **not started**, **needs the reader**.
The PRD's own computed status lives in `build_analytics/design_state.md`; this
file is the working list for items 130–139 and what they reopened.

Last updated 2026-11-08 evening (items 141-147 below). Earlier: 2026-11-07 late. A native store crash at CHECKPOINT (D-23 class, also at 18:11 before today's store change) was restarted by the supervisor.

## PLUGIN_GOAL 141-147 -- 2026-11-08

| # | What | Status | Evidence |
|---|---|---|---|
| 141/143/145 T-1,T-17 | UMAP the authority; one bounded spacing pass; no telescope | confirmed | frames with motion while streaming 2/2,260 vs planted 436/1,528 (`6676422`) |
| 143 | pane loaded before the fit stays on force layout | confirmed | late fit asked 1 / loaded 1 vs planted 0/0 (`380e798`) |
| 143 | strict UMAP for streamed, not-yet-placed nodes (no force layout at all) | partial | the caption no longer says "no embedding needed"; unplaced streamed nodes are still drawn by their parent until the fit places them |
| 143 | sidecar /health stall | confirmed | 20.05 s timeout -> 0.01-0.04 s (`2d396a3`) |
| 143 | UMAP slow | partial | fit read 25-30% less (`f2338c5`); chunk transform and redraw still seconds |
| 143 | sidecar process split (micro-processes, PG 4519) | approved (148), not started | shape: an always-answering front process; workers own store, encoder, UMAP fit |
| 137(6) | white mass in the pages view | confirmed | halo stack 8.2 / k 0.366 vs planted 0.14 / 1 (`b9518c9`) |
| 144 | workspaces per vault, menu, own port | confirmed | to scratch-144 and back, both listed, ports kept (`e6055f5`) |
| 147 | new vaults get the plugin; sidecar autostart | confirmed (install) / built (autostart) | `test` vault enabled, 4 older skipped (`380e798`) |
| 146 | ego craft centred, turns with heading | confirmed | centred 0-1 units vs planted 8,650-18,431; 88 deg turn vs 0 (`380e798`); hidden in first person (`e6055f5`) |
| 142 T-11 | magnetised cells compile row-major | confirmed | A,B,terminal,chat vs planted BFS (`796ec71`) |
| 142 | PowerShell terminal as a plane cell | confirmed | mounted in its card (`796ec71`) |
| 142 T-10 | governing artifact generates the browser panel | confirmed | reader field appears vs planted absent (`368c944`) |
| T-8 | click halo, double-click panel | confirmed | `0d06f36` |
| T-12 | idle drift off by default | confirmed | 0 vs 0.106 rad (`9d03cf9`) |
| UR N.4 | left-drag wiring in graph form | confirmed | 1 edge vs 0 (`3f6083a`) |
| O.14 | delete a halo result, the next comes in | confirmed | with 18 same-kind fixture notes: 13 shown, reserve 4; dismissed -> 13 shown, gone not shown, refilled 1; planted plantNoRefill -> 12 (`c859b9e`) |
| T-14 | per-workspace Python environment | closed by the reader (148): one shared interpreter | |
| G-145 | streaming-layer rework | partial, re-measured | 2026-11-08 after T-1 (no forces in either view): bandcamp streaming into the 62,694-node chunk view, 60 s: main thread blocked 28.2 s (was 40.6), 154 long tasks, 1 freeze > 1 s (was 1), 17 rebuilds. One rebuild = ~230 ms against a ~30 ms idle frame, so rebuilds are ~4 s of the 28; the other ~24 s are not yet attributed (next: a CPU profile of the stream's apply path and the scene batch's per-sync work over 62k instances) |
| T-4 | `{ref}` between plane cells is a hard link | confirmed | linked both ways vs planted none (`31592c5`) |
| T-15 | pydantic types from trie-path patterns | confirmed | 8,028 instances / 51 pages / 20 fields live; planted split fields (`082aa33`) |
| 140/5364 | one unified markdown panel | confirmed (no defect found) | right-click pins become plane panels (side card only under its plant); stuck billboards mount the editor cell |
| T-13 | outputs in retrieval, ego only by default | confirmed (for outputs chunked on their own) | a 600-token output: unset search [] vs ego [/section/output]; planted outputs-everywhere: found unset too. An output small enough to share a chunk with prose stays with it (the chunk is the unit) |
| T-16 | rank-dominance collapse for every node | confirmed | ruled by PLUGIN_GOAL 145: a node dominates what extends its trie path (deeper url paths; deeper xpaths). archive.org/ folded 29 pages (1,011 -> 982) and unfolded (1,011); planted plantNoTrieDominance: the page fold ran instead |
| T-5 | chunk = framed browser + markdown on one chunk object | stands (137(4) confirmed) | |

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
| 135(c) chat code outputs become pickable magnetic nodes with solid links | confirmed (cells + magnet) | PG-135-code-cells run 21: 2 code blocks -> 2 cells chained under the reply, both in the chat's context; planted none. Solid links on the 2D plane: PG-136-memory-links (code output -> its reply) |
| 135(d) solid links toggle on/off by right-click (solid/translucent) | confirmed (3D view) | PG-135-link-toggle run 20: on 0.95, off 0.05; planted 0.14 unchanged. The 2D plane's panel links + persistence: see 136 (PG-136-memory-links) |
| 135(e) panel page view draws the page's own pictures | confirmed | desktop width (PG-135-desktop-width) + per-host native fallback (PG-139-richardmille) |
| 135(f) Q.002: keep hover panes after they close | confirmed | Q-002 run 11: the closed VHS pane's text kept (as a version) after close and revisit; planted retire-in-session + no-versions: gone |
| 136 magnetizing never creates links; links come from the computation graph | confirmed (both arms) | PG-136-memory-links run 70: plane panels joined ONLY by computation-graph links -- a code output's `from:` its reply drew 1 solid line; a magnet-snapped panel with no call drew 0; right-click 0.95 -> 0.25, and the state KEPT after both panels closed and reopened (135d persistence, by pair key); planted plantNoMemoryLinks: 0. Run arm: PG-136-run-links run 71 -- a cell naming another plane panel's note by {ref}, run with its Run button: 0 lines before, 1 after, from the store's recorded run (/signal, from_signal 1); planted: 0 |

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
| G-145 tens of thousands of nodes without a freeze (PRD DEFECT) | reproduced | 2026-11-08 long-task census over a switch to the 62.7k-node chunk view (window visible, unfocused): two freezes of 2.8 s and 2.5 s, ~30 tasks of 400-500 ms, the view not at 50k nodes within 60 s. Found and fixed on the way: the relax's 250 ms background slice fired on any frame gap > 100 ms, so an unfocused visible window took 95 stalls > 200 ms in 45 s; now only at > 900 ms gaps (the minimized 1 Hz signature). CPU profile of 60 s from the switch (webContents.debugger, 1 ms sampling), self time: d3 forces over all nodes each tick (w4 wrapper, 3.4 s) + force re-initialize on data changes (initialize/force.initialize ~4 s); per-node look/colour (baseLook/lookOf/colour ~5.9 s); edge build + covered-set bookkeeping (addEdges, expandedUrls, collapseCovered ~5.6 s); GC 3.1 s. The motion recorder is gated (forceBefore returns at once). Built: the zero-strength link force is skipped in chunk view (planted plantLinkForceAtZero). Measured, 60 s after the switch each arm: stalls >200 ms 77 vs 108 planted, but blocked time 44.4 s vs 45.2 s of 60 -- the main thread is busy ~74% of the minute either way. The link force was not the main cost; Then found the real driver: applyForceDelta, per STREAMED delta, copies all ~62k nodes, filters ~52k links, maps every node, and hands 3d-force-graph whole new data -- a full force re-initialize per delta. Built: a batch of deltas shares one rebuild, large graphs wait 400 ms to gather (planted plantDeltaPerApply). At 400 ms it did not help (244 rebuilds, 14 merged -- deltas arrive spread out); over 20k nodes they now gather 2 s: 60 s after the switch, rebuilds 21 vs 71 planted, blocked 36.4 s vs 45.5 s, stalls >200 ms 54 vs 85. G-198 still passes at page level (grey 1.4 s, markdown 194 ms). Also built: a delta that changes nothing drawn skips the graph hand-over and the reheat -- measured with bandcamp streaming, 60 s each arm: rebuilds 21 (+34 no-op deltas skipped) vs 69 planted, blocked 40.6 vs 47.4 s, stalls >200 ms 39 vs 53, freezes >1 s 1 vs 3 (an earlier census had the next census saw no streamed deltas at all -- and WITHOUT a stream the chunk view blocked 9.5-12 s of 60, no freeze over 1 s, against 36-45 s with bandcamp streaming: the stream is the cost). Still ~60% busy while streaming: Next (a core change): a delta must cost O(delta) -- streamed nodes kept out of the 62k-node graphData (their own small layer / straight into the scene batch), so one delta never re-initializes the whole graph |
| ~60 PRD rows in **Partly** | see `build_analytics/design_state.md` |

## Reader's answers 2026-11-08 (148)

- G-4 closed at 94.2% (approved).
- D-12 spherical layout closed (approved: dropped).
- D-2/T-1 chunk trie re-key to five levels + R-C5 over-long single lines split: approved, not started.
- Disk cleanup: not approved; nothing deleted.

## Ego re-check, 2026-11-08 evening (PLUGIN_GOAL 149)

| What | Status | Evidence |
|---|---|---|
| craft much smaller | confirmed | extent 119 -> 33 units (`93fda82`) |
| craft not buried in the world | confirmed (seen) | drawn over the world, screenshot (`3e691dd`) |
| computing triple lit (readout) | confirmed | readout lit vs planted not (`3e691dd`) |
| computing triple lit (input lines) | built, unmeasured | the store's one recorded run is on a non-craft note |
| ego controls, confirm run 1 | 10 of 13 pass after G-273's fix | G-271, G-273 (`239ba57`), G-281, G-282, G-283, G-284, G-285, G-331, G-333, G-334 |
| G-275 plan leg drawn in the ego view | open | after map -> ego the craft moved 3.3 units in 20 s and never reached leg 1 (G-283, the cockpit's plan, passes) |
| G-280 cockpit throttle text vs agent | open | after Shift the text read 45, the agent 40 |
| G-270 store-wide dedup | open | 66 contents drawn twice, 101 extra group leads |
| live memory structures from recursive calls (PG 4909) | not started | |

## Ego checks, full re-run 2026-11-08 20:22 (confirm runs 6-7)

8 of 13 pass: G-270 (now passes: projected_not_drawable 0), G-273, G-281,
G-282, G-284, G-331, G-333, G-334. REGRESSED since run 4 (18:58): G-271,
G-275, G-280, G-283, G-285 -- flights do not close (G-271 cruise 20 at
throttle 0.25 where 40 is expected; min_d 531 not the 24 floor), G-283 leaves
play "true" in the text at the end, G-280's cockpit circle is null.
Not yet attributed. Changed since run 4: idle drift on by default (now held
off while the craft flies -- did not fix it), the cockpit's camera field and
play write-back, tethers, memory rings, near-shrink, graph-card sizing. The
ego note's text was also left by checks at throttle 100 / camera first.
Next: bisect with each new binding planted off, starting with the cockpit's
camera field and play write-back (they act on the same note the checks drive).

## Ego checks back to 13/13 (2026-11-08, confirm run 23)

Runs 11-22 named five real defects behind the failures. Fixing them, not loosening the checks, is what brought the set back:

- **Craft rebuild loop (no check saw it).** The vault is the repository, so the sidecar's `requests.log` and `graph.kuzu.wal` are vault files. Each request the craft's rebuild made wrote the log, which rebuilt the craft again: 67 rebuild requests in 8 s at rest. Now only `.md` changes mark the craft dirty. Measured: 0 builds in 15 s; planted `plantCraftAnyFile` gives 8.
- **G-331: a readout is in the craft when its run ends.** The craft read every note from disk, and a run's output sits in the editor until autosave, so the pulse stopped at the cell. Now an open panel's live text is read (`liveText`), and a run's end rebuilds the craft (`fresh()`, bounded at 1.5 s) before pulsing. Clean: 2 hops per pulse. Planted `plantDiskText`: no readout, 1 hop.
- **G-270: a purged note leaves the projector at once.** `/purge` removed the chunks but never told the projector, so they stayed drawn until the 180 s idle reconcile. Fixture notes from G-282 and G-284 were named by the new `not_drawable_sample`. Now `/purge` queues the page's held chunks. Clean: held 1 → 0. Planted `purge-keeps-projected`: still 1.
  - **`lead_vectors` now agrees with the drain.** A group lead with an all-zero group vector falls back to its own vector in both (unit test plus a planted arm).
  - **The reconcile's `not_drawable` mark is one-shot.** A content address that is stored again is drawable again.
- **G-284: a stream delta during a halo moves a transported node's HOME, not the node.** Without this, a delta (for example the purge above) put halo nodes back at their fit under the halo. That was order-dependent: G-284 failed right after G-282. Clean: node moved 0, home moved 40. Planted `plantHaloOverwritten`: dragged 606 units off the cone.
- **Check fixes (each named in the check):**
  - **G-280:** reads the cockpit title in text form when the slate was left in graph form, and restores the form.
  - **G-285 and G-271:** pick world-drawn web pages, because a vault note can be the ego's (PLUGIN_GOAL 76: radius 0 in the world).
  - **G-270:** reads the projector until it settles (30 s cap) and reports the first snapshot too.

## Cockpit camera field on (149/150 "selecting the camera view"), confirm runs 24-27

- **The binding works both ways, at rest.** V writes the view into the slate's `camera` field, and an edit of the field picks the view. G-333 has a new arm. Clean: text `third` after V, view `first` after the edit. Planted `plantNoCameraField`: the text stays `first`.
- **Turning it on surfaced one more feedback path.** Every cockpit write-back (camera, throttle, lit key) is an edit of `domvec/ego.md`, and each one rebuilt the craft, although the craft never reads that text. Run 25: G-331's run-end rebuild waited behind them, and the pulse left before the readout existed. The cockpit note no longer marks the craft dirty.
- **G-284's drop is read as it lands.** A stream delta after the drop is the map's to make.
- **Run 26: 12/13.** G-271 cruised 38 vs 45 (18%, its band is 15%). Re-run straight after G-333 (run 27): 40.8 vs 40.5. Recorded as a timing excursion, not a pass. Watch it.

## Confirm run 30 (2026-11-09): 8/13, at 1.5 fps

Every failure in this run depends on frames:
- **G-271 and G-285:** flights did not arrive in time (end_d 312).
- **G-275 and G-282:** the planted arms had not redrawn yet.
- **G-331:** the readout was not there at the pulse.

Measured straight after the run: 1.5 fps, with `document.visibilityState` reading visible and the window focused. Each render takes about 1 ms and there are no long tasks, so the main thread was idle. The browser was delivering frames slowly, which looks like the OS throttling an occluded window. That is not the plugin.

Run 23 (13/13) and runs 26-29 were taken at normal frame rates. Re-run the full set with the Obsidian window uncovered before reading these results as regressions.

## Ego checks after R-C5, the camera field and the Obsidian restart (2026-11-09)

The 8/13 runs were taken with the window MINIMIZED. `BrowserWindow.isMinimized()` was true while `document.visibilityState` still read visible, and the window ran at 1.5 fps. Restored, it runs at 240 fps.

Run 2, uncovered: 12/13. G-331 measured nothing on all three arms (no edges, no pulses, 94 s), which points to a cold kernel straight after the Obsidian restart. Re-run alone (run 3): pass. Clean: 2 hops per pulse with the readout present. Planted plantDiskText: no readout, 1 hop.
