# Second-pass formulations

Ten mechanisms, each stated as a complete design. They compose: the rank
spine (§1) supplies the order statistics that §2, §3 and §5 consume, and the
transport (§10) carries whatever the others emit.

---

## §1 Rank-spine fold

Every element maintains its children not as a flat list but as a balanced
aggregation tree — a spine — whose internal nodes carry two summaries: the
combined digest of the children beneath them, and their count.

The spine is the element's record; the DOM's own child list is never
re-enumerated once the spine exists.

**Three queries, all logarithmic in fan-out.**

- *digest* — the spine root's combined value, recomputed on a child change by
  updating only that child's path through the spine.
- *ordinal* — a node's positional index is a **rank query**: sum the counts of
  spine subtrees to its left. The xpath ordinal is therefore computed, never
  counted and never stored.
- *insertion* — splices one leaf and refreshes the spine path above it.

The ordinal-as-rank-query is what makes the spine worth its bookkeeping. A
document with a ten-thousand-child feed container answers "what index is this
node" in fourteen steps, and answers it *the same way* before and after any
insertion, so nothing downstream holds a number that a later insert falsifies.

Fan-out and depth become independent cost axes: a change costs
`O(depth · log fanout)`, and both factors are observable, so the harness can
report them separately rather than reporting a single opaque repair cost.

## §2 Budgeted chunk B-tree

Chunks behave as the leaves of a B-tree over the document, governed by a fill
discipline rather than a boundary computation.

- A chunk holds content up to `budget` characters.
- On overflow it **splits**: its children become chunk roots in document
  order, each inheriting the parent's address prefix.
- On underflow it **merges** with its next sibling chunk when their combined
  content fits.

The fill band is asymmetric: split at `budget`, merge only below `budget/2`.
That hysteresis means a container growing one node at a time crosses a
boundary once and then stays put, so the emitted chunk set is stable under
steady growth and each delta names a small, bounded set of chunk ids.

Chunk identity is the identity of its root node. A split emits one `removed`
and several `added`; a merge emits several `removed` and one `added`. Both are
expressible in the same delta vocabulary as an ordinary content change, so a
consumer needs no separate notion of restructuring.

## §3 Dual fingerprint

Two independent summaries per node, each answering one question.

**Content fingerprint** — a multiset hash over the node's tokens and its
children's fingerprints, combined by an operation that is commutative and
invertible (addition in a large prime field, with each token mapped through a
random-looking function of its bytes). A child's change updates every ancestor
by subtracting the old value and adding the new, touching nothing else.

**Structure digest** — the spine's combined value from §1, which is
position-dependent by construction.

The pair separates *what is present* from *in what arrangement*. Reordering a
list changes the structure digest and leaves the content fingerprint fixed,
which is exactly the signal a consumer wants when deciding whether to
re-extract text (no) or re-emit addresses (yes).

The content fingerprint's invertibility is also what makes containment cheap:
the fingerprint of a subtree is the sum of its parts, so asking whether one
node's content is wholly accounted for by another is arithmetic on two numbers
rather than a traversal.

## §4 Layered address with provenance

An address segment is chosen from an ordered preference list and **records
which layer produced it**:

1. `id`, when present and syntactically stable;
2. a designated stable attribute (`data-testid`, `data-key`, …);
3. a hash of the node's own content fingerprint (§3);
4. the rank from the spine (§1).

A full address is a path of such segments, each tagged with its provenance,
plus the rank of every segment as a tiebreak field. Where two siblings would
otherwise produce identical segments, rank distinguishes them, so uniqueness is
guaranteed by construction at every layer.

Provenance is a first-class part of the address because it states the
address's **durability class**:

| grounded in | durable across |
|---|---|
| `id` / stable attribute | sessions, re-scans, site redeploys within reason |
| content hash | as long as the content is unchanged |
| rank | the current session's view of the document |

A store can therefore decide what to persist as a long-lived key and what to
treat as session-local, and retrieval can prefer durable addresses when
linking. The distinction is available without any extra analysis because the
addressing already knows it.

## §5 Span coalescing

The dirty set is expressed as **spans** — `(parent, firstRank, lastRank)` —
rather than individual nodes.

When a mutation names inserted or removed nodes, their ranks bound a span.
Adjacent and overlapping spans under the same parent merge on insertion into
the set; a span whose parent is already covered by an enclosing span is
absorbed.

A feed appending two hundred articles produces one span. A framework
re-rendering a table's body produces one span. Repair then walks each span
once, in document order, and the number of repairs is a function of how many
*regions* changed rather than how many nodes did — which is the quantity that
actually stays small on real pages.

Spans also give the scheduler a natural unit of interruption: a repair can
process spans one at a time and yield between them, with the untouched
remainder still exactly described.

## §6 Cache-consulting walk filter

Traversal runs through a native tree walker whose filter is the place
incrementality is enforced.

For each node the filter consults the record cache and returns one of three
verdicts:

- **reject** — the subtree is provably irrelevant: a script, style, or
  template element, or a node whose cached record is present and whose parent
  reported no dirty span covering it. The walker skips the entire subtree
  without entering it.
- **skip** — the node itself emits nothing but its descendants may: structural
  wrappers with no own text.
- **accept** — fold this node.

Because the walker evaluates the filter in the engine, a clean subtree costs
one filter call rather than a traversal, and the cost of a repair is
proportional to the dirty region even though the walk is expressed over the
whole root.

The filter is also the single place where "what counts as content" is decided,
so the detection rules live in one function that the traversal consults, and
adding a rule cannot accidentally introduce a second pass.

## §7 Sketch-then-verify dedup

Each record carries a small fixed-width count sketch of its tokens —
a few dozen counters, updated by the same fold that produces the fingerprint.

Deduplication is a two-step test, applied between a node and the nearest
ancestor that emits:

1. **sketch test** — is every counter in the child's sketch matched by the
   ancestor's? A handful of word-wide comparisons, no strings touched.
2. **exact confirmation** — only for nodes the sketch admits, compare the
   actual token multisets.

The sketch's job is to make the exact test rare, and the exact test's job is
to make the decision correct, so suppression only ever happens on verified
containment.

Counts rather than membership means multiplicity survives: a node repeating a
word three times is not covered by an ancestor that says it once. Scoping the
comparison to the nearest emitting ancestor keeps every sketch sparse and
bounds the memory per node to a constant, independent of document size.

## §8 Independent oracle reading

A second, wholly separate reading of the document is available on demand:
the browser's own composed-tree serialization, taken in one call, parsed
without reference to any cached state.

This reading is the equivalence check every incremental mechanism ships with.
Periodically — every *n*th repair, at scan end, and on demand from the harness
— the maintained state is compared against a reading produced this way, and
the comparison is reported as a first-class metric rather than an assertion
that merely passes silently.

Because the oracle shares no code with the incremental path, agreement between
them is evidence rather than tautology. It is the mechanism that lets an
incremental design be trusted at scale: the harness can report, per page,
whether the fast path and the independent reading agree, and the rate at which
they do is a headline number for any candidate.

## §9 Monotone pattern overlay

Structural chunking (§2) is the substrate and runs at mutation speed. Pattern
knowledge is an **annotation** layered over it, produced asynchronously.

As chunks accumulate, a generalisation step groups them by the shape of their
address paths and, for each group, identifies the field slots that recur
across members — a title-bearing slot, a link slot, a content slot. Groups
whose members all resolve every slot are promoted to patterns; the annotation
attaches a pattern identity and a slot map to each member chunk.

The annotation is **monotone**: a chunk begins unannotated and correct, and
later gains a pattern label that refines how it is rendered, grouped and
ranked. Nothing already emitted becomes wrong when an annotation arrives, so
the overlay may run arbitrarily late, in batches, at whatever cadence its cost
allows.

Consumers read the annotation when present and the structure when not, which
gives a graceful ladder: a page seen once renders structurally; a page seen
repeatedly, or a site with many similar pages, renders with its patterns
recognised, its navigation furniture grouped away, and its records aligned
into fields.

## §10 Versioned append-only dictionary transport

Path segments, tag names and attribute names are interned to integers in the
page. Deltas carry integer arrays.

The dictionary is append-only and versioned: every payload begins with any new
entries it needs, followed by the delta that uses them, followed by the
dictionary version after those additions. A receiver holding version *k* that
receives a payload built on *k* applies it directly; one that receives a
payload built on *k+j* it never saw requests a resync and is sent the missing
range.

This makes a delta stream self-describing and replayable. A consumer can be
restarted, a worker can be lost mid-sweep and resumed, and a recorded stream
can be replayed offline against a new consumer implementation — which is what
allows one captured run to evaluate several downstream designs without
re-driving the browser.

The size effect is substantial on pages with deep shadow nesting, where paths
share long prefixes and the same few dozen tag names recur throughout: the
dictionary converges quickly and the steady-state payload is integers.
