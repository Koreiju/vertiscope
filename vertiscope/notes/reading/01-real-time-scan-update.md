# REAL_TIME_SCAN_UPDATE.md — notes

891 lines. Marked HISTORICAL/SUPERSEDED (§O.17) **as an implementation target**,
but it is the only document that specifies the delta-chunking algorithm at the
level I need. Its *operational* reasoning is not superseded — what was
superseded is the frontend/layout half and the `cp/*.js` file surfaces.

**Verdict: this is the source document for the mutation-chunking-delta-vectorizer.**
My `docs/THEORY.md` re-derived a weaker version of it from scratch. Several
things in THEORY.md are now provably wrong or naive. Listed at the bottom.

---

## The vocabulary it fixes (§2)

| term | definition | in vertiscope? |
|---|---|---|
| Content-distilled DOM | only content-bearing nodes; wrappers kept as ancestry connectors | yes (`content_tagger`) |
| **Generalized XPath** | indices stripped **below `PATTERN_ANCHOR_DEPTH`**; segments above the anchor kept verbatim to disambiguate page regions | **NO — we strip ALL indices** |
| Pattern | region-anchored generalized xpath | partial |
| **Subtree Text Budget** | prose-relevant chars only. Computed from **direct `Text` children only, never `el.textContent`** | in JS engine; Python side differs |
| **Content Hash** | 32-bit rolling hash of node + all descendants | computed (`_subtree_hash`) but unused across scans |
| Content Leaf | deepest node with non-empty `content_fields` and no content-bearing children | yes |
| Commutation Count | # absolute xpaths sharing a generalized pattern | yes |
| **Verified Delta** | a batch the scanner has confirmed *stable* — no further mutation at the same patterns on the next scroll. Only verified deltas trigger re-chunking | **NO** — we settle the whole page, not per-pattern |
| Chunk Ledger / `_claimed` | chunk_id → consumed xpaths, plus the **reverse index** xpath → chunk_id | **NO** |
| Landmark Anchor | nearest `<main>/<nav>/<header>/...` ancestor, prefixed to the pattern key | **NO** |

## Architecture (§3)

Four layers: Selenium/CDP → Python mapper → snapshot pipeline → GUI.
Explicit decisions worth keeping:

- **No separate distill step** — detection and budgeting fused into the JS walk.
- **Hash-diff transport** — JS *accepts* `prevHashes` (xpath → hash) and returns
  only nodes whose hash changed. Stated effect: **~10 MB → a few KB** on
  subsequent scrolls. This is the memory/bandwidth answer, and it is a
  *protocol* property, not an algorithm property.
- TF-IDF and embedding happen **asynchronously in the background, never
  blocking the live stream**.
- Master tree retained in memory **solely for lazy billboard serialization**,
  "never re-walked for scanning or chunking".

## Output format (§4.6) — the thing I was asked about

Tree-structured JSON, `_meta` per node, plus a **flat `leaves` array** of
absolute xpaths:

```json
{ "tagName": "li", "xpath": "/html/body/div[2]/ul/li[1]", "children": [...],
  "shadowRoot": null,
  "_meta": { "subtree_text_budget": 342,
             "has_image": true, "has_audio": false, "has_video": false,
             "has_interactive": true,
             "content_fields": { "text()": "The Fool",
                                 "a/@href": "/cards/the-fool",
                                 "img/@src": "https://.../fool.jpg" },
             "content_hash": "0xA3F2C1D4" } }
```

Dual purpose is explicit: **the tree structure serves the merge/dedup
algorithm** (needs parent-child links + sibling order) while **Python lifts
`_meta` into flat indexes without a second traversal**. That is exactly the
"renderable data + characterizing hidden metadata" split in the request.

`content_fields` = **relative address → value**, addresses being `text()`,
`@attr`, `child/@attr`. Values >80 chars truncated (full value stays in DOM).

## Shadow DOM (§4.1, §4.7)

- Shadow children get xpaths `/host-xpath/#shadow-root/child-tag[N]`; their
  text and budgets **merge upward into the host**.
- When the bottom-up walk hits a `#shadow-root` segment as a parent, **skip it
  transparently** and use the shadow host as the effective ancestor — otherwise
  the literal `#shadow-root` in the pattern makes it look unique (count=1) and
  forces an early stop. Consequence: `representative_xpath` may point outside
  the shadow root, which is valid because the shadow subtree is already in the
  member set.

## Embedded content (§5) — regex over embedded fields

The canonical detection table. Relevant to "URLs and JSON only":
- **urls**: URL regex over *all* attribute values (not an allowlist) except a
  skip-list, plus explicit `href/src/action/poster/data-*/cite/longdesc`.
  `data:`/`blob:` → resource.
- **json_data**: `<script type="application/ld+json">`, plus **any `data-*`
  attribute that parses as valid JSON**.
- **Excluded attributes** never scanned: `style, class, id, width, height,
  viewbox, d, fill, stroke` (`_SKIP_ATTRS`).

## Python indexes (§6.1)

`_tag_cache` (xpath→meta), `_pattern_index` (pattern→{xpath}),
`_chunk_ledger` (chunk_id→consumed xpaths), **`_claimed` (xpath→chunk_id,
reverse index, O(1) claim checks)**, `_sorted_xpaths` (bisect for descendant
ranges: `bisect_left(sorted, mxp + '/')` then scan while prefix matches →
**O(log N + |descendants|)**), `_pattern_chunks`.

Explicit lifecycle: per-snapshot only; cleared at navigation/teardown.

## Delta integration (§6.2)

Two phases — **evict removed first**, then integrate changed. Removal is
computed as `set(_tag_cache) - set(new_nodeMap)`, and any chunk containing a
removed xpath marks its pattern dirty. Then dirty patterns are **fully
re-chunked** (see §7.7).

## Bottom-up chunker (§7)

Leaf → ancestor walk, stopping on the **first** of:
1. `subtree_text_budget > HARD_CHAR_LIMIT` (aggregate over the whole subtree —
   a `<section>` with 10 cards has 10× budget, correctly preventing it from
   becoming one chunk);
2. commutation count == 1 (unique structure);
3. **fingerprint divergence** across instances of the pattern.

`chunk_id = sha1(url|pattern|ordinal)[:16]` — deliberately **excludes
snapshot_id** so ids are stable across scroll iterations, which is what makes
`chunk_replaced` update a sphere in place instead of remove+add.

Ordinals from lexicographic sort of split-cluster representative xpaths
(lexicographic order of absolute xpaths == document order for siblings).

§7.4 argues *why* `content_hash` and not Jaccard over `content_fields`: an
ancestor's own `content_fields` is empty, so two `<li>`s differing only in
`<img>` vs `<video>` children look identical at the `<li>` level. Only the
rolled-up hash sees it. `STRICT_HASH_MATCH` (default True) with a **tolerant
per-pattern override** when all instances share a key schema but differ in
values — auto-enabled when strict mode would have split into N single-member
chunks with identical key sets.

§7.6 splitting = cluster by fingerprint, recurse from each cluster's leaves.
"Recursive sampling": start optimistically wide, refine only on violation.

**§7.7 is important and I got this wrong.** On a dirty pattern, *always re-run
the full bottom-up chunker on that pattern's leaves* — never patch
`member_xpaths` in place, because new members can change which ancestor wins
the budget check. Correctness beats finer incrementality. So the O(Δ) unit is
**the dirty pattern**, not the dirty node.

§7.8 **Landmark anchoring** solves generalized-xpath collision across regions
(nav `<ul>` vs results `<ul>` both → `/html/body/div/ul/li`). Pattern key is
prefixed with the absolute xpath of the nearest landmark ancestor. Explicitly
chosen over `PATTERN_ANCHOR_DEPTH=3` because deep React trees hit generic
wrapper divs at fixed depths.

---

## Corrections this forces on `docs/THEORY.md`

1. **§1 `g` is wrong.** I defined generalization as strip-all-indices. That
   collides across page regions. Must be landmark-anchored.
2. **The O(Δ) unit is the pattern, not the node.** My path-repair theorem is
   right about invalidation but wrong about the repair granularity — §7.7
   deliberately re-chunks the whole dirty pattern for correctness.
3. **I missed hash-diff transport entirely.** The dominant cost on a live scan
   is the JS→Python payload, not the fold. 10 MB → KB. This belongs in the
   cost model as a first-class term.
4. **I missed "verified delta".** Re-chunking on unstable deltas produces
   churn; the doc gates on per-pattern stability, which is finer than our
   whole-page settle.
5. **My containment/laminar-family proposal is a reinvention.** `_claimed` +
   `_sorted_xpaths` bisect already gives O(log N + |desc|). Reconcile: a sorted
   string list with prefix-range queries *is* the trie, flattened.
6. **chunk identity diverges.** Doc: `sha1(url|pattern|ordinal)` (stable under
   content change → enables `replaced`). vertiscope: `sha1(url|pattern|content_hash)`
   (content change → new id). Ours cannot express `chunk_replaced`. Needs a
   deliberate decision, not an accident.
7. **Budget definition matters and I hand-waved it.** Direct text only (never
   `textContent`, which multiplies by depth), and URLs/media **excluded** from
   the budget while still being extracted as fields.

## Open questions

- Is `PATTERN_ANCHOR_DEPTH` still live, or fully replaced by landmark
  anchoring? (§2 defines it; §7.8 argues against it.)
- Does the shipped `wfh_chunk_engine.js` implement hash-diff transport, or was
  it only specified? `scanner.py` has `_prev_hashes` — check whether the JS
  actually consumes it.
- Read the remaining ~450 lines (§8 onward).
