# Theory: JavaScript patterns for an in-page extraction algorithm

How the injected code should be *built*. Companion to `JS_INJECTION.md`, which
covers the Selenium boundary; this covers the algorithm on the page side.

The governing constraint: a passive sensor over a mutating shadow DOM that
holds its own state, touches nothing, blocks nothing, and repairs locally.
Every pattern below is chosen against that.

---

## 1. One fold, many algebras (tupling)

The single most important structural decision. A subtree needs, at once:

- a Merkle digest (what changed),
- a content-budget total (where chunks divide),
- an absolute xpath (the address),
- a content detection (what kind of datum it is),
- a dedup key (whether an ancestor already says this).

Computing these in five traversals is five times the work and — worse — five
opportunities for the traversals to disagree about the tree they walked.
**Tupling** (the banana-split law) says a tuple of folds over the same
structure is itself one fold. So one post-order pass returns a record:

```js
// one visit, one record, five results
{ digest, chars, xpath, detections, tokens }
```

The xpath is the one that *must* come from the same walk: it is a function of
the path taken, so recomputing it later means re-walking from the root. Carry
it down (inherited attribute) while digest/chars/tokens come up (synthesised).
That is a single attribute-grammar pass, not two traversals.

**Consequence for the current code:** `deep_serialize.js` folds digests,
`wfh_chunk_engine.js` folds chunks, and Python re-derives xpaths and
detections from a re-parse. Three walks of the same tree in two languages.
Collapsing them is most of the compaction available.

## 2. State lives beside the DOM, never in it

`WeakMap<Node, Record>` is the pattern that makes a passive sensor possible:

- **no expandos, no attributes** — the page cannot see it, CSS cannot select
  on it, and the page's own scripts cannot collide with it;
- **removal is free** — a detached subtree's entries are collected with the
  nodes, so there is no cache-invalidation pass and no leak on a feed that
  churns thousands of nodes;
- **identity, not position** — the key is the node itself, so it survives
  sibling insertion that renumbers every positional address.

That last property is the answer to the renumbering problem: keep the *cache*
keyed by node identity and treat the xpath as a derived, recomputable value,
rather than keying the cache by a string that an unrelated insert invalidates.

`WeakRef`/`FinalizationRegistry` are available but not needed here: nothing
must *react* to collection, only stop occupying memory.

## 3. Native traversal beats recursion

`document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | SHOW_TEXT, filter)`
runs the walk in the engine rather than in interpreted frames:

- no per-node array allocation — `Array.from(node.childNodes).map(...)`, as in
  the original serializer, allocates an array per node and a closure per call;
- `NodeFilter.FILTER_REJECT` prunes a whole subtree at native speed, which is
  the cheap way to skip `<script>`, `<style>`, `<template>` and already-clean
  subtrees;
- no recursion depth limit — a 6,000-deep wrapper chain is ordinary for a
  walker and fatal for naive recursion.

A walker does not cross shadow boundaries, so the pattern is *one walker per
root*, with a small explicit stack of roots to visit. That stack is the only
recursion in the design.

## 4. The observer is a producer; the drain is a consumer

Classic producer/consumer with a **double buffer**:

```js
let front = [], back = [];        // swap on drain, never splice
function drain() { const out = front; front = back; back = out.length ? [] : back; out.length = 0; ... }
```

Swapping references is O(1); `queue.splice(0)` is O(n) and reallocates under
the reader. The observer callback appends to `front` and returns immediately —
it does no work beyond marking a node dirty, because a callback that computes
runs inside the page's own critical path.

**The dirty set is a `Set<Node>`, not a list of records.** Mutation records are
redundant by nature: a render storm produces hundreds naming a dozen distinct
subtrees. Coalescing to a set of dirty roots — and dropping any node whose
ancestor is already in the set — turns a burst into a small repair. That
ancestor-collapse is the highest-yield line in the whole callback.

## 5. Repair is scheduled, not immediate

The callback marks; an idle task repairs:

- `requestIdleCallback(repair, {timeout})` yields to the page's rendering and
  is what makes the sensor passive in the performance sense, not merely the
  mutation sense;
- a **generator** makes the repair interruptible — `yield` between chunk roots
  lets a long repair spread over several idle slices instead of blocking one;
- the pending-timer flag *is* the settle signal the Python side reads.

**Never read layout in the callback.** `offsetHeight`, `getBoundingClientRect`,
`getComputedStyle` force synchronous reflow; a sensor that touches them stops
being passive and starts changing the page's timing. Structure and text are
free, geometry is not — which also means visibility must be inferred from
markup, never measured.

## 6. Memoise by identity, invalidate by ancestry

Hash-consing, applied to the DOM: a node's record in the `WeakMap` is valid
until the node or a descendant mutates. So invalidation walks *up* from a
dirty node clearing ancestors' records, and recomputation walks down only
where a record is missing. Both are O(path), never O(page).

This is the same information the Merkle digest carries, which is why the two
must be the same structure and not two caches — a second cache keyed
differently is precisely how a stale subtree survives a change, and how 44
addresses went missing on archive.org.

## 7. Flyweight the strings

Absolute xpaths through four shadow roots run ~200 bytes and share nearly all
their prefix. Fifty in one delta is 10 KB of repeated text.

- **Intern the segments**: a `Map<string, int>` of path segments, and emit
  paths as integer arrays with a dictionary sent once.
- **Or emit relative-to-chunk** paths plus the chunk's own absolute root — the
  addressing scheme already nests this way.

Both shrink the payload by an order of magnitude on delta-heavy pages, and the
dictionary is itself incremental.

## 8. Keep object shapes monomorphic

Hot paths — the per-node record, the delta event — should be constructed with
the same fields in the same order every time, so the JIT keeps one hidden
class. Conditionally adding a field (`if (x) obj.extra = …`) makes the shape
polymorphic and de-optimises every consumer of that object. Initialise all
fields, use `null` for absent, and never `delete`.

Counters and digests belong in typed arrays (`Uint32Array`) rather than plain
objects when they are per-node and numerous.

## 9. The module boundary

One IIFE, one returned handle, everything else closed over:

```js
(() => {
  const state = new WeakMap();
  const dirty = new Set();
  const observers = new Map();          // root -> MutationObserver
  function drain() { … }
  function stats() { … }
  return { drain, stats };              // the only reachable surface
})();
```

The returned object is the *entire* API. Nothing else is nameable from the
page, which is what makes the sensor invisible (see `JS_INJECTION.md` §2.1 for
where that handle is parked, and why one hidden property is the floor).

## 10. Idempotence as the correctness discipline

Every repair must be safe to run twice. Mutation delivery is at-least-once in
practice — a re-injection after navigation, a drained-but-unacknowledged
batch, a repair interrupted mid-generator — and an algorithm that assumes
exactly-once silently drops or doubles content.

Concretely: repairing a chunk root recomputes that chunk's whole record from
the DOM rather than applying a diff to a previous record. Recompute-from-source
at a *small* scope is both idempotent and cheap; diff-application at a small
scope is neither, because it inherits every earlier error.

---

## 11. What these patterns say to change

| current | pattern | effect |
|---|---|---|
| three traversals (digest / chunks / Python re-parse) | §1 tupling | one walk, no disagreement |
| `data-vertiscope-hash` written into the DOM | §2 WeakMap | genuinely passive |
| `Array.from(childNodes).map(extract)` recursion | §3 TreeWalker | no per-node allocation, no depth limit |
| delta queue drained by copy | §4 double buffer | O(1) drain |
| repair inline in the callback | §5 idle + generator | no competition with page render |
| absolute xpath strings per detection | §7 interning | order-of-magnitude smaller deltas |
| `window._wfhEngine` fixed public name | §9 closure + hidden handle | undetectable, collision-free |

None of these are refactors for tidiness. Each removes a specific cost that
was measured, or a specific way the current design can silently lose content.
