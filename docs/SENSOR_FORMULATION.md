# Formulation: a shadow-DOM sensor library

What the library *is*, stated once, then the object model, the API, and the
transformation from what exists today. Companions: `JS_INJECTION.md` (the
Selenium boundary), `JS_PATTERNS.md` (the patterns each decision uses).

---

## 1. The formulation

> **A catamorphism cache over the composed tree, with located invalidation.**

That is the whole library. Everything else is a consequence:

- *catamorphism* — one bottom-up fold computes every derived quantity;
- *cache* — the fold's result per node lives in a `WeakMap`, so identity keys
  it and collection clears it;
- *located invalidation* — a `MutationRecord` names where the change is, so the
  repair set is the root path from that node, given rather than searched.

The current code is the same idea spread across three traversals in two
languages with two chunk models. The transformation is not new capability; it
is collapsing that into the one sentence above.

## 2. The algebra

For a node `n` with composed children `c₁..cₖ` (light children then shadow-root
children, in document order):

```
R(n) = {
  digest : H(tag, contentAttrs(n), text(n), [R(cᵢ).digest])
  chars  : |text(n)| + Σ |R(cᵢ).chars|
  det    : detect(n)                              // local, no recursion
  toks   : toks(text(n)) ⊎ ⨄ R(cᵢ).toks           // multiset union
}
```

Four synthesised attributes, one visit. Plus one **inherited** attribute
carried downward:

```
path(n) = path(parent) · sep(n) · tag(n) · [ordinal(n)]
```

`path` must be inherited because it is a function of the route taken; deriving
it later means re-walking from the root, which is the single largest avoidable
cost in the present design.

### 2.1 What each attribute buys

| attribute | direction | pays for |
|---|---|---|
| `digest` | up | change detection, transport pruning |
| `chars` | up | chunk boundaries |
| `det` | local | content detection |
| `toks` | up | **dedup, for free** |
| `path` | down | addressing |

`toks` is the one worth dwelling on. Dedup by token-multiset subsumption — a
child whose tokens are a sub-multiset of what an ancestor already emitted is
redundant — currently runs in Python *after* rendering, which is why the REPL
shows **20.8% duplicate lines**. In the fold the multisets are already being
synthesised, so subsumption is a comparison the traversal has already paid
for. Dedup stops being a pass and becomes a predicate.

### 2.2 Chunking falls out of the same visit

A node is a **chunk root** iff `R(n).chars ≤ budget` and its parent exceeds it.
Post-order gives the parent both facts at the moment it folds, so chunk
emission happens at the parent with no second pass and no separate chunker.

This is the reconciliation of the two chunk models: there is one, and it is a
predicate on the fold, not a component.

## 3. Object model

Six types, no more.

```
Root      an observable scope: document or a shadow root.
          { node, observer, hostRecord }        roots form a tree via hosts

Record    the fold result for one node. Lives in WeakMap<Node, Record>.
          { digest, chars, det, toks, chunkId|null }

Address   (rootPath, nodePath, tag, accessor) — DERIVED from `path`, never
          stored. Identity is the Node; the address is a projection of it.

Chunk     a maximal subtree under budget, identified by its ROOT NODE.
          { node, lines[], addresses[] }

Delta     { added[], changed[], removed[] } of chunk ids, with payloads.

Sensor    the module. Owns WeakMap, dirty Set, Root map, buffers.
```

**Identity is the Node throughout.** The address is derived on demand. This is
what dissolves the renumbering problem: inserting a sibling renumbers the
*projection* of many nodes but invalidates the *record* of none — only the
inserted node's ancestors are dirty, and addresses are re-projected when a
chunk is next emitted rather than stored and patched.

## 4. API surface

Three verbs. Everything else is closed over.

```js
observe(rootNode)     // attach; discover nested shadow roots as they arrive
drain()  -> Delta     // swap buffers, return what changed since last call
stats()  -> Counters  // nodes, chunks, dirty, repairs, settled
```

`drain` and `stats` return in **one** call from Python's side (the boundary
toll is per-call, not per-byte). `observe` is idempotent per root.

There is no `getTree`, no `serialize`, no `extract`. A full document is just
the delta from an empty state, which is what makes the cold path and the warm
path the same code — and therefore the same correctness.

## 5. The repair cycle

```
mutation ──▶ mark: dirty.add(nearest chunk root or target)
             collapse: drop any node whose ancestor is already dirty
             schedule: requestIdleCallback (debounced)

repair ────▶ for each dirty root, in document order:
               invalidate: clear Records up the root path      O(path)
               refold:     TreeWalker over that subtree only   O(subtree)
               emit:       chunk added/changed/removed into buffer
```

Two properties this must hold, both learned from failures already recorded in
this repo:

- **idempotent** — repair recomputes a chunk from the DOM rather than patching
  a previous record, so an at-least-once mutation delivery cannot double or
  drop content;
- **verifiable** — a periodic full refold must equal the incrementally
  maintained state. Without that assertion an incremental cache drifts
  silently, which is exactly how 44 addresses vanished on archive.org.

## 6. What crosses to Python

Only `Delta`, and only chunk-shaped:

```
{ chunkId, absPath, lines: [{depth, text, addr}], removed: [chunkId] }
```

Python's remaining job is the half that provably cannot be repaired locally —
quantities defined across the whole document rather than over a subtree:

- frequency vectors and IDF,
- PageRank over the link graph,
- retrieval,
- the store,
- the REPL.

Nothing in that list re-derives structure. No re-parse, no re-tagging, no
second chunker.

## 7. Transformation from what exists

| today | becomes |
|---|---|
| `deep_serialize.js` (271) — digest fold + prune + serialize | the `digest` attribute of §2 |
| `wfh_chunk_engine.js` (1,177) — separate bottom-up chunker + observers | the `chars` predicate of §2.2 + §5 |
| `ContentTagger` (Python) — re-walk, re-detect | the `det` attribute, in-page |
| `AddressTrie.from_tagged` — rebuild per pass | `path` inherited; trie becomes a Python-side index of received chunks |
| `render_trie` + `_dedupe` (Python) | `toks` subsumption, in the fold |
| `data-vertiscope-hash` attributes on the DOM | `WeakMap` records |
| `window._wfhEngine` | closure + one hidden handle |

**Two JS modules of 1,448 lines collapse to one of roughly 400**, and three
Python stages (tagger, trie build, markdown render) lose their re-derivation
work and keep only what receives a delta.

The reason this is a compaction rather than a rewrite is that every piece
already exists — the digest fold, the bottom-up chunker, the detectors, the
subsumption dedup. They are currently *five traversals of one tree*. The
transformation is to make them five attributes of one visit.

## 8. What this formulation refuses

- **No page modification.** No attributes, no expandos, no layout reads.
- **No second cache.** One `WeakMap`; anything keyed differently can go stale
  independently, which is a defect generator.
- **No full-document API.** A cold start is a delta from nothing.
- **No structure work in Python.** If Python re-derives it, the boundary was
  crossed with the wrong payload.
- **No unverified incrementality.** Every incremental path ships with the
  full-recompute equivalence check that proves it.

## 9. Open questions this formulation does not settle

1. **Ordinal stability under insertion.** Records survive, but a chunk's
   emitted addresses change when a preceding sibling is inserted. Is the
   re-emission of those chunks acceptable, or does the address need a
   non-positional key (id / content hash) with ordinal as fallback?
2. **Detection scope.** `det` as a local function of one node is cheap but
   cannot express mortegon's golden-trio joint-presence gate, which is a
   predicate over *pattern members* — a quotient quantity. Does the trio gate
   live in Python with the other global quantities, accepting staleness, or
   does the fold carry enough to approximate it locally?
3. **Closed shadow roots** are outside the observable state and always will be.
   The library should say so in its stats rather than silently under-report.
