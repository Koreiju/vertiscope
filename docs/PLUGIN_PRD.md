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
| D-4 | `markdown.py` is tuned "17:1 toward leaving noise rather than risking loss" and `_dedupe` is element-scoped | *"full deduplication of repeat substrings that are essentially structural redundancies of the web pages themselves"* | **Defect** |
| D-5 | Markdown renders no tables at all | *"a hierarchically-header-structured markdown document with tables, images, web links"* | **Defect** |
| ~~D-6~~ | ~~The delta path re-admits a chunk it should have reassigned or popped~~ | **WITHDRAWN 2026-09-12 — not demonstrated.** The evidence for it was a metric that could not tell two real siblings from one re-addressed node. `--resolvable`: 0 unresolvable of 719. `--drift --kind insert`: 0 stale, 0 lost over ~190 moved addresses ×3. See §M.3 for what remains untested | — |
| ~~D-8~~ | ~~A `src` detection and an `alt` detection at one `<img>` are drawn as TWO media lines~~ | **FIXED 2026-09-13** — `markdown._join_media` merges the pair at one element, keeping the url's address and absorbing the alt's. A fresh live scan of the reporting site: **0 pairs**, against 365 before. §M.5.1 | — |
| D-9 | A chunk rooted at a `<tr>` carries its cells' VALUES and none of their names, though the header at the same `td[n]` position is in the trie | `M-10` full structural preservation; `M-11` the chunk is what gets embedded | **Defect** — 44 of 79 row chunks (§M.5.2) |
| D-10 | One ar.wikipedia `<tr>` renders **302 tokens against a 300-token window while still holding twelve splittable children** — a chunk over the window that is not indivisible | `M-12` the window is enforced; `test_oversized_chunks_are_indivisible_not_lazy` states the rule | **Defect** — NEW under `G-22`. `tokens.budget` is smaller than `tokens.count`, so the descent stops at a node it used to split through. Held by `strict=True` xfail at two windows in `tests/test_markdown.py` so the day it is fixed the marker has to come off. Five candidate causes ruled out by measurement, each named in that file; the growth is between `_descend`'s return and the page-global passes **Superseded 2026-09-26 by a contract change, not a fix:** the lenient cut (`G-86`, `markdown.LENIENCY` 1.5) makes 302 against 300 inside the bound; the growth after `_descend` is still unexplained |
| D-13 | The `/layout` cache held **one slot** in a `ThreadingHTTPServer`, so two concurrent requests for different spaces or levels could each be served the other's answer | `G-17`/`G-53`: the pane has a button for each axis and asks for what it draws | **FIXED 2026-09-19** — four slots, keyed identically. Caught by `confirm.mjs`'s D-11 check, which asks for both spaces at once: sequentially all three requests were right, concurrently `euclidean` came back `"S3"`. The server's own comment two hundred lines below already notes that a vault opens many connections at once |
| D-14 | **Every `/search` crashed** on this workspace: `IndexError: index 13397 is out of bounds for axis 0 with size 13397`. `Workspace.index` is a lazy property with no lock, so two concurrent searches both hydrated into one shared `EmbeddingMatrix`, each grew a copy of the same stale array, and the smaller assignment landed last | `G-42`, `G-63`, `G-64`, `G-69`, `G-70`, `G-71` — all six marked **Done**, none of which could run | **FIXED 2026-09-19** — `EmbeddingMatrix.set` is serialised and the index is built once under a lock. `tests/test_vectors_concurrent.py`, with the non-vacuity arm checked by removing the lock (2 failed). Six concurrent searches now return 200 with 8 hits each. **Nothing in the suite touched the structure from two threads**, which is why a green suite carried a dead endpoint |
| D-21 | **A stored fit restored the picture and not the anchors.** `G-12` serves a layout out of the store without calling `build_page_layout`, and with it skips the side effect that records where each page was DRAWN — so an unfolding had no anchor for the space it was in | `G-54` unfolding, `G-12` persistence | **FIXED 2026-09-20** — `remember_page_positions` rebuilds `_PAGE_POS` from the stored payload, which carries every page's url and position already. **`D-20` again by a different route**, and the second half is the worse half: `unfold`'s fallback borrowed anchors from whichever space HAD them, so a missing euclidean anchor silently became a spherical one and chunks landed **378 units** from their node against a ball of radius 90. The fallback is gone — a space with no anchor derives one from the live fit, which is at least the space the reader is in. Caught by `G-54`'s placement assertion within minutes of `G-12` landing |
| D-22 | The layout cache and the persisted fit were keyed on a chunk **count**, so a stored fit was served to a corpus it had never seen | *“a fitted layout is persisted and queried back instead of refitted”* (`G-12`) — for the question it answered | **Fixed 2026-09-20.** A count is not an identity: purge twenty pages, capture twenty chunks elsewhere, and the key is unchanged while the corpus is not. Found by `G-54` passing alone and failing in sequence. Measured cold against the live store: the served page layout still carried nodes for `live_mutate.html` fixtures purged hours earlier, and unfolding one of its pages put the chunks **643 units from the page against a ball of radius 90**. `GraphStore.corpus_fingerprint()` hashes the Page table's urls and per-page chunk counts in order — one indexed scan on the path that already paid for the count. Same cold sequence after: **90.0**, and `G-54` passes in the full suite where it had read 238. Both arms in `tests/test_corpus_invariants.py`: a different corpus of the SAME count must change the fingerprint, and an untouched one must not churn. The same discriminator failure as the blanked `[n]` and the cumulative `repairMs` — a number two states share cannot tell them apart |
| D-23 | **The sidecar segfaults during a live capture's chunk ingest**, under sustained load | *“one page's failure must not end a corpus run”* (`S-15`) — and a process that dies ends everything | **Defect — diagnosed, not fixed, 2026-09-20.** Seven crashes under a full `confirm.mjs` suite, native, exit 139, no Python traceback. `-X faulthandler` names one frame every time: `kuzu/connection.py:execute` ← `graphstore._batch` ← `graphstore.ingest` ← `workspace.ingest_chunks` ← `sidecar._post_capture`. **It is not a Python-level race**: at the fault every other thread is parked in `wait` or `select`. Memory steps hard just before it — 1,935 → 2,199 → **4,767 MB in 11 seconds**, then gone. **Four mitigations applied, none of them the cure**, all kept because each guards a real hazard: a fit lock (concurrent UMAP on request threads), a connection lock (kuzu reads ran unserialised against writes), a weight-aware `_batch` slice, and a bounded `buffer_pool_size`. The pool bound lowered the peak from 4,767 to 2,242 MB and the process still died, which rules out simple exhaustion. **Not caused by this session's changes** — the first crash predates them. Next step, untested: the 4.9 GB store has now survived seven hard kills, so it may be damaged; run the same suite against a freshly scanned workspace to separate a corrupt store from a kuzu fault. The suite reaches **20 of 21** before it dies, and `confirm.mjs` now stops and says the sidecar went away rather than reporting 28 broken features |
| D-24 | **The live checks could not see the interface.** Every graph row was scored on `fitX/fitY/fitZ` — the fit's own space — and never projected to pixels, so the requirement passed while the picture failed | `G-4`, `G-5`, `G-21`, `G-6` | **Defect — instrument built 2026-09-20, the rows it invalidates are D-25.** `obsidian-plugin/src/harness.ts` puts three things on `window.__domvec`: `ui()`, the interface as a data structure in SCREEN pixels that tells drawn from merely present; `trace`, every sidecar call captured by wrapping `fetch` ONCE at the boundary rather than at twelve call sites that go stale; and `act()`, a gesture through the application's own paths returning the UI before, the UI after, and the backend work it caused. Measured on a real page: `scan` → 7 calls, 930 ms, `/sensor` x1 and `/capture` x6, 0 failures. `cdp.mjs` already had `axTree` and `mouse`/`click`/`drag` and `confirm.mjs` used none of it. **Screenshots are not the answer** — expensive, and a picture cannot be asserted on |
| D-25 | **The projector's picture is not measured where a reader meets it** | `G-4`, `G-5`, `G-21` | **Open, and the first numbers here were WRONG — corrected 2026-09-20.** I reported "86 of 97 nodes overlap" from a screen-space 2D test. That conflates DEPTH: in a 3D projection two nodes far apart along the view axis land near each other in pixels, and rotating separates them. Measured in world space, where the collider works, only **14 of 97** genuinely interpenetrate (median gap 69.3 against a median radius 19.65). The 2D figure is a fact about a still frame, not a defect, and I filed it as one. **What survives**: at chunk level **116 of 558 nodes were off the canvas**; the cloud uses about **a fifth of the pane**; and the node SIZING was self-defeating by arithmetic — at `spacing.p50 / 6` the drawn diameter equalled the median spacing, so every node closer than the median overlapped and half are by definition. Fixed to `/12`: drawn radius 39.3px → 20.4px. **Still open**: the fit is tight (fit→drawn drift 0–22) and framing wastes most of the pane. **The “simulation never moves a node” clause was wrong and is withdrawn (2026-09-20).** Velocities do stay 0 through a reheat, and the reason is that there is nothing to push: counted in world space with the pane's OWN collider radius function, **0 of 7,750 pairs** interpenetrate, so `forceCollide` is at equilibrium rather than asleep. Two other readings in that clause were also environmental — `cooldownTicks` reads `null` only because `JSON.stringify(Infinity)` is `null`, and a render loop that measured **0 frames in 2 s** ran at **407 frames in 2 s** once the minimised window was woken with `Emulation.setFocusEmulationEnabled`. The real defect at this level is D-27. The proposed shape is **force-directed chunks within force-directed UMAP page nodes**, relaxed at each scale |
| D-26 | **Most markdown lines came back with `key: ""`, so a click could not name an element in the page** | *“It sends the line's ADDRESS, not just its text … it is what lets a click in Obsidian name an element in the real page”* | **Defect — diagnosed and fixed 2026-09-20. The first filing of this row was wrong in its headline number and in its cause, and both are corrected here.** *What was wrong:* it reported “331,020 addresses against 36,799 anchors — 11.1%” as the coverage figure. That is the wrong denominator and it is not answerable: an ADDRESS is every point the trie holds for a page, an ANCHOR is one per rendered markdown LINE, and a page holding thousands of addresses renders a few dozen lines. It also generalised from one sample of 8 chunks that happened to land on affected pages. Measured properly, per page: **34 of 74 sampled pages were fully keyed, 29 were at zero, 11 partial — 60.1% of lines**, all-or-nothing per page rather than uniformly broken. *The actual cause:* the anchors were there all along; their addresses had a blank `akey`, which will not parse, so `addresses_of` silently dropped every row. **118,180 of 331,242 addresses (35.7%)** held a blank key, and affected pages were at 100% while the rest were at 0%. The guard in `ingest` — `needs_value = aid not in unchanged_addresses` — was a function of `content_hash` ALONE while the write it skipped sets six columns including `akey`, so a row missing its key was judged current and left that way **permanently**: re-scanning cannot move a content hash that never changed. That is `CLAUDE.md` 5c applied to a row rather than to a classification. *Reproduced from the cause, not observed:* `tests/test_address_rewrite_skip.py` blanks the keys on a fresh store and re-ingests the identical page — **505 of 505** stayed blank before the fix, with a non-vacuity arm proving a fresh ingest writes every key. *Fixed two ways:* the guard now compares `akey` as well (it is derived from `url\|xpath\|tag\|accessor`, so one comparison covers four columns), and `repair_blank_keys` rebuilds the string in place from those columns — no re-scan, because the key is derived, not captured, and the rebuilt key is asserted byte-identical to the original and to parse back. **Live corpus after the repair: 118,180 → 0 blank addresses, 1,947 → 0 blank-key anchors; pages fully keyed 34 → 55, pages at zero 29 → 5, lines keyed 60.1% → 91.7%.** `G-39`'s own failing gesture now works: the xpath `…/ol/li/article/h3/a` that `confirm.mjs` reported as “no chunk draws” with `ringed: 0` resolves in 2 ancestor steps to a chunk with **6 lines, 6 keyed, 2 controls**. `/health` reports `addresses_blank_key`, `anchors_blank_key` and `unreadable_addresses` so neither cause can go silent again |
| D-29 | **Five pages still serve every line unkeyed, and their addresses are now whole** | same as `D-26` | **Defect, open, found 2026-09-20 after D-26's repair.** With `addresses_blank_key` at 0 corpus-wide, a chunk that still returns no keys means `addresses_of` found **no `Anchors` edges at all** — a genuinely missing anchor rather than an unreadable one, which is what D-26 was originally filed as. It affects 5 of 74 sampled pages: ar.wikipedia, MDN's JavaScript reference, mastodon.social/explore, nodejs.org/api/fs.html and en.wikipedia's browser comparison. **Recorded rather than guessed at**: not yet established whether these chunks were written by a path that never produced anchors, or whether `_reconcile` deleted them and `fresh_anchors` did not put them back. The 11 partly-keyed pages (71–96%) are a separate question — a positional drift between `_reflow(stored.md).splitlines()` and the `anchors` array, which `chunk_payload` zips by index |
| D-30 | **The harness could not reach most of the requirement space, so the requirement space was argued about instead of measured** | the whole of Part I | **Defect — built 2026-09-20.** Every verification behind `D-26` and `D-27` was a throwaway script over a raw CDP socket: no history of having been wrong, and two of them WERE — a screen-space overlap count that conflated depth, and a branch query that counted an inter-page link as an unfold branch. The MCP surface is now eight tools wider: `wake`, `graph_probe`, `key_coverage`, `repair_keys`, `confirm`, `design_state`, plus the gestures `unfold`, `click`, `retrieve` and `reload`. **One persistent CDP session, woken once** — `setFocusEmulationEnabled` lasts exactly as long as the session that set it, so a connect-evaluate-close cycle can never be awake, and a minimised window reads 0 rendered frames in 2 s against 407 awake. `confirm` returns a verdict per requirement WITH the numbers it decided on, refuses to run when the sidecar is down rather than scoring its absence as broken features, and waits for the pane it just reloaded. **It found four defects in its own first four runs**: a reload routed through the harness it was replacing (so the first run scored the previous build), a `fetch` guard that was a boolean and could not be re-earned across a reload (`calls: 0` for work that happened), a containment force that called `graphData()` inside a tick and took the projector down, and a probe measuring reach from a hub the collider moves rather than from the fixed anchor containment is defined against — which reported a 341-unit spill while **0 of 33** branches were outside their territory, and very nearly had a correct fix reverted. **Live: 13 of 14** |
| D-31 | **Some pages hold chunks whose lines have no `Anchors` edge at all** | as `D-26` | **Defect, open, 2026-09-20. This is what `D-26` was mistakenly filed as, and it is real but much smaller.** With `addresses_blank_key` at 0 corpus-wide, a chunk still serving `key: ""` means `addresses_of` found no edges. `G-39` is the live failure: allrecipes.com/recipes returns a chunk with **0 of its lines keyed**, so there is nothing to resolve and the gesture cannot name an element. **Narrowed, not guessed**: `tests/test_capture_path_keys.py` puts the delta path — `ingest_chunks` with `complete=False` and addresses derived from the chunks' own line anchors, which is exactly what the browser cell does — through the same questions on a fresh store, and it writes every key and strands no anchor. So the delta path is clean in isolation and the cause is elsewhere. **The strongest remaining lead ties this to `D-23`**: blank keys reappeared after a run during which the sidecar segfaulted, and they were concentrated entirely in the LARGEST pages — 11 pages at 100% blank holding 26,298 / 22,533 / 10,778 / 9,769 / 8,466 addresses, against 63 pages at 0% — which is the same `_batch`-inside-`ingest` frame `D-23`'s faulthandler names every time. A process dying mid-batch would leave the node MERGEd and the `SET` lost, which is precisely the state observed. Not yet proven || D-27 | **The two layers do not nest: the second one covers the first.** An unfolding opened into a ball of a FIXED 90 world units and sized its contents in a different unit from the container they belong to | *“force-directed on chunks within force-directed (scale-wise) UMAP nodes”*; `G-53`, `G-54`, `G-34` | **Defect — found and fixed 2026-09-20.** Three faults, one symptom. (1) **`UNFOLD_RADIUS` was a constant, and it was bigger than the gap between pages.** Nearest-neighbour spacing across the 97 page nodes is **71 units at the median** (49 p10, 104 p90) against a 90-unit ball, so **67 of 97** pages had at least one other page inside their own unfolding, up to five. It is now `0.45 ×` the distance to the nearest page, read from `_PAGE_POS` — the layer-1 layout itself — so it tracks a corpus that spreads or tightens. (2) **The two layers were sized in different units.** A page is `sqrt(chunks it holds)`; a chunk fell back to `sqrt(chars)`, because neither `unfold` nor `place_into` emitted `val` at all. Measured live: chunk world radius p50 **17.24** against a median PAGE at **11.43** — contents 1.5× their container. Both paths now emit `sqrt(chunks stood for)`, so `members <= chunks` makes the nesting a property of the trie rather than a tuned number. (3) **The hub collapsed to `val` 1** on unfold (radius **5.78**), making the container the smallest object in its own neighbourhood; only the billboard `image` is dropped now. **Measured after, on the same 97 pages:** reach/nearest-gap p50 **0.225**, max **0.450**, **0** pages spilling, **0** branches bigger than their page, and the unfold reach is no longer constant — 10.8 / 22.1 / 41.0 at p10/p50/p90. **Non-vacuity, same pages and same positions with the old constant planted back:** p50 **0.937**, max **2.824**, **81 of 97** spilling, **287** branches bigger than their page. **Placement alone was not enough, found 2026-09-20 by the new `graph_probe`.** Containing a branch where the sidecar PUTS it says nothing about where relaxation leaves it: RFC 9110's 31 branches, placed inside a 33-unit ball, were carried by the collider to **102 units** against a 74-unit gap. Three things were needed and all three are in. (a) `unfold` emits `room` and `anchor` with each branch and the pane runs a one-sided radial `contain` force -- a node inside its territory feels nothing, so the local fit survives; a node outside is pulled to the SURFACE, not the centre, which would collapse an unfolding into its hub. Its strength is floored rather than alpha-scaled, because a boundary that fades as the simulation cools is a boundary only while nothing is settled. (b) Branches are **scaled to the territory**: 31 spheres cannot pack into 19 units at any arrangement, so the collider and the boundary were being asked for incompatible things and strength only decided which failure you got. Radius is capped at `room / (1.6 * cbrt(n))`, one factor for all of them, so relative size -- the statement `val` makes about the trie -- is preserved. (c) **The opened hub is bound to its own anchor.** It was not, so the branches stayed and the page walked: 18.1 units of reach from the anchor against **283.8** from the hub, on one unfolding. Measured live on that same 31-branch page after all three: room 59.1, reach from anchor **58.2**, reach from hub **63.4** (the two now agree), hub drift **6.0**, gap to the next page 128.5, reach/gap **0.453**, branches outside their room **0**, world-overlapping pairs **0**, hub radius 18.98 against a branch median of 9.73. The live-capture path scores the same: 343 chunks through `/place`, **0** past halfway, **0** without a `val`, **0** oversized |
| D-32 | **Lexical rows were lost on every hard stop, and rows indexed while a chunk was empty stayed empty** — 4,724 of 16,251 chunks (29%) could not be returned by any query | *“the retrieval overlay”* (Addendum IV); `G-3` strict product | **FIXED 2026-09-23.** The frequency matrix was written only by `close()` and `rebuild_lexical()`, so a sidecar ended by a kill lost every row added since it opened while the chunks stayed in the graph; and `restore_markdown` refilled markdown without re-deriving rows built from the empty text. Measured by the start-up repair: **4,324 rows missing, 400 empty**. Now: `rebuild_lexical` also refreshes empty rows, the sidecar runs it at start (1.4 s), and `save_lexical` writes the matrix within 30 s of any change. Next restart: 0 added, 0 refreshed, 16,251 held. `tests/test_lexical_coverage.py` (planted empty row; a session that never closes) |
| D-33 | **The semantic factor scored each chunk with ANOTHER chunk's similarity** | `G-3`; *“retrieval stays TRIPLE”* | **FIXED 2026-09-23.** `EmbeddingMatrix.similarities` answers in the embedding matrix's own row order (arrival order); search read it as frequency-row order. The two agree only on a corpus built in one pass — the frequency matrix reclaims retired rows and gains repaired ones, the embedding matrix appends. Live: pages captured that afternoon were unreachable by their own name ("Persona": 0 hits) and "Ternary search tree" ranked coinmarketcap above the ternary-search-tree page. Now joined on cid; live after the fix, "Ternary search tree" returns that page 3/3, "Persona" and "Shin Megami Tensei" the Persona page, "HTTP header field" net/http and RFC 9110. `tests/test_semantic_row_alignment.py` — planted with the two matrices in opposite orders: before the fix, searching a chunk's exact meaning returned nothing and a vectorless chunk scored 1.0 |
| D-34 | **A search waited minutes: the first one after a start, and any one after browsing** | *“the retrieval overlay”*; `G-69` continuous scrolling | **FIXED 2026-09-24.** Measured by timing the index's own phases: the first build spent **146 s hydrating** embeddings -- `EmbeddingMatrix._grow` added one row per vector and copied the whole matrix each time (old growth: 7.9 s at 4k rows, 39.2 s at 8k) -- and a search after a capture spent **38 s running the encoder inline**. Now the matrix doubles (16k vectors in 0.21 s), hydration reads in bulk, the sidecar's search never runs the encoder (`embed_inline`, the worker owns it), and the index is built at start. Live: index warm 5 s after start; searches 0.11-0.21 s; a page browsed seconds earlier found by its own name in 1.03 s (rebuild: hydrate 116 ms, build 419 ms, encoder 0) |
| D-35 | **Navigating to a new page, the overlay and the streaming "completely degrade"** | *Addendum IX: “the chunk overlay and streaming from the electron scanning completely degrades when navigating to a new page”*; `S-12`, `G-91` | **Confirm — fixed and seen in the app 2026-09-27** (`a0f3a31`; check `D-35`, fresh run_20260927162317): across a navigation to a new heavy page the longest drain gap is 1.2 s and hover answers 234 ms after the first drain (from the page's own chunking); planted arm (drain held across the capture, store-only hover) 4.3 s / 3.9 s, caught |
| D-36 | **A chunk's panels do not read like the page.** DuckDuckGo's Search Assist answer, one sentence on the page, is three bullets in the billboard and the side card, split at its inline `<b>`; buttons print as `( label )`; protocol-relative image urls (`//external-content...`) fail to load; a raw href stands in for a control | *2026-09-27: “the panel rendering of the chunk in both GUI locations (3D billboard and 2D clipboard) are discontinuous with how the text/html is rendered in the original webpage, which is a bug”*; `G-81`, `G-82`, `G-102` | **Confirm — fixed and seen in the app 2026-09-27** (check `D-36`): card AND billboard carry the page's text in order (1.0), no distilled marks, the page's title colour and breadcrumb colour/decoration, favicon loaded; snapshot 4 ms, 9/9 elements; planted arm (distilled panels) caught |
| D-37 | **New diffs are not seen outlined.** The diff outline was a 1.2 s flash of on-screen chunks only; most of a drain lands off screen, so new content was never outlined where the reader looked. Per-drain reasons now on each trace (`flash`: flashed / covered / unstored / offscreen / nobox) | *2026-09-27: “overlays for completely new diff updates are completely broken and have not been observed for several minutes”*; `G-90`, `G-92` | **Confirm — fixed and seen in the app 2026-09-27** (check `D-37`): results loaded off screen are outlined when the reader scrolls to them (6 of 6); planted arm (1.2 s flash) shows 0, caught |
| D-38 | **The Obsidian window hung during the hard-page run and the browser cell went blank.** The renderer answered nothing, not even the debugger, with idle CPU (a synchronous wait); the run lost its connection and the reader saw an empty cell | *2026-09-27: “Nothing showing in the obsidian browser. It's currently a blank screen”* | **Defect, open.** Recovered by a browser-side reload; `Live.recover()` does it from the harness; the cell reopens its last page. The CAUSE (which page, which wait) is not yet found: G-101 must visit pages one at a time with a watchdog |
| D-39 | **Probe pages leaked into the reader's working store.** Two DuckDuckGo queries my terminal probes ran ("b tree split 7927", "trie cache 544") were stored as pages and drawn among the reader's | *2026-09-27: “the nodes may not be pages/url nodes and show leakage”* | **Defect, open.** Purged (145 + 16 chunks). Guard to build: exploration probes run against a test store, never the working one |
| D-40 | **Hover and diff lag after a long scroll.** On discourse's /latest the outline trailed the pointer by 65-138 ms, and a new batch of topics reached the overlay 150-600 ms after the page wrote it. Causes, measured: the hover and the drain were POLLED, and a pulled crossing queued behind the page's own long tasks (a bare `executeJavaScript('1')` 12 ms p50, 942 ms max while scrolling); the fold waited for an idle callback (up to 320 ms); the drain crossing grew 30 -> 231 ms drain by drain. Fixed: the sensor pushes both on the page console (native console only, a per-load nonce in the prefix), the hover computed at event time and the drain sent from the task that folded it, which on a pushing host is the mutation's own task (a microtask; one per frame in a burst) | *2026-09-27: “Significant chunk highlight-when-hovered lag after extensive scrolling ... it should be simple enough to continuously stream diffs from the mutationobservers to the electron overlay to the 3D gui without having to wait for database write queues”* | **Defect, fixed; check `D-40` judged ON discourse.julialang.org/latest (planted: `pull-drain` + `poll-hover`; the page's changes timed by the check's own observer, each matched to the drain that carried it).** The fixture `busy_feed.html` measured 3/6 ms page -> host (planted 155/163) -- mechanism only, not the reader's page. Probe on discourse after 40 wheel steps: hover move -> outline p50 8.4-9 ms, p95 11.4-14.4 ms; mutation -> overlay placed p50 74 ms, p95 91 ms for 30-topic batches with the frame-aligned fold, before the microtask fold |
| D-41 | **An open page's layout broke its own geometry.** The sunflower disc gave each chunk a slot by UMAP rank, blind to its parent, so a hub chunk's 30 edges crossed the whole disc and an open page read as a web converging on a point; laid in one camera's plane, it became a clumped ring once the reader orbited. Measured on Wikipedia's Radix_tree in the app: 34 of 65 drawn nodes buried (the planted no-collide arm: 9). Fixed: a radial tree on the disc -- each subtree its own wedge ordered by UMAP direction, internal nodes on inner rings, leaves staggered over m outer rings a collider step apart, the first ring outside the page's own billboard -- re-faced to the camera when an orbit ends | *2026-09-27: “force-directed layouts have incorrect geometries and constraints”* (with a screenshot) | **Defect, fix built; check `G-94` (planted: `sunflower`, `noreface`) measures crossings, chunks on the page's billboard, and burial before and after an orbit** |
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
| S-11 | The **256-token** window holds **throughout processing**, with a verification pass after the scan. A target, not a ceiling: a single indivisible unit may exceed it | **Partly — the verification pass now exists** (`domvec/analytics/window.py`, `--window-check`), which is the deliverable that kept this row Partial. It is what the row's other half is now measured by, and the answer is not yet clean. Measured on `build/corpus123` at 256, **with the two populations separated because they ask different questions**: chunks the chunker COULD have cut — **74 of 11,155 over, 0.66%**, max 803 — and single-line leaves, where the row itself permits an over — 161 of 2,978, 5.41%, max 1,554. **And the stage nobody had checked**: a merge group's assembled markdown is a new string, longer than any member by construction, and it is what a reader is shown and what re-vectorisation embeds — **5 of 517 over, max 309**. The pass counts what the ENCODER gets (`tokens.budget_for`), so a `code://` chunk is scored on the string after code spans are dropped; a budget enforced on one string and spent on another is not a budget. Non-vacuity: planting a multi-line oversize record is caught at cost 1,139 and the clean arm does not report it (`tests/test_corpus_invariants.py`). The **0.4% (21 of 5,337)** this row used to carry was a MIXED denominator over both populations on a different store; separated, the cuttable residue is 0.66% and the permitted one is 5.41%. What remains open is the 74 and the 5, not the pass |
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
| T-5 | The **local vault** is in the trie | **Done** — `domvec/vault.py` + `Workspace.index_note` + `domvec notes <dir>`. Addressed `vault://<vault>/<path>` with markdown's tree as `section`-wrapped xpath steps; 18 docs indexed to 786 chunks / 2,697 addresses and retrievable. Module dependencies and the directory tree as UMAP links (`G-8`/`G-10`) are still Open |
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
| M-3 | **Tables** | **Defect D-5** |
| M-4 | Images, web links, embedded links | Partial |
| M-5 | **Markdown panel links** to other panels | Partial — continuation links done, retrieval links absent |
| M-6 | Renders in regular / normal / **minified** form | Partial |
| M-7 | **No intermediated hierarchical fields** where a single trie path node was collapsed | Open — 39.0% of chunks carry one |
| M-8 | **Full deduplication of structural redundancy** | **Defect D-4** — 88% of in-chunk repetition is the page repeating itself |
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
| G-4 | **Inter-spatial normalization** — nodes are discernible, not a clump | **Defect D-25** — measured on screen the cloud uses **23.8% of the canvas** with more than half its nodes overlapping, and at chunk level it sits in one quadrant with 116 of 558 nodes off the canvas. The previous pass was scored in fit space, where the spread is real and invisible to a reader |
| G-5 | **Every node is on screen at the default camera** | **Partly — true at the level it was tested, false at the other.** Page level: **0 of 97 off screen**. Chunk level: **116 of 558 off screen**, 21%. The row does not say which level it means and the check only ever saw one of them **Fresh store, 2026-09-26: 33 of 41 on screen** after the suite's earlier checks opened pages -- the mixed-level case, still failing |
| G-6 | **Patricia-trie links drawn** | **Done — seen live 2026-09-19** — `confirm.mjs`, re-runnable and idempotent. Unfolding RFC 9110 draws **26 nodes and 26 links**, 0 unresolved endpoints, 0 dangling; all 26 carry a three.js line object attached to the scene, and the star is visible on screen. **The `Confirm` was hiding a defect.** The row claimed 31 nodes and 30 edges; live it was 26 and **0**, because `_edges_among` cannot draw an edge at the step a reader takes: containment runs parent-to-child and the branches are disjoint subtrees, so every edge it finds lies inside one branch and is dropped as a self-edge. Measured on that page: 1,072 containment edges, 662 with both endpoints surviving, **0 crossing two branches**. The 30 edges were a star from the parent, and `unfoldNode` had started REMOVING the parent. The hub now stays, shrinks to its smallest branch, and drops its picture |
| G-7 | **Markdown retrieval links drawn** | Open — and `G-14`'s measurement bounds what is available: page-to-page web links cannot be drawn in this corpus at all (0 possible edges). A markdown/vault link axis is a different edge set and is still unbuilt |
| G-8 | **Module dependency links** for codebases and Python modules | **Done 2026-09-20** — and NOT as a second graph. An import is categorised as a link, so `ContentAddress.is_url` says so, the store's existing `_link_pages` resolver picks it up, `edges()` routes it and PageRank counts it — the same treatment a hyperlink gets, which is the whole reason for spending an address on it. Measured on `domvec/` itself: **102 modules, 232 dependency edges, 2,180 edges for PageRank** |
| G-9 | …including modules inside **local PyPI packages** | **Done 2026-09-20** — the same walker pointed at an installed package, located by import rather than guessed at a path. Measured on numpy: 12 files → 510 addresses, 123 chunks, addressed `code://pypi/numpy/…` |
| G-10 | **Vault directory** drawn as links | **Done 2026-09-20** — a note's links become `LinksTo` edges through the same resolver a hyperlink and an import use. One change made it possible: `urljoin` performs relative resolution only for schemes it KNOWS, so `urljoin("vault://v/a.md", "b.md")` hands back `"b.md"` unchanged — not an error, just the input — and every vault link therefore resolved to nothing. `canonical_url` joins local schemes by hand now. A wikilink gets the `.md` spelling offered as well, since `[[Lattice]]` names a note and a note is a file; the store's own rule still decides, so a wikilink to a note nobody indexed stays an address — asserted as its own arm |
| G-11 | **Three sources in one skeleton**: web, vault, PyPI | **Done 2026-09-20** — one store holding all four spellings at once: `https://`, `vault://`, `code://` for the repository and `code://pypi/` for an installed package. Measured: 59 chunks, 653 addresses, **one trie**, every chunk's xpath resolving the same way whatever it came from. `tests/test_source_corpus.py` asserts the schemes coexist |
| G-12 | **UMAP embeddings persisted to the db** and queried straight into the graph view | **Done 2026-09-20** — a `Layout` node table keyed on everything the fit is a function of (corpus size, dims, space, level), so a stored answer comes back only to the question it answered. Measured on `corpus123` across a sidecar RESTART: **19.3s → 0.15s**, and the reply says `from_store: true` so a reader can tell which they got. A table rather than columns on `Chunk`: the payload belongs to a fit, and four fits of one corpus (page/chunk × euclidean/S³) would not fit in one column each. **The hazard it introduces is guarded**: a fitted reducer is a MODEL and does not serialise, so serving a stored layout would have left every unfolding answering "no fit to place into yet". `_ensure_projection` builds one on demand — verified live, 26 nodes and 26 edges out of a process that had only ever served a stored picture |
| G-13 | Re-projection **batched in a queue whose latency adapts** to the projection's own cost | Open |
| G-14 | **Graph linkage completeness** across trie, web links, markdown links | **Partly — and the web-link axis is EMPTY for a measured reason, not an unbuilt one.** The trie axis is drawn and confirmed live (`G-6`). The web axis holds **2** `LinksTo` edges over 96 pages, and `store.relink()` — a repair that re-resolves every url address against the pages held now, since a link is otherwise resolved once at ingest against whatever existed then — adds **0**. The ceiling is 0, and here is why: of **29,186** url-valued addresses, **2,675** are anchored to a chunk and **72** resolve to a page this corpus holds, and the two sets **do not intersect**. The links that point at pages we have are in addresses no chunk draws; the links chunks draw point outside the corpus. That is a property of a collection of unrelated pages rather than of a crawl, and `relink` stays because on a crawl it is the difference between a link graph and a scatter |
| G-15 | **Media present in the projector**, not only the panels | **Done — seen live 2026-09-19** (`confirm.mjs`). Nodes carry an `image` and draw as billboards; `G-21` separately confirms they are COLLIDED as panels rather than spheres |
| G-16 | Chunk deltas diffed **into the projector view** live | **Done — seen live 2026-09-19** (`confirm.mjs`, needs a `--capture` sidecar). The whole path in one gesture: the browser pane folds the page it is showing, `POST /capture` writes it, the worker vectorises, `place_into` anchors, and `absorb` takes the nodes into the picture already on screen. Measured on `books.toscrape.com`: **320 addresses, 26 chunks over 7 passes**, and all 26 arrived in the projector with a position, **0 on the frame** — the last being the arm that `D-17` would have failed while every count above it still looked right. 96 → 122 nodes |
| G-17 | The projection's **output space is spherical**, fitted with an angular metric rather than rescaled into a cube afterwards | **Built (`G-18`); what is Open is the COLOUR axis only.** Addendum III asked whether the third angle is spent on colour (S³) or the fit is S² and colour becomes a legend; that is still unanswered. The metric itself was dropped at 21:39 and rescinded at 22:00 — see Addendum IV, "Addendum III, dropped and then restored" |
| G-18 | Points are **quaternions and the distance between them is the quaternion distance** — the geodesic angle on the unit 3-sphere, `2·arccos(\|⟨p,q⟩\|)`, absolute because `q` and `−q` are one rotation | **Built, measured, not default** — `domvec/obsidian/spherical.py`, §M.9. A numba `output_metric` over three hyperspherical angles (umap-learn's own advice: parameterise without coordinate constraints), gradient-checked against finite differences. It keeps **0.19** of the encoder's 10-NN neighbourhoods against the Euclidean fit's **0.38**. **"Not default" understates it: see D-11** — at the default page level `?space=S3` is accepted and ignored, so the user's *"apply the updates throughout"* (21:23) is not met by the surface they actually open |
| G-19 | The view is **centred on the origin** | **Partly — true by construction, not true of the picture.** `spherical.to_ball` does send the identity rotation to the origin. But nothing puts the DATA near it: measured on 96 pages, the centroid sits 94.0 from the origin against a mean radius of 94.9 — every page on one side — so the origin-centred camera frames an empty middle with the corpus as a blob off to one side, which is `G-5` failing in S³. `_spherical_init` now centres the warm start (D-12), which moves it without fixing it. The verbatim is *"we center our focus on the origin"*, and that is a claim about where the data goes, not only where the camera looks |
| G-20 | **Force-directed relaxation seeded from the UMAP embedding** — UMAP initialises, the simulation converges | **Done** — `graph.ts`. Nodes carry `x/y/z` from the fit instead of `fx/fy/fz`, and `fitX/fitY/fitZ` alongside so drift is measured rather than assumed. `charge` and `center` are removed and `link` is kept at **zero strength**, not removed: `forceLink` is also d3's id resolver, and dropping it left all 2,961 edges holding their endpoints as strings, so every patricia and inter-note link stopped drawing with nothing reporting an error. Measured cold: 2,302 of 5,337 nodes sit exactly where the fit put them, which is the proof no force but collision runs |
| G-21 | **Nodes never overlap**, with billboards sized as panels not spheres | **Defect D-25** — the check measured fit-space separation against a fit-space radius and passed. Measured in SCREEN pixels through the application's own `nodeRelSize`: **54 of 97 page nodes overlap** a neighbour at the drawn radius, closest decile 10.1px apart. The billboard half is untested at the pixel level |
| G-22 | **The chunking window counts only what a model reads.** Link targets — `href`, `src`, bare urls — are excluded from the token budget; the render keeps them | **Done** — `tokens.for_model`/`tokens.budget`, §M.7. 52.5% of the corpus's rendered tokens were addresses. **No live check, and deliberately so**: the comparison that matters is `budget(x)` against `count(x)` over the same string, and the tokenizer is server-side — a whitespace word count is not a baseline for a subword tokenizer, and a check built on one reported a link-heavy chunk at ratio 1.06 and called the exclusion broken. §M.7 is the measurement |
| G-23 | **Two vectors, two strings.** The quantized semantic embedding is given link-free markdown; the frequency matrix keeps url path words as lexical terms | **Done** — `vectors.VectorQueue.push` strips; `vectors.tokens` does not. An address is not a sentence; a url tail *is* a term |
| G-24 | **Exact duplicates are resolved in the database, over the aggregate DOM chunks, before any embedding is consulted** — page-scoped, byte-exact, no threshold | **Done** — `graphstore._same_content`, §M.8. Marked, not merged: `Anchors {ord}` pairs lines to addresses by position, so collapsing the nodes would misattribute every line |
| G-25 | **One node per distinct rendering in the projector**, with the copy count carried, not one node per address | **Done** — `layout.py`. archive.org drew a cluster of **125** identical nodes; dropped before the fit, because a duplicate embeds to the same vector and spends the projector's neighbourhood budget on a point it already has |
| G-26 | **Stage two: near-duplicate aggregation over the quantized semantic embeddings.** DBSCAN (or a nearest-neighbour feature aggregation in its place) merges chunks that are the same thing said differently, which exact bytes cannot reach | **Done** — `domvec/aggregate.py`, DBSCAN over the quantized semantic vectors. 494 groups over 1,248 chunks on `corpus123`, against a null arm of zero (§M.12) |
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
| G-46 | **Interactive fields in the shadow-DOM view act on the real page** through the trie, when a connection exists | Open — §O.2, and it is constraint 2 of `CLAUDE.md`: a field is acted on in place |
| G-47 | **Scanning migrates from Selenium to the Electron browser** that hosts the cell, and that is where scanning then happens | **Done** — the browser cell folds the page it is showing and hands drains to `POST /capture`. Verified against the scanner it replaces on the same page: 176 addresses, 14 chunks, 7 passes, identical. Reported first as *"I don't see the scans running in the new browser panel like I would hope for our work"* (2026-09-13 20:34), which left no requirement at the time: the panel existed and Selenium was still doing the scanning behind it |
| G-48 | **Headers, fields and formatting are part of the text that gets vectorised** — the crypto-panel case is the standing example of what is lost when they are not | **Partly** — link-free markdown keeps headers, fields and formatting and drops only addresses, so the structure reaches the encoder. The crypto-panel case that motivated it has not been re-measured |
| G-49 | **The local codebase, the vault, and locally-installed PyPI packages are in the trie too**, alongside the web scans | **Done 2026-09-20** — `domvec/source.py`, addressed `code://<root>/<path.py>` exactly parallel to `vault://`, with Python's own tree as the xpath in the sensor's `name[ordinal]` spelling. Measured on this repository: **214 files, 16,074 addresses, 4,395 chunks in 33.4s** (156 ms/file). Nothing downstream learned a word — `from_tags`, the chunker, the frequency rows and the graph are the page path untouched, which is the whole reason the addressing was defined to look like a page's |
| G-50 | **The scanning code is itself a visible chunk.** A reader can see the script that runs the browser scan, in the graph, while watching that scan happen in the browser panel | **Done 2026-09-20** — `.js` joins `SOURCE_SUFFIXES`, so the FOLD is in the trie: `code://domvec/domvec/core/js/sensor.js`, **1,001 addresses over 71 chunks**, 67% of the render dropped before the encoder. It gets COMMENTS, not structure: `_js_comments` is a scanner that tracks strings and template literals so a `//` inside `"http://…"` is not counted — 1,000 comments over 2,870 lines — and it says plainly what it cannot do, the regex literal, rather than pretending a regex is a parser. The Python half (`capture.py`, the sidecar, the analytics) comes from `G-49` |
| G-51 | **Dependencies are tracked throughout** — imports and package requirements are edges in the same graph as page links | **Done 2026-09-20** — same graph, literally: `LinksTo`, the relationship a hyperlink uses. `canonical_url` passes `code://` and `vault://` through as identity rather than rejecting them, which is the one change that let a local address be a link target at all. **`relink()` is what makes it complete**: 100 edges at ingest, **232 after** — a link resolves once against the pages held at that moment, so a module that imports one indexed later gets no edge until the repair runs. Both spellings are offered for `from pkg import lib` (a submodule or a name) and for a package (the module file or its package init), and the store's own rule decides: a link becomes an edge only when its target is a page we hold |
| G-52 | **Source is vectorised by its COMMENTS AND DOCSTRINGS ONLY, never the code itself** | **Done 2026-09-20** — and it is one flag, because `domvec/source.py` makes the separation a property of the RENDER: docstrings, comments and names are prose, code is a code span. `tokens.for_model(text, drop_code=True)`, switched on by the `code://` scheme in `vectors.VectorQueue.push`. Measured over this repository: **985,336 rendered tokens → 304,039 for the encoder, 66.2% is code and is dropped** — the direct parallel to `G-22`'s 52.5% link targets, and the same argument: an identifier is not a sentence, the way a url is not. The code stays in the chunk a reader opens and in the trie that addresses it. **Off by default for everything else**, deliberately: a web page's code sample is part of what that page says, and dropping it would change every existing embedding to serve a requirement about source files. Both arms tested, and both directions of breakage fail the suite |
| G-53 | **The projector draws PAGES by default, not chunks.** One node per shadow DOM; a page unfolds into its chunks on demand | **Done** — `layout.build_page_layout`, `?level=page`. 96 pages over 14,169 chunks, **20,309 draw calls become 94**, and the fit takes 8.8s where the chunk-level one takes 95. A page's vector is the mean of its chunks', renormalised, and the fit is ON the pages — which is what lets a chunk be `transform`ed into the same picture when its page unfolds |
| G-54 | **Dynamic unfolding over the patricia trie** — an UNRAVELLING along a chunk's own single path, root to leaf, not an expansion of a subtree | **Done — seen live** (`confirm.mjs`). `layout.unfold`, `POST /unfold`, click in the pane. A step descends the shared path until it BRANCHES and shows the branches, which is patricia compression and is why a chain of wrappers nobody chose costs one step rather than five. **Where the chunks GO was wrong until 2026-09-19** (`D-17`, `D-18`) and is now a LOCAL fit anchored at the page node: transforming chunks into the page-level fit kept 0.078 of their 8-NN neighbourhoods against a random baseline of 0.030 — not a projection of anything. A fit over the page's own chunks keeps **0.507**. The page's mean cannot stand in for its chunks, because the mean is exactly the direction they all share and what distinguishes them is what is left after it is removed. Global position comes from the page node, which already carries it; colour stays the global fit's, so two chunks on different pages that mean alike still look alike |
| G-55 | **Unfolding depth follows the reader.** How far a page unfolds is a function of how many results they have continuously scrolled through in the browser's retrieval overlay | **Done** — §M.14. The overlay's hit list IS the depth: it grows as they scroll and the projector opens the page to exactly it. Measured: 10 chunks drawn, then 30 after three scrolls, 96 nodes to 125 |
| G-56 | **Only the chunks matching the most recent debounced retrieval query are drawn live**, inside their unfolded page | **Done** — §M.14. Clicking MDN's Headers index drew its **10 matching chunks**, not its hundreds, and the page node was removed |
| G-57 | **Clicking a node opens its shadow-DOM panel as a BILLBOARD inside the 3D view** — draggable, in the projector, not a separate Obsidian pane | **Done — seen live 2026-09-19** (`confirm.mjs`). `graph.openBillboard`, anchored by `graph2ScreenCoords`. Measured: 19 lines drawn, **anchored to 0px** of its node's projection, inside the canvas, follows the camera, **pins where it is dragged**, and closes. It runs its own frame loop rather than `onEngineTick`, because the simulation stops ticking once it settles and the camera keeps moving after that — a panel anchored on ticks detaches the moment a reader orbits, which is exactly when they are looking at it. The canvas needed `position: relative`: `graph2ScreenCoords` answers in the CANVAS's frame and the layer would otherwise have escaped to the pane and drawn every panel a caption-bar below its node |
| G-58 | **In tandem, the Electron browser navigates and scrolls that chunk into view**, and the browser is the primary panel representation | **Done — seen live 2026-09-19**. Both clauses now hold, and the second only became true with `G-57`: the navigate-and-scroll is measured under `G-40` (parked at scrollY 4945, click moved it to 363 with the element in view), and the Obsidian chunk pane no longer opens on a click at all — the panel became a billboard in the projector, so the browser is what shows the page and nothing competes with it for the workspace. §O.5 |
| G-59 | **The Obsidian-native chunk panels become the OFFLINE FALLBACK format** — the shape the structures take when there is no live page to point at, and **offline the billboard is a main Obsidian panel rather than a projector billboard** | Open — §O.5. The second clause is verbatim and is the one distinction from `G-57`: *"seeing still the billboarded panel that we currently have as a more 'main' panel within obsidian rather than in the UMAP projector"*. Online the panel opens in the 3D view; offline it takes the pane |
| G-60 | **A toggle saves the full page as the Electron browser presents it live**, for offline use | Open — §O.5. Saved as presented, not as fetched: the composed tree the reader saw, scripts already run |
| G-61 | **A saved page whose source does not carry its layout is INFILLED from the traced chunks** | Open — §O.5. The trie holds `url : xpath : markdown : content` for every address; a saved source missing its render is exactly what that can repair |
| G-62 | **With no connection, the page is reconstructed fully rendered and scrollable from the scan trace alone** | Open — §O.5. The strongest form of the affine map: the trace IS the page |
| G-63 | **Retrieval overlay above the Electron browser, coarse-to-fine**: merged chunks first, then within-shadow-DOM top-k | **Done** — `search_payload`. Coarse suppresses a merge group's members so the lead stands for them, because a reader scrolling a ranking does not want the same passage eight times; `coarse=0` ranks the members, which is what a click expansion inside one page wants |
| G-64 | **Cross-page ranking fits the 256 pure-text window** — the most relevant parts of different shadow DOMs, inside one budget | **Done** — `?budget=`. Results are taken until the next would not fit, counted in `tokens.budget`, so a list handed to a model is a list that can be handed to a model |
| G-65 | **Aggregation runs on the DIFF STREAM, not only at the settle.** A chunk rewritten while the reader browses rejoins or leaves its merge group as it changes | **Done** — §M.12. Queued per page on every capture, debounced 1.5s so it lands when the reader pauses, and run on the embedding worker so it is ordered after the vectors it needs. Verified live: a 128-chunk page the corpus had never seen went from 0 to **23 merge groups in 2 seconds**, with nothing asking |
| G-66 | **The O(delta) budget is stated per phase and measured**: fold, then the verbatim's own sequence — *"dedup-vectorize-dedup-aggregate-vectorize, and projections through the async batched queue of UMAP transforms"*. **Two dedups, not one, and the second is not the merge**: `G-24` on bytes before any vector; then vectorise; then the embedding pass that *establishes* near-duplicate links (*"we first establish duplicate-links and **then** merge"*, 18:54) — which `G-29` says is a separate verdict from merging; then aggregate (`G-26`); then re-vectorise the group (`G-27`'s `group_embedding`); then transform. Timed as six phases, not five | **Done** — every phase of a capture is timed separately and reported: decode, absorb, render, store, place, plus the store's own five statements. §M.11 is what that found |
| G-67 | **UMAP transforms go through an async batched queue** — a diff does not wait for a projection, and a projection does not run per chunk | **Confirm — built 2026-09-23** (`domvec/obsidian/projector.py`). The embed worker hands every chunk it just embedded to the projector's queue; a worker drains it in batches of 256 into the fit, off the request path. Live, a page new to the store: 79 chunks stored → 79 embedded → 79 projected within 4 s, no request waiting on it. `tests/test_chunk_projector.py` |
| G-68 | **Interactive fields in the billboarded shadow DOM act on the live Electron page** through the trie | Open — §O.5, and it is `G-46` at the surface a reader actually touches |
| G-69 | **Retrieval is continuous scrolling over a ranked list, not top-k.** Top-k is what a click expansion uses; the overlay itself keeps going | **Done** — `?offset=`, and the list asks for more as it nears its own bottom. Measured: 12 results on typing, 48 after three scrolls |
| G-70 | **Clicking a shadow-DOM node SCOPES the query to that url**, however the global ranking placed it. Right-clicking restores global scope | **Done** — the projector click sets the overlay's scope through the plugin, and a right-click on any node releases it. Brokered rather than held by either pane, because neither may require the other to be open |
| G-71 | **Scoped results unfold by the same mechanics as the overlay's** — one behaviour, two places | **Done — seen live 2026-09-19** (`confirm.mjs`). Scoped hits open their page through `showHits`, the page node is KEPT as their hub and marked open, and the containment star is drawn — the same shape `G-6` asserts for a click. The check had to learn what `G-63` learned: asking for "the" returned nothing, because a stopword scores ~0 lexically and under the strict product a zero is a veto |
| G-72 | **Every position the 3D graph draws comes from ONE chunk projector** — the default page view, an unfolding and a live capture alike. A page sits at the transform of its chunks' mean vector into the chunk fit; a merge group's lead speaks with its 512-token aggregate vector | *Addendum V: “Instead, stream O(delta) diff chunk updates in queue based batches to a fitted UMAP projector”*; *“the way our 3D graph layout is now computed”* | **Confirm — built 2026-09-23.** `/layout`, `/place` and `/unfold` answer from `projector.PROJECTOR`; the page-mean fit and `_local_positions` are off every default path (`?source=legacy` keeps them for comparison). Fitted on a sample of 4,000 of 14,516 drawable chunks (41 s), the rest transformed in (34 s). Live, the 79 chunk nodes of a newly browsed page sit at the projector's positions to **0.0 units**, none carrying the old local territory. Measured cost of the honest picture: only **43.4%** of chunks are nearer their own page's hub than any other (1.7% with page labels shuffled); pages interleave where their content does. `tests/test_chunk_projector.py` (planted: a sentinel written into the stream comes back from `/place` verbatim) **Exception, 2026-09-26:** before the FIRST fit exists, positions come from the force-directed fallback (`G-89`); the pane says so (`layout_mode`) and switches once the fit is ready |
| G-73 | **Panes follow the projector's stream, O(delta)** — what moved since the last sequence number, not a new layout; a new fit (epoch) redraws once and re-places what was open | *Addendum V: “streams to the projector”* | **Confirm — built 2026-09-23.** `GET /projector/delta?since=&epoch=`, polled once a second by the graph pane: re-placed chunks move to their new fit position, gone chunks are removed with their links, new chunks on an open page are placed, a page whose chunks changed moves. Live: the pane applied seq 602→778 (158 moves, 2 page updates) with no reload |
| G-74 | **Refit at 2× chunk growth, in the background; the fit survives a restart** | *Addendum V: “incrementally re-fits for every 2x growth in the number of total chunks”* | **Confirm — built 2026-09-23.** The worker checks growth every 5 s and refits on a separate thread while the old fit keeps answering; the swap is one assignment. The fit is kept in `projector.pkl` beside the store and reconciled on start: only chunks whose vector changed, or that the fit never saw, are re-streamed. Tested at 1.99× (no refit) and 2× (refit) |
| G-75 | **Every check runs THROUGH the running plugin (hardware in the loop)** and is driven and read by MCP tools; a terminal script is only a client of it | *Addendum VI: “a full Obsidian MCP layer that runs all tests through the *actual* plugin itself while live in the Obsidian GUI”* | **Confirm — built 2026-09-26.** `checks/live.mjs` holds all 36 checks once; `src/verify.ts` runs them in the plugin's own window (`__domvec.verify`), results stream into the corner box; `confirm.mjs` and the MCP `confirm`/`verify_state` tools are clients that reload the plugin from outside and start the in-app run. Seen: in-app runs 4/4, 3/3, 6/6 |
| G-76 | **Scan statistics have no pane of their own**: the pipeline readout is the collapsible, scrollable box in the Electron browser's bottom-right corner, which MCP tools can see, expand and collapse | *Addendum VI: “remove the segregated statistics panels”; “collapsed to a small black box on the bottom right corner”* | **Confirm — built 2026-09-26.** Live: separate panes chunk 0 / profile 0 / no status readout; the harness's `pipebox` gesture opens and closes the box (same state a click sets), corner 10/10 px, profile readout drawn inside it. Check `G-76` in `checks/live.mjs` |
| G-77 | **No separate chunk pane**: a chunk's rendered shadow-DOM form is a billboard in the 3D graph | *Addendum VI: “show as a billboarded 2D panel within the 3D gui rather than a third panel”* | **Confirm — built 2026-09-26.** Billboard mounts `ChunkSurface` forced interactive: an open shadow root (4 elements on a text chunk, 72 with 2 images on a picture chunk); chunk panes 0. Check `G-77` |
| G-78 | **Right-click pins a chunk**: its outline stays on the page at its on-screen box, its markdown goes to the browser cell's markdown side (native render, beside the page), and its billboard opens in the graph; all three persist and close together | *Addendum VI: “right clicks persist the chunk that is then overlay-highlighted and sends the markdown render to the markdown-side panel. When this happens, the shadow DOM billboard is also opened and persists”*; Addendum IV (switchable second view); 2026-09-22 (“clear highlight (non-blinding) over the current chunk's cartesian bounding box”) | **Confirm — built 2026-09-26.** Live on the Radix tree page: pin outline 0.49 px from the element's own box; markdown card rendered; billboard held by the browser with a shadow root; closing the billboard -> 0 pins, 0 billboards, 0 outlines. Planted 20 px offset: check fails, measuring 20 |
| G-79 | **Hover outlines the chunk over the page's own layout**, minimal and without banners, and rings its node in the graph -- aligned to what the browser renders | Addendum I (“an overlay that highlights the chunk structures overtop of the page's native cartesian displays”); Addendum IV (“minimal highlight … without banners”); Addendum VI | **Confirm — rebuilt 2026-09-26 (DESIGN_VII §1, §3).** The overlay resolves hovers from a map the renderer holds (`GET /page_map` on landing, `map_delta` in every capture reply), never the store, and outlines the 256 chunk's WHOLE extent -- the union of every element its lines draw. Live on Radix tree, with the landing capture in flight: hover p50 3.4 ms, p95 7 ms (100 samples; was 28 ms p50, 5,626 ms max via `/resolve`); 6/6 heading+paragraph pairs one chunk and ONE box; outline 0.01 px from the extent oracle (the sidecar's own map); node ringed. Planted (matched element only + a 1 s wait): fails, extent off 675 px, p95 1,411 ms. Check `G-79` |
| G-80 | **Hover-first**: the hovered element is chunked first and its embedding and projection jump the queue, so it reaches the graph fastest; the profile traces it as its own kind | 2026-09-22 (“whichever element that is hovered is recursively chunked first … projected through our 3D graph as fast as possible”) | **Partly — built 2026-09-26.** `/focus` moves the hovered chunk to the front of the encoder and projector queues (seen: 1 call per new hover); unresolved hover drains at once; `hover` traces recorded. Time-to-screen of a hover trace not yet read back as an outcome |
| G-81 | **A chunk node shows one of its pictures and expands to the whole chunk** as a billboard | *Addendum VI: “chunk nodes represented by only one of their image billboards which expands to viewing the total chunk”* | **Confirm — built 2026-09-26.** A chunk node with a picture is drawn as a sprite and opens to the whole chunk's shadow-DOM form (72 elements, 2 images). Check `G-81` |
| G-82 | **The side panel is the only second view**: no markdown face, no face toggle; a pinned chunk's markdown is a side panel beside the page, pins stack, and closing any one of the three forms closes all three | *Addendum VII follow-up: “side-by-side markdown sub-panel”, the browser stays the main surface* | **Open.** `DESIGN_VII.md` §5, work order step 2 |
| G-83 | **UMAP places PAGES only**, from each page's centroid (triple — pagerank-weighted semantic + frequency — or quantized semantic alone, chosen by the measured `centroid_ms`) | *Addendum VII: “UMAP only on page centroids”* | **Partly.** `PageProjector` built and tested (`test_page_tree.py`), gated off by `DOMVEC_PROJECTOR=page`; not the default **Order, 2026-09-26:** *“first on global chunk averaging on per-page and then fitting, but a transform over the full chunk set is cheap as well”* -- fit on page centroids FIRST, then place every chunk by transform through that fit |
| G-84 | **Left-click opens a page's WHOLE patricia tree, right-click closes it**: the content-node subtree of its shadow DOM, single-child chains collapsed to one link, one parent per node | *Addendum VII: “expands its FULL patricia TREE”* | **Partly.** `/page_tree` and `page_tree()` built (`test_page_tree.py`); the pane still unfolds per step |
| G-85 | **Much longer links** inside an opened tree, their length derived from the page layer's spacing | *Addendum VII: “The max link lengths need to be much longer.”* | **Open.** `DESIGN_VII.md` §6 |
| G-86 | **A heading heads what follows it**: the 256 cut is lenient -- a run takes the next piece past 256 while the result stays nearer 256 than 512 (< 384), so no chunk is a heading alone | *Decisions 2026-09-26: “If this is closer to 512 than 256 … keep the previous, otherwise include the merge”* | **Open.** `DESIGN_VII.md` §4, work order step 4 |
| G-87 | **Every test run reads a fresh, empty store that the APP starts and fills** by browsing a fixed page list; the working store is never touched, and every verdict records which store it read | *2026-09-26: “tear down the current db so that all new tests run in a fresh and empty db”*; *“All tests run inside of the GUI”* | **Partly — built 2026-09-26, in the plugin.** The corner box's "fresh store" button (`Verifier.runFresh`): a child `supervise` sidecar on an empty workspace (port 8790), the plugin pointed at it in memory only, 12 pages browsed in the cell, the checks, then back on the working sidecar with the test tree stopped -- every step in the box. A first, terminal-driven version (a `freshrun` module, since removed) seeded 12/12 pages, 0 -> 927 chunks, in ~60 s and was removed for running outside the app. The record merges per requirement and names the store (`confirmations.py`, `test_confirmations.py`) **2026-09-27: the full suite, 41 of 41, on a fresh store the app filled itself (13 pages)**; runs are isolated per check (pins, menus, billboards, live capture, idle guest) |
| G-88 | **The app is audited by using it**: each finding traced verbatim -> user story -> row -> check -> what the app did, peripheral effects included | *Addendum VIII* | **Open.** `docs/AUDIT_VIII.md` |
| G-89 | **The pending DIFF is drawn force-directed; what the transform has placed collapses into the page-node view.** Every chunk a drain produces is drawn at once as a force-directed node hung from its page -- built in the renderer from the drain itself (the sensor's MutationObserver chunking: no sidecar, no embedding, no UMAP) -- and stays so until that drain's chunks have been through the projector's transform; then its force nodes collapse into the page node (the default view draws pages, `G-53`; a page's inside opens on demand, `G-84`). Before any fit that is every scan; after one it is only the diff still waiting in the vectorization and transform queues. The fit is over page centroids and refits asynchronously (`G-83`); transforms run on the diffs, O(delta). **Phase contracts** (checked in order, in the running plugin, off `ui().graph` and the fresh-store run's phase trace): **C1 empty** -- a fresh store before any scan: 0 nodes, `layout_mode: "empty"`. **C2 first scan** -- the page's first drain draws at once: `layout_mode: "force"`, a page root plus one node per sensor chunk, each chunk with exactly ONE parent (nearest enclosing chunk by address, else the page); no vector waited for. **C3 delta** -- each drain adds exactly the chunks it emitted and removes exactly the ones it named removed; every other node keeps its identity and position; per-drain renderer time p95 < 50 ms. **C4 pages** -- each new page is its own tree. **C5 no fit yet** -- while the projector has no fit, the force trees stay up and the caption says it is waiting for the fit. **C6 the fit lands** -- the pane draws the page-node view from the projector; force nodes whose chunks are still unplaced stay drawn, hung from their page's projected node. **C7 collapse** -- when a drain's chunks have all been placed by the transform, its force nodes go (collapsed into the page node): pending force nodes fall to 0 once the queues are empty. **C8 after the fit** -- a new drain on a page the fit already holds adds force nodes under that page's projected node, and they collapse once transformed; a refit does not drop pending force nodes. **Interactions:** hover outlines and rings (`G-79`); a pin opens its billboard and survives the redraws (`G-78`); every node is on screen (`G-5`). **Planted:** the drain not wired to the graph must fail C2 | *2026-09-26: “the first handful of scans are rendered with a full force-directed layout as a fallback”*; *“force-directed layouts as a first and primary representation”*; *“the layout priorities are only on the diff that is queued to the vectorization and projection itself”* | **Partly — built 2026-09-26.** C1-C5 seen live on a fresh store (11 pages as trees before the fit, per-drain p95 24.7 ms, one parent per node); C6-C8 being rebuilt for the diff reading. Check `G-89` |
| G-91 | **Streaming, landing and leaving.** Landing on a stored page draws its projected chunks at once (served from the projector's memory with the page's chunk map, one call), with NO pending diff and NO diff flash -- content the store held before the visit is already transformed; only content the store does not hold, or whose text changed, is drawn force-directed and flashed. Leaving a page (for any page, blank included) drops its pending diff at once and, once its settle is done, collapses its projected chunks into its page node -- unless the reader opened it in the graph or a pin holds a chunk. Late placement results for a page no longer browsed add no chunk nodes; force nodes take no collision room, so projected chunks stay near their transform positions | *2026-09-26: "collect the full list … the different diffs and 3D nodes and 2D browser highlights … UMAP transforms and when collapses to page centroid nodes happens"* | **Partly -- built 2026-09-27.** Timelines (AUDIT_VIII pass 2): a stored page's projected chunks at 0.3-0.5 s after landing (was 3.6-5.2 s behind 145-564 duplicate force nodes and a 20-34 box flash); left pages collapse (other pages' chunk nodes had grown to 280). Check `G-91` |
| G-92 | **The stream runs in this order, and a node collapses when it is SAVED.** Mutation -> chunk diff -> overlay (in the page) -> force-directed nodes in 3D (before the store) -> store -> the store confirms a chunk saved and THAT node collapses into its page's root, before any vector or projection -> vectorize -> project through the current fit. Supersedes the collapse trigger of `G-89`/`G-91` (collapse once the transform placed it) | *Addendum IX: “as soon as the db pings back that the one node in the diff from any set of the streams has been saved, that one node collapses (still force-directed only until umap projections return) to its root”* | **Open.** Today a pending node collapses when a capture REPORTS it placed (`coverForce`), i.e. after the transform |
| G-93 | **The streaming force layout is relaxed and translucent**: no upper bound on link length, gentle attraction rather than strong repulsion, and streaming nodes drawn translucent -- a temporary signal that scanning is happening now | *Addendum IX: “without an upper bound on link lengths and perhaps more lenient/relaxed attractive forces (rather than strong repulsion)”; “force-directed layouts initialize to simple translucent nodes”* | **Open.** Force nodes are opaque; `treeSpring` bounds link length |
| G-94 | **A root that is not yet projected is itself force-directed**; when a projection arrives it REPLACES the force position, and the only force left is collision spacing: node diameter x an INTEGER safety factor plus an invisible margin | *Addendum IX: “collision boundaries defined as the diameter multiplied by some safety factor … I would argue is integer-valued”* | **Open** |
| G-95 | **Clicking a root toggles its whole tree**: collapsed -> every chunk of that page expands as the complete patricia tree; expanded -> click again and they all collapse back. Amends `G-84` (right-click closed it; right-click now belongs to the browser menu and pins) | *Addendum IX: “When the roots are clicked, all nodes expand … When the roots that are uncollapsed are clicked again, all the chunks for that page collapse back.”* | **Open.** `/page_tree` exists (`G-84`); the pane unfolds per step |
| G-96 | **UMAP coordinates are persisted per chunk, force positions never; a re-fit over the whole page history re-projects every stored 512-chunk.** Colour comes from the fit | *Addendum IX: “UMAP coordinates for projected chunks are saved to DB, but not their force-directed updates. All coordinates in the DB for all 512-chunks are re-projected over the UMAP upon a new re-fit”* | **Partly.** The fit persists in `projector.pkl` (`G-74`) and positions are re-derived on an epoch; whether coordinates live in the store, and whether every stored chunk is re-projected, is unmeasured |
| G-97 | **Each new chunk is projected at once, as its sub-chunk centroid through the current fit**; the first fit runs when enough pages are scanned. Simpler than `G-83`'s page-centroid fit | *Addendum IX: “vectorize the chunk diffs … and immediately compute the subchunk centroid and project it over the currently fitted UMAP (or fit for the first time once reached an appropriate number of scanned pages”* | **Partly.** `G-67` transforms in batches of 256; the sub-chunk centroid is not what is transformed |
| G-98 | **Deduplication holds on the store side, vectors included**: a chunk already stored is neither written nor embedded twice, with tests, then new edge-case tests once those pass | *Addendum IX: “ensuring deduplication on DB-side as well, including vectorization steps, perhaps some tests for this, and new tests once the old ones pass”* | **Partly.** `G-24` dedups bytes before a vector; not re-proven against the new order |
| G-99 | **Every kind of content on a page is detected**: text, JSON (script data, inline state), images, video, audio, other media -- found by planned searches over what the chunker has dropped, not by sampling | *Addendum IX: “all content that could possibly be detected, whether it be text; json; images; videos; media”* | **Open** |
| G-100 | **Media is cached in the workspace with its source**: every image reaches the 3D view, and no image is fetched twice | *Addendum IX: “confirm that all images are actually presented in the 3D GUI, and that re-fetches aren't required by locally saving the media in a workspace cache”* | **Open** |
| G-101 | **The hard-page corpus**: archive.org, YouTube, Instagram, Amazon, Facebook, Netflix, IMDb, DuckDuckGo, Richard Mille (rotating JSON-fed panels), Bandcamp (a live feed of releases) -- each browsed in the cell and scored live | *Addendum IX: “Please test on more difficult and larger-scale pages like …”* | **Open** |
| G-102 | **A billboard looks like the chunk it opens, and does not fake live controls**: HTML rendering improved; a control that cannot act on its xpath says so rather than looking pressable (`G-68` is the live version) | *Addendum IX: “aren't necessarily 'interactive on their xpaths' and so the buttons are just stale … some amount of html-based rendering improvements”* | **Open** |
| G-103 | **One loop, judged by the eye**: every 30 minutes, every requirement in scope ("Done" included); sparing screenshots at the steps that matter, read as a person would read them, compared with the MCP's numbers; what the picture shows and the numbers miss fixes the MEASUREMENT first, then the app | *Addendum IX: “The human's visual evaluation should be what informs our app's design for both features and MCP-based interaction testing.”* | **Partly — the loop runs from 2026-09-27.** Alignment rule (same day, *“all tests are run directly through the app in ways that are observable to the tools and yourself”*): only an in-app check started by the app's own control and read from what it renders counts; a probe finding becomes a live check plus an MCP field first |
| G-104 | **Each installed Python package is a tree-shaped projection** of its chunked comments and docs, with dependencies from variable to module to directory, localized to chunks; our own codebase included | *Addendum IX: “render each python package as a tree-structured UMAP projection on the chunked comments/code docs, and show the full dependencies on variables to modules to directories”* | **Open.** Packages are in the trie (`T-6`, `G-9`, `G-51`); no tree view |
| G-105 | **Package chunks go into Jupyter cells as code prototypes**, in the notebook with its kernels, terminals and browser cells as the older design documents specify (`NOTEBOOK_PANEL_DESIGN.md`, `P-N`, `P-B`) | *Addendum IX: “bringing these chunks into code prototypes in jupyter python cells on a notebook”* | **Open.** Design recollection first |

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
| P-N5 | Notebooks are **dynamically recursively chunked** like webpages | **Partial** — a note and its stored cell outputs chunk through the same recursive descent a page does (`domvec notes`); outputs are addressed `…/output[n]` and retrievable. Not yet *dynamic*: re-indexing is a command, not a diff on save (`P-N6`) |
| P-N6 | …and **continuously diff-updated to the db**, re-vectorized and re-assigned to chunks | Open |
| P-N7 | **One interface** centralizing retrieval and code research | Open |
| P-N8 | **Chunk scanning is exposed in the panel** — the reader can see the chunk boundaries the sensor drew | **Done** — a CM6 gutter marks every chunk's extent with its token count and flags any over the window, computed live by `POST /chunk_preview` through the same pipeline indexing uses. Editor only; reading view has no gutter |
| P-N9 | **Selection highlighting over the rendered markdown**, in the alternative panel | Open |
| P-N10 | That selection **annotates the context fed to the SLM** — the reader marks what the model is given, rather than the model taking the whole panel | Open |

**P-M — the native markdown panel, built outward**

| id | requirement | status |
|---|---|---|
| P-M1 | The **original Obsidian markdown panel survives in native form**, distinct from the notebook panel | Open |
| P-M2 | The same retrieval is added to the native default | Open |
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
| P-B7 | **Hover** overlays the chunk structure on the page's own cartesian layout, showing the chunks embedded in it | Open |
| P-B8 | **Right click locally indexes a chunk to its dual-view markdown panel inside the cell** — this is what feeds the SLM | **Done — seen live 2026-09-19**, and it is `G-39` by another name: the webview's own `context-menu` event, `elementFromPoint` at the cursor, `GET /resolve` walking UP to the nearest chunk the trie holds, and Obsidian's own `MarkdownRenderer` in the panel's other face. Measured: 2 ancestors up to an `article`, 199 chars over 10 rendered elements |
| P-B9 | Right-click indexing covers the **static type set only**; interactive components are deferred to tool calls in much later iterations | By design |
| P-B10 | **Dual per-chunk browser + markdown panels are reachable from the projector too** | **Done — seen live 2026-09-19**. Both halves: `G-40` takes the browser to the clicked chunk (parked at scrollY 4945, click moved it to 363) and `G-57` opens the markdown as a billboard beside the node (19 lines, anchored to 0px, follows the camera, pins on a drag) |
| P-B11 | **Straddle the shipped core `webviewer` and take ownership of Electron** as the work proceeds — use it, and outgrow it | **Done** — the cell is a `<webview>` chosen over `BrowserView`/`WebContentsView` because it flows with the DOM and therefore resizes with the panel, and the scanning that used to need Selenium now runs in it (`G-47`) |

### R. Retrieval — the `[]()` gesture

| id | requirement | status |
|---|---|---|
| R-1 | Typing the four symbols makes the bracket contents a **semantic retrieval query** | Open |
| R-2 | Results in **scrollable whitespace immediately below the line** | Open |
| R-3 | The remaining editable lines stay **uninterrupted** — the panel is one cohesive unit. `EditorSuggest` overlays; a CM6 **block widget** reflows | Open |
| R-4 | Clicking a result **infills the link between the parentheses** | Open |
| R-5 | **All retrieval comes through this one interface** — web, vault, packages alike | Open |
| R-6 | Package retrieval applies a **vector-centroid pre-filter**, then partition-wise retrieval; the filter must not become a second interface | Open |
| R-7 | The docs are updated to match this gesture wherever they disagree | Open |

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
| R-K1 | No intermediated hierarchical fields: a level of indentation holds more than one child, or it does not exist | **Open** — 39.0% of chunks carry one |
| R-K2a | No contentless lines: a unit with neither words nor a target is not drawn | **Open** — 703 repeats, 2.79% of chunks |
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
check whether `domvec.analytics` already answers the question.** A fresh metric
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
| isolated persistent session `persist:domvec-probe` | obtained — this is *"profiles from their base"* |
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
and works (`domvec/vault.py`, `T-5`): a note becomes trie addresses with
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
