# Intent: iterate fast over many approaches, not settle on one

**This is the governing note. Read it before `SENSOR_FORMULATION.md`.**

`SENSOR_FORMULATION.md` presents *one* formulation. It is a candidate, not a
decision. The intent of this work is the opposite of converging early: to
**generate and try many algorithmic approaches**, each rooted in the
theoretical coverage, each a complete end-to-end answer to the whole
requirement set, and each mapped as far as possible **inside JavaScript,
Selenium and the shadow DOM themselves** rather than in downstream Python.

The method is:

1. state the requirements once, explicitly (§1);
2. name the axes the design space actually varies along (§2);
3. formulate several complete approaches, not fragments (§3);
4. run each through the same harness on the same pages (§4);
5. keep what the measurement prefers, and say why.

An approach that cannot be run end-to-end by the harness is not a candidate.
An approach that wins on one stage and is untested on the rest is not a
candidate either. Speed of iteration comes from the harness being fixed while
the approach varies — not from skipping the parts that are hard to measure.

---

## §1 Requirements — every candidate must answer all of them

These are examples of the full set, not the full set. New ones get added here
rather than assumed.

| | requirement |
|---|---|
| R1 | Work per mutation is O(delta), not O(page) — for every stage that can be |
| R2 | Nested open shadow roots, to arbitrary depth; closed roots reported as unobservable, never silently skipped |
| R3 | Mutation observation *everywhere* — every root, including roots that appear after load |
| R4 | Detect all content: text, urls, media, interactive controls, embedded JSON |
| R5 | Deduplicate — without downstream DOM access and without embeddings |
| R6 | Recursive chunking under a context-window budget, budget as a hyperparameter |
| R7 | Addressing: absolute xpath, complete and unique, stable under sibling insertion |
| R8 | Markdown/JSONL mirroring the address trie |
| R9 | Passive: no DOM modification, no page-visible state, no layout-forcing reads |
| R10 | Webnav: scroll, pagination, click, filters, menus as mutation sources |
| R11 | Downstream Python does vectorisation, frequency, PageRank, retrieval — nothing structural |
| R12 | The REPL is the terminus and is exercised per delta, not per page |
| R13 | Every stage independently measurable by the harness across ~10⁴ live pages |

## §2 Axes of the design space

Each axis is a real choice with measurable consequences. A candidate is a
point in this space; the space is the thing to explore.

| axis | options |
|---|---|
| **traversal** | manual recursion · `TreeWalker`/`NodeIterator` · `Range`-bounded · generator-sliced |
| **fusion** | one tupled fold · staged folds sharing a cache · separate passes |
| **digest combination** | positional (order-sensitive) · commutative+invertible (O(path) ancestor repair, order-blind) |
| **invalidation granularity** | node · chunk root · shadow root · region |
| **state location** | `WeakMap` · DOM attributes · `window` · Python-side |
| **shadow discovery** | probe added nodes · native `getHTML({serializableShadowRoots})` · patched `attachShadow` (rejected — modifies page) |
| **addressing identity** | ordinal xpath · stable-key path (`id`/`data-*`/content hash) with ordinal fallback · node identity + projected path |
| **detection site** | in-fold local predicate · `NodeFilter` during walk · downstream · accessibility tree (costs layout) |
| **dedup mechanism** | token-multiset subsumption · Bloom/bitset per node · digest equality · suffix-automaton |
| **chunk boundary** | char budget post-order predicate · pattern-based (mortegon golden trio) · hybrid |
| **transport** | full serialize · Merkle-pruned splice · chunk deltas only · interned-segment deltas |
| **scheduling** | synchronous in callback · debounce · `requestIdleCallback` · generator slices |

## §3 Candidate approaches

Each is complete end-to-end. Each is a different point, not a variation on one.

### A — Fused fold, node-granular, positional digest
The formulation in `SENSOR_FORMULATION.md`. One `TreeWalker` post-order visit
computing `{digest, chars, det, toks}` up and `path` down; `WeakMap` cache;
dirty set of nodes; repair along the root path.
*Strength:* maximal fusion, dedup free. *Risk:* ancestor repair re-hashes all
siblings of the changed child.

### B — Chunk-granular observers (the current engine, formalised)
Observer per emitted chunk root, plus one global for unclaimed regions. A
mutation re-chunks its own subtree only; the fold never leaves the chunk.
*Strength:* repair scope is bounded by the budget, not by depth. *Risk:*
cross-chunk moves and chunk splitting/merging are the hard cases.

### C — Commutative-invertible digest
Children combined by an invertible commutative operation (XOR / sum mod p), so
a changed child updates every ancestor by *subtract-old, add-new* in O(path)
with **no sibling re-visit**.
*Strength:* the cheapest possible ancestor repair. *Cost:* by Cor. 23.5 the
digest certifies the child *multiset*, not the sequence — pure reordering
becomes invisible. Viable only if a separate order witness (e.g. an ordinal
checksum) rides alongside.

### D — Stable-key addressing
Address segments prefer `id`, then a stable `data-*`, then a content hash,
falling back to ordinal only when nothing else exists.
*Strength:* directly answers R7 — sibling insertion stops renumbering
descendants. *Cost:* uniqueness must be re-proved; two nodes can share a key.

### E — `Range`-bounded repair
Use `MutationRecord.previousSibling`/`nextSibling` to construct a `Range` over
exactly the affected span and re-fold only that span.
*Strength:* the tightest possible dirty region for `childList` bursts.
*Risk:* only helps `childList`; attribute and characterData records are
already point-located.

### F — Detection in the `NodeFilter`
The walk itself rejects non-content subtrees, so detection costs nothing extra
and pruning happens at native speed.
*Strength:* fuses R4 into traversal. *Risk:* a filter that rejects too early
loses content an ancestor-level rule would have kept.

### G — Bloom-bitset dedup
Each record carries a fixed-width bitset of its token hashes; subsumption is
`(child & ~ancestor) === 0`, a few machine words.
*Strength:* O(1) dedup test, no strings compared, satisfies R5 with no DOM and
no embeddings. *Cost:* approximate — false "already covered" is possible, so
it needs a measured false-positive rate before it can be trusted.

### H — Native shadow serialization
`Element.getHTML({serializableShadowRoots: true})` where supported, instead of
manual shadow traversal.
*Strength:* the engine does the composed-tree walk. *Risk:* availability
across the target browser, and it returns markup rather than located nodes —
which may cost the identity keying that A and D depend on.

### I — Pattern-first chunking (mortegon)
Chunk boundaries come from detected repeating patterns and the golden-trio
joint-presence gate, not from a char budget.
*Strength:* directly addresses the 20.8% duplication and nav/footer noise.
*Cost:* pattern classes are quotient quantities (Prop. 23.3) — no local
repair, so this half must be batched and its staleness declared.

### J — Interned-segment delta transport
Path segments interned to integers in-page; deltas carry integer arrays plus
an incremental dictionary.
*Strength:* order-of-magnitude smaller payloads on delta-heavy pages.
*Orthogonal* — composes with any of A–I.

**Composability.** A–J are not mutually exclusive. C, D, E, G and J each
compose with A or B. The exploration is over *combinations*, which is another
reason to iterate fast rather than argue toward one answer.

## §4 How candidates are compared

The harness is fixed; the approach is the variable.

- Same frame (~10⁴ search-discovered pages), same scroll count, same budget.
- Per-stage metrics from one contract: `{stage, in, out, dirty, ms}`.
- Per-delta, not per-page: R12 means the REPL is driven on every pass.
- Reported as distributions per stratum, never means.
- Every candidate ships its **equivalence check** — incremental state must
  equal a periodic full recompute, or its numbers are not admissible.

A candidate is characterised by: work-per-mutation curve against page size,
bytes crossing the boundary, duplication rate visible in the REPL, content
recall against the page, and whether it holds R2/R3/R9 at all.

## §5 Why this note exists

The failure mode this guards against is the one already committed in this
repo: adopting the first plausible structure, measuring it with an instrument
built around it, and reporting the result as a property of the design. Many
candidates measured by one fixed harness is the corrective. The harness is
therefore the asset, and no candidate is permitted to bring its own.
