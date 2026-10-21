# The Obsidian plugin — product requirements

`PLUGIN_GOAL.md` holds the user's two binding statements word for word and
outranks this file. This is their decomposition: every requirement traced to a
phrase in one of them, numbered so it can be argued about and measured.

**Status vocabulary.** `Done` means built *and* verified in the running app
over CDP, never by screenshot (X-2). `Partial` means built with a measured
shortfall, and the shortfall is stated. `Open` means not started. **`Defect`**
means something is built and CONTRADICTS the goal — those are not gaps to fill
but code to change, and they are listed first because they are the only
category where doing nothing makes things worse.

**Part I** is the decomposition: 128 numbered requirements, plus section 0b recording every judgment where the two statements disagreed. **Part II** keeps the measured findings from
the work so far, under their original `R-*` ids, as the evidence Part I cites.
Those ids are retired as requirements and retained as anchors.

---

## Part I — the decomposition

### 0. Defects: shipped code that contradicts the goal

| id | what is built | what the goal says | |
|---|---|---|---|
| D-1 | `layout.py` fits the projector on tf-idf **and** semantic jointly, equalised by width | *"quantized semantic (and not pre-umapped frequency) vectors are the primary embeddings space for the projector"* | **Done 2026-09-12** — see below. The row read **Defect** for a week after the fix landed, which is the drift `design_state.py` exists to catch |
| D-2 | The trie is keyed `url : xpath : taxonomy : content` | *"a unified patricia trie of domain/url-tail/xpath/markdown/content-detection"* — five levels, and markdown is one of them | **Defect** |
| D-3 | The panel draws a read-only surface inside a code block | *"retrofitted to show their **base and original** markdown editors"* — the native, editable Obsidian editor | **Defect** |
| D-4 | `markdown.py` is tuned "17:1 toward leaving noise rather than risking loss" and `_dedupe` is element-scoped | *"full deduplication of repeat substrings that are essentially structural redundancies of the web pages themselves"* | **Partly** 2026-10-11 -- the verbatim settles it (PLUGIN_GOAL: "when a page repeats itself structurally, the chunk shows it once"). Exact duplicate CHUNKS are `G-24`'s (marked in the db). Within a chunk, measured over six stored pages: 1,855 of 20,535 lines repeat; three causes are structure and are now drawn once, each folded onto the line whose words show it, its address kept on that line's `inline` (`markdown.py` `_fold_structural`, planted `PLANT_STRUCTURAL_NOISE`; `tests/test_structural_fold.py`): punctuation cut off its text (`- .`, `- |`), a link's own icon (alt = label), a header's repeated control label ("Sort ascending"). Live payload: **240 fewer lines, 1,048 -> 923 repeats, covered 8,617 and accounted 8,855 unchanged**; stored page: 0 pencil icons, "Sort ascending" once a table. NOT folded, by rule and by test: data -- "Yes"/"No", a cell's "?", API type links. What repeats now is mostly those, in tables whose spans keep them a cell per line (`D-5`). The first cut folded 20 data cells and an empty `![]`; both caught and fixed |
| D-5 | Markdown renders no tables at all | *"a hierarchically-header-structured markdown document with tables, images, web links"* | **Confirm** 2026-10-11. Tables render as tables, laid out as a browser lays them out: the sensor (`sensor.js`) and the offline tagger (`content_tagger.py`) now report a cell's `rowspan`/`colspan` above 1; the renderer never draws those units (`_is_span`), reads them into one layout per table per page (`_table_layouts`, across every chunk -- a fragment's rows sit under spans another chunk holds; an empty cell keeps its column by ordinal), and places each value in its column (`_tabulate`). A fragment with its header draws pipe rows (separator added for display only, `with_table_separators`); one away from its header names each value (`D-9`). A row line carries its first CONTENT cell's address (a control's would repaint the row as a control -- caught by `test_every_line_repaints_to_itself` on GitHub's file table) and every other address inline. Planted `PLANT_NO_TABLES`, `PLANT_NO_SPANS` ("Linux" under "Name"); `tests/test_tables_render.py`. Live on Comparison_of_web_browsers, new sensor in a hidden window: 289 span units, none drawn; continuation rows "Platform: iOS · Latest release: 4.9.0" (planted: "Browser: Linux · Developer: 1.97.56"). Stored after a sidecar restart and recapture: **540 named rows, 42 continuation rows in their column, in-chunk repeats 59** (923 that morning -- the "Yes"/"No" cells were tables drawn a cell per line); the markdown panel shows them |
| ~~D-6~~ | ~~The delta path re-admits a chunk it should have reassigned or popped~~ | **WITHDRAWN 2026-09-12 — not demonstrated.** The evidence for it was a metric that could not tell two real siblings from one re-addressed node. `--resolvable`: 0 unresolvable of 719. `--drift --kind insert`: 0 stale, 0 lost over ~190 moved addresses ×3. See §M.3 for what remains untested | — |
| ~~D-8~~ | ~~A `src` detection and an `alt` detection at one `<img>` are drawn as TWO media lines~~ | **FIXED 2026-09-13** — `markdown._join_media` merges the pair at one element, keeping the url's address and absorbing the alt's. A fresh live scan of the reporting site: **0 pairs**, against 365 before. §M.5.1 | — |
| D-9 | A chunk rooted at a `<tr>` carries its cells' VALUES and none of their names, though the header at the same `td[n]` position is in the trie | `M-10` full structural preservation; `M-11` the chunk is what gets embedded | **Done** 2026-10-11 -- each table's header row is read across all of a page's chunks before any is rewritten, and a fragment away from it whose rows match the header's width draws each row as `Name: value · Name: value`, every cell's address kept on the line (`markdown.py` `_table_headers`, `_tabulate`; planted `PLANT_NAKED_ROWS`; `tests/test_tables_render.py`). On the way: one row key merged `thead/tr` with `tbody/tr`, and a sortable header's own "Sort ascending" was read as its name -- both fixed. Live, Comparison_of_web_browsers recaptured: **11 tables' headers found, 281 rows named** in the store (planted: 0); 83 rows still pipe rows where the header is in the chunk. (44 of 79 row chunks bare, §M.5.2) |
| D-10 | One ar.wikipedia `<tr>` renders **302 tokens against a 300-token window while still holding twelve splittable children** — a chunk over the window that is not indivisible | `M-12` the window is enforced; `test_oversized_chunks_are_indivisible_not_lazy` states the rule | **Superseded** 2026-09-26 by `G-86`'s lenient window (a run may take the piece that crosses the window while under 1.5x, so 302 against 300 is inside the bound); `tests/test_markdown.py::test_oversized_chunks_are_indivisible_not_lazy` states the new bound and passes at 300/600/1200/2400 (re-run 2026-10-11, 29 passed). Was: NEW under `G-22`. `tokens.budget` is smaller than `tokens.count`, so the descent stops at a node it used to split through. Held by `strict=True` xfail at two windows in `tests/test_markdown.py` so the day it is fixed the marker has to come off. Five candidate causes ruled out by measurement, each named in that file; the growth is between `_descend`'s return and the page-global passes **Superseded 2026-09-26 by a contract change, not a fix:** the lenient cut (`G-86`, `markdown.LENIENCY` 1.5) makes 302 against 300 inside the bound; the growth after `_descend` is still unexplained |
| D-13 | The `/layout` cache held **one slot** in a `ThreadingHTTPServer`, so two concurrent requests for different spaces or levels could each be served the other's answer | `G-17`/`G-53`: the pane has a button for each axis and asks for what it draws | **FIXED 2026-09-19** — four slots, keyed identically. Caught by `confirm.mjs`'s D-11 check, which asks for both spaces at once: sequentially all three requests were right, concurrently `euclidean` came back `"S3"`. The server's own comment two hundred lines below already notes that a vault opens many connections at once |
| D-14 | **Every `/search` crashed** on this workspace: `IndexError: index 13397 is out of bounds for axis 0 with size 13397`. `Workspace.index` is a lazy property with no lock, so two concurrent searches both hydrated into one shared `EmbeddingMatrix`, each grew a copy of the same stale array, and the smaller assignment landed last | `G-42`, `G-63`, `G-64`, `G-69`, `G-70`, `G-71` — all six marked **Done**, none of which could run | **FIXED 2026-09-19** — `EmbeddingMatrix.set` is serialised and the index is built once under a lock. `tests/test_vectors_concurrent.py`, with the non-vacuity arm checked by removing the lock (2 failed). Six concurrent searches now return 200 with 8 hits each. **Nothing in the suite touched the structure from two threads**, which is why a green suite carried a dead endpoint |
| D-21 | **A stored fit restored the picture and not the anchors.** `G-12` serves a layout out of the store without calling `build_page_layout`, and with it skips the side effect that records where each page was DRAWN — so an unfolding had no anchor for the space it was in | `G-54` unfolding, `G-12` persistence | **FIXED 2026-09-20** — `remember_page_positions` rebuilds `_PAGE_POS` from the stored payload, which carries every page's url and position already. **`D-20` again by a different route**, and the second half is the worse half: `unfold`'s fallback borrowed anchors from whichever space HAD them, so a missing euclidean anchor silently became a spherical one and chunks landed **378 units** from their node against a ball of radius 90. The fallback is gone — a space with no anchor derives one from the live fit, which is at least the space the reader is in. Caught by `G-54`'s placement assertion within minutes of `G-12` landing |
| D-22 | The layout cache and the persisted fit were keyed on a chunk **count**, so a stored fit was served to a corpus it had never seen | *“a fitted layout is persisted and queried back instead of refitted”* (`G-12`) — for the question it answered | **Fixed 2026-09-20.** A count is not an identity: purge twenty pages, capture twenty chunks elsewhere, and the key is unchanged while the corpus is not. Found by `G-54` passing alone and failing in sequence. Measured cold against the live store: the served page layout still carried nodes for `live_mutate.html` fixtures purged hours earlier, and unfolding one of its pages put the chunks **643 units from the page against a ball of radius 90**. `GraphStore.corpus_fingerprint()` hashes the Page table's urls and per-page chunk counts in order — one indexed scan on the path that already paid for the count. Same cold sequence after: **90.0**, and `G-54` passes in the full suite where it had read 238. Both arms in `tests/test_corpus_invariants.py`: a different corpus of the SAME count must change the fingerprint, and an untouched one must not churn. The same discriminator failure as the blanked `[n]` and the cumulative `repairMs` — a number two states share cannot tell them apart |
| D-23 | **The sidecar segfaults during a live capture's chunk ingest**, under sustained load | *“one page's failure must not end a corpus run”* (`S-15`) — and a process that dies ends everything | **Confirm** 2026-10-11 -- the supervisor's own record (`build/corpus123/crashes.log`): the last native access violation (exit 3221225477) was 2026-10-07; across 2026-10-10 and the sustained load of 2026-10-11 (large captures, recaptures, Verifier runs) every exit is a deliberate restart (-1) -- none native. Was: Defect -- diagnosed, not fixed, 2026-09-20. Seven crashes under a full `confirm.mjs` suite, native, exit 139, no Python traceback. `-X faulthandler` names one frame every time: `kuzu/connection.py:execute` ← `graphstore._batch` ← `graphstore.ingest` ← `workspace.ingest_chunks` ← `sidecar._post_capture`. **It is not a Python-level race**: at the fault every other thread is parked in `wait` or `select`. Memory steps hard just before it — 1,935 → 2,199 → **4,767 MB in 11 seconds**, then gone. **Four mitigations applied, none of them the cure**, all kept because each guards a real hazard: a fit lock (concurrent UMAP on request threads), a connection lock (kuzu reads ran unserialised against writes), a weight-aware `_batch` slice, and a bounded `buffer_pool_size`. The pool bound lowered the peak from 4,767 to 2,242 MB and the process still died, which rules out simple exhaustion. **Not caused by this session's changes** — the first crash predates them. Next step, untested: the 4.9 GB store has now survived seven hard kills, so it may be damaged; run the same suite against a freshly scanned workspace to separate a corrupt store from a kuzu fault. The suite reaches **20 of 21** before it dies, and `confirm.mjs` now stops and says the sidecar went away rather than reporting 28 broken features |
| D-24 | **The live checks could not see the interface.** Every graph row was scored on `fitX/fitY/fitZ` — the fit's own space — and never projected to pixels, so the requirement passed while the picture failed | `G-4`, `G-5`, `G-21`, `G-6` | **Done** -- instrument built 2026-09-20 and in use: `__vertiscope.ui()`, `trace` and `act()` measured today's G-21, G-151 and frame-cost checks, the rows it invalidates are D-25.** `obsidian-plugin/src/harness.ts` puts three things on `window.__vertiscope`: `ui()`, the interface as a data structure in SCREEN pixels that tells drawn from merely present; `trace`, every sidecar call captured by wrapping `fetch` ONCE at the boundary rather than at twelve call sites that go stale; and `act()`, a gesture through the application's own paths returning the UI before, the UI after, and the backend work it caused. Measured on a real page: `scan` → 7 calls, 930 ms, `/sensor` x1 and `/capture` x6, 0 failures. `cdp.mjs` already had `axTree` and `mouse`/`click`/`drag` and `confirm.mjs` used none of it. **Screenshots are not the answer** — expensive, and a picture cannot be asserted on |
| D-25 | **The projector's picture is not measured where a reader meets it** | `G-4`, `G-5`, `G-21` | **Confirm** 2026-10-11 -- measured where the collider works (world space, the application's own `drawnRadiusOf`): 0 of 255 url nodes overlapping (`G-21`), 0 of 349 chunks inside their url node's sphere (`G-147`). Was: Open, and the first numbers here were WRONG — corrected 2026-09-20.** I reported "86 of 97 nodes overlap" from a screen-space 2D test. That conflates DEPTH: in a 3D projection two nodes far apart along the view axis land near each other in pixels, and rotating separates them. Measured in world space, where the collider works, only **14 of 97** genuinely interpenetrate (median gap 69.3 against a median radius 19.65). The 2D figure is a fact about a still frame, not a defect, and I filed it as one. **What survives**: at chunk level **116 of 558 nodes were off the canvas**; the cloud uses about **a fifth of the pane**; and the node SIZING was self-defeating by arithmetic — at `spacing.p50 / 6` the drawn diameter equalled the median spacing, so every node closer than the median overlapped and half are by definition. Fixed to `/12`: drawn radius 39.3px → 20.4px. **Still open**: the fit is tight (fit→drawn drift 0–22) and framing wastes most of the pane. **The “simulation never moves a node” clause was wrong and is withdrawn (2026-09-20).** Velocities do stay 0 through a reheat, and the reason is that there is nothing to push: counted in world space with the pane's OWN collider radius function, **0 of 7,750 pairs** interpenetrate, so `forceCollide` is at equilibrium rather than asleep. Two other readings in that clause were also environmental — `cooldownTicks` reads `null` only because `JSON.stringify(Infinity)` is `null`, and a render loop that measured **0 frames in 2 s** ran at **407 frames in 2 s** once the minimised window was woken with `Emulation.setFocusEmulationEnabled`. The real defect at this level is D-27. The proposed shape is **force-directed chunks within force-directed UMAP page nodes**, relaxed at each scale |
| D-26 | **Most markdown lines came back with `key: ""`, so a click could not name an element in the page** | *“It sends the line's ADDRESS, not just its text … it is what lets a click in Obsidian name an element in the real page”* | **Done** -- diagnosed and fixed 2026-09-20, and held: `key_coverage` 2026-10-11 reads 0 blank keys over 644,312 addresses (`D-29`, `D-31`). Was filed as Defect. The first filing of this row was wrong in its headline number and in its cause, and both are corrected here.** *What was wrong:* it reported “331,020 addresses against 36,799 anchors — 11.1%” as the coverage figure. That is the wrong denominator and it is not answerable: an ADDRESS is every point the trie holds for a page, an ANCHOR is one per rendered markdown LINE, and a page holding thousands of addresses renders a few dozen lines. It also generalised from one sample of 8 chunks that happened to land on affected pages. Measured properly, per page: **34 of 74 sampled pages were fully keyed, 29 were at zero, 11 partial — 60.1% of lines**, all-or-nothing per page rather than uniformly broken. *The actual cause:* the anchors were there all along; their addresses had a blank `akey`, which will not parse, so `addresses_of` silently dropped every row. **118,180 of 331,242 addresses (35.7%)** held a blank key, and affected pages were at 100% while the rest were at 0%. The guard in `ingest` — `needs_value = aid not in unchanged_addresses` — was a function of `content_hash` ALONE while the write it skipped sets six columns including `akey`, so a row missing its key was judged current and left that way **permanently**: re-scanning cannot move a content hash that never changed. That is `CLAUDE.md` 5c applied to a row rather than to a classification. *Reproduced from the cause, not observed:* `tests/test_address_rewrite_skip.py` blanks the keys on a fresh store and re-ingests the identical page — **505 of 505** stayed blank before the fix, with a non-vacuity arm proving a fresh ingest writes every key. *Fixed two ways:* the guard now compares `akey` as well (it is derived from `url\|xpath\|tag\|accessor`, so one comparison covers four columns), and `repair_blank_keys` rebuilds the string in place from those columns — no re-scan, because the key is derived, not captured, and the rebuilt key is asserted byte-identical to the original and to parse back. **Live corpus after the repair: 118,180 → 0 blank addresses, 1,947 → 0 blank-key anchors; pages fully keyed 34 → 55, pages at zero 29 → 5, lines keyed 60.1% → 91.7%.** `G-39`'s own failing gesture now works: the xpath `…/ol/li/article/h3/a` that `confirm.mjs` reported as “no chunk draws” with `ringed: 0` resolves in 2 ancestor steps to a chunk with **6 lines, 6 keyed, 2 controls**. `/health` reports `addresses_blank_key`, `anchors_blank_key` and `unreadable_addresses` so neither cause can go silent again |
| D-29 | **Five pages still serve every line unkeyed, and their addresses are now whole** | same as `D-26` | **Done** 2026-10-11 -- see the dated note at the end. Was: Defect, open, found 2026-09-20 after D-26's repair. With `addresses_blank_key` at 0 corpus-wide, a chunk that still returns no keys means `addresses_of` found **no `Anchors` edges at all** — a genuinely missing anchor rather than an unreadable one, which is what D-26 was originally filed as. It affects 5 of 74 sampled pages: ar.wikipedia, MDN's JavaScript reference, mastodon.social/explore, nodejs.org/api/fs.html and en.wikipedia's browser comparison. **Recorded rather than guessed at**: not yet established whether these chunks were written by a path that never produced anchors, or whether `_reconcile` deleted them and `fresh_anchors` did not put them back. The 11 partly-keyed pages (71–96%) are a separate question — a positional drift between `_reflow(stored.md).splitlines()` and the `anchors` array, which `chunk_payload` zips by index **2026-10-11:** `key_coverage` over 140 pages: 97.5% of lines keyed, 3 pages with none (nodejs fs, mastodon explore, MDN Array) -- all three with no `Anchors` at all (`/page_map` 404), stored by an older ingest. A visit re-anchors them: sampled 212/212, 56/56, 128/128 keyed; corpus 97.9%, 1 zero-keyed page left (MDN Array's older chunks, retired by its settle). |
| D-30 | **The harness could not reach most of the requirement space, so the requirement space was argued about instead of measured** | the whole of Part I | **Done** -- built 2026-09-20; today's checks ran through it (`scripts/live_probe.py` adds the reader guard). Every verification behind `D-26` and `D-27` was a throwaway script over a raw CDP socket: no history of having been wrong, and two of them WERE — a screen-space overlap count that conflated depth, and a branch query that counted an inter-page link as an unfold branch. The MCP surface is now eight tools wider: `wake`, `graph_probe`, `key_coverage`, `repair_keys`, `confirm`, `design_state`, plus the gestures `unfold`, `click`, `retrieve` and `reload`. **One persistent CDP session, woken once** — `setFocusEmulationEnabled` lasts exactly as long as the session that set it, so a connect-evaluate-close cycle can never be awake, and a minimised window reads 0 rendered frames in 2 s against 407 awake. `confirm` returns a verdict per requirement WITH the numbers it decided on, refuses to run when the sidecar is down rather than scoring its absence as broken features, and waits for the pane it just reloaded. **It found four defects in its own first four runs**: a reload routed through the harness it was replacing (so the first run scored the previous build), a `fetch` guard that was a boolean and could not be re-earned across a reload (`calls: 0` for work that happened), a containment force that called `graphData()` inside a tick and took the projector down, and a probe measuring reach from a hub the collider moves rather than from the fixed anchor containment is defined against — which reported a 341-unit spill while **0 of 33** branches were outside their territory, and very nearly had a correct fix reverted. **Live: 13 of 14** |
| D-31 | **Some pages hold chunks whose lines have no `Anchors` edge at all** | as `D-26` | **Done** 2026-10-11 -- `key_coverage` over 140 pages: 97.5% of lines keyed, 0 blank keys; the three pages with none (nodejs fs, mastodon explore, MDN Array) had no `Anchors` at all, stored by an older ingest, and a visit re-anchored them (sampled 212/212, 56/56, 128/128 keyed; corpus 97.9%). Filed 2026-09-20 as what `D-26` was mistakenly filed as; the history is in `D-29` |
| D-32 | **Lexical rows were lost on every hard stop, and rows indexed while a chunk was empty stayed empty** — 4,724 of 16,251 chunks (29%) could not be returned by any query | *“the retrieval overlay”* (Addendum IV); `G-3` strict product | **FIXED 2026-09-23.** The frequency matrix was written only by `close()` and `rebuild_lexical()`, so a sidecar ended by a kill lost every row added since it opened while the chunks stayed in the graph; and `restore_markdown` refilled markdown without re-deriving rows built from the empty text. Measured by the start-up repair: **4,324 rows missing, 400 empty**. Now: `rebuild_lexical` also refreshes empty rows, the sidecar runs it at start (1.4 s), and `save_lexical` writes the matrix within 30 s of any change. Next restart: 0 added, 0 refreshed, 16,251 held. `tests/test_lexical_coverage.py` (planted empty row; a session that never closes) |
| D-33 | **The semantic factor scored each chunk with ANOTHER chunk's similarity** | `G-3`; *“retrieval stays TRIPLE”* | **FIXED 2026-09-23.** `EmbeddingMatrix.similarities` answers in the embedding matrix's own row order (arrival order); search read it as frequency-row order. The two agree only on a corpus built in one pass — the frequency matrix reclaims retired rows and gains repaired ones, the embedding matrix appends. Live: pages captured that afternoon were unreachable by their own name ("Persona": 0 hits) and "Ternary search tree" ranked coinmarketcap above the ternary-search-tree page. Now joined on cid; live after the fix, "Ternary search tree" returns that page 3/3, "Persona" and "Shin Megami Tensei" the Persona page, "HTTP header field" net/http and RFC 9110. `tests/test_semantic_row_alignment.py` — planted with the two matrices in opposite orders: before the fix, searching a chunk's exact meaning returned nothing and a vectorless chunk scored 1.0 |
| D-34 | **A search waited minutes: the first one after a start, and any one after browsing** | *“the retrieval overlay”*; `G-69` continuous scrolling | **FIXED 2026-09-24.** Measured by timing the index's own phases: the first build spent **146 s hydrating** embeddings -- `EmbeddingMatrix._grow` added one row per vector and copied the whole matrix each time (old growth: 7.9 s at 4k rows, 39.2 s at 8k) -- and a search after a capture spent **38 s running the encoder inline**. Now the matrix doubles (16k vectors in 0.21 s), hydration reads in bulk, the sidecar's search never runs the encoder (`embed_inline`, the worker owns it), and the index is built at start. Live: index warm 5 s after start; searches 0.11-0.21 s; a page browsed seconds earlier found by its own name in 1.03 s (rebuild: hydrate 116 ms, build 419 ms, encoder 0) |
| D-35 | **Navigating to a new page, the overlay and the streaming "completely degrade"** | *Addendum IX: “the chunk overlay and streaming from the electron scanning completely degrades when navigating to a new page”*; `S-12`, `G-91` | **Confirm — fixed and seen in the app 2026-09-27** (`a0f3a31`; check `D-35`, fresh run_20260927162317): across a navigation to a new heavy page the longest drain gap is 1.2 s and hover answers 234 ms after the first drain (from the page's own chunking); planted arm (drain held across the capture, store-only hover) 4.3 s / 3.9 s, caught |
| D-36 | **A chunk's panels do not read like the page.** DuckDuckGo's Search Assist answer, one sentence on the page, is three bullets in the billboard and the side card, split at its inline `<b>`; buttons print as `( label )`; protocol-relative image urls (`//external-content...`) fail to load; a raw href stands in for a control | *2026-09-27: “the panel rendering of the chunk in both GUI locations (3D billboard and 2D clipboard) are discontinuous with how the text/html is rendered in the original webpage, which is a bug”*; `G-81`, `G-82`, `G-102` | **Confirm — fixed and seen in the app 2026-09-27** (check `D-36`): card AND billboard carry the page's text in order (1.0), no distilled marks, the page's title colour and breadcrumb colour/decoration, favicon loaded; snapshot 4 ms, 9/9 elements; planted arm (distilled panels) caught |
| D-37 | **New diffs are not seen outlined.** The diff outline was a 1.2 s flash of on-screen chunks only; most of a drain lands off screen, so new content was never outlined where the reader looked. Per-drain reasons now on each trace (`flash`: flashed / covered / unstored / offscreen / nobox) | *2026-09-27: “overlays for completely new diff updates are completely broken and have not been observed for several minutes”*; `G-90`, `G-92` | **Confirm — fixed and seen in the app 2026-09-27** (check `D-37`): results loaded off screen are outlined when the reader scrolls to them (6 of 6); planted arm (1.2 s flash) shows 0, caught |
| D-38 | **The Obsidian window hung during the hard-page run and the browser cell went blank.** The renderer answered nothing, not even the debugger, with idle CPU (a synchronous wait); the run lost its connection and the reader saw an empty cell | *2026-09-27: “Nothing showing in the obsidian browser. It's currently a blank screen”* | **Confirm** 2026-10-11 -- the in-app result this cell was waiting for: the reader's store held 30 pairs of url nodes at the IDENTICAL position (copies of a fixture page) for the whole day and no octree hang came of them; today's freezes were each profiled to another cause and fixed (`G-145`); and coincident url nodes are now parted outright (`G-21`). Was: Defect -- reopened 2026-09-28 evening (see the end of this cell). Earlier the same day: *root cause found and fixed.* Not a hang: Chromium's log says "Renderer process oom". Paused in the act (debugger armed before the freeze): `add3 <- addAll3 <- octree <- collide force <- tick`, heap 866 MB and climbing ~1 GB/s. d3-octree's subdivision never ends for a point built from x + vx when vx is NaN. The NaN was written by the LINK force, first every time (per-force attribution): the pane pushed new links and nodes INTO the simulation's live arrays, the forces' per-item arrays (strengths, distances, radii) are rebuilt only at the graph's deferred digest, and a frame ticked in between read `l * undefined`. Fixed: no in-place push anywhere (new arrays, adopted at the digest); a guard resets any non-finite or runaway position/velocity/radius before an octree and records it with the force that wrote it (`non_finite` in the MCP state). Evidence: the same 2-minute rapid scroll+hover on the Julia forum froze the window 4 times before; after: 0 guard catches, 0 NaN, 12/12 pushed drains applied in 3D. Still open: the PAGE's own renderer can run out of memory on an endless /latest scroll (Discourse keeps every row: 469k DOM nodes; 81% of the page's live-heap growth is Discourse, 18.5% the sensor's per-node records). **REOPENED 2026-09-28 evening:** the same `add3 <- addAll3 <- octree <- collide <- gated` hang, caught paused twice (heap 1,067 and 1,326 MB) about two minutes after 30 s of rapid scrolling on a forum URL the store had never seen (~1,000 streaming nodes, capture backlog 21), and once more while the app sat idle on that page for over an hour. The guard missed it: `sanitize` let an unplaced node (x undefined) through "because the octree skips it" -- it does not, it inserts it at the origin with a NaN leaf -- and compared `vx ?? 0` where collide's accessor reads `x + vx` raw. `octreeguard.ts` now refuses exactly what the accessors would read as non-finite, so collide and many-body sit that tick out and record it (`octree_skips`). Module tests (`node --test obsidian-plugin/tests/octree_guard.test.mjs`, 7 pass): planted, two unplaced nodes exhaust d3-octree's build (a 128 MB child process dies in 0.24 s), and so do placed nodes whose velocity was never set; the null arm, the same graph placed, builds in 22 ms. The second hang happened WITH the first guard loaded, which is how its `?? 0` was found; whether the exact guard closes it is not yet shown in the app -- the watcher now scans the octree's own input at the moment of a hang. **It did (2026-09-28 23:58), and the road was a different one:** 766 nodes, 2 bad -- two page nodes of johnwick.movie at the IDENTICAL position with velocities +-Infinity, tree bounds -Infinity/NaN, guard counters 0. d3's collide measures a pair's separation as x_a + vx_a - x_b - vx_b; the positions cancel, velocities decayed to ~1e-200 leave a component that is not `=== 0` (so no jiggle) and whose square underflows to 0; `(r - sqrt 0) / 0` is Infinity, written inside collide's first iteration and fatal to its second iteration's octree. Two pages with one centroid sit at one position for good, which is why the window also died idle. Fix (`09b349b`): velocities under 1e-100 flushed to exactly 0 before collide (d3's jiggle then separates the pair finitely), and collide run one iteration at a time with the octree check between. Planted in `obsidian-plugin/tests/octree_guard.test.mjs` with d3-force-3d's real `forceCollide` on the caught pair: Infinity, then a hung octree, in 0.34 s; flushed first, finite and built (10 pass). In the app: the same reproduction re-run under the watcher -- result recorded when it is in |
| D-39 | **Probe pages leaked into the reader's working store.** Two DuckDuckGo queries my terminal probes ran ("b tree split 7927", "trie cache 544") were stored as pages and drawn among the reader's | *2026-09-27: “the nodes may not be pages/url nodes and show leakage”* | **Confirm** 2026-10-11 -- the guard is built: a sidecar started with `--capture` takes captures only from the plugin's browser cell (`X-Vertiscope-Client`), unless `--allow-probe-captures` names it a scratch store (`sidecar.py`, `__main__.py`, `sidecar.ts`; `tests/test_capture_guard.py`, planted: unguarded, the probe's capture lands). Live on the reader's sidecar: a probe's capture is refused naming `D-39`; the plugin's still lands (471 chunks, all identical, skipped). **A regression on the way, caught live:** the new header made the app's request a CORS preflight the sidecar did not allow, and every capture failed ("Failed to fetch") for nine minutes while the reader was idle -- fixed in `Allow-Headers`, with a preflight test. Was: Defect, open; purged 145 + 16 chunks |
| D-40 | **Hover and diff lag after a long scroll.** On discourse's /latest the outline trailed the pointer by 65-138 ms, and a new batch of topics reached the overlay 150-600 ms after the page wrote it. Causes, measured: the hover and the drain were POLLED, and a pulled crossing queued behind the page's own long tasks (a bare `executeJavaScript('1')` 12 ms p50, 942 ms max while scrolling); the fold waited for an idle callback (up to 320 ms); the drain crossing grew 30 -> 231 ms drain by drain. Fixed: the sensor pushes both on the page console (native console only, a per-load nonce in the prefix), the hover computed at event time and the drain sent from the task that folded it, which on a pushing host is the mutation's own task (a microtask; one per frame in a burst) | *2026-09-27: “Significant chunk highlight-when-hovered lag after extensive scrolling ... it should be simple enough to continuously stream diffs from the mutationobservers to the electron overlay to the 3D gui without having to wait for database write queues”* | **Done** -- fixed (filed as Defect); check `D-40` judged ON discourse.julialang.org/latest (planted: `pull-drain` + `poll-hover`; the page's changes timed by the check's own observer, each matched to the drain that carried it).** The fixture `busy_feed.html` measured 3/6 ms page -> host (planted 155/163) -- mechanism only, not the reader's page. Probe on discourse after 40 wheel steps: hover move -> outline p50 8.4-9 ms, p95 11.4-14.4 ms; mutation -> overlay placed p50 74 ms, p95 91 ms for 30-topic batches with the frame-aligned fold, before the microtask fold |
| D-41 | **An open page's layout broke its own geometry, then was not force-directed, then followed the camera.** The sunflower disc gave each chunk a slot by UMAP rank, blind to its parent (Radix_tree in the app: 34 of 65 drawn nodes buried, 190 crossing edges). Its replacement, a radial tree, was a PINNED geometry -- collide 0, `home` to the slot -- read as a flat circle, and the projector's stream overwrote the slots (every chunk at exactly 0.45 of the room). Made force-driven, a flat star (the Julia forum's 229 rows under one page) still rested on the siblings' shell radius: a ring, distance spread 0.06. And both the seeding (in the camera's plane) and an orbit (the tree turned to face it) followed the camera. Now: seeded in 3D beside each chunk's parent, in the fit's direction, never reading the camera; laid out by short springs along the tree, siblings' local repulsion (three steps), the integer collider (the page's billboard included) and a generous page room; the projector's stream updates a chunk's direction, never its place | *2026-09-27: “force-directed layouts have incorrect geometries and constraints”; 2026-09-28: “Layouts still collapsing to something likely non force directed. This is a flat circle”; “Ring layouts still showing instead of force directed”; “re-facing ... always facing the camera and adjusting its orientation; this is an unneeded addition that needs to be removed without breaking the functionality of what is force-directed”* | **Superseded** 2026-09-28 (filed as Defect): the open-page layout is REMOVED -- projected chunks sit at their fit (`G-97`), streaming nodes are force-directed (`G-93`); a page's chunks sized to its room.** Earlier fix: check `G-94` on Radix_tree AND the Julia forum's /latest: a hub's children FOLLOW it (planted: `sunflower`, pinned), the forum's distances SPREAD (planted: `shell`, the ring), burial, the page's billboard not buried; crossings and an orbit reported** |
| D-42 | **Link and image destinations were cut at the first `)`.** Thumbor-style pictures (`.../filters:no_upscale():max_bytes(150000):...`) and Wikipedia titles (`Mercury_(planet)`) rendered as a broken `<img>` with the rest of the url as caption text, and the 3D node's picture was the same broken url | *2026-10-06: "the attached image doesn't actually render anything"* (photo: an allrecipes card) | **Fixed 2026-10-06** (`1b13c6a`): balanced parentheses in every parser -- `htmlform._MEDIA/_LINK`, `layout._MEDIA_RE`, `tokens._TARGET_RE`, `markdown._LINK_RE`, the plugin's surface `MEDIA/LINK`; `tests/test_paren_urls.py` 6 (planted: the old pattern truncates the same url). Seen live: the allrecipes card's image loads in the panel |
| D-43 | **Pages that wrap `console.debug` got no pushed drains**, so their overlay waited for the 1.2 s poll: 0 pushed drains in a session on Wikipedia and DuckDuckGo, `mutation_to_host` 1,088-1,259 ms | *2026-10-06: "Overlay and green register overlays for new chunks/diffs are still quite laggy. Latency should be single digit millisecond."* | **Fixed 2026-10-06** (`ce5f682`): the sensor runs in an Electron isolated world (`isolate.ts`, world 1029) -- own native console, same DOM; the page no longer sees `__vertiscopeSensor`. A/B on `tests/fixtures/latency_probe.html` (wraps console.debug): 4/4 drains pushed, `mutation_to_host` p50 3 ms vs 0 pushed planted (`main-world`). Live on johnwick.movie: 2-17 ms. Open: `drain_to_overlay` (see G-113 latency) |
| D-44 | **Shadow roots attached after the fold were never read** (archive.org: 426 open roots 8 deep, 32,231 characters; the cell's sensor folded 17 chunks through 33 observers) | *2026-10-06: "archive.org is not being picked up at all. I know for a fact this is a nested shadow node issue"* | **Fixed 2026-10-06** (`83dfd5c`): custom-element hosts folded without a root are held and re-checked each repair and on a backoff; a host gaining an open root is observed and re-folded; `:defined` replaces the per-world registry. `attachShadow` untouched. Fixture A/B (`tests/fixtures/late_shadow.html`, two sensors in two isolated worlds of one page load): 3/3 leaves vs 0/3 planted (`nolateroots`). Live on archive.org: 157 sensor chunks / 407 observers; the store wrote 28 chunks |
| D-45 | **The overlay misplaced and stale**: diff boxes drawn 64 px above the cell (a `position: fixed` box offset by its parent); boxes not following scrolls (nothing mutates on a scroll; johnwick scrolls by transform, `scrollY` 0); outlines larger than the viewport (a chunk's box was its container's; johnwick's chunks sit in multi-screen sections) | *2026-10-06: "the tracked overlay actually slides off the page's bounds"; "Scrolls on this page leave stale billboards"; "overlays are quite large and span lots of text"* | **Fixed 2026-10-06**: `boxFrame` offsets only for a real containing block; the sensor pushes `scroll` (scroll/wheel listeners and a style/class observer, passive, trailing throttle) and the host re-measures; `runBox` is the union of what the chunk DRAWS (text runs, media, controls; nested chunks skipped), clipped to the chunk's own elements (an ellipsised title measured its full width: archive cards 258 px on 177 px -> 177 px); the hover's "smallest chunk under the pointer" descends open shadow roots (archive outlines median 8.1% of the viewport). Live: 8 real wheel events -> 248 re-measures; sampled outlines median 1.2% of the viewport, 0 of 121 larger than it (were 121 of 121). Fold-reads-no-layout tests pass |
| D-46 | **Panels opened empty, slowly, and stayed open**: the page form served a held snapshot forever (a stale grey mask), waited for a snapshot before drawing anything, and a hover panel was marked only after it loaded | *2026-10-06: "a clicked panel not rendering. This has begun to happen quite a bit now"; "Billboards don't close, are *very slow* to render, and don't show anything at all"; "Billboards are slow to close when not hovered"* | **Fixed, being measured, 2026-10-06**: markdown form from the store at once (payload prefetched during the hover dwell), the page form swapped in only when its snapshot shows text or a picture, re-read on every diff; hover panels marked at creation, closed 120 ms after the hover leaves every chunk; open/close timings in `panelTimes` and `app_anomalies.panel_speed`. **Check `G-113` PASS 2026-10-07** (Verifier: 1 flight, panel from the hover with text, outline 1.1% of the viewport, closed 285 ms after the pointer left; planted no flight, no panel). The slow part was the store: `/chunk` cost 0.36-2.0 s (one `addresses_at` scan of 500k addresses per element); `addresses_at_many` makes it one query -- 0.10-0.15 s warm (`tests/test_chunk_payload_batched.py`: identical payloads) |
| D-47 | **A settle wrote a page still loading as the complete page.** A page reloaded in the cell ended its session holding the fresh load's first fold; the settle retired 30 of johnwick's 31 stored chunks, the next capture re-added 24 as new rows, and the view's nodes for the 30 became phantoms (the anomaly recorder: 17-36 phantoms at 22:16-22:34; the central diff log: settle `retired 30, chunks 1`) | *2026-10-06: "Phantom nodes and weirdness/3d rendering lag on layouts and loose/stale 3D artifacts"* | **Fixed 2026-10-07, not yet loaded**: `_settle_truncated` -- a session under 15 s old rendering under half of 6+ stored chunks settles nothing and retires nothing; logged as a `settle` diff with `skipped`. `tests/test_central_diff.py` +3 (planted: no `born`). **Seen live 2026-10-07**: on johnwick.movie and archive.org, after reloads and revisits, the recorder read 0 phantoms (it had read 17-36 before the guard) |
| D-48 | **The working sidecar crashed natively and its store would not reopen** (2026-10-07 04:12: exit 0xC0000005 inside Kuzu on `MATCH (a:Chunk {url})-[:Contains]->(b:Chunk {url})` during `confirm.mjs`; the WAL was set aside unreplayable, ~17 MB; `freq/freq.npz` was left at 0 bytes, so every restart died on "No data left in file") | *2026-10-06: "Phantom nodes and weirdness/3d rendering lag"; the reader's working store* | **Repaired 2026-10-07, cause of the native crash open.** `FreqMatrix.save` is atomic now (temp files, fsync, rename; `tests/test_freq_atomic_save.py`, planted: an in-place write truncates). The index was rebuilt from the store's own markdown (`rebuild_lexical`: 20,826 rows in 1.6 s); the broken files and logs kept in `build/corpus123.rescue-20261007/` and as `*.crash-20261007`. The store reopened (196 pages, 20,826 chunks) and retrieval answers. **The likely cause, found 2026-10-07**: the buffer pool. 2 GiB was set for a 4.9 GB store; the store is 32 GB, and a `CHECKPOINT` failed outright with *"the buffer pool is full and no memory could be freed"*. The pool now scales with the store (`_pool_for`: a sixth of it, 2 GiB to a quarter of RAM -- 5.2 GiB here), and the WAL is folded in by a background thread after 60 s with no write (`_checkpoint_forever`; a checkpoint takes 10-21 s on this store, so never on the browsing path) -- a crash now costs at most what was written since the reader last paused. `tests/test_store_checkpoint.py` (planted: no checkpoint, the WAL holds the writes). Open: the store's size itself (32 GB for 197 pages / 502k addresses -- compaction rewrites the reader's store and is theirs to approve), and what the set-aside WAL held. **2026-10-07 09:00 -- the store had lost its STRINGS again**, the D-33 signature (80.6% on 2026-09-23): `chunks_empty_md` 19,128 of 24,107 (78.2%), 159 of 233 pages with every chunk empty, `addresses_blank_key` 145,618 of 600,126 -- every integer beside them intact (`line_count` set on all 17,846 empty chunks sampled). It is what the reader saw as panels that "don't show anything at all": 80% of chunks had no markdown to show, and this morning's lexical rebuild ran over the emptied markdown, so those pages could not be retrieved (`G-3` "unreachable": RFC 9110, nodejs fs, Persona...; `G-16`/`P-B2` 0 hits on the working store, passing fresh). **Repaired**: `/restore_markdown` from the JSONL checkpoint 19,128 -> 207 empty (chunks with an image 3,571 -> 9,524, pages with an image 36 -> 167); `/repair_keys` 145,618 -> 0; the restart re-derived the lexical rows (RFC 9110 and nodejs fs answer again, 5 and 3 hits). **Ruled out by measurement on a scratch store** (`scripts/store_torn_wal.py`, `scripts/store_set_blanks.py`, 60,000 and 12,000 rows): a WAL set aside after a kill mid-write (4 kill points x 2 arms), after a kill INSIDE the checkpoint (4 x 2, a full 24.6 MB WAL present each time), and per-page SETs on other columns (the merge layer's group SETs, embedding and group-embedding SETs, checkpoints, a reopen) -- **0 strings lost in every arm**. The cause is open and may need the real store's scale, which the disk (46 GB free, a 40 GB store) cannot copy. So the store now **dates the next loss itself**: `integrity.log` beside `crashes.log` gets a record at every sidecar start (a crash and its replay are bracketed) and every ten quiet minutes, and a count that ROSE is flagged with the statement the store last ran (`_integrity_record`, 256 ms on this store; `tests/test_integrity_log.py`, planted: blanked md and keys are flagged, the null arm is not). One more native crash was seen, 08:40:33, on the same statement as 04:29 (`MERGE (p)-[:HasChunk]->(c)`, a capture right after the restore's 18,921 writes); the WAL replayed and the restore survived |
| D-28 | **The second UMAP layer does not run.** A patricia step is two or three branches wide, and `_local_positions` cannot fit fewer than four points | *“the two layer UMAP … on the patricia trie”*; `G-54` | **Superseded 2026-09-23 by `G-72`.** The second layer no longer fits anything: an unfolding's branches are placed by the ONE chunk projector (a branch at the transform of its members' mean, a chunk where the stream put it), so the `n < 4` ring and the degenerate small fits are no longer on any path the pane draws. Original finding: **Defect, open, found 2026-09-20.** Unfolding every page in the corpus at its root: the width histogram is 2×26, 3×14, 4×10, 5×17, and a long tail of 7–183. **41 of 75 (54.7%)** come back with fewer than four nodes and take the `n < 4` branch, which is a hardcoded planar ring — no UMAP, and flat in a 3D pane. Another 27 land at four or five, where a fit with `neighbors = n-1` is degenerate. So the layer the goal calls a UMAP is, for most pages, a ring. **This is a design tension, not a coding slip, and it is recorded rather than guessed at**: `G-54` specifies unfolding as ONE patricia step, O(depth), explicitly not a subtree — and a step that narrow has nothing for a projection to say. Either the unfold opens a page to its CHUNKS (where archive.org has 25 and a fit is meaningful) or the second layer is honestly not a UMAP. That choice belongs to the user |
| D-20 | **One anchor table for two spaces.** An unfolding hangs its chunks off the page's drawn position, and asking for `?space=S3&level=page` re-runs the page fit and overwrote those positions with SPHERICAL ones — while the pane was still being served the euclidean layout out of the cache. The chunks then hung off coordinates from a fit nobody was looking at | `G-54` unfolding, `G-17`/`G-18` the two spaces coexisting | **FIXED 2026-09-19** — `_PAGE_POS` is keyed by space and `/unfold` takes one, which the pane supplies from its own toggle. **Caught by `G-54`'s live check within an hour of that check learning to look at a coordinate**: chunks landed 378 units from their page against a ball of radius 90. Nothing else would have noticed, because both spaces produce perfectly plausible numbers |
| D-19 | **A `Page` node does not always carry the same url its chunks do**, and seven per-page reads matched through it. 3,033 of 14,169 `HasChunk` edges join a page to chunks with a different url, over 8 pages, in two classes — percent-encoding (`ar.wikipedia.org/wiki/<arabic>` on the page, `%D9%81…` on the chunks) and a trailing slash (`https://books.toscrape.com` against `https://books.toscrape.com/`) | `G-54` unfolding, `G-26`/`G-31` aggregation, `T-*` the trie is keyed on url | **FIXED 2026-09-19** — `chunks`, `embeddings_for`, `chunk_count`, `group_count`, `set_groups`, `purge_page` and reconcile now key on `c.url`, which is what `page_vectors`, `contains_within` and `addresses_at` already used. Before: the LARGEST page in the corpus returned **0 chunks**, so clicking it drew nothing and aggregating it was skipped as under the gate. After: ar.wikipedia 801 chunks / 801 vectors / unfolds to 5 nodes, ja.wikipedia 187, books.toscrape 26, danluu 17 — all four previously dead. Found while asking why the biggest page unfolded to nothing **Where the two urls come from, traced:** not link-target stubs, as first guessed — those Page nodes carry 801, 187, 36 and 26 `HasChunk` edges and empty titles. Within ONE ingest, the `url` argument (what the caller asked for) differs from the url the CHUNKS carry (what the sensor read back from `location.href` after the browser resolved it): a trailing slash on six pages, percent-encoding on the two wikipedias, a `www.` prefix on data.gov.uk. 98 Page nodes for 96 distinct chunk urls. The write path should settle on the resolved url; that is **not** changed here, because the reads should never have depended on the two agreeing and routing around it is the smaller, safer change. Left open: a link to `danluu.com` still will not resolve to the scanned `danluu.com/`, which costs `G-14` linkage and pagerank |
| D-17 | **Every placed node landed on a frame corner.** `_spread` kept the fit's distribution so a newcomer could be ranked against it, but `column = out[:, axis]` is a numpy VIEW and the next line overwrote it with the ranked values — so what was stored was the POST-spread column, 0..1, not the raw coordinates. `_spread_apply` then compared a raw UMAP coordinate (measured −3.42 .. 5.39) against a distribution spanning 0 .. 1: every point fell wholly below or wholly above, ranked to 0 or 1, and framed to exactly ∓300 | `G-34`, `G-54`, `G-55`, `G-56`, `G-16`, `G-65` — every path that PLACES rather than fits | **FIXED 2026-09-19**, reported by the user (*"opening a few pages re-sets all the UMAP embeddings… they all seem jumbled in the center"*). Measured on RFC 9110: 26 chunks at ONE point, 762 units from their own page node. After the copy: 0 of 144 coordinate values on the frame. `tests/test_projection_place.py`, and restoring the view fails it |
| D-18 | **Ranking a newcomer CLAMPED at the ends**, so everything past the fit's range collapsed onto the boundary — 101 of 200 chunks on one axis of one page, all at one coordinate | `_spread`'s own contract: *"the ORDER along every axis is preserved exactly and only the gaps change"* | **FIXED 2026-09-19** — `np.interp` places a newcomer BETWEEN its neighbours instead of on one of them, and beyond the support the tail slope continues, taken across the outer decile rather than the last pair (one gap between two extreme points is noise). The fit is over 96 page-means and the points it places are individual chunks, so falling outside is the ORDINARY case here, not an edge one. Saturation 9.0% → **0.0%** |
| D-15 | **56.3% of the corpus could not be retrieved by any query.** 7,955 of 14,129 chunks held an embedding and **no frequency row**, and retrieval is a strict triple product, so a zero on the lexical factor is a veto. **28 of 96 pages had no coverage at all** — RFC 9110 (1,173 chunks), the Rust `Vec` docs (1,097), `nodejs.org/api/fs` (835) among them | `G-3` the triple; `M-11` the chunk is what gets embedded and retrieved | **FIXED 2026-09-19** — `workspace.rebuild_lexical()`, a repair rather than a re-scan since the rows are derivable from markdown the store already holds: 6,174 → **14,129 rows** in 2.8s, vocabulary 228,923 → 411,660. Verified on the page that found it: scoping to RFC 9110 answered **0 hits for every query** before and returns 8 with real lexical and semantic scores after. `tests/test_lexical_coverage.py` asserts the invariant and repairs a PLANTED gap — without planting one the test passes on any fresh workspace and is evidence about nothing |
| D-16 | **A read-only workspace wrote to disk on close.** `Workspace.close()` saved `freq.npz` with no `read_only` guard, so every reader rewrote it on exit: the sidecar, an MCP server, a diagnostic script | Constraint 7 in spirit, and the plain meaning of opening something read-only | **FIXED 2026-09-19** — found by noticing `freq.npz` dated TODAY on a store last written six days earlier, and every one of those dates was a reader closing. Nothing observed was corrupted by it, and that is luck rather than design: anything that pruned the matrix in memory would have been persisted by a process that had promised not to write. The test asserts on the FILES, not on the flag, because a guard that was later reordered would still satisfy an assertion about `self.read_only` |
| D-12 | The spherical fit's **warm start has never run**. `spherical.from_ball` exists only to produce it and had ZERO callers; `_WARM_INIT` was bound to `None` at module scope and assigned nowhere, so the guard could not pass | `from_ball`'s own docstring: left to its own initialisation the fit *"collapses onto the identity rotation"*, which is why the warm start was written | **Wired 2026-09-19, and it does NOT rescue the fit.** `_spherical_init` now runs the Euclidean fit, centres it, and maps it through `from_ball`. Every spherical number ever quoted — including `G-18`'s 0.19 retention — was measured without it. Measured after: the page-level cone narrows from 15.3° to 11.4° and is still a cone. On synthetic clustered data the same code spreads properly (cone 128°, median 73°), so the concentration is **this corpus's page vectors**, which are renormalised means of chunk vectors. The Euclidean view's apparent spread is `_framed` rescaling, which the spherical path deliberately skips. See `G-19` |
| ~~D-11~~ | ~~`?space=S3` is accepted, cached as honoured, and silently ignored at the default level~~ | *"apply the updates to our UMAP metric **throughout**"* (2026-09-13 21:23, reaffirmed 22:00) | **FIXED 2026-09-19** — `build_page_layout` takes `spherical_space` and its reply names the space it produced. Confirmed live: the pane's toggle reads S³ and `?space=S3&level=page` returns `space: "S3"` where it used to return no `space` field at all. The xfail is now a plain assertion |
| ~~D-7~~ | ~~A media element with no alt text renders as a bare `![images]`~~ | **WITHDRAWN 2026-09-12 — not a defect.** Already fixed by `499fd6d` (M-9). Filed against `vaultws512`, built 34 minutes BEFORE that commit. On the 256 re-cut: **0 bare placeholders, 1,073 named**. See §M.0 | — |

**D-1 is FIXED** (2026-09-12, `layout: the projector fits on semantic alone`).
`build_layout` fits the semantic space alone; frequency is demoted to the
no-embeddings fallback and `fitted_on.semantic` names which happened. Verified
against the running plugin over CDP: `/layout` reports `spaces: ["semantic"]`
across 3,135 nodes. `halves` and `equalised` are gone with the machinery they
described. 19 tests, including a non-vacuity arm that fails if the embeddings
are ignored.

**Both D-6 and D-7 were withdrawn the same day they were filed**, and the two
failures had one cause: a metric invented for the occasion instead of the
instrument the repo already had. §M.0 and §M.3 record them, because the method
error is more reusable than either finding would have been.

### 0b. Resolutions by recency

Where the two statements disagree the later one wins. These are the judgments
that produced Part I, written down so they can be overturned rather than
inherited:

| the first statement asks for | the addendum says | resolution |
|---|---|---|
| chat contexts localized to a panel; **pull chunk panels into a new chat and aggregate**; chat within-chunk | *"add back the quantized chat feature as something **much smaller and minimal**"* | **Deferred, not dropped.** L-1..L-11 are the whole of the chat now: a rewind over the current notebook. Aggregation and cross-panel chat are out of this scope and survive as future work. |
| the **chained single-hop prompt architecture** — one generated system prompt per hop, outputs instructing the next, a final aggregate pass | *"put the LLM complexities aside"*, then a minimal embedded chat | **Deferred, not dropped.** Nothing in the addendum contradicts it; it is simply not this scope. It stays in `PLUGIN_GOAL.md` unnumbered. |
| *"no dedups"*, inside a list about elegance | *"full deduplication of repeat substrings that are essentially structural redundancies"* | **Deduplicate.** This is D-4, and it reverses how the phrase was read for most of the work so far. |
| the projector fitted on frequency **and** semantic | *"quantized semantic (and not pre-umapped frequency) vectors are the primary embeddings space for the projector"* | **Semantic only.** D-1. Frequency stays in retrieval (G-3). |
| panels "retrofitted to show their base and original markdown editors" | *"keep the original obsidian markdown panels in their native form as well"* | **No conflict** — both name the native editor. D-3 stands. |
| the window is **256**, and 512 loses on every measurement | *"512 max context window for text-only tokens. The projector shows the aggregated vectors while the retrieval still runs on the 256 chunks"* (Addendum IV, 21:17) | **Both, for different jobs.** 512 is the display and merge context (`G-27`, `G-28`); 256 stays the retrieval unit. The measurement below compared them for the SAME job and is still why retrieval is 256. |
| the spherical/quaternion fit is dropped — *"We'll drop the spherical and quaternion stuff"* (21:39) | *"If spherical UMAP works, and our aggregation is wired, please show that it works by processing everything we currently have in our DB"* (22:00) | **Rescinded after twenty-one minutes; the fit STANDS.** `G-18` is not an experiment held in reserve. Only the colour axis (`G-17`) is still open, and D-10 is the fit not reaching the default level. |

### Two readings that are still ambiguous

**"Quantized"** is used as the name of the semantic axis
(*"frequency-quantized-pagerank"*), which reads as *the quantized model's*
embeddings — the f16 GGUF nomic already in use. It could instead mean
product-quantized vectors, which would be a storage and ANN decision that does
not exist today. Part I assumes the first.

**The window question is SETTLED, and it was settled by being split.**
This section used to carry it as an ambiguity between 256 and 512.
Addendum IV (2026-09-13 21:17) answers it by giving each number a different
job: *"512 max context window for text-only tokens. The projector shows the
aggregated vectors while the retrieval still runs on the 256 chunks."* So 512
is the display and merge context (`G-27`, `G-28`) and 256 is the retrieval unit,
and stage one cutting at half of stage two's ceiling is what makes a merge of
two neighbours fit by construction.

The measurement below is what decided 256 **for retrieval**, on 2026-09-12,
and it stands unchanged. It compared the two numbers competing for ONE job;
the resolution gives them two.

| window | hit@1, three pages | over window | record tests |
|---|---|---|---|
| 64 | **85 / 90 / 83%** | 13.3% | nav AND prose split |
| 128 | 60 / 75 / 65% | 7.8% | prose splits |
| **256** | 45 / 48 / 58% | **2.5%** | **all 11 pass** |
| 512 | 48 / 28 / 45% | 1.0% | all pass |

Retrieval favours small monotonically; structure favours large. 256 is where
they meet — every structural property holds and it still beats 512 by about
ten points of hit@1 while filling half the window rather than a third. **512
is dominated *as a retrieval unit*: for that job it wins on no measurement.**
As the merge and display ceiling it is not competing here at all. 64 was tried first and reverted
because a nav bar split into three chunks of menu labels, against
`test_a_nav_bar_is_not_a_record_set`'s own reason — "a menu item is not a
retrievable unit".

The 64 column is an upper bound on its own advantage: those probes are
verbatim lines, which favours short chunks mechanically. The direction held on
three unrelated pages, so 256-over-512 is safe; 64-over-256 wants paraphrased
probes first.

### S. The scanner

| id | requirement | status |
|---|---|---|
| S-1 | Shadow DOM elements linked in **millisecond O(delta)** time | **Done — seen live 2026-09-20** (`confirm.mjs`). **The shape of an O(delta) claim is a constant delta against a growing page**, so the shadow fixture's own pager is pressed four times: each press appends six `result-card`s — each with its own nested shadow root — INTO a shadow root, so the delta is identical every round while the document grows. Measured per-delta folds of **3.40, 2.70, 2.40, 3.60 ms** while the page went from 6 cards to 30 — **5x the page, 1.06x the cost**. Null arm **0.10 ms and 0 chunks**: the fixture has essentially no motion of its own, so the figures above are the mutation and not the document. **The first version of this check PASSED on a meaningless statistic.** `repairMs` is CUMULATIVE — the sensor adds to it and `drain()` clears `front`, `removedIds` and `moves` but not the timer — so reading it per-delta gave 15.5, 18.7, 21.9, 25.4: a fold apparently getting steadily dearer, which was four cheap folds and a running total, and a "cost ratio" of one lifetime sum over another. Green, and not proof. Differenced, it is flat. **The 2026-08-29 `live_delta.jsonl` could not have answered this**: `sensor.js` changed 08-31, two days AFTER that artifact was written, and a store is a recording of what some past version did |
| S-2 | MutationObservers on every chunk root *and* every nested shadow root | Partial — a shadow root attached after the walk is unobserved |
| S-3 | Content detection across the full taxonomy | Done |
| S-4 | Deduplication, efficient, in the same O(delta) budget | **Partly — measured 2026-09-20, and the two halves of this row answer differently.** *Efficient*: yes. The phase is now separated from the undifferentiated 2.16s block, which the budget table recorded as "not separated". `_same_content` is **linear at 0.11 µs/chunk** (0.001ms at 10 chunks → 0.575ms at 5,337; 4x the chunks costs 3.5–4.5x the time at every step), so the corpus's largest page pays **0.575ms** — inside the millisecond range. *In the same O(delta) budget*: **no**, and the constant is what hides it. A one-chunk delta on a 5,337-chunk page re-hashes the whole page: **1430x** the work the delta needs. It is affordable, not delta-sized, and those are different claims. Completeness is separately **`D-4`** — this dedup is exact and chunk-scoped, and the verbatim asks for *substring* structural redundancy |
| S-5 | A **queue** mapping distilled markdown structures, in chunk-batches, to the vectorization steps | **Done 2026-09-20** — `vectors.VectorQueue`, and the note this row carried ("`flush_vectors` is a separate per-page pass") was reading the design as the defect: being a separate pass is what makes vectorisation a function of *settled* change. `tests/test_corpus_invariants.py` measures the two claims the existing queue tests never touched, both by **counting embedder calls**: a chunk rewritten 20 times between flushes costs **1** embedding (20 distinct chunks cost 20, which is the arm that stops this measuring the flush instead of the coalescing), and 40 chunks at `batch=16` leave as **[16, 16, 8]** — three calls, not forty. A queue embedding one chunk per call would have passed every other test in the file |
| S-6 | **tf-idf is global** to the full DB corpus, not per page | **Done 2026-09-20** — `tests/test_corpus_invariants.py`. One `FreqMatrix` over everything, growing as the corpus does; the shared unigram is one column, not one per page. The arm that makes it mean something: a term private to page B is IN the vocabulary page A's row is scored against — planted the per-page fitting and it reads False there, True here, which is the only way the two are distinguishable. Live scale after `D-15`: 14,129 rows over one vocabulary of 411,660 terms |
| S-7 | Every page interaction is mutation-observed and persisted through the panel's browser half to db, vectors and trie | **Done — seen live 2026-09-20** (`confirm.mjs`). A real left click, dispatched as an input event to the guest, appends a list item (2 → 3); the chunk the trie draws that list from then contains the clicked-in sentence, 356 → 449 chars, read back through `GET /resolve`. **The instrument is the chunk's markdown, not a count** — a count moves for a lazy image or a second capture pass, whereas the markdown either contains the sentence or does not, which is the affine map stated as a test. **Null arm: 0.** The page is a served fixture (`tests/fixtures/live_mutate.html`) whose only motion is the motion the check causes, so the same 5-second wait with no click changed nothing — on a live site that floor is never empty. Three arms earned the hard way: the aim must be **on screen** (a previous check's split had squeezed the cell to **3 pixels wide** and four runs read as the sensor refusing to fold), capture must have been **armed while browsing**, and the corpus must be **the same size after as before** (99 → 99) — a harness that grows the corpus it measures is changing its own denominator |
| S-8 | **Smooth, live-tuned steady scroll** per visit, tuned to Selenium's update rate, fine-grained and time-efficient | **Done — seen live 2026-09-20** (`confirm.mjs`). The scan ran six fixed passes at a 700ms pause and a 0.9-viewport step, which every page paid whatever it was. Now **both the pause and the step follow the page**: each drain that returns dirty chunks lengthens the pause and snaps the step back to fine; each empty one shortens the pause and coarsens the step, and the loop stops when the page has been seen to the bottom AND the trie has stopped changing. In trie terms nothing about WHAT is written changes — each drain still carries one delta — what is tuned is WHEN the next delta is asked for, and when to stop asking. **Measured as an A/B against the old cadence, on one page in one session, with the tuned arm going FIRST so any warm-cache advantage falls to the arm it is trying to beat**, and the url purged between arms because a re-scan drains nothing and the tuned arm would otherwise "win" by measuring nothing. Short page: **3 passes / 1,399ms against 8 / 5,104ms — 3.7x — for the same 6 addresses**. Tall page with lazy blocks: **11 passes / 5,830ms, settled**, against 8 / 6,225ms **that never reached the bottom**, same 26 addresses. The pacing is legible in the evidence: pauses `560, 784, 470, 282, 395, 237, 142` and steps `0.5, 0.5, 0.75, 1.13, 0.5` — coarsening while quiet, fine again the moment a lazy block lands. **Two criteria, not one**, because the row makes two claims that separate: the short page scores time, the tall one scores settlement, and scoring the tall page on the clock alone would have credited not finishing. A first flat-0.5 attempt was **slower than what it replaced** (7.9s against 6.2s for identical addresses) because every pass costs a round trip; that is why the step is tuned and not merely small |
| S-9 | Pagination deliberately **not** automated — manual, in the browser views | By design |
| S-10 | Browser streams ported to the panels efficiently, *"completely and exactly mirroring features/calls to the original selenium"* | Partial — rrweb is the architecture; its shadow-DOM capture is the wrong half |
| S-11 | The **256-token** window holds **throughout processing**, with a verification pass after the scan. A target, not a ceiling: a single indivisible unit may exceed it | **Partly — the verification pass now exists** (`vertiscope/analytics/window.py`, `--window-check`), which is the deliverable that kept this row Partial. It is what the row's other half is now measured by, and the answer is not yet clean. Measured on `build/corpus123` at 256, **with the two populations separated because they ask different questions**: chunks the chunker COULD have cut — **74 of 11,155 over, 0.66%**, max 803 — and single-line leaves, where the row itself permits an over — 161 of 2,978, 5.41%, max 1,554. **And the stage nobody had checked**: a merge group's assembled markdown is a new string, longer than any member by construction, and it is what a reader is shown and what re-vectorisation embeds — **5 of 517 over, max 309**. The pass counts what the ENCODER gets (`tokens.budget_for`), so a `code://` chunk is scored on the string after code spans are dropped; a budget enforced on one string and spent on another is not a budget. Non-vacuity: planting a multi-line oversize record is caught at cost 1,139 and the clean arm does not report it (`tests/test_corpus_invariants.py`). The **0.4% (21 of 5,337)** this row used to carry was a MIXED denominator over both populations on a different store; separated, the cuttable residue is 0.66% and the permitted one is 5.41%. What remains open is the 74 and the 5, not the pass |
| S-12 | Every sensor→db stream reaches the graph view **and the opened *and closed* panel set, uniformly** | **Done — seen live 2026-09-20** (`confirm.mjs`), **and it was false when first measured.** A real click appends a list item; the store gets it, the graph has the node, a panel opened afterwards shows it (539 chars) — and the panel that was **already open sat unchanged at 448**. In trie terms: a capture writes the dirty chunks to the trie, and an open panel is a reader of one address in it that read once, at open, and was never told to read again. Fixed by `ChunkView.refreshIf`, driven from the same dirty-cid signal the projector already absorbs; `show` could not be the fix because it returns early on an unchanged cid, which is right for its own job — what changed here is the CONTENT at an unchanged cid. **Planted the defect back and the numbers moved** (448 → 448 again), which is also what proved the harness now reloads the plugin rather than scoring a build nobody was running. Measured after the fix: 448 → 539 open, 539 reopened, node present, trigger `input-event` **Regressed and re-fixed 2026-09-26.** Addendum VI retired the chunk pane and moved a chunk's two forms to a pin (side panel + billboard, `G-78`); the refresh did not move with them. The pinned side panel held the markdown read at pin time -- 364 characters before the click and after it, with the billboard beside it updated (4,873 -> 4,964) -- and the check could not see it, because it still opened the retired pane and failed on "view.show is not a function", which reads as a harness fault. Now a capture's `dirty_cids` re-read every pinned chunk they name (`BrowserView.refreshPins`, O(delta): one resolve per touched pin) and redraw every open billboard they name, not only newly placed ones. Check `S-12` rewritten to the pinned forms: fails on the old build (side 364 -> 364), passes on the new (364 -> 455), fresh store both times |
| S-13 | **Investigate** whether Electron can be driven directly to give "the same sensor-like functionality" as Selenium — deliverable is a capability verdict with evidence, NOT a migration | **Verdict delivered (§N)** — yes: `BrowserWindow`/`WebContentsView` + `session.fromPartition` + `preload` + `webContents.debugger`, all reachable from plugin code; MutationObserver attaches; and Electron loaded apnews.com in 26.4 s where geckodriver timed out at 40 s. Migration NOT decided — §N.4 lists what is untested |
| S-14 | Whatever hosts the sensor must keep **profile control "from their base"** and stay "slim on web interfaces" | **Available on the Electron host** — `session.fromPartition('persist:…')` gives an isolated persistent profile, verified (§N.2). Counter-cost in §N.4: Chromium's version becomes Obsidian's, not ours |
| S-15 | One page's failure must not end a corpus run; every failure is named and the exit code is non-zero | **Done** — `cmd_scan` collects per-page failures; a 24-page re-cut had been aborted by apnews.com alone |

### T. The trie and the database

| id | requirement | status |
|---|---|---|
| T-1 | One trie keyed domain / url-tail / xpath / markdown / content-detection | **Defect D-2** |
| T-2 | It reconstructs the **full digital trace** of the page, not only its content | Partial |
| T-3 | Shadow DOM nodes localized to their **ancestors in the trie**, giving structural guarantees on the distilled HTML | **Done — seen live 2026-09-20** (`confirm.mjs`). Asked of the SET of addresses and their prefixes, via `GET /addresses`, because that is what "localized to its ancestors" is a claim about — `/resolve` answers "which chunk draws this point", which is the reader's question and the wrong one here. Measured on `tests/fixtures/shadow_catalogue.html` scanned in the browser cell (the same sensor, read from the sidecar at request time; no second browser and so no leaked processes): **66 addresses, 63 of them inside shadow roots, 54 of those nested two or more deep, 0 orphans, 0 rootless, every nested path prefixed by its outer boundary**. The deepest is three roots down and keeps its ordinals across the boundary: `/html/body/result-list/#shadow-root/div/result-card[2]/#shadow-root/article/card-meta/#shadow-root/p/text()[1]`. **The non-vacuity arm was run, not asserted**: pointed at a shadow-free page the same check reports 0 orphans, 0 rootless and nesting-ok — every clause passes except the first, which is exactly the vacuous pass that clause exists to block, and exactly what every live site reachable during development would have produced |
| T-4 | Intermediate trie paths reflected as **intermediate chunk-node linkages** | **Done — seen live 2026-09-19** (`G-6`), plus `tests/test_corpus_invariants.py` for the half a pane cannot see. `layout.unfold` emits a `path:` node for a branch standing in for several chunks and the hub star joins them: 26 nodes, 26 links, 0 dangling on RFC 9110. The trie half is asserted on depth — a nested page reads 5 where a flat one reads 0, so the measure moves with the nesting it claims to reflect |
| T-5 | The **local vault** is in the trie | **Done** — `vertiscope/vault.py` + `Workspace.index_note` + `vertiscope notes <dir>`. Addressed `vault://<vault>/<path>` with markdown's tree as `section`-wrapped xpath steps; 18 docs indexed to 786 chunks / 2,697 addresses and retrievable. Module dependencies and the directory tree as UMAP links (`G-8`/`G-10`) are still Open |
| T-6 | **Installed Python packages** are in the trie, per-package partitioned with main-DB links | **Done 2026-09-20** — `G-9` measured it (numpy: 12 files → 510 addresses, 123 chunks, `code://pypi/numpy/…`) and `G-49` put it in the one store beside the web scans and the vault. **The url IS the partition**, which is why nothing separate has to be maintained. `tests/test_corpus_invariants.py` holds the arm: the same file under two packages is two addresses, and collapsing the root reads 1 where the real corpus reads 2 |
| T-7 | Semantic vectors **and** hard graph links in the **same database** | **Done 2026-09-20** — one kuzu store: `embedding` and `group_embedding` are columns ON `Chunk`, beside the `LinksTo`, `Contains`, `HasChunk` and `Anchors` rel tables. Asserted in `tests/test_corpus_invariants.py` by a single traversal returning a chunk's vector AND the page it links to — a query that could not be written at all were they two stores, which is the strongest form the row has. The no-anchor arm returns 0 edges, so the join is not passing on an empty corpus |
| T-8 | The trie is streamed to the panels' interactive side | **Done — seen live 2026-09-20** (`confirm.mjs`, `S-12`'s check). The panel that updated from the capture stream was drawing its **interactive** face, not its markdown one — `surface_mode` is reported so the row is cited rather than inferred, since "the panel updated" does not say which of the surface's two faces was drawn. That face renders the distilled DOM as ELEMENTS with their addresses wired, into the surface's own shadow root: a `<button>` is there because the trie says the element at that xpath is a control. Measured live: 448 → 539 characters on the already-open panel as the stream landed |
| T-9 | The xpath **shape** exists as a second address dimension, never as the identity | Done |
| T-10 | A delta that moves content must **retire the address it left** — the trie must not hold an address the page does not have | **Holds, on what has been tested** — `--drift --kind insert` repaired ~190 moved addresses with 0 stale and 0 lost, 3 of 3 exact; `--resolvable` 0 of 719 unresolvable. Not yet tested on a live/mutating page (§M.3) |

### M. Markdown distillation

The quality bar is the Milkdown playground's left editable pane, on four named
axes: **structure, content, organizedness, completeness**.

| id | requirement | status |
|---|---|---|
| M-1 | The **full content** of the original in-browser HTML survives | Partial — reach 37.1% |
| M-2 | **Hierarchically header-structured** | Partial |
| M-3 | **Tables** | **Confirm** 2026-10-11 -- see `D-5`: laid out with spans, named away from the header, stored and drawn in the panel |
| M-4 | Images, web links, embedded links | Partial |
| M-5 | **Markdown panel links** to other panels | Partial — continuation links done, retrieval links absent |
| M-6 | Renders in regular / normal / **minified** form | Partial |
| M-7 | **No intermediated hierarchical fields** where a single trie path node was collapsed | **Confirm** 2026-10-11 — seen in the app: the running sidecar stored a fresh capture of Okapi as 182 chunks, 1,887 lines, **0 with an empty indent level, 0 starting indented** (read back through `/chunk`, whose lines carry their indentation). Built and measured: `markdown.py::_level_page` now levels each chunk from its own lines' parents (a line one step below the nearest preceding line drawn shallower; none, the margin), where the page-wide mapping left an empty indent wherever a depth branched elsewhere on the page. `python -m vertiscope.analytics.levels` (2026-10-11, all 136 frozen pages rendered fresh, 14,859 chunks): chunks with an empty level **38.23% -> 0%** (24,647 lines under one -> 0), chunks starting indented **87.44% -> 0%**; containment **98.31% both arms** (51,235 of 52,117 ancestor pairs); depth rho 0.916 -> 0.902 (cousins at different page depths now drawn level under one parent). Planted `PLANT_PAGE_LEVELS` reproduces the filed 39.0%. `tests/test_levels.py` |
| M-8 | **Full deduplication of structural redundancy** | **Partly** -- see `D-4` (structural repetition within a chunk drawn once; data never folded) |
| M-9 | A control is named by the page, never by the taxonomy | Done — 1,556 lines → 2 |
| M-10 | **Full structural preservation along content links in nested shadow DOM nodes** | Open |
| M-11 | Quality holds **at the interactive chunk level**, because the chunk is what gets embedded and its structure decides how representative the vectors are | Open |
| M-12 | Reading order matches the document | Done — 100% |
| M-13 | A media element renders with something that **distinguishes it** — alt text, a filename, or `![]`, never the taxonomy | **Done** — `499fd6d`; on the 256 re-cut 0 of 1,073 media render as a taxonomy placeholder. Filed briefly as D-7 against a stale store and withdrawn (§M.0) |

### G. The projector and the graph

| id | requirement | status |
|---|---|---|
| G-1 | Projector fitted on **quantized semantic vectors only** | **Done** — `D-1` fixed 2026-09-12. `build_layout` and `build_page_layout` both report `spaces: ["semantic"]`; frequency is the no-embeddings fallback only |
| G-2 | Chunk embeddings batch-UMAPped **with their per-document source** — two node kinds, one fit | Open |
| G-3 | Retrieval stays **triple**: frequency × quantized-semantic × pagerank | **Done — seen live 2026-09-19** (`confirm.mjs`), and the check needed a second arm. It asserted that the hits it got carried all three factors and that each VARIES — present-and-constant is not ranking anything. That passed throughout `D-15`, because only chunks that CAN be returned ever carry factors, and 56.3% of the corpus could not be returned at all. It now also samples the six largest pages and requires each to answer a scoped query about its own words |
| G-4 | **Inter-spatial normalization** — nodes are discernible, not a clump | **Partly** 2026-10-11 -- re-measured through `__vertiscope.ui()` in the pages view: the cloud spans **36.8% of the canvas** (was 23.8%), 908 of 916 nodes on screen, and in world space **0 of 255** url nodes overlap (`G-21`). No bar was ever stated for "discernible"; the screen-space overlap figure conflates depth (`D-25`). Was: Defect D-25 — measured on screen the cloud uses **23.8% of the canvas** with more than half its nodes overlapping, and at chunk level it sits in one quadrant with 116 of 558 nodes off the canvas. The previous pass was scored in fit space, where the spread is real and invisible to a reader |
| G-5 | **Every node is on screen at the default camera** | **Partly — true at the level it was tested, false at the other.** Page level: **0 of 97 off screen**. Chunk level: **116 of 558 off screen**, 21%. The row does not say which level it means and the check only ever saw one of them **Fresh store, 2026-09-26: 33 of 41 on screen** after the suite's earlier checks opened pages -- the mixed-level case, still failing |
| G-6 | **Patricia-trie links drawn** | **Done — seen live 2026-09-19** — `confirm.mjs`, re-runnable and idempotent. Unfolding RFC 9110 draws **26 nodes and 26 links**, 0 unresolved endpoints, 0 dangling; all 26 carry a three.js line object attached to the scene, and the star is visible on screen. **The `Confirm` was hiding a defect.** The row claimed 31 nodes and 30 edges; live it was 26 and **0**, because `_edges_among` cannot draw an edge at the step a reader takes: containment runs parent-to-child and the branches are disjoint subtrees, so every edge it finds lies inside one branch and is dropped as a self-edge. Measured on that page: 1,072 containment edges, 662 with both endpoints surviving, **0 crossing two branches**. The 30 edges were a star from the parent, and `unfoldNode` had started REMOVING the parent. The hub now stays, shrinks to its smallest branch, and drops its picture |
| G-7 | **Markdown retrieval links drawn** | Open — and `G-14`'s measurement bounds what is available: page-to-page web links cannot be drawn in this corpus at all (0 possible edges). A markdown/vault link axis is a different edge set and is still unbuilt |
| G-8 | **Module dependency links** for codebases and Python modules | **Done 2026-09-20** — and NOT as a second graph. An import is categorised as a link, so `ContentAddress.is_url` says so, the store's existing `_link_pages` resolver picks it up, `edges()` routes it and PageRank counts it — the same treatment a hyperlink gets, which is the whole reason for spending an address on it. Measured on `vertiscope/` itself: **102 modules, 232 dependency edges, 2,180 edges for PageRank** |
| G-9 | …including modules inside **local PyPI packages** | **Done 2026-09-20** — the same walker pointed at an installed package, located by import rather than guessed at a path. Measured on numpy: 12 files → 510 addresses, 123 chunks, addressed `code://pypi/numpy/…` |
| G-10 | **Vault directory** drawn as links | **Done 2026-09-20** — a note's links become `LinksTo` edges through the same resolver a hyperlink and an import use. One change made it possible: `urljoin` performs relative resolution only for schemes it KNOWS, so `urljoin("vault://v/a.md", "b.md")` hands back `"b.md"` unchanged — not an error, just the input — and every vault link therefore resolved to nothing. `canonical_url` joins local schemes by hand now. A wikilink gets the `.md` spelling offered as well, since `[[Lattice]]` names a note and a note is a file; the store's own rule still decides, so a wikilink to a note nobody indexed stays an address — asserted as its own arm |
| G-11 | **Three sources in one skeleton**: web, vault, PyPI | **Done 2026-09-20** — one store holding all four spellings at once: `https://`, `vault://`, `code://` for the repository and `code://pypi/` for an installed package. Measured: 59 chunks, 653 addresses, **one trie**, every chunk's xpath resolving the same way whatever it came from. `tests/test_source_corpus.py` asserts the schemes coexist |
| G-12 | **UMAP embeddings persisted to the db** and queried straight into the graph view | **Done 2026-09-20** — a `Layout` node table keyed on everything the fit is a function of (corpus size, dims, space, level), so a stored answer comes back only to the question it answered. Measured on `corpus123` across a sidecar RESTART: **19.3s → 0.15s**, and the reply says `from_store: true` so a reader can tell which they got. A table rather than columns on `Chunk`: the payload belongs to a fit, and four fits of one corpus (page/chunk × euclidean/S³) would not fit in one column each. **The hazard it introduces is guarded**: a fitted reducer is a MODEL and does not serialise, so serving a stored layout would have left every unfolding answering "no fit to place into yet". `_ensure_projection` builds one on demand — verified live, 26 nodes and 26 edges out of a process that had only ever served a stored picture |
| G-13 | Re-projection **batched in a queue whose latency adapts** to the projection's own cost | Open |
| G-14 | **Graph linkage completeness** across trie, web links, markdown links | **Partly — and the web-link axis is EMPTY for a measured reason, not an unbuilt one.** The trie axis is drawn and confirmed live (`G-6`). The web axis holds **2** `LinksTo` edges over 96 pages, and `store.relink()` — a repair that re-resolves every url address against the pages held now, since a link is otherwise resolved once at ingest against whatever existed then — adds **0**. The ceiling is 0, and here is why: of **29,186** url-valued addresses, **2,675** are anchored to a chunk and **72** resolve to a page this corpus holds, and the two sets **do not intersect**. The links that point at pages we have are in addresses no chunk draws; the links chunks draw point outside the corpus. That is a property of a collection of unrelated pages rather than of a crawl, and `relink` stays because on a crawl it is the difference between a link graph and a scatter |
| G-15 | **Media present in the projector**, not only the panels | **Done — seen live 2026-09-19** (`confirm.mjs`). Nodes carry an `image` and draw as billboards; `G-21` separately confirms they are COLLIDED as panels rather than spheres |
| G-16 | Chunk deltas diffed **into the projector view** live | **Done — seen live 2026-09-19** (`confirm.mjs`, needs a `--capture` sidecar). The whole path in one gesture: the browser pane folds the page it is showing, `POST /capture` writes it, the worker vectorises, `place_into` anchors, and `absorb` takes the nodes into the picture already on screen. Measured on `books.toscrape.com`: **320 addresses, 26 chunks over 7 passes**, and all 26 arrived in the projector with a position, **0 on the frame** — the last being the arm that `D-17` would have failed while every count above it still looked right. 96 → 122 nodes |
| G-17 | The projection's **output space is spherical**, fitted with an angular metric rather than rescaled into a cube afterwards | **Built (`G-18`); what is Open is the COLOUR axis only.** Addendum III asked whether the third angle is spent on colour (S³) or the fit is S² and colour becomes a legend; that is still unanswered. The metric itself was dropped at 21:39 and rescinded at 22:00 — see Addendum IV, "Addendum III, dropped and then restored" |
| G-18 | Points are **quaternions and the distance between them is the quaternion distance** — the geodesic angle on the unit 3-sphere, `2·arccos(\|⟨p,q⟩\|)`, absolute because `q` and `−q` are one rotation | **Built, measured, not default** — `vertiscope/obsidian/spherical.py`, §M.9. A numba `output_metric` over three hyperspherical angles (umap-learn's own advice: parameterise without coordinate constraints), gradient-checked against finite differences. It keeps **0.19** of the encoder's 10-NN neighbourhoods against the Euclidean fit's **0.38**. **"Not default" understates it: see D-11** — at the default page level `?space=S3` is accepted and ignored, so the user's *"apply the updates throughout"* (21:23) is not met by the surface they actually open |
| G-19 | The view is **centred on the origin** | **Partly — true by construction, not true of the picture.** `spherical.to_ball` does send the identity rotation to the origin. But nothing puts the DATA near it: measured on 96 pages, the centroid sits 94.0 from the origin against a mean radius of 94.9 — every page on one side — so the origin-centred camera frames an empty middle with the corpus as a blob off to one side, which is `G-5` failing in S³. `_spherical_init` now centres the warm start (D-12), which moves it without fixing it. The verbatim is *"we center our focus on the origin"*, and that is a claim about where the data goes, not only where the camera looks |
| G-20 | **Force-directed relaxation seeded from the UMAP embedding** — UMAP initialises, the simulation converges | **Done** — `graph.ts`. Nodes carry `x/y/z` from the fit instead of `fx/fy/fz`, and `fitX/fitY/fitZ` alongside so drift is measured rather than assumed. `charge` and `center` are removed and `link` is kept at **zero strength**, not removed: `forceLink` is also d3's id resolver, and dropping it left all 2,961 edges holding their endpoints as strings, so every patricia and inter-note link stopped drawing with nothing reporting an error. Measured cold: 2,302 of 5,337 nodes sit exactly where the fit put them, which is the proof no force but collision runs |
| G-21 | **Nodes never overlap**, with billboards sized as panels not spheres | **Confirm** 2026-10-11 (was Defect D-25: 54 of 97 url nodes overlapping on screen) — the check measured fit-space separation against a fit-space radius and passed. Measured in SCREEN pixels through the application's own `nodeRelSize`: **54 of 97 page nodes overlap** a neighbour at the drawn radius, closest decile 10.1px apart. The billboard half is untested at the pixel level **Re-measured 2026-10-11 in WORLD space** at the application's own `drawnRadiusOf` (the screen count conflates depth, `D-30`): 30 overlapping url-node pairs, every one a copy of a fixture page (`busy_feed.html` from two test ports) at the SAME fit point -- identical content, and pinned at rest the collider never parted them. Url-node targets are now relaxed like a page's chunks, spheres at the safety factor, collisions only (`graph.ts`, `roomStats.parted`; planted `plantPagesTogether`; `tests/camera.test.mjs`): **0 of 255** overlapping; planted **129**, worst coincident. Real pages had 0 already. |
| G-22 | **The chunking window counts only what a model reads.** Link targets — `href`, `src`, bare urls — are excluded from the token budget; the render keeps them | **Done** — `tokens.for_model`/`tokens.budget`, §M.7. 52.5% of the corpus's rendered tokens were addresses. **No live check, and deliberately so**: the comparison that matters is `budget(x)` against `count(x)` over the same string, and the tokenizer is server-side — a whitespace word count is not a baseline for a subword tokenizer, and a check built on one reported a link-heavy chunk at ratio 1.06 and called the exclusion broken. §M.7 is the measurement |
| G-23 | **Two vectors, two strings.** The quantized semantic embedding is given link-free markdown; the frequency matrix keeps url path words as lexical terms | **Done** — `vectors.VectorQueue.push` strips; `vectors.tokens` does not. An address is not a sentence; a url tail *is* a term |
| G-24 | **Exact duplicates are resolved in the database, over the aggregate DOM chunks, before any embedding is consulted** — page-scoped, byte-exact, no threshold | **Done** — `graphstore._same_content`, §M.8. Marked, not merged: `Anchors {ord}` pairs lines to addresses by position, so collapsing the nodes would misattribute every line |
| G-25 | **One node per distinct rendering in the projector**, with the copy count carried, not one node per address | **Done** — `layout.py`. archive.org drew a cluster of **125** identical nodes; dropped before the fit, because a duplicate embeds to the same vector and spends the projector's neighbourhood budget on a point it already has |
| G-26 | **Stage two: near-duplicate aggregation over the quantized semantic embeddings.** DBSCAN (or a nearest-neighbour feature aggregation in its place) merges chunks that are the same thing said differently, which exact bytes cannot reach | **Done** — `vertiscope/aggregate.py`, DBSCAN over the quantized semantic vectors. 494 groups over 1,248 chunks on `corpus123`, against a null arm of zero (§M.12) |
| G-27 | **The merge layer indexes; the 256-token chunks remain the retrieval unit.** A merged chunk is what is structured and presented, up to the 512-token display context; the originals and their embeddings stay underneath and are still what a hit resolves to | **Done** — `group_of`/`group_n` mark, never merge; the 256-token chunks and their vectors stay underneath and are what a hit resolves to. Coarse ranking suppresses a group's members so the lead speaks for them (§M.13) |
| G-28 | **The window is a staging device, not a hard constraint.** Stage one cuts conservatively at a window that is a strict subset of the display context; stage two merges back up | **Done** — stage one cuts at 256 link-free tokens, stage two merges up to `MERGE_WINDOW` 512. The 256 is deliberately half of it, so a merge of two neighbours fits by construction |
| G-29 | **"Exact duplicate" and "should be merged" are different verdicts and are decided separately.** Substring matching is explicitly rejected for the second | **Done** — two verdicts, two mechanisms: `G-24` decides exact duplicates on bytes with no threshold, and stage two decides merges on a radius read off the page's own neighbour distribution. Substring matching is used for neither |
| G-30 | **Frequency vectors verify the merge, as their own step, after dedup** — not mixed into the first pass | **Done 2026-09-19** — `workspace._lexically_verify`, called from `aggregate` after the semantic decision. Measured over the corpus: **19 pages, 748 groups, 14 flagged (1.9%)** — worst `ourworldindata.org/grapher/population` at 7 of 16. The merge STANDS and the doubt is recorded: tf-idf is the wrong instrument to overrule a meaning judgement with, and a page's furniture shares words with everything on it. Restricted to each group's own nonzero columns, which is exact for cosine and avoids densifying a corpus-wide vocabulary. `tests/test_aggregate.py` covers both arms plus the wiring |
| G-31 | **Aggregation is localised to a shadow DOM, not run over the corpus.** It is a second stage of *chunking*, inside the scan, coarse-to-fine — not a separate offline pass | **Done** — `aggregate_page` is called per url and sees one page at a time. Corpus-wide clustering would merge a paragraph on one site with a paragraph on another |
| G-32 | **A significance gate**: stage two runs only once a page has yielded enough chunks from the recursive text-only window for the pairwise distances to discriminate | **Done** — two gates: `MIN_CHUNKS` 24, and a structure gate on the shape of the neighbour distribution (p10/p90 < 0.25). §M.12 records why the radius alone was not enough |
| G-33 | **Structure enters the pairwise metric.** Either pagerank over the soft adjacency of the shadow DOM in its current state, or an LCA path metric over the patricia paths | Open — `lca_distance` is implemented and deliberately NOT wired in. The requirement says measure what a structural term adds before adopting one, and that measurement has not been made |
| G-34 | **Online aggregation.** The similarity structure is maintained diff-efficiently across a continuous scan: a merge or split re-vectorises only the chunks it touched, and the UMAP update is batch-minimal | **Partly** — live aggregation runs on the diff stream (`G-65`) and placement transforms into the existing fit rather than refitting. It is not INCREMENTAL: a page re-clusters whole, in ~110ms, which §M.12 argues is the right trade and records as a decision rather than an omission |
| G-35 | **The projector's force-directed relaxation and picture billboards survive every aggregation update** | **Done** — verified after live insertion: 0 overlapping pairs of 719,400, extent unchanged, 2,302 of 5,337 nodes exactly where the fit put them |
| G-36 | **The browser cell is an Electron browser**, and it is one component with two hosts: standalone panel, or a cell inside the notebook. Same functionality in both; one is a collapsed view of the other | **Done** — `browser.ts`, a `<webview>` chosen over `BrowserView`/`WebContentsView` because it flows with the DOM and therefore resizes with the panel. Standalone pane only so far; the notebook-cell host is not built |
| G-37 | **One panel, two toggleable views**: the live Electron browser, and the same content as a **native Obsidian markdown panel** rendering the full markdown — not a reduced one | **Done — seen live 2026-09-19**. The markdown face was a placeholder waiting on `G-39` and is now filled by it, rendered with Obsidian's own `MarkdownRenderer` rather than a code block. Relative targets are resolved against the PAGE: the distiller keeps a link as the document wrote it, so `media/cache/….jpg` asked the VAULT for a file of that name and rendered as "could not be found" |
| G-38 | **Hovering a chunk in the browser highlights it minimally**, and highlights the corresponding node in the 3D projector. No banner, no chunk details — they are already on screen | **Partly — the correspondence is built and seen live, on RIGHT-CLICK rather than on hover, and the difference is a constraint, not a shortcut.** Right-clicking rings the chunk's node in the projector (`confirm.mjs`, under `G-39`); at the default page level it rings the PAGE node standing for the chunk, since no chunk node is drawn until that page is unfolded. **Hover itself is blocked on a decision only the user can make.** Measured, three ways: (1) the host never sees the cursor — a `mousemove` listener on the `<webview>` element caught **0 events** while the pointer crossed it, because the guest swallows them; (2) Chromium *can* paint the highlight with nothing added to the document — `Overlay.highlightNode` was seen to shade a product card, which is exactly the "minimal, no banner" the row asks for; (3) but it reports no node identity for synthetic input, on hover **or** click — three `Input.dispatchMouseEvent` moves plus a full press/release yielded only `DOM.setChildNodes`. So the only route to the literal requirement is a `mousemove` listener INSIDE the page, and **constraint 7 forbids writing into the page**. Either that constraint is relaxed for a read-only listener, or hover stays a right-click. The half-built inspect-mode machinery was **withdrawn rather than shipped**, because a button whose behaviour cannot be verified from the harness is the thing this project keeps calling a green suite that proves nothing |
| G-39 | **Right-click ports the full-content markdown to the other view** in the same panel | **Done — seen live 2026-09-19** (`confirm.mjs`). The webview's own `context-menu` event, raised in the HOST: nothing listens inside the page and nothing is written into it, and the single read is `elementFromPoint` at the cursor, on demand (`G-41` holds). The xpath is built with the trie's own convention — index omitted for the first sibling, present for the rest, so `li/a` and `li[10]/a` are addresses and `li[1]/a` is not one at all. New route `GET /resolve` walks UP from there, because a reader points at a span inside a paragraph inside a section and only one of those is a thing the trie holds; `ancestors_walked` says how far. Measured: pointing at a product link resolved 2 ancestors up to its `article`, 199 chars over 10 rendered elements, every target absolute, **and one node ringed in the projector** (`G-38`) **2026-09-26: the check now asserts the face does NOT switch** -- the markdown renders beside the page (`G-78`, `G-82`); asking for face === "markdown" scored a correct app as failing |
| G-40 | **Clicking a node in the 3D projector navigates the browser to that chunk** — same session, scrolled into view, rather than a new rendering of it | **Done — seen live 2026-09-19** (`confirm.mjs`). The machinery existed and was private: `goToHit` already navigated and scrolled by xpath, reachable only from the overlay's own result rows. Now `browser.reveal(url, xpath)`, brokered through the plugin so neither pane requires the other. **`build_layout`'s chunk nodes carried no xpath at all** — `unfold`'s always had — so a chunk clicked in the chunk-level view had a url and nowhere on the page to go; they carry `path` now. Measured: the page parked at scrollY 4945, the click moved it to 363 with the addressed element in the viewport |
| G-41 | **Nothing is injected into the page.** The retrieval overlay and the highlight are a layer *above* Electron, linked to the store, never script written into the document | **Done** — the overlay and the search bar are Obsidian's own DOM drawn over the webview, verified to paint above it. Nothing is written into any page |
| G-42 | **A retrieval panel above the browser, results overlaid**, selecting one navigates to its url and chunk | **Done** — `browser.ts`, `GET /search`. Obsidian's own DOM drawn over the webview and verified to paint above it; selecting navigates and brings the chunk into view by evaluating its xpath and calling `scrollIntoView`, which reads the document and moves the viewport without writing anything into it |
| G-43 | **A hoverable chat panel on the browser**, whose context is exactly the right-clicked full markdowns, **each sent at most once** — the context window is updated by delta the way the scan is | Open — §O.2 |
| G-44 | **The chat is continuous markdown**: outputs land below the selected markdown, in conversational structure, and inside a notebook they append to the selected cell with the rewind rules unchanged | Open — §O.2 |
| G-45 | **The selection gesture is the delta.** The right-clicked elements since the last response are what is pre-injected into the next prompt — there is no separate context box | Open — §O.2 |
| G-46 | **Interactive fields in the shadow-DOM view act on the real page** through the trie, when a connection exists | **Confirm** 2026-10-12 live, end to end (sidecar started with `--enact`, the reader's choice): in a 3D panel over DuckDuckGo's results, "giraffe" typed into the panel's copy of the search box and Enter pressed THERE drove the live page in the cell from `?q=okapi` to `?q=giraffe` -- the act adjudicated by `/enact` plan, performed at the stored xpath (type, then the page's own Enter); planted `act-noop`: the page stayed on `?q=okapi` and the panel's readout said so (`scripts/check_panel_enact.py`). Open — §O.2, and it is constraint 2 of `CLAUDE.md`: a field is acted on in place |
| G-47 | **Scanning migrates from Selenium to the Electron browser** that hosts the cell, and that is where scanning then happens | **Done** — the browser cell folds the page it is showing and hands drains to `POST /capture`. Verified against the scanner it replaces on the same page: 176 addresses, 14 chunks, 7 passes, identical. Reported first as *"I don't see the scans running in the new browser panel like I would hope for our work"* (2026-09-13 20:34), which left no requirement at the time: the panel existed and Selenium was still doing the scanning behind it |
| G-48 | **Headers, fields and formatting are part of the text that gets vectorised** — the crypto-panel case is the standing example of what is lost when they are not | **Partly** — link-free markdown keeps headers, fields and formatting and drops only addresses, so the structure reaches the encoder. The crypto-panel case that motivated it has not been re-measured |
| G-49 | **The local codebase, the vault, and locally-installed PyPI packages are in the trie too**, alongside the web scans | **Done 2026-09-20** — `vertiscope/source.py`, addressed `code://<root>/<path.py>` exactly parallel to `vault://`, with Python's own tree as the xpath in the sensor's `name[ordinal]` spelling. Measured on this repository: **214 files, 16,074 addresses, 4,395 chunks in 33.4s** (156 ms/file). Nothing downstream learned a word — `from_tags`, the chunker, the frequency rows and the graph are the page path untouched, which is the whole reason the addressing was defined to look like a page's |
| G-50 | **The scanning code is itself a visible chunk.** A reader can see the script that runs the browser scan, in the graph, while watching that scan happen in the browser panel | **Done 2026-09-20** — `.js` joins `SOURCE_SUFFIXES`, so the FOLD is in the trie: `code://vertiscope/vertiscope/core/js/sensor.js`, **1,001 addresses over 71 chunks**, 67% of the render dropped before the encoder. It gets COMMENTS, not structure: `_js_comments` is a scanner that tracks strings and template literals so a `//` inside `"http://…"` is not counted — 1,000 comments over 2,870 lines — and it says plainly what it cannot do, the regex literal, rather than pretending a regex is a parser. The Python half (`capture.py`, the sidecar, the analytics) comes from `G-49` |
| G-51 | **Dependencies are tracked throughout** — imports and package requirements are edges in the same graph as page links | **Done 2026-09-20** — same graph, literally: `LinksTo`, the relationship a hyperlink uses. `canonical_url` passes `code://` and `vault://` through as identity rather than rejecting them, which is the one change that let a local address be a link target at all. **`relink()` is what makes it complete**: 100 edges at ingest, **232 after** — a link resolves once against the pages held at that moment, so a module that imports one indexed later gets no edge until the repair runs. Both spellings are offered for `from pkg import lib` (a submodule or a name) and for a package (the module file or its package init), and the store's own rule decides: a link becomes an edge only when its target is a page we hold |
| G-52 | **Source is vectorised by its COMMENTS AND DOCSTRINGS ONLY, never the code itself** | **Done 2026-09-20** — and it is one flag, because `vertiscope/source.py` makes the separation a property of the RENDER: docstrings, comments and names are prose, code is a code span. `tokens.for_model(text, drop_code=True)`, switched on by the `code://` scheme in `vectors.VectorQueue.push`. Measured over this repository: **985,336 rendered tokens → 304,039 for the encoder, 66.2% is code and is dropped** — the direct parallel to `G-22`'s 52.5% link targets, and the same argument: an identifier is not a sentence, the way a url is not. The code stays in the chunk a reader opens and in the trie that addresses it. **Off by default for everything else**, deliberately: a web page's code sample is part of what that page says, and dropping it would change every existing embedding to serve a requirement about source files. Both arms tested, and both directions of breakage fail the suite |
| G-53 | **The projector draws PAGES by default, not chunks.** One node per shadow DOM; a page unfolds into its chunks on demand | **Done** — `layout.build_page_layout`, `?level=page`. 96 pages over 14,169 chunks, **20,309 draw calls become 94**, and the fit takes 8.8s where the chunk-level one takes 95. A page's vector is the mean of its chunks', renormalised, and the fit is ON the pages — which is what lets a chunk be `transform`ed into the same picture when its page unfolds |
| G-54 | **Dynamic unfolding over the patricia trie** — an UNRAVELLING along a chunk's own single path, root to leaf, not an expansion of a subtree | **Done — seen live** (`confirm.mjs`). `layout.unfold`, `POST /unfold`, click in the pane. A step descends the shared path until it BRANCHES and shows the branches, which is patricia compression and is why a chain of wrappers nobody chose costs one step rather than five. **Where the chunks GO was wrong until 2026-09-19** (`D-17`, `D-18`) and is now a LOCAL fit anchored at the page node: transforming chunks into the page-level fit kept 0.078 of their 8-NN neighbourhoods against a random baseline of 0.030 — not a projection of anything. A fit over the page's own chunks keeps **0.507**. The page's mean cannot stand in for its chunks, because the mean is exactly the direction they all share and what distinguishes them is what is left after it is removed. Global position comes from the page node, which already carries it; colour stays the global fit's, so two chunks on different pages that mean alike still look alike |
| G-55 | **Unfolding depth follows the reader.** How far a page unfolds is a function of how many results they have continuously scrolled through in the browser's retrieval overlay | **Done** — §M.14. The overlay's hit list IS the depth: it grows as they scroll and the projector opens the page to exactly it. Measured: 10 chunks drawn, then 30 after three scrolls, 96 nodes to 125 |
| G-56 | **Only the chunks matching the most recent debounced retrieval query are drawn live**, inside their unfolded page | **Done** — §M.14. Clicking MDN's Headers index drew its **10 matching chunks**, not its hundreds, and the page node was removed |
| G-57 | **Clicking a node opens its shadow-DOM panel as a BILLBOARD inside the 3D view** — draggable, in the projector, not a separate Obsidian pane | **Done — seen live 2026-09-19** (`confirm.mjs`). `graph.openBillboard`, anchored by `graph2ScreenCoords`. Measured: 19 lines drawn, **anchored to 0px** of its node's projection, inside the canvas, follows the camera, **pins where it is dragged**, and closes. It runs its own frame loop rather than `onEngineTick`, because the simulation stops ticking once it settles and the camera keeps moving after that — a panel anchored on ticks detaches the moment a reader orbits, which is exactly when they are looking at it. The canvas needed `position: relative`: `graph2ScreenCoords` answers in the CANVAS's frame and the layer would otherwise have escaped to the pane and drawn every panel a caption-bar below its node |
| G-58 | **In tandem, the Electron browser navigates and scrolls that chunk into view**, and the browser is the primary panel representation | **Done — seen live 2026-09-19**. Both clauses now hold, and the second only became true with `G-57`: the navigate-and-scroll is measured under `G-40` (parked at scrollY 4945, click moved it to 363 with the element in view), and the Obsidian chunk pane no longer opens on a click at all — the panel became a billboard in the projector, so the browser is what shows the page and nothing competes with it for the workspace. §O.5 |
| G-59 | **The Obsidian-native chunk panels become the OFFLINE FALLBACK format** — the shape the structures take when there is no live page to point at, and **offline the billboard is a main Obsidian panel rather than a projector billboard** | Confirm — `obsidian-plugin/src/panelview.ts` (`PANEL_VIEW`), `GraphView.dockPanel`/`offlineNow` in `graph.ts`; live `scripts/check_offline.py` (2026-10-11), the cell offline through Chromium's own network emulation: a chunk's panel opened while offline is the SAME billboard element moved into a main pane (`docked 1, in_pane true, in_graph false`, 61 chars drawn); planted `plantOfflineBillboard` it stays in the projector (`docked 0, in_pane false, in_graph true`). The second clause is verbatim and is the one distinction from `G-57`: *"seeing still the billboarded panel that we currently have as a more 'main' panel within obsidian rather than in the UMAP projector"* |
| G-60 | **A toggle saves the full page as the Electron browser presents it live**, for offline use | Confirm — the "save offline ●/○" toggle in the browser cell's bar (`settings.saveOffline`, persisted, off by default); `BrowserView.saveOfflinePage` serialises the live document with Chromium's `webContents.savePage(…, "MHTML")` -- scripts already run, every resource inline -- plus its `textContent`, and `POST /offline` keeps it (`vertiscope/obsidian/offline.py`). Live (2026-10-11): Okapi saved once a visit, 1,631,010 bytes. A failed load is never saved: the first run kept Chromium's error page as Axolotl (744 bytes, `Snapshot-Content-Location: chrome-error://`), now refused by the cell (`loadFailedUrl`) and by the sidecar (`offline.is_the_page`, planted `PLANT_ANY_SNAPSHOT`); one already on disk is kept and never opened (`rejected`). `tests/test_offline_pages.py` |
| G-61 | **A saved page whose source does not carry its layout is INFILLED from the traced chunks** | Confirm — `offline.page_info` measures the saved page's text against the trace as the page displayed it (each chunk's saved page form, markdown only where it has none; letters-only words, link destinations dropped); below `INFILL_BELOW` 0.9 it opens `infilled`: `offline.infill` keeps Chromium's MHTML byte-for-byte except the document part, which gains before `</body>` every chunk of which the saved text holds under half, marked as traced. Live (2026-10-11): Okapi's saved page holds 0.875 of its trace (the misses are language names and navbox entries the page loads lazily); offline it opens with its own layout (`#mw-content-text`) AND 10 infilled chunks, 1.0 s, and 100% of the live page's words present (the traced-only form had 98.1%). Planted `PLANT_REPLACE_NOT_INFILL` (the first cut) throws the saved page away for the trace; null arm: a whole saved page gains nothing. `tests/test_offline_pages.py` |
| G-62 | **With no connection, the page is reconstructed fully rendered and scrollable from the scan trace alone** | Confirm — `offline.reconstruct`: every stored chunk of the url in document order, drawn by its saved page form where it has one and its markdown where not, saved pictures inlined as data URIs; served `no-store` (cached a day, the cell opened a stale form). A main-frame load failing for want of a connection (`BrowserView.NO_CONNECTION`) opens it from a local file. Live (2026-10-11), Axolotl never saved, the cell offline: opened as a local file, 228 chunks (7 from page forms, 221 from markdown), 130,101 chars, scrollable; banner "2 of 31 pictures held" and 2 load -- the other 29 were never saved by any scan, so an offline page cannot have them. Opening costs 0.4-3.0 s in the plugin (was 15-36 s: one store query per chunk, now one per page, `snapshots.load_page_forms`); the rest of the wait is Chromium reporting the failed load. Null arm for `G-61`: no saved layout, no infill block **And offline ENDS on any navigation to a live page** (2026-10-11, found by G-125's check): only the button cleared `offlineFor`, so after a check left the cell offline every later hover panel was docked into the offline pane, pinned, and never expired. `browser.ts` `did-start-navigation` now clears it for an http(s) url; the check's leaving arm: clean `offlineFor` '' after landing a live page, planted `plantStickyOffline` still set. Seen live 2026-10-11 |
| G-63 | **Retrieval overlay above the Electron browser, coarse-to-fine**: merged chunks first, then within-shadow-DOM top-k | **Done** — `search_payload`. Coarse suppresses a merge group's members so the lead stands for them, because a reader scrolling a ranking does not want the same passage eight times; `coarse=0` ranks the members, which is what a click expansion inside one page wants |
| G-64 | **Cross-page ranking fits the 256 pure-text window** — the most relevant parts of different shadow DOMs, inside one budget | **Done** — `?budget=`. Results are taken until the next would not fit, counted in `tokens.budget`, so a list handed to a model is a list that can be handed to a model |
| G-65 | **Aggregation runs on the DIFF STREAM, not only at the settle.** A chunk rewritten while the reader browses rejoins or leaves its merge group as it changes | **Done** — §M.12. Queued per page on every capture, debounced 1.5s so it lands when the reader pauses, and run on the embedding worker so it is ordered after the vectors it needs. Verified live: a 128-chunk page the corpus had never seen went from 0 to **23 merge groups in 2 seconds**, with nothing asking |
| G-66 | **The O(delta) budget is stated per phase and measured**: fold, then the verbatim's own sequence — *"dedup-vectorize-dedup-aggregate-vectorize, and projections through the async batched queue of UMAP transforms"*. **Two dedups, not one, and the second is not the merge**: `G-24` on bytes before any vector; then vectorise; then the embedding pass that *establishes* near-duplicate links (*"we first establish duplicate-links and **then** merge"*, 18:54) — which `G-29` says is a separate verdict from merging; then aggregate (`G-26`); then re-vectorise the group (`G-27`'s `group_embedding`); then transform. Timed as six phases, not five | **Done** — every phase of a capture is timed separately and reported: decode, absorb, render, store, place, plus the store's own five statements. §M.11 is what that found |
| G-67 | **UMAP transforms go through an async batched queue** — a diff does not wait for a projection, and a projection does not run per chunk | **Confirm — built 2026-09-23** (`vertiscope/obsidian/projector.py`). The embed worker hands every chunk it just embedded to the projector's queue; a worker drains it in batches of 256 into the fit, off the request path. Live, a page new to the store: 79 chunks stored → 79 embedded → 79 projected within 4 s, no request waiting on it. `tests/test_chunk_projector.py` |
| G-68 | **Interactive fields in the billboarded shadow DOM act on the live Electron page** through the trie | **Confirm** 2026-10-12 live, end to end (sidecar started with `--enact`, the reader's choice): in a 3D panel over DuckDuckGo's results, "giraffe" typed into the panel's copy of the search box and Enter pressed THERE drove the live page in the cell from `?q=okapi` to `?q=giraffe` -- the act adjudicated by `/enact` plan, performed at the stored xpath (type, then the page's own Enter); planted `act-noop`: the page stayed on `?q=okapi` and the panel's readout said so (`scripts/check_panel_enact.py`). Open — §O.5, and it is `G-46` at the surface a reader actually touches |
| G-69 | **Retrieval is continuous scrolling over a ranked list, not top-k.** Top-k is what a click expansion uses; the overlay itself keeps going | **Done** — `?offset=`, and the list asks for more as it nears its own bottom. Measured: 12 results on typing, 48 after three scrolls |
| G-70 | **Clicking a shadow-DOM node SCOPES the query to that url**, however the global ranking placed it. Right-clicking restores global scope | **Done** — the projector click sets the overlay's scope through the plugin, and a right-click on any node releases it. Brokered rather than held by either pane, because neither may require the other to be open |
| G-71 | **Scoped results unfold by the same mechanics as the overlay's** — one behaviour, two places | **Done — seen live 2026-09-19** (`confirm.mjs`). Scoped hits open their page through `showHits`, the page node is KEPT as their hub and marked open, and the containment star is drawn — the same shape `G-6` asserts for a click. The check had to learn what `G-63` learned: asking for "the" returned nothing, because a stopword scores ~0 lexically and under the strict product a zero is a veto |
| G-72 | **Every position the 3D graph draws comes from ONE chunk projector** — the default page view, an unfolding and a live capture alike. A page sits at the transform of its chunks' mean vector into the chunk fit; a merge group's lead speaks with its 512-token aggregate vector | *Addendum V: “Instead, stream O(delta) diff chunk updates in queue based batches to a fitted UMAP projector”*; *“the way our 3D graph layout is now computed”* | **Confirm — built 2026-09-23.** `/layout`, `/place` and `/unfold` answer from `projector.PROJECTOR`; the page-mean fit and `_local_positions` are off every default path (`?source=legacy` keeps them for comparison). Fitted on a sample of 4,000 of 14,516 drawable chunks (41 s), the rest transformed in (34 s). Live, the 79 chunk nodes of a newly browsed page sit at the projector's positions to **0.0 units**, none carrying the old local territory. Measured cost of the honest picture: only **43.4%** of chunks are nearer their own page's hub than any other (1.7% with page labels shuffled); pages interleave where their content does. `tests/test_chunk_projector.py` (planted: a sentinel written into the stream comes back from `/place` verbatim) **Exception, 2026-09-26:** before the FIRST fit exists, positions come from the force-directed fallback (`G-89`); the pane says so (`layout_mode`) and switches once the fit is ready |
| G-73 | **Panes follow the projector's stream, O(delta)** — what moved since the last sequence number, not a new layout; a new fit (epoch) redraws once and re-places what was open | *Addendum V: “streams to the projector”* | **Confirm — built 2026-09-23.** `GET /projector/delta?since=&epoch=`, polled once a second by the graph pane: re-placed chunks move to their new fit position, gone chunks are removed with their links, new chunks on an open page are placed, a page whose chunks changed moves. Live: the pane applied seq 602→778 (158 moves, 2 page updates) with no reload |
| G-74 | **Refit at 2× chunk growth, in the background; the fit survives a restart** | *Addendum V: “incrementally re-fits for every 2x growth in the number of total chunks”* | **Confirm — built 2026-09-23.** The worker checks growth every 5 s and refits on a separate thread while the old fit keeps answering; the swap is one assignment. The fit is kept in `projector.pkl` beside the store and reconciled on start: only chunks whose vector changed, or that the fit never saw, are re-streamed. Tested at 1.99× (no refit) and 2× (refit) |
| G-75 | **Every check runs THROUGH the running plugin (hardware in the loop)** and is driven and read by MCP tools; a terminal script is only a client of it | *Addendum VI: “a full Obsidian MCP layer that runs all tests through the *actual* plugin itself while live in the Obsidian GUI”* | **Confirm — built 2026-09-26.** `checks/live.mjs` holds all 36 checks once; `src/verify.ts` runs them in the plugin's own window (`__vertiscope.verify`), results stream into the corner box; `confirm.mjs` and the MCP `confirm`/`verify_state` tools are clients that reload the plugin from outside and start the in-app run. Seen: in-app runs 4/4, 3/3, 6/6 |
| G-76 | **Scan statistics have no pane of their own**: the pipeline readout is the collapsible, scrollable box in the Electron browser's bottom-right corner, which MCP tools can see, expand and collapse | *Addendum VI: “remove the segregated statistics panels”; “collapsed to a small black box on the bottom right corner”* | **Confirm — built 2026-09-26.** Live: separate panes chunk 0 / profile 0 / no status readout; the harness's `pipebox` gesture opens and closes the box (same state a click sets), corner 10/10 px, profile readout drawn inside it. Check `G-76` in `checks/live.mjs` |
| G-77 | **No separate chunk pane**: a chunk's rendered shadow-DOM form is a billboard in the 3D graph | *Addendum VI: “show as a billboarded 2D panel within the 3D gui rather than a third panel”* | **Confirm — built 2026-09-26.** Billboard mounts `ChunkSurface` forced interactive: an open shadow root (4 elements on a text chunk, 72 with 2 images on a picture chunk); chunk panes 0. Check `G-77` |
| G-78 | **Right-click pins a chunk**: its outline stays on the page at its on-screen box, its markdown goes to the browser cell's markdown side (native render, beside the page), and its billboard opens in the graph; all three persist and close together | *Addendum VI: “right clicks persist the chunk that is then overlay-highlighted and sends the markdown render to the markdown-side panel. When this happens, the shadow DOM billboard is also opened and persists”*; Addendum IV (switchable second view); 2026-09-22 (“clear highlight (non-blinding) over the current chunk's cartesian bounding box”) | **Confirm — built 2026-09-26.** Live on the Radix tree page: pin outline 0.49 px from the element's own box; markdown card rendered; billboard held by the browser with a shadow root; closing the billboard -> 0 pins, 0 billboards, 0 outlines. Planted 20 px offset: check fails, measuring 20 |
| G-79 | **Hover outlines the chunk over the page's own layout**, minimal and without banners, and rings its node in the graph -- aligned to what the browser renders | Addendum I (“an overlay that highlights the chunk structures overtop of the page's native cartesian displays”); Addendum IV (“minimal highlight … without banners”); Addendum VI | **Confirm — rebuilt 2026-09-26 (DESIGN_VII §1, §3).** The overlay resolves hovers from a map the renderer holds (`GET /page_map` on landing, `map_delta` in every capture reply), never the store, and outlines the 256 chunk's WHOLE extent -- the union of every element its lines draw. Live on Radix tree, with the landing capture in flight: hover p50 3.4 ms, p95 7 ms (100 samples; was 28 ms p50, 5,626 ms max via `/resolve`); 6/6 heading+paragraph pairs one chunk and ONE box; outline 0.01 px from the extent oracle (the sidecar's own map); node ringed. Planted (matched element only + a 1 s wait): fails, extent off 675 px, p95 1,411 ms. Check `G-79` |
| G-80 | **Hover-first**: the hovered element is chunked first and its embedding and projection jump the queue, so it reaches the graph fastest; the profile traces it as its own kind | 2026-09-22 (“whichever element that is hovered is recursively chunked first … projected through our 3D graph as fast as possible”) | **Partly — built 2026-09-26.** `/focus` moves the hovered chunk to the front of the encoder and projector queues (seen: 1 call per new hover); unresolved hover drains at once; `hover` traces recorded. Time-to-screen of a hover trace not yet read back as an outcome |
| G-81 | **A chunk node shows one of its pictures and expands to the whole chunk** as a billboard | *Addendum VI: “chunk nodes represented by only one of their image billboards which expands to viewing the total chunk”* | **Confirm — built 2026-09-26.** A chunk node with a picture is drawn as a sprite and opens to the whole chunk's shadow-DOM form (72 elements, 2 images). Check `G-81` -- **2026-09-28: one check, two halves, both planted** (the second check under the same id had no plant and overwrote the first's result). Fresh store: page icons 7 of 7 against 0 of 7 with `plantNoIcons` (which now strips the layout's own page image too -- it had been removing nothing); chunk pictures drawn AS pictures 20 of 20 against 0 of 20 with `plantNoPicture`; the chunk's card opened with 27 elements, 1 image. Drawn through the scene batch's atlas since G-107 |
| G-82 | **The side panel is the only second view**: no markdown face, no face toggle; a pinned chunk's markdown is a side panel beside the page, pins stack, and closing any one of the three forms closes all three | *Addendum VII follow-up: “side-by-side markdown sub-panel”, the browser stays the main surface* | **Confirm** 2026-10-17 live (`checks/live.mjs` G-82, in-app verifier, 27 s): 2 pins, 2 cards newest first, 2 billboards, kept away and back, closing the newest closes its three forms. The fail before it (2 pins, 1 billboard) was a pin holding a cid the store no longer had (`561404dd`: "no such chunk"); a pin is now re-anchored by its url : xpath when its chunk is retired or unknown to `/place` (`scripts/check_pin_reanchor.py`: billboard on the live chunk in 4 s; planted `no-pin-reresolve` never, `plantWaitUnknown` 58 s). `DESIGN_VII.md` §5 |
| G-83 | **UMAP places PAGES only**, from each page's centroid (triple — pagerank-weighted semantic + frequency — or quantized semantic alone, chosen by the measured `centroid_ms`) | *Addendum VII: “UMAP only on page centroids”* | **Partly.** `PageProjector` built and tested (`test_page_tree.py`), gated off by `VERTISCOPE_PROJECTOR=page`; not the default **Order, 2026-09-26:** *“first on global chunk averaging on per-page and then fitting, but a transform over the full chunk set is cheap as well”* -- fit on page centroids FIRST, then place every chunk by transform through that fit |
| G-84 | **Left-click opens a page's WHOLE patricia tree, right-click closes it**: the content-node subtree of its shadow DOM, single-child chains collapsed to one link, one parent per node | *Addendum VII: “expands its FULL patricia TREE”* | **Partly.** `/page_tree` and `page_tree()` built (`test_page_tree.py`); the pane still unfolds per step |
| G-85 | **Much longer links** inside an opened tree, their length derived from the page layer's spacing | *Addendum VII: “The max link lengths need to be much longer.”* | **Open.** `DESIGN_VII.md` §6 |
| G-86 | **A heading heads what follows it**: the 256 cut is lenient -- a run takes the next piece past 256 while the result stays nearer 256 than 512 (< 384), so no chunk is a heading alone | *Decisions 2026-09-26: “If this is closer to 512 than 256 … keep the previous, otherwise include the merge”* | **Partly** 2026-10-12. `python -m vertiscope.analytics.headings` over the frozen corpus, rendered fresh: heading-alone chunks **43 -> 25** of 14,794, multi-line chunks past 1.5x the window **33 -> 0**; planted `before` arm (`PLANT_HEADING_APART_FROM_RECORD` + `PLANT_NO_RECUT`) reproduces 43 / 33 exactly, `strict` (LENIENCY 1.0, trailing headings) 56 / 23. Two causes fixed in `markdown.py`: a heading before a record set was flushed alone (27 of the 43 -- NASA's "Highlights" over its cards, Python's `<h3>` over `<dl>` entries, RFC sections) and now goes with the first record within the bound; and the page-wide post-passes grew chunks after the descent sized them (`_tabulate` naming every row's columns, D-9: 26 of the 33 one Wikipedia comparison table), now re-cut by lines under the same lenient rule (`_recut`). A third cause fixed: a content boundary right after a lone heading flushed it alone (Python's `### Functions` over a 218-token `<dl>`, RFC 9110's sections) -- a buffer of headings only is carried whole (`PLANT_LONE_HEADING_FLUSH`). Re-measured: **22** heading-alone (before arm 43). The 22 head nothing (Wikidata "(0 entries)", an empty "Languages", archive.org's "Javascript is required" page, Slashdot ad slots) or sit over one indivisible line past 512 (httpbin 827, PostgreSQL 643), which the user's rule keeps apart. |
| G-87 | **Every test run reads a fresh, empty store that the APP starts and fills** by browsing a fixed page list; the working store is never touched, and every verdict records which store it read | *2026-09-26: “tear down the current db so that all new tests run in a fresh and empty db”*; *“All tests run inside of the GUI”* | **Partly — built 2026-09-26, in the plugin.** The corner box's "fresh store" button (`Verifier.runFresh`): a child `supervise` sidecar on an empty workspace (port 8790), the plugin pointed at it in memory only, 12 pages browsed in the cell, the checks, then back on the working sidecar with the test tree stopped -- every step in the box. A first, terminal-driven version (a `freshrun` module, since removed) seeded 12/12 pages, 0 -> 927 chunks, in ~60 s and was removed for running outside the app. The record merges per requirement and names the store (`confirmations.py`, `test_confirmations.py`) **2026-09-27: the full suite, 41 of 41, on a fresh store the app filled itself (13 pages)**; runs are isolated per check (pins, menus, billboards, live capture, idle guest) |
| G-88 | **The app is audited by using it**: each finding traced verbatim -> user story -> row -> check -> what the app did, peripheral effects included | *Addendum VIII* | **Open.** `docs/AUDIT_VIII.md` |
| G-89 | **The pending DIFF is drawn force-directed; what the transform has placed collapses into the page-node view.** Every chunk a drain produces is drawn at once as a force-directed node hung from its page -- built in the renderer from the drain itself (the sensor's MutationObserver chunking: no sidecar, no embedding, no UMAP) -- and stays so until that drain's chunks have been through the projector's transform; then its force nodes collapse into the page node (the default view draws pages, `G-53`; a page's inside opens on demand, `G-84`). Before any fit that is every scan; after one it is only the diff still waiting in the vectorization and transform queues. The fit is over page centroids and refits asynchronously (`G-83`); transforms run on the diffs, O(delta). **Phase contracts** (checked in order, in the running plugin, off `ui().graph` and the fresh-store run's phase trace): **C1 empty** -- a fresh store before any scan: 0 nodes, `layout_mode: "empty"`. **C2 first scan** -- the page's first drain draws at once: `layout_mode: "force"`, a page root plus one node per sensor chunk, each chunk with exactly ONE parent (nearest enclosing chunk by address, else the page); no vector waited for. **C3 delta** -- each drain adds exactly the chunks it emitted and removes exactly the ones it named removed; every other node keeps its identity and position; per-drain renderer time p95 < 50 ms. **C4 pages** -- each new page is its own tree. **C5 no fit yet** -- while the projector has no fit, the force trees stay up and the caption says it is waiting for the fit. **C6 the fit lands** -- the pane draws the page-node view from the projector; force nodes whose chunks are still unplaced stay drawn, hung from their page's projected node. **C7 collapse** -- when a drain's chunks have all been placed by the transform, its force nodes go (collapsed into the page node): pending force nodes fall to 0 once the queues are empty. **C8 after the fit** -- a new drain on a page the fit already holds adds force nodes under that page's projected node, and they collapse once transformed; a refit does not drop pending force nodes. **Interactions:** hover outlines and rings (`G-79`); a pin opens its billboard and survives the redraws (`G-78`); every node is on screen (`G-5`). **Planted:** the drain not wired to the graph must fail C2 | *2026-09-26: “the first handful of scans are rendered with a full force-directed layout as a fallback”*; *“force-directed layouts as a first and primary representation”*; *“the layout priorities are only on the diff that is queued to the vectorization and projection itself”* | **Partly — built 2026-09-26.** C1-C5 seen live on a fresh store (11 pages as trees before the fit, per-drain p95 24.7 ms, one parent per node); C6-C8 being rebuilt for the diff reading. Check `G-89`. 2026-10-19 fresh store (run 26): C1-C7 all hold (13 pages force-drawn before the fit, drain p95 12.8 ms, collapsed to 0, projector drawn); C8 appeared 1,055 ms, collapsed 214 ms, a mutation's node hung from its page -- but that second node did NOT fold within 60 s. On the working store the same steps fold it in 874 ms, so the open question is what a fresh store lacks for a mutated chunk (its placement?). |
| G-91 | **Streaming, landing and leaving.** Landing on a stored page draws its projected chunks at once (served from the projector's memory with the page's chunk map, one call), with NO pending diff and NO diff flash -- content the store held before the visit is already transformed; only content the store does not hold, or whose text changed, is drawn force-directed and flashed. Leaving a page (for any page, blank included) drops its pending diff at once and, once its settle is done, collapses its projected chunks into its page node -- unless the reader opened it in the graph or a pin holds a chunk. Late placement results for a page no longer browsed add no chunk nodes; force nodes take no collision room, so projected chunks stay near their transform positions | *2026-09-26: "collect the full list … the different diffs and 3D nodes and 2D browser highlights … UMAP transforms and when collapses to page centroid nodes happens"* | **Partly -- built 2026-09-27.** Timelines (AUDIT_VIII pass 2): a stored page's projected chunks at 0.3-0.5 s after landing (was 3.6-5.2 s behind 145-564 duplicate force nodes and a 20-34 box flash); left pages collapse (other pages' chunk nodes had grown to 280). Check `G-91` |
| G-92 | **The stream runs in this order, and a node collapses when it is SAVED.** Mutation -> chunk diff -> overlay (in the page) -> force-directed nodes in 3D (before the store) -> store -> the store confirms a chunk saved and THAT node collapses into its page's root, before any vector or projection -> vectorize -> project through the current fit. Supersedes the collapse trigger of `G-89`/`G-91` (collapse once the transform placed it) | *Addendum IX: “as soon as the db pings back that the one node in the diff from any set of the streams has been saved, that one node collapses (still force-directed only until umap projections return) to its root”* | **Built 2026-09-28, check `G-92` on the Julia forum's /latest (planted: `late` -- the old order, collapse only once projected).** TRACED: a saved node waited for its PROJECTED node to be drawn (`collapseCovered`), so it stayed a streaming node through embedding and placement, and on a collapsed page for good. Now the capture's reply folds it into its page's root at once (a 250 ms tween into the projected page, or into the page's force root while unprojected); a late placement on a page the reader has left is folded, not drawn; a placement replaces any force node still drawn for that chunk. The graph keeps a per-node lifecycle (drawn, saved, folded, placed) in the MCP's `lifecycle` |
| G-93 | **The streaming force layout is relaxed and translucent**: no upper bound on link length, gentle attraction rather than strong repulsion, and streaming nodes drawn translucent -- a temporary signal that scanning is happening now | *Addendum IX: “without an upper bound on link lengths and perhaps more lenient/relaxed attractive forces (rather than strong repulsion)”; “force-directed layouts initialize to simple translucent nodes”* | **Partly** 2026-10-17 (`checks/live.mjs` G-93, FAIL). Translucent: 190/190. Spread FAILS: nn p10 0.2 radii against a bar of 3, 122/190 touching. Calm FAILS, and it is not shaking: instrumented per update, the whole p90 is ONE update per stream in which ~30-37 nodes move 124-254 radii together -- (1) each batch's glide from its grey spawn to its `/project` fit (PLUGIN_GOAL 48, designed), long because a new page's root is born near the origin while its chunks project ~320 units away; (2) the root's own projection arriving ~2 s later (cold `/project` 1.9-2.3 s) and the telescope re-laying the page around it. The measure now splits each node's one glide to its fit (`glide`) from the rest (`jitterHeld`, which the bar reads). Built: the root takes `/project`'s page position (G-94's "replaces"), planted `plantRootUnplaced` -- glide 124 -> 14.6 radii in one run, not in others: timing-dependent, NOT confirmed. Tried and REVERTED: birth beside the trie neighbour (longest stored url prefix) -- the stored `/latest` sits 254 radii from where this visit's topics project (a feed page's meaning moves). Open question for the reader: a root cannot know its place before `/project` answers, so either the first drain waits ~0.6-2 s for it, or the one placement move is accepted as the grey -> fit transition |
| G-94 | **A root that is not yet projected is itself force-directed**; when a projection arrives it REPLACES the force position, and the only force left is collision spacing: node diameter x an INTEGER safety factor plus an invisible margin | *Addendum IX: “collision boundaries defined as the diameter multiplied by some safety factor … I would argue is integer-valued”* | **Partly** 2026-10-17. Built: the force root takes `/project`'s page position when it arrives (`applyProjected`, planted `plantRootUnplaced`); collider = drawn radius x `COLLIDER_SAFETY` 2 + `COLLIDER_MARGIN` 1. The live check FAILS on burial as seen: 67 of 732 drawn buried (bar 5%), clean = planted no-collide (253/251 overlapping) because the burial is not the collider's: of 179 buried screen pairs, **0** are within 2 radii in 3D (median 12.5 radii apart), 92 share a host -- dense site clusters seen THROUGH each other; 822 random discs would bury ~6.5 pairs. The levers are depth compression (`DEPTH` 0.4) and node size -- the first the reader just kept ("Keep current layout"), the second against G-188's "larger". For the reader |
| G-95 | **Clicking a root toggles its whole tree**: collapsed -> every chunk of that page expands as the complete patricia tree; expanded -> click again and they all collapse back. Amends `G-84` (right-click closed it; right-click now belongs to the browser menu and pins) | *Addendum IX: “When the roots are clicked, all nodes expand … When the roots that are uncollapsed are clicked again, all the chunks for that page collapse back.”* | **Confirm** 2026-10-12 live (`checks/live.mjs` G-95, `f4fe7d9`): the stdlib html parser module page, 35 stored chunks -- first click 35 drawn, second 0; planted `plantUnfoldOnClick` 37 then 37 (never collapses) |
| G-96 | **UMAP coordinates are persisted per chunk, force positions never; a re-fit over the whole page history re-projects every stored 512-chunk.** Colour comes from the fit | *Addendum IX: “UMAP coordinates for projected chunks are saved to DB, but not their force-directed updates. All coordinates in the DB for all 512-chunks are re-projected over the UMAP upon a new re-fit”* | **Partly.** The fit persists in `projector.pkl` (`G-74`) and positions are re-derived on an epoch; whether coordinates live in the store, and whether every stored chunk is re-projected, is unmeasured |
| G-97 | **Each new chunk is projected at once, as its sub-chunk centroid through the current fit**; the first fit runs when enough pages are scanned. Simpler than `G-83`'s page-centroid fit | *Addendum IX: “vectorize the chunk diffs … and immediately compute the subchunk centroid and project it over the currently fitted UMAP (or fit for the first time once reached an appropriate number of scanned pages”* | **Built 2026-09-28, check `G-97` (planted: `scatter`).** TRACED: the sidecar places each chunk by the fit (page position + its transformed offset from the page centroid), but the pane overrode it for every OPEN page with its own geometry (a disc, then a radial tree, then a force-seeded tree). Removed: a projected chunk is drawn at its fit, `home` holds it there, collision only spaces it; an online update or refit moves it through the stream |
| G-98 | **Deduplication holds on the store side, vectors included**: a chunk already stored is neither written nor embedded twice, with tests, then new edge-case tests once those pass | *Addendum IX: “ensuring deduplication on DB-side as well, including vectorization steps, perhaps some tests for this, and new tests once the old ones pass”* | **Check `G-98` built 2026-09-28 (planted: a streaming node left beside its stored node).** MEASURED in the working store: no two chunks share an element address on the forum, Radix_tree or Trie (1 of 14,146 addresses on the forum claimed twice); the graph drew no id twice and no streaming node beside its stored node; the store's CONTENT duplicates per page are measured by the check and reported |
| G-99 | **Every kind of content on a page is detected**: text, JSON (script data, inline state), images, video, audio, other media -- found by planned searches over what the chunker has dropped, not by sampling | *Addendum IX: “all content that could possibly be detected, whether it be text; json; images; videos; media”* | **Open** |
| G-100 | **Media is cached in the workspace with its source**: every image reaches the 3D view, and no image is fetched twice | *Addendum IX: “confirm that all images are actually presented in the 3D GUI, and that re-fetches aren't required by locally saving the media in a workspace cache”* | **Confirm** 2026-10-12 live (two plugin loads in url view): the 3D view's pictures come from the workspace's media store first (`GET /media/<sha1(url)>`, `snapshots.load_media`) and are saved there the first time they are fetched (`POST /media`) -- clean load **126 from the store, 0 from the web**; planted (`__vertiscopePlantNoMediaCache`, the old path) 0 / **125 from the web**. Before: every load fetched every picture again (only an in-memory cache). The 6-10 "failed" are URLs that answer with HTML (a missing favicon): no picture either way, now remembered as none and never decoded. |
| G-101 | **The hard-page corpus**: archive.org, YouTube, Instagram, Amazon, Facebook, Netflix, IMDb, DuckDuckGo, Richard Mille (rotating JSON-fed panels), Bandcamp (a live feed of releases) -- each browsed in the cell and scored live | *Addendum IX: “Please test on more difficult and larger-scale pages like …”* | **Confirm** 2026-10-19 live on a FRESH store (in-app `verify.startFresh`, run_20261019044551, 13/13 seed pages): all **10 of 10** hard pages browsed in the app captured and stored, embedded and projected -- archive.org 20 chunks, YouTube 36, Instagram 1 (login wall), Amazon 27, Facebook 4 (login wall), Netflix 20, IMDb 34, DuckDuckGo 23, Richard Mille 5, Bandcamp 71; overlay p95 5-33 ms, first 3D node 2-914 ms, 0 capture errors, pictures stored where the page shows them; planted arm (a page whose drains are dropped) -> nothing stored, caught. |
| G-102 | **A billboard looks like the chunk it opens, and does not fake live controls**: HTML rendering improved; a control that cannot act on its xpath says so rather than looking pressable (`G-68` is the live version) | *Addendum IX: “aren't necessarily 'interactive on their xpaths' and so the buttons are just stale … some amount of html-based rendering improvements”* | **Partly** 2026-10-19 -- the control half confirmed live (`confirm.mjs` G-102, fixture `controls_inert.html`, opened from the graph in page form): the labelled button and the email field the trie addresses stay live and unmarked; the icon-only button it holds no address for is drawn inert -- opacity 0.55, cursor not-allowed, aria-disabled, titled "not reachable from here: the page's map holds no address for this control"; planted `plantInertLooksLive` -> drawn as pressable as the live one. With no cell to act through every control says "not live here" (`snapshot.ts`). Seen: `build_analytics/g102_inert_control.png` (the dot grey in the panel, black on the page). The "HTML rendering improved" half is D-36's (in order 1.0, page colours) and is not re-scored here. |
| G-103 | **One loop, judged by the eye**: every 30 minutes, every requirement in scope ("Done" included); sparing screenshots at the steps that matter, read as a person would read them, compared with the MCP's numbers; what the picture shows and the numbers miss fixes the MEASUREMENT first, then the app | *Addendum IX: “The human's visual evaluation should be what informs our app's design for both features and MCP-based interaction testing.”* | **Partly — the loop runs from 2026-09-27.** Alignment rule (same day, *“all tests are run directly through the app in ways that are observable to the tools and yourself”*): only an in-app check started by the app's own control and read from what it renders counts; a probe finding becomes a live check plus an MCP field first |
| G-104 | **Each installed Python package is a tree-shaped projection** of its chunked comments and docs, with dependencies from variable to module to directory, localized to chunks; our own codebase included | *Addendum IX: “render each python package as a tree-structured UMAP projection on the chunked comments/code docs, and show the full dependencies on variables to modules to directories”* | **Confirm** 2026-10-12 live: this codebase (124 modules, 3,027 chunks) and json, urllib, http, html (19 modules) indexed through POST `/package`; `relink` took import edges 164 -> 320; queued into the projector like a capture's pages, the page layout carries **141 module pages, 132 directory-tree edges, 264 import edges**, and the 3D view shows them as one connected tree hanging from the package modules (screenshot `build_analytics/app_20261012_064305.png`). Built: `vertiscope/packages.py` (`index_tree` / `index_package`: every module through `index_source` as `code://<root>/...` pages, then `relink` so an importer indexed first gets its edge; `code_tree_edges`: each module under its folder's package), the page layout's `dir` edges beside the import links (planted `PLANT_NO_CODE_TREE`), POST `/package` gated with `--capture`. `tests/test_packages.py` (4). |
| G-105 | **Package chunks go into Jupyter cells as code prototypes**, in the notebook with its kernels, terminals and browser cells as the older design documents specify (`NOTEBOOK_PANEL_DESIGN.md`, `P-N`, `P-B`) | *Addendum IX: “bringing these chunks into code prototypes in jupyter python cells on a notebook”* | **Open.** Design recollection first |
| G-106 | **The online update's scope follows the GPU's measured cost.** While pages are few, the fit and each `update()` run over EVERY chunk's vector (a chunk drawn at its own UMAP position, its page at the centroid of its chunks); once there are tens to hundreds of pages, over the page centroids (today's page projector). The switch is decided by the measured fit/update milliseconds on this GPU against a budget, and both the scope and the timing are reported | *2026-09-28: “changing to UMAP coordinates after a re-fit and `update()` style transform incrementally over the new nodes. Depending on GPU runtimes, perhaps update with the full set of chunks, or just the centroided pages, or the former for few pages and the latter for tens to hundreds.”* | **Built 2026-09-29, not yet seen in the app** (the running sidecar predates it). `vertiscope/obsidian/refitscope.py` decides per fit: chunk scope when an update over pages + chunks is predicted within `SCOPE_BUDGET_MS` (5 s), page scope otherwise, never past 8,192 rows. The prediction starts from this GPU's measured curve -- `update()` of 10 rows over 160 / 500 / 1,000 / 2,000 trained rows: 1.5 / 2.7 / 6.6 / 15.9 s (RTX 4070 laptop, 768-d) -- and is replaced by the updates the projector actually runs. In chunk scope the fit and every online update TRAIN on chunk vectors (`pumap._raw` holds them), not only transform them; drawing is unchanged. Status and every fit record: `scope`, `scope_why`, rows, predicted and budget ms, the cost model. `tests/test_refit_scope.py` (8 pass): planted budgets flip the decision both ways; a real GPU fit trained on 14 pages + 126 chunks, and on 14 pages only with a 1 ms budget. Working store (159 pages, 16,189 chunks) is page scope; a fresh store of a dozen pages is chunk scope |
| G-107 | **Every stored chunk of an open page is drawn, within a frame budget.** The 3D view draws every node and edge the graph holds in a bounded number of draw calls (≤ 10, whatever the node count), each node at the size its collider reserves, pictures from one atlas rather than a texture per node, and the pointer still picks each node | *2026-09-28 ruling: “Everything stored” (the option noted “I'd attack the cost with instancing and texture atlases instead”); Addendum IX (2026-09-28): “centralizing everything to this main pipeline ... (that includes rendering as deeper inlaid parts of the processing now, each with different time constraints)”* | **Built 2026-09-28** (`obsidian-plugin/src/scenebatch.ts`; design `.design/L4-arch/pg-062.render.md`). Check `G-107` (planted: the per-node objects and per-link cylinders; pick proxies the raycaster cannot hit). MEASURED live at 1,839 nodes: 2 draw calls a frame and 1.2 ms render CPU p50, against 3,524 calls and 31.1 ms with the per-node objects planted back; textures 1 against 1,805; picking 7 of 8 in both |
| G-108 | **The 3D view's motion is observable, and holds still where the stream is not.** The harness records every drawn node's world and screen motion per frame, the velocity each force added, and the pipeline's events, and reports teleports, vibration, drift, flicker, pulsing sizes, page churn, stalls and why nodes are not visible; an off-screen camera films an open page at its own scale; both are MCP tools. While a page streams: no node elsewhere moves; on the page, fit moves glide and no node jumps across a frame or vibrates | *2026-09-29: “The force-directed methods are still throwing glitches. You'll need to improve the fidelity of your MCP tooling harness to capture the details of what anomalous and specific behavior I'm describing. Get inventive.”* | **Built 2026-09-29.** Instruments: `obsidian-plugin/src/motion.ts` (`__vertiscope.motion`), `GraphView.inspect` (`__vertiscope.inspect`), `vertiscope/obsidian/motionfilm.py`, MCP tools `graph_motion` and `graph_inspect`. Found on the live forum: 210 teleports and 257 vibrating nodes in 20 s, the worst on untouched pages (collide vs contain/home, re-energised by ~1 reheat per second); an open page's 1,109 chunks drawn as a 9-px sub-pixel dot at default zoom; streaming nodes hung as a star from the page hub; fit moves assigned outright (190-256 units in a frame). Fixes: calm pin (`plantNoCalm`), glide (`plantTeleport`), governor (`plantNoGovernor`). Live A/B: elsewhere teleports 0 and 0 calm against 138 and 15 planted; governed 0 and 21 teleports against 465 and 207 planted. Caveat measured: the camera instruments cut the frame rate 197 -> 57 fps, so the Verifier check G-108 runs the recorder alone on the deterministic busy feed with all three plants. **Check `G-108` PASS (fresh store, 2026-09-29 00:42):** clean 0 teleports, 0 vibrating, 0 drift, 0 stalls over 18 drains at 238 fps; planted no-calm 9 teleports (141 units in a 3 ms frame, collide), no-governor 38 (336 units), assigned fit moves 10 (the page node 3,437 units). Not shown by it: "nothing moves elsewhere" -- a fresh store's 13 pages do not crowd; that half rests on the live forum A/B. Still visible and open: streaming nodes hang as a STAR from the page hub (an undrawn parent falls back to the page node) |
| G-109 | **One central diff, computed on the backend from the patricia trie's render, is what every view applies.** Each capture and each settle yields one record keyed on the cid (`added`, `dirty`, `retired`, `renamed`, `known`); the store retires what it names, the projector reports it gone, and the 3D view, the chunk map and the pins remove, re-key or carry nodes from it. A revisit of a stored page draws the stored chunks, never new ones: content the store holds under a shifted address is that chunk RENAMED | *2026-10-04: “centralize deduplication etc on diffs throughout the pipeline in a centralized place on the backend ... a singular diff update on the scan side compatible with the same set of 3D and 2D representations”; “Re-navigating back to a previous page re-spawns existing nodes. This is where the patricia trie on the DB is the central spine for chunk handling, scanning, and web nave.”* | **Built 2026-10-04, partly seen live.** Backend `_page_diff`/`_record_diff`/`GET /diffs` in `vertiscope/obsidian/sidecar.py`; consumers `GraphView.applyDiff`, `ChunkMap.applyDiff`, `BrowserView.noteDiff`; `GraphView.staleStored()`. Tests: `tests/test_central_diff.py` 13 (planted: a session ignoring the store re-spawns every known chunk; without the stored content a revisit duplicates), `obsidian-plugin/tests/chunkmap_diff.test.mjs` 6. **Live, test workspace :8791 (2026-10-04):** before the cross-visit rename a revisit of a gamerevolution guide took the store from 26 to 50 rows (24 byte-identical copies under shifted xpaths) with up to 8 streaming nodes; after it, two revisits of the ddg results page read 19/19 chunks `known`, peak 1 streaming node, store 19 -> 20, and the guide 25/25 then 26/26 `known`, 0 added; leaving the guide settled it and retired the 24 copies (store 26 = render 26). `staleStored` = 0 throughout. Check `G-109` (busy feed `?prepend=1&shift=1`) written, not yet run in the Verifier. **Check `G-109` PASS 2026-10-07** (Verifier, busy feed with shifts): clean -- 0 stale nodes sampled every second through the run and at the end, 10 diffs applied, 7 retired nodes removed, 6 renamed carried; planted -- a drawn node the store does not hold is caught (stale 1, named). Found on the way: the view retires a chunk by THREE roads (the central diff, the projector's gone log, folding on leave), so switching one off (`plantNoDiff`) never left anything stale -- the earlier planted arm was vacuous for that reason, not because the instrument was blind |
| G-110 | **Right-click on a page node toggles its chunks**: drawn chunks fold into the page node and stay folded while the reader browses that page; with none drawn, every chunk the store holds for the url is placed at its UMAP position | *2026-10-04: “Still also seeing no right-click on central url nodes collapsing the chunks into the node and expanding the full UMAPped chunk set.”* | **Built 2026-10-04, seen working through the graph's own callback.** `GraphView.togglePage`, `foldChunks`, `collapsedByReader` (`obsidian-plugin/src/graph.ts`). Live, :8791: duckduckgo 31 -> 0 chunk nodes on collapse and 0 -> 31 on expand; the fandom article 0 -> 1 (its store holds one chunk: a Cloudflare challenge was what got captured). Check `G-110` (planted `plantNoToggle`) written, not yet run in the Verifier |
| G-111 | **A chunk panel is the live page's controls, interactive and linked to the trie**: every element a chunk's lines name carries its trie address; a click, a fill or a toggle in a panel (side card or 3D billboard) is adjudicated against the store and performed on the page in the browser cell at the stored xpath -- navigating there and scrolling to it first -- and the page's own mutation flows back through the normal pipeline. Controls with no address stay inert; refusals and the enact flag still apply | *2026-10-04: the shadow-DOM chunk panels must be direct HTML, interactive, linked to the trie, and act on the live page (navigate, scroll, perform)* (verbatim in `docs/PLUGIN_GOAL.md`, 2026-10-04) | **Built 2026-10-04, module-tested, not seen in the app.** `obsidian-plugin/src/snapshotscript.ts` (address tags on the CLONE's serialized HTML, never the page), `panelact.ts`, `BrowserView.actOn`/`arrive` (`browser.ts`), `/enact mode=plan` (`vertiscope/obsidian/enact.py::plan`, behind `--enact`), `sensor.js` `perform` accepts `{xpath}`. Tests: `tests/panelact.test.mjs`, `tests/snapshot_tag.test.mjs` (planted: an unaddressed control stays disabled, a password field never goes live), `tests/test_obsidian_enact.py` +5. Check `G-111` (fixture `tests/fixtures/panel_act.html`, planted `act-noop`) written, not yet run: needs a sidecar started with `--enact`. Known limit: synthetic events, so pages that test `isTrusted` do not respond. **Check `G-111` PASS 2026-10-07** in the Verifier (`--enact` sidecar): click, fill (the page echoes the typed word; the card shows it), refusal ("Sign in" refused, page unchanged), planted no-op, navigation first. Three fixes on the way: a `<label>` the trie holds passes its address to its control (`label.control`) in the snapshot (`tests/snapshot_label.test.mjs`, planted: a label with no control makes nothing live); the sensor routes type/check/choose on a label to its control; only the latest gesture on a panel writes its readout (a fill's late result overwrote a refusal) |
| G-112 | **What the 3D view draws of a page is a tree, over every edge it draws**: one root per url, one parent per node whichever path drew the edge (containment, the streaming tree, the page star), no cycle, no edge into another url's subtree | *2026-10-04: the patricia trie shown clearly and guaranteed tree-structured* (verbatim in `docs/PLUGIN_GOAL.md`, 2026-10-04) | **Instrument built 2026-10-06, module-tested.** `obsidian-plugin/src/treeguard.ts` `treeVerdict`, exposed as `__vertiscope.tree()`; `tests/tree_guard.test.mjs` 7 (planted: a containment plus a streaming parent, a cycle, a cross-url edge, an orphaned second root). `treeOnly` prunes containment edges only; whether the live view breaks the tree is not yet measured |
| G-113 | **Hovering a chunk on the page flies the 3D camera to that chunk and keeps it in view while the forces move it; its panel opens at once with content and closes when the hover ends** | *2026-10-06: "hovering overlays should zoom-focus the camera in the 3D editor on the specific chunk, no matter placement in the diff, with focus persisting on force-directed updates"; "when this flying happens, this also opens the panels on the 3D side, but closes them when the hovering stops"; "Please ensure you're capturing this in our tests"* | **Built 2026-10-06, seen flying live** (the reader: "flying to nodes works perfectly now"). `focusOn`/`flyTo`/`followFocus`, `hoverPanel`, `BrowserView.storedCidFor` (the hovered sensor chunk to its stored chunk, placed if undrawn). Only a chunk moves the camera (page fallbacks made it alternate). Check `G-113` (real pointer input; planted `plantNoFocus`) |
| G-114 | **A chunk panel has two forms -- the page's own rendering and Obsidian's markdown -- and its header is the chunk's full trie address**; each form its own size, switched about the panel's centre | *2026-10-06: "try instead just using obsidian's default markdown renderer in this panel view rather than having this switching between markdown and 'shadow DOM' ... the header of the panel should show the full patricia trie address ... resizing centered by the button clicked at the top right corner"* | **Built 2026-10-06, seen live**: header `https://www.allrecipes.com/recipes/ : /html/body/main/section/div[2]/section`; page form with its image loaded; markdown via `MarkdownRenderer`, one image per element, relative urls absolutised, video/audio as players. **Resize about the centre seen live 2026-10-07**: page 340x213 -> markdown 500x269 with the centre moved 0 px. On the way: the billboard loop had died (one positioning error ended the frame chain while `billboardFrame` stayed set), so panels neither followed their nodes nor re-centred; each panel is now positioned in its own try, and a loop with no beat for 500 ms is restarted |
| G-115 | **Each open page's chunks are telescoped radially about its node**: UMAP directions and distance ratios kept, an inner minimum distance, a maximum bound | *2026-10-06: "the umap clusters are still quite small, and still quite closely packed for each URL ... a max bound distance that telescopes the chunk distances from their centroid url node radially within some bounds, which still preserves the UMAP geometries"; "we need UMAPs to be scaled, perhaps by a minimum distance to the center as a threshold ... Removing voronoi might be the move"* | **Built 2026-10-06, under measurement.** `GraphView.telescope` (planted `plantNoTelescope`), bound max(0.45 x nearest page, 0.35 x scene radius). Node growth into the room was tried and REVERTED the same evening ("Nodes are way too closely packed together now"). Voronoi dropped by the reader |
| G-116 | **The stream grows as a tree over the page's open patricia trie**, not a sphere around the page node | *2026-10-06: "The lagging chunks initialized into a perfect sphere and note really the 'diff' over the patricia trie at all ... The diff should be sort of like a trickling effect over the emerging diff on the active and open tree structure"* | **Built 2026-10-07, not yet seen live.** Cause: a chunk's parent was the nearest chunk ENCLOSING it; sibling regions rarely enclose each other, so everything hung on the page (the hour's recorder: 9/9 stream samples a full star). `ForceTree.skeleton`: the branching prefixes of the held addresses are drawn as small path nodes, each chunk and branch hangs from its nearest proper-prefix node, recomputed when an address comes or goes (branches added, dropped, reparented); empty branches pruned bottom-up when their chunks fold. `tests/forcetree_skeleton.test.mjs` 3 (tree verdict ok; planted `plantFlat` = the star; a new divergence reparents) |
| G-117 | **Every image, video, sound and background a page shows is detected**, checked by a screenshot that accounts for each against the chunks | *2026-10-06: "most images and media are not registering in nodes on johnwick.movie ... screenshot the page and then puzzle-piece the images from the chunks ... until we clearly have fully detected all the possible elements"; "Please make sure audio detection is working for this page as well"* | **Instrument built 2026-10-06**: `python -m vertiscope.analytics.media_coverage` (store addresses resolved in the page; every media element incl. shadow roots; screenshot outlined green/red). johnwick: images 154/156 (visible 17/17), video 2/2, inline svg 4/37, CSS backgrounds 0/3; its sound is the trailer video's (muted) track. **archive.org (2026-10-07, after the instrument resolved shadow-root addresses with the sensor's own `node()` -- `resolve()` is a yes/no and had read 0/115)**: images 64/95 with every VISIBLE one covered (10/10); svg 20/98 direct + 69 icons inside held links/buttons (`in_control`), 9 missing; the 31 missing images are all zero-size thumbnails in collapsed menus. **Node pictures (2026-10-07)**: the picture peripheral walks open shadow roots and counts CSS background images -- `querySelectorAll('img')` stopped at a shadow host, so archive's card thumbnails could never be a node's picture. Now 61/90 archive chunks and 31/50 johnwick chunks carry one (e.g. `services/img/kodi_archive`, the CSS-only `home/trailer.jpg`); c2 holds (a peripheral read). Open: CSS backgrounds as DETECTIONS in the trie (the fold reads no style), unlabelled svg graphics, script-played audio (resource timing), and whether hidden-menu media belongs in each page's chunks |
| G-118 | **The MCP server sees what the reader sees** -- phantoms, stale links, tree, stream shape, panels (empty/broken/duplicate, timings), overlay bounds, latency -- from the app's own objects | *2026-10-06: "Please make sure the design of the mcp server is also just as observant for these kinds of things"; "This could also be capture in the MCPs for observability"* | **Built 2026-10-06**: `__vertiscope.anomalies()` / MCP `app_anomalies` with `problems` in words; `vertiscope-git` MCP (git history, vector cache only). **Called through the MCP server 2026-10-07** (`VertiscopeMCP.handle tools/call app_anomalies`): census, tree, overlay, latency (drain->overlay p50 4.5 ms, 25/25 pushed), panel speed and `problems` returned from the live app; `--cdp` now follows `VERTISCOPE_CDP` (Obsidian on 9223 while a Chrome held 9222) |
| G-119 | **johnwick.movie and archive.org are the test pages for every current feature**, the page-original panel form on dynamic renders included | *2026-10-06: "please use this and archive.org as pages to test all of our current features on"* | **Open** -- each row above re-checked on both pages |
| G-120 | **A popup a page opens on hover is captured and LINKED to what opened it** (archive.org's tile hover pane: views, collections, description) | *2026-10-07: "Also not sure if the popup chunks are captured as well and linked correctly"* | **Partly, 2026-10-07.** Captured: the sensor drains `TILE-HOVER-PANE` as its own chunk the moment it opens (chunk 94/95, outlined at the pane's own box). Not kept: when it closes it leaves the page, and today's retirement (`RETIRE = "delete"`) drops it from the store -- whether transient content is kept is Q.002. Not linked: nothing records which chunk opened it. Open, for the user's ruling with Q.002 |
| G-121 | **Chunking speed, profiled stage by stage in the app, and the slow stages cut** | *2026-10-06: "the chunking speed might be pretty slow, and I'm wondering also if the overlay registers the detections 'immediately'. Again, tests, speed profiles, improvements without breaking things, the works."* | **Partly, 2026-10-07.** Measured in the app (johnwick.movie, archive.org, 59 capture traces): the in-page fold 1.7 ms p50 (drain), mutation->host 3-21 ms, drain->overlay 4.3-6.6 ms p50, drain->3D 9-12 ms -- the overlay and the stream register a detection at once. The seconds are AFTER: the store write 0.1-4.2 s (Kuzu: anchors up to 2.4 s on archive's shadow-DOM page, the pre-query 170-450 ms, chunks 130-550 ms) and, on a new page, the wait for a vector (p50 1.0 s, p90 12 s). Cut: a capture's own chunks go to the FRONT of the embedding queue (they waited behind other pages' backlog). The address pre-query reads by primary key (`UNWIND ... {aid: x}`), not a scan of the ~500k-row Address table (scratch store, 300k rows, 800 aids: 631 -> 70 ms, identical rows). Live after a sidecar restart the store write stayed 2.6 s p50 / 8.1 s p90 over 7 captures with a COLD buffer pool on a 32 GB file: the store's size is the root (197 pages, 502k addresses in 32 GB), and compacting it rewrites the reader's store -- theirs to approve. Open |
| G-122 | **The overlay outlines the STORED chunk** -- one forum topic row is one card and one outline, though the page's own chunking cuts it into cells *(2026-10-10: "This should be all one chunk, but it is erroneaously split up into subchunks for the same card"; PLUGIN_GOAL 36)* | **Confirm** 2026-10-10. Measured live on julialang.org/latest: the sensor's fold cut the row into five cell chunks (8-12), the same at every sensor version back to 2026-09-27 (`scripts/fresh_fold.py` in a hidden window), while the store holds the row as ONE chunk (19 addresses, td..td[5]). A pushed hover now draws the page's box at once and replaces it with the stored chunk's extent a round trip later; within one stored unit it never flashes back to the cell (`pipelinebox.ts` `pushedHover`, `storedUnitMs`; `unionRect` resolves through the sensor's own `node()` so shadow addresses count). Check `G-122` in `checks/live.mjs` (planted `plantPageUnit`: the cell) -- not yet run in the Verifier |
| G-123 | **A scanned chunk's page form is SAVED and renders with its page gone** -- no "unavailable" banner ever *(2026-10-10: "I should also never see the notification that something that we have already chunked and tracked is inaccessible. All the data must be saved and mapped ... Even media"; PLUGIN_GOAL 41, 51)* | **Confirm** 2026-10-10. The browser cell takes each stored chunk's page form while its elements are on the page, a few at a time and never while it scrolls, and saves it as a content-addressed blob mapped in the graph as `Chunk.snap` (`vertiscope/obsidian/snapshots.py`, `/snapshots`, `/snapshot/<cid>`, `/snapshot_coverage`; `browser.ts` `saveFormsSlice`). Live: johnwick.movie 19/19 saved in the first 4 batches after reload. A panel reads the live page first, the saved form second (`graph.ts` `pageFormFor`); the banner is gone. `tests/test_saved_page_forms.py` (planted: never saved reads back nothing). Check `G-123` (planted `plantNoSaved`). **Open within it: media bytes** -- the form keeps absolute media URLs, so it renders offline only from the HTTP cache; **pictures saved 2026-10-11**: each picture a saved form draws is fetched once through Obsidian's `requestUrl` and kept by the sidecar (`snapshots.save_media`, `POST /media`, `GET /media/<key>`); a saved form read back points every picture it has at the local copy (`localize`). Live on Monarch: 9 forms and 2 pictures saved in 70 s, a form read back with `media: {local: 2, remote: 0}`, the copy served (9,865 bytes, image/svg+xml). `tests/test_saved_page_forms.py` (planted: a picture never saved stays remote) **Verifier PASS** 2026-10-11 (fresh store, reader idle): page form from the SAVED form, no banner; planted: markdown, nothing saved. |
| G-124 | **Hover flight zooms once per navigation, then keeps the reader's zoom**, tracking debounced *(2026-10-10: "fly-to-node should zoom initially, but preserve user zoom while still tracking during fly-throughs"; "some kind of debounce on continuous tracking and re-setting the zoom action for 'new navigations'"; PLUGIN_GOAL 39, 40, 43)* | **Confirm** 2026-10-10. `src/camera.ts` `zoomFor` (two navigations inside 1.5 s zoom once; the second is absorbed); tracking closes a quarter of the gap a frame with a 0.05 dead-band (`graph.ts` `followFocus`). Live drive on en.wikipedia/Monarch_butterfly: 10 hover flights, 1 zoom, 9 kept the reader's distance. `tests/camera.test.mjs` (planted always-zoom). Check `G-124` (planted `plantAlwaysZoom`). 2026-10-11, the unreproduced "empty nodes" flights (PLUGIN_GOAL 66): the kept zoom never leaves the target smaller than 6 px of radius on screen (`minTargetPx`, from the camera's field of view; `focusStats.clamped`; planted `plantSpeckFlights`) **Verifier PASS** 2026-10-11: two flights, one zoom, the reader's distance kept (2,677 -> 2,677); planted: reset to 877. |
| G-125 | **One hover panel persists** -- the most recent; it outlives the hover and closes itself after a minute; a chunk with nothing to show opens none *(2026-10-10: "showing hovered panels ... should persist, but disappear after a minute maybe"; "I should only see a single most recently hovered and flown to panel persist"; PLUGIN_GOAL 45, 58 -- replacing 2026-10-06's "closes them when the hovering stops")* | **Confirm** 2026-10-10. `graph.ts` `hoverPanel`/`expireHoverPanels`, `hoverPanelTtlMs` 60 s, `hoverPanelCap` 1, `hoverStats.empty_skipped`. Check `G-125` (planted `plantCloseOnLeave`) **Verifier PASS** 2026-10-11: one hover panel at a time, still open 1.5 s after the pointer left, gone after its time-to-live; planted: closed on leave. |
| G-126 | **A page's chunk cloud is centred on its url node** and telescoped into its bound with the local fit's shape kept *(2026-10-10: "Not sure why there's this clumping happening ... with centroids still at the center"; PLUGIN_GOAL 37)* | **Confirm** 2026-10-10. Measured: julialang.org/latest's 186 chunks drew as a ball whose centre sat 95 units from its node (radius 29) because offsets were taken from the page point; telescoped now from the chunks' own centroid (`src/camera.ts` `centredTelescope`; `teleStats.centre_off` reports the correction: 95.9 on Monarch). No force attracts chunks to the url node: link strength 0 in the projector layout, measured live. `tests/camera.test.mjs` (planted off-centre). |
| G-127 | **Search answers while a large page is being stored** *(2026-10-10: "retrieval breakdown during a scan over a large page. Perhaps a db lock .wal issue"; PLUGIN_GOAL 42)* | **Confirm** 2026-10-10. Not the WAL: legislation.gov.uk's capture held the store 100.6 s (77.9 s of address upserts on the 40 GB store) and every search queued behind it on the ONE shared connection. Reads now run on their own connection beside the writer (`graphstore.py` `_read_conn`), auto-checkpoint off, every checkpoint taken holding the readers' lock, the sidecar's quiet checkpointer given a 256 MB ceiling. Scratch: shared connection reads p95 4.9 s beside writes, split 46 ms; with auto-checkpoint on, a commit's checkpoint FAILED 1 write in 14 -- off and gated: 30 writes, 7 checkpoints, 4,473 reads, 0 errors (`scripts/store_read_concurrency.py`). `tests/test_store_split_reads.py` (planted `VERTISCOPE_SHARED_READS=1` waits out the write) |
| G-128 | **A LOCAL UMAP per url**, over that url's full chunk set, persisted; the page fit places the page *(2026-10-10: "persist per-URL node fits (i.e., fitting UMAP within the full chunk set within a url) and then call global updates more intermittently"; PLUGIN_GOAL 47, 49)* | **Partly** 2026-10-10. Built in the page projector (`projector.py` `_local_offsets`, `_fit_local`, `_local_knn`, `local_fits.pkl`): a chunk's offset from its page is its local-fit position at the page's reach; an unseen chunk is placed by its 5 nearest fitted neighbours at once; a refit is queued when a quarter of a page is new. Live: 58 urls fitted, ko.wikipedia/물리학 674 chunks in 749 ms, 695 re-placed; `/projector` `local`. **Measured live 2026-10-10** (`/local_quality`, 10-NN kept): local fit vs the old page-fit transform vs random -- Rust Vec 141 chunks 0.496/0.161/0.067, ar.wikipedia 341 0.422/0.130/0.030, legislation 177 0.521/0.151/0.056, he.wikipedia 108 0.530/0.239/0.080, B-tree 91 0.622/0.267/0.119, Trie 70 0.657/0.386/0.149: the local fit keeps 2.2-3.2x more on large pages. Three pages read 0 chunks (vectors not in the projector's memory) and were not measured |
| G-129 | **The global fit refits when the app is latent** -- no chunk diffs streaming -- not only at 2x growth *(2026-10-10: "ensure that we still run global umapping when there is latent activity in the app that doesn't stream new chunk diffs to the 3D graph and database"; PLUGIN_GOAL 32)* | **Confirm** 2026-10-11 -- **Verifier PASS** (`checks/live.mjs` G-129, fresh store; the test sidecar's latent window 20 s via `VERTISCOPE_LATENT_S`, the reader's stays 120 s): fit at 612 chunks; latent with no growth -- **0 refits, epoch unchanged** (the null arm); three busy pages took it to 789 against a target of 765; latent again -- **1 refit, epoch moved, 790 fitted**. Was: Partly 2026-10-10. `projector.py` run loop: 120 s with no drain and 1.25x growth since the fit trigger a full refit (`LATENT_S`, `LATENT_GROWTH`, `latent_refits` in `/projector`); the online GPU update still trains new pages 2 s after the stream quiets. Decision extracted and tested (`projector.py` `latent_refit_due`; `tests/test_latent_refit.py`, planted: the 2x rule alone never refits a quiet app at 1.3x). Not yet seen firing live (growth 1.13 at the last read, below 1.25) |
| G-130 | **Both panel forms are complete and match** -- no degraded state: the page form is what the page drew (live or saved) plus every line it did not draw, or the store's own rendering when nothing was drawn *(2026-10-10: "The following method of feature degradation on the dual panel representation shall be deprecated, with full rendering, completeness, and matching guarantees as appropriate for both panel views"; PLUGIN_GOAL 33, 59)* | **Confirm** 2026-10-10. Measured first (`scripts/practice_drive.py`, Monarch_butterfly, 36 panels opened): 15 showed >= 98% of their chunk's words, the worst 5.6% -- page forms of the hidden language list, sidebar and menus. `graph.ts` `completePageSnapshot` appends the undrawn lines beneath the page's drawing; the struck-through page button is gone. Check `G-130` (planted `plantNoComplement`: the hidden menu's items missing) **Verifier PASS** 2026-10-11 after a fix: it FAILED first -- 0 of 5 hidden-menu items shown -- because the complement read every in-page link (`[x](#m1)`) as a footnote mark the page had drawn. Now only footnote-shaped marks are (a 1-3 character label, or `#cite`); clean **5 of 5**, 23 lines complemented; planted 0 of 5. |
| G-131 | **Streamed chunks are placed by the fit before the store holds them** -- no grey wait *(2026-10-10: "async projections and fits for streamed deltas so that we don't wait with grey force-directed while hierarchical fits are happening"; "Force-directed and UMAP fitted node renderins on diff streams problem"; PLUGIN_GOAL 48, 57)* | **Confirm** 2026-10-10. Measured first (`scripts/fold_watch.py`): on ko.wikipedia 695 streamed nodes stayed grey ~20 s beside 447 placed while the capture stored (15.6 s) and the embedder waited 4.3 s for the lock; nothing stuck (STUCK 0 in every sample). Now the drain's new chunks go to `/project` (encoded under a shared encoder lock, never the store's; placed through the page's local fit or the page fit; a provisional page position for a page the fit has not met) and take the fit's colour and place at once (`projector.py` `project_transient`, `browser.ts`, `graph.ts` `applyProjected`). `/project` live: 2 chunks in 66 ms (encode 46, place 20) |
| G-132 | **A picture keeps its aspect ratio in the page form** at a panel narrower than the page drew it *(2026-10-10: "Image aspect ratio rendering is weird on the HTML rendering panel forms"; PLUGIN_GOAL 55)* | **Confirm** 2026-10-10. A fixed pixel height under max-width:100% stretched every picture a panel shrank, and a text-less shape (a round play button) reflowed to a line; pictures, posters, inline SVGs and drawn shapes now keep `aspect-ratio` with the page's `object-fit`/`object-position` (`snapshotscript.ts` `ratio`). Check `G-132` (precondition: the panel is narrower than the 700 px the page drew) **Verifier PASS** 2026-10-11: the picture's ratio in the page form 3.5 against the page's 3.5. |
| G-133 | **Hover flies to the stored chunk on every page**, an already stored one included; relative pictures in the markdown form resolve against the page's base *(2026-10-10: "Flying to chunk nodes ... has degraded"; "Fly to hovered degradation spotted as well when navigated to a new website"; PLUGIN_GOAL 35, 56)* | **Confirm** 2026-10-10. Two causes, both measured: (1) the sidecar's projector drained a 5,132-chunk backlog without yielding its lock and `/pages` timed out at 30 s, so every hover's placement hung (`projector.py` yields between batches; `sidecar.ts` `place` bounded at 5 s); (2) on johnwick's Parabellum page 310 of 519 in-page chunks resolved to NO stored chunk because `coversFor` refuses ancestors -- now the map's nearest-ancestor walk for hovers (`browser.ts` `storedCidFor`, planted `plantNoAncestorHover`): 0 unresolved. Pictures: johnwick sets `<base href="/">`; the cell records each page's `document.baseURI` (`snapshot.ts` `putBase`/`baseFor`) |
| G-134 | **Every control and picture of a chunk is in its page form**, degrading gracefully at a panel's width *(2026-10-10: "Buttons on the page aren't persisted to the HTML chunk"; PLUGIN_GOAL 54)* | **Confirm** 2026-10-10. Measured in the panel's own frame: johnwick's footer chunk (`2acd8f36...`) draws Shop, Text Updates, Email Updates, LEGAL and FOLLOW, white and visible, icons loaded -- below the fold of a 420 px panel (y 945-1062), the three buttons wrapping to two rows at 311 px. They are light-DOM Angular components, not shadow roots; the clone already descends open roots |
| G-135 | **A harness drive never runs over the reader** *(2026-10-10: "Weird behavior where I click the markdown button ... the whole panel disappears" -- it was the drive cycling panels; PLUGIN_GOAL 50)* | **Confirm** 2026-10-11 -- every stage now re-checks the reader at each wait (`practice_drive.py`: the store stage's 90 s wait and the pin stage had none). `scripts/check_drive_stops.py` runs the drive and marks the reader back mid-run: stamped at 8 s (landing) it stopped **0.6 s** later; stamped at 25 s (after storing) **0.5 s** later. Was: Open 2026-10-10. The drive (`scripts/practice_drive.py`) checked reader idle once at the start and then opened and closed panels for minutes while the reader used the app; it was stopped by hand. Wanted: every stage re-checks `__vertiscope.reader.idleMs()` and stops at the first sign of the reader |
| G-136 | **The end-to-end drive on pages new to the store**: navigate, scroll, hover, pin to the clipboard by double right-click, see every chunk placed in its url's scope, every panel full, at least one picture on the billboard *(2026-10-10; PLUGIN_GOAL 30, 31, 33, 34)* | **Confirm** 2026-10-11 (was Partly 2026-10-10). `scripts/practice_drive.py` on en.wikipedia/Monarch_butterfly (live, `build_analytics/practice/`): 1,999 streamed + 391 branch nodes in 14 s of real wheel scrolling; 718 chunks stored; 12/12 hovers resolved, 10 flights; the double right-click pinned exactly the chunk under the pointer, card and billboard both page form, 770 chars, 4/4 pictures; 5/5 chunks with a picture showed it in the panel AND as the node's picture. Fell short: panel completeness (now `G-130`) and url scope (`D-49`) **Re-driven 2026-10-11 on a page NEW to the store** (en.wikipedia/Okapi, `scripts/practice_drive.py`, reader idle): 189 chunks stored, placeable after 19.9 s, **183 of 183 nearer their own url node**, 0 overlaps, 0 inside its sphere; 11 of 12 hovers resolved, 11 flights, zoom kept on all 11; the double right-click pinned the chunk under the pointer -- card and billboard both page form, picture loaded, the node drawn as that picture; 8 of 8 picture chunks showed it in the panel and on the node; panels **26 of 40 at >=98%, minimum 84%**. Two drive defects fixed on the way: it asked for placement before the chunks had vectors (Axolotl: 0 of 232 placed at 11 s, all placeable a minute later -- it now waits until placeable), and its coverage counted link DESTINATIONS as missing words (footnote anchors, edit urls: 16 of 40 'full'). What the panels still 'miss' are `title` attributes the markdown joins into link labels ("Taxonomy (biology)", the IPA hover titles) -- invisible on the page, so absent from the page form by design |
| D-49 | **A page's chunks reach into its neighbours, clump, and sit on their own url node** *(2026-10-10: "get umapped within their url domain node's scope"; "keeping the URL nodes close enough together ..."; "force-directed post-umap ... with the original residual coordinates as phantom coordinates ... collision ... with a radius/diameter safety factor on collision spheres"; "Phantom links and clumping tells me the central URL node collision radius boundary was not enforced"; PLUGIN_GOAL 31, 37, 38, 44)* | **Confirm** 2026-10-10. Measured on ko.wikipedia/물리학 (285 chunks open): **2,069 overlapping pairs, 68 chunks inside the url node, nn p50 1.5 against a drawn radius 2.3** -- the collider ran only for 3 s after a placement and the fit was a dense core. Now, per open page: the radius by RANK (cube-rooted, so the ball fills evenly; direction and order kept) and the targets RELAXED -- collision spheres at the safety factor, the url node's own sphere kept clear, each anchored to its telescoped fit as the phantom (`src/camera.ts` `centredTelescope(uniform)`, `relaxCloud`; `graph.ts` `telescope`) -- the home force glides each node there, so calm pins and dragging are untouched. After: **0 overlapping pairs, 0 inside the url node, nn p50 10.3**; the relaxation reported 255 -> 0 on the targets. Neighbours make room: a closed page inside an open page's sphere is moved out to 2B + its radius, two open pages until their spheres part, each keeping its fit as `homeFit` (`roomFactor`, planted `plantNoRoom`). `tests/camera.test.mjs` (planted no-relax: overlaps and intrusions kept; planted raw radii: the knot kept). Seen in the app: `build_analytics/practice/cloud_after_relax.png`. **Scope re-measured on Monarch_butterfly 2026-10-11** (669-673 chunks open): overlaps 0, inside the url node 0, but only **48** chunks nearer their own url node -- the room pass moved neighbours' TARGETS while (a) calm pins held them and (b) `contain` pulled each back to its unmoved anchor (targets ~288 out, drawn at 57-111). Now a moved page glides to its target and its anchor moves with it (`homeAnchor` keeps the fit's): **671 of 671 nearer their own url node**, 104 neighbours moved, within ~10 units of target; `build_analytics/practice/monarch_scope.png` |
| G-137 | **The Verifier and every harness drive stop the moment the reader uses the app** *(2026-10-10: a run drove the browser cell while the reader navigated to archive.org; PLUGIN_GOAL 50)* | **Confirm** 2026-10-10. `verify.ts` `runChecks`: before each check the run ends if the reader's input stamp moved since it began ("the reader used the app"), and `__vertiscope.verify.stop(why)` ends it on request; `scripts/practice_drive.py` marks itself as a stress run and stops at the next loop step when the stamp moves. **Seen live 2026-10-10 20:53**: a fresh-store run ended itself after two checks, "stopped: the reader used the app" |
| G-138 | **Saving page forms never lags the page** *(2026-10-10: "Significant render lag on streamed updates and saves to the 3D viewer from the browser"; PLUGIN_GOAL 61)* | **Confirm** 2026-10-10. Measured while the reader browsed archive.org (`scripts/main_thread_probe.py`, 40 s): Obsidian's main thread healthy (frame gap p95 13 ms, no long task), but the saver held the PAGE's thread 14.7 s of the 40 (eight snapshot clones a slice, the same thread the sensor drains from). Now two a slice, 2.5 s apart, never within 2 s of a scroll, hover or drain. The sidecar is not globally blocked by store writes (`scripts/gil_probe.py`: /health p95 32 ms through a 2.3 s write); the 7.5-20 s end-to-end is the persistence path in series (store, the embedder waiting 3.5-4.3 s for the store lock, placement) -- which the streamed nodes no longer wait on (`G-131`, live: 434 of 434 projected) |
| G-139 | **The complete page form never repeats what the page drew** *(2026-10-10: "Duplicate image found in the HTML render on ko.wikipedia on the higgs boson"; PLUGIN_GOAL 60)* | **Confirm** 2026-10-10. Pictures compared by file (a page draws `/thumb/.../250px-X.jpg` of the `X.jpg` a line names); link destinations never counted as content (a footnote `[[ 77 ]](#cite_note-...)` nests brackets); a line of in-page jumps only is never complemented (`graph.ts` `completePageSnapshot`). The MARKDOWN form drew `32(#cite_note-...)` as text (nested brackets); footnote jumps now render as superscript marks like the page's (`chunkMarkdown`) -- seen live on Asclepias_exaltata: `[2]` marks, no raw cite text (`scripts/footnote_probe.py`) |
| G-140 | **One unit for a field list, in the page's own chunking too** *(2026-10-10: "per-field chunk degradation on overlay"; "This should be all one chunk"; PLUGIN_GOAL 36, 62)* | **Confirm** 2026-10-11. archive.org's item metadata was SIX in-page chunks (one per field) and ONE stored chunk (`scripts/field_units.py`). The sensor's `merge` variant gathers small siblings into budget-sized runs, but was off -- and with it on, `at()` resolved archive's merged fields to NO chunk. Cause found with a read-only `slotOf` export (`scripts/merge_at_probe.py`): the sweep at the end of every fold untracks and reports removed each slot not marked SEEN, and `makeMerged` never marked its slots seen -- every merged run was swept by the fold that emitted it. Fixed (`sensor.js` `makeMerged`: the slot's live head, tracked, seen; planted variant `unseenmerged`); `merge` + `semantic` now ON in the browser cell (`browser.ts` `sensorVariants`, planted `no-merge`). Check `G-142` PASS. Live on a ScienceDirect article afterwards: 200 in-page chunks against 212 stored, all 200 resolving to a stored chunk; sensor tests 196 passed |
| G-141 | **A panel paints at once** -- never waiting on its page form, its controls or a duplicate fetch *(2026-10-10: "Overlay panel showing in the 3D GUI is now extremely slow... watch out for that in time profiling"; PLUGIN_GOAL 67)* | **Confirm** 2026-10-11. Profiled stage by stage in the app (`scripts/panel_stages.py`): first paint **222-763 ms**. Causes: (1) the page-form attempt ran BEFORE first paint, and when the page drew nothing for a chunk the in-page snapshot fell through to a 137 ms sidecar fetch and a second clone -- twice per panel (`browser.ts` `snapshotChunk`, `graph.ts` `openBillboard`: 80 ms for the page form, else the markdown paints and the page form replaces it; one attempt, which is also the upgrade; planted `plantSerialPanel`); (2) `/chunk` spent ~50 ms of every 51-110 ms on a scan of the 600k-row Address table for the chunk's controls, flat whatever its size -- now read ONCE per page per capture, warmed when the page's map loads, dropped when a capture writes the page (`sidecar.py` `_page_controls`, `_ms` timings in the payload; planted `_PLANT_CONTROL_SCAN`; `tests/test_chunk_payload_batched.py` proves the payload identical). After: `/chunk` 18-41 ms, **first paint 28-34 ms** |
| G-142 | **Merged in-page units resolve and hold** -- every member of a field list longer than the budget resolves to its merged unit through `at()`, the same across folds *(2026-10-11; PLUGIN_GOAL 62)* | **Done** 2026-10-11 -- Verifier PASS on the working store: `tests/fixtures/field_list.html` (60 fields that re-render after load, 3,766 chars) -> 5 merged units, every field resolved, identical across two folds; planted `unseenmerged`: 58 of 60 resolve to nothing (`checks/live.mjs` G-142) |
| G-143 | **A section heading opens the chunk of what it heads** -- never the last line of the section before *(2026-10-11: "chunking degradation seen in https://culinarypedia.com/..."; PLUGIN_GOAL 69)* | **Confirm** 2026-10-11. culinarypedia's flat article (`<h2><p><p><ul><table>` under one `<div>`) stored `p[8], ul[2], table[2], h2[3], p[9]` as ONE chunk: each heading and its lead closed the previous section's chunk. The 256-window merge (`markdown.py` `_descend`) now flushes before a bare heading, never takes a heading by the lenient rule, carries a trailing heading into the next run, and returns a short section tail (< `MIN_FILL`) to the chunk before it within `LENIENCY` -- a heading always opens. Bare headings only: cutting before every heading-led `<li>` made the merge a running total again (37 new chunks for one inserted row of 400, caught by `tests/test_content_boundaries.py`). `tests/test_heading_chunks.py` (planted `PLANT_TRAILING_HEADINGS`: headings mid-chunk again). On the LIVE page's own HTML (read from the browser cell, 2026-10-11, reader idle), rendered by the code under test: **9 of 9 headings open their chunk, 0 mid-chunk**; planted: 4 of 9, 5 mid-chunk. The stored copy follows when the sidecar restarts on this code (held until its 249 MB WAL is folded in, `G-153`) |
| G-144 | **A hover draws one outline, once** *(2026-10-11: "overlays flicker on github"; PLUGIN_GOAL 68)* | **Confirm** 2026-10-11. A hover drew the page's element box, then the stored unit's union rect when it resolved -- two outlines per hover. Now a hover over a known stored unit draws only the final outline (`pipelinebox.ts`; 40 ms fallback; planted `plantTwoStep`). Live, the reader's own browsing: **241 outline placements for 217 hovers, 0 fallbacks**, stored-unit rect 8-18 ms |
| G-145 | **Tens of thousands of nodes without a freeze, every feature kept** *(2026-10-11: "obsidian froze"; "really slow though. id like the same feature set with significant speedups"; "immediate lag after clicking a node. perhaps force-directed has something to do with it"; PLUGIN_GOAL 71, 73)* | **Confirm** 2026-10-11. Profiled in the app at 23,027 nodes (CDP sampling; `scripts/freeze_watch.py`, rolling 15 s windows). Found and fixed: (1) pictures decoded through a char-by-char data url, all at once, failures retried every frame -- 2.8 s of 11 s (`graph.ts` `decoded`: `createImageBitmap` on a Blob; `scenebatch.ts`: 4 in flight, failures remembered; planted `plantDataUrlDecode`, `plantUnthrottled`); (2) collision over all 23k nodes to move the few free ones -- 2.3 s (`collideScope`: free nodes and all within reach; planted `plantFullCollide`); (3) `d3AlphaMin` 0, so every click's `dragend` bought 15 s of ticks (`d3AlphaMin(0.001)`; planted `plantNoAlphaMin`); (4) a 4,096-entry colour cache thrashing at 23k hues -- 1.9 s of 7; (5) pick proxies walked by the renderer -- 0.7 s (hidden as objects; raycasting ignores `visible`); (6) `fitRadiiToSpacing` all-pairs, **34 s of 35 on the main thread** once the engine could stop -- a grid with the exact verdict (planted `plantAllPairsSpacing`): **3 ms**. Reader: "image hovers and speed are back to normal" (before (6)) |
| G-146 | **Pictures near the pointer's ray, spheres elsewhere; url nodes always** *(2026-10-11: "render images within closest distance to the ray normal projection of the mouse proximity at a time ..."; "hover images also only apply for chunk view. not url view."; PLUGIN_GOAL 72)* | **Confirm** 2026-10-11. `graph.ts` `refreshDetail`: the 64 chunks with the shortest normal to the mouse ray, per unit of depth (screen nearness -- the raw normal let far specks take every slot), recomputed on pointer or camera moves at most every 80 ms; others draw at the SAME size as their colour, so collider, pick proxy and drawn extent never move with the mouse; url and branch nodes always picture (planted `plantAllPictures`). Live: 2.8 ms a pass over 9,855 candidates. `scripts/check_reader_items.py` (reader idle): pages view **255 of 255** url-node pictures drawn; chunk view **64 of 9,919**; planted 9,919 of 9,919 |
| G-147 | **The url node's sphere is a third of the distance to its nearest url node AS DRAWN, and no own chunk enters it** *(2026-10-11: "force sphere does the opposite of what its intent is... linked nodes are within the sphere ..."; "force fields still broken"; PLUGIN_GOAL 64)* | **Superseded** 2026-10-11 by the reader: *"Remove the repulsion sphere entirely please"*, then *"Giant clumping problem"* (PLUGIN_GOAL 79/80). The sphere is gone from `graph.ts` -- its radius (`rootShare`), the bound it widened (`B >= sphere/0.6`, which widened every chunk's room so chunks stopped shrinking and drew at full size), the telescope's inner hole, `sphereStats` and `plantFitSphere`. A url node keeps clear only its DRAWN body, as any two nodes do. `scripts/check_reader_items.py`'s arm for it now checks item 80 instead: no two of an open page's chunks overlap as drawn (planted `plantNoRelax`) |
| G-148 | **A page's chunk map is there whenever its page is** *(2026-10-11: "chunking degradation and invisible panels spotted in the chunk node view")* | **Confirm** 2026-10-11. Comparison_of_web_browsers sat with an EMPTY map: its one landing load failed during a freeze, the page was already stored so no capture came to patch it, and every hover resolved to nothing. The load is retried at 1.5/4/10/25 s while the map is empty (`browser.ts`, `mapRetries`; planted `map-once`). After reload: 301 chunks mapped |
| G-149 | **A right-click opens what the reader folded** *(2026-10-11: "re-right clicking doesn't open chunks back up in chunk view")* | **Confirm** 2026-10-11. The toggle asked "is anything of this page drawn?" -- and the page being browsed keeps drawing its stream's nodes, a pinned chunk stays -- so every right-click folded nothing. The reader's own fold decides first (`togglePage`, planted `plantToggleByDrawn`). `scripts/check_reader_items.py` (a chunk pinned, so the page stays drawn): clean fold 349 -> 1, second right-click **expand -> 349**; planted: the second right-click folds again, 1 -> 1 |
| G-150 | **A capture writes only what the store does not already hold** *(2026-10-10: "Please ensure everything is processing async and as fast as possible ..."; PLUGIN_GOAL 67)* | **Confirm** 2026-10-11. A new capture session re-sends every chunk as added; the store rewrote identical chunks (GitHub 52 in 2.5 s; ScienceDirect 212 of 212). Now compared against `graphstore.chunk_mds` first (`sidecar.py`, `phases.unchanged_skipped`; planted `_PLANT_REWRITE_SAME`). Live: culinarypedia re-sent 34 dirty, **34 skipped, store 63 ms** against 1,869 ms the first time. `tests/test_skip_identical_writes.py` |
| G-151 | **Chunk view is UMAP alone** -- no force simulation; every node at its fit *(2026-10-11: "i dont think the chunk view needs force-directed, might also slow things down and we can rely on UMAP only for this view"; PLUGIN_GOAL 78)* | **Confirm** 2026-10-11. `graph.ts` `draw`: in chunk view every force is removed but the link force at strength 0 (it resolves an edge's ids to the nodes the batch draws between) and each node is pinned at `fitX/Y/Z`; the pages view gets its forces back on the next load (`umapOnly`; planted `plantChunkForces`). Seen in the app 2026-10-11 (`scripts/check_chunk_view.py`, reader idle): **0 of 22,835** nodes off their fit; planted: 1,888 moved, up to 2,861 units. The frame then measured at 4.7 s of script in every 5 -- not the forces: the batch rewritten every frame and three.js re-multiplying 23k proxy world matrices because the scene and the graph's root group recomposed theirs each frame. Now the batch syncs only on a change (engine tick, glide, node set, sizes/colours, hover, picture, panel; every 250 ms regardless; planted `plantSyncEveryFrame`), proxies compose their matrix when moved (`nodePositionUpdate`), static ancestors are frozen (`frozenAncestors`; planted `plantProxyAutoMatrix`), and chunk view's engine stops after 2 ticks. `scripts/check_frame_cost.py` at 22,836 nodes: **5.1 ms of script a frame** against 21.6 (sync planted) and 15.4 (matrices planted); picking 10/10 in every arm through the graph's own tooltip |
| D-50 | **Chunk view: link hubs drawn as specks, rows missing from a stored table** *(2026-10-11: "force fields still broken"; "chunking degradation ... in the chunk node view")* | **Done** 2026-10-11 -- both halves found. Specks: `fitRadiiToSpacing` (`G-145`, floored) and chunk view now has no forces (`G-151`). Rows: a fresh capture (390 chunks, 388 identical) still lacked Konqueror/KDE/KHTML, so it was not staleness; the sensor DOES emit them (`scripts/sensor_payload_probe.py`), and the capture's render dropped them -- `G-152` |
| G-152 | **A link whose title is its own name renders on the live path** *(2026-10-11: "chunking degradation and invisible panels spotted in the chunk node view"; `D-50`)* | **Confirm** 2026-10-11. Reproduced end to end offline from a fresh sensor payload of Comparison_of_web_browsers: the live path files a link's href under `link.anchor` (category `link`, not `urls`), so `_dedupe` compared the url as prose and the title -- already joined with the link's text -- was "subsumed" by its own url. Now a unit is a target by accessor as well as category (`markdown.py` `_dedupe`, `_TARGET_ACCESSORS`; planted `PLANT_URL_AS_PROSE`), and identical words join as one spelling (`_join_inline`). That page: **2,456 link lines, 40 browser-name links, tr[88] `[Konqueror] [KDE] [KHTML] [WebKit]`**; planted: 1,235, 0, the row from `BSD` on -- **1,221 link lines** a page were being dropped, every Wikipedia article link whose title is in its url. `tests/test_live_link_titles.py`. Stored pages keep the thinned copy until recaptured |
| G-153 | **The store's write-ahead log is folded in while the reader is away** *(2026-10-10: "Please ensure everything is processing async and as fast as possible ..."; the D-48 losses)* | **Confirm** 2026-10-11. The checkpointer waited for 120 s with no request of any kind, which the plugin's background polls never allow: after 2.8 idle hours the WAL held **249 MB** unfolded, no checkpoint recorded since the sidecar started. Now also due after 10 min with no WRITE and a 2 s lull between polls, checked every second (`sidecar.py` `_checkpoint_due`; planted `_PLANT_REQUEST_QUIET`; `tests/test_checkpoint_due.py`). Live 2026-10-11: the first rule (a 2 s lull) never saw one -- the open pane polls about once a second -- so the WAL reached 144 MB; with the plugin paused it folded at once (78.7 s, the file emptied). The lull requirement is gone: ten minutes without a write is enough. **Seen working:** last write 08:11:01, checkpoint 08:21:16 with the pane open and polling, 12.5 s, the WAL left at 1 KB |
| G-154 | **A sidecar restarted under an open page never stores garbage addresses** *(2026-10-11, found confirming `G-152`: "Everything in the doc built and confirmed")* | **Confirm** 2026-10-11. Restarting the sidecar while Comparison_of_web_browsers stayed open stored the Konqueror row under `/header/tr[2]/b/small/i[88]/ol/nav/paragraph`: the page's sensor had sent its interned-segment dictionary to the old process and now sent only additions, decoded against an empty one. The check `sensor_restarted` covered only the other direction. Now a fresh session that cannot complete the dictionary refuses with `409 resync` (`sidecar.py`, planted `_PLANT_NO_RESYNC`), the plugin calls the sensor's new `resync()` and drains (`browser.ts` `resyncSensor`), and the sensor re-sends its whole dictionary and every chunk -- an `EMIT_GEN` generation on every skip-unchanged gate (`sensor.js`). Hidden window on that page: first drain 475 chunks / 107 entries, a quiet drain 0 / 0, after `resync()` **475 / 107**. `tests/test_capture_resync.py` (whole dictionary decoded; stale refused with resync, then decoded once whole; planted decodes it). **Verifier PASS** 2026-10-11 (`checks/live.mjs` G-154, fresh store): a busy page's sidecar session dropped mid-visit -- clean: 2 refused, 2 resyncs, **20 captures stored after the loss, 262 of 262 stored addresses held by the page**; planted `no-resync`: 51 refused, 0 stored. The working store's comparison page holds 0 garbage-shaped addresses of 471 chunks |
| G-155 | **An open page's chunks are never drawn as a clump of large overlapping spheres** *(2026-10-11: "Giant clumping problem", after "Remove the repulsion sphere entirely please"; PLUGIN_GOAL 79/80)* | **Confirm** 2026-10-11. The sphere is gone from `graph.ts` (G-147 superseded). `scripts/check_reader_items.py` `(80) no clump`, on the stored page with the most chunks (RFC 9110, 1,172 chunks): clean **0 overlapping pairs as drawn, 0 in the url node's body**; planted (chunks unrelaxed, `plantNoRelax` with `plantBigChunks`) **845 overlapping, 240 deep**. The first two runs of this arm could not fail: `plantNoRelax` alone on Dril read 0 like the clean arm, and the 8-chunk fixture fits at any size -- hence the crowded page. Drawn sizes were equal in both arms (half 2.3), so it is the relax that parts them |
| G-156 | **With no reader activity the scene turns -- position and colour ("xyzhsv")** *(2026-10-11, PLUGIN_GOAL 83/93: "a latent feature that rotates both cartesian and color coordinates slowly but noticeably whenever there is no user activity"; "pls dont forget about the rotating xyzhsv")* | **Confirm** 2026-10-11 (`confirm.mjs G-156`, live: idle, the camera turned and the hue moved with no node's colour or layout written; acted, both stopped and the hue returned to 0; planted `plantNoDrift`: nothing turned; the hue reaches the glass orbs too) — built: `graph.ts` `idleDrift` -- after 20 s with no reader input (`__vertiscopeReaderAt`) the camera orbits its target at 0.063 rad/s and every colour turns about the grey axis at 0.052 rad/s (`scenebatch.ts` `uHue`, in the sphere, streaming and glass shaders); drawn only, nothing written; any input stops it and the hue eases back in about a second; suspended while the verifier or a stress run is driving. Check `G-156` (planted `plantNoDrift`); its first run failed on the check's own window (activity measured past the 1 s threshold it set) |
| G-157 | **The naked search field on the 3D panel; k/n beside it; a horizontal scroll that sets how many results are drawn; results lit, everything else colourless glass** *(2026-10-11, PLUGIN_GOAL 84/86/87/88)* | **Confirm** 2026-10-11 (live, before n was served). `searchfield.ts` (`visibleCount`, `brightness`, `tests/searchfield.test.mjs`), `graph.ts` `searchAsk`/`showSearch`/`lookOf`, `scenebatch.ts` glass pass (one more draw call: a lens impostor with a fresnel rim and up to 16 point lights in world space). Live (`confirm.mjs G-157`): field centred at the panel's bottom, placeholder "search"; "protocol" k=12 -> 11 hits, 1 shown at the left with 1 light and every other node a colourless lens; scrolled right, 11 shown, 11 lights, the last-revealed brightest (1.0) and the first dimmest; cleared, no lens left. Planted `plantNoGlass`: no lens, no lights. Found on the way: `ForceGraph3D(canvas)` empties its element (the field was detached), and `absorb` dropped results whose page was not open. The reader saw it: "the rendering looks really amazing, scrolling works perfect". **Open in it:** n from the ranking (`/search` `n`, needs the sidecar restarted) |
| G-158 | **Every query also searches DuckDuckGo: the browser cell scrolls the results and presses "More results", and the page streams in as a diff** *(2026-10-11, PLUGIN_GOAL 85)* | **Confirm** 2026-10-11. `browser.ts` `searchWeb`, `graph.ts` `followWeb`, setting `webSearch` (on: the query leaves the machine -- the one thing the plugin transmits by itself). Live (`confirm.mjs G-158`): a query from the field took the cell to DuckDuckGo's results, it scrolled and pressed "More results" by pointer input, and the results page was captured into the store. Planted `plantNoWebSearch`: the cell never left its page |
| G-159 | **"showing {k}/{n} results", k an editable top-k, never above n** *(2026-10-11, PLUGIN_GOAL 86: "showing 12/11 results ... I'm sure there's more results")* | **Confirm** 2026-10-11 (live, `confirm.mjs G-157`: "protocol" served n = 275 matching; 49 of the 50 asked returned; k and n are both fields, k never shown above the results there are) — `/search` returns `n`, the ranking's own count of chunks with a positive score (`search.py` `SearchDiagnostics.survivors`), before duplicates collapse; the field shows k at most n. Needs the sidecar restarted to be served |
| G-160 | Superseded into `G-157` (the scroll's window) | **Superseded** |
| G-161 | Superseded into `G-157` and `G-166` (glass and light) | **Superseded** |
| G-162 | **A toggle shows or hides the browser overlay's chunk boxes by alpha only** *(2026-10-11, PLUGIN_GOAL 89)* | **Confirm** 2026-10-11. `browser.ts` `toggleBoxes` (setting `showBoxes`, class `vertiscope-boxes-off`, opacity 0 on outline/structure/diff/pin boxes). Live: off, the hover outline placed at opacity 0 and the hover still reached the 3D view; on, opacity 1. Planted `plantBoxesStopHover`: off also stopped the hover |
| G-163 | **The overlay and the stream are fast and right on every page**: outlines respond at once to scrolling, updates, streaming and region identification; chunking and the diff stay O(delta); every detection found, nested shadow roots included, at the right coordinates -- tested on every corpus page *(2026-10-11, PLUGIN_GOAL 90)* | **Confirm** 2026-10-11 (overlay coordinates; the stream's O(delta) speed is G-174/G-164's) — `scripts/check_overlay_hits.py`, two measures over ten hard pages. (1) The SENSOR's box: for a grid of points, the deepest element by the browser's own hit testing through open shadow roots, and whether the box for its chunk contains the point. Displaced boxes only on RFC 9110 (21 of 84: a zero-height `<dl>` clipped the text box to a 6 px sliver) -- fixed, 21 -> 0 live, planted `plants.yclip` restores them. (2) The outline the plugin DRAWS, which on a stored page is the union of the stored chunk's elements: real pointer moves, the overlay's own rect read back. Before: the outline missed the pointer by 40+ px on YouTube 18 of 27 hovers, archive.org 8 of 21, IMDb 6, DDG 4 -- the stored xpaths resolve to OTHER elements on a page that moved since it was stored. Fixed (`pipelinebox.ts`): a stored union that does not touch the page's live box for the hovered chunk is not drawn, the live box is (`unionFallbacks`); a kept outline must overlap the new element. After: YouTube 25/27 inside, 1 displaced; archive.org 21/21, 0; DDG, bandcamp, GitHub, HN, richardmille 0 displaced; IMDb 2 in BOTH arms (its carousels move -- the page, not the overlay). Planted `plantStaleUnion`: YouTube 18, archive.org 8 back. The sensor's lookup is 0.1-0.3 ms |
| G-164 | **Hover-to-panel is immediate at every stage of a stream** -- grey nodes, projected, the url's local update, the full UMAP refit -- each shown to run and reach the 3D panel, its time profile reported at the interface with provenance through the backend *(2026-10-11, PLUGIN_GOAL 91)* | **Confirm** 2026-10-11. `profile.ts` visits: drain, grey, projected, stored, refit marked the first time each reaches the 3D view, per page visit, with provenance (the drain trace, the sidecar's phases), shown in the browser's readout as a stage strip. Live (`confirm.mjs G-164`, a never-stored page): drain 255 ms, grey 287, projected 382, stored 2,026; planted `plantNoProjected` shows that stage missing. Found on the way: 0 of 300 drain traces ever reached "visible" (a capture's reply no longer carries placed nodes; pick proxies are invisible objects); a window-held profiler replaced by `instanceof` thrashed between plugin loads -- now by capability. Hover-to-panel: dwell 150 -> 60 ms, page-form wait 80 -> 30 ms, payloads prefetched for the browsed page and held 60 s (dropped when the stream rewrites them); measured 103-163 ms on settled pages against 209 before; the prefetch's own share is NOT yet separated from the rest (a fair A/B is still owed). The refit stage observed live 2026-10-11: the pane's refit pressed while a never-stored Okapi url was browsed -- the new fit landed 50 s later and the page's strip marked `refit` at 59.3 s with the fit's epoch and its 290-chunk sample as provenance. Seen in the same run: with the refit computing alongside, `stored` took 42.7 s (vs ~2 s without), and `projected` did not mark -- the projector was busy refitting, so the stream's placements waited for it (an interaction to measure, not yet fixed) |
| G-165 | **Renamed labyrintalis, secrets and personal information removed, pushed to a NEW repository** separate from the mothership on "mortegon" -- after the items above *(2026-10-11, PLUGIN_GOAL 92)* | Open — waiting on the reader. Inventory (2026-10-11, read-only, 850 tracked files): home-directory paths (`C:\Users\<name>`) in 16 files, the user name in 33, the author's full name in 1; every commit's author name and email (published by a push unless the history is squashed or rewritten); `tests/corpus/` -- third-party page snapshots up to 2.6 MB each, one holding archive.org's own expired CSRF token (a copyright question to publish; `scripts/fetch_corpus.py` can fetch it instead); "vertiscope" in 360 files / 2,612 lines, including the Python package and the plugin id `vertiscope-bridge` (renaming the id moves the vault's plugin folder and settings). No secret of the reader's found. Needs from the reader: `gh auth login`, the owner (the account or org "mortegon" is under), visibility, and rulings on history and the corpus |
| G-166 | **The glowing glass orb is every node's default look** -- its own colour, glowing from within; during a search the lights are the results in the scroll window *(2026-10-11, PLUGIN_GOAL 93: "standardize the latent glowing glass orbs as the default")* | **Confirm** 2026-10-11 (seen live in `confirm.mjs`) — built: `graph.ts` `lookOf` (plain nodes -> glass with glow 1 in their own colour; pictures and streaming nodes keep their looks), `scenebatch.ts` glass shader (tint, inner glow, hue turn). Check `G-166` (planted `plantOpaqueOrbs`) |
| G-167 | **Retrieval is a look: a search places, moves and removes no node** -- results light the drawn node standing for them (their chunk, else their page), and the streaming and layout pipelines run as they would without it *(2026-10-11, PLUGIN_GOAL 96: "streaming and node layout pipelines ... unaffected by the retrieval results (since that's just a brightness and fly-to-node thing)")* | **Confirm** 2026-10-11. `graph.ts` `resolveSearch` (re-resolved on every draw), no placement. Live (`confirm.mjs G-167`, url view, "dril"): the scene's node set identical before, during and after; results resolved to their page nodes. Planted `plantPlaceResults` (the first version, which placed undrawn results and removed them on clear): the node set changed. Consequence, measured: in the url view a closed page's results light its page node ONCE -- 12 results resolved to 2 page nodes -- which is why the url view shows few glowing nodes where chunk view shows every result |
| G-168 | **Every node is the same glowing glass** -- streaming nodes as dimmer orbs; a REVEALED picture is the picture alone, unrevealed the node is its orb (the old node/image switch) *(2026-10-11, PLUGIN_GOAL 99: "we dont need spheres over images")* | **Confirm** 2026-10-11 (seen live in `confirm.mjs`) — built (`graph.ts` default look; an orb-around-picture was built and removed on the reader's word). Check `G-166` covers it (planted `plantOpaqueOrbs`) |
| G-169 | **A check run pauses for the reader and resumes after quiet**; a check the reader acted in is run again *(2026-10-11, PLUGIN_GOAL 98: "tests should auto-resume after I interact with the GUI/plugin")* | **Confirm** 2026-10-11 (seen live in `confirm.mjs`) — built: `verify.ts` `waitForQuiet` (30 s quiet, 30 min at most), re-run of an interrupted check (twice at most), `state.paused/pauses/resumed`; `confirm.mjs` prints the pause and the resume. Planted `plantStopOnReader`: the old stop |
| G-170 | **Chunk view gets one bounded collision relax** after its layout lands -- collision only, each node leashed to 4 of its radii from its UMAP point, one iteration a frame, the fit unwritten *(2026-10-11, PLUGIN_GOAL 100: "perhaps *some* amount of force-directed is still worth, but not to the extent that we have to break our memory bank or see nodes exploding")* | **Confirm** 2026-10-11 (seen live in `confirm.mjs`) — built (`graph.ts` `relaxChunkView`, integer spatial hash, 40 iterations at most). Check `G-170` (planted `plantNoChunkRelax`) |
| G-171 | **No node in the old material**: a picture not yet in the atlas (or failed) is its glowing orb meanwhile *(2026-10-11, PLUGIN_GOAL 101: "still seeing older nodes in tests")* | **Confirm** 2026-10-11 (seen live in `confirm.mjs`) — built (`scenebatch.ts` sync routes a pending picture to the glass pass; `lastStats.spheres` counts the old material). Check `G-166` asserts at most the hovered node is one (planted `plantSphereFallback`) |
| G-172 | **Nodes near the pointer's ray glow** -- the picture-reveal region, graded by nearness: an orb glows brighter, a picture keeps its image and glows at its edge *(2026-10-11, PLUGIN_GOAL 102)* | **Confirm** 2026-10-11. `graph.ts` `refreshDetail` ranks every node by nearness to the ray in the same pass that picks the pictures (`glowNear`, 1 at the nearest, 0.25 at the region's edge); `scenebatch.ts` picture glow (brightened, edge light) and orb glow above 1. Live: 64 in the region, 8 orbs brighter, 56 of 56 pictures glowing with their image kept, none outside the region. Planted `plantNoHoverGlow`: none |
| G-173 | **A page's chunks are linked along the trie** -- each to its nearest enclosing chunk, never all to the url node -- however the page was streamed in *(2026-10-11, PLUGIN_GOAL 103: "it looks like a shortcut where there's just all the recursive chunks linked to their root URL node")* | **Confirm** 2026-10-11, a standing check. Live (`confirm.mjs G-173`, url view): each opened page's drawn parents against the trie's, computed in the check from each chunk's own addresses -- RFC 9110 99.9% (1 on the url node, 1 trie root), Dril 100%, Okapi 100%, Monarch_butterfly 99.8% (1 / 1), Persona_(series) 99.8% (545 on the url node = 545 trie roots: no chunk encloses them). Planted `plantSliceContainment`: RFC back to 249 on the url node. Four causes, each measured before it was fixed: (1) `_link_containment` links within ONE write, so a page streamed in drains held almost none (RFC 0/1,172) -- `contains_within` now derives the trie's parent at read time; (2) a page opened in 400-chunk slices hung each slice's orphans off the url node and no pass ever covered the whole page -- one `drawContainment` after the last slice; (3) parents were found by render ROOT, which a long element cut in parts shares -- by TRIE NODE now (the common prefix of a chunk's own addresses, never shallower than its root); (4) a node owned by a chunk never drawn (a duplicate) took the edge, which was then dropped -- derived among the drawn chunks only (`among=`). `tests/test_containment_streamed.py` (3) |
| G-174 | **Hover, glow and picture reveal respond at once** *(2026-10-11, PLUGIN_GOAL 104)* | **Confirm** 2026-10-11. Live (`confirm.mjs G-174`, chunk view, 22,671 nodes, a 120-move sweep): pointer to glow written **p50 9.7 ms, p90 18.5 ms**; planted old path (80 ms throttle, full re-sync, full raycast) p50 14.3, p90 41.9, and its frame per move 110.6 ms against 67.8. Picking still lands: 10 of 10 on-screen nodes hit by a ray at their own screen point. Integrity after 857 in-place mesh moves: 0 slot mismatches, 0 outside a mesh's count, 0 in the wrong mesh. What moved it, each found by a CPU profile, not guessed: three.js's per-frame world-matrix pass over the 22k pick proxies (21.7% of CPU with no input) -- proxies now write their world matrix when they move; its hover raycast over all proxies (~28% while moving) -- gated to the nodes near the pointer's ray by a per-frame stamp; a full re-sync per glow change -- patched in place, revealed pictures MOVED between meshes; the 250 ms safety-net sync (25.7 ms at 22k) -- 2 s on a large graph; the glow throttle 80 -> 16 ms. Measured directly: idle frame p50 26 -> 8.8 ms, moving 58 -> 21 ms. Rendering itself was never it: 4.6 ms a frame with the GPU finished, glass or opaque alike |
| G-175 | **After a plugin reload no code of the closed views keeps running** *(found 2026-10-11 by G-164: the window-held profiler swapped between two builds after a reload)* | **Confirm** 2026-10-11. `graph.ts`/`browser.ts` `onClose` clear every timer they started outside `registerInterval` (the web-follow, the hover-panel sweep, the settle, the placement and offline timers); a timer still firing on a closed view counts itself (`__vertiscopeClosedTicks`). `scripts/check_reload_leak.py` (a script: a reload would end an in-plugin check): a search in flight, the plugin reloaded, 12 s watched -- clean **0** ticks; planted `__vertiscopePlantLeakTimers` 5 |
| G-176 | **The web half of a search is exhaustive: it scrolls and presses "More results" until a round adds no results or the button is gone, and records which ended it** *(2026-10-11, PLUGIN_GOAL 105: "an exhaustive while loop until no deltas or something like the more results button isn't there")* | **Confirm** 2026-10-11 -- the reader: "exhaustive more results works". Built in `browser.ts searchWeb` (no round count; `stopped` is "no delta" or "no more-results button"; per-round `deltas`); planted `plantFixedRounds`; live check `G-176`. |
| G-177 | **While a query stands, what streams into the store re-ranks it as a diff, and the scroll bar shows the brightness gradient** *(2026-10-11, PLUGIN_GOAL 106: "no diff update on retrieval results and effects on the scroll bar")* | **Confirm** 2026-10-12 live (`confirm.mjs G-177`): a stale order (reversed) re-ranked back -- 34 restored, `moved 34`, the reader's scroll kept, 20 gradient stops on the bar; planted `plantNoRerank` never follows the query. `searchfield.ts update()` swaps in the new ranking, keeps the reader's scroll and shows `+a −r ⇅m`; `graph.ts followStore` re-asks every 3 s and at once on `absorb`, resting after 20 unchanged rounds (planted `plantNoRerank`); `barGradient` paints one stop per result as bright as the scene's light (unit tests `searchfield.test.mjs`). Live check owed. |
| G-178 | **Typing ranks the store only; the web half runs on the search button (and Enter)** *(2026-10-11, PLUGIN_GOAL 107)* | **Confirm** 2026-10-12 live (`confirm.mjs G-178`): three typed queries sent **0** to the web, the button **1**; planted `plantWebOnType` sent all 3. `SearchField.button` / `submit()` -> `onSubmit` -> `onWebSearch`; `searchAsk` no longer touches the browser cell. A field the reader types in keeps the keyboard while the cell navigates or clicks for a search (`browser.ts giveBackFocus`, only within 1.5 s of the cell's own act; planted `plantKeepFocus`). Live check owed. |
| G-179 | **A fitted layout is stored on the entities it places; switching to chunk view reads it instead of relaxing again** *(2026-10-11, PLUGIN_GOAL 108: "we should be persisting these layouts to the entities in our database")* | **Confirm** 2026-10-12 probe (chunk view, 22,651 nodes, two switches): shown in **1.34 s / 1.22 s** (it was minutes); the second switch kept **22,598 stored places fixed** and relaxed only the **52** new or moved (IMDb streaming), 5.3-5.8 s time-sliced; 104 places saved through `/drawn`. Before: the relax re-ran over all 22,648 every switch, 39-47 s, re-saving them (planted `plantRelaxAll`). `Chunk.drawn DOUBLE[]` = drawn place + the fit point it was relaxed from (`GraphStore.save_drawn`, POST `/drawn`); `projected_chunk_layout` hands it back only while the fit still puts the chunk there (`drawn_kept` / `drawn_stale`; planted `PLANT_NO_DRAWN`); the pane skips the relax when every node has one and posts what it moved. `tests/test_drawn_places.py` (2). Server side waits on a sidecar restart (WAL 71 MB). |
| G-180 | **Up/Down in the k and n fields step the value, faster the longer the key is held** *(2026-10-11, PLUGIN_GOAL 109)* | **Confirm** 2026-10-12 live probe (k field): a tap steps 1; a 3 s hold steps 1,1,1,1 at first and 24,28,32,37 by its end (the tap is the null arm). `holdStep`: 1 for 400 ms, then doubling every 600 ms to 100 (unit test, monotone); k follows at once, n asks once the keys rest (300 ms). |
| G-181 | **Chunk view draws every sphere at one size; only pictures differ** *(2026-10-11, the reader's "I'd like consistent node sizes if possible" and "why are some of the spheres like GIANT?")* | **Confirm** 2026-10-12 live (chunk view, 22,706 nodes): every non-picture sphere drawn at **0.254** (p10 = p90 = max); planted `plantSizedInChunkView` 2.65-4.64. The one size is derived from the UMAP FIT -- 45% of the median nearest-neighbour distance -- because read from the drawn `val`s it fed on its own layout (places relaxed for orbs 14x too big kept them 14x too big; my regression, the reader: "more jumbling"). Stored places now carry the radius they were relaxed at and are relaxed again when it changes (round 1 re-relaxed 22,706 at the new size, round 2 skipped). Measured live before: the DuckDuckGo page node (605 members) radius 9.43 vs median chunk 0.22; streaming placeholders 2.2 (10x); 1,587 unrevealed favicon chunks 3.24 (14x). `baseLook` sizes pages, streaming nodes and unrevealed pictures as one chunk in chunk view (planted `plantSizedInChunkView`). |
| G-182 | **A page streaming in places each new chunk once and leaves placed ones where they are, with low latency however large it grows** *(2026-10-11, PLUGIN_GOAL 110: "both jumbling and extreme latency on the diff streams")* | **Confirm** 2026-10-12 live (an infinite-scroll page grown 10 -> 100 quotes in the cell; its local fit refit 3 times): each refit MOVED ONLY THE NEW CHUNKS -- 3, 6, 6 moved while 9, 12, 18 stayed put, every chunk whose local place was kept; before the last fix the same growth moved 12, 18, 24 (all). Two causes: the refit replaced every local coordinate (now kept, Procrustes for the new), and the page's anchor and scale are recomputed as it grows (now a chunk whose local place was kept is not re-placed; `stayed` in the local stats; planted `plant_local_jumble`). Latency: chunk view 1.2-1.6 s (G-179). Unattended runs need the browser pane laid out: it was 0 px wide, so the page reported `hidden` and loaded nothing on scroll or "More results" -- and the 0 px was MINE: the reload script blanked the views' leaves and opened new ones, leaving 13 empty leaves splitting the window (found and undone 2026-10-12 06:4x; the script now rebuilds each view in its own leaf). Jumbling: a local refit moved every chunk of the page (DuckDuckGo: 598 moved in one) -- `projector._keep_placed` lays the refit onto the old frame (Procrustes) and keeps placed chunks EXACTLY (`tests/test_local_keep_placed.py`, 4, planted `plant_local_jumble` moves all 40). Latency: one drain 45.8 s end to end, 21.4 s of it transport behind a chunk-view `/layout` of 42-66 s that read every page's anchors under the shared read lock -- trie nodes now kept per page until the page is written (`GraphStore._tnode_memo`, planted `PLANT_NO_TNODE_MEMO`; `test_containment_streamed.py`). Restarted 2026-10-12: a cold chunk-view layout **4.8 s** (rows 40 ms, markdown facts 4.5 s read ONCE at start by the warm-up, edges 238 ms), warm **0.37-0.45 s** with 0 facts read -- it was 30-66 s. Each chunk's title, tokens and picture kept per (cid, chars, write count) (`layout._CHUNK_FACTS`, planted `PLANT_NO_FACT_MEMO`; `test_drawn_places.py`), each page's chunk rows kept with its trie nodes. |
| G-183 | **A field in a panel is typed into in place and reaches the live page through its trie address** *(2026-10-11, PLUGIN_GOAL 111: "I can't enter things in the search bar but I should be able to through the patricia trie")* | **Confirm** 2026-10-12 probe (`scripts/check_panel_typing.py`, DuckDuckGo results in the cell, the act INTERCEPTED so nothing reached the page): clean -- the same field after a capture's redraw, value kept, 1 redraw held, Enter -> one act `type "okapi"` + `enter`, 1 released on leaving; planted `plantRedrawWhileTyping` -- the field replaced, value lost, 0 held, no act. **The last step, granted and seen:** **Confirm** 2026-10-12 live, end to end (sidecar started with `--enact`, the reader's choice): in a 3D panel over DuckDuckGo's results, "giraffe" typed into the panel's copy of the search box and Enter pressed THERE drove the live page in the cell from `?q=okapi` to `?q=giraffe` -- the act adjudicated by `/enact` plan, performed at the stored xpath (type, then the page's own Enter); planted `act-noop`: the page stayed on `?q=okapi` and the panel's readout said so (`scripts/check_panel_enact.py`). Before: the running sidecar is started without `--enact`, so the plan route answers "enact is off" and the act is refused in the panel's readout (asked 2026-10-12, DuckDuckGo's box) -- the flag lets the vault press controls on live pages and is the reader's to grant. A THIRD cause found on the way: the panel's fast snapshot path (from the chunk map, 2026-10-11) passed no address table, so every control in a panel was cloned DISABLED; controls now get their addresses in the background and the panel redraws live (addresses kept 60 s; planted `fast-unaddressed`). The store holds DuckDuckGo's box (`…/form/div/textarea`, a combobox) and the snapshot clones it live; two defects: every capture of a streaming page re-mounted the panel under the reader's fingers -- now held while a field of it has the keyboard (`refreshBillboards` + `onFieldDone`, planted `plantRedrawWhileTyping`); and Enter acted only in an `<input>` -- now in a `<textarea>` too, and it sends the page's own Enter after the typing (`chainFor(..., enter)`, `panelact.test.mjs`). |
| G-184 | **The pointer reveals and glows only within a bounded cylinder about its ray** *(2026-10-11, PLUGIN_GOAL 112: "no matter how far, the images from a far-away url would still reveal")* | **Confirm** 2026-10-12 probe: url view, 329 nodes, the ray aimed at each corner: clean **0 revealed, 0 glowing**; planted `plantUnboundedReveal` 21 revealed, 64 glowing at every corner. Aimed at 8 picture nodes: 8/8 revealed. Radius `revealShare` 0.04 of the cloud's p5-p95 extent (30.5 units here). |
| G-185 | **The idle turn runs with a query standing too** *(2026-10-12: "also not sure if I'm seeing the xyzhsv rotations taking effect yet" -- 0 starts since the reload, gated off by a standing query; "hsv rotation seems pretty slow", "physical rotation could be slower... im feeling dizzy", "hsv rotation could be a lot faster, physical rotation could be somewhat faster")* | **Confirm** 2026-10-12 live (`confirm.mjs G-185`): with a query standing the camera turned 0.158 rad and the hue moved; planted `plantDriftStopsOnSearch` 0. Rates per the reader: hue 0.8 rad/s (the wheel in ~8 s), orbit 0.035 rad/s (~3 min a turn). |
| G-186 | **Every line of a stored chunk carries its OWN address, so the overlay outlines what the line draws** *(2026-10-12: "chunk overlay issue ..." on arXiv's listing -- an outline from entry [8]'s authors into [9]'s title)* | **Confirm** 2026-10-12 (arXiv's listing, live): every worded line holds its own element -- **211/211**, 0 wrong -- and 0 of 27 chunks carry a line anchored twice; on the same store one capture earlier, under the batched delete, 741 stale anchors were computed and NONE removed (25 of 27 chunks doubled, 179/220 lines right). The cause that remained: stale anchors were never deleted at all -- a delete bound by key at both ends (and any UNWIND) plans from the address side, whose adjacency lacks these edges on the working store, so it matched nothing; deleted now forward from the chunk, one statement a row (`a.aid + ''` keeps the planner off the key). A capture skips a chunk only with one anchor per addressed line, so a chunk carrying stale anchors is rewritten and healed. **Correction 2026-10-12:** the store-wide figure reported here ("1,654 chunks over 190 pages, 167,203 stale anchors") was a MEASUREMENT artifact -- `/chunk_stats?url=*` returned url and line_count beside `count(e)`, which aggregated by (url, line_count), pooling every same-length chunk of a page into one row. Counted per chunk (`heal_anchors`, which groups `WITH c`), ONE chunk held stale anchors (9 past its last line), now deleted; arXiv's doubled lines were real and counted per chunk, and healed on recapture. The route now aggregates per chunk. The reader approved a store-wide clean-up on the wrong figure; it ran and removed those 9. Earlier: Two defects found and fixed, each with a planted arm (`tests/test_anchors_by_line.py`, 5): (1) two lines drawing one address kept ONE anchor (the write keyed anchors by address), and the payload zipped the ordered anchors with the lines by POSITION -- from that gap on, every line took its neighbour's address ("Total of 341 entries" keyed to the `h1` reading "Machine Learning"); now anchored per line and read by line index (`GraphStore.anchors_by_line`; planted `PLANT_ONE_ANCHOR_PER_ADDRESS`, `_PLANT_POSITIONAL_ANCHORS`, both together reproduce the shift). (2) A capture skipped any chunk whose MARKDOWN was unchanged, so addresses that moved under unchanged text stayed stale for good; now skipped only when markdown AND the address signature (`Chunk.asig`) match (planted `_PLANT_SKIP_BY_MD`). Ruled out: the sensor's addressing (`--resolvable` on the live listing: 400 sampled, 0 unresolvable, 0 mismatched; the in-page resolver and the document's XPath agree on `dt/a[3..5]`) and the page (`--stability`: floor 0). **Open:** on the live listing in the cell, the stored lines hold their element for 206/209 worded lines on some visits and 179/220 on others ("View HTML" keyed to `dt/a[3]`, the pdf link) -- the live capture itself produces the shift on those visits (28/28 chunks rewritten, then 28/28 skipped as identical); turning drain merging off (`serial-ingest`) did not separate the two states. Probe: `scripts/check_arxiv_keys.py` (first-word holding, planted positional arm). |
| G-187 | **No ring around an open page: opening a page leaves its neighbours at their fit** *(2026-10-12, the reader asked "should the room-pass ring be removed?": "Remove it")* | **Confirm** 2026-10-12 live: the most crowded page opened (144 pages near it) -- clean 0 pushes, 2 neighbours off their fit (coincident pages parted, a separate pass); planted `plantRoomRing` (the push to 2B) 803 pushes, 358 neighbours moved onto the shell. Pages moved before glide home (the restore at the top of the room pass). |
| G-188 | **Nodes a little larger and brighter by default, links a little fainter -- more colour, links still clearly visible** *(2026-10-12, PLUGIN_GOAL 115)* | **Open** -- built and seen in a screenshot (`build_analytics/app_20261012_113017.png`): every node drawn 1.25x (`nodeScale`, pictures included -- a favicon is most of url view's colour), the glass orb's own colour and glow opacity x1.4 (`uBright` / `nodeBright`), links at 0.14 opacity (was 0.25, `linkAlpha`). The reader's eye is the check. |
| G-190 | **The cloud is framed where it is**: the camera aims at the cloud's bounding box, so a cloud whose middle is off the origin -- a fresh store with a page or two -- is framed whole and centred; nothing in the cloud is moved to do it *(2026-10-17, PLUGIN_GOAL 116, read off `c4648c1`)* | **Confirm** 2026-10-17 live (`scripts/check_frame_centre.py`, idle-gated, read between the 400 ms flight and the reframe's disc pass): worst off-centre **0.013** of the pane on clouds shifted (900,300,0) and (-600,0,400), the same as unshifted; fills >= 0.79. Planted `plantOriginFrame`: 0.224 shifted (0.026 unshifted), fills 0.37 |
| G-191 | **A probe attaches to the workspace window**, never the vault picker (also an `app://` page) *(2026-10-17, PLUGIN_GOAL 117)* | **Confirm** 2026-10-17: `Live` and `scripts/live_probe.py` both on `app://obsidian.md/index.html` with webview guests listed first |
| G-192 | **The app is brought up, inspected and reloaded through MCP tools that cannot damage the store or the reader's state** *(2026-10-17, PLUGIN_GOAL 119)* | **Confirm** 2026-10-17, each exercised against the running app (`2d34b06`): `sidecar_status` healthy in 3.1 s (was "timed out" at 2 s), with the WAL size; `sidecar_start` leaves a running sidecar (pid 28140) unless asked, and start/stop refuse a WAL over 8 MB; `obsidian_launch` keeps `data.json` and survives the repo-as-vault; `obsidian_close` graceful first; `plugin_reload` idle-gated, enable fired not awaited, both views rebuilt in their leaves; `graph_reframe` reads the settled camera; `live_health` says `layout_ready` |
| G-193 | **The phased projection pipeline, first priority a COMPLETE projection of the page**: every vectorised chunk of the url projected, debounced to the measured latency of that url's local fit update; then local and global updates, each debounced by its own measured cost *(2026-10-17, PLUGIN_GOAL 120)* | *Addendum X* | **Open** |
| G-194 | **A refit does not snap the camera**: the new url-node coordinates are registered onto the previous (scale-aware ICP / similarity Procrustes over url nodes) and the camera keeps its pose in that registered frame *(2026-10-17, PLUGIN_GOAL 121)* | *Addendum X* | **Confirm** 2026-10-17 live (`scripts/check_refit_pose.py`): the camera put where no reframe would, then the pane redrawn as a new fit epoch redraws it -- the 122 url nodes in view moved **1 px** on screen (p50 and p90), registered over 710 matched pages; planted `plantSnapOnRefit` (the reframe, as before) moved them p50 352 / p90 513 px. The registration (`similarityFit`, Horn's quaternion + Umeyama scale, matched by url so one closed-form solve) is unit-tested on a real rotation, scale and shift (`obsidian-plugin/tests/similarity.test.mjs`, 3 tests). Not yet seen across a REAL refit of the corpus (epoch change), whose frame actually differs |
| G-195 | **Hovering a browser chunk box keeps driving the 3D billboards with good latency** (kept as is; guarded) *(2026-10-17, PLUGIN_GOAL 122)* | *Addendum X* | **Confirm** 2026-10-19 live, guarded (`confirm.mjs` G-195): on a stored page (Wikipedia Trie), real pointer moves onto another chunk box -> that chunk's panel open WITH TEXT in the graph: 9 of 10 opened, **p50 191 ms, p90 399 ms** (bar p50 < 250, p90 < 600); planted `poll-hover` (the hover found by the poll) -> 0 registered in 2.5 s. Two changes behind the margin the same day: the shown url kept from the webview's commits instead of a synchronous main-process ask per force tick (sync asks 1,891 -> 43 per 45 s on the Julia forum, frame p95 102 -> 32 ms), and a chunk cloud re-telescoped only when its inputs move. |
| G-196 | **A toggle: billboards open on fly-to, or only on a right-click** *(2026-10-17, PLUGIN_GOAL 123)* | *Addendum X* | **Confirm** 2026-10-17 live (`scripts/check_addendum_x_quick.py`): right-click mode -- a hover opens no panel (1 skipped), a right-click on a chunk node opens it; fly-to mode (null arm) -- the hover opens it, as before. Bar button `panels: fly-to / right-click`, kept per viewer |
| G-197 | **A chunk panel shows every image its chunk holds** (recipe sites missing some the store already has); a development MCP tool checks a rendered panel's content-completeness against the streamed chunk *(2026-10-17, PLUGIN_GOAL 124)* | *Addendum X* | **Confirm** 2026-10-19 live (`confirm.mjs` G-197, fixture `tests/fixtures/recipe_images.html` in the plugin's browser cell, read back through the panel the reader opens): clean -- 0 namespace pictures, both lazy photographs drawn (`data-lazy-src`, `data-src`), **0 stand-ins**, the drawing data-url SVG kept, 3 of 3 captions; the panel 4 rendered, 4 loaded, 0 broken, 0 missing. Planted (`xmlnsurl` + `POST /plant placeholder-target`) -> 1 namespace picture, the WP Rocket photo not drawn, 1 stand-in, 3 broken. Three causes: the sensor's attribute scan denied `xmlns` but not `xmlns:xlink` (`content_tagger` denied it all along); `address._URL_ATTRS` and markdown's `_TARGET_ACCESSORS` lacked the sensor's lazy attributes, so `data-lazy-src` was held and never read as a url; and an element's first url named it, stand-in or not (`_is_placeholder`). Real page (`scripts/check_panel_images.py`, copykat Crumbl sugar cookies re-captured live): lazy stand-ins drawn **30 -> 0**, namespace pictures 27 -> 0; its three richest chunks' panels 22 of 22 pictures loaded, 0 broken, 0 stand-ins (they were 22 blank). The tool: `panelCompleteness` / MCP `panel_completeness` (pictures rendered, loaded, broken, missing, stand-ins, text cover; the page form read inside its snapshot iframe). Screenshot `build_analytics/g197_panel_photos.png`. |
| G-198 | **Grey nodes show their markdown at once; the shadow-DOM panel streams in after; vectorisation and projection come last** -- rendering never waits on them *(2026-10-17, PLUGIN_GOAL 125)* | *Addendum X* | **Partly** 2026-10-17: grey nodes keep their streamed lines (`ForceTree.linesOf`) and a hover opens a provisional markdown panel at once -- 77-116 ms on archive.org (planted `no-force-panel`). The shadow-DOM form streaming in after, and vectorisation last, not yet measured as a pipeline |
| G-199 | **Bluesky: scanned nodes persist, a scanned page's url node unfolds/folds on click, embedded media shows** *(2026-10-17, PLUGIN_GOAL 126)* | *Addendum X* | **Confirm** 2026-10-17 live (`scripts/check_bluesky.py`, a public profile scrolled 40 steps): (1) scanned nodes persist -- the feed recycles like archive.org's list; retained 39-56 chunks beyond the 222-234 live ones (G-216's union). (2) the url node: a fold HID the page's streamed chunks by deleting their specs, so an unfold brought back only the store's (339 grey folded, 1 chunk back); now a fold hides and an unfold redraws them -- 138 grey + 74 stored back (planted `plantFoldForgets`). (3) media: grey panels drew a picture's url as text (0 images); a line an `<img>` draws is now `![](src)` -- grey panels 2/2, 2/2, 1/1 images loaded (planted `ForceTree.plantImgAsText`); stored panels 2/2 and 11/11 |
| G-200 | **One set of back/forward buttons in the browser cell** *(2026-10-17, PLUGIN_GOAL 127)* | *Addendum X* | **Confirm** 2026-10-17 live (`scripts/check_addendum_x_quick.py`): Obsidian's header arrows hidden on the browser view (computed `display: none`), still shown on the graph view (null arm); the cell's own two arrows drive the page |
| G-201 | **uBlock Origin in the browser cell** *(2026-10-17, PLUGIN_GOAL 128)* | *Addendum X* | **Partly** 2026-10-17 live (`scripts/check_adblock.py`, a recipe page, as the reader browses): uBlock Origin 1.75.0 (official chromium build, the reader's go-ahead) loaded into the browser cell's own session `persist:vertiscope` -- ad/tracking requests that reached the network **12 with it vs 54 without** (78% fewer; 139 vs 286 requests in all). Loaded as shipped it blocked NOTHING (60 vs 51): Electron lacks `chrome.browserAction`, uBlock threw on it at startup and never registered its filter; a compatibility shim (`obsidian-plugin/src/ublockshim.ts`, written into the extension by the plugin) stands in for the five APIs Electron lacks and blocking does not use. 12 header-bidding requests still pass -- likely request types Electron's extension webRequest does not surface; unproven |
| G-202 | **Natural text typed in the url bar searches DuckDuckGo** *(2026-10-17, PLUGIN_GOAL 129)* | *Addendum X* | **Confirm** 2026-10-17 live (`scripts/check_addendum_x_quick.py`, `obsidian-plugin/tests/address.test.mjs` 3 tests): "patricia trie radix" + Enter -> DuckDuckGo results; `en.wikipedia.org/wiki/Radix_tree` -> the page; planted `address-literal` -> a broken host. No scroll, no More-results run |
| G-203 | **Fast multi-page navigation: grey nodes streamed seconds ago on one page persist while the next page streams** *(2026-10-17, PLUGIN_GOAL 130)* | *Addendum X* | **Confirm** 2026-10-18 live (`scripts/check_open_rows.py`, plugin reloaded first): B-tree streamed **147** grey chunk nodes, the reader moved to Heap, and 1.2 s later all **147** were still drawn; planted `drop-on-leave` -> **0**. |
| G-204 | **No collision drift: positions stay the UMAP's, scaled adaptively** -- about each url node's chunk centroid so the minimum chunk separation is twice the chunk diameter (expand or contract), then over the url nodes about a browser centroid node with their own constants; url nodes 2-3x a chunk's size *(2026-10-17, PLUGIN_GOAL 131)* | *Addendum X* | **Open** |
| G-205 | **The browser centroid node: a gauge-point placeholder** for a future one-tool MCP graph-RAG surface (web / domain / in-page scopes; chunks as atomic interactive units; up/down distinct from back/forward) -- designed with the reader BEFORE it is built *(2026-10-17, PLUGIN_GOAL 132)* | *Addendum X* | **Open** |
| G-206 | **At full view nodes draw smaller; full size zoomed in** (the reader's answer for G-94's burial: "Smaller at full view") *(2026-10-17, PLUGIN_GOAL 133)* | *Addendum X* | **Confirm** 2026-10-17 live (`scripts/check_addendum_x_quick.py`): at full view the shader draws nodes at 0.5x; buried discs AS DRAWN 17 of 747 (2.3%) against 67 with `plantNoZoomScale`; at a fifth of the full-view distance the factor is 1 (null arm). Display only (a `uZoom` uniform): layout, colliders and stored places do not change with zoom; pick proxies follow. `seenLayout` now measures as drawn (it left out `nodeScale`) |
| G-207 | **Chunk nodes glow: a liminal, diffuse, additive glow in each node's colour, so a node too small to see as a sphere still reads as a point of light** *(2026-10-17, PLUGIN_GOAL 134)* | *Addendum X* | **Confirm** 2026-10-17 live (`scripts/check_chunk_glow.py`, screenshots `build_analytics/glow_on.png` / `glow_off.png`): at full view every chunk orb in the pane is a visible point of light, 40/40 (peak luminance p50 227), against 14/41 with `plantNoHalo` (p50 48). A soft additive halo from the glass mesh's own instance buffers (no sync of its own), at least 12 px on screen, mostly diffuse `(1-r^2)^2` with a 0.15 core; colour added, alpha untouched (the first cut wrote alpha and drew dark rings on the transparent canvas, which the reader saw). Background opaque black (the reader: "ensure the background is also black and not grey"; planted `plantGreyBackground`). Dense clusters add up to white -- reported, for the reader's eye |
| G-208 | **A hovered node presents its picture in chunk view, at a readable size, covering the glow around and in front of it** *(2026-10-17, PLUGIN_GOAL 135)* | *Addendum X* | **Partly** 2026-10-17 (`scripts/check_hover_picture.py`, chunk view): a revealed picture was drawn at the one orb size, ~1 px -- now presented between 12 and 64 px of radius on screen (loaded ones measured 12, 12, 12 px); the glow is drawn FIRST so a presented picture covers it; pictures are exempt from the full-view shrink. Still short: the atlas loads 4 at a time and only 3-5 of 6 hovered pictures had landed within 8 s, and until one lands the node is a tiny pending orb. Picture latency (`scripts/check_picture_latency.py`): after a 40-place sweep leaving a 226-picture backlog, a hovered picture landed in 0.55 / 1.0 / 1.7 s with decodes newest-first and a re-asked picture lifted to the top; the first-in-first-out arm ran on a warm atlas (13-31 queued) and is NOT comparable -- the ordering's benefit is unproven. Planted arm (`plantTinyReveal`) not yet run to completion -- the reader was active each time |
| G-209 | **A search's rendering glows as the default view does** *(2026-10-17, PLUGIN_GOAL 136)* | *Addendum X* | **Confirm** 2026-10-18 live (`scripts/check_open_rows.py`): query taken from the Trie article's own chunks, n=120, k=30 -> 30 lit, 5 of them chunk orbs, **5 of 5 drawn as glowing glass** (`lookOf`: glass, translucent, alpha 1.42); planted `plantOpaqueResults` -> **0 glass, 5 opaque** (alpha 1). The other 25 are page favicons, which stay pictures with a glow either way, so they cannot discriminate and are not counted. Screenshot `build_analytics/g209_search_lit.png`. |
| G-210 | **Tiered retrieval: url nodes ranked first, then each page's chunks re-ranked into the readout, page by page** *(2026-10-17, PLUGIN_GOAL 137)* | *Addendum X* | **Partly** 2026-10-17 live: tier 1 `/search_pages` (url centroids from the index, alignment-planted test `tests/test_search_pages.py`) answers in ~1 s; tier 2 is the page-scoped ranking, 1.2-3 s a page, three pages in flight, the readout re-ranked after every page (`SearchField.tiered`, planted `plantSingleTier`). Search itself: lexical 26-33 ms (tf-idf cached per mutation; was 750-930 every query), semantic ~55 ms, shape 2-46 ms (the ranking's reads reused; was 1.2-2.2 s), duplicates collapsed by content hashes built with the index (no read per candidate); a whole search 0.94-1.51 s warm. What is left is the ONE read of the kept hits, 0.6-1.4 s: random reads on the 63 GB store cost 100-300 ms each -- the store's size is the next lever, not the ranking |
| G-211 | **The k/n fields: k shown (numerator) of n retrieved (denominator), edits take effect, no 50 cap** *(2026-10-17, PLUGIN_GOAL 138)* | *Addendum X* | **Confirm** 2026-10-18 live (`scripts/check_open_rows.py`): n field set to 120 -> **120 retrieved** of 56,780 matching (over the old 50 cap); k field 30 -> **30 shown and lit**; both fields read back the values set. |
| G-212 | **The 3D graph follows the most recent re-ranked set, tier by tier** *(2026-10-17, PLUGIN_GOAL 139)* | *Addendum X* | **Partly** 2026-10-17: the 3D view follows each tier's re-ranked set (every tier-2 page re-ranks the retrieved set and calls the same show path as a scroll); not yet scored live as a streamed sequence |
| G-213 | **Nodes in front of a presented picture are drawn dark, orb and glow** *(2026-10-17, PLUGIN_GOAL 140)* | *Addendum X* | **Partly** 2026-10-17 (`scripts/check_hover_picture.py`): every node in the reveal cylinder nearer the camera than the presented picture is drawn dark, orb and glow (alpha 0.12): 40/40, 40/40, 30/30, 5/5 in front were dark across the hovered pictures. Planted `plantNoFrontDim` arm not yet run to completion (reader active) |
| G-214 | **The idle turn starts after a few seconds and does not stall: only the reader stops it** *(2026-10-17, PLUGIN_GOAL 141)* | *Addendum X* | **Confirm** 2026-10-17 live (`scripts/check_idle_turn.py`, chunk view, 90 s unattended): the turn on for 90/90 s, 0 stops, 3.17 rad turned, 0 reader stamps from any source. Built: 4 s of quiet, not 20; a page hover counts as the reader only when the page did not scroll or mutate in the last 400 ms (planted `hover-always-reader`); every stamp tallied by source in `__vertiscopeReaderBy` |
| G-215 | **The panels toggle governs the browser hover**: right-click mode, a hovered chunk box flies without a panel; a right-click on it opens the panel *(2026-10-17, PLUGIN_GOAL 143)* | *Addendum X* | **Partly** 2026-10-17 live: the browser cell's right-click now reaches the graph (`onRightChunk` -> `rightPanel`) -- through the webview's own `context-menu` handler, right-click mode opened the hovered chunk's panel (right_opened 1), fly-to mode did not (0); only a 3D node's right-click was wired before, which is why the reader saw it do nothing (822 hovers correctly skipped, 0 right-click opens). On archive.org the hover itself opened nothing for grey chunks (54 `empty_skipped`) until G-198 gave them their streamed text. Awaits the reader's eye |
| G-216 | **Constant in-place mutation (archive.org scrolling) streams as diffs of a stable set of unique chunks**: rewrites update their chunk, no leaked duplicates, nothing waits on a slower stage, the diff stream never stalls or floods *(2026-10-17, PLUGIN_GOAL 144)* | *Addendum X* | **Confirm** 2026-10-17 live (`scripts/check_archive_stream.py`, archive.org search, 15 s of rapid scrolling): ONE force tree for the document (was 7: the list rewrites its url `&page=2..8` as it scrolls and each was taken for a new page), 6/6 rewrites kept as the same document (a url rewritten while the page scrolls is the same document; without a scroll, half the live chunks removed decides a new page -- an app's route change), 60 drains decoded, 94 live chunks at the end. A page begun inside a running document adopts its stream (`ForceTree.adopt`; a fresh tree decoded none of its drains -- `tests/forcetree_adopt.test.mjs`, null arm). Planted `inpage-is-new-page`: 7 trees, backlog 135. **Union of what the visit showed** (the reader: "archive still not registering correctly"): the list recycles as it scrolls -- 584-881 chunks removed and 409-517 elements reused in 15 s. The force tree now RETAINS removed chunks and gives a reused element's new content its own node: **322 grey nodes drawn after the scroll vs 41** with `plantDropRemoved` (329 retained; 580 revived when shown again, one node per content). Store side built, not yet live (needs the sidecar restart): in-session drop-outs kept, only renamed chunks retire; the settle retires none of what the visit kept (`_PLANT_RETIRE_IN_SESSION`). Cost: a drain that removes what a queued job carries is no longer merged into it, so the capture backlog peaks at 42 (was 3) -- no content lost in exchange |
| G-217 | **Chunk streams persist at any interaction speed; hover-to-panel latency measured and brought down per phase** *(2026-10-17, PLUGIN_GOAL 145)* | *Addendum X* | **Partly** 2026-10-17: the capture backlog stays a job per page -- drains merged at ENQUEUE, replayed in order (`mergePayloads`: a removed-then-re-added chunk was dropped; `tests/merge_payloads.test.mjs`, planted fails): max 3-5 jobs under archive.org scrolling vs 71 with `no-enqueue-merge`, through a 195 s checkpoint that holds the store lock. Hover to a grey chunk's panel: 77-116 ms (it opened nothing before: the panel had no text until the store held the chunk). Still slow: a STORED chunk's hover 84-888 ms (sidecar fetch), captures p90 13 s under lock waits; the 1-3 min checkpoints on a 63 GB store are untouched |
| G-218 | **The store is compact: efficient storage, measured against what it holds; performance optimised throughout; no write lost in the switch, the original kept** *(2026-10-17, PLUGIN_GOAL 146)* | *Addendum X* | **Confirm** 2026-10-18 live (`scripts/compact_store.py`): the store rebuilt by kuzu's own EXPORT/IMPORT round trip -- **67.77 GB -> 1.40 GB**, every table's count identical (Page 922, Chunk 74,554, Address 1,791,913, Anchors 709,699, Contains 63,020, HasChunk 74,902, LinksTo 603, Layout 25), the export 0.37 GB; dropped only 2,548 `Anchors` and 10 `Contains` edges whose source chunk had been DELETED (an untyped `count(r)` counted them; a typed match with a key on each endpoint does not -- the first two runs aborted on exactly that and swapped nothing). Sidecar down ~30 s (stopped gracefully: supervisor first, `/shutdown` under the work lock; restarted with its own command line); the original kept as `graph.kuzu.orig-20261018-011143` for the reader to remove. Measured after: `select` 23-94 ms (was 0.6-1.4 s quiet, up to 140 s under load), capture lock waits max 2.3-2.7 s, median 0 (were 44-90 s). The plugin now waits out an unreachable sidecar however long it takes (a fetch failure had read as a refusal and DROPPED the drain); a refused one keeps 15 minutes. **2026-10-18 05:42, a second rebuild after a store defect**: from 04:08 the sidecar died natively in kuzu ~50 times in an hour (`crashes.log`: 0xC0000005 on the anchors/address writes; three write-ahead logs set aside; the supervisor restarting into the same replayed capture each time), so the store took no writes for ~1.5 h. Reproduced OFFLINE on a copy: inserting NEW `Address` rows segfaulted for some keys -- a plain `UNWIND ... CREATE (:Address)` of 400 rows, no edges -- while edges to existing addresses always passed: the Address primary-key index was damaged (**cause found later, 06:23-12:50**: the loop came back 15 minutes after the rebuild, and with every statement of the replayed capture dumped (`VERTISCOPE_DUMP_ROWS=1`) and replayed in a server on a copy: `COPY Anchors FROM df` -- 4d50da4's bulk anchor path -- was REFUSED by kuzu, "Buffer manager exception: Unable to allocate memory! The buffer pool is full", 41 rows on a 5.1 GB store with a 2 GiB pool, because appending to the populated rel table needs memory that grows with the table; and reads in flight on the second connection at that moment (`_warm_index`, `_warm_containment`) segfaulted. Earlier I had cleared COPY on a wrong reading; it was the trigger. Fixed: COPY for anchors is opt-in (`VERTISCOPE_ANCHOR_COPY=1`); a buffer-pool refusal poisons the store -- no further statement runs on it -- and `_poison_watch` restarts the process (75). `tests/test_store_poison.py` (4: poisoned vs planted `VERTISCOPE_PLANT_NO_POISON`, which runs the next statement). On a copy with the plugin's real queued captures: COPY on -> refused -> ACCESS VIOLATION in 35 s; default -> 366 statements, 234 anchor writes, no refusal, no crash, stopped gracefully). Remedy proven on the copy first: EXPORT/IMPORT, then the same 400-key insert, the 400-row fused statement and a 400-row COPY all pass where the original crashed. Applied with `compact_store.py`: 5.42 GB -> 1.44 GB, every table identical (Address 2,023,088, Anchors 864,561, Chunk 83,974, Contains 72,282, HasChunk 84,322, Page 1,056), 5 orphan Anchors dropped and reported; original kept as `graph.kuzu.orig-20261018-054234`. **And the markdown, a third time**: `integrity.log` shows chunk markdown EMPTY for 180 chunks at the 2026-10-17 22:36 start and **67,040 of 74,401** at the 00:44 start -- lost across that restart with nothing flagged, because the record's baseline was in memory and every loss so far (09-23, 10-07, 10-18) happened across a restart; every annas-archive homepage chunk drew an empty panel. Refilled by `POST /restore_markdown` from the JSONL checkpoint, by cid, only where empty: **66,449 restored in 32 s, 591 not in any checkpoint** (the 06:08 start record: `empty_md` 591). Now the record reads the previous PROCESS's last line from disk, and a rise of >= 500 empty heals at once (restore, then the lexical rows re-derived): `tests/test_integrity_log.py` -- a loss across a restart flagged and healed to 0; planted `VERTISCOPE_PLANT_NO_MD_HEAL` flagged and left empty |
| G-219 | **A hover resolves only to a chunk of the page shown -- never another page's (edge case: navigating while the new page loads)** *(2026-10-17, PLUGIN_GOAL 147)* | *Addendum X* | **Confirm** 2026-10-17 live (`scripts/check_cross_page_hover.py`, archive.org <-> TMDB both ways, the real pointer moving through each load; judged from the webview's own commit, not the app's session): **0 cross-page targets or panels over 72 hovers / 36 panels** vs **100 over 120** with the old behaviour planted (`session-at-load` + `cross-page-hover`) -- the reader's TMDB-hover-opens-archive-chunk reproduced and gone. Cause: the session moved only at load end (TMDB loads ~15 s) while the new page's sensor already pushed hovers, and a hover's sensor id was looked up in the OLD page's tree. Now the session follows the document at commit (`did-navigate`), a hover from a page not shown is refused, a force id resolves only within its own page, and every page check (snapshots, page form, corner box, hover map) asks `currentPage()` -- the archive.org list's url rewrites resolve to their document |
| G-220 | **A hovered archive.org tile opens its OWN chunk** -- its title, count and picture -- not a neighbour's, not the grid, not a far container; it stays right while the virtual list rewrites tiles in place *(2026-10-17, PLUGIN_GOAL 148, 149)* | *Addendum X* | **Confirm.** Live 2026-10-18 after G-244's list rule (`scripts/check_archive_hover.py`, the REAL pointer on each tile, two passes): homepage **12 of 12** hovers open the tile's own chunk (planted 3 of 12); the radio-drama SEARCH page **7 of 8** (planted 2 of 8) -- the one miss an empty panel on the first pass while the fresh page was still arriving, right on the second. Earlier record: 2026-10-18 live (`scripts/check_archive_hover.py`, the real pointer over tiles inside the shadow roots, scored by the `/details/` id of the tile UNDER the pointer at judgement time, not the listed one -- the list re-lays out between). **Homepage: 6/6, 12/12, 12/12 clean** across scroll depths 14/24/40, vs **0/6 and 8/12** with the id collision alone planted (`--only-gen`) and 0/6 with every old behaviour planted. Four causes, each with its own planted arm and unit test (`tests/forcetree_adopt.test.mjs`, 15 pass): (1) a STORED chunk is a recording of what each address held at capture, and a virtual list reuses addresses -- every tile opened its slot's former occupant; the live unit wins where its lines are not all in the stored unit (`plantTrustStored`); (2) a REMOVED element whose sensor id came back took its kept version's node id, and lookups read the kept version first ("Archive Team: US Government" opened "Medical Heritage Library"); the generation now advances on every retention (`plantGenOnRewriteOnly`); (3) the sensor spelled a hover's address by the LIGHT DOM while the fold addresses a slotted element through the slot that draws it -- archive.org's search tiles sit in light children of `tab-manager`, so no hover there named an address the trie held; `hoverAddress` now walks `assignedSlot` (`tests/test_composed_tree.py::test_a_hover_names_the_address_the_fold_gave` + its planted twin, live; `plants.lightpath`; search page 4/6 clean vs **0/6** planted); (4) two live chunks at one address resolve to the sensor's own hovered chunk, then the newest, and an item with no lines yet has no unit rather than its list's (`plantMostLines`, `plantClimbPastList`). **Still missing: the search page, 4/6** -- one tile (`ae7k5...`, Boxcars711) shows `pacifica_radio_archives-WZ0288`'s lines in both arms, cause not yet found |
| G-221 | **Going back to a scanned page resumes from what was kept**: the visit is diffed against the page's chunks, not rescanned and re-sent whole *(2026-10-17, PLUGIN_GOAL 150)* | *Addendum X* | **Partly** 2026-10-18, two contributors found and fixed, the revisit itself not yet measured: (1) a refused capture ("dictionary incomplete") resynced the sensor of whatever page was SHOWN -- a full drain of every chunk, captured again -- even when the refusal was a late drain of a page already left; now only a refusal for the shown document resyncs (`onRefused`, planted `resync-any-refusal`; the probe `scripts/check_refusal_resync.py` did not reproduce a refusal in either arm, so this is unmeasured live); (2) a closed browser view kept pumping its capture queue after a plugin reload, beside the new view's (`scripts/check_close_pump.py`: closed view **2 sends (its settles), 17 drains abandoned** vs planted `pump-after-close` **5 sent and 7 still queued** a minute later). The sidecar logged 83 refusals in ten minutes at 00:36, in bursts of several a second for pages from before a reload -- consistent with (2), not reproduced since. Open: diffing a revisited page against what was kept instead of re-sending it whole **Measured 2026-10-18** (`scripts/check_revisit.py`, Hash_table with a fresh query per arm, the first visit STORED -- 155-162 chunks -- before leaving): the store side is a diff -- going back 0-1 captures, 84-146 chunks unchanged-skipped. The 3D side: (3) the chunk map of the last 8 pages is kept (`ChunkMap` cache, planted `no-map-cache`; `tests/chunkmap_cache.test.mjs`) so a page gone back to has its map before the store answers. Going back by hand: **0** grey nodes at 1.5-12 s, twice. In the probe's 20 s window the clean arm still showed 77-79 grey at some instant vs 83-200 planted -- transient, not yet explained (content that changed on reload is the candidate) |
| G-222 | **A horizontal strip of results above the search bar**, scroll-linked to the bar below: same scale, results highlighted with their nodes, hovering one flies to its node *(2026-10-17, PLUGIN_GOAL 151)* | *Addendum X* | **Partly** 2026-10-18 live (`scripts/check_strip_and_zoom.py`): the strip holds one item per result in the slider's window (12 of 12), each named as its node and lit as its node (`stripLight` = the node's `brightness`; `tests/searchfield.test.mjs`); moving the BAR to 50% / 100% moved the strip to **0.501 / 1.0** (and 0.5 / 1.0 on a second run) of its span vs planted `plantStripUnlinked` **1.0 / 1.0** and **0 / 0**; scrolling the strip moves the bar back. A hover on an item takes the search's own resolution: its chunk if drawn, else its page -- flown to -- and opens the CHUNK's panel (seen: the panel id is the hit's cid). Not yet seen: a flight between DISTINCT nodes from the strip -- in url view every candidate query's top 12 sat on one page, so each hover resolved to the node the camera was already on. One later run did not follow in either arm (frames likely throttled with the window behind); to re-check in front |
| G-223 | **Retrieval latency measured by phase and brought down** (slow again) *(2026-10-17, PLUGIN_GOAL 152)* | *Addendum X* | **Partly** 2026-10-18 live (`scripts/check_search_under_load.py`: three searches through the field while fast archive.org visits stream captures; clean vs planted `VERTISCOPE_PLANT_INDEX_REBUILD=1`, each after a graceful restart): first result **cowboy 2.0 / 2.4 s, radio drama 0.9 / 0.9 s, patricia trie 7.1 / 6.6 s** vs planted **7.1, 15.3, 50.4 s**; was 73 s on the 67.8 GB store and 10-14 s on the compact store before the index fix. Causes, each fixed: the store (G-218); every capture threw the search index away and the next search rebuilt it from all 74k chunks (2-9 s wall per search while a page streamed) -- the index now takes each write's DELTA (`ThreeFormIndex.apply_delta`, O(delta); `tests/test_index_delta.py`, incl. a freed row reused in the same delta) and rebuilds in full off the request path after 30 s of quiet. Still open: the third search's 6.6-7 s coincides with the projector's training (35-46 s a run) and the quiet rebuild; to measure and take off the request threads; 2026-10-18 later: as a DISTRIBUTION (`scripts/check_search_latency.py`, fresh queries every 1.5 s for 90 s while archive.org streams, after warmup) **p50 991 ms, p90 4.4 s, max 5.6 s**, 9% of wall time waiting; one request DIED there -- a search built its tf-idf while a capture added vocabulary ("inconsistent shapes"): the lexical matrix now has one lock for its counts and everything derived from them (`tests/test_freq_lock.py`: concurrent add + search, 0 errors locked; the planted unlocked arm reproduces the race). Background training now steps aside for a search between optimiser steps (`pumap.TRAIN_YIELD`; planted `VERTISCOPE_PLANT_NO_TRAIN_YIELD=1`) -- no training ran in the measured window, so its effect is unmeasured |
| G-224 | **Click-to-panel latency measured and brought down** *(2026-10-17, PLUGIN_GOAL 153)* | *Addendum X* | **Partly** 2026-10-18 measured live (`scripts/check_click_panel.py`: a page unfolded as a click does, six of its chunks opened through the click's own call, timed until the chunk's OWN first line is in the panel -- the address header is there at once and is not the content): **p50 74 ms, p90 112 ms** cold, warm alike; the payload fetch 35-151 ms of it, the rest the render. On the rebuilt store (G-218); no before arm on this instrument |
| G-225 | **k/n bounded by the number matching, not a fixed 2000** *(2026-10-17, PLUGIN_GOAL 154)* | *Addendum X* | **Confirm** 2026-10-18 live (`scripts/check_kn_bounds.py`, the field driven in the running app, then restored): the bound is the CORPUS's match count, computed by tier 1 in the ranking's own pass with no chunk read (`count_only`; `tests/test_search_pages.py`) -- "the" asked 3000 / 5000 shows **3000 / 5000 of 31,412 matching and retrieves 5,000** (2.8 s, first page 110 ms); planted (fixed 2000 cap + the per-page sum + a page count from n) shows **2000 / 2000 over 4,434 and retrieves 2,277**; "cowboy" 2000 / 2000 retrieves **1,712** of 2,040 matching vs **165** planted. Three causes under the 2000: the fixed cap (`fieldBounds`); `matching` summed over the top pages only; and tier 1 ranking pages by semantic centroid -- pages near in meaning that hold no match the product admits ("cowboy": 9 of 12 pages answered 0) -- now ranked by their best fused chunk score with each page's own count, pages taken until the counts cover n (`search_pages_matching`, planted `centroid=1`, `scripts/check_tier_pages.py`). A fourth cause found on the way: duplicates were keyed on the STORED markdown, empty for 67,040 of 70,083 chunks (the store's earlier loss), so all of them were one duplicate and RFC 9110's 457 matches returned **1**; keyed on the index's token rows they return **387** (`_row_digest`, planted `_PLANT_MD_DIGEST`) |
| G-226 | **A scan registers its chunks oldest-first, and vectorises, projects and fits in batches as it goes** -- nothing waits for the end *(2026-10-17, PLUGIN_GOAL 155)* | *Addendum X* | **Partly** 2026-10-18, two changes, live A/B queued: (1) the capture queue serves the OLDEST job first -- the page on screen went first and a page scrolled past or left waited behind it (planted `current-page-first`); `scripts/check_oldest_first.py` was CONFOUNDED (the queue never drained between arms: 16 -> 59 jobs left) and is not evidence. (2) The cause of that backlog, from the sidecar's own profile over ten minutes of archive.org scrolling: anchor writes took **201 s of 321 s** of store time (8-12 ms an anchor) -- the in-place tile rewrites send most anchors down the two-lookup CREATE (address current, edge new), which costs **23 ms a row** on the rebuilt store vs **0.37 ms** for kuzu's bulk `COPY Anchors FROM` a frame (1,000 edges: 23.0 s vs 0.37 s, measured on a copy). Edges now go by COPY, falling back to the statement when an endpoint is gone (`tests/test_anchor_copy.py`: same edges both ways, no partial COPY; planted `VERTISCOPE_PLANT_ANCHOR_MATCH=1`). `scripts/check_capture_throughput.py` (both arms, restart + warmup + drained queue first) is queued for the reader's idle |
| G-227 | **Zoom stays smooth while a stream flows**: the stream's work is throttled under a zoom *(2026-10-17, PLUGIN_GOAL 156)* | *Addendum X* | **Confirm** 2026-10-18 live (`scripts/check_zoom_stream.py`: a 2 s wheel zoom on the graph canvas while archive.org streams drains; two runs each arm): frame interval **p95 18 / 18 ms, 6 / 6 frames over 50 ms** vs planted `plantNoDeltaDefer` **p95 395 / 415 ms, 32 / 22 frames over 50 ms**. A drain's delta is held while the READER moves the camera (wheel or drag on the canvas -- not the idle turn) and applied in one batch when it rests, held at most 1.5 s so the stream never waits on a zoom that does not end |
| G-228 | **Node sizes explained and checked**: why some orbs are huge in front of small results, and whether the scaling serves them *(2026-10-17, PLUGIN_GOAL 157)* | *Addendum X* | **Partly** 2026-10-18, explained by measurement (`scripts/check_node_sizes.py`, the app's own `drawnRadiusOf` and `baseLook`, read-only): in url view a page orb is sized by its member count (`val` = sqrt(members); DuckDuckGo "cowboy" with 2,153 chunks draws at radius **3.8**, the largest pages at **6.6**), while a result is drawn at the scene's MEDIAN size (**~2.1**), so a large result page is about 1.8-3x a result. And of 27 results only 3 resolved to drawn nodes, all page orbs: the chunks themselves were not drawn in url view. Nothing dims or shrinks the non-result pages in front of results during a search (G-213 does it only in front of a presented picture). Proposed, not built: during a search, non-result orbs no larger than the result size, and dimmed in front of results |
| G-229 | **The reader's zoom persists over later hovers** of the search-scroll-scan *(2026-10-17, PLUGIN_GOAL 158)* | *Addendum X* | **Confirm** 2026-10-18 live (`scripts/check_strip_and_zoom.py`): the camera pulled back to 4x (a zoom-out), then four flights through the hover path to small nodes -- the distance after each **1.00 / 1.00 / 1.00 / 1.00** of the zoomed-out one vs planted `plantClampKeptZoom` **0.08** each. Cause: the speck clamp (a target kept at least `minTargetPx` on screen) ran on every flight, so each later hover pulled a zoomed-out camera back in; it now applies only to a flight that ZOOMS (a new navigation) |
| G-230 | **Per-hover adaptive spread**: a hovered url's nodes spread so pictures and panels do not overlap, and return to the post-fit transform when the hover ends *(2026-10-17, PLUGIN_GOAL 159)* | *Addendum X* | **Confirm.** Built 2026-10-18 (`spread.ts spreadFactor`, `graph.ts spreadUrl/unspread`). Live (`scripts/check_hover_spread.py`, on pages whose drawn nodes CROWD -- the first run sampled uncrowded pages, where k = 1 is right and nothing was tested; and with 2.5 s waits, because a covered window draws ~1 frame a second): clean -- closest pair / summed radii 0.115 -> **0.689** (k capped at 6) and 0.677 -> **1.15** (k 1.7, the gap exactly); after the hover every node at its fit target (**0** units off). Planted `plantNoHoverSpread`: 0.172 -> 0.172 and 0.641 -> 0.641, nothing moves, nodes left 127-166 units off their targets |
| G-231 | **Retrieval works as the reader uses it** -- the field, the tiers, k/n, the strip, the lights and panels behave together without bugs *(2026-10-18, PLUGIN_GOAL 160)* | *Addendum X* | **Partly** 2026-10-18, two defects found in the reader's own session (search "small language models site:arxiv.org", 200 / 200, screenshot `build_analytics/app_20261018_030817.png`): every strip item read "duckduckgo.com/" -- all 200 results were chunks of TWO search-engine pages, because tier 1 took pages until their counts covered n and two pages held thousands of matches each (a regression from G-225's page coverage); now a page counts and is asked for at most n/6, so at least six pages contribute and the merged ranking still decides (planted `plantUncappedShare`); and a strip item is labelled with the result's own first line (the search's `preview`), not its url. Also seen: 19 queries asked, 8 answered (typing supersedes), the strip re-rendered 711 times over 51 background re-ranks. Live probe queued (`scripts/check_retrieval_use.py`) **Live 2026-10-18** (`scripts/check_retrieval_use.py`, the reader's own query at 200/200, twice): clean 8 distinct pages and 102-103 distinct strip labels vs planted (`plantUncappedShare`) 1 page and 5 labels |
| G-232 | **The panels toggle governs the results strip**: right-click mode, a hovered result flies without a panel and a right-click opens it; fly-to mode, a hover flies and opens it *(2026-10-18, PLUGIN_GOAL 161)* | *Addendum X* | **Confirm.** Built 2026-10-18; live (`scripts/check_retrieval_use.py`): right-click mode, a strip hover flies and opens **0** panels, a right-click opens 1; planted `plantStripIgnoresToggle` -- the hover opens **1**. The first run's planted arm went through `hoverPanel`, which checks the mode itself, so it could never fail; the plant now opens the panel directly, as the defect did |
| G-233 | **A web code block is one code artifact**: its text whole, addressed below the `pre` by its own syntax (as `code://` files are, `G-49`); a hover on it shows the code, never its copy button; an unlabeled control does not read as "button" *(2026-10-18, PLUGIN_GOAL 162)* | *Addendum XI* | **Partly.** Built 2026-10-18 (8a262d0): the sensor folds a `<pre>` as ONE indivisible unit, its text whole with its newlines (`sensor.js` emitChunks/collectLines); the markdown fences it; the unit search stops at a code block; an `@control` with no label draws as the stored markdown's `( . )` / `[ ]`, not "button". `tests/test_code_blocks.py` (live): clean one chunk holding the whole sample, planted `variants.codespans` (set at boot -- chunks are cached at the first fold) splits it into highlight spans. Live 2026-10-18 (`scripts/check_code_hover.py`, the transformers quicktour, the REAL pointer on a highlighted span mid-block, six blocks per arm): clean -- **5 of 5** opened panels hold their block's first AND last line; planted (`codespans` + `ForceTree.plantCodeAsText`) -- 4 of 5, one block cut. Weak separation: the page is stored at once, and a hover resolves to the STORED chunk, which holds whole blocks either way (`scripts/check_web_code.py`: 0 stored chunks below a `pre` in both arms). Corrected 2026-10-18: the markdown did NOT fence a block -- the renderer flattens every value's whitespace, so a sample is one inline span -- and it must not: a chunk's markdown lines zip one-to-one with its addresses, and a fenced block (tried, then reverted) shifted every line after it onto the next paragraph's and a button's addresses. The code graph reads the trie's value instead (newlines kept; `Workspace.web_code_cpg(raw=)`, the sidecar passes its spine's trie). Below the `pre` the block is now addressed by its own syntax in the code graph (`G-235`) |
| G-234 | **One class of code artifact, one interface**: web code blocks, `code://` repo and packages, vault code cells chunk, address, vectorise (`G-52`) and show alike -- the code artifact panel (`P-C1`, `P-C2`, `P-C5`) with the kernel/terminal toggle (`P-N3`) *(2026-10-18, PLUGIN_GOAL 163)* | *Addendum XI* | **Open** |
| G-235 | **A Code Property Graph in the store**: AST (CONTAINS), CFG, PDG (DATA_FLOWS_TO), CALLS, IMPORTS, INHERITS as property edges with context (`line`, `arg_passed`), in the kuzu graph the trie lives in (imports already links, `G-8`/`G-51`) *(2026-10-18, PLUGIN_GOAL 164)* | *Addendum XI* | **Partly.** Built 2026-10-18 for `code://` Python: `vertiscope/cpg.py` derives the graph by the chunks' own addresses (a function is `/module[1]/class[1]/function[2]`, its statements `.../stmt[n]` below it -- the same walk as `tag_source`, test-checked to agree), and the store keeps it as `CodeNode` + one `Cpg` edge table with `kind` AST / CFG (`next`, `true`, `false`, `loop`, `except`, `entry`) / DFG (`var`) / CALLS (`line`) / INHERITS; imports stay `LinksTo`. Upserted per file in `index_source` -- the reader's incremental update -- with calls and bases into other files resolved by qualified name BOTH ways, so whichever file is indexed first the edge appears and a re-index keeps it (`tests/test_cpg.py`, 3). Live: `POST /package {repo}` indexed 128 modules in 4.6 min -- **125 graphs, 140 classes, 1,790 functions, 23,350 statements; AST 25,280, CFG 27,050, DFG 29,345, CALLS 2,122 (490 across files), INHERITS 3** (`GET /cpg_stats`, `GET /cpg?url=`). **Web code blocks** 2026-10-18: a page's Python `<pre>` is graphed BELOW its address (`<url>|<pre xpath>/module/...`), scoped per block, re-graphed only when its code changes; the module's own statements are a scope now (numbered, CFG/DFG, an import defines its names, calls from the module node) -- a sample is top-level code and graphed to an empty module before. Tests `tests/test_cpg.py` (trie value vs planted `VERTISCOPE_PLANT_CODE_FROM_LINE`, offline and the live path; module statements vs planted `_PLANT_NO_MODULE_STMTS`). Live (huggingface quicktour, fresh): **10 blocks, 28 statements, CFG 28, DFG 15; library calls `transformers.pipeline`, `transformers.AutoTokenizer.from_pretrained`, `datasets.load_dataset`, `huggingface_hub.notebook_login` +6**, the same on two reads; before: 17 blocks, 0 graphed. Not yet: `arg_passed`, the pypi packages' graphs, JavaScript (comments only, as `tag_source`) |
| G-236 | **Unified-diff upsert from a graph mutation**: ADD/DELETE node/edge, MODIFY_PROPERTY compiled to source by `ast` + `difflib`, compile-checked, applied as a diff -- the path of `P-C5`'s live module deltas *(2026-10-18, PLUGIN_GOAL 165)* | *Addendum XI* | **Partly.** Built 2026-10-18: `vertiscope/cpg_mutate.py` -- ADD_NODE, DELETE_NODE, MODIFY_PROPERTY (`name`, `docstring`, `code`), ADD_EDGE / DELETE_EDGE (CALLS as a call statement, INHERITS as a base), each addressed by the CPG's canonical xpath; edits on the source LINES at the nodes' positions (comments and formatting outside the edit survive, never `ast.unparse`); the result must compile; returned as a unified diff. `POST /cpg_mutate` previews; with `apply` it writes only this repository's own files and re-ingests them (chunks, CPG, projector). Tests `tests/test_cpg_mutate.py` (6): a CALLS edge added and deleted returns the source byte-identical and the graph shows the edge between; a breaking mutation and an unknown address refused; applied and re-ingested, the STORE's graph has the new edge. Live (preview only -- nothing written into the reader's repository): a rename + a call on `code://repo/cpg.py` came back as the right unified diff; a mutation leaving `( ` unclosed refused ("'(' was never closed (line 44)"); the file's md5 unchanged. Not yet: `apply` seen live |
| G-237 | **Three local quantized models by role**: OpenJEV (typed categoricals over graph data), DeepSeek-Coder 6.7B (code), Triplex (web chunks -> KG triples); relation to the recorded Nous Hermes 2 DPO 7B chat choice (`L-1`) to confirm *(2026-10-18, PLUGIN_GOAL 166)* | *Addendum XI* | **Open** |
| G-238 | **Natural-language-first prototyping**: docstrings and code-type wireframes first, then each component completed, informed by graph RAG over the code-diff graph, the docstrings and the web KG (meets `G-105`, `R-5`) *(2026-10-18, PLUGIN_GOAL 167)* | *Addendum XI* | **Open** |
| G-239 | **Through-stack agents**: model + bounded context + isolated terminal + local code artifact + MCP tools from its code; recursive graph-RAG tool calls between stacks (spawned when a query does not resolve) as edges of the workspace graph; prompt = one more input to that call; promises at the MCP surface rolling up to a validated code transformation; reconstruction, repair, skeleton/ephemeral separation, recurrence detection. Design with the reader first *(2026-10-18, PLUGIN_GOAL 168)* | *Addendum XI* | **Open** |
| G-240 | **Everything is a plugin**: extensions fill named slots of a stable core and may only tighten it; the core runs without them *(2026-10-18, PLUGIN_GOAL 169)* | *Addendum XI* | **Open** |
| G-241 | **The PyPI package base in the 3D view as projected chunks, laid out for the code property graph's triple form**: the AST with its CFG (execution order) and PDG (data flow) as three edge types, docs/comments (embedded, `G-52`), the code (not embedded); UMAP vs force-directed vs both decided by measurement; specialised node kinds, edge types and interfaces per KG form (extends `G-104`, `G-9`, `T-6`) *(2026-10-18, PLUGIN_GOAL 170)* | *Addendum XI* | **Partly.** The three-layout measurement (`scripts/measure_code_layout.py`, 2026-10-18) on this repository's graph -- 1,930 classes and functions, 1,364 with a docstring vector, 2,096 CALLS: semantic = k-NN recall@10 of embedding neighbours in the layout; structure = median CALLS length / median random-pair distance; planted = the same with the CALLS endpoints shuffled. **UMAP 0.334 / 0.299 (shuffled 1.019); force-directed 0.076 / 0.064 (shuffled 0.694); hybrid 0.334 / 0.301 (shuffled 1.018).** Force draws calls shortest and keeps about a fifth of meaning's neighbourhoods; UMAP keeps meaning and still draws calls 3.4x shorter than chance -- so the proposal stands: positions from UMAP, undocumented symbols in their AST parent's room, CALLS/CFG/DFG drawn, never forces. **Drawn, live 2026-10-18** (`scripts/check_code_edges.py`): `GET /cpg_edges` maps each CALLS / INHERITS end to the chunk drawing it; unfolding `code://repo/graphstore.py` (136 chunks) drew **106** orange CALLS lines of 124 mapped (both ends drawn) -- the batch drew 553 lines = 447 structural + 106; CALLS switched off -> 447 (none of them), on -> 106 again; the graph's force links 447 in both arms (drawn, never forces); planted `plantNoCodeEdges` 0. Switches `calls` / `inherits` in the view's bar. Not yet: CFG and DFG, which join STATEMENTS (not drawn nodes yet), and the motion score |
| G-242 | **A panel opened inside a link carries the link**: a unit chosen within an anchor includes the anchor's own href (archive.org tiles showed no link to their item) *(2026-10-18, PLUGIN_GOAL 171)* | *Addendum XI* | **Confirm.** Built 2026-10-18 (8a262d0): `address.inUnit` counts a line on an ANCHOR wrapping the unit as the unit's own, so the tile's panel holds its item link (`obsidian-plugin/tests/address.test.mjs`, clean + planted `__vertiscopePlantNoWrapLink`). **Live 2026-10-18** (`scripts/check_archive_hover.py --only-link`, archive.org homepage, the real pointer on 6 tiles twice): **11 of 12** panels hold the tile's own `/details/<id>` link vs planted **0 of 12** (which still opened the right tile, 12/12 -- only the link was missing) |
| G-243 | **An open hover panel never blocks the pointer from the nodes beneath it** *(2026-10-18, PLUGIN_GOAL 172)* | *Addendum XI* | **Confirm.** Built 2026-10-18: a panel a HOVER opened carries `is-preview` and passes the pointer through (`styles.css`); its title bar stays live, so a drag keeps it and minimize/close work; a click on its node, or the browser asking for it, makes it an ordinary panel (`graph.ts openBillboard`). Planted `plantPreviewBlocks`. Live, `scripts/check_preview_passthrough.py` with the REAL pointer (CDP mouse events): null arm, no panel -- the graph's tooltip names node T; clean, a preview's body over T -- element under the pointer `canvas`, T hovered; planted -- under the pointer `panel`, T NOT hovered; both arms: a click on the previewed node keeps it as a pinned panel |
| G-244 | **A list of small items is one unit**: one panel for a prose list, not one per bullet; the item-is-the-unit rule only where items are tiles *(2026-10-18, PLUGIN_GOAL 173)* | *Addendum XI* | **Confirm.** Built 2026-10-18 (f3abf91, then a second cause): the climb returned at the first level with three lines, so a bullet made three lines by inline code or links opened ALONE before the list was reached; now an item of a list that fits joins it -- but only a PROSE item (`address.isProseItem`: an `li` whose lines are all inline), so archive.org's tiles stay one per panel (`tests/address.test.mjs`: the four-item list, its planted arm, a 30-item list, a tile row). Live on fastapi's README (`scripts/check_list_hover.py`, the real pointer on each short list's second bullet): **3 of 3** lists open whole (8, 2 and 4 items -- the 4-item one has inline code in every bullet) vs planted `plantItemAlways` 1 of 3; and G-220's tiles unharmed (12/12, 7/8) |
| G-245 | **A url node stands at the centroid of its chunks** (`G-106`) *(2026-10-18, PLUGIN_GOAL 174)* | *Addendum XI* | **Partly.** Measured as the url node's distance from its drawn chunks' centroid over the cloud's rms radius. A page UNFOLDED from the store is centred: 8 pages, median **0.044** (max 0.08) vs planted `plantOffCentre` 0.129 (max 23.3) (`scripts/check_url_centroids.py`). The off case is a page NEW to the store, while it is browsed (`scripts/check_stream_centroid.py`): two causes found. (1) The telescope equalises radii by rank, so a lopsided raw fit drew its mass to one side -- the url node at the edge of its own fan, 0.59-0.71 -- now the whole cloud is shifted onto the url node after the relax (`plantNoRecentre`); (2) chunks sat 118-193 units from their targets, calm-pinned, for 25 s+ -- now any chunk drawn more than max(2, 5% of its bound) from its target glides there (`plantTeleByForce`). At 20-35 s after landing: clean 0.11-0.33 (Splay tree, Skip list) vs planted (both) 0.53-1.23 (Treap, Scapegoat tree). (3) A glide that lands where its target no longer is now glides on (`stepGlides`). Second run, three new pages per arm, 20-35 s: clean 0.06-0.40 (median ~0.14), planted 0.02-1.13 (Rope 0.82-1.13). **Not yet**: the drawn chunks of a just-landed page still wander 75-110 units from centred targets at times; the source is not pinned. Caveat on every drawn-position number here: these probes ran with the Obsidian window COVERED, which Chromium throttles to ~1 frame a second (measured 2026-10-18); glides are time-based and unaffected, but the force simulation advances per frame, so force-driven settling runs ~60x slower than for a reader in front of it |
| G-246 | **annas-archive result cards chunk along their own boundaries** *(2026-10-18, PLUGIN_GOAL 175)* | *Addendum XI* | **Open** |
| G-247 | **A DDoS-guard reload does not reset the page's stream** *(2026-10-18, PLUGIN_GOAL 176)* | *Addendum XI* | **Confirm.** With `G-249`'s gate the check never enters the url's trie, so passing it continues the page. Live (`scripts/check_page_gate.py`, a revisit THROUGH the check): clean 1 capture, the page's 4 stored chunks unchanged-skipped; planted `store-gates` 2 captures, the check's chunk kept beside the real ones. And in the 3D view (`scripts/check_check_reload.py`: the page settled, then a 12 s check that reloads itself): clean -- the page's drawn nodes kept 100% during the check and after, nothing of the check drawn; planted -- the same nodes kept but the check drawn as a FIFTH node of the page, still there after the real page is back. Measured on a 4-chunk fixture: a long page's stream through a check is not yet measured |
| G-248 | **PDFs are downloaded and chunked**: a PDF link or file url the reader reaches is fetched, kept, and its text recursively chunked into the trie under its own url, vectorised, drawn and panelled like a page *(2026-10-18, PLUGIN_GOAL 177)* | *Addendum XI* | **Confirm.** Built 2026-10-18: when the cell's document is `application/pdf`, the PAGE reads its own bytes (`fetch(location.href)` -- the browser's copy, nothing new asked of the host) and sends them to `POST /pdf`; the sidecar keeps the file as `pdfs/<sha1>.pdf` and lays its text out as one `section` per page, `h3` for larger-type blocks, `p` per text block, links kept (`vertiscope/pdf.py`, PyMuPDF), which goes through `index_html` -- the same chunker, vector queue and graph; the viewer's own DOM is kept out of the stream. Address: `<url> : /html/body/article/section[page]/(h3|p)[n]`. Tests `tests/test_pdf.py` (3, a scanned PDF reported as `pages_without_text`, never invented). Live (`scripts/check_pdf.py`): arXiv 2005.14165, 75 pages, 6.8 MB -- read 0.2 s, stored 16.2 s, **293 chunks** holding the paper's words, **293 drawn**; arXiv 1706.03762 -- 15 pages, 53 chunks, 53 drawn. Planted `no-pdf`: the store got **1 chunk reading "about:blank"** (the viewer), none of the paper. Not yet: a PDF served as a download (`Content-Disposition: attachment`) never opens in the cell, so it is not reached |
| G-249 | **Error pages and bot-check interstitials are page states, not content**: a 502 or a "checking your browser" page is not stored as the url's chunks; the stream resumes on the real page (with `G-247`); nothing works around the check *(2026-10-18, PLUGIN_GOAL 178)* | *Addendum XI* | **Confirm.** Built 2026-10-18: `obsidian-plugin/src/gate.ts` decides from what the host already has -- the main frame's HTTP status (`did-frame-navigate`; a webview's `did-navigate` does not carry it), the title (anchored both ends: "DDoS-Guard - Wikipedia" is not a check, caught by the test), and for a small first fold (<= 40 lines) the check's own wording; `browser.ts absorbDrain` drops a gated drain before the force tree, the outline and the capture queue, and says so in the caption. Nothing is clicked, solved or worked around. Tests `tests/gate.test.mjs` (3, with non-vacuity). Live against a local imitation (`scripts/fixture_gate_server.py` -- a check that reloads itself to the real page, and a 502): store DURING the check clean 0 chunks / planted `store-gates` 1 chunk holding the check's text; after the real page clean 4 chunks, no check text / planted 5, the check text kept; a 502 clean 0 / planted 1 chunk; documents gated 3 / 0. The store's one real instance: `annas-archive.pk/search?q=small+language+models` is stored as the DDoS-Guard page (found by searching the store; left for the reader's next real visit to replace) |
| G-250 | **A link's destination resolves to its domain in every panel**: `https://huggingface.co/docs/...`, never a bare `/docs/...` tail; and a control in the view's bar says what it is and appears only where it does something *(2026-10-18, PLUGIN_GOAL 179)* | *Addendum XI* | **Confirm.** Built 2026-10-18: a streamed chunk's link line resolves against the base its page declared (`ForceTree.lineText`, `ForceTree.baseOf = snapshot.baseFor`; the stored panels already did); test `obsidian-plugin/tests/forcetree_adopt.test.mjs` (absolute on the page's domain vs planted `plantRelativeLinks` keeping the tail). The `calls` / `inherits` switches now appear only while a code page's chunks are drawn, each with a tooltip saying what it draws. Live 2026-10-18 (`scripts/check_list_hover.py <quicktour>`, links mode, the REAL pointer on each short list): clean -- list 1's panel holds **3 absolute `https://huggingface.co/docs/` links, 0 bare `/docs/` tails**; planted `plantRelativeLinks` -- **1 absolute, 2 tails** (list 2: 1 absolute, 0 tails in both arms, its link was already absolute) |
| G-251 | **A unit is a whole item, and its panel leaves from a node of its own**: hovering any part of an item -- a track row's cover, its title block -- opens the item's one panel; each unit's panel hangs from its OWN grey node, one level below its chunk (or its page, when the chunk is not drawn), never from a position its chunk's other units or its page share *(2026-10-18, PLUGIN_GOAL 180 a, b)* | *Addendum XI* | **Confirm.** Built 2026-10-18. (a) The unit search no longer stops at the first level holding three lines: from there it climbs while the level above is not a list, adds a line, stays within `max`, adds no other chunk's lines (`ForceTree.chunkForElement`), or the chunk is not yet whole (`address.unitOf`); a link ends the climb below it. Tests `obsidian-plugin/tests/address.test.mjs` (cover and title of a bandcamp-shaped row -> the row; a one-row chunk -> whole; planted `__vertiscopePlantSubUnit` -> the title block) and `forcetree_adopt.test.mjs` (same over live chunks, planted `plantSubUnit`). (b) `GraphView.ensureUnitNode`: a panel with no drawn node -- `chunk|unit`, or a chunk on an unopened page -- gets a grey `unit` node on a Fibonacci shell about its chunk (or page), linked to it, kept through redraws (`keepUnits`), the oldest beyond 96 dropped unless a panel holds it; the panel anchors to that live node. Live 2026-10-18 (`scripts/check_unit_nodes.py`, bandcamp radio show 1010, the REAL pointer on the cover and then the title of 7 track rows, three arms): clean -- **7 panels for 7 rows, 0 rows split, 7 distinct anchors, 14 of 14 hovers anchored to a node in the graph**; planted `plantSharedAnchor` -- 7 panels, **0 of 14 anchored to a graph node** (copies of their chunks' positions); planted `plantSubUnit` -- **14 panels, 7 of 7 rows split** (cover and title each their own) |
| G-252 | **Rendering first, vectorization after it**: a fresh page's chunks are drawn as grey nodes and their panels open from the sensor's own tree before anything is stored, embedded or placed; the store, the vectors and the projection follow without blocking it *(2026-10-18, PLUGIN_GOAL 180 c)* | *Addendum XI* | **Confirm.** Built earlier (grey nodes from the drain, `G-198`; grey panels, PLUGIN_GOAL 125); measured 2026-10-18 (`scripts/check_render_first.py`, each page cache-busted so nothing of it is stored; the pipeline profiler's visit marks, renderer clock from navigation; the REAL pointer on a text block as soon as the first grey node is drawn). Clean: huggingface quicktour grey **1.7 s**, placed 2.5 s, stored 9.2 s, early panel **291 ms**, grey, nothing stored yet; wikipedia Radix_tree grey **1.3 s**, placed 2.5 s, stored 10.7 s, panel **231 ms**, grey; bandcamp radio/1010 grey **0.67 s**, placed 2.3 s, stored 7.2 s, panel **231 ms**, grey. Planted `no-force-panel` (a grey chunk has no panel): the early hover opens **no panel** on all three. Found on the way: the profiler instance outlives a plugin reload and was kept by a capability test that did not name the newest method, so every reload ran the old class; and a server redirect (`radio?show=1010` -> `/radio/1010`) filed the visit's stages under no visit. Both fixed (`profile.ts` `visitAlias`, `did-redirect-navigation`); live, the redirected visit's marks went from {} to drain/grey/stored |
| G-253 | **A scanned chunk leaves grey for its projected place once vectorized; nothing stays grey that the store will never place** *(2026-10-18, PLUGIN_GOAL 181)* | *Addendum XI* | **Partly.** Measured 2026-10-18 on bandcamp's homepage (its feed rewrites itself), `scripts/check_projection_follow.py`: the stored path works -- 65 of 65 projected chunks drawn at their place -- but grey nodes piled up beside them, and the session's lifecycle read 3,381 grey drawn, 586 saved, 2,060 timed out. Four causes found, three fixed: (1) an uncovered grey node went after a flat 20 s while its capture was still in flight -- it now waits for its capture's own answer (`onUnstored`), 120 s as the net (`collapseCovered`); live, 90 s on bandcamp: **0 timed out, 73 saved** vs planted `plantUncoveredClock` **318 timed out, 0 saved**; (2) a LEFT page's settle ran before the next page's first capture (oldest-first, PLUGIN_GOAL 155) -- it now waits behind the page on screen, its drains keeping their age order (`pumpCaptures`); `scripts/check_next_page_capture.py`, 25 s on bandcamp then a fresh Wikipedia article: first stored chunk drawn at **28.3 s** vs planted `settle-in-age-order` **none in 120 s** (110 grey, 0 covered); (3) the store had grown 1.6 -> 8.8 GB uncompacted (embedding SETs, ~1.1 GB a checkpoint) and captures slowed from 3-10 s to 15-26 s: auto-compaction waited for request silence the app's polling never gave. The plugin now reports the reader idle (`POST /maintenance`, once a minute after 5 min idle) and compaction counts that as away when nothing was captured for 2 min (`_compact_due`, planted `_PLANT_REQUEST_QUIET_ONLY`, `tests/test_autocompact.py`); live the route answered `compact: true` at 6.9 GB and the supervisor compacted to 1.6 GB, every count kept; (4) unit nodes (G-251) stayed grey after their panels closed -- they now go with the panel and take their chunk's colour (live, planted `plantKeepUnits`). **Not yet**: 95 of 170 grey nodes at 75 s were OLD versions of feed items the page rewrote in place -- kept as nodes (G-216: every unique chunk seen) but never stored (the store keeps the address's current content), so never placeable. Whether they are stored as their own chunks or let go is the reader's call (asked). Capture latency is still 5-12 s a capture on a busy page; anchor writes are most of it (COPY is 33x faster per batch but stays opt-in, `graphstore._ANCHOR_COPY`) |
| G-254 | **Loading takes seconds, not minutes** *(2026-10-12: "loading's taking quite a long time"; "loading takes several minutes instead of seconds" -- recovered verbatim, PLUGIN_GOAL 182)* | *Addendum XI* | **Open.** No requirement was written for it at the time and nothing measures it: what "loading" spans (Obsidian start to plugin ready, the projector's first layout, a page's first stored chunk) is not yet defined against your words. A plugin reload today: 6 s to settled, projector ready 12.1 s (`Live.reload_plugin`) |
| G-255 | **A searchable history of the codebase -- a minimal adapter that queries git directly, vectors only a cache** *(2026-10-06: "a simple graph RAG MCP on the full git diff"; "a minimal adpater plugin design that does vectorization efficiently but queries still directly over the git logs" -- PLUGIN_GOAL 2026-10-06 (2), (4))* | *Addendum IX* | **Done.** Built 2026-10-06 (`368dacc`, `vertiscope/gitlog.py`, MCP server `vertiscope-git`: `git_search` semantic/grep/pickaxe, `git_show`, `git_file_history`); used in this session. Recorded as a row only now (inventory, PLUGIN_GOAL 182) |
| G-256 | **The field the reader is typing in keeps the keyboard** while the cell navigates or presses "More results" *(2026-10-11: "i can't interact with the result boxes. i type a number and am instantly kicked out")* | *Addendum IX* | **Partly.** Built 2026-10-11 (`browser.ts` `giveBackFocus`: given back only when the cell's own action took it, never a click of the reader's). No row until now; not live-checked |
| G-257 | **A drag on empty space moves nothing** -- no invisible pick sphere larger than the node drawn *(2026-10-12: "clicking and dragging empty space somehow drags a nearby (up close to the camera) but distant node")* | *Addendum IX* | **Partly.** Built 2026-10-12 (`graph.ts` `fitProxies`: every pick proxy at its node's drawn size each sync; 21,808 of 22,229 had been stale, up to 21.5x; planted `plantStaleProxies`). No row until now; not live-checked |
| G-258 | **A second node clicked drives the browser as the first did** -- scroll to or navigate to its element *(2026-10-12: "clicking on a node after clicking on another node gives no response in the browser")* | *Addendum IX* | **Partly.** Built 2026-10-12 (`graph.ts`: the click reveals the element the chunk's FIRST line draws). No row until now; not live-checked |
| G-259 | **Obsidian's own force-directed graph, considered as the layout engine** *(2026-10-04: "there is likely a more convenient approach that uses obsidian's original force-directed layout" -- PLUGIN_GOAL 2026-10-04 (6))* | *Addendum IX* | **Open -- never answered.** Read as a candidate on 2026-10-04 and then neither evaluated nor ruled on; the 3D view went on with its own forces and the projector. Asked now |
| G-260 | **One compact code knowledge graph: what code IS and DOES, one triple per fact** -- `a = b` one triple, an import one triple -- combining the AST, CFG and DFG *(2026-10-18, PLUGIN_GOAL 186g)* | *Addendum XI* | **Confirm.** Built 2026-10-18 (`vertiscope/code_kg.py`, design `docs/GRAPH_WORKBENCH_DESIGN.md` §3): DEFINES, ASSIGNED_FROM, IMPORTS, CALLS, INHERITS, TAKES, RETURNS, BRANCHES_ON, each at the CPG's own trie address and citing the CPG edges it summarises -- a view of the CPG, not a second store. A dotted chain is one name (`os.environ.get`, not also `os`). `tests/test_code_kg.py` (4, incl. a changed module changing exactly its triples, and a web block below its `pre`). Live: `GET /code_kg?url=code://repo/cpg_mutate.py` -> 465 triples (105 DEFINES, 173 ASSIGNED_FROM, 8 IMPORTS, 15 CALLS, 1 INHERITS, 20 TAKES, 49 RETURNS, 94 BRANCHES_ON). **Drawn** 2026-10-18 from a `code://` chunk's panel field `triples` (the module's triples at the chunk's enclosing scope and below): live on `code://repo/address.py`, **77 entities hung from the chunk, 120 triple lines, 1.5 s** (`scripts/check_kg_draw.py`; planted `plantNoKg`: no field, nothing drawn) |
| G-261 | **Special files are content -- .gguf, .safetensors, .csv/.tsv/.parquet, .json, archives, .pdf -- drawn as their own nodes with a panel per kind, and a download that ASKS before it fetches** *(2026-10-18, PLUGIN_GOAL 186k; "downloads for special files should include .pdf and also prompt the user before applying a download on-click")* | *Addendum XI* | **Confirm.** Built 2026-10-18: detected at the linking line's address when a page is stored (`Workspace.special_files`, relative links resolved, a Hugging Face `/blob/` viewer link taken as its `/resolve/` file), kept per chunk (`FileRef`, `GET /files`); drawn hung from that chunk in the kind's colour (`GraphView.loadFiles`); the panel shows kind, name, link and the size from a HEAD (`GET /file_head` -- nothing fetched), and its `download` field turns into a prompt -- name, size, destination, confirm / cancel -- before `POST /download {confirmed: true}`, which the sidecar refuses without that flag. A model goes to `~/.cache/gpt4all`, a PDF is then chunked like a page (`index_pdf`), anything else to the workspace's `downloads/`. Tests: `tests/test_special_files.py` (3, planted `_PLANT_NO_FILES`, `_PLANT_HF_BLOB`), `tests/test_file_download.py` (unconfirmed refused with nothing written; confirmed lands). Live (`scripts/check_file_nodes.py`, OpenJev Flash 9B's file list, fresh): **5 files, 5 nodes, all linked to their chunks; panel size 5.63 GB; prompt shown; cancel -> no download started**; planted `plantNoFileNodes` -> 0 nodes |
| G-262 | **Models installed and run as typed graph entities** -- one way to install from a model's web page and run it in the plugin, with hard type constraints per model and task *(2026-10-18, PLUGIN_GOAL 186a-c, 186j)* | *Addendum XI* | **Partly.** On disk 2026-10-18 (your approval): DeepSeek-Coder 6.7B Instruct Q4_K_M (4.08 GB), Triplex Q4_K_M (2.39 GB), OpenJev 27B Q4_K_M (16.55 GB), OpenJev Flash 9B Q4_K_M (5.63 GB; no DeepSeek-based JEV exists in ~1,200 listings -- Flash 9B, Qwen3.5-based, is the fast member of the same API). Install from the web is G-261's download into the model directory. Typed runner built 2026-10-18 (`vertiscope/models.py`): a ROLE per model fixes its I/O types and its parser; the parser returns the type or says why not, never coerces (`tests/test_models.py`, 4, the Triplex fixture is the model's real output). `GET /models` lists roles, files and whether each runs; `POST /model_run` + `GET /model_job` run one in a thread. Live: DeepSeek-Coder answered a prompt in 38 s (CPU) and its code block came back as code-KG triples (`answer DEFINES longest_common_prefix`, `TAKES str1`, ...). Not yet: model NODES in the 3D view; GPU runs; JEV -- it reads per-option scores at the first output position, which needs `llama-cpp-python` (not installed) with Qwen3.5 support |
| G-263 | **The 2D graph workbench recovered from the mothership and extended**: the black-slate card, typed panel form, right-click fold / double-click compile, commuting panel <-> graph, the reservoir rollout with its readout perimeter and bisector node; trie-path patterns across pages as aggregate pydantic types; through-stack nodes *(2026-10-18, PLUGIN_GOAL 186d-f, 186i, 186m)* | *Addendum XI* | **Open -- design.** Recovered from `github.com/Koreiju/mortegon` (its user-requirements doc §E, §F, §M, §P, §R, §S, §T and its domain model §7.8 -- files in that repository, cloned at `Documents/web_fiber_haptics`) into `docs/GRAPH_WORKBENCH_DESIGN.md` §1-2, with what vertiscope already has against each (for code the panel/graph dialectic already commutes: `cpg_mutate` round-trips). Questions for you in §6 |
| G-264 | **Triplex: a web text panel to knowledge-graph triples**, linked to its source chunk, force-directed without embeddings of its own *(2026-10-18, PLUGIN_GOAL 186h, 186l)* | *Addendum XI* | **Partly.** Runner and strict parser built (`run_triplex`, `parse_triplex`: `[n], TYPE:name` entities, `[a] PRED [b]` triples; an id defined twice keeps its first, an undefined id / an unasked predicate / a stray item is noted, not guessed); a chunk is given as its PLAIN prose (`models.plain`: link targets, images and wiki chrome dropped). Live on Wikipedia's Radix tree, CPU: 10 entities, 2 triples in 37 s (`lookup operation USED_FOR string exists in a trie`; one wrong -- `Patricia Trie INVENTED_BY Patricia`: the parser checks form, not truth); through `POST /model_run` on a chunk: 23 entities, 0 triples in 65 s. **Drawn** 2026-10-18: a chunk panel's `triples` field runs Triplex on the GPU (`MODEL_DEVICE` cuda, CPU fallback; a paragraph 1.8-3.2 s vs 37-65 s on CPU) and draws each entity as a node hung from the chunk (no embedding of its own, force-directed about it) and each triple as a line between them (drawn, never a force); an entity's panel lists its triples. Live (`scripts/check_kg_draw.py`, Wikipedia's Radix tree): **12 entities, all linked to the chunk, 5 triple lines, 10.6 s including the model's load**; planted `plantNoKg`: no field, 0 nodes |
| G-265 | **Tables render as tables** -- a page's `<table>` and a linked CSV in a simple table view; one open Wikipedia panel renders a table wrongly now *(2026-10-18, PLUGIN_GOAL 186k)* | *Addendum XI* | **Confirm.** Found and fixed 2026-10-18 on Wikipedia's Trie (its infobox holds the 3-column "Time complexity" table in a cell). Three causes: (1) the panel joined lines into one paragraph and a table cannot interrupt one -- a blank line now goes before and after each run of rows; (2) the nested table's rows ran on under the infobox's 2-column delimiter, so a renderer dropped the third column -- a change of width starts a new table (`with_table_separators`, the panel's markdown form; planted `PLANT_ONE_TABLE_RUN` / `plantOneTableRun`); (3) the row-head test took a LINK row (`[Space complexity](...)`) and `O( n )` cells for controls and fell the whole nested table back to a cell per line -- `_is_control_glyph` counts only real control glyphs (planted `PLANT_BROAD_ROW_CONTROL`: 19 loose lines vs 7 rows). `tests/test_tables_render.py` (+2). Live (`scripts/check_tables.py`, the Trie article fresh): **11 pipe rows stored; the markdown panel draws 2 tables, "Worst case" in a cell**; planted: 0 tables. A CSV's own table view is G-261's next kind |
| G-266 | **Uniqueness and diff streaming that preserve earlier states**: how the codebase, its docs and the transcript have handled it, and whether uniqueness holds for the stream's versions and the store's addresses independently -- then fade or store the old versions of rewritten items (G-253) *(2026-10-18, PLUGIN_GOAL 183)* | *Addendum XI* | **Partly -- researched, your ruling asked.** `docs/UNIQUENESS_AND_VERSIONS.md`: the view is unique by CONTENT per element (G-216's generations), the store by POSITION (`sha1(url|xpath|part)`, chosen after content-keyed ids collapsed 18.8% of the corpus, ERRATA B10/B12); each holds alone, and they part on an in-place rewrite, where the store overwrites what the view keeps. Proposed: a VERSION chunk keyed by position AND content, no anchors, a `VersionOf` edge, vectorised and projected, capped per position -- or fade. Not built |
| G-267 | **The 3D view evaluated against Obsidian's graph, each in 3D** *(2026-10-18, PLUGIN_GOAL 184; G-259)* | *Addendum XI* | **Partly -- measured.** `scripts/measure_layout_vs_obsidian.py` on a copy of the store, 24 pages / 1,028 chunks, both in 3D: OURS (UMAP over chunk vectors, page at its centroid) keeps meaning -- **k-NN@10 0.513**, links short (0.086 of the median pair distance, vs 0.99 with their ends shuffled), page silhouette 0.364; OBSIDIAN's model (springs on links + all-pairs repulsion + centring, no vectors) separates pages (**silhouette 0.892**) and draws links shortest (0.032) but keeps **half** the meaning (k-NN 0.263); force relaxation started FROM UMAP for only 10 steps already falls to 0.264. Read: Obsidian's model is the better picture of LINK structure, ours of MEANING. Not yet measured: cross-page links (0 among these pages -- Obsidian's home ground, a vault's linked notes) |
| G-268 | **labyrintalis prepared, not pushed**: a renamed, scrubbed copy for review *(2026-10-18, PLUGIN_GOAL 185; G-165)* | *Addendum XI* | **Done.** `scripts/prepare_labyrintalis.py` -> `Documents/labyrintalis` (2026-10-18): 829 tracked files, no git history (commit authors stay out), `tests/corpus/` left out (137 third-party snapshots); vertiscope -> labyrintalis throughout (package, imports, plugin id `labyrintalis-bridge`, env prefixes); 84 home paths, the full name and e-mail replaced; the copy's own scrub report lists the 2 residual hits (the word "Gmail" in a benchmark summary). 31 tests pass inside the copy. Nothing committed there or pushed -- the push stays G-165, yours |
| G-189 | **Chunk view stays responsive at 26k nodes** *(2026-10-12: "significant lag experienced here", right after G-188)* | **Confirm** 2026-10-12 live (chunk view, 26,846 nodes, 90 frames): p50 **20 ms**, p90 36, max 95 -- it was p50 211, p90 5,452, max 6,836. CPU profile: 53% in url view's open-page pass (`fitChunkSizes` -> `telescope` -> `relaxCloud`), which ran in chunk view over every chunk, synchronously, on every projector update and absorb -- now skipped there (planted `plantFitInChunkView`); and a second look pass over every node on every sync (`fitProxies`) -- now at most once a second. |

### P. The panels

**P-W — the per-chunk web panel**

| id | requirement | status |
|---|---|---|
| P-W1 | Specialized for the **interactive components** of webpages | Partial |
| P-W2 | The **native, editable** Obsidian markdown editor as one half | **Defect D-3** |
| P-W3 | The interactive HTML card as the other, one per chunk, boundary set by the sensor | Done |
| P-W4 | A **minimal form of the original browser** — not raw HTML, not a browser re-render; same content, structure and affordances | Partial |
| P-W5 | Interactable **against the database, offline** | Partial |
| P-W6 | **And** dispatched to the live page when online | Partial — `enact` exists, gated off |
| P-W7 | **Media in both halves** | Partial |
| P-W8 | A switch between the two halves | Done |

**P-C — the code artifact panel**

| id | requirement | status |
|---|---|---|
| P-C1 | Full code artifacts **viewable and editable standalone** | Open |
| P-C2 | **A terminal always directly below** the artifact — a kernel *run-and-output surface*, not a shell prompt (P-N2 §4a) | Open |
| P-C3 | **Artifacts vectorized by their comments and docstrings** | **Done 2026-09-20** — `G-52`. Measured over this repository: 985,336 rendered tokens → 304,039 for the encoder, 66.2% is code and is dropped |
| P-C4 | **Docstrings and code docs more broadly are the vectorized surface for codebases** | **Done 2026-09-20** — `G-52` again, and it reaches past Python: `G-50` gives JavaScript its comments (1,000 over `sensor.js`'s 2,870 lines) without pretending to parse it |
| P-C5 | **Live delta updates to modules** in both halves and in the 3D view | Open |

**P-N — the retrieval-enhanced notebook panel**

| id | requirement | status |
|---|---|---|
| P-N1 | A **Jupyter kernel** panel, retrieval-enhanced | **Partial** — a python kernel runs cells per note, gated behind `--kernel`, via `POST /kernel`; the button is live in both rendering paths. NOT Jupyter-protocol (subprocess; see `NOTEBOOK_PANEL_DESIGN` §1) and not yet retrieval-enhanced |
| P-N2 | **Switchable** between Jupyter kernels and PowerShell terminals. Resolved §4a: a *kernel run in place*, a *command terminal* in a **separate pane** | **Partial** — shells switchable from discovery (`GET /interpreters`) and running per pane; Jupyter kernels are *listed* but not driven — the sidecar runs a subprocess, not the protocol |
| P-N3 | A **toggle on a code block** opens terminal or kernel — possibly both at once. Under P-N2's resolution "both" is the panel running its kernel *while* a separate pane holds a terminal: two panes, no special layout | Open |
| P-N4 | A facade over Obsidian's vault interface exposing local kernels to the filestructure | Open |
| P-N5 | Notebooks are **dynamically recursively chunked** like webpages | **Partial** — a note and its stored cell outputs chunk through the same recursive descent a page does (`vertiscope notes`); outputs are addressed `…/output[n]` and retrievable. Not yet *dynamic*: re-indexing is a command, not a diff on save (`P-N6`) |
| P-N6 | …and **continuously diff-updated to the db**, re-vectorized and re-assigned to chunks | Open |
| P-N7 | **One interface** centralizing retrieval and code research | Open |
| P-N8 | **Chunk scanning is exposed in the panel** — the reader can see the chunk boundaries the sensor drew | **Done** — a CM6 gutter marks every chunk's extent with its token count and flags any over the window, computed live by `POST /chunk_preview` through the same pipeline indexing uses. Editor only; reading view has no gutter |
| P-N9 | **Selection highlighting over the rendered markdown**, in the alternative panel | Open |
| P-N10 | That selection **annotates the context fed to the SLM** — the reader marks what the model is given, rather than the model taking the whole panel | Open |

**P-M — the native markdown panel, built outward**

| id | requirement | status |
|---|---|---|
| P-M1 | The **original Obsidian markdown panel survives in native form**, distinct from the notebook panel | Open |
| P-M2 | The same retrieval is added to the native default | Confirm — the `[]()` gesture is a CodeMirror extension registered on Obsidian's own markdown editor (`registerEditorExtension(linkGesture(...))`), so it runs in every native note; `R-3`'s live check is in one (a scratch note under `vertiscope-checks/`, trashed after) |
| P-M3 | Code, kernel and terminal options are built **on top of** the native form | Open |
| P-M4 | Buttons that add new structural cells sit at the **very bottom** of the markdown | Open |
| P-M5 | The hovering chat sits **below the boundary of the scrollable markdown window** | Open |

**P-B — the browser notebook cell**

| id | requirement | status |
|---|---|---|
| P-B1 | A fully-fledged **regular browser view** in the cell — NOT constrained to a chunk | **Done — seen live 2026-09-20** (`confirm.mjs`). An Electron `<webview>` with an address bar, back, forward and reload, navigating anywhere. Measured: loaded `books.toscrape.com`, followed a link, and went back |
| P-B2 | **Navigate exactly as in a normal browser**, while scanning continues on the live page | **Done — seen live 2026-09-20** (`confirm.mjs`, `P-B1`'s check). Navigation and back both work, and `live_capture_on` was TRUE throughout — the scanning loop stays armed while the reader browses, which is the half of this row that could have been quietly false. `G-16` confirms the chunks reach the projector |
| P-B3 | Embed the native **Selenium session view** in the cell if possible | **Superseded, not dropped** — the question this asked was answered the other way: the cell hosts an Electron browser and the SENSOR moved into it (`G-47`, verified against the scanner it replaces: 176 addresses, 14 chunks, 7 passes, identical). There is no Selenium window left to embed, which is the outcome Addendum II's "straddle" anticipated |
| P-B4 | **Resizing the cell resizes the Selenium window** | **Superseded** with `P-B3` — a `<webview>` flows with the DOM, so it resizes with the panel by construction rather than by driving a second process's window. That property is why the webview was chosen over `BrowserView` |
| P-B5 | The passive MutationObserver sensor fires throughout — scroll, hover, interact — diffing DOM → DB in O(delta) ms | Open |
| P-B6 | **Left click behaves exactly as in Firefox under Selenium** | **Done — seen live 2026-09-20** (`confirm.mjs`). Dispatched as a real input event to the guest rather than by setting `location`: the claim is that clicking behaves like clicking, and asserting it any other way would test the assignment instead. Measured: the click landed on `a-light-in-the-attic`, which is where that link goes |
| P-B7 | **Hover** overlays the chunk structure on the page's own cartesian layout, showing the chunks embedded in it | Confirm — `obsidian-plugin/src/chunkstructure.ts` (`embedded`): the hovered chunk's addresses share a prefix, its patricia node; that node's parent is the container it is embedded in, and the other chunks under it are its structure (up to `MAX_UP` 3 levels when the parent holds no other, never the page itself; a chunk whose node holds the hovered one is its frame, not a sibling). `PipelineBox.placeStructure` outlines them faintly in the cell above the page, one read of the page for all of them, nothing written into it; re-measured on scroll; gone on leave. `tests/chunkstructure.test.mjs`. Live (`confirm.mjs P-B7`, 2026-10-11, `shadow_catalogue.html`): hovering result card 3 gave the container `/html/body/result-list/#shadow-root/div`, 4 sibling cards, **4 of 4 measured inside the container's own box on the page** (read independently through the sensor), the hovered card not among them, 1 on screen and drawn (3 below the fold), none after leaving. Planted `plantNoStructure`: the hover outline only. **It found a hover defect on the way**: the sensor's push named only its in-page chunk, which can be COARSER than the store's (the whole shadow-DOM list is one in-page chunk), and every card resolved to the page header's stored chunk -- the outline, the camera and the panel all went to the header. The push now carries the hovered element's own composed address (`sensor.js` `hoverAddress`, spelled as the fold spells it) and the host resolves it by the store's nearest-ancestor walk; planted `plantHoverById` reproduces the header. And a pointer that left the page and came back to the SAME element was never hovered again (`lastHoverTarget` survived the leave) |
| P-B8 | **Right click locally indexes a chunk to its dual-view markdown panel inside the cell** — this is what feeds the SLM | **Done — seen live 2026-09-19**, and it is `G-39` by another name: the webview's own `context-menu` event, `elementFromPoint` at the cursor, `GET /resolve` walking UP to the nearest chunk the trie holds, and Obsidian's own `MarkdownRenderer` in the panel's other face. Measured: 2 ancestors up to an `article`, 199 chars over 10 rendered elements |
| P-B9 | Right-click indexing covers the **static type set only**; interactive components are deferred to tool calls in much later iterations | By design |
| P-B10 | **Dual per-chunk browser + markdown panels are reachable from the projector too** | **Done — seen live 2026-09-19**. Both halves: `G-40` takes the browser to the clicked chunk (parked at scrollY 4945, click moved it to 363) and `G-57` opens the markdown as a billboard beside the node (19 lines, anchored to 0px, follows the camera, pins on a drag) |
| P-B11 | **Straddle the shipped core `webviewer` and take ownership of Electron** as the work proceeds — use it, and outgrow it | **Done** — the cell is a `<webview>` chosen over `BrowserView`/`WebContentsView` because it flows with the DOM and therefore resizes with the panel, and the scanning that used to need Selenium now runs in it (`G-47`) |

### R. Retrieval — the `[]()` gesture

| id | requirement | status |
|---|---|---|
| R-1 | Typing the four symbols makes the bracket contents a **semantic retrieval query** | Confirm — `obsidian-plugin/src/gesture.ts` (`gestureIn`): `[query](` with the paired `)` after the cursor, or `[query]()` before it; three characters or more, never an image's `![alt]()`, never a filled link; `tests/gesture.test.mjs`. The query goes to the workspace's one ranked list (`/search`). live `confirm.mjs R-3` 2026-10-11, in a native note: `[patricia trie]()` with the cursor between the parentheses opened 9 ranked results, 17 after scrolling to the list's foot |
| R-2 | Results in **scrollable whitespace immediately below the line** | Confirm — `linkgesture.ts`: a block under the gesture's line, its list scrolling at 220 px and asking for the next page of the ranking as it nears its foot (`G-69`'s offset); a scroll during a slow page is kept and answered when the page lands (dropped, the list sat at its first page: the first search after a plugin reload took 20 s+ behind the projector), and the list fills itself until it can scroll. The end is the server's own `more`, never a page that did not arrive. live `confirm.mjs R-3` 2026-10-11, in a native note: `[patricia trie]()` with the cursor between the parentheses opened 9 ranked results, 17 after scrolling to the list's foot; scrollable before the click |
| R-3 | The remaining editable lines stay **uninterrupted** — the panel is one cohesive unit. `EditorSuggest` overlays; a CM6 **block widget** reflows | Confirm — built as the design note settled it: a CodeMirror 6 block widget, from a state-computed decoration (CM6 refuses blocks from a view plugin), its DOM owned by one controller so results appended in place keep the reader's scroll; the editor reflows around it. Measured live (`confirm.mjs R-3`, 2026-10-11): the line below moved down **250 px for a 250 px block**, not covered. Planted `plantOverlay` -- the floating `EditorSuggest` shape: the line below moved **0 px** and the results covered it |
| R-4 | Clicking a result **infills the link between the parentheses** | Confirm — the click writes the hit's destination inside the `()` and closes the block: a vault note by its path, a page with an exported note by that note (a markdown-panel link), anything else by its own address (`main.ts` `gesture.destination`, `VaultLinks.noteFor`). Live (`confirm.mjs R-3`, 2026-10-11): the line became `[patricia trie](https://duckduckgo.com/?q=patricia+trie&ia=web)` -- the top hit is a stored search-results page, which is the ranking's answer, not the gesture's; 1 infill, block closed. The exported-note branch is not yet seen live |
| R-5 | **All retrieval comes through this one interface** — web, vault, packages alike | **Partly** — the gesture asks the one `/search` ranking, which holds web pages, vault notes (`vault://`) and source files (`code://`) together; it adds no index of its own. **Not yet ONE interface**: the older `/` gesture (`retrieval.ts`, passages inset with rules) and the projector's retrieval overlay (`G-69`) are retrieval surfaces beside it. Whether they stay is the reader's ruling (*"all retrieval comes from the singular `[]()` interface"*), not removed here |
| R-6 | Package retrieval applies a **vector-centroid pre-filter**, then partition-wise retrieval; the filter must not become a second interface | **Confirm** 2026-10-12 live, real embeddings, 5 code partitions: each query keeps 3 and the package it is about is always among them -- "decode a JSON document" keeps repo/json/urllib (hits json, repo); "HTTP client status codes" urllib/http/html (hits http, urllib); "parse a URL" repo/urllib/html (hits repo, urllib); "escape html entities" urllib/http/html (hits html, http). Built inside the one `/search` ranking (`Search._prefilter_code`): each code root is a partition with a unit-mean centroid; a query keeps the 3 nearest and ranks code only within them; web and vault rows never masked; `SearchDiagnostics.code_partitions` reports it. `tests/test_code_prefilter.py` (3, planted `code_partitions = 0`). |
| R-7 | The docs are updated to match this gesture wherever they disagree | Done — 2026-10-11, a search of every doc for the gesture: `docs/OBSIDIAN_BRIDGE.md` named the `/` gesture as THE retrieval gesture -- it now names `[]()` (`gesture.ts`, `linkgesture.ts`) and marks `/` as the older surface awaiting the `R-5` ruling; `docs/NOTEBOOK_PANEL_DESIGN.md`'s sketch drew `[[]]` (Obsidian's wikilink) as the gesture, now `[query]()`. `PLUGIN_GOAL.md`'s design note already described the built shape |

### L. The minimal embedded chat

Deliberately small. Everything below is the whole of it; the chained
single-hop architecture from the first statement is **not** in scope here.

| id | requirement | status |
|---|---|---|
| L-1 | A **quantized** small model — Nous Hermes 2 DPO 7B on local CUDA | Open |
| L-2 | Embedded **within the notebook panels**, at the bottom of the selected cell — markdown, code, or terminal/kernel | Open |
| L-3 | Context **begins at the last-most viewable cell in the current selection** and **rewinds backwards** through the notebook | Open |
| L-4 | It rewinds over the notebook **in its current state**, including terminal and kernel output — which is the norm for intermediate cells | Open |
| L-5 | The prompt/response panel **hovers and follows the scroll** | Open |
| L-6 | A **new rewind only when the cursor lands on a new cell**, not on scroll | Open |
| L-7 | The rewind is **injected into the user prompt** as the effective contextual history | Open |
| L-8 | The **user prompt decides how many further chunks** to rewind | Open |
| L-9 | Rewind size stays within a **safety factor of the max input token limit**, so sessions continue without compaction or one-shot restart | Open |
| L-10 | Also available **hovering over the native markdown panels** | Open |
| L-11 | Deferred by name: cell/code navigation, running things in the terminal, writing updates back to notebooks | Deferred |

### X. How the work is done

| id | requirement | status |
|---|---|---|
| X-1 | **Search GitHub for working codebases and examples at every step** — *"the most important drivers of success"* — so the code the model uses to touch the interface is visible | Standing |
| X-2 | Verify in the running app over devtools, **never by screenshot** | Standing |
| X-3 | Where a document contradicts the goal, the **document** changes | Standing |
| X-4 | Measure the distribution **before** writing an acceptance criterion | Standing — four criteria here were written first and all four were wrong |
| X-5 | Cleanups gate on **`accounted`**, not `covered` | Standing |

**X-6 — the build order is given, and it is not the order of these tables.**

The addendum states it as a sequence, so it is a requirement and not a
suggestion: the **native Obsidian markdown panel is the substrate**, and
everything is grown from it — *"we essentially build the native obsidian
markdown out into this more fully fledged interactive panel"*.

1. native markdown panel, kept in native form (P-M1)
2. + the same retrieval (P-M2)
3. + code, kernel and terminal options (P-M3, P-N)
4. + the hovering chat (L-10)
5. + **interactive web browser cells — explicitly "the final step"** (P-B)

P-M and P-N are therefore not peer panel types: P-N is P-M grown, and the
native form survives alongside it. P-B is last because *"the way browser
interactions and dual panel views work is slightly different, and particularly
so."*

**X-7 — Addendum II refines that order for the near term.** It does not
replace X-6; the notebook panel still grows from the native substrate and
browser cells still come last.

1. **Re-cut the corpus at 256** — done first so nothing downstream is measured
   against a window the goal no longer names.
2. **Verify the duplication capabilities** — §M.1 and §M.2 above; *"at least
   verify the capabilities of to explore"*.
3. **Notebook kernel panel design, nailed down first** — *"we move onward to
   the notebook kernel panel design first to nail it down correctly"*.
4. **Bring the Electron sensor in when ready** — the phrase is *"when ready"*,
   so S-13's verdict gates this rather than a date.
5. **Then the hovering SLM bar** — *"then, we go for the hovering SLM bar
   itself and work out the details"*.

Note what moved: the hovering chat was item 4 of X-6 and is item 5 here,
behind the notebook panel. Nothing was dropped.

---

## Part II — measured findings

Everything below is evidence for Part I, kept under the `R-*` ids it was
recorded against. Those ids no longer number requirements; they anchor
measurements. Where Part I cites a number, it comes from here.

## A. The panel — the artifact view

| # | Requirement | Status |
|---|---|---|
| R-A1 | "interactive interface that is slim with the markdown-centric chunks with interactives themselves" | Done |
| R-A2 | "distilled DOM rendered as interactive obsidian object structures … as shown by the rendered and interactive fields where 'properties' is" | Done |
| R-A3 | "we don't need 'properties' at the very top of each panel … remove this top panel" | Done |
| R-A4 | "at the very top of each panel, we can have a simple switch between the markdown and the shadow DOM button" | Done |
| R-A5 | The panel occupies the top of the note *(implied by R-A3: the panel takes the place properties vacated)* | Done |
| R-A6 | "the whitespace could be a little tighter to border the content" | Done |
| R-A7 | "there is quite a bit that is duplicated/exploded" — a chunk draws each thing once | Done |
| R-A8 | "remove the duplicate prose below the panel" | Done |
| R-A9 | "Images, interactive fields rendered properly" | Done |

**R-A2** renders into a shadow root carrying its own stylesheet, written in
Obsidian's own custom properties so a control follows the reader's theme.
Obsidian's native property rows are the visual reference.

**R-A3** is the vault setting Obsidian's own Appearance pane writes
(`propertiesInDocument: hidden`), not a plugin reaching around it. The
frontmatter stays — `cid` is what the graph, the link map and the chunk pane
resolve on — it is only not drawn.

**R-A4** shows *both* states with the live one marked. A single button
labelled with the other state is ambiguous exactly where it matters: it can
equally mean "you are looking at markdown" and "press for markdown".

**R-A6** verified 813px → 183px on one chunk, old spacing against new on the
same content.

**R-A7** verified live: 5 lines, 5 distinct, nothing repeated. A product card
had been drawing its title five times — the image's alt, the picture's
caption, the wrapping div's visible text, the anchor's `title`, and the
heading. All five are real addresses; markdown must spend a line on each
because a line is all markdown has, and HTML need not.

**R-A8** folds the prose into a collapsed callout rather than deleting it. A
callout is a blockquote, so the wikilinks in it are still parsed into the
graph, Obsidian's search still finds the words, and the file stays a
plain-text archive. Deleting outright would cost every vault edge unless the
links moved to frontmatter.

---

## B. Two forms, one distillation

| # | Requirement | Status |
|---|---|---|
| R-B1 | "markdown-centric chunks … **or** a more pure html extension to render original web content directly but still in distilled, organized, and slim minimal-html chunks, where we can keep the interactive and the static/media asset components" | Done — both |
| R-B2 | "Switch between read-only interactive web elements and markdown distillation renderings" | Done |
| R-B3 | "aligned to the same graph RAG database with triple retrieval" | Done |
| R-B4 | "a simple button or hotkey" | Done |

**R-B1** was offered as an either/or and both were built. The markdown form
*reconstructs* widgets from a rendering; the HTML form emits an `<input>`
because the trie says the element is a control. Both are built from **one
payload** — the same line-to-address alignment used twice — so a chunk cannot
say one thing in one form and something else in the other.

**R-B4** ships the switch and a command. No default hotkey: Obsidian asks
plugins not to claim one, and a conflict is silent.

---

## C. Structural fidelity — the weakest area

| # | Requirement | Status |
|---|---|---|
| R-C1 | "If there is a possible way to retain as much as the original web interface while keeping the distilled html something that could be rendered, that would be a big deal" | **Partial** — reach 35.2% |
| R-C2 | "the structures like boxes and nested things can stay and be reconstructed from the patricia trie path nodes perhaps if we stick to absolute xpaths" | **Partial** — reading order 76% |
| R-C3 | "matching cartesian coordinates kind of thing on the page (as in we keep all our structures distilled, but localized enough still such that we can render them as their intended cohesive structures)" | **Partial** — see the constraint below |
| R-C4 | "switch to a more generalized xpath structure that keeps absolute structure with agnostic array indices for multiple/repeat fields like menu items, paragraphs, search results" | Done — as a second field, not a replacement |
| R-C5 | "chunks should be at their context window limits and measured using markdown renderings for token counts" | **Partial** — one chunk is 15x the window |
| R-C6 | "Our chunking should be such that, for example, we get search results as singular chunks" | Done |
| R-C7 | "…and semantic + frequency vectors" | Done |

### Acceptance criteria for the partials

**R-C1 — reach ≥ 60% mean.** Today 35.2%. Some of the gap is deliberate
(dedup, suppressed taxonomies, hidden elements) and some is loss; nothing yet
separates the two, so the first task is to classify the unreached elements
before trying to reach them. A reach number that rises by un-suppressing noise
would be worse than the one it replaced.

**R-C2 — reading order ≥ 95%.** Today 76%: a quarter of chunks draw their
elements in an order the page does not present them in. Reading order is the
one structural property a reader notices immediately.

**R-C3 — a stated constraint, not a shortfall to close.** The sensor captures
**no box geometry, by design** (`tests/test_no_box_geometry.py` enforces it),
so literal cartesian coordinates are not available and cannot be without
changing the sensor's contract. What stands in for them is *containment*: the
distilled tree's nesting is the page's grouping, and the record rule (R-C6)
makes each group a chunk, so a chunk arrives already localised to one cohesive
thing. A group holding one picture with words beside it is drawn as a card.
**Accepting containment-as-geometry, or changing the sensor to capture boxes,
is a decision for the user — not one to settle by implementation.**

**R-C5 — the window is not enforced on a single oversized VALUE.**

Reported by the user, who opened the note; the board had it as MET. The
metric was `chunks_over_window`, which counts how MANY chunks exceed the
window and never by how much, so 1.2% read as met while one chunk sat at
**7,745 tokens against a window of 512 — fifteen times over**. The board now
carries `worst_overflow_ratio` beside it, with a bar of 1.5x, so this cannot
hide again.

It was read first as a chunking problem -- one value too big to cut -- and an
offset-splitter was written for it twice, and reverted twice, because the
worst chunk did not move. The user's own reading was the correct one:
**under-chunking**. Not a value that resists division, a value that should
never have existed.

data.gov.uk's publisher filter is a `<select>` of 1,511 `<option>` elements.
The tagger names a control with `_own_label`, which walks every descendant --
right for `<button><span>Menu</span></button>`, wrong here, because a
listbox's descendants are its OPTIONS, and the tagger already emits each one
as its own `interactive.inputs` detection at its own xpath. So the option list
was recorded twice: once as 1,509 addressed lines, and once more as a single
43,542-character label on the select. The reader got a wall of text with one
address for 1,511 things, sitting beside the same content properly addressed.

The browser is the authority on what a collapsed select draws, and
`analytics/groundtruth.py` already wrote the rule down -- "a `<select>` draws
the one value it holds". `_chosen_option` makes the tagger agree: the option
carrying `selected`, and otherwise nothing. Falling back to the first option
was tried and rejected as a fabrication -- this filter opens on an empty
`<option value="">`, so the box a reader sees is blank, and naming it after
the first real entry would report a filter as applied when it is not. The
control still renders (`[ ] select`), and the `<label for=publisher>` beside
it still says `Publisher`.

Measured over the frozen corpus, in-process, with the change toggled on
identical input:

| | before | after |
|---|---|---|
| worst chunk | 7,745 tokens (**15.1x**) | 2,997 tokens (**5.9x**) |
| chunks | 22,504 | 22,500 |
| distinct addresses | 335,982 | 335,982 |
| covered addresses | 287,763 | 287,762 |
| `chunks_over_window` | 0.72% | 0.72% |

Four chunks disappear -- the four aggregates, on the corpus's four listboxes.
No address is lost from the trie.

**What remains, and why it is a different problem.** The new worst chunk is
Project Gutenberg's *Pride and Prejudice*, `/html/body/p[1099]` -- Darcy's
letter, one genuine paragraph of 2,997 tokens. That IS a single indivisible
unit, and it is the case the offset-splitter was really for. Two constraints
bind any such split and the reverted attempts held neither:

* It cannot consult the window. `test_no_address_is_lost_when_the_window_
  changes` holds that the covered address set is identical at every setting,
  so cutting at the window would mint window-dependent addresses -- 713 of
  them, measured.
* It must run where every path sees it, not inside `_emit_runs`.

The vocabulary is already there: `text()@412` is a documented accessor form
and `sensor.js` cuts long text into budget-sized pieces addressed by offset.
The offline path does not yet.

Acceptance: `worst_overflow_ratio` <= 1.5x with the covered address set
unchanged across windows.

**R-C4 — the measurement, and what it says.**

    addresses                   23,654
    distinct by shape            2,831   (88.0% fewer)
    shapes covering >1 element   1,290   median 5, p90 31, max 1511
    of those, holding DIFFERENT content
                                 1,022   (79.2%)

The premise holds: the corpus really is mostly repeated templates. The naive
form does not: four shapes in five cover elements that say different things,
and `/html/head/script` alone covers three unrelated script urls. An address
is a *pointer* — the REPL presses it, `enact` resolves it against a live DOM,
the store keys chunks on it — and a shape cannot point at either sibling.

**The design that follows:** keep the indexed absolute xpath as the identity,
add the shape as a **second, derived field** on `ContentAddress`. Additive, so
no key changes and no rows migrate — the same rule `render_class` already
follows. It buys grouping across repeats, retrieval by template ("every result
row"), and stability across re-scans, since an inserted sibling shifts every
index and no shape.

**What it will not fix:** of the 420 duplicate chunks, only 97 are the same
template on the same page. Most duplication in the projector is repeated
*content* at unrelated places, which wants content-hash dedup — a separate
change (R-E3a below).

---

## D. Graph and links

| # | Requirement | Status |
|---|---|---|
| R-D1 | "plugs into Obsidian graph view" | Done |
| R-D2 | "Align markdown graph view links with web links with web chunks" | Done |
| R-D3 | "Clickable markdown deciding which vault artifact to inline hyperlink via the panel's full patricia trie address" | Done |
| R-D4 | "Source the right other plugin packages first to see how they work, then fork findings over" | Done |

**R-D1** deliberately does not touch Obsidian's own graph view. It has no
plugin API, and the one community plugin that extends it patches undocumented
internals and warns in its own README that settings can be lost. Real
wikilinks in real notes make the native graph work for free.

**R-D4** produced the decision behind the shadow root: of Obsidian's
HTML-rendering plugins, those taking *arbitrary* markup all sandbox in an
iframe, because arbitrary markup carries scripts. `html-blocks` is the
exception and uses a shadow root per block, for style isolation. Ours is
neither arbitrary nor scripted, so the iframe's isolation buys nothing and
costs the two things that matter — event wiring to trie addresses, and
Obsidian's CSS variables reaching in.

---

## E. The 3D projector

| # | Requirement | Status |
|---|---|---|
| R-E1 | "equivalent-dimensional pre-UMAP concatenations of the frequency vectors to the same dimensionality as the semantic ones, and then a final-stage concatenated UMAP with equal information dimensions" | Done |
| R-E2 | "some HSV dimensions as well to the UMAP to make it 6D" | Done |
| R-E3 | "Image and media billboards for distilled HTML" / "images should show in the 3D viewer" | **Done — seen live 2026-09-19** — `G-15` (media present in the projector) and `G-21` (a billboard is COLLIDED as a panel, half-diagonal, not as a sphere — sizing them as spheres left 96 overlapping pairs) |
| R-E4 | "For each 3D node … when I click, I should only see the chunk itself as either structured markdown or interactive HTML" | Done |
| R-E5 | "3D projector has no viewable nodes" — the view must show its nodes | Done — **re-broken and re-fixed**, see R-J4 |

**R-E1** verified: `frequency + semantic · equal halves of 768 · equalised
true`, on real nomic vectors.

**R-E2** spends three of six components on hue, saturation and value from the
*same* fit. Colour was a hash of the host, which is a legend, not a
measurement. `fitted_dims` is reported beside `requested_dims` and the colour
is dropped when the fit could not produce it — asserted from the measured
width, never from the intention.

**R-E3 acceptance: ≥ 95% of nodes carrying a picture render it.** Today 74%.
The 66 failures are dead asset urls in a frozen corpus, not a code path — a
live re-scan is the test, not a fix.

**R-E5** was a real failure with two causes, both worth keeping in view: the
projection arrived off-origin at a scale that moved with the corpus, and
`zoomToFit` only adjusts distance along the current view direction, so a
camera inside the cloud is "fitted" from inside it. Measured: 0.32% of pixels
lit from inside, 5.56% from outside. The layout is delivered centred in a
known cube and the camera is *placed* before it is fitted; a **recentre**
button exists because a reader who orbits inside has no way back.

### Proposed, not yet requested

**R-E3a — content-hash dedup of chunks.** 13.4% of chunks are exact markdown
duplicates, and walking four hops from a real article lands on two distinct
nodes both reading "Games". This inflates the projector and the embedding
matrix. Flagged here because it was *observed*, not asked for; it needs the
user's call, since two identical chunks at different addresses are arguably
two real things.

---

## F. Retrieval and editing

| # | Requirement | Status |
|---|---|---|
| R-F1 | "a `/` gesture in the markdown panel rendering a Kindle/Kobo-style inline retrieval template" | Done |
| R-F2 | "Retrieval interlaced with content editing" | **Partial** |
| R-F3 | Triple retrieval — frequency · semantic · pagerank | Done |

**R-F2** inserts a retrieved passage into the note with its wikilinks
rewritten. What is not built is the *interlacing*: retrieval does not follow
the cursor, and editing does not re-fire retrieval. Acceptance is undefined
until the user says which of those two directions matters.

---

## G. The live-browser port

| # | Requirement | Status |
|---|---|---|
| R-G1 | "Selenium navigations ported from interactions with the shadow DOM distilled in its Obsidian form" | Done |
| R-G2 | "so the user scrolls and interacts in Obsidian while the Selenium remote browser does the real scanning" | **Superseded** — answered the other way and better: the reader scrolls and interacts in a browser that is INSIDE Obsidian, and the same surface does the scanning (`G-47`, `P-B2` — `live_capture_on` true while navigating). There is no remote browser to drive, which removes the round trip this row was designing around |
| R-G3 | "or the graph RAG database purely when offline" | Done |

**R-G1** is the one write path in the bridge and it is off by default, behind
four gates: the server flag (`--enact`), the refusal set mirrored from
`sensor.js`, an address that must already be in the store, and same-page-only
navigation. Verified end to end: a control in a note drove Firefox to
books.toscrape and reported `did: press`.

**R-G2 acceptance: scrolling the panel drives the remote browser's scroll and
the resulting delta re-enters the store.** Today `enact` supports
`press | type | read` only. This is the half of the requirement that makes the
vault a *viewport* rather than a remote control, and it is the largest unbuilt
piece of the pivot.

---

## H. Private, and offline

| # | Requirement | Status |
|---|---|---|
| R-H1 | "Interact with artifacts as live or passive shadow DOM surfaces purely locally without internet" | **Partial** |
| R-H2 | "Interactive pages that are completely private?" | Done |
| R-H3 | "endpoint features that may or may not be locally runnable without internet connections" | **Open** |

**R-H2** is a property of the design rather than a setting: the sidecar is
loopback-only, the notes are files, retrieval and the graph run against the
local store, and the distilled HTML fetches exactly one kind of thing — a
picture — which is off by default. Fetching a page's assets from a vault tells
those hosts the page was read again, at a new time, from a new address.

**R-H1 acceptance: reading, retrieval and the graph work with no process
running.** Today the notes and the native graph do; the panel and the 3D view
need the loopback sidecar. Closing this means either shipping the chunk's HTML
into the note (which reintroduces the duplication R-A8 removed) or accepting
the sidecar as part of "local".

**R-H3** is untouched. A chunk is a readable, pressable surface, not a
self-contained runnable one.

---

## I. How the work is done

| # | Requirement | Status |
|---|---|---|
| R-I1 | "Enforce using MCP/plugin based devtools that can be searched and installed rather than screenshots whatsoever please" | Done |
| R-I2 | Search Obsidian's catalogue *and* the web before building *(paraphrased from two prompts)* | Done |

**R-I1 is binding and has a reason.** A screenshot answers less than a probe
and captures whatever else is on screen. Verification runs over CDP against
the live renderer — the plugin registry, the command list, the workspace, the
DOM, computed styles, WebGL draw calls. `obsidian-plugin/cdp.mjs` and
`probes/` are the instrument.

Two traps that made a working plugin look dead, both now handled in `cdp.mjs`:
Chromium suspends layout in an **occluded** window — a terminal in front of
Obsidian is enough — so every measurement returns zero; and Obsidian keeps a
**hidden source-view copy** of every rendered block under a `display:none`
ancestor, which `document.querySelector` finds first.

---

## J. The projector must be legible

From `PLUGIN_GOAL.md`: *"We also need to pay attention to inter-spatial
normalization on UMAP nodes since most are way too compressed together to see
anything discernable."*

| id | requirement | status |
|---|---|---|
| R-J1 | Adjacent nodes must be **visually separable**: the median nearest-neighbour distance is at least one rendered node diameter | **Done — seen live 2026-09-20** (`confirm.mjs`). Measured on the drawn picture: median gap **86.25** against a median diameter of 66.01, **ratio 1.31**. And the number underneath it: **0.86 before collision** — the FIT alone does not satisfy this row, the collider does, which is what `G-20`/`G-21` exist for and had never been scored against this criterion. Measuring `fitX/fitY/fitZ` instead reports 0.86 and reads as a failure of the picture a reader never sees |
| R-J3 | The tightest crowding is duplicate content, not projection, and is answerable to `duplicate_chunks` — not to a spatial fix | **Open** |
| R-J4 | The camera frames the cloud from the DATA, never from node radius | Done — 0% → 100% of nodes on screen |
| R-J2 | Node size follows the layout's **real local density**, not an assumed uniform spacing | **Partly** — size VARIES rather than being uniform (spread 90.2 across the page nodes, `confirm.mjs` under `R-J1`), and that much is the defect this row was written against. But it varies by CONTENT — `val` is the chunk count a node stands for — not by the density around it. A node in a crowded region and a node alone in space draw the same size for the same content, so the second half of the row is not built |

**R-J1 — measured, and it is not one bug but two assumptions 27x apart.**

Over the 3,135-node layout the sidecar serves today:

| | value | as % of the 882.5-unit bounding diagonal |
|---|---|---|
| nearest-neighbour p05 | 0.090 | 0.0102% |
| nearest-neighbour p50 | 0.757 | 0.0857% |
| occupancy, 32^3 grid | 182 of 32,768 cells | **0.56%** |
| half the nodes | 37 cells | 0.11% of the box |

The extent is NOT the problem, which matters because that is what was fixed
last time: `_EXTENT` centres and scales the cloud into a known cube, and the
cube is duly 600 x 540 x 356. Rescaling a clumped cloud leaves it clumped.
What is wrong is the distribution inside the cube.

**Half of it is one parameter.** `build_layout` passes UMAP's default
`min_dist=0.1`, which is the tight-packing setting. Refitting the same
vectors, same seed:

| min_dist | nn p50 % | nn p05 % | occupancy % | busiest cell | half the nodes in |
|---|---|---|---|---|---|
| **0.10** (ours) | 0.0733 | 0.0093 | 0.45 | 119 | 24 cells |
| 0.35 | 0.1786 | 0.0521 | 0.70 | 112 | 36 cells |
| 0.60 | 0.3353 | 0.1160 | 1.63 | 47 | 96 cells |
| 0.90 | 0.4445 | 0.1757 | 2.11 | 33 | 123 cells |

Monotone: 6.1x on median separation, **19x on the 5th percentile** — the
crowding that actually hides nodes — and 4.7x on occupancy, for one number and
a refit. It trades cluster tightness for even spacing, which is the right
trade for a surface whose job is browsing.

**R-J2 — and it is still not enough, because the renderer sizes for a cloud
it does not have.** `graph.ts` computes `spacing = 2 * extent / cbrt(n)` and
`relSize = spacing / 8`, with radius `cbrt(val) * relSize`. That is the
spacing of a *uniform* cloud. At n=3,135 it yields a node radius of roughly
10-20 units against a measured median separation of **0.76 units** — the
renderer is sized for neighbours about 27x further apart than they are, so
every node is drawn overlapping dozens of others. Even at `min_dist=0.9` the
median separation is only ~3.9 units, still well under one node diameter.

So the fix is both halves: spread the distribution, *and* size nodes from the
layout's real nearest-neighbour distribution rather than from `cbrt(n)`. The
layout already computes the positions; shipping their nn quantiles in the
report costs one `cKDTree` query and removes the renderer's need to assume.

**R-J3 — why the criterion is pinned at the MEDIAN, and was wrong at p05.**

The first version of R-J1 asked for the 5th-percentile separation to clear a
node diameter. That criterion cannot be met and should not be: the tightest
pairs are not a projection failure. Of the closest 5% of neighbour pairs,
**98.7% share a url and 54.5% share a title** — against 7.0% same-title among
the furthest quarter, and 22.8% over all pairs:

| pairs | same url | same title | same token count |
|---|---|---|---|
| closest 5% | 98.7% | **54.5%** | 30.1% |
| closest 25% | 96.0% | 42.3% | 24.0% |
| furthest 25% | 84.6% | 7.0% | 3.3% |
| all | 88.7% | 22.8% | 12.5% |

Those are near-duplicate chunks off one page. Their vectors are nearly
identical, so they land on each other — which is the projection being
*correct*. No `min_dist` and no normalization can separate points that mean
the same thing, and pushing them apart would draw a distinction the data does
not contain. That crowding is answerable to `duplicate_chunks` (13.2% on the
board), which is a chunking metric, and it belongs there.

The median is where the projection actually governs: 0.757 units against 41.0
for a uniform cloud of 3,135 points in this cube — **54x below uniform**,
where p05 is 456x below and mostly duplicates.

**Inter-spatial normalization, measured.** A per-axis quantile transform
(each axis through its own empirical CDF, so the order along every axis is
preserved exactly and only the spacing changes), applied to the layout as
served:

| | as served | quantile-normed |
|---|---|---|
| nn p50 (units) | 0.757 | **3.658** |
| nn p05 (units) | 0.090 | 0.469 |
| occupancy % | 0.56 | **3.41** |
| busiest cell | 71 | 36 |
| 10-NN neighbourhood kept | 100% (ref) | **80.2%** |

4.8x on the median for 20% of the local neighbourhood structure. That trade is
a decision, not an obvious win, and it is recorded here rather than taken.

**R-J4 — the camera was a node-size servo, and it emptied the pane.**

`zoomToFit` frames node bounding SPHERES, so the distance it chose was a
function of node RADIUS and not of where the nodes are. Measured over CDP on
this corpus: at `nodeRelSize` 5.124 it settled at 148.9, at 0.126 it settled at
3.67 — **40.6x apart, exactly the ratio of the radii** — and in both cases the
rendered node came out at 278.9 px. It holds apparent node size constant,
which is the wrong invariant for framing a cloud. With the cloud spanning
+/-380 it put the camera inside: nodes projected to (1076, 1029) and
(1323, 1718) against a 518 x 840 canvas, **0 of 3,135 on screen**. R-E5 was
marked Done and was not.

Replaced with a distance computed from the data: the layout centres on the
origin, so the cloud radius is the furthest node, and `R / sin(half-angle)`
puts a sphere of that radius in the frustum — the binding half-angle being the
smaller of vertical and horizontal, since a sidebar pane is usually taller than
it is wide. Verified: cloud radius 380.3, camera 1529.0, **3,135 of 3,135 on
screen**.

**R-J1/R-J2 — the criterion is satisfiable and insufficient, and now the gap
is a number.**

With R-J4 in place the sizing change was re-applied and both numbers held at
once: 100% on screen AND `nn_p50 / diameter` = 1.000. It still does not ship,
because at a camera distance of 1529 framing a radius-380 cloud one world unit
is 1.70 px, so a median node of 0.757 units draws at **0.45 px** — correct,
and invisible.

Legibility is two-sided, and the renderer can only satisfy one side:

* clear your neighbour — `diameter <= nn_p50`
* be visible — `diameter >= ~2 px`, which is 3.40 world units here

Both hold only when the median separation is at least **~4.5x** what the fit
delivers today (0.757 units, needs ~3.40). That is a projection change, not a
renderer one. Two candidates are measured above and either would clear it:
`min_dist=0.9` gives 6.1x on the median, and the per-axis quantile transform
gives 4.8x for 20% of the local neighbourhood structure. **This is the
decision that unblocks both R-J1 and R-J2.**

**Acceptance:** `nn_p50 / node_diameter >= 1.0`, computed from the layout the
sidecar serves and the renderer's own sizing, verified over CDP. Today that
ratio is **0.037** (0.757 units against a 20.5-unit diameter). R-J2 is the
half that closes it: a diameter taken from the layout's own `nn_p50` satisfies
this by construction, and means half of all nodes clear their nearest
neighbour instead of the renderer guessing a spacing the data never had.

## K. The markdown half, against the stated bar

`PLUGIN_GOAL.md` names the Milkdown playground's left pane as the quality
standard and gives its negative form, which is the testable half:

> *"no dedups, headers and structures within markdown structures are
> appropriately and most simply matched without things like intermediated
> hierarchical fields when a singular path node of some form of structure like
> that is rendered from its shadow DOM and interactive browser half"*

Measured over all 3,135 exported notes -- the artifacts a reader actually
opens, not the renderer in isolation.

| id | requirement | status |
|---|---|---|
| R-K1 | No intermediated hierarchical fields: a level of indentation holds more than one child, or it does not exist | **Confirm** 2026-10-11 — seen in the app: the running sidecar stored a fresh capture of Okapi as 182 chunks, 1,887 lines, **0 with an empty indent level, 0 starting indented** (read back through `/chunk`, whose lines carry their indentation). Built and measured: `markdown.py::_level_page` now levels each chunk from its own lines' parents (a line one step below the nearest preceding line drawn shallower; none, the margin), where the page-wide mapping left an empty indent wherever a depth branched elsewhere on the page. `python -m vertiscope.analytics.levels` (2026-10-11, all 136 frozen pages rendered fresh, 14,859 chunks): chunks with an empty level **38.23% -> 0%** (24,647 lines under one -> 0), chunks starting indented **87.44% -> 0%**; containment **98.31% both arms** (51,235 of 52,117 ancestor pairs); depth rho 0.916 -> 0.902 (cousins at different page depths now drawn level under one parent). Planted `PLANT_PAGE_LEVELS` reproduces the filed 39.0%. `tests/test_levels.py` |
| R-K2a | No contentless lines: a unit with neither words nor a target is not drawn | **Partly** — FOLDED, not dropped (2026-10-11): `markdown.py` `_fold_contentless` moves a bare-mark line's address into a worded line of the SAME element as an INLINE address, which `covered` counts -- the drop (built and reverted, below) put it in `absorbed`, which it does not. Element-scoped inside one rendered subtree, which holds every unit of its elements: the same at every window. `python -m vertiscope.analytics.contentless`, all 136 frozen pages fresh: contentless lines **4,399 -> 2,980 (-32.3%)**, covered addresses **272,672 = 272,672**, pages losing any covered address **0**. Planted `PLANT_KEEP_CONTENTLESS`. `tests/test_levels.py`. The 2,980 left are elements whose ONLY rendering is a mark (inline `<svg>`, nameless forms) -- removing those is the tagger's question below, not the renderer's |
| R-K2b | A chunk showing what the page itself repeats — faithful, or noise? | **Open** — a decision, 88% of the repeats |
| R-K3 | A control's name is the page's word for it, never the taxonomy's | Done — 1,556 → 2 lines |

**R-K1 — 39.0% of chunks, and the cause is that the collapse is global where
the property is local.**

| | |
|---|---|
| chunks with a pass-through level | 1,223 of 3,135 (**39.0%**) |
| such levels | 3,212 (1.02 per chunk) |

`_level_page` maps the set of depths that OCCUR ON A PAGE onto consecutive
integers, so "a chain of five wrappers costs one step instead of five" holds
only when those depths appear nowhere else on that page. On a real page they
do: the same depth carries genuine branching in another chunk, survives the
compaction, and still spends an indent in the chunk where it holds a single
child. `htmlform.py::_collapse` does not have this problem because it works on
the node tree locally -- and its own docstring credits `_level_page` with
already doing the job, which is the belief this measurement corrects.

Acceptance: pass-through levels <= 2% of chunks, with `reading_order`,
`containment` and `depth_rho` unmoved.

**R-K2 — split, because the measurement says it is two things and the bar
can only be asked of one of them.**

The criterion first written here -- "chunks with a repeated line <= 2%" -- was
set before the repeats were looked at. Over 40 corpus pages, 1,438 of 10,014
chunks (14.36%) hold a repeat, and those repeats decompose:

| | lines | share |
|---|---|---|
| the page genuinely says it twice | **5,161** | **88.0%** |
| contentless -- mark only, no words | 703 | 12.0% |

So 2% is not reachable by removing renderer artifacts. Suppressing every
contentless line takes the figure from 14.36% to about 11.6%, and the rest is
the document repeating itself: a nav label in the header and again in the
footer, inside one chunk.

**R-K2a is the renderer's, and is a defect.** 703 lines carry a mark and
nothing else -- `![]` x551, `<#>` x72, `===  ===` x39, `[ ]` x11, and `![]
![]` x7 where two placeholders were inline-merged. A media unit with no alt
and no source, a link whose href is `#`, a form with no name: each says only
"a detector fired here", and drawing it fifteen times says it fifteen times.
279 chunks have no other kind of repeat, so this alone is 2.79% of all chunks.

The fix is not simply to drop them: a unit that draws no line leaves no
address, which is the failure `_suppressed_controls` exists for -- 89.8% of
anchor affordances were lost that way once. The line goes and the address
rides on `absorbed`, the mechanism already built for exactly this.

Measured over 40 corpus pages: **1,671 contentless lines, 2.27% of all
lines** -- `![]` x1,377, `===  ===` x159, `<#>` x85, `[ ]` x28, and a tail of
`![] ![]`, `</>`, `(  )` where two placeholders were inline-merged.

They split on whether dropping one costs an address:

| | lines | |
|---|---|---|
| another line survives at the same element | 782 | 46.8% |
| the only line at its element | 889 | 53.2% |

**And the obvious implementation is forbidden, which is the finding.** The
natural pass is chunk-level: walk a chunk's lines, drop a bare mark when
another line in that chunk shares its xpath, and hang the address on the
survivor. Two things kill it.

`absorbed` is deliberately NOT counted by `covered` -- its own comment says
why: "coverage must not move with the context window ... counting a collapse
as covered therefore made the set window-dependent by four addresses at
window 200, twice". So moving an address there LOWERS `covered`, which is the
opposite of the acceptance criterion.

Worse, the test itself is window-dependent. Whether another line at the same
element is in the same chunk is a fact about where the chunker cut. A rule
keyed on that would drop a line at one window and keep it at another, and
`test_no_address_is_lost_when_the_window_changes` exists for precisely that.

This codebase has made the same correction twice already, and written it
down: "a pass whose result must not depend on the descent belongs outside it"
(`_absorbed_by_element`), and the same reasoning in `_suppressed_controls`.
So the rule has to be **element-scoped over the trie**, where `_dedupe`
already lives: a unit that renders to a bare mark is dropped when another
unit AT THAT ELEMENT renders with words -- a property of the document, true
at every window.

That still only reaches the 46.8%. The remaining 889 are elements whose only
rendering is a mark: 643 images with neither an alt nor a source, 113
nameless forms, 84 links whose href is `#`. Those are upstream -- a media
detection with no alt and no src describes nothing, and the question is
whether the tagger should emit it at all.

**And the renderer cannot be where this is fixed.** `_dedupe`'s drops land in
`absorbed`, which `covered` excludes by design, so dropping 782 lines drops
782 covered addresses. "Contentless = 0 with `covered` unchanged" is not
achievable by dropping a line at all -- the line and the address are the same
thing at that point. There is also a reverted attempt on record at the
`_dedupe` call site: a containment-chain rule that hid repeated names, costing
"about a point of deduplication for four units of *loss*", with the verdict
"a rule that trades coverage for tidiness is the wrong trade at any exchange
rate". This one is different in kind -- it drops renderings that carry no
words at all, which is the "reason beyond `these strings match`" that comment
asks a future rule to have -- but the coverage arithmetic is the same and
rules the renderer out.

**Upstream, the detection itself is redundant.** Over 40 corpus pages, 1,634
of 4,404 media addresses (37.1%) have neither a source nor an alt, and their
value is literally the element's tag name. Counting every media `text()`
detection valued at its own tag: **2,245**, on `svg` x732, `img` x376,
`source` x370, `picture` x91, `video` x63.

`srcset` is NOT the gap -- the tagger already splits it into indexed
candidates, so a `<source>`'s real URLs exist as their own addresses. The
contentless thing is a SECOND detection at the same element whose accessor is
`text()`, on an element that has no text, falling back to the tag.

| | detections | |
|---|---|---|
| element keeps another address without it | **1,368** | 60.9% |
| element would lose its only address | 877 | 39.1% |

The 877 are `<svg>` x725, `<picture>` x91, `<video>` x60 -- an inline SVG
genuinely is a graphic with no source, and its address is the only thing
saying one is there.

**Built, measured, reverted.** The rule was implemented in the tagger exactly
as specified -- drop only where the element retains another address -- and it
did what it promised on its own terms, over 40 corpus pages:

| | before | after |
|---|---|---|
| addresses | 140,395 | 139,027 (**-1,368**, the predicted count) |
| distinct elements | 65,943 | **65,943** -- nothing orphaned |
| contentless lines | 1,671 | **949** (-43.2%) |
| chunks with a repeat | 14.36% | **12.71%** |
| **covered addresses** | 118,387 | 116,484 (**-1,903**) |

Coverage fell by 535 MORE than the addresses removed. Diffing the covered sets
over 12 pages: 589 addresses removed from the trie, 929 lost coverage, so
**340 addresses that still exist stopped being accounted for** -- 265
`media.images` and 75 `text.accessible`.

That is the trade `markdown.py` refuses at its `_dedupe` call site in exactly
these words: *"a rule that trades coverage for tidiness is the wrong trade at
any exchange rate."* 722 fewer contentless lines for 340 lost addresses is
that trade. Reverted.

**The mechanism is not understood, and two explanations have been wrong.**
The first guess was that the `![]` line is a carrier -- that the element's real
`src` and `alt` ride on it as `inline` -- which would make it contentless only
in appearance. Checked: all 819 `![]` lines carry **zero** inline addresses.
So that is not it either. Removing a detection also moved 105 chunk boundaries
and 2,177 lines, far more than the 1,368 detections removed, so something
downstream of the trie is reacting to the removal in a way neither guess
predicted.

Acceptance is unchanged in intent, but no further attempt should be made until
that mechanism is identified: a change that reduces coverage by an amount its
author cannot explain is not ready regardless of what it improves.

**R-K2b is not a defect and is not mine to decide.** 88% of the repetition is
in the page. Rendering it is *faithful*; suppressing it makes the artifact
cleaner than the thing it distils. The goal says "no dedups" in a list about
elegance, which reads as "the panel should not show the same thing twice" --
but this renderer's standing direction is the opposite, tuned "17:1 toward
leaving noise rather than risking loss", and `_dedupe` is element-scoped on
purpose. Cross-element dedup inside a chunk would drop addresses that name
real, distinct elements.

The question for the user: when a page puts the same words in its header and
its footer, should one chunk show them once or twice?

**R-K3 — the taxonomy word standing in for a name.**

Lines drew the category as the label: `[ ] input`, `( button )`,
`=== form ===`, and in the media path `![images]` from `address.subcategory`
used as an alt. A reader learns nothing from `[ ] input` that `[ ]` did not
already say — the mark states the affordance, and the tag repeats it in the
detector's vocabulary instead of the page's.

`_echoes_its_element` already answered the question ("is this value only the
element's own tag name") and was used in two places, neither of them the
render. Applying it there, and dropping the `subcategory` fallback on the
media alt:

| over 40 corpus pages | before | after |
|---|---|---|
| category-as-name lines | **1,556** | **2** |
| lines | 73,675 | 73,675 |
| covered addresses | 118,387 | 118,387 |
| chunks | 10,013 | 10,014 |
| chunks with a repeated line | 14.31% | **14.36%** |

*(The corpus-wide figure of 136 quoted earlier came from the 24 exported pages
and a narrower match that missed the `![images]` / `![video]` forms; 1,556 is
the same measurement done properly.)*

**And it made R-K2 marginally worse, which corrects a claim made here.** This
was recorded as "the direct cause of most of R-K2". It is not: removing a
false name does not remove the duplication underneath it. Fifteen unnamed
icons were fifteen identical `![images]` lines and are now fifteen identical
`![]` lines, and a few `![images]`/`![video]` pairs that differed only by
their category now collide — +0.05 points. The gain is 778x on the target and
the cost is 0.05 points on a neighbour, so it ships, but the two are not the
same defect and fixing one does not fix the other. R-K2 needs its own answer:
a unit with neither words nor a target carries nothing, and drawing it at all
is the actual duplication.

Also found, and small: 133 lines (0.56%) say one phrase twice --
`=== Toggle Table of Contents Toggle Table of Contents ===`, `( Change theme
Change theme )` -- from `_own_label` concatenating an element's own text with
a nested element repeating it.

Acceptance: category-as-name lines = 0; doubled-phrase lines <= 0.05%.

## L. What coverage means — the gate every cleanup collided with

Five iterations of markdown cleanup ran aground on the same number, so the
number was examined instead of the changes.

**`covered` answers "what did the render draw". It was being read as "what
does the system account for".** Those differ by `absorbed` — the spellings a
collapse dropped, an `aria-label` beside the text it duplicates, an `href`
hidden because the anchor says the words.

**The store never had the confusion.** `graphstore` maps an address to a
chunk from `address`, then `inline`, then a THIRD pass over `absorbed`, and
says why: reading only the first two "left 37,452 addresses over the corpus
with no chunk at all, 8,167 of them urls, and an edge they could not hang on".
An absorbed address has a chunk, hangs its edge, is findable. `covered` calls
it lost.

Measured over twelve corpus pages:

| | share of the trie's addresses | moved by re-chunking at 128 vs 512 |
|---|---|---|
| `covered` (address + inline) | 89.4% | 46 |
| `accounted` (+ absorbed) | **95.9%** | 227 |

**What this cost.** The nameless-media change (R-K2a) was reverted because
`covered` fell by 340 addresses that still existed. Re-measured against
accounting, it fell by **94**. The gate overstated the damage 3.6x, and a
change was reverted substantially on that.

**And the invariant everyone reasons from is weaker than believed.**
`covered` is not window-invariant either: 46 addresses move between window 512
and window 128 on twelve pages. `test_no_address_is_lost_when_the_window_
changes` passes because it runs on a SINGLE fixture page. Every argument in
this repo of the form "that would make the covered set window-dependent" rests
on a property that does not hold at corpus scale — including two reverts of a
value splitter earlier in this work.

**The settlement.**

* `covered` keeps its definition and its meaning narrows to what it always
  measured: lines drawn.
* `MarkdownChunk.accounted` is added — `address` + `inline` + `absorbed`,
  mirroring the store's three passes exactly, so the metric and the store
  cannot drift.
* **Cleanups are gated on `accounted`.** Gating on `covered` forbids the whole
  class by construction: drawing fewer redundant lines lowers it, because
  that is what such a change means.
* The window-invariance test should be re-pointed at page-level `accounted`
  and run over the corpus rather than one page. It currently certifies a
  property it does not check.

R-K1, R-K2a and R-E3a were all blocked by this and are unblocked by it —
under the correct gate, each still has to prove it costs no accounting.

## M. The two duplications, measured apart

Addendum II flags *"a lot of both duplicate chunks ... and also duplicate
content within the markdown panel renderings"*. Those are two layers, and the
first thing to do with them is refuse to add them together.

### M.0 — the first measurement was wrong, and how

It was taken against `build/vaultws512`. That store was written **2026-09-09
22:38:46**; commit `499fd6d` — *"markdown: the taxonomy is not a name — 1,556
lines → 2"*, which is `M-9` — landed **23:12:36 the same evening, 34 minutes
later**. The corpus had been rendered by pre-fix code.

What that produced: `![images]` appeared 1,575 times and 40% of all in-chunk
repetition was traced to it, so it was filed as **D-7**. On the 256 re-cut,
rendered by current code, **0 of 1,073 media carry a taxonomy placeholder**.
The defect had been fixed three days before it was reported, and `499fd6d`'s
own comment describes the exact symptom: *"a page with fifteen unnamed icons
rendered `![images]` fifteen times, telling a reader nothing except which
detector fired"*. D-7 is withdrawn.

**The rule this adds to `CLAUDE.md`'s list.** *A rendering claim must be
measured against a corpus rendered by the code under test.* The existing rules
cover the page moving (`--drift --kind none`) and the denominator being wrong;
neither covers the **instrument having changed since the corpus was written**.
A store is not neutral evidence — it is a recording of what some past version
of the renderer did, and its mtime is part of its meaning.

The cheap guard: compare the store's mtime against `git log -1 --format=%ad`
for the module whose output is being scored, before quoting a number.

Two further caveats on the numbers below, both stated rather than buried:

- **The corpora differ by one page.** apnews.com refuses automation (403 to
  curl, a 40s navigation timeout) and is absent from the 256 store. It was the
  single largest contributor to every duplication figure on the 512 store —
  removing it alone took bare media from 1,575 to 675 — so no 512↔256 delta
  below is a clean window comparison.
- **Neither store has a link graph** (`links`: 3 and 0). Both were scanned
  without `--follow`, so the pagerank factor is near-uniform and the triple
  product is effectively a pair product. Any retrieval figure taken on these
  stores understates what `G-3` describes.

### M.1 — duplicate CHUNKS: how many, and what they are

Identical rendered markdown at more than one address. **Measured on
`build/vaultws256` (5,337 chunks, 23 pages), current code**, read-only.

| | 256 (valid) | 512 (stale code — reference only) |
|---|---|---|
| duplicate groups | **105** | 147 |
| redundant chunks | **246 of 5,337 — 4.6%** | 163 of 3,135 — 5.2% |
| groups whose addresses are siblings in one parent | **99** | 36 |
| groups in structurally unrelated places | **6** | 111 |

**The duplicates are real; the first diagnosis of them was not.** That middle
row was initially read as an index-shift defect and filed as `D-6`. It is not:
sibling addresses are what a repeated list looks like, and §M.3 shows why the
test could not tell the two cases apart. All 105 groups currently read as
`D-4`/`M-8` — **the page repeating itself** — which Addendum II puts in scope:
*"full deduplication of repeat substrings that are essentially structural
redundancies of the web pages themselves."*

Which pages carry them:

| url | groups |
|---|---|
| developer.mozilla.org/en-US/docs/Web/CSS | 37 |
| archive.org/details/texts | 19 |
| discourse.julialang.org/latest | 17 |
| arxiv.org/abs/1706.03762 | 10 |
| ar.wikipedia.org — Physics | 7 |

That distribution is itself the argument for `D-4`: a CSS property index, a
reference list and a forum's latest-topics page are documents whose *structure*
is repetition. A defect in the delta path would not concentrate there.

The `512 → 256` shift in the last two rows is **not** a change in the page.
A 256-token window cuts more often, so which repetitions come out
byte-identical changes with the window. Both columns are window-conditioned,
which is why §M.3 ends by asking for a measure over content hashes rather than
over chunk boundaries.

### M.2 — duplicate CONTENT: one chunk's render repeats itself

Repeated non-blank lines *within* a single chunk, on the 256 store.

| | 256 (valid) | 512 (stale code) |
|---|---|---|
| chunks with ≥1 repeated line | **211 of 5,337 — 4.0%** | 492 of 3,135 — 15.7% |
| repeated lines | **621 of ~40k — 2.9%** | 980 — 4.1% |
| of those, bare media placeholders | **0** | 389 — 40% |
| of those, a label echoed at both ends | **0** | 91 — 9% |

Both named causes are gone: the first with `499fd6d` (§M.0), the second with
it, since `Deprecated. Not for use in new websites. Deprecated` was the
taxonomy echoing a label it should never have drawn.

What remains is **621 lines with no identified cause**, and that is the honest
state: a residue, not a diagnosis. It is smaller than the flag implied and it
has not been explained.

### M.3 — D-6 withdrawn: the metric could not tell two siblings from one move

The evidence for `D-6` was: *"N% of duplicate-chunk groups differ only by a
positional index in the xpath"*, computed by blanking every `[n]` and seeing
whether the addresses collapsed to one skeleton.

**That test cannot distinguish the two cases it was built to separate.** Any
two siblings share a skeleton once their ordinals are blanked. Looking at what
it actually matched:

```
…/section[12]/div[2]/div/div/ol/li[41]/span[2]/span[3]
…/section[12]/div[2]/div/div/ol/li[69]/span[2]/span[3]
…/section[12]/div[2]/div/div/ol/li[125]/span[2]/span[3]
```

Those are entries 41, 69 and 125 of an Arabic Wikipedia reference list. They
exist *simultaneously* and carry identical text. The page repeats itself —
`D-4` — and the test called it an index shift.

**The `div` vs `div[3]` case that looked decisive was also misread.**
`sensing.py::_name_test` emits a bare tag when the ordinal is 1:

```python
return f"{tag}[{ordinal}]" if ordinal > 1 else tag
```

So `div` *is* `div[1]`, and `/…/div[2]/div/bsp-header` against
`/…/div[2]/div[3]/bsp-header` names the first and third children — two real
containers, each holding a header. Addresses are ordinal-stable by
construction; the sensor's `stepFor` always emits an explicit ordinal and only
the formatter elides `[1]`.

### The instruments that actually answer the question

Both already existed. Neither was used before the defect was filed.

**`--resolvable`** — *"ask the page whether every address in the trie names a
node it has"*. It is the only oracle independent of both the fold and the
walk, which is exactly the independence a claim about phantom addresses needs.

| | |
|---|---|
| pages | 2 (books.toscrape.com, danluu.com) |
| addresses asked | 719 |
| **unresolvable** | **0** — names nothing in the page |
| **mismatched** | **0** — resolves, holds something else |

**`--drift --kind insert`** — mutate, repair, score the repaired trie against a
fresh full map. This is the delta path, which is what Addendum II's phrase is
about.

| page | mutations | recall | **stale** | **lost** | wrong | moved |
|---|---|---|---|---|---|---|
| books.toscrape.com | 1 | 100.0% | **0** | **0** | 0 | 190 |
| books.toscrape.com | 3 | 100.0% | **0** | **0** | 0 | 192 |
| books.toscrape.com | 5 | 100.0% | **0** | **0** | 0 | 194 |

3 of 3 exact. An insertion moved ~190 addresses and **not one went stale** —
`stale` being precisely *"addresses the trie holds and the page does not"*,
which is the defect as stated.

### What this does NOT establish

Stated plainly, because a withdrawal that overclaims is the same error
inverted:

- **One page carried it.** danluu.com was excluded — *"no drawn repeated
  group"*, a page that could not fail. Two pages asked, one scored.
- **Both pages are static.** The flag may well be about pages that move on
  their own, and coinmarketcap's ticker is the known hard case. `--drift` on a
  moving page needs its `--kind none` null arm first.
- **Only `insert` was run.** `delete` and `relocate` are the gestures where a
  pop is most likely to be missed, and `relocate` is the one that matches
  *"reassignment"* most literally.
- **The store-side observation was real even though the diagnosis was not.**
  105 duplicate-chunk groups exist on the 256 store. They now read as `D-4`,
  the page repeating itself, which `M-8` already covers and which Addendum II
  puts in scope. The duplicate chunks the user saw are real; what was wrong
  was attributing them to the index path.

So `D-6` is withdrawn as *not demonstrated*, not as *disproved*. The next run
is `--kind delete` and `--kind relocate`, each against its own `--kind none`
arm, on a corpus that includes a page known to move.

### M.5 — three reported 2026-09-13, then measured

Reported from the app against chunk `98b0c576` of `coinmarketcap.com`, whose
root is `…/table/tbody/tr[91]` — **a table row**, which turns out to explain two
of the three. Measured on `build/vaultws256` (5,337 chunks, current code) before
anything was filed, because `D-6` and `D-7` were both filed from bad
measurements and both withdrawn within hours.

#### M.5.1 — one image, two lines

| | |
|---|---|
| chunks containing media | 835 of 5,337 |
| **same url with an empty alt AND a named alt** | **365** — 44% of them |
| url appearing with only an empty alt | 348 |

**Cause, from the addresses rather than the picture.** Two detections sit at one
`<img>`, and the renderer draws each as its own line:

```
line 0   image | src|media.tag/img   …/td[3]/div/div/a/span/img   ![](…34466.png)
line 1   image | alt|media.tag/img   …/td[3]/div/div/a/span/img   ![PENGU logo](…34466.png)
```

Identical xpath, different accessor. That is not an indexing fault —
`ContentTag`'s own docstring makes `(xpath, category, subcategory, source_attr,
sub)` the key, so `src` and `alt` are legitimately two detections of one
element. **The defect is in the projection**: a url and its caption are one
image, and drawing them as two lines both doubles the media and produces the
"empty image with no text" that was reported, because the line carrying the url
is the one WITHOUT the alt.

**And it is a LIVE-SENSOR defect only, which is the sharper finding.** The two
taggers disagree about what an `alt` IS:

| at one `<img>` | `src` | `alt` |
|---|---|---|
| offline `ContentTagger` | `media.images` | **`text.accessible`** |
| live `sensor.js` | `image` | **`image`** |

The offline path calls the alt TEXT, and the existing element-scoped `_dedupe`
absorbs it into the image's line as a caption. The live path calls it an IMAGE,
so `_RENDER["image"]` draws a second `![…]`. That is why no fixture reproduces
this and why a test built on `index_html` would have passed against the bug —
the bug cannot occur on that path.

This is the recurring class in `CLAUDE.md`'s own terms: **one taxonomy with two
spellings, sensor and tagger.** The projection fix below is correct and
sufficient for the rendering; making the two taggers agree about `alt` is a
separate and deeper question, and is NOT done.

**Fixed** by `markdown._join_media`, a line pass beside `_join_labels`. It merges
two media lines at one element, keeps the address carrying the URL — the url is
the media's identity, what `is_url` reports and a reader clicks — and records the
dropped address in `absorbed`, which exists for exactly this: *"other spellings
of the same fact at the same element… what it needs is to remain findable."*

`_dedupe` could not have done it and should not be asked to. It collapses by
token subsumption and states the rule: *"URLs never collapse against prose…a
link and its label are different data even when the strings coincide."* A url and
its alt ARE a link and its label; they survive that rule by design, and are one
picture all the same — a fact about media, not about tokens.

Two things it deliberately does not merge, each with a test: two different
elements (the reason `_dedupe` is element-scoped — a chunk-scoped version
"collapsed every card in a grid sharing a placeholder image down to one"), and
two different urls at one element, which is a `<picture>` and its sources.

**Verified on a fresh live scan of the reporting site**: 0 same-url pairs
against 365 in the store scanned before the fix.

**What is NOT fixed, stated so it is not read as fixed.** 74 of that scan's 187
media lines still carry an empty alt. Those are images the page gave no alt
for, where `![]` is markdown's own honest form and `499fd6d`'s reasoning says
drawing anything else would be inventing a caption. The report is answered where
a caption EXISTED; where the page supplies none, there is nothing to attach and
the question becomes whether nearby text should be associated with it — which is
`M-4`/`M-10` and not this.

#### M.5.2 — naked fields: a row without its headers

| | |
|---|---|
| chunks rooted at a `<tr>` | 79 |
| **rows carrying ≥3 unlabelled values** | **44** |

`90`, `0.14%`, `0.78%`, `16.00%`, `$455.28M`, `62.86B PENGU`, `-4.07` — every
one a value with no name. The names are real and in the page; they are in the
table's header row, which is not in this chunk because the chunk is the row.

**And the names are recoverable, which is what makes this a defect rather than a
limit.** The addresses carry the column:

```
cell | text()[0] | table.*   …/tr[91]/td[2]/p/text()[1]      90
cell | text()[0] | table.*   …/tr[91]/td[4]/div/span/text()[1]  $0.007242
cell | text()[0] | table.*   …/tr[91]/td[5]/span/text()[1]   0.14%
```

`td[n]` is the column index, and the header for column *n* is the table's
`th[n]`. So a cell can be named by the header at its own position, from the trie,
with no new detection.

Why it matters beyond looking wrong: `M-11` says quality must hold *at the
interactive chunk level, because the chunk is what gets embedded and its
structure decides how representative the vectors are.* A row of bare numbers
embeds as almost nothing — `0.14% 0.78% 16.00%` has no subject — so these 44
chunks are close to unretrievable by meaning, whatever the retrieval stack does.

#### M.5.3 — duplicate chunks, still

Reported as still present. §M.1 counted 105 duplicate-content groups on this
same store and attributed them to `D-4`, the page repeating itself; nothing has
been done about `D-4`, so the report is consistent with that and with the two
findings above, which produce visible duplication inside a single chunk without
producing duplicate chunks.

**Not separated yet.** What is missing is whether the duplicates being seen are
§M.1's 105 groups or the 365 within-chunk image pairs — the two look identical
from the panel and have different fixes. Next: re-take §M.1's count and compare
group-for-group, not count-for-count.

### M.4 — the standing lesson

Two defects filed and both withdrawn within hours, with one shared cause:
**a metric invented for the occasion, when the repo already had an
instrument.** `D-7` was measured against a store older than its own fix; `D-6`
was measured with a discriminator that could not discriminate. `--resolvable`
and `--drift` existed the whole time, and both were built precisely because
this project has made this class of error before.

`CLAUDE.md` gains the first lesson (compare the store's mtime to the module's
last commit). The second belongs beside it: **before writing a measurement,
check whether `vertiscope.analytics` already answers the question.** A fresh metric
has no non-vacuity arm, no null arm, and no history of having been wrong in a
known way — the existing harness has all three.

---

### M.6 — what a picture panel costs the embedding, measured

`G-20` and `G-21` pull against each other and the PRD said nothing about the
exchange rate. A panel has to be given room, so the collider evicts whatever
the fit put beside it; the bigger the panel, the more of the embedding is spent
buying it. Displacement cannot score this — a uniform inflation moves every
node a long way and changes nothing about who is near whom — so the measure is
**neighbourhood retention**: of a node's ten nearest neighbours in the fit, how
many are still its ten nearest once the simulation stops. Scored live over a
300-node sample of the 5,337-chunk corpus.

The **null arm** shuffles the final positions between nodes: the same cloud,
the same shape, no correspondence. It scores **0.001–0.004**, so retention is
being read against a measured floor rather than a hoped-for one.

| panel gain | edge (world) | retention, panels | retention, spheres | extent | overlapping |
|---|---|---|---|---|---|
| 1.00 | 2.73 | 0.841 | 0.937 | 305 | 0 |
| **1.75 — shipped** | **4.77** | **0.690** | **0.925** | **309** | **0** |
| 2.50 | 6.82 | 0.547 | 0.914 | 328 | 0 |
| 4.00 | 10.90 | 0.355 | 0.879 | 429 | 0 |
| 18.0 — as shipped before | 18.00 | 0.214 | 0.810 | 781 | 0 |

Three things this settles.

**The gain does not buy `G-21`.** Every row reaches zero overlapping pairs. The
panel size buys picture size and pays in embedding, and nothing else.

**The old size was not a choice, it was a stale constant.** `clamp(√val·4, 6,
18)` is an absolute world size that knows nothing about the corpus it draws.
`nodeRelSize` was 5.124 when those numbers were picked and is 0.699 now, so a
panel had grown to roughly 26× the sphere it stood in for, and the clamp had
flattened them — nearly every panel sat at the ceiling of 18, the same size
whatever the chunk. This is the identical defect `relSize` already documents
for spheres, left standing one function away. Panels are sized from the fit
now, as a multiple of the sphere they replace.

**Oversized panels were displacing plain nodes too.** The last column moves
0.810 → 0.925: the fix returns 0.11 of retention to the 4,510 chunks that never
showed a picture at all.

1.75 puts a panel's edge at 4.77 against this fit's median node spacing of
4.19 — a panel is as wide as the room the embedding allotted a node, and no
wider. The honest caveat: at the pane's default framing that panel draws at
**3.3 px**, and the old 18-unit panel drew at 12.5 px. Neither is a legible
thumbnail; the reader zooms either way. The old size was paying 0.21 retention
for legibility it never delivered.

### M.7 — the window was counting addresses, not words

Measured with the real encoder over `build/vaultws256`, 5,337 chunks, before
the change:

| | tokens |
|---|---|
| the corpus, as rendered | 548,451 |
| of those, **link targets** | **288,200 — 52.5%** |
| chunks spending more than half their budget on addresses | **3,591 of 5,337 — 67.3%** |

By page, the share that is link target: discourse.julialang.org 71.2%,
commons.wikimedia.org 68.9%, developer.mozilla.org 61.9%, arxiv.org 53.5%.
The worst single chunk is 370 tokens that reduce to **1**. So a 256-token
window was a ~121-token window of anything a reader or a model would read,
and the chunker had been cutting pages to fit machine addressing.

Three chunks read off the live pane, which is what the defect looks like from
the reader's side rather than in aggregate:

| chunk | badge | what is in it |
|---|---|---|
| `d52f569d` | 238 tok, 93% of 256 | a paper title and eight author names, each name followed by a full `arxiv.org/search?searchtype=author&query=` target |
| `f8c995ac` | 206 tok, 80% of 256 | two link lines and two `![]()` image urls |
| `d5511a40` | 104 tok, 41% of 256 | one avatar, one profile link, and the word "image" |

The fix counts `tokens.budget` — `count` over `for_model`, which drops targets
and keeps labels. The render is untouched, because a link is an affordance the
reader acts on in place. The quantized semantic embedding is given the same
link-free string, since an address is not a sentence; the frequency matrix
keeps expanding urls into path words, because a url tail is a legitimate
lexical term. That is `G-22` and `G-23`, and it is the reason there are two
vectors.

### M.8 — the duplicate cluster, diagnosed and closed without embeddings

`build/vaultws256`, grouping by (page, exact rendered markdown):

| | |
|---|---|
| duplicate groups within a page | 38 |
| redundant chunks | **176 of 5,337 — 3.3%** |
| the largest single group | **125** |

The 125 are one string — `Press Down Arrow to preview item details` — at 125
distinct addresses on `archive.org/search`:

```
/section/infinite-scroller/#shadow-root/.../article
    /tile-dispatcher/#shadow-root/div/div
 [2]/tile-dispatcher/#shadow-root/div/div
 [3]/tile-dispatcher/#shadow-root/div/div      … ×125
```

Each search result is a `<tile-dispatcher>` custom element with **its own
shadow root**, and every one of those roots carries the same accessibility
hint. The trie is right to hold 125 addresses; the projector was wrong to draw
125 nodes, and the reader saw a cluster of identical dots.

**Why `_dedupe` could not see it.** It is element-scoped by design: it groups
units by `addr.xpath` and compares only within a group. Identical content at
*different* xpaths has never been compared to itself, and 125 tiles are 125
different xpaths.

**Marked, not merged.** `Anchors {ord}` pairs a chunk's markdown lines with its
addresses by position — `ingest_chunks` records what happened the last time
that alignment slipped — so one chunk holding 125 tiles' addresses would
attribute one line to 125 elements. Every chunk keeps its node, its anchors and
its addresses; `dup_of` and `dup_n` are a fact *about* them that consumers may
act on. The projector drops copies before the fit and carries the count.

Byte-exact and page-scoped on purpose: no threshold, no embedding, and two
pages sharing a cookie banner stay two documents. The near-duplicate case —
the same thing said differently — is `G-26` and needs the embeddings, so it
does not hold this up.

### M.9 — the quaternion fit, measured

`G-18` is implemented, gradient-checked, and **worse than what it replaces**
on the one property a projection is answerable for.

The measure is neighbourhood retention against the space the fit is OF: of a
chunk's ten nearest neighbours by cosine over the encoder's vectors, how many
are still among its ten nearest in the picture. 4,985 nodes of
`build/vaultws256`.

| fit | retention | radius p50 (of 300) |
|---|---|---|
| **euclidean** | **0.375 – 0.400** | 288.7 |
| S3, colour weight 1.0 | 0.188 | 10.8 |
| S3, colour weight 0.1 | 0.189 | 10.8 |
| S3, warm-started from the euclidean fit | 0.186 | 12.1 |
| S3, angle scaled ×8 | 0.166 – 0.186 | 49.8 |

**Three explanations were tested and all three are wrong.**

*Not the product metric being unbalanced.* The angle term is bounded by π and
the colour term is unconstrained Euclidean, so the colour half looked likely
to swamp the position half. Weights 1.0 and 0.1 give 0.188 and 0.189.

*Not the parameterisation's singularity.* Hyperspherical angles are degenerate
at φ₁ = 0, exactly where the identity rotation sits, and the cloud collapsed
onto it — a median radius of 10.8 out of 300. Warm-starting the fit from a
Euclidean layout that already has structure gives 0.186.

*Not only the metric's range against UMAP's `a`/`b` curve.* That curve is
fitted for unbounded Euclidean distances, and a metric whose whole range is 0
to π leaves it no room. Scaling the angle by eight moved the median radius
from 10.8 to 49.8 — the collapse is real and that is its cause — and left
retention where it was.

**A fourth explanation was tested after the fact and is also wrong: the
display map is not hiding anything.** The retention above is scored on drawn
3D coordinates with Euclidean distance, and `to_ball` is a logarithmic map —
two points far from the origin are not separated by their rotation angle once
it has run — so the number looked like it might be charging the metric for the
map's distortion. Scored instead in the metric the optimiser actually worked
in, the rotation angle between the quaternions the angles generate:

| | retention |
|---|---|
| S3, fit, in the rotation metric | **0.185** |
| S3, picture, in drawn 3D | 0.186 |

They agree to a thousandth. The fit itself preserves 0.185, and the display
map costs nothing. So the residue is in the embedding, not in the drawing.

What remains unexplained is the retention itself, and it is recorded as
unexplained. The flag exists (`build_layout(spherical_space=True)`), the
report says which space it fitted, and the number above is what has to move
before it becomes the default. Shipping it as the default now would be
shipping a halving of neighbourhood fidelity in exchange for a geometry
nobody has yet shown a benefit from.

What the spherical map DOES deliver is `G-19` exactly: `to_ball` puts the
identity rotation at the origin and makes the rotation angle the radius, so
the cloud is centred by construction and `recentre` becomes unnecessary —
rather than centred by measuring an extent and subtracting it, which is what
`_framed` does today.

### M.10 — the projector's frame rate, and where it goes

Measured in the pane on `build/corpus123`:

| | |
|---|---|
| nodes | 12,820 |
| links | 7,889 |
| **frames per second** | **3.3 idle, 3.2 rotating** |
| **draw calls per frame** | **20,309** |
| triangles | 1,404,712 |
| geometries / textures | 2,306 / 1,102 |

**The frame rate above is against the wrong ceiling, and the null arm is what
showed it.** An Obsidian with NOTHING open answers `requestAnimationFrame` at
**9.3 fps** in this session — the window is driven over CDP and nobody is
looking at it, and Chromium throttles rAF for a window that is not focused. So
3.3 was never "3.3 out of 60". Read against what the app can actually do:

| | fps | share of the ceiling |
|---|---|---|
| ceiling, nothing open | 9.3 | — |
| 12,820 chunk nodes | 3.3 | **35%** |
| 96 page nodes | 8.7 | **94%** |

The chunk view really was costing two thirds of the app's available frames,
and the collapsed view really does give them back. But no absolute frame rate
in this document was measured with a focused window, and none should be quoted
as one. This is the "measure the page before blaming the sensor" rule reaching
a rendering measurement: a score against a throttled compositor is the
throttle plus the scene, and they only separate if the empty app is measured
first.

**It is not the triangles.** 1.4 million is unremarkable for any GPU made this
decade, and the frame rate does not move between sitting still and rotating,
which is what a fill-rate or vertex-bound scene would do. It is the draw
calls: `3d-force-graph` gives every node its own `THREE.Mesh` and every link
its own, so the count is `nodes + links + sprites` and each one is a separate
instruction to the driver.

**Measured after the collapse: 20,309 draw calls become 94.** That is the
durable number here, because it does not depend on who is looking at the
window.

Two ways out, and they are not alternatives.

The rendering answer is instancing — one `InstancedMesh` for all the spheres,
one merged geometry for all the links — which is a change inside `graph.ts`
and would take the count from 20,309 to single digits.

**And the page graph is nearly edgeless, which is worth saying.** The corpus
has **2** `LinksTo` edges across 98 pages: `_link_hyperlinks` only records a
link whose target was also scanned, and this corpus is a broad sample of
different hosts rather than a crawl. The 7,889 links the chunk view drew were
`Contains` edges — structure inside one page — which collapse to self-loops at
page level and are dropped. A page-level map of a crawled corpus would have
edges; this one has almost none, and that is a property of the corpus.

The design answer is `G-53`: **draw pages, not chunks**. 94 shadow DOMs
instead of 12,820 chunks, unfolding on click and on retrieval. That is the
reader's own instinct and it is also the cheaper picture by two orders of
magnitude. It is preferred because it is not only a performance fix: a map of
12,820 chunks is not legible at any frame rate.

## N. S-13 — can Electron host the sensor? Measured, in the running Obsidian

Addendum II asks this as an investigation: *"there are still selenium-like
interfaces that can perhaps overtake a firefox browser telling an electron
browser what to see. Perhaps, instead, we explore any selenium-like links with
electron itself such that we obtain the same sensor-like functionality while
staying slim on web interfaces and able to control profiles from their base."*

`S-13`'s deliverable is a capability verdict with evidence. This is it, taken
over CDP against the live Obsidian (`X-2`), not from documentation.

### N.1 — what the renderer actually reaches

Obsidian 1.13.7 runs **Electron 39.8.3 / Chromium 142 / Node 22.22.1**, with
`nodeIntegration` on and `@electron/remote` exposed to plugins. From plugin
code:

| via `require('electron').remote` | |
|---|---|
| `BrowserWindow` | function |
| `WebContentsView` | function |
| `BrowserView` | function (deprecated by Electron) |
| `session` + `session.fromPartition` | object / function |
| `app`, `webContents`, `webFrameMain` | available |
| `getCurrentWebContents().debugger` | **present — CDP from inside** |

`<webview>` is also available, but **Electron now advises against it**:
*"Chromium's webview is undergoing dramatic architectural changes... consider
alternatives, like iframe, a WebContentsView, or an architecture that avoids
embedded content altogether."* So `P-B3`/`P-B4` should be built on
`WebContentsView`, not the `<webview>` tag. That is a correction to the
obvious reading of those rows.

### N.2 — the verdict: yes, and it is demonstrated

Driven from plugin code in the running app, with **no Firefox and no
geckodriver**:

| step | result |
|---|---|
| isolated persistent session `persist:vertiscope-probe` | obtained — this is *"profiles from their base"* |
| hidden `BrowserWindow` on that partition | created |
| navigate to `https://books.toscrape.com` | loaded |
| `executeJavaScript` in the page | title, **542** DOM nodes, **94** anchors |
| **`MutationObserver` attached to `document.body`, subtree** | **true** — the fold's own primitive works |
| `webContents.debugger` | available |
| teardown | destroyed |

`preload` is the injection point the sensor needs: it runs *before* page
scripts, which is required for a fold that must not miss the first mutation.
`executeJavaScript` on `dom-ready` is the fallback for re-injection.

### N.3 — the finding that is not about tidiness

**Electron loaded a page Firefox cannot.** `apnews.com` refuses automation: it
returns 403 to curl and timed out the Selenium/geckodriver scan at 40,000 ms,
which is why the 256 re-cut holds 23 pages and not 24.

| | Firefox + geckodriver | Electron `BrowserWindow` |
|---|---|---|
| `https://apnews.com` | **TimeoutException at 40,000 ms** | **loaded in 26,350 ms** |
| DOM nodes | — | 10,161 |
| anchors | — | 1,772 |
| body text | — | 22,340 chars |

That is not a performance argument, it is a **coverage** argument: the corpus
is currently missing a page because of the host, and the alternative host
reaches it.

### M.11 — where a capture's 22 seconds went

`G-66` asked for the phases separately before anyone optimised anything. Three
pages, captured live through the browser cell, times in milliseconds:

| page | dirty chunks | decode | absorb | render | store | total |
|---|---|---|---|---|---|---|
| quotes.toscrape | 14 | 1.5 | 5.6 | 113.2 | 515.6 | 636 |
| books.toscrape | 26 | 3.7 | 13.4 | 55.9 | 1,482.6 | 1,556 |
| MDN CSS index | 191 | 57.9 | 197.8 | 579.7 | **21,437.6** | **22,273** |

**The store was 96% of it**, and the trie and the projections were never the
problem: MDN's whole markdown projection over 952 chunks is 580ms. Breaking
the store down further:

| statement | ms |
|---|---|
| reconcile | 408.7 |
| addresses | 1,301.4 |
| chunks | 66.2 |
| **anchors** | **19,121.6** |
| contains | 75.0 |

**One wrong guess, recorded because it was wrong.** `_reconcile` deletes every
anchor on the chunks being written and the write then used `MERGE` on the
relationship, so the existence check could never find anything. Changing it to
`CREATE` — which also required `_reconcile` to clear by the *written* set
rather than the *page's* set, so that emptiness is a postcondition — moved the
number from 19,121.6 to 19,065.9. Nothing. The check was not the cost.

**What it actually was.** The anchor write asked for two nodes in one pattern:

| statement, per row | ms |
|---|---|
| `MATCH (c:Chunk {cid})` alone | 0.045 |
| `MATCH (a:Address {aid})` alone | 0.80 |
| **both in one comma pattern** | **6.60** |

Eight times the sum of its parts — the planner stops treating it as two key
lookups. And the Address table has **329,712** rows, so even the lone lookup
is expensive. 2,924 anchors × 6.6ms is the 19.3 seconds, exactly.

Three spellings, measured on the same rows:

| | total | per row |
|---|---|---|
| comma MATCH, as shipped | 19,136 ms | 6.54 |
| two separate MATCH clauses | 10,964 ms | 3.75 |
| **fused into the address MERGE** | **1,448 ms** | **0.50** |

The fix is the third: the address write already does `MERGE (a:Address {aid})`
and therefore already has the node bound, so carrying the chunk id and the
ordinal on the address row lets one statement write the node and hang the edge
off it — with no second lookup at all. Only the Chunk is matched, at 0.045ms.

Sound because the pairing is one-to-one: a line carries one address, and an
address reaching two chunks is the defect `test_the_page_is_still_partitioned`
forbids. An anchor whose address this write does not carry falls through to
the two-clause form rather than being dropped.

**Verified live, end to end, on the same page:**

| phase | before | after |
|---|---|---|
| anchors | 19,121.6 | **1,476.6** |
| addresses | 1,301.4 | 11.2 |
| render | 631.5 | 626.5 |
| **capture, total** | **22,041** | **3,068** |

7.2× on the worst page in the corpus. What is left is 2.2s of store against
0.86s of fold-and-render, so the store is still the majority and `reconcile`
and `anchors` are the two to take next.

### M.12 — live aggregation, and the machinery that was not built

`G-65` wanted stage two on the diff stream. The obvious design was an
incremental DBSCAN: `min_samples=2` makes it connected components of the
eps-graph, so a union-find maintains them, a new chunk unions with whatever
lies inside `eps`, and a changed chunk forces its component to be recomputed.
That is a real algorithm and it was not built, because measuring first said it
would have been machinery bought to speed up the wrong half.

**What a page actually costs.**

| chunks | read ms | cluster ms |
|---|---|---|
| 1,097 | 476.5 | 737.5 |
| 863 | 374.4 | 102.9 |
| 835 | 330.2 | 77.9 |
| 801 | 406.1 | 71.6 |
| 54 | 30.9 | 7.4 |

The clustering was never the cost. The read was — and it was an N+1:
`aggregate` fetched each chunk's vector with its own query,
`store.embedding(cid)`, once per chunk. One query for the page instead:

| | before | after |
|---|---|---|
| 835 chunks | 330.2 ms | **32.8 ms** |
| 863 chunks | 374.4 ms | **37.2 ms** |

So a whole page re-clusters in roughly 110ms, which is cheap enough to run on
every pause with no incremental structure at all. The union-find is recorded
here as designed-and-declined rather than built, because an optimisation aimed
at 78ms while 330ms sat beside it would have been the wrong work done well.

**How it runs.** Every capture that stores dirty chunks queues its page with a
deadline 1.5s out; each further drain pushes the deadline back, so the work
lands when the reader pauses rather than while they scroll. The queue is
drained on the embedding worker, after a flush, because the two are ordered —
a page clustered before its new chunks have vectors clusters the chunks it had
a moment ago. Nothing on the request path waits for any of it.

**Verified live**, on a 128-chunk page the corpus had never seen:

| t | dirty | placed | groups |
|---|---|---|---|
| 0s | 124 | 0 | **0** |
| 2s | 0 | 72 | **23** |
| 4–12s | 0 | 0 | 23 |

124 dirty chunks became 72 drawn nodes and 23 merge groups, unprompted, two
seconds after the capture. The 52 difference is the group members, which
`G-27` folds into their leads.

**And a confusion worth keeping.** The first run of this check reported six
chunks "awaiting a vector" forever, and the embedder looked broken. It was
not: all six had vectors. `place_into` reports everything as `unplaced` when
there is no FIT to place into, and the pane rendered that as "awaiting a
vector" — two different states under one word, which sent me hunting a working
component. The reply carries `why` for the fit case now and the pane says
which of the two it is.

### M.13 — the overlay, and the scope that returned nothing

**Scoping is not filtering, and the first version was.** `?url=` restricted
the results *after* the index had ranked a global top-k, so a scoped query for
three results returned whatever of that handful happened to be on the page —
which for MDN's Headers index, a page with hundreds of chunks about exactly
the query, was **zero**. The index ranks rather than filters, so a scoped
request now widens its depth until the page is certainly inside it, bounded at
4,000 so a scope on a 1,173-chunk page cannot become a ranking of the corpus
end to end.

| request | hits | ms |
|---|---|---|
| global, k=4 | 4 | 186 |
| scoped, k=4 | 3 | 107 |
| scoped, fine | 3 | 113 |
| scoped, offset 4 | 2 | 117 |

**The score is a product of three small numbers and reads as zero.** `score`
comes back around 1e-5 — rank × lexical × semantic — which at any sane
precision is `0.000` and says nothing about *why* a result ranked. The payload
carries the three factors separately now and the overlay shows two of them, so
a reader can see whether the words matched or the meaning did:

    lex 0.0686   sem 0.5546   pagerank 0.00039

**Driven as a reader would**, on MDN's Headers index:

| step | results | |
|---|---|---|
| typed a query | 12 | overlay visible over the page |
| scrolled three times | **48** | `G-69`: it keeps going |
| scoped to this page | 19 | 12, then 7, then exhausted |
| clicked a result | — | `at /html/body/div[2]/…/section[5]/dl/dd[5]` |

**The overlay paints above the webview**, which was not a given: a `<webview>`
is composited and can draw over ordinary DOM siblings. Verified visually
rather than assumed, and the page stays visible underneath because the
overlay is capped at 62% of the pane — a list that covers what it is ranking
is a list with no context.

**A duplicate that TypeScript hid.** A second `interface SearchHit` was added
beside the existing one and the compiler said nothing, because interfaces of
the same name MERGE. The merge silently made every new field mandatory on the
`/` gesture's payload too. One interface now, with the overlay's extra fields
optional.

### M.14 — the map opens where the reading went

`G-55` and `G-56` read as two requirements and are one mechanism. The
overlay's hit list is simultaneously *the set of chunks matching the query*
and *how far the reader has got*, because it grows as they scroll. So the
projector opening a page to exactly that list satisfies both, and neither
needs a depth counter of its own.

Driven in the app, on MDN's Headers index:

| step | nodes | results | scope |
|---|---|---|---|
| start | 96 | — | everywhere |
| query typed | 96 | 12 | everywhere |
| **page clicked** | **105** | 10 | **this page** |
| **scrolled ×3** | **125** | 30 | this page |
| right-click | 125 | 24 | everywhere |

Clicking the page drew its **10 matching chunks** rather than its hundreds,
and removed the page node. Three scrolls took the ranking to 30 and the map
to 125 nodes — in step, because they are the same list.

**Reported only when the ranking is SCOPED.** A corpus-wide query touches
most pages, and opening every one of them is the 12,820-node picture again,
arrived at from the other direction. Scoping is what makes "open to the
results" a bounded instruction.

**A confusion that cost a run, and is the same shape as the last one.** The
first attempt returned zero results at every step, and the overlay looked
broken. It was not: `rankScope` was left pointing at `about:blank` from an
earlier probe, so every query was scoped to a page with no chunks in it. The
reply was correct at every layer — a scoped ranking over an empty page IS
empty — and nothing said which of "no matches" and "no such page" had
happened. The same word covering two states, twice in two features.

**Releasing the scope does not re-collapse the page**, and that is left as it
is deliberately rather than overlooked: the reader opened those nodes, and a
map that shuts itself when a filter is released takes work back that someone
did. Whether that is right is a judgment for use to settle.

### N.4 — what this does not settle

The verdict is *the capability exists and one real advantage is measured*. It
is not yet a decision to migrate, and Addendum II did not ask for one.

- **26.4 s is not fast.** It is inside Firefox's timeout but not comfortably.
  One load, one page; no distribution behind it.
- **`sensor.js` was not run.** `MutationObserver` attaching proves the
  primitive; it does not prove the fold, the taxonomy, or `repairMs`.
- **O(delta) is unmeasured on this host.** Every timing in
  `build_analytics/` was taken under Gecko. They are not transferable, and
  re-taking them is the real cost of this migration.
- **Closed shadow roots stay closed** (hard constraint 6). Electron changes
  nothing here and must not be presented as a way in.
- **`shadowRootsReachable: 0`** in the probe is a property of
  books.toscrape.com, not a shadow-traversal result. Untested.
- **Chromium version is Obsidian's, not ours.** Today it is 142. We ship
  `geckodriver.exe` and control that; an Electron host inherits whatever
  Obsidian ships and upgrades when Obsidian does. That is a real loss of
  control traded for one fewer binary.
- **Single-engine risk.** `invariants.a1` and `c1` compare composed-tree walks,
  and the addressing convention was developed against Gecko. Moving to Blink
  changes DOM edge cases; the invariants have to be re-run, not assumed.
- **Detectability.** apnews admitting Electron where it refused geckodriver is
  today's behaviour of one site's bot detection, not a property. It can change
  and it is not a guarantee for other pages.

### N.5 — the cheap next step

Run the existing sensor against an Electron-hosted page and compare the map to
the Gecko one for the *same url*, address by address. `invariants.a1` already
does this comparison; it needs a second host, not a new measure — which is
`M.4`'s lesson applied before making the same mistake a third time.

---

## O. The design ahead

What is designed and not yet built, or built and not yet finished.
Separate from Part II's measurements, which are about what IS.

### O.1 — two-stage chunking: recursive descent, then embedding aggregation

The design the user set out, recorded before it is built.

**Stage one** is what exists: recursive descent to a window counted in
link-free text (`G-22`). The window is *staging*, not a ceiling — it is chosen
as a strict subset of the display context so that stage two has room to merge
back up. 256 stays, because it was chosen on hit@1 and that is not reopened.

**Stage 1b** is `G-24`: exact duplicates resolved DB-side, over the aggregate
DOM chunks, before any embedding is consulted. Shipped; see §M.8.

**Stage two** is aggregation over the **quantized semantic embeddings only**.
Frequency vectors are not dimension-efficient and exist for fine-grained
retrieval, so they do not drive the merge — they verify it, afterwards, as
their own step (`G-30`).

Open questions the build has to answer with measurements, not choices:

1. **What separates "duplicate" from "should be merged"?** Substring matching
   is rejected. The proposed first cut is *relative*: within X% of the closest
   neighbour's distance, scaled by the maximum closest-neighbour distance on
   the page, so the criterion is a property of the page rather than a
   constant. Establish duplicate-links first, merge second.
2. **When is there enough to discriminate?** Stage two runs only past a sample
   size N of chunks from one shadow DOM (`G-32`). N is to be measured by
   sweeping it against aggregate accuracy, not assumed.
3. **What structural term belongs in the pairwise metric?** Pagerank solves an
   eigenvalue problem over linked relevance and suits *linked* aggregation;
   an LCA path metric over patricia paths suits *spatially* co-located
   subchunks. Start with the embeddings alone and measure what each adds.
4. **Sinkhorn / annealing** to localise the aggregation to its page structure,
   given a pairwise matrix carrying both the coarse and fine encodings and the
   structural term.
5. **Online.** A continuous scan must maintain this diff-efficiently: a merge
   or split re-vectorises only what it touched, and the projector's update
   stays batch-minimal (`G-34`) without regressing the force-directed layout
   or the picture billboards (`G-35`).

The merged layer is what is indexed, structured and presented; the 256-token
chunks and their embeddings stay underneath and remain what a hit resolves to
(`G-27`). Merged chunks are scored in the same unit as everything else —
link-free markdown tokens.

### O.2 — the browser cell

One component, two hosts: a standalone panel, or a cell in the notebook. The
functionality is identical; the standalone is the expanded view.

The panel has **two toggleable faces**: the live Electron browser, and the
full markdown rendered as a native Obsidian panel. Hovering a chunk in the
browser highlights it minimally and lights the same chunk in the 3D projector
— no banner, because the content is already on screen. Right-click ports that
chunk's full markdown to the other face. Clicking a node in the projector
drives the same browser session to that url and scrolls the chunk into view,
which is what collapses "browser", "shadow-DOM view" and "chunk view" into one
thing.

Above the browser sits retrieval, drawn as an **overlay** — a layer above
Electron linked to the store, never script written into the page (`G-41`).
Selecting a result navigates to its url and chunk.

The chat is hoverable on the browser and its context is exactly the
right-clicked markdowns, **each sent at most once**: the selection gesture
*is* the delta, so there is no separate context box. Outputs land below the
selected markdown as continuous conversational markdown, and inside a notebook
they append to the selected cell with the rewind rules unchanged.

This is also where scanning moves (`G-47`): the Electron browser that hosts the
cell becomes the sensor's host, replacing Selenium.

### O.3 — the codebase in the trie

`G-49`..`G-52`. The corpus is web pages; the thing reading them is not in it.
So a reader can watch a scan run in the browser panel and cannot look at the
code that is running — which is the one gap that keeps the map from closing
on itself.

Three sources, one addressing scheme. `vault://<vault>/<path>` already exists
and works (`vertiscope/vault.py`, `T-5`): a note becomes trie addresses with
`section[n]` wrappers, and headings and blocks are siblings. Source files want
the same treatment with a different authority — the repository, and the
installed environment's `site-packages` — so that an import edge can point
from one to the other.

**Dependencies are edges.** An import in a module, a requirement in a package's
metadata: the same kind of thing as a link between two pages, and they belong
in the same graph so that `LinksTo` answers both questions. That is what makes
"which code ran this scan, and what does it rest on" a query rather than a
separate tool.

**Vectorised by comments and docstrings only.** This is `G-23` one domain
over. A url is not a sentence and neither is an identifier: `_certainly_
overflows(child_chars, window)` tokenises into fragments that mean nothing to
a sentence encoder, and a file of them would embed to the centroid of "source
code" rather than to what the code is for. The prose in a codebase is its
comments and its docstrings, and in this repository that prose is where the
reasoning actually lives. The code itself stays in the render and in the trie,
exactly as a link target stays in the markdown — it is kept out of the
quantized semantic embedding, not out of the map.

The frequency vector is the other half of the same split: identifiers *are*
legitimate lexical terms, the way a url tail is, so the lexical side keeps
them and retrieval by symbol name still works.

### O.4 — O(delta), end to end, in milliseconds

The goal says the two projections fuse to reconstruct the distilled shadow DOM
"in **millisecond range** and in **O(delta)**". The fold has been measured
against that for a long time. Nothing downstream of it has, and the phases
downstream are now most of the work.

**The phases, and what is known about each today.**

| phase | what it does | measured | status |
|---|---|---|---|
| fold | `sensor.js` maintains the catamorphism in the page; a drain carries only what changed | `repairMs`, long-standing | O(delta), with the `reclassify` exception |
| transport | the drain crosses from the page to the sidecar | inside the 2.1s below | not separated |
| decode | interned segments, shapes, chunk records -> addressed units | inside the 2.1s | not separated |
| absorb | `StreamingScan` folds the delta into the trie | inside the 2.1s | not separated |
| render | `render_trie` redraws the dirty subtrees | inside the 2.1s | memoised on `exact_hash` |
| store | `ingest_chunks` writes the dirty chunks | inside the 2.1s | batched |
| dedup | `_same_content`, exact, page-scoped | not separated | O(chunks on the page) |
| vectorise | the encoder, on the settled text | background worker | off the request path |
| aggregate | DBSCAN over the page's vectors | 27s for 94 pages, **at the settle only** | `G-65` |
| re-vectorise | a merge group's assembled text | inside the 27s | — |
| transform | `Projection.place` into the existing fit | **27ms** for 8 chunks | `G-67` wants it queued |

What is actually known end to end: **a page's first capture is 2.16 seconds**,
of which placement is 27ms and everything else is fold-through-store in one
undifferentiated block. An empty drain answers in **5 to 10ms**, which is the
only number here already inside "millisecond range".

So `G-66` is a measurement requirement before it is an optimisation one: the
2.1 seconds has to be broken into its phases before anyone can say which of
them is the problem. Guessing which phase dominates is exactly the mistake
this document exists to stop.

**Live aggregation** (`G-65`). Stage two runs inside `ingest(complete=True)`,
which is the settle. While a reader browses, a chunk can be rewritten a dozen
times and its merge group is whatever the last settle decided -- so the groups
on screen describe a page that has moved on. Running DBSCAN per drain is not
the answer either: it is O(chunks on the page) in the gram matrix, and a
reader scrolling produces drains faster than that completes on a large page.

The shape that fits the constraint: keep the page's neighbour structure
incrementally. A drain touches a handful of chunks; their rows in the pairwise
matrix are the only ones that change, and DBSCAN's verdict only moves for
points within `eps` of them. That is a local update, not a refit -- and it is
the same argument `_certainly_overflows` makes about the render, one stage
along.

**The transform queue** (`G-67`). Placement is 27ms and runs inline. That is
affordable now and stops being affordable when a drain touches hundreds of
chunks, because `Projection.place` is a matrix operation whose cost is in the
batch. Queued and batched, a burst of drains produces one transform; inline,
it produces one per drain.

### O.4b — the one question in Addendum IV nobody has answered

From the 23:17 statement, and it is the only sentence in either long
statement that produced no requirement:

> Also unsure of the loading... portion of the current open panel and
> whether or no this is a panel interactions thing or if we can somehow
> instead explore deeper interactive mappings in our patricia trie and
> our electron browser.

It reads as a question about whether the panel's loading state is a
*panel* concern at all, or whether what looks like loading is really the
absence of the trie-to-browser mapping that `G-46`/`G-68` describe. It is
recorded here unnumbered rather than guessed at, because the two readings
lead to different work: one is a progress indicator, the other is `G-68`.

### O.5 — three representations, collapsed into one

The reader currently has a chunk panel in Obsidian, a browser cell, and a 3D
node, and none of them knows about the others. The design that collapses them:

**The Electron browser is the primary panel.** Clicking a node in the
projector drives the browser to that url and scrolls the chunk into view
(`G-58`). It is the same session the reader was already browsing, so the page
is the page -- not a rendering of it.

**The shadow-DOM panel becomes a billboard in the 3D view** (`G-57`). It is
already generated and already in the store; what changes is that it opens
*in the projector*, draggable, beside the node it belongs to, instead of
taking over an Obsidian pane. Its interactive fields act on the live page
through the trie (`G-68`).

**The Obsidian-native panels become the offline fallback** (`G-59`). They are
what the structures look like when there is no live page to point at, which
is a real mode and not a degraded one. **And offline the billboard moves**:
the verbatim puts it "as a more 'main' panel within obsidian rather than in
the UMAP projector", which is the exact inverse of `G-57`. Online the panel
opens in the 3D view beside its node; offline it takes the pane, because
there is no live page for it to sit alongside.

**Offline is a first-class path, in three degrees** (`G-60`..`G-62`):

1. the page saved as the browser *presented* it -- composed tree, scripts
   already run -- which is what "save this page" should mean and is not what
   a browser's own "save as" gives;
2. a saved source that lost its layout, **infilled from the traced chunks**;
3. no source at all, and the page **reconstructed from the scan trace** --
   fully rendered and scrollable. This is the affine map's strongest claim:
   the trace is not a description of the page, it is the page.

### O.6 — retrieval, coarse to fine

The overlay `G-42` placed above the browser, and what it is for.

**Coarse first.** The merged chunks (`G-27`) are what the projector draws and
what a query first ranks -- a page's worth of meaning, not a paragraph's. That
is the layer the reader navigates.

**Then fine, inside the shadow DOM.** A coarse hit opens into its members, and
top-k runs *within* that page's chunks. This is the same coarse-to-fine shape
the chunker itself has, applied to reading rather than cutting.

**Across pages, inside one window** (`G-64`). Results from different shadow
DOMs are ranked together and the selection has to fit 256 tokens of pure text
-- the same unit everything else is counted in. A ranked list that does not
fit the window is a list nobody can act on.

**And the overlay drives the unfolding** (`G-55`). How far a page opens in the
projector is a function of how many results the reader has scrolled through,
so the map unfolds where attention has actually gone rather than where someone
clicked once. That is also what keeps `G-53`'s frame rate: the picture stays
94 pages until a reader's own reading earns more.

## What "fully realized" means

The pivot is realized when:

1. **R-C1** reach ≥ 60%, with deliberate suppression separated from loss.
2. **R-C2** reading order ≥ 95%.
3. **R-C4** the shape field exists as a second address dimension. *(met)*
4. **R-C5** `worst_overflow_ratio` ≤ 1.5x — the window enforced on a single
   oversized value, and not only on a chunk made of several.
5. **R-E3** ≥ 95% of picture-carrying nodes render, on a live scan.
6. **R-G2** scrolling in Obsidian drives the remote browser.
7. **R-H1** and **R-H3** either built, or explicitly dropped with the reason
   recorded here.
8. **R-C3** answered by the user: containment accepted as the stand-in for
   geometry, or the sensor's no-geometry contract changed.

Items 7 and 8 are decisions, not implementations, and they belong to the user.
Everything else is measurable and has a number above to move.
