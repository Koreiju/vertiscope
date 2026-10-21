# Deduplication and identity: lineage, inventory, conflicts (2026-10-04)

Read-only research over `git log -p`, `git log --all` (366 commits, 2 branches: `feat/plugin-goal-projector`, `master`) and the working tree. Nothing was run: no app, no sidecar, no tests. Every behavioural claim below is a **reading of code**, with file:line and commit sha. Anything I could not establish from source is marked **UNVERIFIED**. Line numbers are working-tree numbers as of 2026-10-04 (HEAD `2fcc022` plus uncommitted edits to `docs/PLUGIN_GOAL.md`, `harness.ts`, `main.ts`, `verify.ts`, `styles.css`).

The user's own statement of the problem is Addendum X in the working tree, `docs/PLUGIN_GOAL.md` (uncommitted, ~line 2072): "way too many force-directed nodes that are persisted in the 3D layout when new scans come in", and the proposal to "centralize deduplication etc on diffs ... in a centralized place on the backend", "a singular diff update on the scan side compatible with the same set of 3D and 2D representations". It also asks that earlier iterations be checked against current ones; Section 1 does that.

---

## 0. Headline findings (details and evidence below)

1. **There is no single identity.** A "chunk" has at least five ids at once: sensor chunk id (`slot.id`, an int, node-keyed), force-tree id (`f:<url>#<sid>`), render cid (`sha1(url|xpath|part)[:16]`, position-keyed), merge-group lead (`group_of`), and duplicate canonical (`dup_of`). Under them sit two leaf identities: `ContentAddress.key()` and trie `uid`. Only the force-tree id and the cid are used by the 3D view, and the only bridge between them is an xpath prefix lookup (`ChunkMap.lookup`), re-run on every capture.
2. **Per-drain writes never retire anything.** The sidecar capture route writes every drain with `complete=False` and does not pass `removed=` (`sidecar.py:1269`). `GraphStore.ingest` has no `removed` parameter at all (`graphstore.py:405-416`); only `complete=True` deletes chunks (`graphstore.py:808-815`). Nobody tells the 3D graph which cids were retired by a drain. The commit that introduced live capture says so in plain words: "per-drain writes are deltas and never retire a chunk that re-partitioning replaced" (`53c9697`, 2026-09-13). The fix for that was a settle on page-leave, not a retirement channel.
3. **The cid is positional**, so any insertion above a chunk renames it. Old cid stays in store, projector and 3D until a settle. The vector queue even has a cache for exactly this churn ("an insertion shifts every address below it, so chunks can arrive with new ids carrying text embedded an hour ago", `61a9828`), which means the new cid is placed at the same coordinates as the stale one.
4. **`dup_of`/`dup_n` are computed over the batch, not the page**, on delta writes (`graphstore.py:590`, written at `:611`), so a duplicate verdict is whole-page only after a settle; each delta can overwrite it.
5. **The force tree and the store tree are two decodings of the same payload with two chunkers.** The Electron cell boots the sensor with `budget: 0` (`browser.ts:1418`), i.e. the default 1200 chars (`sensor.js:28`); the Selenium path passes `sensor_budget(context_window)` = 768 chars at window 256 (`workspace.py:862`, `tokens.py:272`). The renderer then re-partitions at 256 tokens. Force chunk to stored chunk is many-to-many and `coversFor` returns one cid per force id.

---

## 1. Lineage: how dedup was done, iteration by iteration

Dates are commit dates. `e4d735c` (2026-08-23, "baseline: vertiscope as of stage 0") is a **snapshot of a pre-existing tree**, not the origin; `reference/dom_deep_serializer.py` says it was "Copied byte-identical from web_fiber_haptics/backend/dom_deep_serializer.py" (file header, lines 1-32). Earlier history is **UNVERIFIED** (not in this repo).

| Era | Date | What identity meant | Evidence |
|---|---|---|---|
| A. Snapshot, whole-DOM Merkle prune | pre-2026-08-23 (imported `e4d735c`) | A subtree is "seen" if its SHA-1 signature is in a **scan-wide set**, anywhere on the page | `reference/dom_deep_serializer.py:137-167` (`_compute_merkle_hashes`), `:170-230` (`_process_node`), `:135` (`seen_signatures`) |
| B. Additive merge-tree | pre-2026-08-23 (imported `e4d735c`, edited `bb251c0`) | Explicitly **rejects** A: "No subtree pruning ... Instead of pruning seen subtrees (which causes truncation), we accumulate ALL content into a master tree" | `core/scanner.py:12-14`, `:386-392` |
| C. Hash-diff transport | imported `e4d735c` | `prevHashes: {xpath -> content_hash}`; only changed nodes cross the wire | `core/scanner.py:160-166`, `:446`; `capture.py:75-116` (`deep_serialize(known=...)`, `data-vertiscope-same` placeholders) |
| D. One spine: trie on the live path | 2026-08-23 `81f169b`, `46e4330` | Identity = **address** (`ContentAddress`), repaired by content ("re-anchor by content instead of by position"); leaf `uid` "identity that outlives an address" | `trie.py:494-738`, `trie.py:246` |
| E. Moves, not re-sends | 2026-08-26/27 `b984095`, `07b6ed6` | "A digest says what a subtree holds, not where it is": gate on digest **and path**; unchanged digest + new path sends `[chunkId, newPath]` | `sensor.js:1327-1350`, `:1461` |
| F. Move carries identity; vacate source | 2026-08-29 `cc1b5c0` -> reverted `6451968` -> verified `11cf723` | Vacating a moved-from address deleted live content (Arabic Wikipedia: 85 identities lost, 47 of 60 "stale" addresses still in DOM); re-introduced only with an oracle (`alive`) | commit messages; `sensing.py:481-496` |
| G. Authoritative per-chunk address sets | 2026-08-29 `ca9fc22` | A re-emitted chunk's address set is authoritative; an address it dropped is gone | `sensing.py:399-429` |
| H. Strict Merkle for projections | 2026-08-29 `f3b7ffd` | Two equivalences: `subtree_hash` ("same content?") vs `exact_hash` ("draws the same?") | `trie.py:249-272`, `:870-894` |
| I. Content-defined chunk boundaries | 2026-08-29 `0d81d7c`, `61a9828` | Boundary from a hash of rendered text so an insertion cannot shift later boundaries; embedder gets a digest->vector cache because cid is address-keyed | `markdown.py` (boundary oracle), `vectors.py:608-690`, `:748-790` |
| J. Page-scoped exact dup marking in DB | 2026-09-13 `ae71c83` (G-24/G-25) | 125 `<tile-dispatcher>` shadow roots drew one string; marked `dup_of`, not merged, page-scoped | `graphstore.py:243-290`, `:96-125` |
| K. Stage-two semantic merge | 2026-09-13 `89255b6`, `443f860`, `2c73576` (G-26..G-33, G-65) | DBSCAN groups per page, `group_of`/`group_n`, assembled on read, never stored twice | `aggregate.py:115`, `workspace.py:1071-1111`, `graphstore.py:1169-1203` |
| L. Write only what moved | 2026-09-14 `55ae7b2` | Store diffs anchors by `(cid, aid, ord)` and addresses by `(content_hash, akey)` | `graphstore.py:442-540` |
| M. Plugin-side force tree | 2026-09-26 `fae7374` (G-89/G-90) | **Third** decoding of the drain, in the renderer, with its own id and its own parent logic | `forcetree.ts`, `graph.ts:712-830` |
| N. Chunk map + coverage | 2026-09-26 `fd09302`; 2026-09-27 `727a38a` | xpath -> cid map in the renderer; force node "covered" when a stored chunk anchors at/under/above-inline its address | `chunkmap.ts`, `browser.ts:669-705` |
| O. Collapse pages left | 2026-09-27 `727a38a` | On leaving a page, all its chunk nodes fold back into the page node | `graph.ts:1359-1388` |
| P. Merged ingest | 2026-09-28 `dee97ca` | Several drains ride in one capture; chunk at latest emission | `browser.ts:190-209`, `:1660-1680` |

**Contradictions between eras that are still in the tree.**

- **A vs B.** Merkle-prune-seen-anywhere (A) drops a repeated identical subtree at a *different* address; additive merge (B) keeps everything. Today's design follows neither: the trie is address-keyed (D) and content-blind dedup only happens in the DB (J) and projector. The user's own record on this is Addendum II, "No dedups is settled, and it means deduplicate" (`docs/PLUGIN_GOAL.md:292`). The D-6 defect ("duplicate chunks ... reassignment and diff-based index pop updates don't land straightforwardly", `PLUGIN_GOAL.md:374`) was **withdrawn** in `270edd4` ("the discriminator could not discriminate"), and D-7 in `768e1ac` ("measured against a store older than its fix"). Those withdrawals concern the *settled-store* measurement; none measured an in-session live graph. The user's current report (Addendum X) is about the live graph.
- **A's `known_hashes` is dead even in the reference.** `known_hashes` is loaded from the DB (`dom_deep_serializer.py:302`) and passed through `_process_node` (`:170`, `:191`, `:202`) but never read in the body. Only `seen_signatures` prunes. The idea was relocated into the sensor as `CFG.known` / `USE_CROSSPAGE` (`sensor.js:123-129`, `:1369`), which is off by default (`V.crosspage`).
- **Sensor-side subsumption dedup stays off.** `USE_DEDUP`/`USE_SIMHASH` (`sensor.js:76`, `:117-121`): "Turning it on collapses 22 more redundant pairs ... adds 6 over-dedup and loses 25 addresses ... It stays off" (`80a55dd`).

---

## 2. Inventory of every dedup / identity mechanism

Legend: **Live** = executes on the Electron cell -> sidecar -> 3D path today. **Off** = coded, default-off. **Dead** = no caller or value unused. **Offline** = analytics/baseline only.

### 2.1 Page sensor (`vertiscope/core/js/sensor.js`)

| # | Mechanism | file:line | Dedups on | Goal (commit) | Live? | Conflicts |
|---|---|---|---|---|---|---|
| S1 | Chunk slot id (`slot.id = chunkSeq++`) in a `WeakMap<Node, slot>` | `sensor.js:306`, `:1646-1651`, `:1430-1437` | **DOM node identity** -> int, session-scoped | Name departures: "Name what left. Without this the delta could only ever add" (comment at `:2396`) | Live | Stable across insertions (node-keyed) but reused if the same node becomes a chunk root again after being reported removed (`:2442` pushes `slot.id` but `chunkOf` keeps the slot, `:1647`). Not the store's cid. Resets on page reload (`sensor_restarted`, `d1bc381`). |
| S2 | Emission gate: skip if `prev.digest === rec.digest && prev.path === here` | `sensor.js:1327-1333` | digest + composed path | "emit only moved digests" (II §10); path added by `b984095` | Live | Digest is positional; a move re-emits or sends a move record. |
| S3 | Move record `[id, newPath]` instead of body | `sensor.js:1340-1350`, `:1459-1462` | digest equal, path differs | "send where it went, not what it is" (`07b6ed6`) | Live | Receiver must rebuild units from its own trie (`stream.py:258-290`). |
| S4 | Removal sweep: `removedIds.push(slot.id)` for chunk roots no longer connected / no longer rooted | `sensor.js:2400-2443` | slot liveness | "a chunk whose node was deleted stayed in the store with an address that no longer resolved" | Live | Names sensor ids only; the trie keys on addresses, so `sensing.py` translates ids to addresses via `_chunk_addrs` (`sensing.py:429`). The plugin's ForceTree consumes the same ids directly. |
| S5 | `USE_DEDUP` / `USE_SIMHASH` token-sketch subsumption | `sensor.js:76`, `:117-121`, `:1702-1763` | token-sketch containment | `II §7 sketch-then-verify` | **Off** (`80a55dd`) | Loses content; kept off. |
| S6 | `USE_CROSSPAGE` known-content skip | `sensor.js:123-129`, `:1369` | `rec.content` (commutative fingerprint) | "the original serializer's `known_hashes` prune moved to where it pays" | **Off** (`variants: {}` in `browser.ts:1418`) | Content-keyed across pages; would contradict address identity if enabled. |
| S7 | `rec.content` vs `rec.digest` | `sensor.js:1685-1690` | digest = positional/identifies the node; content = commutative fingerprint | comment in `makeChunk` | Live (both sent) | Two hash notions per chunk on the wire. |

### 2.2 Host decode (`vertiscope/sensing.py`)

| # | Mechanism | file:line | Key | Goal | Live? | Conflicts |
|---|---|---|---|---|---|---|
| H1 | `_chunk_addrs`: sensor-chunk-id -> addresses | `sensing.py:247`, `:395-463` | sensor chunk id -> set of `ContentAddress` | "the sensor names removals by its own grouping and the trie is keyed by address" (`81f169b`) | Live | The only place a sensor id is mapped to trie addresses; the map is **private to `Sensor`**, never exported to the plugin. |
| H2 | Re-emitted chunk's address set is authoritative | `sensing.py:399-426` | address-set difference | `ca9fc22` | Live | |
| H3 | Orphaned move source vacated | `sensing.py:481-496` | claimed vs moved-from addresses | `8804cd2`, `11cf723` | Live | Reverted once (`6451968`) for deleting live content. |
| H4 | Stale-dictionary guard `sensor_restarted` | `sidecar.py:77-95`, `:1184` | `stats.dictSize` arithmetic | "never decode with a stale dictionary" (`d1bc381`) | Live | The restart discards the old session's trie **without settling it**; stored rows of the old session persist until the next settle. |

### 2.3 Sidecar trie (`vertiscope/trie.py`, `vertiscope/stream.py`)

| # | Mechanism | file:line | Key | Goal (commit) | Live? | Conflicts |
|---|---|---|---|---|---|---|
| T1 | Trie path = `url : xpath : tag : accessor` is the leaf **address**; `ContentAddress.key()` and `aid` | `address.py:476-518` | injective string key; `aid = sha1(key)[:16]` | "The key is the identity everything downstream is keyed on -- chunk anchors, the store's rows, every dict the render builds" (docstring) | Live | The one key every Python-side store uses. The plugin never sees it except as xpath strings. |
| T2 | `TrieNode.uid` + re-anchor by `content_hash` within touched spans; reported moves carry uid | `trie.py:246`, `:494-738` | `content_hash` (candidate only) + reported `moved` pairs | "identity that outlives an address" (`46e4330`) | Live | uid is leaf-level; no chunk-level analogue exists. Nothing outside the trie reads `uid` (grep: only `trie.py`, tests). |
| T3 | `content_hash` = SHA-1 of normalized token multiset | `trie.py:116-157` | token multiset (blind to order/case/punct.) | "Equal hashes are duplicate **candidates**, and that is all a hash can be" (`trie.py` module docstring ~l.78-90) | Live (used by `apply`, `diff`, store `Address.content_hash`) | Deliberately blind; must not decide "is there anything to write" (`trie.py:621-650`, `e222c80`). |
| T4 | `subtree_hash` Merkle (content-blind) | `trie.py:249`, `:870-883` | segment + content_hash + children | O(delta) `diff` (`e4d735c`) | Live in `diff()`; the live path uses `apply`, not `diff` | Used only by snapshot path `StreamingScan.push` (`stream.py:196`). |
| T5 | `exact_hash` Merkle (strict) | `trie.py:272`, `:884-894` | segment + address + exact value + children | "A projection prints values verbatim, so it must key on the second" (`f3b7ffd`) | Live (RenderMemo) | Per-process `hash()`, never persisted (`61a9828`). |
| T6 | `apply()` rule: "A removal this same drain contradicts is stale" | `trie.py:724-735` | `want` address keys | `d996151` | Live | `units` authoritative over `removed`. |
| T7 | `StreamingScan.absorb` / `push` | `stream.py:225-307` | | "one pipeline, not two" (`81f169b`) | Live (`absorb`); `push` snapshot-only | `absorb` observes the delta; `push` recovers it by `diff()`. **Two ways to build a delta.** |
| T8 | `dirty_chunks`: `touched = added+changed+removed+moved`, `dirty = chunks whose anchors intersect`, **`update.all_chunks = every chunk`** | `stream.py:310-398`, `:393` | address keys | "a caller holding live chunks needs it to retire the ones a removal emptied" (comment on `ScanUpdate.all_chunks`, `stream.py` ~l.88-93) | Live; **`all_chunks` is not consumed on the capture path** (only `/live_render`, `sidecar.py:1716`, and the REPL, `repl/app.py:318`) | This is the retirement oracle that exists and is unused where it matters. |
| T9 | `RenderMemo` | `stream.py:162-171`, `markdown.py` | `exact_hash` | `f3b7ffd` | Live | |

### 2.4 Markdown / projection dedup (`vertiscope/markdown.py`, `obsidian/htmlform.py`)

| # | Mechanism | file:line | Key | Goal | Live? | Conflicts |
|---|---|---|---|---|---|---|
| M1 | `_dedupe`: token-multiset subsumption **scoped to one element (xpath)** | `markdown.py:870-930` | token multiset, same `addr.xpath` | "chunk scope starts deleting distinct nodes that happen to share a string" -> element scope | Live | Cannot see identical content at different xpaths (stated in `ae71c83`) -> the reason J exists. |
| M2 | "One element does not say the same thing twice" | `9ceaae7` (2026-09-05) | `consumed`/text_at owner | 208 duplicate lines -> 0 | Live | |
| M3 | Containment-chain collapse | `83c6122` | n/a | "sameness of rendered text is not sufficient grounds to hide a unit" | **Reverted** | Records the negative result. |
| M4 | `cid` = `sha1(url\|xpath\|part)[:16]` | `markdown.py:259-268` | **position** | "Keyed on position rather than on content ... a content-keyed id degenerates wherever content is absent" (ERRATA B10; `61a9828`: a content key collapsed 18.8% of instances against the address's 0%) | Live | **Renames on any shift above the chunk.** |
| M5 | Content-defined boundary (hash of rendered text) | `0d81d7c` | piece text hash | An insertion must not move later boundaries | Live | Chunk *boundaries* stay stable, chunk *ids* do not (M4). |

### 2.5 Store (`vertiscope/graphstore.py`, `vertiscope/workspace.py`)

| # | Mechanism | file:line | Key | Goal (commit) | Live? | Conflicts |
|---|---|---|---|---|---|---|
| D1 | `_same_content(chunks)`: exact-markdown dup marking -> `dup_of`, `dup_n` | `graphstore.py:243-290`, call `:590`, write `:611` | **`chunk.markdown` bytes**, scope = `chunks` argument | "Resolved in the database, over the aggregate chunks, on exact bytes, scoped to one page" (`ae71c83`) | Live | **Scope is the batch**, not the page, on `complete=False` (see 3.2). `c.dup_of` is overwritten on every MERGE. |
| D2 | `_reconcile`: delete anchors only for `stale_anchors`; `DETACH DELETE` chunks not in this batch **only if `complete`**; same for addresses | `graphstore.py:738-833`, `:808-815` | cid set difference | "a re-scan of a page that lost content removes what is gone" (`ingest` docstring) | Live | `complete=False` -> "absence from a delta carries no information" (`:766-771`). |
| D3 | MERGE-on-primary-key idempotence; write-diff (`stale_anchors`, `fresh_anchors`, `unchanged_addresses` on `(content_hash, akey)`) | `graphstore.py:442-540` | cid / aid / (cid, aid, ord) | `55ae7b2` | Live | `SET` list omits `embedding` and `group_of` (`:608-614`): a rewritten chunk keeps its **old vector** and its **old group** until later stages overwrite. |
| D4 | `set_groups` clears every chunk on the page then writes groups | `graphstore.py:1169-1203` | cid -> lead cid | "A group that no longer holds after a re-scan must stop being claimed" | Live (called from `Workspace.aggregate`) | Only runs when the page passes the 24-chunk gate (`aggregate.py:115`, `workspace.py:1107`); when `skipped`, **old groups are not cleared** (UNVERIFIED in practice). |
| D5 | Workspace retirement: `superseded` -> `freq.remove`, `vectors.forget`, mirror pop | `workspace.py:453-470`, `:524-535` | cid set; `complete` = store-derived set, `complete=False` = caller's `removed` | "A delta names what it removed; it never implies removal by omission" (`ingest_chunks` docstring) | Live | The capture route never supplies `removed` (`sidecar.py:1269`), so retired cids keep their frequency row, vector-queue digest, mirror row. The REPL path **does** supply it (`repl/app.py:309-334`), but `GraphStore.ingest` ignores it, so even there the **graph** keeps the chunk. |
| D6 | Settle: `ingest(url, spine.trie)` (complete=True) then `_project_page` then `sessions.pop(url)` | `sidecar.py:1203-1215` | whole trie | "per-drain writes are deltas and never retire a chunk that re-partitioning replaced" (`53c9697`) | Live, **only** on page leave, pane close, scan end | The sole retirement point. |
| D7 | `purge_page`, `forget` | `graphstore.py:1862-1873`; `sidecar.py:905-913` | url | Manual | Live | |
| D8 | `VectorQueue` digest gate + `digest -> vector` cache | `vectors.py:608-690`, `:748-790` | **markdown SHA-1**, keyed by cid | `61a9828` | Live | Content-keyed (digest) layer under a position-keyed id (cid): by design (two keys). |
| D9 | `aggregate_page` (DBSCAN) -> groups, `_vectorise_groups`, debounced 1.5 s after each drain | `workspace.py:1071-1211`, `sidecar.py:1288`, `:381`, `:278` | embeddings per page | `2c73576` | Live | Stale `group_of` between drains: a rewritten member keeps its old lead; a retired lead leaves members pointing at a non-existent lead; the projector treats `group_of != cid` as "gone" (`projector.py:332`). **UNVERIFIED** live. |

### 2.6 Projector and sidecar read paths

| # | Mechanism | file:line | Key | Goal | Live? | Conflicts |
|---|---|---|---|---|---|---|
| P1 | Projector drops `chunk is None or chunk.redundant or group_of != cid` before the fit; logs `gone` | `projector.py:330-363` | `dup_of`, `group_of` | "drops copies BEFORE the fit rather than after" (`ae71c83`) | Live | Reads `chunks_for_placement` from the store, so a **retired-but-still-stored** chunk is *not* gone for the projector. |
| P2 | `enqueue_page` re-queues now-current cids plus `by_url[url]` "that the page no longer has -- they are gone, and nothing else will say so" | `projector.py:304-311`; `sidecar.py:233-243` | cid sets | `97ad3f2` | Live, **only from settle** (`sidecar.py:1211`) | Per-drain only `_project(dirty_cids)` (`:1302`), which carries rewritten cids and never retired ones. |
| P3 | `delta(since)` log (`chunk`, `gone`, `page`) -> plugin `pullDelta` | `projector.py:597-630`; `graph.ts:1470-1560` | cid | `97ad3f2` | Live | The only channel by which a stored cid node leaves the 3D graph while the page is open. |
| P4 | Dup/group filters repeated in `layout.py` (`:426`, `:1565`, `:2427`, `:2555`, `:2655`), `projector.py:333`, `:1261`, `:1273`, `sidecar.py:487-600`, `:1757-1772`, `:1830-1832` | | `dup_of`, `group_of` | | Live | Same predicate written in at least 10 places; none in the plugin. |
| P5 | `/resolve` first anchor wins: `MATCH (c)-[:Anchors]->(a) ... RETURN c.cid LIMIT 1` | `sidecar.py:1552-1560` | any anchored chunk | `G-39` | Live | If a retired and a current chunk both anchor an address, which wins is arbitrary. **UNVERIFIED** live; the preconditions are shown in 3.2. |
| P6 | `/page_map` serves store `Anchors` and projector positions | `sidecar.py:1750-1800` | store rows | `727a38a` | Live | Reads the store, so it includes retired-but-unsettled chunks. |

### 2.7 Plugin (renderer)

| # | Mechanism | file:line | Key | Goal (commit) | Live? | Conflicts |
|---|---|---|---|---|---|---|
| R1 | `ForceTree`: chunk id `f:<url>#<sid>`, address = **longest common element path of the chunk's lines**, parent = nearest enclosing held chunk | `forcetree.ts:67-68`, `:102-126`, `:129-200` | sensor id; address derived locally | "straight from the electron's recursive mutationobserver shadow DOM chunking basically prior to vectorization" (G-89, `fae7374`) | Live | Independent re-decoding of the payload; shares nothing with `sensing.py` except the wire format. Drops `again`-flag semantics on identical ids (`graph.ts:~744`, `if (byId.has(a.id)) continue;`). |
| R2 | ForceTree removal: `payload.removed` -> delete by sid; dictionary restart -> remove everything held | `forcetree.ts:129-148`, `:155-160` | sid | | Live | |
| R3 | `mergePayloads`: chunk at latest emission, "a chunk emitted and then removed dropped" (a **set**, order-blind) | `browser.ts:190-209` | `String(c.id)` | `dee97ca` ("merged ingest") | Live (up to 40 drains) | Order-blind removal: a sid that is removed in drain k and re-emitted in k+1 (possible given S1 slot reuse) is filtered out of `chunks` although alive. **UNVERIFIED** live. Only the capture is merged; ForceTree still sees each drain singly (`browser.ts:1536-1541`). |
| R4 | `coversFor`: force id -> stored cid via `ChunkMap.lookup([addr, ancestors-through-inline-tags])` | `browser.ts:675-705`; `chunkmap.ts:141-149` | **xpath string / prefix** | "A force node is the PENDING diff only while this finds nothing the projector has drawn" | Live | **The one and only bridge between the two id spaces.** One cid per force id. |
| R5 | `ChunkMap`: `byXpath`, `byPrefix`, `byCid`; "newer chunk takes addresses and prefixes from the one a re-partition replaced" | `chunkmap.ts:49-139` | cid <-> xpath | `fd09302`, `727a38a`, `d1bc381` | Live | The 2D overlay's **own** retirement rule ("newest wins"), because the sidecar never names the retired chunk (comment, `chunkmap.ts:~104-113`). `byCid` entries shrink only when addresses are taken; a retired cid with no overlapping address survives. |
| R6 | `unstoredIds` / `unstoredAt` | `browser.ts:640-655`, `:1766-1773` | force id / address | "content a capture processed and the store did not keep is dropped, not timed out" (`727a38a`) | Live | Id-keyed memory is never pruned (cleared only in `restartCapture`, `browser.ts:830`). |
| R7 | `forceSpecs` (id -> parent/url/cid/stale/born) + `collapsedTo` (force id -> cid) | `graph.ts:826-830`, `:1271-1274` | force id | `fae7374`, `727a38a` | Live | `collapsedTo` is the only surviving force-id -> cid map after a collapse, and **no code reads it to remove a stored node when its force id is later reported removed** (`forceDelta`, `graph.ts:712-727`, never consults it). |
| R8 | `absorb()`: add-by-cid (`byId.get(node.cid)`); existing cid gets `Object.assign` + glide; no removals except `replaced` force nodes | `graph.ts:3231-3345` | **cid** | "A chunk that was REWRITTEN moves" | Live | Add-only for stored chunk nodes. |
| R9 | `ForceNodeDelta.covers/settled` -> `coverForce` -> `foldIn` -> `redrawForce` | `graph.ts:978-1004`, `:1133-1200`, `:1267-1340` | force id -> cid | `fae7374` | Live | |
| R10 | `life` / `lifecycleState` `force_beside_stored` | `graph.ts:~1210-1215`; `checks/live.mjs` | | G-92/G-97/G-98 | Live (instrument) | Counts force-beside-stored only; **does not count stored-beside-retired-stored**. |

### 2.6 Offline / reference

| # | Mechanism | file:line | Notes |
|---|---|---|---|
| X1 | Reference Merkle prune (`seen_signatures`) | `reference/dom_deep_serializer.py:135-230` | Baseline for analytics only (`baseline.py:38-80`). CLAUDE.md constraint 3. |
| X2 | `ShadowDOMScanner` additive merge | `core/scanner.py` | Used by `capture.py:212,269` (snapshot path). |
| X3 | `DedupStatsCollector` | `core/dedup_logging.py` | Logging only. |
| X4 | Analytics: `--drift` (stale = "addresses the trie holds and the page does not"), `--resolvable`, `live_delta.py` | `vertiscope/analytics/` | Measure the **trie**, not the 3D view. |
| X5 | G-98 check "no two chunks share an element address on the forum ... no streaming node beside its stored node" | `docs/PLUGIN_PRD.md:294` | Measured on the **settled working store**, plus force-beside-stored; not stored-beside-retired mid-session. |

---

## 3. Where mechanisms agree and where they contradict

### 3.1 Agree
- Address (`ContentAddress.key()`/`aid`) is the identity of every leaf in trie, store, anchors, `Address` rows, markdown lines (T1; `address.py:476`). No one has proposed replacing it, and `3c1f822` measured why shape-keyed identity fails (79.2% of multi-element shapes cover different content).
- Content hash = candidate, not decision (T3). Exact bytes decide dup marking (D1); exact value decides writes (`trie.py:621`); `exact_hash` decides render reuse (T5).
- "Marked, not merged" for dups and groups (D1, D4): chunks keep their cids, anchors and addresses; consumers filter.

### 3.2 Contradict

**C1. Retirement is settle-only, in every layer that matters.** Capture route: `complete=False`, no `removed` (`sidecar.py:1269`). Store: `complete=False` skips deletion (`graphstore.py:772-775`, `:808`). Workspace: `superseded = set(removed or ())` is empty (`workspace.py:457`). Projector: only dirty cids are queued (`sidecar.py:1302`). Plugin: `absorb` is add-only (`graph.ts:3231+`); `pullDelta` removes only cids the projector logged `gone`, which only happens after `_project_page` at settle (`sidecar.py:1211`). Evidence of design intent: `53c9697`, `browser.ts:1190-1197`, `:1975`. The settle fires only on page leave (`browser.ts:1205-1255`), pane close (`:540-546`) or end of scan (`:1975`). On a page the reader stays on (infinite scroll, forum), stale chunks accumulate without bound for the whole visit.

**C2. Two chunk ids, one positional, one not.** Sensor id is node-keyed and survives shifts (S1); cid is position-keyed and does not (M4). A head insertion into an N-item list yields N sensor "moves" (S3) and N renamed cids; the force tree stays correct while the stored side gets N new cids next to N stale ones. `61a9828` documents the reuse of vectors for exactly this case, so the new cid lands where the old one is.

**C3. Dup verdict scope.** `ae71c83` promises page scope; code computes it over `chunks` (`graphstore.py:590`), which on every capture is `dirty` only. Effects: (i) a chunk that was a duplicate and is rewritten alone gets `dup_of = ""` (`:611`) and reappears as a full node; (ii) a copy that arrives in a later drain than its canonical is never marked until the settle; (iii) a canonical rewritten alone has `dup_n` reset to 1.

**C4. Group and vector columns survive rewrites.** `SET` at `graphstore.py:608-614` leaves `group_of`, `group_n`, `group_embedding` and `embedding` untouched, so a rewritten chunk keeps its old vector and group until `flush_vectors` / `aggregate` (debounced 1.5 s, gated at 24 chunks, `aggregate.py:115`) overwrite them. `graph.ts:3253` comment says a rewritten chunk "moves"; it moves only after the new vector lands.

**C5. Force tree vs stored tree are different partitions.** Sensor budget in the Electron cell is 1200 chars (`browser.ts:1418` -> `sensor.js:28`) whereas `sensor_budget(256)` is 768 (`tokens.py:272`; used by the Selenium path `workspace.py:862`). The renderer re-chunks at 256 tokens. `coversFor` returns exactly one cid per force id (`chunkmap.ts:141-149`), so a force chunk spanning two stored chunks collapses on whichever is found first and is never "covered" by the other.

**C6. Force-id -> cid knowledge is thrown away on collapse.** `redrawForce` deletes the spec after recording `collapsedTo[id] = cid` (`graph.ts:1267-1274`); `forceDelta` removal handles force ids only (`graph.ts:712-727`). A sensor-reported removal of a chunk that was already saved/folded removes nothing from the 3D graph.

**C7. Dup/group predicate is in the sidecar and projector, absent from the plugin's force path.** `dup_of`/`group_of` are applied at ~10 sites (P4) but ForceTree knows nothing of them; instead `captureOne` guesses "undrawable" by `dirty_cids` minus placed/waiting (`browser.ts:1744-1751`) and the force node waits for the 90 s timer otherwise (`graph.ts:1245-1251`).

**C8. Id-keyed memory vs address-keyed memory in the browser.** `unstoredIds` is keyed by force id and `unstoredAt` by address; the commit that added the second says why: "a sensor instance renumbers its chunks on every landing, so id-keyed memory forgot page furniture" (`browser.ts:642-646`, `727a38a`). The id-keyed one remains and is only cleared on `restartCapture` (`browser.ts:830`).

**C9. `/resolve`, ChunkMap and store disagree on what happens when two chunks anchor an address.** Store: any (`LIMIT 1`, `sidecar.py:1559`). ChunkMap: newest wins (`chunkmap.ts:112-128`). The store state that creates the conflict follows from C1: `stale_anchors` only clears anchors of chunks in the batch (`graphstore.py:466-474`), so a retired chunk's anchors persist beside the new chunk's. (`test_the_page_is_still_partitioned`, `tests/test_content_boundaries.py:169`, protects the settled case; **UNVERIFIED** whether it covers the unsettled one.)

**C10. Two ways to build the delta in Python.** `push()` recovers a delta by `diff()` on `subtree_hash`; `absorb()` observes it (T7). Only `absorb` is on the Electron path. `diff()` and `subtree_hash` have no live consumer in this path; they remain the snapshot path's mechanism.

**C11. Reload handling.** `sensor_restarted` starts a fresh session (`sidecar.py:1184-1190`) without settling the previous trie. `ForceTree.apply` handles the same event by removing all its held ids (`forcetree.ts:136-146`), so the force side clears and the store side keeps both generations until the next settle. The pre-reload settle is the only thing that removes the old rows.

---

## 4. Answers

### (a) Where a diff's chunk gets two (or more) identities, and what maps between them

| Identity | Defined at | Scope / lifetime | Keyed on |
|---|---|---|---|
| sensor chunk id `sid` | `sensor.js:1647-1651` | one page-load of one sensor | DOM node |
| force-tree id `f:<url>#<sid>` | `forcetree.ts:68` | one `ForceTree` per url in `browser.ts:634`, cleared on dict restart | `sid` |
| force-tree address | `forcetree.ts:102-116` | recomputed per drain | common prefix of the chunk's line paths |
| render cid | `markdown.py:259-268` | store lifetime, but changes when xpath or part changes | `url\|xpath\|part` |
| merge-group lead cid (`group_of`) | `graphstore.py:224-240` | until the next aggregation | DBSCAN over embeddings |
| duplicate canonical cid (`dup_of`) | `graphstore.py:217-235` | until the next MERGE of that chunk | exact markdown bytes in the batch |
| leaf address key / `aid` | `address.py:476-518` | forever, but the trie moves content between addresses | `url\|xpath\|tag\|accessor` |
| leaf `uid` | `trie.py:246` | across moves in the trie | trie-internal counter |

**Mappings that exist:**
1. `sid` -> addresses: `Sensor._chunk_addrs` (`sensing.py:247`). Private to the sidecar.
2. `sid` -> force address: `ForceTree.address()`. Private to the renderer.
3. force id -> cid: `coversFor` -> `ChunkMap.lookup` via xpath prefix (`browser.ts:675-705`). Recomputed on every capture for all held nodes (`browser.ts:1741`) and on landing (`:1236`). Persisted as `forceSpecs[id].cid` and, after collapse, `collapsedTo[id]` (`graph.ts:1271`).
4. cid -> addresses: store `Anchors {ord}` edges, and the capture reply's `map_delta` (`sidecar.py:1297`).
5. address -> uid: trie only. Nothing outside the trie uses `uid`.

**Mappings that do not exist (and would be needed for a single diff):**
- old cid -> new cid on a re-partition or shift. The sidecar has the facts (`delta.moved` address pairs from `trie.apply`, and the new render) but never computes it.
- sid -> cid at the sidecar. The sidecar knows sid -> addresses and addresses -> cid but returns neither the sid nor the retired cid set.
- retired cids per drain. `StreamingScan.dirty_chunks` already returns `update.all_chunks` (`stream.py:393`); the retired set is `previous all_chunks cids - current all_chunks cids`, the one-liner the REPL does (`repl/app.py:316-321`) and the sidecar does not.

### (b) Every place a streaming/force or stored chunk node leaves the 3D view, and when it does NOT

Force nodes (id `f:...`, `forceSpecs`):

| # | Removal | file:line | Condition | Does NOT remove when |
|---|---|---|---|---|
| F1 | `forceDelta` `d.removed` | `graph.ts:722-727` | sensor reported removal and `ForceTree` held it | the id was never held (e.g. ForceTree returned `null` for an unreadable transport, `forcetree.ts:133`, `:142`); the payload's removal arrived inside a merged capture only (ForceTree sees drains singly, so fine); the **stored cid node** for that chunk is untouched (C6) |
| F2 | `forceDelta` skip as already drawn | `graph.ts:752-756` | `a.settled` or covering cid already drawn non-force | a covering cid exists but is not drawn (merge-group member, duplicate) |
| F3 | `coverForce` -> `foldIn` -> `redrawForce` | `graph.ts:978-1004`, `:1133-1200` | `capture` reply gave `covers[id]` | `coversFor` found no chunk (`!hit`), the chunk is `stale` (content changed again), page root force nodes (`!spec.parent` return at `:1141`) |
| F4 | `collapseCovered` | `graph.ts:1235-1260` | `spec.cid && !spec.stale && drawn.has(spec.cid)`; or timeout `parent && ((!cid && age>20 s) || age>90 s)` | page-root force nodes never time out; `spec.stale` stays true until `absorb` places the cid (`graph.ts:3236-3242`) |
| F5 | `absorb` `replaced` | `graph.ts:3331-3345` | a placed cid equals `spec.cid` | spec had no cid yet |
| F6 | `redrawForce` root drop | `graph.ts:1279-1300` | projected page node exists and drawn, or all chunks collapsed and page expanded | page not projected yet (`layoutMode !== "projector"`), or force children still pending |
| F7 | `dropForce(url)` | `graph.ts:1390-1398` | reader leaving url | **returns early unless `layoutMode === "projector"`** (`:1392`): before first fit it never fires |
| F8 | `dropForceIds` (unstored) | `graph.ts:1402-1408` | capture processed id and `covers[id]` absent | same early return before first fit |
| F9 | `collapsePage(url)` | `graph.ts:1359-1388` | page left and settled; removes **all** non-page, non-pinned nodes of that url (force and stored) | `openedByReader.has(url)`; pinned billboards; **early return unless projector mode** (`:1366`); only fires after `settleQueued`, which waits for the next page's first capture or 4 s (`browser.ts:1254-1258`, `firstCapture`) |
| F10 | `load()` reload | `graph.ts:485-495` | after a fit, specs of non-browsing urls deleted | url equals `browsingUrl()` |
| F11 | `resetForStore` | `graph.ts:~1426-1437` | store switched | n/a |

Stored (cid) chunk nodes:

| # | Removal | file:line | Condition | Does NOT remove when |
|---|---|---|---|---|
| S-a | `pullDelta` `goneIds` | `graph.ts:1517-1523` | projector `delta()` contains the cid in `gone` | the cid was never enqueued after being retired (C1: only `_project_page` at settle enqueues retired cids, `sidecar.py:1211`, `projector.py:304`); the projector still finds the chunk in the store (retired-but-unsettled) |
| S-b | `pullDelta` `reload` | `graph.ts:1479-1490` | projector epoch/seq mismatch | n/a (re-places everything open) |
| S-c | `collapsePage` (above, F9) | `graph.ts:1359` | as above | as above |
| S-d | `resetForStore`, billboard close | | | |

**Leak paths (condition that leaves a node drawn):**
1. **Retired stored cid while the page stays open** (S-a, C1): any re-partition or shift in a drain leaves the old cid node drawn until the settle. Not removed by `forceDelta`, because the force tree never sees cids.
2. **Sensor-removed chunk already folded** (C6): the force node is already gone; `d.removed` finds nothing; the stored node stays.
3. **Pre-fit mode** (F7, F8, F9): `dropForce`, `dropForceIds` and `collapsePage` all `return` unless `layoutMode === "projector"`, so before the first fit the only removals are F1, F3-F5 and the timers; page-root force nodes (`!spec.parent`) have no timer (`graph.ts:1245`).
4. **Force node covered by an undrawable cid** (F2/F4): a merge-group member or `dup_of` chunk is never drawn, so `drawn.has(spec.cid)` is false and the node waits out the 90 s timer. The "undrawable" inference at `browser.ts:1744-1751` only helps when `dirty_cids` contains the cid.
5. **`stale` force node** whose cid is not re-placed (embedding lag; `graph.ts:3236-3242`): remains until the 90 s timeout.
6. **Page revisit / reload**: `ForceTree` clears and reports removals on dict restart (`forcetree.ts:136-146`), but the stored rows of the previous session persist until the next settle (C11).
7. **Same url, different session**: `forceTrees.get(url)` is reused when the same url is re-entered after leaving (`browser.ts:1537`); the tree is cleared only if the new sensor's dictionary size mismatches. A same-size dictionary would silently decode against stale ids. **UNVERIFIED** (reasoned from `forcetree.ts:134-146`).
8. **`collapsedTo` parent resolution** (`graph.ts:960-968`): children hang from the cid a collapsed parent became; if that cid is later retired, `parentFor` still names it until `byId.has(into)` fails; low impact. 20000-entry reset (`:1274`).
9. **`mergePayloads` drops a live chunk** if its sid was both removed and re-emitted inside the 40-drain window (R3). **UNVERIFIED**.

### (c) Recommendation: the one identity for a central diff object

Make the **cid** the view-level identity, and make the diff say explicitly what happens to every cid, computed once in the place that already has everything it needs: `StreamingScan.dirty_chunks`. Evidence: the cid is the key of every consumer that has to agree: store `Chunk` (`graphstore.py:96`), `Anchors`, the projector's `pos`/`by_url` (`projector.py:330-373`), `ChunkMap` (`chunkmap.ts`), billboards and pins (`browser.ts:1134-1160`), 3D node ids (`graph.ts:3368-3370`, `n.id = cid`), `VectorQueue` (`vectors.py:677`), the capture reply (`dirty_cids`, `map_delta`, `sidecar.py:1293-1302`). The sensor id and force id are session-scoped, transport-local, and exist in only one process; they should become aliases resolved by the diff (the existing `covers` map) rather than a second key space. Content hash cannot be the identity: `61a9828` measured that a content-keyed id "collapsed 18.8% of instances on the 54-page corpus against the address's 0%", and `3c1f822` measured shape-keyed identity at 79.2% wrong. Position (cid) is the only key that is injective on a page, which is the property CLAUDE.md constraint 1 requires of "the universal link structure". Its one defect is that it renames under shifts, so the central diff must carry **`retired` (previous `all_chunks` cids minus current) and `renamed` (old cid -> new cid, derived from `delta.moved` address pairs and trie `uid`, the only chunk-to-chunk continuity the trie holds)** next to `dirty`, `added` and `moved`. That is exactly what the REPL already computes for `retired` (`repl/app.py:316-321`), what `ScanUpdate.all_chunks` was created for ("a caller holding live chunks needs it to retire the ones a removal emptied"), and what `ingest_chunks(removed=...)` and the projector's `gone` log already know how to consume; the missing pieces are `GraphStore.ingest` honoring `removed`, the sidecar passing it, `_project` queuing retired cids, and the capture reply carrying `retired`/`renamed` so `ChunkMap`, the overlay and `absorb`/`forceDelta` all apply one list. Underneath, `ContentAddress.key()` stays the leaf identity and the trie `TrieDelta` stays the source of truth (every field of the central diff is "reads from the trie"). Dup/group verdicts should be computed by the same object over the **whole page's** `all_chunks`, not over the batch (C3), so the diff hands every view the same `drawable` set.

---

## 5. Caveats and UNVERIFIED list

- **No live run.** All of Sections 3 and 4 are static reading. The user's observation of persisted nodes is **consistent with C1/C2** but I did not observe it. The existing instrument `lifecycleState().force_beside_stored` (`graph.ts:~1210`) measures only force-beside-stored; a new metric (stored cid node whose cid is not in the latest `all_chunks`) would be needed, with a null arm (`CLAUDE.md`).
- **UNVERIFIED**: D4 stale groups when a page falls under the 24-chunk gate; C9 `/resolve` ambiguity under two anchoring chunks in the live store; leak 7 (`ForceTree` reuse with equal dictionary size); leak 9 (`mergePayloads` and sid reuse); whether `tests/test_content_boundaries.py:169` covers the unsettled case; whether the vector column, once stale at a rewritten cid, is visible to the user (depends on the embed worker timing).
- **Not examined**: `aggregate.py` internals beyond the gate; `layout.py` placement internals; the REPL's `live/` package beyond what is cited; `docs/DESIGN_*.md` for earlier dedup designs (only commit messages and code comments were used).
- **Instrument/corpus rule** (CLAUDE.md): none of the figures quoted from commits (e.g. 176 of 5,337 redundant, 215 groups over 601 chunks) were re-measured here; they are as reported in the commit bodies at those dates.
- `git log -S` earliest hits: `e4d735c` is a baseline import, so "introduced" for items present at that sha means "present at import", not "written then".
