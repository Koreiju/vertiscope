# UMAP Integration Facts — 2026-10-04

## 1. Chunk Embedding Vector Production

**Model:** Nomic embed-text via GPT4All (vertiscope/core/embedding_service.py:1-25)
**Vector width:** 768 dimensions (line 4)
**Text source:** `vertiscope/tokens.for_model()` (tokens.py:158-200) which strips link targets and URLs; **52.5% of tokens in corpus are link targets** (line 169)
**Entry point:** `vertiscope/core/chunk_instance_embedder.py` (referenced but not fully traced)

---

## 2. Chunk Vector Averaging

**_semantic_centroid (projector.py:768-771)** — unit-normalized mean of chunk vectors
- Unweighted: `block.mean(axis=0)` where block is array of vectors
- Weighted: `(w[:, None] * block).sum(axis=0)` with weight vector w
- Normalized: `_unit()` function divides by norm (lines 84-86)

**_page_rows (projector.py:783-817)** — computes page centroids
- Creates semantic centroid per page (line 793)
- UNCONFIRMED: triple centroid combines semantic + frequency SVD when fitted, unit-normalized then stacked and re-normalized by `np.sqrt(2.0)` (line 817)

**lead_vectors (graphstore.py:1288-1319)** — drawable rows fed to projector
- Each chunk returns: group_embedding (if group_n > 1 and exists), else individual embedding
- Duplicates and group members filtered out; only leads and originals returned

---

## 3. Online UMAP Training

**ParametricUMAP.update() (pumap.py:~line 120)** — trains on diff with landmarks
- Input: X_new (new vectors, already placed by transform)
- Stacks: X = vstack[old_raw, X_new]
- Trains with update_epochs (default 120, pumap.py:52) using old positions as landmarks
- Old positions held with landmark_weight=10.0 (line 52)
- Records drift stats (old_drift_p50, p90)

**RefitCost + choose_scope (refitscope.py:36-97)** — decides chunks vs pages scope
- Predicts update() cost as function of rows trained
- Chunks scope if: cost ≤ budget_ms AND rows ≤ WHOLE_FORWARD_ROWS (8192, line 33)
- Pages scope otherwise
- Cost model seeded from (160ms, 500ms, 1000ms, 2000ms) baseline curve (line 27)

---

## 4. Positions Streamed to UI

**ChunkProjector.delta (projector.py:597-629)** — returns changed positions since sequence number
- Response: `{"chunks": {cid: {"pos": [x,y,z], "hsv": [...], "url": ...}}, "pages": {url: {"pos": [x,y,z], "hsv": [...], "projected": count}}, "epoch": int, "seq": int}`
- Chunk positions from `self.pos[cid]` (line 621)
- Page positions from `self.page_pos.get(u)` (line 625)

**Sidecar route /projector/delta (sidecar.py:1673)** — HTTP GET endpoint
- Query params: `since` (sequence number), `epoch`
- Calls `proj.delta(since, epoch)` and sends JSON response

**Plugin polling (graph.ts:585)** — every 1 second via `pullDelta(load)`
- Reads projSeq, fetches delta since last seq
- UNCONFIRMED: whether chunk position updates are applied to LayoutNode.pos field in real time or deferred

---

## 5. 3D Position Assignment in obsidian-plugin/src/graph.ts

**LayoutNode.pos: number[]** (graph.ts:55) — the 3D coordinate array for each node

**Known position assignment points:**
- **forceDelta (line 712)** — applies force-directed tree; UNCONFIRMED whether stream positions override here
- **absorb (line 505)** — called after place() returns; UNCONFIRMED: no position assignment visible in grep
- **sanitize (line 1068-1100)** — replaces non-finite positions with fitX/Y/Z, or resets to origin
- **glide/folding (line 1124-1170)** — animated tween from old position to target; UNCONFIRMED: whether target is stream position or page root

**UNCONFIRMED:** Whether live stream updates (chunk pos changes) are applied directly to drawn nodes' pos field or go through glide animation.

---

## Summary

The embedding → UMAP → position pipeline is:
1. Chunks embedded with nomic-768 (tokens via for_model, links stripped)
2. Chunk vectors averaged (weighted/unweighted unit-norm means) into page centroids
3. Lead vectors (group or individual) trained by ParametricUMAP
4. Positions stored in ChunkProjector.pos and .page_pos
5. Streamed via delta() → sidecar HTTP → plugin polling
6. Applied to LayoutNode.pos (exact timing and mechanism UNCONFIRMED)

**Measurement readiness:** position stream is O(delta) per sidecar code; transformation cost prediction exists in RefitCost; GPU timing recorded.
