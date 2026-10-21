# Audit VIII — the app, used, against the verbatim

Addendum VIII (2026-09-26) asks for the app to be audited by USING it: the
interactions the design implies, performed in the running app, with their
records kept, including the peripheral changes each one causes; and every
finding traced from the verbatim to what the app actually did. This file is
that record. It is appended to by the audit loop; the newest pass is last.

## The chain

Each user story is one reading of a verbatim sentence. Each is served by
requirement rows, checked by live checks (run inside the plugin, `G-75`),
reachable by MCP tools, and backed by unit tests. The last column is what the
app DID when the story was performed, on a fresh store the run seeded itself
(`G-87`), unless it says otherwise.

| # | user story (verbatim source) | rows | live check · MCP | app, 2026-09-26 |
|---|---|---|---|---|
| U-1 | I see the scan pipeline's statistics as a small black box in the browser's bottom-right corner, and collapse or expand it; so can the MCP tools (VI: *"a simple open/closed scrollable readout"*) | G-76 | `G-76` · `ui_act pipebox` | passes |
| U-2 | Hovering anything on the page outlines the whole chunk that draws it, at its on-screen box, fast, and rings its node (VI: *"matches the cartesian coordinates"*; VII f/u: *"super super slow and inaccurate"*) | G-79, G-38 | `G-79` · `ui_act` | passes: p95 7 ms, extent 0.01 px (`fd09302`) |
| U-3 | Right-clicking pins the chunk: the outline stays, its markdown goes to a side panel beside the page, its billboard opens in the graph and persists with it (VI) | G-78, G-39, G-82 | `G-78`, `G-39` · `ui_act pin` | passes. **Fixed:** the check wanted the page to switch away (a retired design) |
| U-4 | What is pinned follows the page: a change on the page reaches the pinned markdown and the billboard (VI: *"full-span chunk persistence"*) | S-12, G-78 | `S-12` | **was broken, fixed**: the side panel stayed stale (F-3) |
| U-5 | A chunk node shows one picture and opens to the whole chunk (VI) | G-81, G-15 | `G-81`, `G-15` | passes |
| U-6 | Every test runs inside the app, driven by MCP, on real actions (VI: *"hardware in the loop"*) | G-75 | all · `confirm`, `verify_state` | passes; record now merges (F-1) |
| U-7 | Every test suite starts from a fresh, empty store (2026-09-26) | G-87 | `fresh` · `confirm {fresh:true}` | built; 12/12 pages seeded from 0 |
| U-8 | Pages are placed by UMAP of page centroids only (VII) | G-83 | — | gated off; not the default |
| U-9 | Left-click opens a page's whole tree, right-click closes it, links long (VII) | G-84, G-85 | — | not built in the pane |
| U-10 | A heading and the paragraph it heads are one chunk (VII f/u; decisions) | G-86 | — | not built |
| U-11 | O(delta) ms-profile traces, interlaced with the above (VI) | G-73, G-80 | `G-80`, `G-12` | `G-12` passes; `G-80` open |
| U-12 | Every node is on screen at the default camera | G-5 | `G-5` | **fails**: 33 of 41 (F-6) |

Stories U-8..U-10 have rows (added 2026-09-26, `G-82..G-88`) but no check
yet: the verbatim reached `DESIGN_VII.md` and stopped there, where no status
column could see it.

## Findings

**F-1. The record of what was SEEN working forgot on every run.**
`confirm.mjs` replaced `live_confirmations.json` each time, so a three-check
run on 2026-09-26 erased every earlier verdict, and `design_state.md` then
said 135 done rows had no live check. The in-app runners (MCP `confirm`, the
fresh-store runner) never wrote it at all. Fixed: one writer
(`vertiscope/obsidian/confirmations.py`) that merges by requirement and records,
per verdict, its date, commit and **which store it read**.
`tests/test_confirmations.py`, planted arm: the replace-style write loses the
rows.

**F-2. The checks read a store no current code wrote.** Every check ran
against `build/corpus123`, written over weeks by past sensors, chunkers and
drains, and damaged by each crash. Fixed: `python -m vertiscope.obsidian fresh`
seeds an empty store through the plugin (the browser cell lands on each page,
exactly the product's path) on a second sidecar, runs the checks, and puts the
plugin back. The working store is never opened. First full run: **29 of 36**;
after the fixes below, the 7 failures are down to 1.

**F-3. A pinned chunk's side panel went stale — a REGRESSION a stale check
hid.** Fixed in the old chunk pane on 2026-09-20; Addendum VI retired that
pane and moved a chunk's forms to a pin, and the refresh did not move with
them. S-12 kept opening the retired pane and failed on "view.show is not a
function", which reads as a harness fault, not a regression. Measured after
rewriting S-12 to the pinned forms, on the old build: side panel 364 chars
before and after the page added an item; billboard 4,873 -> 4,964. Fixed:
the capture's `dirty_cids` re-read each pinned chunk they name, and redraw
each open billboard they name (not only newly placed ones). New build: side
364 -> 455. **Lesson:** when a surface is retired, its checks move with its
DUTIES, or the duty is lost while its check keeps failing noisily.

**F-4. Clean-up deleted pages the check did not make.** S-7 and S-8 purged
fixture pages by FILE NAME, so they deleted the seeded
`shadow_catalogue.html` too and then failed their own "page count unchanged"
(13 -> 12). Invisible on the old store, which had no such page. Fixed: purge
by the check's own fixture origin (a port per check).

**F-5. Three checks asked questions the store could not answer.** G-70
searched the literal "header" (0 hits on a store about trees and tables); G-63
asked about the biggest merge group, a row of book covers with no words, then
about words taken from link targets ("ref-aho") that the lexical index never
held; G-39 demanded a retired face switch. All three now choose from the
store, or assert the current rule; all pass on the fresh store, and each still
fails on the defect it names (G-39: a face switch; G-63: identical rankings).

**F-6. Not every node is on screen (G-5, open).** 33 of 41 after earlier
checks opened pages. The earlier split was page level fine, chunk level 21%
off; the fresh run shows the mixed case. Next pass: reproduce by hand.

**F-7. Same page, same code, different chunk counts.** Seeding the same six
public pages twice, minutes apart, on empty stores: B-tree gave 227 new chunks
once and 205 the other time; every other page matched to the chunk. Either
the page moved or the seeder moves on before a page's capture has finished.
Next pass: two stability maps of B-tree (`--stability`), then compare against
the seeder's "held" signal.

**F-8. The crash does not happen on a fresh store.** D-23 (kuzu segfault in
relationship MERGE) hit `corpus123` every ~2 minutes this afternoon; three
fresh-store runs (seed + 36 checks, and two partial runs) crashed zero times.
A lead on the root cause: store size or state, not load alone.

**F-9. Citation metadata may be leaking into chunk text.** G-63's chosen
words on the fresh store included "Ajournal genre unknown jtitle", which
reads like COinS metadata (Wikipedia's hidden `Z3988` span). Next pass:
resolve that chunk and read its lines.

## Peripheral effects to watch

- A check that opens a view type the plugin no longer registers leaves a
  blank leaf behind (the old S-12 did this every run).
- `fresh` switches the plugin's `sidecar` setting for the run and restores it
  in a `finally`; a run killed from outside leaves the plugin pointed at a
  dead port. The restore is visible in `fresh_run.json` (`previous_sidecar`).

## Pass 2 — the streaming layout, timed (2026-09-26, evening)

Collected before fixing, per the user's instruction. Each row comes from a
250 ms timeline of the running app while a reader's gesture happens (probe:
browser url/loading, graph mode and node counts by kind and page, force
nodes, projected-chunk drift from their fit, diff boxes, pin outlines, the
chunk map, the projector stream's sequence). Scenarios: A land on a stored
page, B land on a new page, C scroll a long stored page, D page to page and
back, E hover sweep.

### Streaming: 3D nodes

| # | what the app did | evidence |
|---|---|---|
| S-1 | **A stored page's projected chunks reach the 3D graph 3-4 s after landing**, though the projector has held their positions all along; they come through the placement queue behind the page's first capture | A: landed 1.36 s, 52 chunk nodes at 5.21 s |
| S-2 | **Meanwhile the first drain draws the page's whole chunk set as force nodes -- for content already projected** (the diff rule only sees what is DRAWN, and the projected nodes are not drawn yet) | A: 145 force nodes at 2.38 s on Radix tree, all collapsed at 5.21 s; C: 564 on Hash table, 14 still up 15 s later |
| S-3 | **The next page's 3D waits behind the previous page's settle.** `pageChanged` awaits the settle capture of the page left before placing the new one | D: Trie after Hash table -- 0 chunk nodes for 6 s; B-tree the same |
| S-4 | **After the fit, a page with a projected node but no chunks drawn gets NO force nodes (collapsed rule), then gets them 2 s later when its projected chunks arrive** -- the pending diff appears after the projection instead of before it | B: projected chunks 3.10 s, 137 force nodes appear with them, collapse by 6.5 s |
| S-5 | **The page's chunk set churns for ~9 s after landing** as successive captures re-partition it (projected nodes added and retired: 71 -> 83 -> 71) | B |
| S-6 | **Chunk nodes of pages the reader has left never collapse back into their page node**; they accumulate | B-D: other pages' chunk nodes 52 -> 122 -> 248 -> 280 |
| S-7 | **Projected chunk nodes are pushed off their transform positions** -- up to 12-23 units steadily, with spikes to 89 / 297 / 398 while force nodes and stream updates arrive (collision with the force cloud, reheats) | A-D drift_max |
| S-8 | **Some stored pages have no page node in the page view** until the stream adds one | C: Hash table page_here false until 7.6 s |
| S-9 | Pending force nodes that are never covered linger (timeout 20/90 s) | C: 14 force nodes 15 s after landing |

### Streaming: 2D browser highlights

| # | what the app did | evidence |
|---|---|---|
| H-1 | **Landing on a stored page flashes its whole first drain as the "diff"** (20-34 boxes) although nothing changed against the store | A, D, E |
| H-2 | A pin's outline covers only the clicked element after a re-partition (the map does not yet hold the new chunk) | Suffix tree pin, item 5 only |
| H-3 | A pinned chunk's billboard for a chunk the re-partition replaced stays open (stale cid) | screenshot, be475590 |
| H-4 | Synthetic hover sweeps did not register until the pointer jiggled -- the known Chromium `:hover` lag; G-79's check handles it, the probe did not (not an app defect) | E |

### Markdown in the chunk (what the card and the billboard show)

| # | what the app did |
|---|---|
| M-1 | A list item's sentence is split into fragments around each inline element ("numbered from" / `$1$` / "to" / `$n$` / ".") -- `_join_inline` joins prose lines but not list-item fragments |
| M-2 | MediaWiki furniture in chunks: the "[ edit ]" section link and "Edit section: X", citation link targets `](#cite_note-7)`, `data-mw`-style JSON on non-math elements (`{"name":"ref",...}`, `{"title":{"lang":"x-page",...}}`) |
| M-3 | The Python scan files tail text under the preceding inline element (reading order, fixture xfail) -- the live sensor is not affected |

### Projector and graph (open from before)

| # | what |
|---|---|
| P-1 | Page-centroid UMAP (`G-83`) is built but not the default; whole-tree open/close (`G-84`) and long links (`G-85`) not in the pane |
| P-2 | `G-5`: not every node on screen at the default camera (33 of 41) |
| P-3 | The same page seeded twice gave different chunk counts (B-tree 227 vs 205) |

### Robustness and harness

| # | what |
|---|---|
| R-1 | The sidecar crash (`D-23`) left a write-ahead log kuzu could not replay; the store would not open until it was set aside by hand. The supervisor should detect that failure and quarantine the log itself |
| R-2 | The disk is 98% full (40 GB free) under a 21 GB store |
| R-3 | A plugin reload drops every pin |
| R-4 | The first right-click after a page load was once swallowed (G-39 now retries and says so) |
| R-5 | The MCP server in the session predates today's tools until it restarts |

### What the user asked to be decided: when do projected chunks collapse?

Today a page's projected chunk nodes are added when it is browsed and never
leave (S-6), and force nodes are drawn by what is drawn rather than by what
is projected (S-2, S-4). Proposed, and built next:

1. **On landing, the page's projected chunks come from the projector at once**
   (positions served with the page's chunk map, one call, ~50 ms) -- S-1.
2. **Force nodes are the TRUE diff only**: chunks the store does not hold, or
   whose content changed, until the transform places them -- S-2, S-4, H-1.
3. **The browsed page is expanded; when the reader leaves it and its diff has
   been transformed, its chunk nodes collapse into its page node** -- S-6.
   A pinned chunk stays drawn wherever its page is.
4. **Landing never waits on the previous page's settle** -- S-3.
5. **Force nodes do not collide with projected ones** -- S-7.

### Pass 2 — where each finding stands (2026-09-27)

Fixed, each seen in the running app on fresh stores the app filled itself
(the 12 streaming checks went 6 -> 8 -> 9 -> 11 of 12 across the round):

| # | fix | measured after |
|---|---|---|
| S-1, S-8 | `/page_map` serves the page's projected chunk nodes and page node from the projector's memory; drawn on landing | stored page: projected chunks 150-600 ms after landing (was 3.6-5.2 s) |
| S-2, H-1 | pending = the TRUE diff: stored-before-visit content is settled; coverage walks inline ancestors to the block; never-stored content remembered per page and address | force nodes on a stored page 0-2 (was 145-564); diff flash 0-2 boxes (was 20-34) |
| S-3 | landing places before settling the page left | the next page's projected chunks no longer wait 6 s |
| S-4 | a page with no projected node draws its force tree at once; pending diff hangs from the projected chunk its parent collapsed into | new page: tree in 0.1-0.9 s, collapsed in 1-5 s |
| S-6 | leaving (blank included) drops the page's diff and, once settled, collapses its projected chunks into its node; late results for a left page add nothing; reader-opened pages and pins stay | other pages' chunk nodes: 0 after leaving (had grown to 280) |
| S-7 | force nodes take no collision room; O(drain x graph) page lookups removed | per-node p95 0.2 ms on 500-chunk drains; small drains p95 0.7-0.9 ms |
| S-9 | never-stored and undrawable (group member / duplicate) coverage settles instead of timing out | pending force nodes reach 0 after the fit |
| — | overlay paints BEFORE the 3D update (same task had held the paint) | drain -> overlay p50 4.2 ms (was 545 under a large graph), -> 3D p50 8.4 ms |
| — | capture session restarts when the page's sensor restarts (stale dictionary wrote `'?'` addresses) | 58 garbage chunks on 3 pages found, purged, re-captured clean |
| — | drains no longer throw when the graph pane is an unloaded background tab | nothing had been captured while it was |
| — | chunk map: newer chunks take over only at or below their root | G-79 back to passing |
| M-1, M-2 | formulas fold into their sentence; `data-mw` dropped from the projection | Suffix tree list items read as sentences |
| R-1 | supervisor sets an unreplayable write-ahead log aside after two failed opens | tests + planted arm |
| harness | checks isolated (pins, menus, billboards, live capture, idle guest); stale test sidecar freed; live capture restored | late input under load no longer contaminates the next check |

Still open: S-5 (a stored page's chunk set churns for seconds after landing
while captures re-partition it), H-3 (a billboard for a chunk a re-partition
replaced stays open), M-3 (the Python scan's tail-text order), R-2 (disk 98%
full), R-3 (a plugin reload drops pins), P-1 (page-centroid UMAP not the
default; whole-tree open/close; long links), P-2 (`G-5`), P-3 (seed count
variance).

## Pass 3 (2026-09-27) — the unified loop's first pass: pictures against measurements

Addendum IX's rule for this pass: judge the app as a person looking at it
would, and where the picture shows something the measurements miss, fix the
MEASUREMENT first (an in-app check with a planted arm), then the app.

| # | what the picture / the user showed | what the measurements said | measurement added | app fix |
|---|---|---|---|---|
| D-35 | navigating: overlay and stream "completely degrade" | per-drain overlay p50 ~4 ms -- every drain that RAN was fast; nothing counted the drains that did not run | `D-35`: longest gap between drains across a navigation to a new heavy page, and time to the first hover; planted arm = drain loop held across the capture + store-only hover | encoder outside the store lock, foreground captures first; captures queued (drains never wait on the store); page left settled after the new page's first capture; hover from the page's own chunking (`at`) |
| D-37 | new-diff outlines "not observed for several minutes" | `drain_to_overlay` 4-9 ms: the outline WAS painted -- off screen, for 1.2 s | per-drain `flash` reasons (flashed / covered / unstored / offscreen / nobox); `D-37`: outlines visible after the reader scrolls to results loaded off screen; planted arm = the 1.2 s flash | streaming outlines follow their chunks until saved + 1.5 s dwell on screen |
| D-36 | billboard and side card do not look like the page (three bullets for one sentence, `( label )`, `[..](..)`, unloaded favicons) | the panel checks (G-77/G-81/G-82) counted elements, images and cards -- none compared the panel with the PAGE | `D-36`: panel text vs the page's text, in order; distilled marks; the page's own title colour and breadcrumb colour/decoration; images loaded -- for the card AND the billboard; planted arm = distilled panels | panels render the chunk's own elements from the live page (computed styles, sandboxed frame); the distilled form fixed too (inline joins across depth, form actions hidden, `//` urls resolved) |
| G-93 | the 3D streaming cluster reads as one grey ball | G-89 counted force nodes and coincident pairs, not spacing relative to size | `G-93`: nearest-neighbour distance in node radii, overlap share, translucency; planted arm = the old spring | rest length grows with the subtree (no cap), softer pull, siblings 3 diameters + margin apart, translucent streaming spheres |

Rule added to the loop after I drove the browser while the user was using it
(a test pin landed on their DuckDuckGo page): check for the user's activity
before any gesture, and work on code instead when they are there.

## Pass 4 (2026-09-27) — the page-centroid default, online CUDA training, and "too far from the original nodes"

| # | what the picture / the user showed | what the measurements said | measurement added | app change |
|---|---|---|---|---|
| G-83 | "make the page-centroid UMAP the default" | chunks transformed through a page fit land nearest their own page only 19-23% (real corpus) | unit tests: own-page share, raw coords kept, planted raw placement | default; chunks DRAWN in the page's neighbourhood (direction kept, clipped), true coords in `raw_pos` |
| G-97 | "incrementally re-train online ... previous fits fixed ... CUDA" | umap-learn `update` moves old pages 37% of spacing; fresh fit 95% | tests: landmark update < 10% (measured 0.7% real, 4-8% toy), planted no-landmark 22-265% | `pumap.py`: parametric UMAP on CUDA; refit and a continuous background worker train only on the diff; GPU fuzzy graph (numba JIT was most of a 33 s fit); fit 57 s -> 10 s, training 3.2 s, transform < 1 ms |
| D-38 | "Nothing showing in the obsidian browser" | the window answered nothing, not even the debugger | `Live.recover()` (browser-side reload), watchdog around in-app runs | the cell reopens its last page |
| D-39 | "the nodes may not be pages ... leakage" | two stored pages were MY probes' DuckDuckGo queries | (guard still to build: probes on a test store only) | purged |
| G-94 | "way too far from the original set of nodes, even though there is sufficient spacing" | spacing checks passed; nothing measured distance from the node's OWN page | G-94 `near_page`: chunk distance / nearest-other-page distance, must stay < 0.5 (nearer its own page than any other); two planted arms (no collision; full-size chunks) | furniture chunks clipped (14.6x -> 0.84x on the working store); chunks sized to their page's room. **Still failing on a fresh store**: crowded neighbourhoods push chunks to 0.68-0.97x and 36/64 discs are buried -- the open page must push its neighbours aside |
| G-93 | (the streaming layout) | — | — | passes in-app: nn p10 51 radii vs planted 0.1 |

Still unobserved or failing in the app: G-94 (above), G-101 (the hard-page run hung the window, D-38 -- to re-run page by page with the watchdog), D-39's guard.
