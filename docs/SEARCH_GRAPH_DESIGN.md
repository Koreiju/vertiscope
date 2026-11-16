# The search as a computation graph on the 2D plane

Design before code, for PLUGIN_GOAL items 163 and 164 (2026-11-15).

## Revision (item 164, the same day) -- this section supersedes §2-§4's drawing

The reader, on the twelve-panel plane: "this might be overcomplicating
things on second thought. A high-level retrieval mechanism that integrates
cleanly with its input and output artifacts, in that all its inputs and
outputs are shown as hard links, is there". So:

- **One node.** The search is ONE retrieval node on the plane -- the ego
  slate's search cell (`ego.md`, `/cell/state`), not twelve stage panels.
- **Its inputs, as hard links:** the artifacts it reads -- the slate it is
  typed into (query, `db`, `duckduckgo`, `where`, `k`), and, when
  `duckduckgo` is on, the browser cell that runs the web branch.
- **Its outputs, as hard links:** each returned result, linked to the node
  that draws that chunk (the `{results}` braces of RESERVOIR item 34 made
  visible as edges). The links change when the results do; nothing is kept
  per search (item 164: "Live search only").
- **"Similar"** on a result re-enters the same node with the result as its
  query, keyed by its stored rows, all three factors (item 164).
- **The per-stage trace stays as DATA** (§5 step 1, `?trace=k`, built): it
  is what answers "why did this rank", and an unnest may show it later, but
  it is not drawn by default.

Observed in the running app before this revision (2026-11-15 20:55, MCP):
the ego plane holds 12 pages (the ego slate, browser slates, notebooks,
chat cells, an outline), its graph data holds NO links among them and no
search node. So the target is not yet built.

**Steps, revised.** (1) the trace -- built. (2) ref queries: `query` accepts
a cid. (3) the search node and its hard links on the plane: inputs from the
slate (and the browser cell when web is on), outputs to each result's node;
live check: one search node, its out-links = the hits shown, in-links = its
input artifacts; planted, the links withheld. (4) `similar` on a result =
(2) through that node.

---

*The original design follows. Its component table (§2) still names what
the node is made of; its drawing (§3) is withdrawn by item 164.*

## 0. What was asked, and what this reads it as

The verbatim is item 163. Three of its sentences carry the design:

- bring "the computation graph of our 'search' bar feature" into the 2D
  viewer's cells and nodes;
- give "each independent component of the existing retrieval framework"
  the intent of "simplicity, minimalism, and interconnectedness of
  abstract-most independent components";
- give "the returned results ... their own similarity based soft links per
  some discussion on the mouse-based navigation before".

Two earlier records bound the reading:

- **Item 91** ends: "seeing immediate search results if i were to unnest
  black box panels to obtain the computation graph for that component".
  So the search cell is a BLACK BOX, and unnesting it is how this graph
  appears. It is not a second search UI.
- **Item 133(g)**: "Soft links are subsumed by 'similar'". So a result's
  soft links are its `similar` retrieval: the halo of items 81-84 and 91,
  where the node nearest the mouse becomes the new retrieval key.

*My reading, not the user's words:* the graph is the search's own
dataflow, one panel per stage that exists in the code today, with each
panel showing that stage's output for the live query. "Similar" on a
result feeds the result back into the same graph as its query.

## 1. The question item 163 opens with: should matching be embeddings?

It was answered by measurement before this design. The answer is no,
because the failure was not lexical. All three defects are fixed with
planted tests (commits listed in OPEN_WORK):

| defect | what ranked first | the fix |
|---|---|---|
| no TypeScript in the corpus | anything but `pipelinebox.ts`, which defines `unionRect` | `code://plugin/`, `tests/test_plugin_source.py` |
| the slate held its own query | `ego.md`, matching the query typed into it | slate `state` addresses, `tests/test_slate_state.py` |
| a results page echoing the query | DuckDuckGo, content share 0.0, score 0.61 | content weighs, never just adds; `tests/test_content_share.py` |

The echo is the case that settles it. A page that repeats the query is
nearest to the query **in both spaces**: live it had lexical 0.47 and
semantic 0.78. In the test's bag-of-words encoder it had lexical 0.69 and
semantic 0.99, against the real answer's 0.11 and 0.20. Embedding-only
matching ranks the echo first too. What separates the echo from the answer
is the content factor, which neither space measures.

The user's other suggestion — comparing the frequency and encoder rankings
side by side — is what this graph is for. Each factor gets its own panel
showing its own top-k, so the reader can see on the plane which factor put
a result where it is.

## 2. The components, as the code has them

Each component below is a stage the code already separates, and almost all
are already timed (`SearchDiagnostics.ms`, the `_lap` names). Every stage
reads and writes rows, and a row is a cid, which is an address in the trie
(`url : xpath`). That is how each panel stays on the map.

| node | inputs → output | code | timed as |
|---|---|---|---|
| **query** | string, or a `{ref}` (section 4) → the query | slate `search/query`; `kernel_objects.search` | - |
| **lexical** | query → a 0..1 score per row (frequency matrix) | `ThreeFormIndex.search` | `lexical` |
| **encoder** | query → one vector | `embedder.embed_query` | inside `semantic` |
| **semantic** | vector → a cosine per row (`EmbeddingMatrix`) | `ThreeFormIndex.search` | `semantic` |
| **rank** | none (query-independent) → a percentile per row: link PageRank, or the code graph's where higher | `_percentile`, `_code_rank_rows` | - |
| **content** | none (query-independent) → a share per row | `content_share` | - |
| **fuse** | lexical, semantic, rank, content → score; lexical > 0 gates | `ADDITIVE_WEIGHTS` × floored content | `fuse` |
| **scope** | score, `url`, live → masked score | `scope_url`, `_live`, `_prefilter_code` | `scope_and_code` |
| **select** | score, k → top rows, duplicate content collapsed | digest collapse | `select` |
| **shape** | rows, `where` → the hits a reader sees: state/output rule, ego/web, redundant, group leads, budget, refill | `search_payload` | `shape` (sidecar) |
| **web** | query → rows from the browser cell (DuckDuckGo, captured like any page) | `kernel_objects.search(duckduckgo=True)` | - |
| **results** | hits (+ web), merged by rank → an iterable of `{ref}` | slate `results` | - |

**Why these and not fewer.** Merging lexical with semantic, or rank with
content, would hide exactly the disagreement item 163 asks to see.
**Why not more.** The BM25 inner terms, the code prefilter's partitions and
the refill loop are each one decision inside one stage. They unnest a
level down if asked, as any black box does (item 91).

## 3. Layout and links on the plane

- **Signal flow governs layout** (RESERVOIR item 35). Left to right:
  `query` → {`lexical`, `encoder` → `semantic`} → `fuse` ← {`rank`,
  `content`} → `scope` → `select` → `shape` → `results` ← `web`. The two
  query-independent priors sit on the inbound side of `fuse`, so each
  column on the plane is one dependency depth.
- **Each panel shows its stage's output for the live query**, as a ranked
  list of `{ref}`s with values: lexical's top-k by lexical, semantic's by
  cosine, and so on. One extra readout, on `fuse` only: the overlap between
  the lexical and semantic top-k (shared count, and Kendall's τ over the
  union). That overlap is the comparison item 163 asked for, and the place
  an echo shows itself: high in both, zero in `content`.
- **Edges are data links, not soft links.** They are drawn the way
  `{query}` / `{results}` braces are (RESERVOIR item 34), and are kept
  apart from the code links that bind `search` to `Database`.
- **The 3D view**: the result nodes are readouts at the reservoir's
  perimeter (RESERVOIR §4), unchanged. The stage panels are plane panels
  and are not placed by the world fit (the rule in RESERVOIR "inputs and
  outputs are NOT placed by the world fit").

## 4. A result's soft links: "similar" closes the graph

`similar` on a result node (133g, the halo of items 81-84 and 91) feeds the
graph's own `query` node with the result as a `{ref}` instead of a
string:

- `lexical` reads the ref's stored frequency row, so there is no tokenizing;
- `semantic` reads the ref's stored embedding, so there is no encoder call
  (the encoder panel shows "skipped: ref");
- `rank`, `content`, `fuse` and everything after are unchanged.

So "similar" is not a second retrieval path. It is the same graph keyed by
an address, and its results are the halo. The mouse navigation of item 91
(the node nearest in 2D becomes the new key) is the same call, made by
movement rather than a click. One graph serving typed queries, clicks and
mouse navigation is the "interconnectedness of abstract-most independent
components" in a form that can be tested: every path into retrieval enters
at `query`.

## 5. What has to exist, and how each piece is proven

Patricia-trie framing: every new surface below reads cids, which are trie
addresses. None writes the trie.

1. **Built 2026-11-15** (`?trace=k`, `Search._trace`; live: see G-372). **`GET /search?trace=1`**: one search returning every stage's output
   (per-factor top-k with values, the overlap readout, laps, counts). It
   is built from `SearchDiagnostics`, which already holds the laps and
   counts; the per-factor vectors are the new part. Test: the trace's
   `fuse` top-k equals the plain search's hits, and a planted
   `PLANT_NO_CONTENT_FACTOR` moves the `content` column and the order
   together.
2. **Ref queries** (`query` accepts a cid). Test: a ref query on a chunk
   returns that chunk first and makes no encoder call (counted). Planted:
   the ref's text re-encoded, so the call count is non-zero.
3. **The black box unnests** in the 2D plane. The `search` cell's
   unnest draws the twelve panels above, wired as section 3 lays out, with
   values from (1). Live check: unnest → 12 panels and 13 edges (`query` feeds `lexical`, `encoder` and `web`); each panel's
   top row equals the trace's. Planted: a stage panel fed another stage's
   column must fail the check.
4. **`similar` on a result** calls (2) and draws the halo. Live check: the
   halo's first ring is the trace of a ref query on that result.

## 6. Open — needs the user

1. **Should `similar` from a result use all three factors, or semantic
   only?** Section 4 assumes all three, keyed by the ref. Semantic only
   would match item 91's "radially normalised similarity distance" more
   literally, and would lose the lexical gate.
2. **Does the overlap readout belong on `fuse`, or on its own panel?**
   Section 3 puts it on `fuse` to keep the panel count at the code's stage
   count.
3. **Is the trace kept per query?** That would make a search's graph a
   replayable artifact (a rollout, RESERVOIR E.7). Kept now only for the
   live query.
