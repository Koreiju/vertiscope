# Design VII — one unit per surface, an overlay that never waits, pages that open whole

**Status: the design Addenda V–VII are built from. Written 2026-09-26, before
the code it describes, as Addendum VII's follow-up requires:** *"re-assess the
landscape of the features from a bird's-eye-view and propagate the necessary
updates and changes downwards ... so that you're not making a whole bunch of
filament-like single-shim changes."*

Every decision below cites the verbatim it serves (`PLUGIN_GOAL.md`) and the
measurement that shaped it. Where the code today disagrees, that is listed
as work, not glossed.

---

## 1. The units, and which surface shows which

The pipeline has four units. Most of today's confusion came from a surface
showing the wrong one.

| unit | what it is | made by | shown by |
|---|---|---|---|
| **address** | one element of the page, `url : xpath` | the sensor's fold, the trie | nothing directly; everything resolves through it |
| **chunk (256)** | a contiguous run of the trie's content, ≤ 256 link-free tokens, leniently (§4) | stage one, `render_trie` | the **retrieval panel** (search hits, scoped ranking, a model's context), the **browser overlay** (hover, pin), the **markdown side panel**, a **pinned billboard's content** |
| **display unit (512)** | a merge group's lead standing for its members — or a chunk with no group — ≤ 512 link-free tokens | stage two, `aggregate` | the **3D graph's leaves** (a pinned chunk's billboard hangs from its group's leaf) |
| **page** | a scanned url | the store | the **3D graph's UMAP layer** (one centroid per page) |

Verbatim: *"The projector shows the aggregated vectors while the retrieval
still runs on the 256 chunks"* (IV); *"sanctioning of subchunks vs chunks to
their respective UIs; the retrieval panel(s) and the 3D graph"* (VII);
*"UMAP is only applied to the averages over pages"* (VII).

**Consequences that are work:**

* The overlay outlines **the chunk's extent** — the union of the boxes of
  every element its lines address — not the one element the hover resolved
  to. (Decided 2026-09-26: *"make hover-pin the 256 limit"*; this section
  first proposed the 512 unit.) Measured: on the Radix tree page 6 of 8
  heading/paragraph pairs are ONE chunk, yet hovering drew the `<h2>` box for
  one and the `<p>` box for the other; the reader saw "two different chunks"
  that the pipeline had as one.
* The markdown side panel shows the pinned chunk's markdown (256).
* The graph's tree leaves are display units (`page_tree` already draws leads
  only).
* The retrieval panel stays on 256 chunks (`G-27`, `G-63`, `G-64` — unchanged).

## 2. Token counting — one rule for both windows

What the requirements say: stage one cuts at **256 link-free tokens**
(`G-28`); stage two merges up to **512** "for **text-only** tokens" (IV,
`MERGE_WINDOW`); the encoder is given link-free markdown (`G-22`/`G-23`);
source code is dropped for `code://` only (`G-52`).

What the code does: **both windows count the same string** —
`tokens.budget` = cl100k tokens over `tokens.for_model(markdown)`: link
TARGETS removed, link labels kept, bare urls removed, everything else counted
(headings, emphasis markers, table pipes, image alt text, code). The chunker
(`markdown.py`, whole chunks and per-line runs) and the aggregator
(`aggregate.py`, `costs = tokens.budget(md)`) use it; nothing else counts.

Differences to resolve:

1. "Text-only" (512) vs "link-free" (256) are worded differently in the
   requirements and implemented identically. **Decided 2026-09-26: they are
   the same rule** (*"text only and link free are the same"*).
2. `code://` chunks are *embedded* without code (`budget_for`) but *cut* with
   it (`budget`) — the chunker counts a string the encoder never sees. Fix:
   the chunker uses `budget_for` with the chunk's url.
3. The 256 window is a target, not a ceiling: a single indivisible unit is
   emitted whole (38 chunks over 256 on the Persona page, max 607). Recorded,
   not changed.

## 3. The pipeline, and what must never wait on what

```
 page ──fold (in-page, ms)──▶ drain ──▶ trie absorb ─▶ render/chunk ─▶ store
                                                  │                     │
                                                  └──▶ OVERLAY MAP ◀────┘ (reply)
 store ──(async worker)──▶ embed ──▶ aggregate ──▶ page centroid ──▶ UMAP place
```

Verbatim: *"we're not async on the stages ... chunking algorithms would be
blocked by downstream vectorization before we see the actual chunk-based
overlays"*; *"hovers need a 1 second or longer latency"* (VII follow-up).

Measured (Radix tree, in-app, 14 hovers): reading `:hover` 6 ms p50; the
chunk's box 0–6 ms; **`/resolve` 28 ms p50, 5,626 ms max** — the store
serialises every statement and a landing capture holds it for seconds. Plus
the corner box polls every 200 ms, and a first hover on unstored content waits
for a drain + store round trip.

**Design: the overlay reads a map the renderer holds, never the store.**

* **The page's display map**, in the browser cell: `xpath → {cid, lead,
  member xpaths}`, built once on landing from one call (`GET /page_map`) and
  kept current from each capture reply, which already names the dirty chunks —
  O(delta), no extra round trip.
* **Hover** = read `:hover` (6 ms) → walk up to the nearest mapped xpath
  (local, µs) → display unit → the union of its elements' boxes (one in-page
  call, ≤ 6 ms). Target **< 50 ms**, polled at 80 ms. The store is not on the
  path; `/resolve` is kept for the harness and for right-click.
* **Hover-first stays** (`G-80`): an unmapped element drains now, and the
  hovered unit jumps the embed and projector queues.
* Embedding, aggregation and placement stay off this path by construction:
  a group formed later updates the map when its capture reply lands.

## 4. The chunker: a heading heads what follows it

Verbatim: *"I'm hovering over a heading and a paragraph and seeing two
different chunks, but I'm sure that this should be one chunk."*

Measured: 2 of 8 pairs on the Radix tree page really are separate chunks —
the long sections ("Comparison to other data structures", "Variants"). The
section overflows, the chunker splits it into its children, and the heading's
wrapper (22 and 16 tokens) is flushed alone: either a content-boundary cut
lands right after it, or the next child is too big to pack and forces a flush.
Stage two does not rejoin them because it merges by similarity, not adjacency.

**Rule (decided 2026-09-26): the 256 cut is lenient.** Verbatim: *"If this
is closer to 512 than 256 in the merge after the context limit, keep the
previous, otherwise include the merge as the final chunk. This should be
pretty lenient to edge cases where we include headings as well."* So in the
merge loop, when the next piece would take the run past the window, the run
TAKES it if the result is still nearer 256 than 512 (under 1.5 × window =
384) and ends the run there; otherwise it stops before it. The same test
governs the two ways a heading is orphaned today:

* a content-boundary cut is never taken right after a heading piece;
* when the next piece must be descended, a buffered run ending in a heading
  is merged into the first chunk that descent produces if the two together
  are under 384 (rooted at the shared parent, which under-claims — safe).

The retrieval unit's ceiling therefore becomes 384 in the worst case, by the
reader's own rule; the target stays 256.

This changes chunk ids on re-scanned pages (a chunk's id is its root and
part). `CLAUDE.md`'s rule applies: no corpus run while this is being edited;
re-measure after.

## 5. The browser cell: the page is the main surface, pins are side panels

Verbatim: *"favor a more direct side-by-side with electron browser as still
the main focus and the right-clicked chunks still as the side-panels"* —
superseding IV's *"switchable second view"*.

* The **markdown face and its toggle button go.** The cell is the page, plus
  the side panel whenever something is pinned.
* The side panel is a **stack of pinned display units**, newest first, each a
  native markdown render with its close ×; closing one closes its outline and
  its billboard (`G-78`, built).
* Pins survive navigation as panels; their outlines hide when their page is
  not the one shown.

## 6. The 3D graph: pages by UMAP, a page's inside by its tree

Verbatim: *"UMAP is only applied to the averages over pages, and then
clicking one page ... we should expand out the full patricia trie at the same
time for one shadow DOM. Left-clicks on nodes expand, right clicks contract
them back ... scrub all the complexities on the per-fold opening/closing
logic"*; *"the patricia tree ... the subtree of all the content nodes ...
intermediate path nodes ... as a single link"*; *"max link lengths need to be
much longer"* (VII).

* **UMAP over page centroids only** (`PageProjector`, built). Centroid:
  `triple` — PageRank-weighted semantic centroid ⊕ PageRank-weighted tf-idf
  centroid (SVD-reduced), each unit-normed — or `semantic` alone. Both are
  computed and timed at every fit; the default follows the measured
  milliseconds (VII: *"depending on millisecond time profiles"*). Stream: a
  changed chunk re-derives only its page's centroid. Refit at 2× chunk growth
  (V), persisted, reconciled on start.
* **A page opens whole** (`GET /page_tree`, built): the patricia tree of its
  content — a node only where the DOM branches, every chain one link, one
  parent per node (measured on the store: 8,338 of 8,379 chunks have one
  containment parent; the lattices came from the per-step view's star + its
  containment edges, not from the store).
* **Left-click** a page: open its tree. **Right-click** a page or any node of
  its tree: close the tree back to the page node. A chunk leaf's left-click
  opens its billboard (shadow-DOM form, `G-77`). Deleted: per-step unfold,
  territory/room/`contain`, the chunk-level toggle, chunk positions from UMAP.
* **Forces:** page nodes pinned at their UMAP positions; tree nodes under a
  link force with **long** distances, charge repulsion among tree nodes, and
  collision. The link distance is set from the page layer's own spacing (not
  a constant), and a check asserts the drawn tree's median link length.
* **The browsed page is open**: landing on a page opens its tree, and each
  drain's chunks arrive attached to their branch (`place_tree`, built).

## 7. What streams where (O(delta))

One capture reply feeds three consumers, none waiting on another:

| consumer | from the reply | cost |
|---|---|---|
| overlay map (browser) | dirty chunks' xpaths and ids | local update |
| graph (if the page is open) | `place_tree` of the dirty chunks | their branch path only |
| projector (sidecar, async) | the embed worker's cids | the page's centroid, one transform |

## 8. Verification — every row checked in the running plugin

All in `checks/live.mjs`, run inside the plugin (`G-75`), each with a planted
arm where one is possible:

| row | asserts | planted |
|---|---|---|
| overlay latency | hover → outline drawn, p95 < 100 ms, with a capture in flight | a 1 s sleep in the map path must fail it |
| overlay extent | hovering a heading and its paragraph in ONE unit draws ONE box = the union of the unit's element boxes | outlining the matched element must fail it |
| heading rule | no chunk on a re-scanned fixture consists of a heading alone | the old merge loop must fail it |
| side panel | no markdown face/toggle; pins stack; closing one closes three | — |
| page UMAP | layout points are pages; centroid kind and its ms reported | — |
| tree | `max_parents == 1`; open/close by left/right click; median link ≥ the page layer's median gap | multi-parent edges injected must fail it |
| streaming | a drain on an open page adds nodes attached to their branch | — |

## 9. Order of work

1. The overlay map + union extent + faster poll (§1, §3) — the reader's
   sharpest complaint, and independent of everything below.
2. The side panel as the only second view (§5).
3. The graph: page UMAP default, whole-tree open/close, long links, deletion of
   the per-step machinery (§6).
4. The heading rule in the chunker (§4) — last, because it changes chunk ids
   and wants a clean re-measure.
5. Checks for each, run in-app (§8), and the PRD rows updated from them.
