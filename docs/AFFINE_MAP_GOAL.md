# The affine map — standing goal

**Set 2026-08-27. Binding. This supersedes the variant-benchmark framing as the
project's purpose.** The percentage detection rates (search 64.4%, pagers 44.2%
over 1,721 pages) are not the objective and were never the objective; they are
a property of one subsystem.

## The user's statement, verbatim

> The main goal here, remember, is for this 'sensor' to be a generalized map of
> the shadow DOMs. I don't think we are focused on these percentage detections
> you're showing me because what we are really trying to do, remember, is to
> treat this rendering as a kind of full affine map from the original shadow DOM
> to its distilled, traced, and interactable state in the REPL. What that means
> is we generalize our structures to what interactive elements themselves are
> detectable, how they relate to the rest of the web structures, and the
> resultant fields that are likewise interactable in the REPL. So what we see in
> the webpage is essentially what we get in the REPL. So these shouldn't at all
> be 'commands.' We'll leave this be for now, since it's cool, but we will focus
> on the stated task now as our true goal. To get a universal scrape-renderer and
> building in chunking and vectorization asyncronously from the overall recursive
> algorithm that obtains our patricia-trie on generalizable
> url:xpath:markdown:content. Ideally, remember, we render the markdown as if it
> were the structure of the page that embeds markdown and interactive wireframes
> as ascii in the REPL. These two fuse to reconstruct the distilled and full
> shadow DOM of the page with all content correctly deduplicated, tracked,
> updated, all in millisecond range and in O(delta) (perhaps timings on both the
> page-size mutation-chunking algorithm and embedding async phases separately and
> also total runtimes). Also please include some form of metrics from our
> chunking/deduplication/hashing/etc algorithms that you have applied. Please
> find some dimensions of our algorithms that can be reliably measured from our
> algorithms such that they are clearly resolvable, expressive of cause and
> effect, and discriminate between true and false positives and negatives (some
> form of confusion matrix that could be extracted, especially for totality of
> coverage from the original and deduplication correctness measures). I'm not
> sure how we could measure that, unless there are clearer ways of
> straightforward analytics we can obtain from this. A micro-but-powerful sensor.
> From now on as well, make sure these analytics are tracked seperately than the
> REPL tool, in their own artifacts. Please remove the parts of the REPL that do
> not cover our concern. Don't get too worried about removing things that I said
> was cool either, because as previously stated, our current approach intends to
> properly realize the REPL as an interactive web browser brought into the lo-fi
> and configurable for small language model context windows. Be most careful
> about our current focus and work in terms of quality, completeness, attention
> to detail, empricism, provability, repeatability, edge case defintions from
> theoretical constraints and analyses on the code, and try to realize this
> prompt to code as best you can from our current codebase and context. We want
> you to get to the point where this is fully proven. This should be made a
> constraint: Keep working towards this central goal until the following is fully
> satisfied by yourself, and always persist this prompt throughout our compacting
> contexts such that this prompt is continuously persisted through one giant goal
> that you self-organize and manage yourself on. Make sure that whenever you make
> a code update, you always refer to it in terms of interactions from and to the
> patricia trie as a universal link structure between the REPL data structure
> interfaces with the web page that are reflected throughout the process and are
> a central point of accessibility constraint requirements on our codebase.

## What the words are taken to mean

**Affine map.** The rendering is a structure-preserving map from the page's
composed tree to the REPL's rendering. "Affine" is read as its load-bearing
consequence rather than as linear algebra: *relations are preserved, the origin
is not.* Reading order, containment depth, and the grouping of a control with
the content it governs survive the map; absolute pixel geometry does not.

**The patricia trie is the map.** It is the universal link structure joining the
REPL's data-structure interfaces to the web page, keyed on
`url : xpath : markdown : content`. Every code change is described in terms of
what it does to, or reads from, the trie. A change that cannot be stated that
way is a change that has left the map.

**Not commands.** The REPL is an interactive web browser, lo-fi and configurable
for small-language-model context windows. Interactive elements are *fields* the
reader acts on in place. A verb the reader must type is a failure of the map,
not a feature of the tool.

**Asynchrony.** Chunking and vectorization run off the recursive trie
construction, not inside it. The trie recursion is the synchronous O(delta)
path; embedding is a consumer of it. The two are timed separately because they
are separately answerable.

### The projection is the other half of O(delta)

The trie applies a mutation in O(delta). The markdown is *read back out* of it,
and for a long time that read was O(page) -- so the pair was O(page), and the
O(delta) claim described a component rather than the sensor.

The trie now carries two Merkle hashes over every subtree, for two different
equivalences, both maintained in one bottom-up pass:

- `subtree_hash` folds in `content_hash`, the hash of a value's normalized
  token multiset. Blind to word order, case and punctuation *by design* --
  that blindness is what lets `apply` recognise a paragraph that moved.
  It answers **"is this the same content?"**, and re-anchoring depends on it.
- `exact_hash` folds in the exact value and the full address. It answers
  **"does this draw the same?"**, which is the question a projection has to
  ask, because it prints values verbatim: `"a b"` and `"b a"` share a
  `content_hash` and render differently.

A projection memo keyed on `exact_hash` may reuse a subtree exactly when the
trie says that subtree is unchanged.

The memo was half the answer. The other half was that the descent asked each
ancestor of a change whether *its* subtree fits the context window, and
answered by rendering it -- at the page root, the page. That question is now
answered from the children, which the descent measures anyway and mostly gets
back from the memo. The argument is structural: **every rendering decision is
scoped to a single element** (`_dedupe` groups units by `addr.xpath` and
compares only within a group; the rule letting a control consume its own label
is keyed the same way), so nothing in one subtree can remove anything in
another and the parent's rendering contains every line its children render.
With depths absolute and `chars` being `len("
".join(lines))`, that gives

    parent_chars  >=  sum(child_chars) + k - 1

which is a *lower* bound, and a lower bound is what proves "this overflows".

`_size_of` applies that recursively: proving a stale ancestor overflows costs
lookups down to the first cached size instead of a render. Without it the path
from an edited leaf to the page root drew the same subtree once per level --
profiled at five whole-page walks to redraw a page after a one-word edit.

### Three reads the write should have been doing

With the renders gone, what was left was profiling as three walks of the whole
page that ran on **every** render whatever had changed — all of them
re-deriving something the trie already knew when it was written:

- `AddressTrie.urls()` visited every leaf to learn one string. It is now an
  insertion-ordered set maintained by `insert`, put back into the trie's own
  order when there is more than one page (arrival order interleaves pages that
  a leaf walk grouped by origin).
- The absolute xpath of every element was cached by a walk before each render.
  `insert` computes that exact prefix while building the path, so it assigns
  it when it creates the node — which is also the truer statement: a node's
  xpath cannot change, because a segment and its ancestors are fixed for its
  life. Content "moving" here is content arriving at a *different node*.
- `TrieNode.ordered_children()` re-sorted, with a regex in the sort key, every
  time any walk asked any node for its children. It is memoised against the
  child count, which is the whole validity check and is sound rather than
  convenient: children are only added or dropped, never replaced, and
  `doc_pos` and `label_order` are set at construction and never assigned
  again, so nothing can reorder a child list while its length is unchanged.

Each is a claim of *equality* with the walk it replaced, so each is tested
against that walk as a reference implementation — on the fixture pages, on
generated shapes, and across live edit/insert passes.

### What it costs now

`analytics/projection.py` measures it, browser-free, by change kind. At a
1,200-character window, in milliseconds, against where this started:

| change | | N=100 | N=400 | N=1600 | N=6400 |
|---|---|---|---|---|---|
| redraw (nothing changed) | was | 46 | 175 | 1844 | |
| | now | 0.2 | 0.7 | **3.3** | 16.1 |
| edit one value in place | was | 48 | 177 | 1819 | |
| | now | 0.6 | 2.0 | **9.0** | 37.6 |
| insert one node at the head | was | 44 | 179 | 1827 | |
| | now | 11.2 | 47.5 | **243** | 804 |

A redraw is what a scroll and an idle tick cost: 16 ms for a 25,602-line page,
0.6 µs per line.

Read honestly, this is **still linear in the page, not in the delta**, and the
residual is located rather than guessed at:

- A **redraw** is nearly free because the page root is clean and one hash
  comparison answers for the whole page.
- An **edit** is close behind. The term left is the one ancestor whose
  children *are* the chunk boundaries: it consults all N of them and re-runs
  its merge buffer. That is a real dependency — one child changing size can
  move every boundary after it — so removing it means splicing the buffer
  around the changed child, which needs its own soundness argument rather than
  a heuristic.
- An **insertion at the head** is the floor, and not a defect. It shifts the
  address of everything below it, and the projection prints addresses: a
  chunk's xpath, a line's anchor. What moved genuinely draws differently. The
  trie keeps identity across the shift (`uid`); the render cannot inherit it.

The same element-scoping argument gives a matching *upper* bound,
`own + sum(child_chars) + k - 1`, which is exactly tight where it holds and
fails in exactly one place: `_collect` carries a heading label into child
elements, so a heading whose words live in child elements draws them as a
heading from the parent and as plain text from the child. That exception is
pinned by a test rather than left as a comment, because the label inheritance
it protects is what stopped 124 of the Guardian's 181 headlines arriving as
ordinary text.

Two preconditions had to hold before any of this was sound, and both are
statements about the trie as the universal link structure:

1. **Nothing in a chunk may be a function of its position.** Chunk ids carried
   the chunk's global emission ordinal, so a cached subtree could not be
   spliced in anywhere. `_number_parts` makes the ordinal a property of the
   (url, xpath) group instead.
2. **The invalidation signal has to be strict enough to stand behind
   "identical".** `subtree_hash` is not, and using it would have served a
   stale render after any reformatting edit. `exact_hash` exists for this.

Every trial checks the memoised render against an unmemoised one on the same
trie and records `identical`; the table prints a banner if it ever disagrees.
A speed column without that check measures nothing.

## The measurement theory

The user asked for dimensions that are "clearly resolvable, expressive of cause
and effect, and discriminate between true and false positives and negatives",
and said plainly they were unsure how to measure it. The framing below is
proposed as the answer, and is falsifiable on its own terms.

### The map's three failure modes

An affine map from page units to rendered units should be **injective on
addresses** and **surjective onto drawn content**. Both properties are
mechanically checkable, and every rendering defect seen in this project so far
is a failure of one of them:

| property | failure | what it looks like | seen as |
|---|---|---|---|
| surjective onto drawn content | **loss** (FN) | a thing on the page absent from the render | images with `alt=""`; nested link targets |
| injective on addresses | **duplication** (FN′) | one page unit rendered twice | `[/tag/love/]` beside `[love]` |
| well-defined (no phantoms) | **invention** (FP) | a rendered unit with no page origin | filled slots emitting their fallback |

`TN` is not a residual to be padded out. It is the content the map is *correct
to omit*: `display:none` runs absent from the wireframe, closed-root content
reported unreachable rather than read as empty, redundant spellings of one thing
collapsed to one. A metric that cannot score a correct omission cannot tell a
faithful renderer from a verbose one.

### Why a naive coverage number is not this

Four separate times, a correct renderer was scored as broken because the
denominator did not match what that renderer is for: hidden content scored
against a drawing; case-sensitive matching against a renderer that uppercases
bold; hrefs scored against a projection that strips hrefs by design; unwrapped
strings scored against a wrapping layout. **A coverage number is a claim about
the renderer and a claim about the denominator, and only one of them was being
checked.** Every dimension defined here names its denominator explicitly, and
the denominator is part of the metric's identity.

### Deduplication as a decision problem

Dedup is where the confusion matrix earns its keep, because both errors are real
and they point in opposite directions:

- **over-dedup** — distinct page content collapsed into one. This is *loss*, and
  it is the dangerous one: a suppression rule once made every search-result
  title vanish because an href was hidden on the grounds that "the anchor
  speaks" while the words were consumed on the grounds that "the link will draw
  them".
- **under-dedup** — redundant content emitted more than once. This is *noise*:
  survivable, measurable, and the failure a naive "keep everything" policy
  guarantees.

A single "dedup rate" cannot separate these. Two counts can, and their ratio is
the tuning knob the suppression rules are actually setting.

### What a change costs the asynchronous phase

Vectorisation runs off the trie recursion rather than inside it, so its cost is
a separate question from the render's, and `analytics/projection.py` reports
it: how many chunks come out holding markdown no chunk held before, which is
what the embedder would have to do.

The greedy merge accumulated siblings until the context window was crossed. It
packs the window well and has one bad property: a boundary is a function of
everything before it, so inserting one sibling shifted every boundary after it
and the phase never came back. Every downstream chunk genuinely held different
text — an O(page) cost for an O(1) change.

**Content-defined boundaries.** The cut now fires with probability
`piece_chars / window` from a hash of the piece's own rendered text, so the
expected content between cuts is one window's worth with nothing to tune, and a
boundary cannot be moved by an insertion that does not touch it.

| chunks holding new text | N=1600 | N=6400 | N=25600 |
|---|---|---|---|
| running total | 177 | 711 | 2844 |
| content-defined | 3 | 3 | 3 |

Constant in the page against linear. Driven end to end through `VectorQueue`
against a counting embedder, an insertion at the head asks for **4 embeddings
at 400 rows and 4 at 25,600** — a page of 3,182 chunks. Coverage and deduplication
are untouched: over the fixture pages both modes emit the same 365 lines with
the same 365 unique anchors and the same dedup tally, no chunk over the window,
nothing addressed twice. The price is packing — about 10% more chunks at a
median a few percent smaller.

Two things had to be got right, and the first was got wrong first:

- **The oracle must be address-free.** `TrieNode.exact_hash` was the obvious
  choice and is the wrong one: it folds in the node's address, so an insertion
  changes every sibling's hash and no boundary survives. Measured — the ratio
  did not move off 1.0. `subtree_hash` fails identically, its Merkle folding in
  a segment that carries the sibling ordinal. The rendered text is what a
  boundary should depend on, and it is what decides whether a chunk needs
  embedding at all.
- **The fill threshold is a trade.** It reads the running total, so it is the
  one accumulation-dependent input left. At 0.65 the packing is better and most
  cuts become window cuts again: on a middle insertion into variable-length
  rows the new-text count went from 1 to 30, worse than what it replaces. 0.5
  is where it stops spending more than it buys.

**Identity churn, and why it is not fixed by re-keying.** `VectorQueue` gates
on `cid`, and a cid is address-keyed (ERRATA B12) so it churns when an
insertion shifts the addresses below it: a chunk can arrive with a new id
carrying text embedded an hour ago. Identity is right to be address-keyed — a
content key collapsed 18.8% of instances on the 54-page corpus, the address
collapses 0% by construction. So the queue keeps a bounded digest→vector cache
instead: an embedding is a function of its text, so serving the second
occurrence from the first is exact rather than approximate. Whether it fires
depends on the page — on some shapes the cid gate already catches everything —
which is why it is tested directly rather than through a page.

**A boundary is persisted the moment a chunk id is written down.** The oracle
must therefore be stable across processes, and the first version was not: it
used Python's `hash`, which is randomised per process, so the same page chunked
differently under different ids on every restart and a stored index would
disagree with the next scan. It surfaced as a test that passed alone and failed
in the suite. The oracle is now a CRC, checked by rendering the same page in
subprocesses under three different `PYTHONHASHSEED` values and requiring one
answer.

### What real pages said that the fixtures did not

Every O(delta) number above was measured on an N-row list built to be measured.
That is the right way to see a *shape* and the wrong way to believe one: a list
of identical rows is the friendliest possible input to every algorithm here.
`analytics/live_delta.py` asks the same question of real documents — it finds
each page's largest repeated-sibling group with no per-site rules, inserts one
minimal node at its head, and scores both chunking modes against the trie's own
delta.

It found three defects in the move decoder within the first run, none of which
the fixture could show, all of which made the trie **write content at paths the
document does not contain**:

1. The old root came from the common prefix of a chunk's addresses, cut back to
   the last "/" unconditionally. Right when the prefix stops mid-step ("li[1]"
   against "li[12]"), wrong when it is already a whole step — which is the case
   whenever a chunk has a unit addressed at its own root, an href or an
   aria-label on the element itself. Every rebuilt address gained a spurious
   step; quotes.toscrape.com went 176 leaves → 317 for one inserted node.
2. The move entry names the node that moved, while a chunk's addresses hang off
   whatever is inside it. On books.toscrape.com the entry named the `li` and
   the addresses hung off the `article` within, so the substitution dropped the
   `article` step: 60 of 60 sampled paths matched zero nodes.
3. Deriving the old root from the address makes it a prefix by construction, so
   the `startswith` guard could never fail and an address in another branch was
   rewritten onto the moved node. Caught by a test rather than by a page.

After all three, 0 of 60 sampled paths are missing from the DOM on all three
pages, and books' genuine-change count for one inserted node went from 191 to 1.

Both findings that run produced turned out to be **one defect in the receiver,
not two in the fold**, and a correction to what I first said about them.

`apply` recovers a shift the fold did not report by re-anchoring on content
hash, bounded to the spans the drain touches — which is what keeps that
recovery proportional to the change. A move *between parents* is outside that
bound: the old leaf lives under a span no incoming unit names, so its uid is
never offered to the address that now holds its content. The consequences were
the two things the harness flagged.

- The trie only ever grew. Content was written at its new address and left at
  its old one, because the DOM removed nothing and so the drain reported no
  removal: 176 addresses → 209 on quotes.toscrape.com for a delta of 1,
  dropping none.
- On news.ycombinator.com the same insertion read as **654 genuine changes**. I
  recorded that as the fold failing to recognise the shift. That was wrong —
  the fold reported 662 moves; the receiver was discarding them, so every
  moved unit was written as a fresh arrival.

A reported move is now authoritative: the uid travels with the content, and the
address it left is vacated. Vacating is deliberately *not* counted as a
removal — a move is not an edit, and the address is already in `delta.moved`;
counting it twice would make one node arriving look like a page rewriting
itself, which is the figure the whole mechanism exists to avoid.

One subtlety cost the last four identities. Where the value arriving at an
address is the value already there — `by`, `(about)`, `Tags:`, the labels that
repeat on every card — the write is a no-op, so the reported uid was dropped
while the source address was vacated. Every uid is snapshotted before any
write, so handing it forward on a no-op is safe, and the chain of identical
values passes identities along it.

One inserted node, measured after the fixture and on four real pages:

| | delta | uids lost | addresses |
|---|---|---|---|
| flat-list fixture | 1 | 0 | 101 → 102 |
| quotes.toscrape.com | 1 | 0 | 176 → 177 |
| books.toscrape.com | 1 | 0 | 321 → 322 |
| news.ycombinator.com | 1 | 0 | 715 → 716 |
| lit.dev | 1 | 1 | 549 → 614 |

lit.dev was not yet right — 65 addresses gained, none dropped — and neither
guess about why was correct. A **null control** settled it: drain the page
after settling, same wait, no mutation. It gained 0 addresses, so the page was
not hydrating; and none of the gained addresses were inside a shadow root, so
it was not a shadow-root reporting gap either.

What it was: the fold reports a move only when the chunk holding it is
otherwise unchanged. Where the chunk *did* change — the common case for the
chunk an insertion lands in — it re-sends the shifted content as ordinary
units and names no move at all. On lit.dev the drain carried 185 units and
zero moves. `apply` recognised every one of them by content hash and carried
its uid, and then nothing vacated the addresses they came from, because the
vacate rule only applied to *reported* moves. An inferred move now vacates its
source on the same terms.

One inserted node, after that:

| | delta | uids lost | addresses |
|---|---|---|---|
| flat-list fixture | 1 | 0 | 101 → 102 |
| quotes.toscrape.com | 1 | 0 | 176 → 177 |
| books.toscrape.com | 1 | 0 | 321 → 322 |
| news.ycombinator.com | 1 | 0 | 715 → 716 |
| lit.dev | 1 | 0 | 549 → 551 |
| www.salesforce.com | 1 | 1 | net +0 (29 gained, 29 dropped) |

salesforce.com was the one page still looking wrong, and two methodological
faults were doing it rather than one sensor defect.

The harness chose the page's largest repeated group with no filter, so on
salesforce it inserted into a run of **17 `<script>` elements**, and on lit.dev
into a group of `<pre>` code samples. Neither is the page's list, and neither
is content a reader ever sees. The group must be drawn and must not be one of
the tags that hold text without being content.

And one run of a live page is evidence of nothing. salesforce answered **341**
chunks of new text in one run and **10** in the next, for the same mutation a
minute apart. The harness now repeats each page and prints the range beside the
median, so a page that does not reproduce says so rather than contributing a
figure that looks like a measurement.

With both fixed, three runs per page, one node inserted into each page's
largest *drawn* repeated group:

| page | group | chunks | delta | moved | new text |
|---|---|---|---|---|---|
| quotes.toscrape.com | div ×10 | 8 | 1 | 140 | 1 [1–1] |
| books.toscrape.com | li ×20 | 28 | 1 | 200 | 1 [1–1] |
| news.ycombinator.com | tr ×92 | 24 | 1 | 662 | 1 [1–1] |
| lit.dev | a ×14 | 30 | 1 | 84 | 1 [1–1] |
| www.salesforce.com | div ×16 | 347 | 1 | 40 | 6 [6–6] |

salesforce is also the page the control arm earns its keep on: it reports
**delta 45 and +41 addresses before anything is inserted**. It rotates its own
content between two visits, which is what the 341 was. Once that is visible and
labelled, its insertion costs a delta of 1 and six chunks, reproducibly.

Inference recovers the shift but not the accounting as tightly as a report
does: a label every card repeats has no *displaced* source when only one card
arrives, so it reads as an arrival rather than as movement. That is why the
reported channel is worth having even though the inferred one is a safety net.

The control arm is now part of the harness. A page that hydrates late is
otherwise indistinguishable from a sensor that mishandles an insertion, and I
spent an iteration believing the wrong one of those.

### A corpus I did not pick

Every live number above came from pages I chose. `tests/corpus/` holds ~130
pages frozen by an earlier pass for *structural* variety — wikis, docs, forums,
news, standards, government, right-to-left and CJK scripts, table-heavy and
deliberately-minimal layouts. `--live-delta --corpus` loads each from disk and
mutates it in a real browser, so the fold and the MutationObserver path are the
live ones and only the document is fixed. Frozen is the point: a benchmark
against the internet measures the internet's variance rather than ours and
cannot be replayed.

It found, in the first eight pages, what five hand-picked LTR sites could not.

**Vacating a moved-from address is wrong, and I had to take it out.** The rule
was: content moved away, this drain does not claim the old address, so the old
address is empty. On a flat list that is exactly right — every vacated address
is immediately reoccupied by its neighbour — and four real pages agreed. Arabic
Wikipedia did not: 11,793 leaves, 151 list items, one inserted node, and the
trie *shrank* by 84 addresses while losing 85 identities. Of 60 addresses the
rule wanted to drop, **47 were still in the live DOM**.

The premise was false. The fold does not re-send content the receiver already
holds, so its silence about an address is the absence of evidence, not evidence
of absence. A stale address is a real defect — the trie grows while the page
does not, and the harness reports it per page. Deleting content the page still
has is a worse one, and silent.

What survives is the identity carrying, which is sound and independent: it took
news.ycombinator.com from 654 genuine changes for one inserted row to 1, and
Arabic Wikipedia from 148 to 1.

### The open defect, stated with its size

The corpus was run whole, 136 pages, on an idle machine. 121 were measurable;
14 have no drawn repeated group to insert into and 1 errored.

| | value |
|---|---|
| delta == 1 for one inserted node | **112 of 121** |
| worst delta | 66 |
| trie grew | **88 of 121** |
| net addresses added, median | **+25** (range +1 … +1841) |
| pages that lost an identity | 47 |
| chunks holding new text — median / p90 / max | 5 / 107 / 746 |

The trie's *change accounting* generalises: one node reads as one change on 93%
of pages nobody chose for the test. What does not generalise is that **the trie
grows**. Content is written at its new address and the old one is never
vacated, so on two-thirds of real documents the map accumulates addresses the
page no longer has.

**Closed, by asking the page.** The fold exposes `alive(paths)`: given the
addresses the receiver holds, it walks each back to a node in the *composed*
tree — crossing shadow boundaries, which no XPath engine will do. When a move
leaves a source orphaned (no other chunk moved into it, no unit re-states it),
the fold is asked about it once, in a batch. A path that no longer resolves is
a removal, and it is the only sound one available. A path that still resolves
is left alone: it holds something, this pass does not know what, and saying
nothing is the honest answer until the value can be re-read.

Across the 121 measurable corpus pages:

| | before | removals as edits | movement not an edit |
|---|---|---|---|
| delta == 1 | 112 | 21 | **112** |
| trie grew | 88 | 31 | **31** |
| shrank | 0 | 4 | 4 |
| lost identities | 47 | 63 | **26** |
| net addresses, median | +25 | +2 | **+2** |
| net range | +1 … +1841 | −49 … +595 | −49 … +595 |
| new text median / p90 / max | 5 / 107 / 746 | 2 / 47 / 438 | **2 / 47 / 438** |

The middle column is why the last one exists: a verified removal is still
*movement* when it is the far side of a reported move, and counting it as an
edit made one inserted node read as a page rewriting itself. The content did
not leave the document; it changed address, and the destination is already in
`delta.moved`.

Per-page, over ten successive mutations, staleness now grows at one address per
mutation rather than five to twenty:

| page | stale 1 → 10, before | after |
|---|---|---|
| blog.codinghorror.com | 5 → 50 | **1 → 10** |
| quotes.toscrape.com | 32 → 198 | **1 → 10** |
| discourse.julialang.org | 183 → 667 | **49 → 86** |
| ar.wikipedia.org | 1546 → 3863 (at 5) | **965 → 1543** |

### The map, scored against the page, on every corpus document

With a truth map for each page — a second sensor booted on the same live
document and walked whole — the confusion matrix can be taken over the whole
corpus after a single insertion. 119 of 136 pages yield one.

| | before | after |
|---|---|---|
| pages exact (nothing stale, lost or wrong) | 30 | **40** |
| pages holding wrong content at a right address | 43 | **26** |
| wrong-value addresses | 6,622 | **134** |
| pages losing addresses | 33 | **0** |
| addresses lost | 14,502 | **0** |
| addresses stale | 17,409 | **3,864** |
| recall, median / min | 100% / 4.0% | 100% / **100%** |

**Recall is 100% on all 119 pages**: the trie no longer loses an address
anywhere in the corpus.

The cause was a guard I had written myself. `_shifted_xpath` accepted a move
only when the old and new roots differed in their *final* step — which assumed
the node that moves is the one whose ordinal changes. Usually it is not: when a
block shifts, the ordinal that changes sits on an **ancestor**, and
`.../section[3]/ul` becomes `.../section[4]/ul` with everything below riding
along. Those were refused as "a different branch of the document", so the moves
never reached the receiver at all — the fold reported 160 moved chunks on
slashdot.org and 596 on theguardian.com, and the receiver was handed 0 and 27.
Everything downstream then kept the old addresses with the old content, which
is where the wrong values came from.

Every test I had written for that guard put the differing step last, so all of
them passed. The measurement that found it was the fold's own counter
(`movedChunks`) set beside the number of moves the receiver was given: 160
against 0 is not a subtle discrepancy, and nothing had been comparing them.

Per page:

| page | wrong / stale / lost, before | after |
|---|---|---|
| slashdot.org | 260 / 135 / 135 | **0 / 34 / 0** |
| theguardian.com | 594 / 940 / 942 | **0 / 0 / 0** |
| MDN Web/CSS | 260 / 2495 / 2494 | **1 / 0 / 0** |
| de.wikipedia Physik | 242 / 1541 / 1539 | **0 / 48 / 0** |
| rfc-editor rfc2616 | 3019 / 1637 / 1632 | **9 / 350 / 0** |

### Vacating, third time, and this time measured against the right thing

A move's source that nothing else claims no longer holds anything, so the trie
drops it. That rule was written twice before and withdrawn twice, and **both
refutations used the wrong oracle**:

- The first checked the vacated paths with `document.evaluate` and found them
  "still present". An unindexed XPath step matches *all* siblings, and the trie
  writes the first of a group without an index, so it was answering about
  twenty nodes rather than about one.
- The second asked the fold whether a node still existed at the path. That is a
  different question again: a node can exist without the fold emitting any unit
  at that address, and it is the *unit* the map is made of.

The oracle that settles it is a fresh map of the page — a second sensor walked
whole — and against that, vacating is exactly right. It is also only *safe*
now: until moves were delivered correctly, orphaned sources included addresses
whose moves had been wrongly discarded, and vacating those did lose content.
Correct delivery had to come first; the rule was never the problem.

| after one insertion, 119 corpus pages | before guard fix | guard fixed | + vacate |
|---|---|---|---|
| pages exact — nothing stale, lost or wrong | 30 | 40 | **70** |
| pages holding wrong content | 43 | 26 | **25** |
| wrong-value addresses | 6,622 | 134 | **129** |
| pages losing addresses | 33 | 0 | **0** |
| addresses lost | 14,502 | 0 | **0** |
| addresses stale | 17,409 | 3,864 | **241** |
| recall, median / min | 100% / 4.0% | 100% / 100% | **100% / 100%** |

**70 of 119 pages are now exact after an insertion**, recall is 100%
everywhere, nothing is lost, and staleness is down from 17,409 addresses to
241.

### An obsolete guard, and what it was costing

A re-emitted chunk's fresh address set is authoritative for that chunk: an
address it emitted last time and does not emit now is gone. The fold used to
spare such an address whenever its *content* reappeared elsewhere in the same
chunk — a guard written because comparing address sets alone once manufactured
N phantom removals for one node arriving (400 on a 400-item list), which the
trie applied, destroying 399 identities the re-anchor had just preserved.

Two things had since made it unnecessary. A shift within a chunk now travels as
a **move** rather than a re-emission, so the 400-item case reports 400 moves
and no removals at all, with the guard or without it. And `AddressTrie.apply`
skips any removal the same drain contradicts, which is the same protection
stated where the write happens.

What it was costing: on a re-emitted chunk whose addresses shifted, every
departed address was spared and the trie kept it. doc.rust-lang.org held **54
stale addresses against a page with 81**, info.cern.ch 30 against 81, noaa.gov
28 of 357.

| after one insertion, 119 corpus pages | ancestor guard fixed | + vacate orphans | + drop the content guard |
|---|---|---|---|
| **pages exact** | 40 | 70 | **91** |
| addresses stale (pages) | 3,864 (73) | 241 (27) | **3 (1)** |
| addresses lost | 0 | 0 | 4 |
| wrong values (pages) | 134 (26) | 129 (25) | 130 (26) |
| recall, median / min | 100% / 100% | 100% / 100% | 100% / **99.8%** |

**91 of 119 pages are now exact** after an insertion — nothing stale, nothing
lost, nothing wrong. Two pages are imperfect on addresses at all:
data.gov.uk holds 3 stale of 3,092, and w3schools loses 4 of 1,774.

### Matching may be blind; writing may not

`apply` decided "already says this, nothing to write" by comparing
`content_hash` — the hash of a normalized *token multiset*. That blindness is
deliberate and load-bearing for the re-anchor, which has to recognise a
paragraph that moved and was reformatted. It is the wrong test for whether
there is anything to write, because **a value made only of punctuation has an
empty multiset**: `(`, `=>`, `,`, `->` and a bracketed line break all hash to
`sha1("")`. Every change between two of them looked like no change and was
refused.

Syntax-highlighted code is made of exactly those. On php.net's manual page, 30
addresses inside `<pre><code><span>` held one token while the page held
another — and the move channel had delivered the right value to the right
address every time. The write was refused after it arrived, which is why every
earlier diagnosis pointed at the mapping and found nothing wrong with it.

The test is now the exact value. This is the same distinction the renderer
needs between `subtree_hash` and `exact_hash`, arrived at independently in a
second place: **matching is allowed to be blind, deciding whether to write is
not.**

| after one insertion, 119 corpus pages | + vacate orphans | + drop content guard | + exact-value write |
|---|---|---|---|
| **pages exact** | 70 | 91 | **116** |
| wrong values (pages) | 129 (25) | 130 (26) | **18 (1)** |
| addresses stale (pages) | 241 (27) | 3 (1) | 6 (2) |
| addresses lost | 0 | 4 | 7 |
| recall, median / min | 100% / 100% | 100% / 99.8% | 100% / 99.8% |

**116 of 119 pages are exact after an insertion** — nothing stale, nothing
lost, nothing wrong. Across the day the figure went 30 → 40 → 70 → 91 → 116.

Every page that is not exact, in full:

| page | stale | lost | wrong | of |
|---|---|---|---|---|
| coinmarketcap.com | 3 | 3 | 18 | 1,525 |
| w3schools.com forms | 0 | 4 | 0 | 1,774 |
| data.gov.uk search | 3 | 0 | 0 | 3,092 |

### The empty multiset, and the last of it

Writing those values rather than refusing them exposed the same root cause one
level down. `content_hash` is the hash of a token multiset, and the re-anchor
matches on it — so with punctuation-only values hashing alike, it would hand
one token's identity to a *different* token, and the dedup filter pooled every
such value together. That is why the leaves were re-issued.

Blindness to word order, case and punctuation is what lets a paragraph be
recognised after it moved and was reformatted, and it is worth having. But
there is nothing to be blind about in a value with *no tokens*: the multiset
carries no information and the only thing distinguishing them is the text. So
a value with an empty multiset is keyed on its whitespace-normalized string
instead, in a separate namespace so it can never collide with a tokenized one —
still blind to the reformatting the token path is blind to, since collapsing
whitespace is exactly what that does.

`],
    [` still matches `], [`; `buy buy` still matches `Buy  BUY`; `a, b`
still matches `b a`. `(`, `=>`, `,` and `->` no longer match each other.

### Where this leaves the map

| after one insertion, 119 corpus pages | start of the day | + exact-value write | + punctuation-aware hash |
|---|---|---|---|
| **pages exact** | 30 | 116 | **118** |
| wrong values (pages) | 6,622 (43) | 18 (1) | **0 (0)** |
| addresses stale (pages) | 17,409 (84) | 6 (2) | **3 (1)** |
| addresses lost | 14,502 | 7 | **0** |
| recall, median / min | 100% / 4.0% | 100% / 99.8% | **100% / 100%** |

**118 of 119 pages are exact after an insertion** — nothing stale, nothing
lost, nothing wrong, on a corpus selected by an earlier pass for structural
variety and not by me. Recall is 100% on every page. Across the day the exact
count went 30 → 40 → 70 → 91 → 116 → 118.

The single page that is not exact is data.gov.uk's search results: 3 stale
addresses of 3,092.

### Four gestures, not one

All of the above was proved against a single gesture — a node inserted at the
head of a repeated group — and a map that tracks one kind of change is not a
map that tracks change. `--drift --kind` now applies four, each an O(1) edit
the trie should absorb exactly:

- **insert** — a new sibling at the head; every later address shifts.
- **delete** — the first sibling leaves; every later address shifts back.
- **edit** — one text node changes; no address moves at all, so this isolates
  the value path from the address path.
- **relocate** — a sibling moves to the end of its group; two shifts at once,
  with the number of siblings unchanged.

Corpus-wide, one gesture per page:

| gesture | pages | **exact** | stale (pages) | lost | wrong | recall min |
|---|---|---|---|---|---|---|
| insert | 119 | 118 | 3 (1) | 0 | 0 | 100% |
| edit | 113 | **113** | 0 | 0 | 0 | 100% |
| relocate | 117 | **117** | 0 | 0 | 0 | 100% |
| delete | 117 | 113 | 25 (3) | 4 (1) | 10 (1) | 99.9% |

In-place editing and relocation are **exact on every page that supports them**.
Insertion misses one page. The page counts differ because a gesture needs
somewhere to happen: `edit` needs text inside the group, `delete` and
`relocate` need at least four siblings.

**Deletion is the weak gesture**, and it is the one the receiver has never been
asked to do in reverse: 4 pages imperfect, 25 stale addresses on three of them,
10 wrong values on coinmarketcap and 4 lost on the Wikipedia largest-cities
table.

What is established about it, and what is not:

- The drain says **nothing at all** about the stale addresses. On
  archive.org's details page: 0 moves, 0 movedChunks, and all 17 stale
  addresses untouched by units, moves and removals alike.
- They belong to four chunk ids (50, 51, 56, 57) that are **the same before and
  after** the drain and are still claimed by the fold afterwards. So the fold
  believes those chunks are unchanged while their line addresses have shifted:
  the deletion removed `section[2]/div[1]` and the content moved to `div[2]`,
  `div[3]` and so on, with the receiver still holding the old spellings.

Two hypotheses tested and refuted, so the next attempt does not repeat them:

1. *The merged-run gate compares the parent path, so a run shifting inside an
   unchanged parent is skipped.* Plausible, and false here — adding the run's
   own head path to that gate changed the skip count not at all (176 before and
   after), and the residue was identical.
2. *These chunks are id-anchored, and an anchored path is deliberately stable
   under shifts.* Also false: none of the 17 stale addresses is id-anchored,
   and the page's truth map has no id-anchored addresses at all.

The single-chunk gate does compare the chunk's *own* path, which is what makes
insert, edit and relocate exact, so whatever spares these four chunks is
something else again. `discourse.julialang.org`
holds 58 addresses with another row's content and loses 44, and
ar.wikipedia.org loses ~750 — both unchanged by this work and both pre-dating
it. Wrong content at a right address remains the worst class and the next
target.

**Two earlier attempts, both of which deleted live content.**

The first put the rule in the trie: an address whose content moved away, and
which this drain does not claim, is empty. The second put it in the fold, which
seemed sound — every address belongs to exactly one chunk, so an address no
chunk claims after a move is one the fold no longer believes in. Across the
corpus that second version was better on every axis but one: growth 88 → 11
pages, median net +25 → +1, identities lost 47 → 27, new-text p90 107 → 38.

And it shrank 24 pages, so I asked the DOM. Of 60 sampled addresses it removed,
**56 were still in the live page** on one and **47 of 60** on another. The
fold's per-chunk bookkeeping is not a complete model of the page's addresses
either.

So neither side can currently answer "is this address gone?", and both attempts
answered it wrongly in the same direction. That is the architectural gap, and
it is stated here rather than patched, because a stale address is a defect the
harness reports per page while deleting live content is silent. The rule that
would close it needs positive evidence of absence — the fold looking at the old
path and finding nothing — which nothing in the pipeline currently produces.

### Delete, and the three separate things wrong with it

The section above states delete as one defect with one unknown cause. It was
three, and none of them was the mechanism the two refuted hypotheses proposed.
The residue split cleanly by page, which is what eventually gave them away —
one cause per group of pages, not one cause spread thin over all of them.

**1. A chunk root that stopped being one.** archive.org's details page (17
stale) and ncbi (4).

The fold tracks chunk roots in slots and sweeps them on each repair, dropping
any whose node has left the document. A deletion re-splits the budget, so the
chunk boundary moves to a *different node* — and the old slot's node is still
in the page. It is connected, so the sweep keeps it; it is no longer a chunk
root, so nothing ever emits under it again; and its addresses stay in the trie
for the life of the page.

Connectedness was the wrong question. A full repair walk visits every live
chunk root, so a slot the walk did not visit is not a chunk root any more,
whatever its node is doing. Stamping each visited slot with the repair number
and retiring the unvisited ones closed both pages. The soundness condition is
that the walk be *full*, which is why the retirement is skipped under
`subtreegate` — that variant prunes unmoved subtrees, so an unvisited slot
there means only that the pruning worked.

**2. A class that is not a function of the node.** en.wikipedia.org's
largest-cities table: 4 stale and 4 lost, which is the whole of that page's
residue.

The four stale addresses and the four lost ones had **identical xpaths**. They
differed in the accessor: `href|pagination.family/link` against
`href|link.anchor/link`. No address arithmetic was wrong. The node's *class*
had changed, and the class is part of the address.

`numericFamily` decides whether a link is a pager by walking four ancestors up
and counting the anchors under that scope — three distinct members of one
numeric family is a series, two is a coincidence. Deleting one `<li>` dropped
the citation family to two and re-classified the survivors. The survivors did
not change, so nothing marked them dirty, so they were never re-folded, and
`rec.tax` — cleared only at the top of a re-fold — kept the old verdict
permanently.

The gate was innocent, and the measurement that establishes it is the one worth
keeping: with `gate: False`, **all 6,832 units were re-sent and the same four
addresses were still wrong**. That rules out, in a single run, every
explanation that lives in what gets transmitted. The staleness was in the page,
not on the wire.

Two changes, and neither works without the other:

- the fold invalidates cached verdicts in the scope of an anchor change, and
  puts those nodes back in its path so the class is recomputed;
- the class is mixed into `rec.digest`, so a recomputed class is a *reason to
  redraw*. Without it the re-fold produces an identical digest — the value did
  not change — the gate skips the chunk, and the page keeps the fresh verdict
  to itself.

This is rule 5b again, and the sharpest instance of it so far: the digest
answers "does this draw the same?", and the class changes what is drawn, so the
digest must see it. `rec.content` deliberately does not take the class, because
content matching across a move must stay blind to role.

The invalidation is guarded to anchors entering or leaving the scope — or an
`href` being edited, which changes family membership without adding or removing
anything — because only anchors are counted. Without the guard it is a
`querySelectorAll` on every childList mutation a page makes.

It is bounded, not total, and the bound is stated rather than glossed: the
scope is the rule's own four-ancestor radius taken *from the mutation's side*,
which covers a family sharing an ancestor with the change. A link whose scope
reaches the change from further away is not reached. That is named residue.

The mechanism is visibly discriminating rather than a blanket re-send: on the
`relocate` gesture the same page reclassifies 1,198 links and emits **0 units**,
because every recomputed verdict came back the same.

#### What the scoped invalidation missed, derived rather than guessed

"Bounded, not total" is not a statement anyone can check. The bound follows
from the rule itself, so it can be written down exactly.

Let `S(A)` be anchor `A`'s scope — the node four levels above it, which is what
`numericFamily` walks to. Let `T` be a mutation's target. Then:

- A mutation at `T` changes the anchor set of `subtree(X)` for exactly those
  `X` that are ancestors-or-self of `T`.
- `A`'s verdict depends only on how many anchors in `subtree(S(A))` share its
  masked href.

So **`A`'s verdict can change iff `S(A)` is an ancestor-or-self of `T`, and the
anchor that entered or left carries `A`'s mask.** Two conditions, and the
invalidation should match both.

The scoped version invalidates `subtree(anc4(T))`. Against the first condition:

- If `depth(S(A)) >= depth(T) - 4`, then `S(A)` lies on `T`'s ancestor chain at
  or below `anc4(T)`, so `subtree(S(A))` is inside `subtree(anc4(T))` and `A`
  is reached. Covered.
- If `depth(S(A)) < depth(T) - 4`, then `A` sits at `depth(S(A)) + 4`, strictly
  *above* the mutation, and may be in a branch `subtree(anc4(T))` never
  touches. Not reached.

The residue is therefore exactly: **an anchor shallower than the change, whose
fourth ancestor is a strict ancestor of the change's fourth ancestor** — a link
high in the document whose scope reaches all the way down to the mutation. Not
"some links far away": a stated set, which a test can construct.

Against the second condition, the scoped version does nothing at all: it
invalidates every anchor in the scope regardless of mask, which is why
`relocate` on the Wikipedia table reclassifies 1,198 links to emit nothing.

Both conditions pointed the same way, and the replacement — now in the fold —
is cheaper than what it replaced:

- **Scope: every observed root.** Exact on the first condition, and it closes
  the residue outright. Shadow roots are separate query scopes, so the sweep
  walks `roots` rather than `document`: a family inside a shadow root is still
  a family, and querying only the document would make the sweep silently
  partial exactly where the map works hardest to be whole.
- **Membership: same masked href.** Exact on the second, and it is the rule's
  own criterion rather than a heuristic filter.

Both halves are held by tests that fail against the scoped version.
`link_family_deep.html` is built to the derivation rather than found on a page:
a link two levels down has the whole document for a scope and counts all three
members of its family, while the members themselves are nested eight divs
deeper and never make three between them. Removing one re-classifies the
shallow link from a branch `subtree(anc4(T))` cannot contain, which is the
residue set stated above and nothing else. The filter's test inserts an anchor
of a *different* mask and requires that nothing be re-folded for it.

The sweep runs **once per repair, not once per mutation**: masks accumulate as
mutations arrive and are drained before the fold walks. A page appending fifty
rows pays for one sweep. It sits inside the timed region, because a phase
timing that hides its own cost is not a phase timing.

One hole this closed on the way past: the observers now set
`attributeOldValue`. Without it an edited href names the family it *joined* and
not the one it *left*, so the abandoned family keeps a count one too high and
every remaining member of it keeps a stale verdict.

Measured on six pages, one gesture each, the filter is what pays for the
widening — same units emitted, same exact map, a fraction of the fold:

| page · gesture | anchors marked dirty, scoped | mask-filtered |
|---|---|---|
| en.wikipedia largest-cities · delete | 1198 | **2** |
| en.wikipedia largest-cities · relocate | 1201 | **5** |
| news.ycombinator · relocate | 228 | **0** |
| books.toscrape · relocate | 92 | **2** |
| quotes.toscrape · relocate | 55 | **4** |
| ncbi pmc · delete | 38 | **0** |

Wikipedia's delete still emits the same 25 units and is still exact; it reaches
that by re-folding two nodes instead of 1,198. The zeros are the honest half of
the same story — a relocation that disturbs no numeric family now costs nothing
at all, where before it re-folded every anchor within four levels of the move.

The cost moves in the right direction because the two changes pull against each
other. Widening the scope costs one `querySelectorAll` and a regex per anchor —
work proportional to the page, but arithmetic, done once per repair that saw an
anchor change rather than once per mutation. Filtering by mask cuts what is
marked dirty from *every anchor in scope* to *the family*, and marking dirty is
the part that costs a re-fold. The O(delta) constraint binds on the fold, not
on the scan, so trading a page-sized scan for a family-sized fold is the trade
this codebase wants.

The alternative — document-wide invalidation without the mask filter — is
exact too, and was rejected: it marks every anchor's path dirty, which makes any
anchor-bearing mutation cost a whole-page fold and gives up O(delta) outright.

Corpus-wide after all three, one gesture per page:

| delete, over the frozen corpus | before | after |
|---|---|---|
| pages measured | 117 | 117 |
| of those, the gesture disturbed nothing | — | 5 |
| **exact, of the 112 it could fail on** | — | **110** |
| stale addresses | 25 (3 pages) | 9 (1 page) |
| **lost addresses** | 4 | **0** |
| wrong values | 10 | 12, on one self-moving page |
| addresses scored | — | 303,480 |

The five excluded pages are not a rounding detail; they are the harness
scoring itself. `www.w3schools.com/html/html_forms.asp` returned 0 stale and 0
wrong on one run and 9 stale and 4 wrong on the next, same gesture and same
group tag, because the first run's deletion removed a `DIV` holding no
addresses at all — truth came back equal to the starting count. Nothing was
asked of the trie, so nothing could fail, and the page sat in the total as
evidence. The count without that exclusion was 115 of 117; it is 110 of 112.

`_score` now records a **footprint** — addresses added or dropped plus values
changed, between what the trie held before the gesture and what the page holds
after — and the summary excludes footprint-zero measurements from the exact
count. A plain count difference would not have worked: `edit` changes a value
and no addresses by design, and a `relocate` of one sibling changes which
addresses exist without changing how many, so both would have read as vacuous.
This is the non-vacuity rule turned on the harness rather than on the sensor.

Sixteen pages have no drawn repeated group to delete from and three errored
(one 45s navigation timeout, two groups too small); both sets are excluded
from the denominator rather than counted as passes.

What is left is two pages, and they are not the same kind of thing.
coinmarketcap's twelve wrong values are the page's own clock, measured
below. `www.w3schools.com/html/html_forms.asp` holds nine stale addresses and
four wrong values and is **new** — it was not among the three pages carrying
delete's residue before, so it is a separate fault and is recorded as one
rather than assumed to be a remnant of these.

**3. A page that moves on its own.** coinmarketcap: 10 wrong values, and not
ours.

The null control settles it — no mutation at all, sensor booted and drained
against a truth map taken moments later, and the page scores **10 wrong**,
which is the same figure the delete gesture reported. It is a frozen snapshot
still running a clock. The gesture was never the cause, and attributing those
ten to the delete path would have been a fabricated defect to chase.

That is the arm every gesture measurement needs and only `live_delta` had. A
score against a moving page is a score of the page's motion plus ours, and
subtracting requires measuring the page alone first.

### The resolution limit, and why two pages were never defects

Twice a page's residue was read as a sensor defect first, and twice the page
was the cause. coinmarketcap's twelve wrong values under `delete` were a price
ticker. `www.w3schools.com/html/html_forms.asp` held nine stale addresses and
four wrong values, and **every one of them was at `/html/iframe[N]`**, holding
an ad-sync beacon URL — `user-sync.fwmrm.net`, `ap.lijit.com`,
`prebid.a-mo.net`. The page's own scripts append and recycle those iframes on
`<html>` for as long as it is open.

The null control said the same: 7 stale and 6 wrong on that page with no
mutation at all, all in iframes. But the decisive form of the evidence takes
the sensor out of the room entirely — **two independent truth maps of the same
live page, three seconds apart, each a full walk by a freshly booted reader,
with no incremental path and no mutation between them**:

| page | addresses | disagrees with itself | where |
|---|---|---|---|
| w3schools html-forms | 1,773 | **8** | 8 of 8 in iframes |
| coinmarketcap | 1,524 | **21** | ticker values |
| quotes.toscrape | 176 | **0** | — |

The document disagrees with itself. Nothing else is present to blame. So
`delete` is exact on every page in the corpus that holds still, and the two
pages that were carrying its remaining residue were never carrying a defect.

Over the whole corpus, with no sensor involved anywhere in it:

| the page against itself, 3s apart | pages |
|---|---|
| measured | 135 |
| **hold still (floor 0)** | **133** |
| move on their own | 2 |
| errored | 1 (codeberg, 45s navigation timeout, every run) |

The two are coinmarketcap (floor 10, entirely value churn -- the ticker) and
w3schools html-forms (floor 4, entirely address churn -- the iframes). They are
exactly the two pages carrying `delete`'s remaining residue, identified here by
a measurement in which the sensor takes no part. The corpus is 133/135 static,
so exactness is claimable nearly everywhere, and the exceptions are named
rather than averaged in.

The floors also move between visits -- w3schools measured 8 by hand earlier and
4 here, coinmarketcap 21 and 10 -- because ad-sync and ticker timing differ per
load. That is not inconsistency in the measurement; it is the reason `drift`
takes its own control window on each page load instead of importing this
artifact. A floor is a property of the document *and* the visit.

This is now measured rather than re-derived by hand whenever a page looks
guilty. `domvec/analytics/stability.py` gives each page a **resolution
limit**: a page whose floor is eight addresses cannot evidence a four-address
defect in either direction, and a corpus total that sums residues without
their floors is summing signal with noise and calling the result accuracy. It
is deliberately not part of `drift`, because the floor is a property of the
document rather than of a gesture and has to be measurable without one.

Two things it is careful about, because the crude versions of both are wrong:

- **The floor is subtracted by name, not by count.** Five stale addresses under
  a floor of eight can still be five real defects somewhere the page held
  still. `_score` takes the *set* of addresses that moved during a control
  window and reports `fp_net` / `fn_net` / `value_wrong_net` with exactly those
  discounted.
- **The floor is measured on the same page load.** Ad-sync iframes differ from
  one visit to the next, so a floor imported from `stability.jsonl` would
  discount the wrong addresses by name. `measure_drift` therefore takes its own
  control window — two full walks, the same 0.45s the gesture gets — before
  touching the page.

What the drift table now reports, per arm: how many measurements the gesture
disturbed nothing on (excluded), how many were exact, how many were exact net
of the page's own motion, and how many were exact on the subset of pages that
held still — which is the only subset where "exact" is a claim about the
sensor at all.

### No measurement can currently exercise a sensor variant

Deduplication correctness is scored, and scored properly: `DedupScore` names
both errors rather than reporting one rate. `over_dedup` is distinct page
content collapsed into one -- loss, the dangerous direction -- and
`under_dedup` is redundancy emitted twice, which is noise. That covers the
default pipeline, markdown suppression rules included.

What it does not cover is the sensor's own subsumption. `USE_DEDUP` --
sketch-then-verify, `subsumed(rec, seen)` at emit -- is declared
`!!V.dedup`, so it is **off unless asked for**, unlike `gate`, `cache` and
`intern`, which are `V.x !== false`. The catalogue removed from the REPL
asserted the opposite, listing dedup among the "settled mechanisms, on by
default". The code disagreed with it, and nothing checked.

The reason that went unnoticed is structural rather than careless: **every
analytics module constructs its sensor as `Sensor(driver, url, budget=...)`,
with no variants at all.**

    domvec/analytics/run.py:109        Sensor(driver, url, budget=...)
    domvec/analytics/drift.py:184      Sensor(driver, url, budget=...)
    domvec/analytics/drift.py:267      Sensor(driver, url, budget=...)
    domvec/analytics/delta.py:85       Sensor(driver, url, budget=...)
    domvec/analytics/live_delta.py:266 Sensor(driver, url, budget=...)

So no measurement in the suite can answer a question about any mechanism that
is off by default. "Is the sensor's subsumption safe to enable?" is not a hard
question -- `DedupScore` is exactly the instrument for it, and the failure mode
it would catch, silent loss of distinct content, is the one that matters -- but
it is currently unaskable. The design space had a vocabulary and no way to
measure anything in it, which is the same defect the vocabulary itself turned
out to be.

The fix is small: thread `variants` through `measure_page` and `measure_drift`
and expose it on the CLI, then run the dedup arm both ways and let the
over-dedup count decide. It is not being applied mid-sweep -- the chained arms
each start a fresh `python -m domvec.analytics`, so an edit to the harness now
would land between arms and put two instruments in one table.

### The asynchronous phase has never had anything to time

The goal asks for the mutation-chunking algorithm and the embedding phase to
be timed separately, and structurally they are. One row of `affine.jsonl`:

    fold_ms 14.0   drain_ms 29.9   decode_ms 3.2   trie_ms 17.3
    markdown_ms 34.4   wire_ms 1.1
    embed_queue_ms 0.071   embed_ms 0.001   total_ms 3264.3

The fold, the crossing, the decode, the trie write, both renderings, the queue
and the embedder each have their own number, and the total is there beside
them. That is the shape the goal asked for.

But `embed_ms` is 0.001 because nothing was embedded. Across **all 84 recorded
runs: 7,053 chunks pushed to the queue, 0 ever embedded.** `measure_page` takes
`embedder=None` and the CLI never supplies one, so `queue.flush(embedder)`
returns immediately.

The code says so rather than hiding it — *"With no embedder this reports the
queue's own cost and an `embedded` count of zero, which is the honest reading
of 'decoupled': the delta path did not wait"* — and that reading is fair as far
as it goes. What `embed_queue_ms` of 0.071ms genuinely establishes is the
decoupling: pushing 8 chunks costs the delta path a fifteenth of a millisecond,
so vectorization is off the recursion, which is half of what the goal asks.

The other half is unmeasured. `embed_ms` is not evidence that embedding is
fast; it is the absence of embedding. A real embedder exists
(`domvec/core/embedding_service.py`, with a model backend and batching), and
`live_delta` already uses an input-dependent counting stub for its cache-reuse
check, deliberately not a constant one because a constant embedder would make
any cache look correct. Closing this means threading a real embedder into the
affine run so that `embed_ms` measures embedding and `embed_queue_ms` keeps
showing the fold did not wait for it. Until then the async phase's own cost and
throughput are not known, and the timing table should be read as one measured
half and one placeholder.

While that row was being read, two other numbers in the same artifact settled
open questions:

    dedup:      redundant_pairs 54  collapsed 54  under_dedup 0  over_dedup 0
    algorithms: deduped 0  near_dups 0  sketch_hits 0

The pipeline collapses redundancy correctly -- 54 of 54, and **zero
over-dedup**, which is the direction that loses content. And `deduped: 0`
confirms from the other side that the sensor's own subsumption contributes
nothing in the default configuration, exactly as `!!V.dedup` implies. The
dedup correctness the goal asks for is real; it is the markdown pipeline's,
not the sensor's.

### How fast the map goes wrong

Knowing the trie grows is not the same as knowing what it costs. The same
sensor can produce a *fresh* map of the page as it now stands, so the repaired
trie can be scored against it address for address — which is the confusion
matrix this goal asks for, applied to the map's own totality of coverage.
`analytics/drift.py` mutates a page ten times and checks in along the way.

Staleness and loss are kept apart deliberately: a lost address is content the
reader cannot reach, a stale one is content reached twice or wrongly, and one
"accuracy" figure would average them into something that sounds fine.

| page | truth | recall | stale after 1 → 10 | lost | wrong value |
|---|---|---|---|---|---|
| blog.codinghorror.com | 615 → 624 | 100% | 5 → 50 | 0 | 0 |
| arxiv.org/abs/1706.03762 | 433 → 442 | 100% | 3 → 30 | 0 | 0 |
| discourse.julialang.org | 889 → 898 | 94.9 → 99.6% | 183 → 667 | 45 → 4 | 58 → 92 |
| docs.python.org/library/re | 5156 → 5165 | 100% | **2, flat** | 0 | 9 |
| quotes.toscrape.com | 177 → 186 | 100% | 32 → 198 | 0 | 0 |

Three things this says that the single-mutation numbers could not.

**Recall holds.** On four of five pages the trie never loses an address across
ten mutations. The map does not forget; it accretes.

**Staleness is linear in mutations, at a page-dependent rate.** Roughly 5 per
mutation on codinghorror, 3 on arxiv, 20 on quotes, 67 on discourse. There is
no bound: after ten insertions **quotes.toscrape.com holds 198 stale addresses
for a page with 186 real ones** — the map is by then more stale than real. That
is what the growth defect actually costs, and it is not cosmetic.

**And it is not universal.** docs.python.org sits at 2 stale addresses after
ten mutations on a 5,156-address page. Whatever produces the drift is a
property of page shape, not of the algorithm everywhere, which is the useful
half of the finding: there is a class of page where the incremental path is
already exact.

discourse.julialang.org is the one page carrying *wrong values* at shared
addresses — 58 rising to 92. Holding the wrong content at a right address is
worse than either staleness or loss, and it is the next thing to chase.

**An unexplained loss, measured rather than guessed at.** Arabic Wikipedia
loses 86 identities on one insertion, and ja-wikipedia 3. I attributed that to
three different mechanisms of my own and was wrong each time; the fourth check
was to measure the page at the commit *before* any of this work, where it
already lost 89. The loss is pre-existing and unexplained. What this work
changed on that page is the delta — 148 → 1 — and the loss, 89 → 86.

### Reading order is the fourth thing the map preserves

An affine map preserves relations, not origin: containment survives as
indentation, ratios survive as relative size, and **reading order survives as
the order lines come out**. Coverage says every unit arrived; deduplication
says none arrived twice. Neither is disturbed by a page whose paragraphs come
out shuffled, and for a long time none of the numbers here were.

It was not hypothetical. The scan keys walk positions on absolute xpaths and
indexes an element wherever it has same-tag siblings — `.../ul/li[1]`,
`.../ul/li[2]`. The trie builds its path from `ContentAddress.path()`, which
drops the index on the first of a group — `.../ul/li`. The lookup missed for
exactly one child per group, that child got `doc_pos = -1`, unknown positions
sort last, and **the first item of every list, table and card grid was drawn
at the bottom of its group**. Every address was right, every unit present,
every dedup decision right; the page simply read in the wrong order. Only on
the snapshot path — the live path supplies no map, so every position is
unknown and sibling index decides, correctly — which means the two paths that
are meant to produce the same chunks did not.

Measured over the fixture pages plus a saved real page: **42 prose inversions
before, 8 after**. `affine.OrderScore` now reports it per page, against the
ground truth's own composed-tree walk so that slotted content is scored where
the page puts it.

Two things are excluded, both for the denominator's sake:

- **Headings.** A heading whose words live in child elements is deliberately
  drawn with the card it labels, ahead of content the walk met earlier.
  Counting it would make the number a function of how many cards a page has.
- **The wireframe.** Its order is the page's *layout* — a right-hand sidebar
  is drawn beside the column it sits next to. Scored against walk order it
  reads 91% on a page it draws correctly. That is the denominator mistake this
  project keeps making, so the visual projection is not scored here rather
  than scored wrongly.

## Constraints that hold throughout

1. **The fold reads no layout.** Enforced by `invariants.c2`. Geometry is a
   peripheral keyed by address, never in the trie.
2. **Closed shadow roots stay closed.** Reaching in requires patching
   `attachShadow`, which is detectable and is refused. They are *reported* as
   unreachable so the coverage number stays honest.
3. **Nothing is written into the page** and nothing is transmitted.
4. **Analytics live outside the REPL**, in their own artifacts.
5. **O(delta)**: a positional shift costs 1, not N+1. A change that reintroduces
   whole-document work is a regression regardless of its wall-clock time.

## Standard of proof

Quality, completeness, attention to detail, empiricism, provability,
repeatability, edge cases derived from theoretical constraints and analysis of
the code. Work until fully proven — not until it looks right.

Two rules earned the hard way in this repo and binding here:

- **A green suite is not proof.** Detection rates structurally incapable of being
  non-zero, a `forget` that crashed when asked, a composed-tree walk that never
  composed, and a coverage number that mixed capture with projection all passed a
  fully green suite.
- **Every metric gets a non-vacuity test.** A check that cannot fail is a check
  that is not measuring. Assert the planted defect is caught, not only that the
  clean case passes.
