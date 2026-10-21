# The affine map — standing goal

**Set 2026-08-27. Binding. This supersedes the variant-benchmark framing as the
project's purpose.** The percentage detection rates (search 64.4%, pagers 44.2%
over 1,721 pages) are not the objective and were never the objective; they are
a property of one subsystem.

`PLUGIN_GOAL.md` is the plugin-side companion to this file, binding in the
same way and covering the panel browser, notebooks, and the language-model
interface.

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

Re-measured with the footprint and floor instrumentation in place, `delete`
over the whole corpus, one gesture per page:

| | pages |
|---|---|
| instrumented measurements | 117 |
| **held still, and exact** | **115** |
| held still, with any residue | **0** |
| moved on their own | 2 |

Every page in the corpus that holds still is exact under deletion: no stale
address, no lost address, no wrong value. That is the claim the three fixes
were for, and it is now the whole static corpus rather than a count with
exceptions.

The two that move are not one story, and the difference is the useful part.
`w3schools` discounts cleanly -- raw 12 down to net 1, its eight stale
addresses and four wrong values falling to one and zero once the addresses it
moved by itself are removed by name. **coinmarketcap does not**: raw 118, net
103, against an in-run floor of 18. The discount barely touched it, so its
residue is not established as page motion, and it is not established as a
defect either.

The exposure-bracketing window does not settle that one, by its own stated
limit: bracketing the two *ends* of the exposure cannot catch a page churning
continuously through the middle, which is precisely what a price ticker does.
What settles it is the `none` arm -- identical timing, identical walks, no
gesture -- which measures what looking at that page costs before anything is
done to it.

**It settled it against the comfortable answer.**

| page | floor | none | delete | |
|---|---|---|---|---|
| coinmarketcap | 18 | **7** | **103** | 96 above control |
| w3schools html-forms | 11 | 0 | 1 | control clean |

With no gesture at all and every other cost identical, coinmarketcap's residue
is **7**. The deletion adds **96**. So the page's own motion is not the
explanation, and the earlier conclusion here -- that its residue was the price
ticker, reached from a null control showing 10 wrong values against 12 -- does
not survive net accounting. The ticker moves values; what the gesture produces
is 87 *stale addresses*, which is a different defect entirely and was hidden
behind a plausible story about the same page.

Two candidates, not yet separated:

- **a vacating shortfall under cascade.** Deleting a row makes the page's own
  framework re-render a region, and 87 addresses the page no longer has stay in
  the trie. That is the same shape as the two faults already fixed today.
- **settling latency, and no defect at all.** The drain happens 0.45s after the
  mutation. If the re-render finishes asynchronously after that, the sensor has
  not seen the tail while truth -- walked later -- has, and a second drain would
  catch up.

They are cheaply separable: drain again after a longer wait and re-score. The
answer is the second, and it is not close.

    coinmarketcap, one row deleted, drained repeatedly:
        after   0.5s   units 15    stale 3   lost 3   wrong 15
        after   1.5s   units 49    stale 0   lost 0   wrong  7
        after   4.0s   units 85    stale 0   lost 0   wrong  8
        after  10.0s   units 203   stale 0   lost 0   wrong  3
    news.ycombinator, same schedule, as a control:
        every wait     units 0     stale 0   lost 0   wrong  0

Stale and lost reach zero by 1.5 seconds and stay there while units keep
arriving -- 15, then 49, 85, 203. **Nothing was missing. The harness was
early.** The residual wrong values are the ticker, which never settles because
the page never stops, and they belong to the floor rather than to the gesture.

So the earlier reading here -- "the sensor captures about 96% of the cascade
within 0.45s" -- was a measurement of the harness wearing the sensor's name.
The sensor captures all of it. The harness sampled before the page had
finished writing.

The asterisk lands where it was predicted to: on the harness, not on the page.
The gesture arm now drains to quiescence using `_settle`, the same rule the
initial scan already used, so a gesture is read the way a boot is. The static
corpus is unaffected -- a page with no asynchronous re-render has nothing
outstanding at 0.45s, which is why the control is clean at every wait -- but a
fixed pause was wrong in principle regardless of which pages it happened to
flatter. A page that never goes quiet exits on `limit`, so a ticker cannot
hang the sweep.

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

**This is why `delete`'s headline figure moves between runs, and why a move is
not news.** Three consecutive corpus runs of the delete arm, spanning a change
to sibling ordering:

| run | ordering | pages with net error |
|---|---|---|
| 22:28 | before | coinmarketcap, w3schools |
| 02:31 | after | none |
| 04:47 | after | coinmarketcap, w3schools |

117 of 117, then 115 of 117, on the same corpus. It reads as a regression and
is not one: the same two pages, always the same two, each error under its own
floor for that run (coinmarketcap 7 against 16, w3schools 2 against 3), and the
run *before* the change shows the identical pair. `drift` imports nothing from
the modules that changed in between. A figure that moves by two on this arm is
the corpus breathing, and the named pages are how you tell that from a defect.

This is now measured rather than re-derived by hand whenever a page looks
guilty. `vertiscope/analytics/stability.py` gives each page a **resolution
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

    vertiscope/analytics/run.py:109        Sensor(driver, url, budget=...)
    vertiscope/analytics/drift.py:184      Sensor(driver, url, budget=...)
    vertiscope/analytics/drift.py:267      Sensor(driver, url, budget=...)
    vertiscope/analytics/delta.py:85       Sensor(driver, url, budget=...)
    vertiscope/analytics/live_delta.py:266 Sensor(driver, url, budget=...)

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
each start a fresh `python -m vertiscope.analytics`, so an edit to the harness now
would land between arms and put two instruments in one table.

### The asynchronous phase, measured at last

`--embed cpu` supplies a real embedder -- `nomic-embed-text-v1.5.f16.gguf`,
present locally, no download -- so `queue.flush` does work instead of returning
immediately. Deliberately not `WFH_FAKE_EMBEDDER`, which exists and would let
this run without a model: timing a fake would produce exactly the kind of
number the flag was added to stop producing.

| phase | quotes.toscrape | news.ycombinator |
|---|---|---|
| fold — the in-page chunking algorithm | 18.0 ms | 45.0 ms |
| drain — the crossing | 32.7 ms | 87.9 ms |
| trie — payload into the patricia trie | 28.0 ms | 72.4 ms |
| markdown | 49.7 ms | 183.7 ms |
| wireframe | 1.9 ms | 6.0 ms |
| **embed_queue — what the delta path pays** | **0.112 ms** | **0.377 ms** |
| **embed — the asynchronous phase** | **7,638 ms** | **38,111 ms** |

**The asynchronous phase costs 100 to 400 times the entire synchronous
pipeline.** Embedding news.ycombinator's 24 chunks takes 38 seconds; folding,
crossing, writing the trie and rendering both projections takes 395ms between
them.

That is the argument for doing vectorization off the recursion, and it is now a
measurement rather than a design preference: **the delta path pays 0.377ms to
hand off 38 seconds of work**, about a thousandth of one percent. Synchronous,
a page would cost 38 seconds instead of 45 milliseconds and the millisecond
claim would be dead. The decoupling is not an optimisation; it is the only
reason the interactive path exists.

Three limits on these numbers. They are CPU, and GPU is unmeasured. Per-chunk
cost scales with chunk size -- 955ms per chunk here against 20ms per short
string in a smoke test, because real chunks run to the 1200-character budget.
And `embed_ms` is taken with `flush` called inline, which is how the cost
becomes visible at all; on the live path it is off-thread, and what the
interactive path actually pays is `embed_queue_ms`.

The embedder is deterministic across calls -- the same text in two calls is
bit-identical, which is what `VectorQueue`'s digest-keyed reuse depends on.
Within a single batch there is float noise of about 5e-08 from accumulation
order at different batch positions, which is below anything the cache or the
retrieval side can notice.

en.wikipedia's largest-cities page (6,845 addresses) exceeded ten minutes on
CPU and did not complete. Recorded rather than dropped.

### What the phase was reporting before this

#### The reading it replaced

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
(`vertiscope/core/embedding_service.py`, with a model backend and batching), and
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

### The sensor's own subsumption loses content, and stays off

`USE_DEDUP` -- sketch-then-verify, `subsumed(rec, seen)` at emit -- was
declared `!!V.dedup`, off, while a catalogue in the REPL listed it among the
"settled mechanisms, on by default". Nothing checked, because until
`--variants` existed no measurement in the suite could exercise a mechanism
that was off. The question is now askable, and the answer is no.

Both arms over eight corpus pages whose stability floor is zero, so none of
this is page motion. The marginal effect of turning it on:

| | change |
|---|---|
| redundancy collapsed | **+22** |
| under_dedup (noise) | **-29** |
| **over_dedup (loss)** | **+6** |
| **addresses lost from the trie** | **+25** |

It stays off. `under_dedup` is noise and survivable; content collapsed away is
not, and 25 addresses missing from the trie is content the reader cannot
reach at any price in payload.

**The row that matters is `docs.python.org/3/library/re.html`**: 17 more
redundant pairs collapsed, 17 fewer noisy duplicates, and **no additional
over-dedup at all**. On the dedup axis alone that is a pure win, and it would
have been the strongest evidence for enabling the mechanism. Its recall fell
from 100% to 99.5%: **24 addresses gone from the trie.**

That is the whole reason the check reads two axes rather than one. A
suppression mechanism can only ever remove emissions, so it can always improve
its own dedup score by dropping content -- and here it did, with every dedup
number moving the right way. `DedupScore` alone would have recommended it.

One correction to record, because it was this document's kind of mistake. The
first reading of these arms reported 109 over-dedup and 47 lost addresses,
taken from the totals of the ON arm. Almost all of that is the markdown
pipeline's and is present with the sensor's dedup off --
`docs-python` carries 88 over-dedup in both arms. The meaningful quantity is
the difference between the arms, which is +6 and +25. Same verdict, a
twentieth of the magnitude, and stated as an absolute it would have condemned
the mechanism for the pipeline's behaviour.

### What the classification sweep costs, and the one place O(delta) does not hold

The sweep that invalidates stale link verdicts runs inside `repair()`, inside
the timed region, and until now had never been priced. "Cheap because it is
filtered" was a claim.

Isolated by two mutations on the same page and the same load -- a `<p>`, which
queues no masks and skips the sweep entirely, against an `<a href>`, which
queues one:

| page | anchors | repair without | repair with | **the sweep** |
|---|---|---|---|---|
| en.wikipedia largest-cities | 1,326 | 3.5 ms | 11.0 ms | **7.5 ms** |
| old.reddit r/programming | 317 | 1.0 ms | 3.5 ms | **2.5 ms** |
| quotes.toscrape | 55 | 0.0 ms | 1.0 ms | **1.0 ms** |

`repairMs` is cumulative in the page, so these are differences between
consecutive drains; read as absolutes they would rise through both arms and
make whichever ran second look expensive.

**The mask filter does exactly what it was built to do.** Six insertions on a
page holding 1,326 anchors invalidated **21** verdicts in total -- which is
0+1+2+3+4+5+6, since each inserted `/family/N` masks to `/family/#` and
disturbs only the ones already sharing it. Unfiltered, the same six mutations
would have re-folded on the order of eight thousand. The page's other 1,300
anchors are never touched.

So the 7.5 ms is almost entirely the *scan*, not the marking, which is the
trade the design intended: a page-sized scan buying a family-sized fold.

**And it is the one place the fold is not O(delta).** The fold proper is
delta-proportional; the classification scan walks every anchor on the page
whenever an anchor enters or leaves, so an anchor-bearing structural mutation
costs O(anchors). On the largest page in the corpus that is 7.5 ms, against 45
ms of fold on news.ycombinator and 38 seconds of embedding. Small, bounded,
and real.

It is recorded rather than fixed. The fix is an incremental mask-to-anchors
index maintained as anchors are folded, which would make the sweep O(family)
and restore O(delta) everywhere. It also means holding references to DOM nodes
outside a `WeakMap`, because a JavaScript `WeakSet` cannot be iterated -- so
the index either leaks anchors that leave the document without being noticed,
or needs a pruning pass that reintroduces the scan it was meant to remove. A
memory leak is a worse defect than 7.5 ms on the corpus's largest page, and
this is a trade worth making only against a measurement that says the scan
hurts.

### Sustained mutation: ten deletions, no accumulated drift

Every corpus figure above is one gesture against a freshly settled trie, and
that is a weaker claim than it reads as. Each repair starts from the state the
last one left, so error that cancels at n=1 can compound at n=10, and a map
that is correct once is not thereby a map that stays correct. `--mutations 10`
scores at 1, 3, 5 and 10 so that drift shows *where along the sequence* it
begins.

Ten successive deletions, eight pages whose stability floor is zero:

| page | addresses at start | reached | stale/lost/wrong at each checkpoint |
|---|---|---|---|
| books.toscrape | 321 | n=10 | 0/0/0 at 1, 3, 5, 10 |
| archive.org details | 608 | n=10 | 0/0/0 at 1, 3, 5, 10 |
| discourse.julialang | 888 | n=10 | 0/0/0 at 1, 3, 5, 10 |
| old.reddit | 1,378 | n=10 | 0/0/0 at 1, 3, 5, 10 |
| docs.python re | 5,155 | n=10 | 0/0/0 at 1, 3, 5, 10 |
| en.wikipedia largest-cities | 6,845 | n=10 | 0/0/0 at 1, 3, 5, 10 |
| quotes.toscrape | 176 | n=5 | 0/0/0; group exhausted at 8 |
| news.ycombinator | 711 | n=1 | 0/0/0; group exhausted at 2 |

**28 of 28 measurements exact.** No drift at any checkpoint, on pages from 321
to 6,845 addresses. Ten repairs deep, each starting from what the last one
left, and the trie still matches a freshly booted reader address for address.

The two short runs are the harness running out of material rather than
failures: `delete` removes members of a repeated group, so a group of ten is
spent by the eighth deletion and a group of four table rows by the second.
Recorded as stops, not counted as passes.

All four gestures, same eight pages, ten mutations each:

| gesture | measurements | exact | pages short of n=10 |
|---|---|---|---|
| insert | 32 | **32/32** | none |
| delete | 28 | **28/28** | quotes (group spent at 8), news.ycombinator (at 2) |
| edit | 28 | **28/28** | docs.python: no text in the chosen group, n=0 |
| relocate | 29 | **29/29** | news.ycombinator: group of 4 rows too small at 3 |
| | **117** | **117/117** | |

**Re-run after both sensor changes -- the svg descent and the `<link>`
exclusion -- and unchanged: 117 of 117.** Changing what the fold captures did
not disturb what it tracks. Single-gesture over the corpus in the same run:
insert 118/119, edit 111/112, relocate 117/117, delete 116/117.

The stability arm was included in that chain deliberately, and it is the one
that would have been most informative had it moved: 133 of 135 pages hold
still, identical to before. The floor is a property of the document, not of
the sensor, so a shift there after two sensor changes would have meant the
measurement is not measuring what it claims. It did not shift.

**117 of 117 measurements exact under sustained mutation.** Every shortfall is
the harness running out of material -- a repeated group spent by repeated
deletion, a group of four table rows too small to relocate within, a group
with no text to edit -- and each is recorded as a stop rather than counted as
a pass. 32 minus 4 and 32 minus 3 account for the two short arms exactly.

That upgrades the claim the corpus supports. "Exact under a gesture" was
established before; "tracked and updated" -- content held correct across a
sequence of changes, which is what the goal actually asks for -- needed this.

### How much of the corpus evidence crosses a shadow boundary

The goal calls this a map of the *shadow DOMs*, and the composed tree is where
the hard part of that lives. `test_composed_tree.py` proves the fold resolves
slots correctly against a fixture built for it. The 1,520,933 addresses scored
over the corpus prove nothing about it unless the corpus has shadow roots --
and a claim about shadow handling backed by pages that contain none would be
invisible, because every one of those addresses is mapped correctly either way.

Measured at runtime, walking *through* shadow roots rather than grepping
source, over all 135 pages:

| page | hosts | nodes in shadow | closed roots | roots observed |
|---|---|---|---|---|
| developer.mozilla CSS | 15 | 585 | 0 | 24 |
| developer.mozilla HTML | 15 | 585 | 0 | 24 |
| github.com/python/cpython | 5 | 15 | **1** | 6 |
| github.com/scrapy/scrapy | 4 | 12 | **1** | 5 |
| ec.europa.eu eurostat | 2 | 4 | 0 | 3 |
| github.com/trending | 1 | 3 | **1** | 2 |
| redis.io docs | 1 | 1 | 0 | 2 |

**Seven pages of 135**, and all seven are exact under all four gestures --
28 of 28. The sensor follows the boundary in the wild, observing up to 24 roots
on a page rather than the document alone.

Three carry a **closed** root, reported as unreachable rather than reached.
That is the constraint holding on real pages and not only in principle:
reaching in means patching `attachShadow`, which is detectable, and is refused.

But the honest reading of "exact on a page with a closed root" is narrower than
it sounds, and worth stating because it is a denominator question again. The
truth map is a second sensor, and it cannot see into a closed root either. Both
sides agree about content neither can reach. So those pages establish that the
map is exact over the *reachable* composed tree with the unreachable part
named -- not that anything is known about what is inside.

And the corpus contribution is thin: about 1,205 nodes inside shadow roots
across the whole corpus, well under one percent of the addresses scored. The
composed-tree handling rests mainly on its fixture, with real-page corroboration
that is genuine, includes the closed-root case, and is small. The corpus figure
should not be quoted as the evidence for shadow DOM correctness; it is
consistent with it.

### What the REPL offers to interact with, against what the page can be

The goal asks that what we see in the page is what we get in the REPL, and
that its interactive elements be the page's own rather than a vocabulary of
commands laid over it. That is a claim about **affordances**, and none of the
coverage arrows make it.

`page->wireframe` scores whether the right addresses were drawn, and reports a
false positive only for an **invented address** -- a path the composed tree
does not contain. A `<div>` drawn as a button passes it: the path is real and
only its class is a fiction. The address is right and the affordance is not.

The two errors are not symmetric, so they are counted apart. A **missed**
control is visible: a reader looking for a button finds prose. A **phantom** is
worse and invisible: it invites an interaction that cannot exist, and teaches
the reader nothing except that the map lies.

`vertiscope/analytics/affordance.py`, over the whole corpus:

| | |
|---|---|
| affordances the pages lay out | **74,797** |
| the REPL presents | **74,573** (99.70%) |
| **phantom (invented)** | **8** |
| missed (unreachable) | 224 |
| pages exact both ways | **111 of 135** |

**The two errors take different denominators, and that is not a detail.**

They ask different questions. A phantom asks *did the REPL invent this?* and is
scored against every control the page has, drawn or not -- a link inside a
collapsed section is a real link, and presenting it is not a fiction. A miss
asks *was the reader denied something reachable?* and is scored against what
the page lays out -- options behind a closed dropdown are not that.

A single `drawn` filter answers one and breaks the other, and both halves were
measured. Counting undrawn controls as missable put 1,788 dropdown options in
the denominator and took missed from 279 to **2,066**, for a REPL correctly
declining to offer choices behind a dropdown nobody had opened. Filtering the
phantom side the same way took phantoms from 8 to **8,701**, every one of them
a control the page genuinely has.

That is the fifth place this codebase has needed the capture/projection
distinction, and the first where the flat form of the rule -- "reader-facing
measures use `drawn`" -- was actively wrong rather than merely incomplete.

**Precision 99.99%.** Six of the eight phantoms are on coinmarketcap, which
rewrites itself between the truth read and the drain. The REPL essentially
never offers an interaction the page cannot perform.

The comparison is deliberately non-circular. The REPL's side is the sensor's
`INTERACTIVE_KIND`; the page's side is `groundtruth.isControl`, deciding from
tags, roles, `onclick` and `tabindex` with no knowledge of `RENDER_CLASS`.
Scored against the sensor's own table it would show only that the table equals
itself, which is the shape of every vacuous measurement here.

**Getting to that number took two corrections, and both were the instrument.**

Matching by path equality first reported **2,005 invented affordances**.
Ground truth marks the `<a>`; the sensor addresses the `<span>` holding the
link's words, which inherits the link class because that is what a reader sees
-- one link, drawn once, wherever its text sits. Every link on ar.wikipedia
scored as invented. Both sides were right and the comparison was wrong;
matching is by containment now, and the reasoning sits in the function so it is
not simplified back.

The second reading reported **267**, of which 254 were `<area href>` on
weather.gov's image map. `CONTROL_TAGS` had no `AREA`, though HTML-AAM maps it
to role `link` and a clickable region of a picture is plainly somewhere a
reader can act. Also corrected: `LABEL` removed, because a label is a *name*
for a control and clicking one activates the control it names, which is counted
in its own right -- counting both makes one affordance two; and
`input[type=hidden]` excluded, because an input the page never lays out cannot
be reached.

Each of those passes the test that keeps such corrections honest: **would I
make this change if the sensor did not exist?** All three are about what an
affordance is.

**A third correction, and it retracts the finding this section first reported.**

The `<details>` / `<summary>` misses were recorded here as the one real sensor
defect the measurement had found -- "the sensor has no handling for it and
draws it as text" -- and left deliberately unfixed so that correcting the
instrument could not be confused with flattering the sensor. That reasoning
was sound and the fact under it was never checked.

The sensor maps `summary` to `button` in `IMPLICIT_ROLE`, and on MDN's CSS
reference it classes **all 100 lines under those summaries as `button`**,
alongside 63 links as `link` and 47 buttons as `button`. It was right.

The fault was in the matcher, which credited only the **nearest** ancestor
control. `<details>` and `<summary>` are both controls in the page, so a drawn
line inside the summary marked the summary covered and left the details
uncovered -- every disclosure on the page counted as unreachable. Controls
nest, and a disclosure's affordance *is* its summary: a reader who can act on
the summary can open the details. Crediting every control on the ancestor
chain took the misses from 602 to 279 and the exact pages from 95 to 106.

The lesson is not about disclosure widgets. This finding was singled out here
*because* it did not flatter the sensor, and that was treated as grounds to
trust it more. **Being unflattering is not evidence of being true.** On this
project the base rate says an unverified number is more likely inert or
miscomputed than correct, whichever direction it points.

**What is left is a definitional boundary, not a defect.** The 279 remaining
misses are dominated by elements made focusable with `tabindex="0"` and
nothing else -- every one of the eight sampled on w3.org's WAI-ARIA spec is a
`<dfn tabindex="0">` with no role, no `onclick` and no `href`. `tabindex`
makes an element focusable; it does not make it actionable. Removing
`tabindex` from `isControl` would drop the figure sharply, and that is
precisely why it stays: the boundary is documented where it is rather than
moved to improve the number it produces.

### The coverage matrix, corpus-wide, against the corrected denominator

Every arrow of the map over all 135 pages, scored against `groundtruth` as it
now stands -- `AREA` counted, `LABEL` dropped, hidden inputs excluded. Figures
taken before those fixes are not comparable to these.

| arrow | TP | FN | FP | recall | precision |
|---|---|---|---|---|---|
| page -> trie (capture) | 365,524 | 2,889 | 4,083 | **99.22%** | 98.90% |
| page -> markdown | 317,528 | 2,622 | 3,024 | **99.18%** | 99.06% |
| page -> wireframe | 316,532 | 3,385 | 104 | **98.94%** | **99.97%** |

Deduplication, same run: 67,618 redundant pairs, **46,773 collapsed**, 11,648
under-dedup, **624 over-dedup**, 137,652 distinct kept. Correctness 93.76%.

**One denominator error, found in three places at once.**

The first version of this table showed 7,043 invented addresses on capture,
and it named that the largest error in the map and the thing to fix next. It
was the measurement. 2,960 of them were on data.gov.uk, and **2,960 of that
page's 2,962 were `/option` paths** -- a page holding 1,511 options in
collapsed `<select>` elements.

Ground truth pruned the subtree under a folded control entirely, which
conflates *the page does not lay this out* with *the page does not have it*.
The trie captures a select's options, because they are content the page holds.
The renderer collapses the select to the value it shows, because that is what
a browser does. Both are right. Only the denominator was wrong, and the
`drawn` flag for expressing the difference already existed and was not
consulted.

Fixing it required three changes that pull against each other, and each one
exposed the next:

- ground truth **descends** into a folded control, marking everything inside
  `drew: false`. Capture FP fell 7,043 -> 4,083.
- `page->markdown` scores against **drawn**, not **all**. Without this the
  first change put data.gov.uk's 3,015 undrawn options in the projection's
  denominator and its recall fell to **5.2% for behaving correctly**.
- `score_dedup` scores over **drawn** content. Without this the same options
  read as distinct content destroyed, and `over_dedup` rose 654 -> 2,290 for a
  renderer that had collapsed a dropdown exactly as a browser does. Corrected,
  it is 624 -- below where it started, because the filter also removes
  undrawn cases that were always being miscounted.

The principle the three share, and the one to keep:

> **Capture is answerable for everything the page holds. Every reader-facing
> measure -- markdown, wireframe, dedup -- is answerable for what the page
> lays out.**

A single denominator across both must be wrong for one of them.

The useful thing about these is that they are not 100%, and each column fails
differently:

- **2,399 units the trie never captured** is the floor of everything
  downstream -- content missing here cannot be recovered by any projection.
- **7,043 invented addresses on capture** is the largest single error in the
  table, and the one to take next. An invented address is content placed
  somewhere the page does not have it, which is worse than a stale one: the
  reader is not merely served twice, they are served a location that does not
  exist.
- **The wireframe invents almost nothing** -- 104 in 316,635 -- which is
  consistent with the affordance result, where it offered 8 controls the page
  did not have in 74,581.
- **654 over-dedup** is the loss direction of the dedup decision, against
  52,849 collapsings that were correct. Small, and the direction that costs
  content rather than noise, so it is the dedup number worth watching.

The gap between capture recall (99.34%) and markdown recall (98.63%) is the
projection's own loss: 2,591 units reached the trie and did not reach the
reader. That decomposition is the point of scoring the arrows separately --
one figure over the whole pipeline would have hidden which half to fix.

### The largest remaining capture gap: text inside SVG

Of 2,889 units the trie never captured across the corpus, **2,167 are on one
page** -- `sqlite.org/lang_select.html` -- and the mechanism is not a defect in
the fold's bookkeeping. It is a design decision meeting a case it was not made
for.

That page carries **139 SVGs holding 2,447 `<text>` elements and 14,037
characters**: the SQL grammar, drawn as railroad diagrams. The trie captures
**zero** addresses containing `/svg`.

`SVG` is in `MEDIA_TAGS`, so an inline SVG is rendered as one media reference
and the fold does not descend into it. For icons and logos that is right and
deliberate -- a page with two hundred tiny path SVGs should not turn each into
content, and the existing note about `.../svg[4]/title` shows the render
standing for the picture rather than its parts on purpose.

For a diagram whose labels *are* the documentation, the same rule loses the
document. A reader of that page in the REPL gets the prose around the
diagrams and none of the grammar.

**Taken, and measured.** An `<svg>` containing `<text>` is no longer folded;
descent is by the ordinary path, so the addresses are the composed tree's and
match ground truth by construction rather than by a targeted query that would
have had to reinvent the addressing scheme. Geometry is still walked and still
emits nothing: a `<path>` has no text child and no content attribute, so the
cost is a traversal, not a line.

| | before | after |
|---|---|---|
| sqlite capture recall | 37.9% | **99.9%** |
| corpus capture recall | 99.22% | **99.80%** |
| corpus capture FN | 2,889 | **725** |
| corpus capture precision | 98.90% | 98.90% |
| `page->wireframe` precision | 99.97% | **99.97%** |
| drift, delete | 115 of 117 | 115 of 117 |

The over-capture canary held. `page->wireframe` precision is the number a
flood of decorative labels would degrade, and it did not move; nor did capture
precision, nor the drift result.

Capture and rendering came apart correctly, which is the part worth keeping.
All 2,447 labels now enter the trie. Only **117 of them have area** -- sqlite
keeps most of its diagrams in collapsed sections -- and those 117 are what the
projections draw. The other 2,330 are captured and not drawn, counted `tn`.
Everything the page holds is addressable; what the reader is shown stays a
separate decision.

The original statement of the fix, kept because the reasoning is what
justified it:

- **The rule to change is narrow.** An SVG is a picture unless it contains
  `<text>`; text inside an SVG is content a reader is entitled to. That mirrors
  the reasoning already written beside `<img alt="">` in `kindOf` -- the role is
  left alone and the *render class* is corrected, because what a reader is
  shown is a separate decision from what the AAM tables say.
- **It is a sensor change, so every number above moves.** What the fold
  captures changes, so coverage, drift, affordance and dedup all need
  re-measuring, and the sustained-mutation runs with them. That is roughly two
  hours of browser time, not a patch and a smoke test.
- **The risk is over-capture, and it has a name here.** DuckDuckGo's region
  filter taught this codebase that structurally faithful is not the same as
  useful: eighty option lines ahead of the first result. A decorative SVG with
  a stray `<text>` label would draw a line the reader did not need. The
  measurement that would decide it already exists -- `page->wireframe`
  precision, currently 99.97%, is exactly the number over-capture degrades.

Recorded rather than fixed in the same breath as finding it, because the
corpus figures in this document are consistent with each other as they stand,
and a sensor change invalidates all of them at once.

### `<link>` is metadata, and capturing it was the mirror of folding the svg

The corpus's 4,083 invented capture addresses had a dominant class, and it was
not addressing arithmetic. `<link>` elements: **377 of them in the body of one
Wikipedia article**, `rel="mw:PageProp/Category"`, hrefs like
`./Category:Articles_with_short_description`, every one of zero area.
Parsoid's category references, which no reader sees and ground truth emits
nothing for.

`<link>` is *metadata content* by the HTML spec. Its href is a machine
reference -- a stylesheet, a canonical url, a category -- and capturing it put
377 addresses per page into the trie that no reader can reach and that dilute
what retrieval ranks over.

| arrow | FP before | after | precision |
|---|---|---|---|
| page -> trie | 4,083 | **1,159** | 98.90% -> **99.69%** |
| page -> markdown | 3,024 | **396** | 99.06% -> **99.88%** |
| page -> wireframe | 104 | 104 | 99.97% (unchanged) |

On the worst page alone: 714 invented addresses down to **2**, at 100% recall
and 100% precision over 14,701 units. Affordances and dedup did not move,
which is the right shape -- a metadata element was never an affordance or a
redundancy.

**This is the svg case in reverse, and the pairing is the point.** Both ask
the same question -- *is this something the page shows a reader?* -- and the
sensor had it wrong in opposite directions:

- folding the svg **lost content**: 14,037 characters of SQL grammar a reader
  should have had;
- capturing `<link>` **gained noise**: category references a reader will never
  see.

Neither was visible in a headline figure. Capture recall read 99.22% while
sqlite silently lost its documentation, and capture precision read like a
sensor defect while the actual fault was metadata being treated as content.
Both surfaced only by reading samples against an independently computed ground
truth, and in both cases the fix is justified by what the element *is* --
HTML-AAM for the diagram, the spec's own "metadata content" for the link --
rather than by which direction it moves a number.

### Where the remaining capture gap actually is

After the svg and `<link>` fixes the capture arrow reads 99.80% recall and
99.69% precision, and what is left is long tail: 727 units never captured
across 135 pages, worst page 64, against 2,167 on a single page before.

The largest identifiable class is `option`, and chasing it produced two
refuted hypotheses before an answer, which is worth recording because both
were plausible and both were mine.

**First: "the sensor's `FOLDED` conflates capture with rendering."** The fold
folds a `<select>` so eighty country names do not draw, and it seemed obvious
that folding also prevented capture -- the same capture/projection confusion
the measurement side had to be taught four times. Refuted directly:
data.gov.uk holds 1,511 options and the trie holds **2,960 option addresses**
for them. They are captured.

**Second: "the collapsed select draws its current value, so the first option
is captured at the select's address instead."** Also wrong. A per-address diff
narrowed it to exactly one missing address per select -- `/select/option`, the
first -- and the check that settled it was looking for that option's text
elsewhere in the trie.

**Its text is empty.** The first option is a placeholder. Ground truth emits a
`control` unit for it because `isControl(OPTION)` is true; the sensor emits
nothing because there is nothing to emit. A unit with no value carries no
content, so the trie is right to hold none, and the miss is the instrument
counting an empty placeholder as something to capture.

The lesson is the one this whole document keeps arriving at from new
directions. Both hypotheses were architectural and interesting, and the answer
was that a string was empty. Neither sample tallies nor a plausible mechanism
would have found it -- only diffing addresses on one page and then asking what
the value actually was.

### A hidden input is a machine payload, not a control

The invented capture addresses had one more class, and the value gave it away:
**422 addresses on openlibrary whose value was the literal string `input`**.
Not plausible page content. It is the placeholder the fold emits for every
form field -- a line saying *there is a control here* -- and that page carries
exactly **422 `input[type=hidden]`**.

A hidden input is a form's machine payload. Nobody can see it or use it, and
the trie was carrying an assertion that it was something to interact with.

The fix keeps the distinction sharp. A hidden field's `value` and `name` are
still captured if they hold anything, because **a hidden field's content is
content**; what is dropped is only the claim that there is a control.

| | before | after |
|---|---|---|
| capture FP | 1,159 | **563** |
| capture precision | 99.69% | **99.85%** |
| openlibrary invented | 422 | **0** |
| markdown / wireframe / dedup | — | unchanged |
| affordances | — | unchanged |
| **drift, delete** | 116 of 117 | **117 of 117** |
| suite | — | 1,500 passed |

**Affordances not moving was the prediction, and checking it was the point.**
Ground truth had already excluded hidden inputs from `isControl`, so the sensor
ceasing to claim them should move nothing there. Had it moved, the account of
which side was wrong would have been incomplete and the change would not have
been committed.

And **this was exposed by an earlier instrument change of ours.** Excluding
hidden inputs from `isControl` stopped truth counting them as controls, and
the sensor's placeholder went from matching to mismatching. The instrument
change was right on its own terms -- a hidden input is unreachable -- and it
made visible a sensor over-capture that had been silently cancelling out
against a matching error on the other side. Two wrongs had been agreeing.

That completes a family of three, all one question -- *is this something the
page shows a reader?* -- answered wrongly in three different ways:

| | error | fix |
|---|---|---|
| `<svg>` with `<text>` | content **lost** by folding | descend |
| `<link>` | metadata **captured** as content | skip |
| `input[type=hidden]` | machine payload **claimed** as a control | no placeholder |
| `role="presentation"` | an annotation meaning *no semantics here*, captured **as** semantics | no `@role` line |
| `data-mw` and its kind | a serialized payload's **fields** mined as the element's own references | no url mining from a value that begins `{` or `[` |

The last is Parsoid's `data-mw='{"parts":[{"template":...}'`, written on every
transcluded citation. Mining urls out of it produced 106 of es.wikipedia's
charged inventions -- template *parameters*, addressed at the `<cite>` that
carries the blob, while the citation's real link is an `<a href>` a few nodes
away and is captured there as itself.

The test is the **shape of the value, not the name of the attribute**. Naming
`data-mw` would encode one wiki's conventions into something that is supposed
to be a universal scrape-renderer; a value that begins as JSON is structured
data whose urls are fields inside it, wherever it came from.

es.wikipedia's capture arrow after it: **12,880 addresses, one miss, zero
inventions -- 100.0% recall and 100.0% precision.**

One consequence went unpredicted and is worth recording because it is the
right one: dedup moved 13 units from `under_dedup` to `collapsed`. The mined
urls were duplicates of the rendered links, so removing them removed real
redundancy from the trie rather than merely removing noise.

The last is the sharpest, because it contradicts the sensor's own reading.
`RENDER_CLASS` maps `presentation` and `none` to `none` -- the element has no
semantics -- and a few hundred lines away a detection was emitted whose value
was the word `"presentation"`. Two parts of one file disagreeing about the
same attribute. 155 of one eurostat page's charged inventions were exactly
that, on `svg`, `span` and `ul` alike, every value the same word.

It was found with `diagnose.py` rather than a raw diff, so the 155 are units
the metric charges rather than ones it had already forgiven. That tool was
written an hour earlier, after the raw diff produced a false account, and this
is the first thing it found.

None was visible in a headline figure, and each surfaced only from reading
values and addresses against an independently computed ground truth.

### Measuring with a proxy for the metric, and reporting the proxy's numbers

Ground truth assigned `text()[n]` ordinals by counting only non-empty text
children. XPath counts them all. So truth emitted addresses that do not
resolve: `document.evaluate` on its `.../p/text()[3]` returns an empty node
while truth recorded it as holding `", y este del"`, and the sensor's
`text()[16]` resolved to exactly the `"y"` it had recorded.

That is a real defect and it is fixed. **The account first written here of what
it cost was not real, and this section is what replaced it.**

The claim was: 115 invented and 115 lost on one page -- the same units counted
once on each side of the confusion matrix -- and roughly 230 of the corpus's
~1,290 capture errors. It made a satisfying observation, that an error can
inflate both columns at once for the same reason.

Measured, the fix changed nothing. es-wikipedia's `page->trie` reads
`fn=1, fp=119` before it and `fn=1, fp=119` after; corpus totals are 727 and
563 either way.

The 115/115 came from a **raw set difference** between trie addresses and truth
addresses, written ad hoc to diagnose. `score_arrow` does not compare that way:
it allows a match when `_owner(path)` is in `page_owners` or in
`page_ancestors`, deliberately, so that a render addressing content one level
up is not charged as invention. The index disagreement was already inside that
tolerance. The diff and the metric were answering different questions, and the
diff's numbers were reported as the metric's.

This is the rule from `CLAUDE.md` -- *name the denominator before reading the
number* -- broken by the person who wrote it, in the same session, in a form
the rule as stated did not quite cover. The denominator was named correctly for
the metric. The mistake was measuring with something else and carrying its
output across.

**The fix stays, on its own terms.** An address is the universal link between
the REPL and the page, and one that does not resolve to what it claims is
wrong whatever the scoring forgives. The drift harness's move decoding
resolves addresses rather than set-comparing them, so a non-resolving address
is a defect waiting for a consumer that takes it literally.

## How much these numbers are worth

Asked directly whether the measurements are valid and the interpretation
robust, and the honest answer has three tiers of independence and one clean
result.

### The clean result: the denominators did not move

The failure most worth ruling out is improving a rate by shrinking what it is
scored against. Across the corpus runs of one session:

| run | trie denominator | markdown denominator | trie precision |
|---|---|---|---|
| 1 | 371,594 | 320,313 | 98.90% |
| 3 | 387,398 | 335,525 | 99.70% |
| 5 | 381,802 | 332,994 | 99.82% |
| 7 | 382,741 | 333,846 | **99.94%** |

The denominators **grew** slightly -- the svg fix added units -- while
precision rose a full point. So the improvement is removal of false positives,
not denominator manipulation.

### Three tiers of independence, and what each can see

**Tier 1, `drift`: a sensor against a second sensor.** `_truth` boots another
`Sensor` on the same page and walks it whole. That catches everything the
incremental path never heard about, which is what it is for -- but it is
**self-consistency, not correctness**. "117 of 117 exact, ten deep" means the
incremental fold agrees with a cold boot of the same code. A systematic
mis-reading present in both is invisible to it, by construction.

**Tier 2, the affine arrows: the sensor against `groundtruth`.** A separate
implementation, written to disagree where the fold is wrong -- and
deliberately sharing the *addressing convention*, because two maps that
address differently cannot be compared at all. `groundtruth.py` cites
`sensor.js::stepFor` for its ordinals, and `invariants.c1` parses both walks
and checks they agree on slot resolution.

That shared convention is necessary and it is a blind spot. **An error in the
convention itself is invisible to this tier**, and one was: truth counted only
non-empty text children when assigning `text()[n]`, so both maps were internally
consistent and both were wrong about where a text node lives.

**Tier 3, `document.evaluate`: the page itself.** The only fully independent
oracle used all day. Asking the browser to resolve an address settled the
text-ordinal question in one measurement -- truth's `.../p/text()[3]` returned
an empty node while claiming to hold `", y este del"`, and the sensor's
`text()[16]` resolved to exactly the `"y"` it recorded.

It is the only check that cannot be fooled by a shared assumption, and it is
available for every address in the trie rather than only when a diagnosis
stalls. It is now a measurement of its own, `--resolvable`, with its own
artifact, and it is the strongest statement this project can make:

| the page asked about the trie's own addresses | |
|---|---|
| pages | 135 |
| addresses asked | **42,038** |
| **unresolvable** | **0** |
| mismatched | 46 (0.11%), of which 36 on one page whose cdn rotates image urls mid-measurement |
| foreign namespace | 467 |
| synthetic annotation | 1,463 |

**Every address the trie holds names a real node in the page, and holds what
that node holds.** That is the `url:xpath:markdown:content` claim tested
against the only authority that cannot be argued with, and it says nothing
about completeness -- content that never entered the trie is invisible here.

Two things no other tier could have surfaced:

- **467 addresses into `<svg>` and `<math>` do not resolve under plain
  XPath.** Those elements are in foreign namespaces and `document.evaluate`
  with unprefixed names cannot match them. The nodes are real and the
  addresses are right about the composed tree, but a consumer following one
  literally -- which is what a universal link structure implies -- gets
  nothing. It only became visible *because* the svg fix put diagram labels
  into the trie in the first place.
- **1,463 synthetic annotations** (`@control`, `@role`) have no counterpart in
  the page at all. They are the sensor's classification living in the same
  address space as content.

The checker needed four corrections before it could say any of this, each
found by reading samples and each caught before a number was reported: an
`href` compared against element text (619 of 1,581 "mismatched", every link
sampled), a synthetic annotation treated as content, foreign-namespace nodes
counted as wrong addresses, and a whole value compared against a truncated
window. `verdict()` is extracted so all four are planted as tests, together
with three that force it to still be able to fail.

### On having changed ground truth five times

A fair suspicion: each change moved numbers, and the person judging whether
they were principled is the person who wanted them. The test applied each time
-- *would I make this change if the sensor did not exist?* -- is necessary and
not sufficient.

The direction of the five is the evidence against systematic flattery, and it
is mixed:

| change | effect on the sensor's numbers |
|---|---|
| `AREA` added to control tags | better (254 phantoms became real affordances) |
| `LABEL` removed | better (misses fell) |
| hidden inputs excluded | better -- *then exposed a real sensor over-capture* |
| descend into folded controls | **worse** (options became capture misses, then a markdown recall of 5.2%) |
| text ordinals count all children | no change at all |

Two of the five did not flatter, one actively made the numbers worse and cost
two further fixes to resolve, and one changed nothing. That is not the profile
of tuning.

### How much the matching tolerance forgives

`score_arrow` accepts a match when the address's owner is a truth owner or a
truth ancestor. If that tolerance were doing heavy lifting, precision would be
an artifact of it. Measured with `diagnose.py`, which reports both:

| page | charged | forgiven |
|---|---|---|
| eurostat | 155 | 17 |
| es.wikipedia | 107 | 4 |
| musicbrainz | 0 | 2 |

Forgiveness is single digits to seventeen against hundreds charged. The
tolerance is not carrying the result.

### What the corpus cannot tell us

Frozen pages, loaded from disk. Their scripts *do* run -- that is how
ad-sync iframes and a price ticker got into the stability floor -- but
server-rendered content fetched at capture time is fixed, and pages that build
themselves from an API are thin. Coverage on a live web is not established by
this corpus and is not claimed.

Shadow DOM is the sharpest case: **7 pages of 135**, about 1,205 nodes. The
composed-tree handling rests on its fixture; the corpus corroborates and does
not prove.

### A text node larger than the budget is dropped, not split

The independent recall check found this, and no other tier could have. The
affine arrows compare against `groundtruth`, which walks the same way the fold
does; `drift` compares a sensor against a sensor. Neither notices content that
*neither* side ever reaches. `innerText` does, because layout produced it.

Two arxiv pages, adjacent in the corpus and nearly identical in structure:

| page | longest text node | in the trie? |
|---|---|---|
| arxiv 1706.03762 | 1,136 chars | **yes** -- longest trie value 1,136 |
| arxiv 2005.14165 | 1,789 chars | **no** -- longest trie value 241 |

The budget is 1,200. The abstract that fits is captured; the abstract that
does not is **absent entirely**. A reader of that page in the REPL gets the
title, the authors and the metadata, and not the paper.

**The mechanism.** `emitChunks` handles a node that overruns the budget by
descending into its children until something fits. A text node has no
children, so the recursion has no base case for it and the node is never
emitted. Splitting above the budget and merging below it is the hysteresis the
chunker is built around, and it is expressed entirely in terms of *elements*.

**The size, counted only over text a reader can see** -- excluding `<script>`
and `<style>`, whose contents the fold is right to skip:

| | |
|---|---|
| pages affected | **14 of 135** |
| oversize text nodes | 129 |
| characters unreachable | **326,820** |

and the pages are the ones this matters most for:

    RFC 2616, the HTTP spec           69 nodes   113,509 chars
    RFC 791, plain text                1 node     94,887 chars
    Pride and Prejudice (Gutenberg)   43 nodes    63,356 chars

RFC 791 is **one text node of 94,887 characters -- the whole document** -- and
the trie holds none of it.

**Why this is worse than its share of the corpus suggests.** The goal asks for
a renderer *configurable for small language model context windows*. The budget
is that configuration. As it stands, **making the window smaller silently
destroys more content**: a reader who sets a 400-character budget to fit a
small model loses every paragraph longer than 400 characters, with nothing to
indicate the loss. The knob that is supposed to adapt the map to a reader's
capacity instead deletes the page for them.

The fix is a base case: a text node over the budget is cut into budget-sized
pieces, at content boundaries where possible. It needs an address per piece,
because the trie is keyed on address and two pieces of one text node must be
distinguishable -- an offset suffix on the `text()[n]` step is the obvious
form, and it must still resolve, which the third-tier check can verify
directly.

**Taken.** Two parts, and the second only became visible because the first
worked.

`emitChunks` now treats an oversize *leaf* as its own chunk, because a text
node has no children to descend into. That recovered the content and left RFC
791 as one 94,887-character chunk, which is no more use to a 1,200-character
window than nothing was. So `collectLines` cuts an oversize value into
budget-sized pieces, breaking at a space near the boundary so a piece ends
between words.

The addressing took a correction worth recording. Each piece needs a
**distinct address**, because the trie is keyed on one -- the first attempt
gave every piece the same interned `text()@` and they overwrote each other, so
94,887 characters came back as *two* leaves. The `@offset` form already existed
for exactly this (`data-mw@496` names one match inside a longer attribute), so
a piece carries its start offset: `text()@1200`, `text()@2400`. RFC 791 now
yields 80 leaves of 1,200 characters holding 94,594 of the node's 94,887, the
difference being whitespace trimmed at the boundaries.

| | before | after |
|---|---|---|
| **capture tp** | 367,964 | **382,013** (+14,049 addresses) |
| capture precision | 99.94% | **99.94%** unchanged |
| markdown tp | 317,648 | 331,312 |
| wireframe tp | 316,654 | 330,298 |
| words a reader sees, unseen | -- | **0.49%** |
| pages showing everything | -- | **93 of 135** |
| unresolvable addresses | 0 | **0**, of 42,043 asked |
| dedup correctness | 93.77% | 93.94% |
| affordances, drift | -- | unchanged |

**14,049 addresses of content the map could not previously reach**, at
unchanged precision, and every new address resolves against the page. The
budget now does what the goal asks of it: a smaller window produces more,
smaller pieces rather than deleting the page beyond it.

### The independent recall check, and a Latin-shaped assumption in it

`visible.py` compares what a reader sees against what the trie holds **using
no addresses at all**, so an addressing mistake cannot hide a miss. `innerText`
is computed by layout rather than by anyone's walk, which is what makes it the
only independent check on recall this project has.

| | |
|---|---|
| pages | 135 |
| words a reader sees | 499,329 |
| **present in the trie** | **99.74%** |
| pages showing everything | **103 of 135** |

Getting to a number worth stating took four corrections, every one of them
the instrument and every one caught before the figure was reported:

1. **Requiring a visible line to appear contiguously in one trie value** --
   59% "missing". `innerText` lines are layout-joined runs across several
   elements: arxiv renders "Search Submit Donate Log in" from four separate
   links. Requiring that of the trie asks it to reproduce the browser's line
   breaking, which it neither does nor should.
2. **Dividing an unseen *word* count by a *line* count** -- 51%. A unit error
   in my own summary line.
3. **Stripping punctuation inside a token instead of splitting on it** --
   `innerText` joins a label span and a heading as `Title:Language Models`,
   and the token `titlelanguage` exists nowhere by construction.
4. **Gating the concatenation check on token length** -- and the gate excluded
   the case it was built for.

The fourth is the one worth keeping. `innerText` joins adjacent inline
elements with no separator where the script has no spacing convention to
apply, so a navbox of links becomes one run of letters. I gated the
segmentation check at 24 characters, reasoning that anything longer "is not a
word" -- **a Latin-shaped assumption**. Arabic words are short: `تطبيقية` +
`فيزياء`, applied + physics, join into thirteen characters and read as one
ordinary word. **133 of ar.wikipedia's 138 misses were that shape and never
reached the check meant for them.**

The gate was also unnecessary. Segmentation runs only on a *miss*, so its cost
was already bounded -- 138 attempts, not 11,814 tokens. I optimised against a
cost the control flow had already bounded, and lost 130 of 138 recoveries
doing it. ar.wikipedia went from 138 unseen to **8**, and the corpus from
0.49% to **0.26%**.

**The fifth correction replaced the segmentation rather than tuning it.**

Matching against a set of *words* could not handle `km<sup>2</sup>`, which
`innerText` renders as `km2` while the trie correctly holds `km` and `2` as
separate text nodes. `2` is not a word: it was excluded by the same
three-character minimum that stops `the` and `of` matching by chance. 246
misses on one page, every one a superscript in an area column, and no
threshold fixes it without making the check forgive everything.

Asking instead whether the run appears in **the trie's text, read in order,
with separators removed** handles every case uniformly -- a superscript joined
to its unit, a navbox of links, Arabic words joined, Chinese with no word
spacing at all. The trie holds each part separately and correctly; only the
browser's joining differs.

**The reported number got worse, and that is the evidence it improved.**
Unseen went 1,304 to 1,620 (0.26% to 0.32%) while pages showing everything
went 103 to 108. Segmentation matched held words at each position *in any
order*, so it was forgiving about 316 runs whose parts existed somewhere but
not in that sequence. Requiring reading order removed that false forgiveness.
`einsteinnewton` no longer matches a page holding `newton` then `einstein`,
and that is now a test.

The limit that remains: the check asks whether content is present *somewhere*
in reading order, not whether it is addressed where the reader would look for
it. That question belongs to the coverage arrows and to `resolvable`, and
keeping them apart is what stops one number from answering neither.

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
the snapshot path, which is the path that builds the index.

**The reassurance in the second half of that sentence used to read "the live
path supplies no map, so every position is unknown and sibling index decides,
correctly", and it was wrong.** The same sentence stood in `trie_doc_pos`, in
`insert`, and here: three copies of one claim, never checked, and each copy a
reason not to look. Sibling index decides correctly only for siblings that
*share a label*. See "The live path had no order check at all" below.

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

### The live path had no order check at all

Everything in the section above is measured through `StreamingScan.push`,
which tags the html and supplies a walk-position map. The sensor path
supplies no map, and nobody had ever asked what it does without one.

It grouped by label. `insert` gave a node's children a position by label
group -- every text child, then every anchor child -- which is right for
siblings that share a label and wrong for a parent whose children
*alternate*. A sentence with a link in it is exactly that parent, and
`tests/fixtures/mixed_inline.html` is seven lines of it:

    page            Physics studies matter and energy across space and time.
    sensor path     Physics studies / and / across / and time.
                    then [matter] / [energy] / space
    snapshot path   Physics studies matter and energy across space and time.

The two paths are meant to produce the same chunks. They produced different
sentences, and the one that ships was the wrong one.

**Nothing could see it.** Coverage compares address sets, dedup compares
values, drift compares a sensor against a sensor; sequence appears in none of
them, and the one check that does look at sequence only ever ran on the path
that was already correct. It surfaced instead through the address-free recall
check, which counted `에너지나` on ko.wikipedia as unseen -- that run exists
only when a link's text and the text node after it are adjacent, so a
reordering is precisely the shape of defect it shows up as.

The fix is to observe the order rather than derive it. The fold walks the DOM
recursively and `sensing._decode` hands the units over in that order, so
`insert` stamps each newly met DOM node with the next value of a counter.
First arrival fixes the position and only the first: a node re-offered by a
later drain has not moved, and re-stamping it would let a page reorder itself
merely by being watched.

What it moved, over the 113 pages measured in both runs:

    words a reader sees, not in the trie   1,620 -> 786   (0.32% -> 0.16%)
    pages showing everything                 108 -> 113
    page->trie          missed                493 -> 471   invented 143 -> 143
    page->markdown      missed              2,070 -> 1,937 invented 142 -> 142
    page->wireframe     missed              2,889 -> 2,754 invented  70 ->  70
    affordances missed / phantom             224 / 8, unchanged
    delete, ten deep                         117 of 117 exact, unchanged

Recall halved and not one arrow lost precision, which is what a reordering
should look like when it is corrected: the content was always there.

**One control appeared to move the wrong way, and the attribution was wrong.**
Dedup correctness read 95.15% -> 95.02% across the two corpus runs either side
of this change, `over_dedup` +40 and `collapsed` -38, +28 of it on
ja.wikipedia. That was recorded here, and in the commit, as a cost of the
ordering fix. It was not.

The controlled form of the question is one capture folded into two tries --
`doc_pos={}` reproducing the old grouping, so sibling order is the only
variable -- scored against the same ground truth:

| page | ordering | collapsed | under | over | correctness |
|---|---|---|---|---|---|
| ja.wikipedia | label-grouped | 923 | 101 | 41 | 94.13% |
| ja.wikipedia | reading order | 923 | 101 | 41 | 94.13% |
| ar.wikipedia | label-grouped | 2,497 | 107 | 43 | 98.06% |
| ar.wikipedia | reading order | 2,497 | 110 | 43 | 98.03% |

**Ordering does not move `over_dedup` at all.** The corpus comparison was not
controlled: its "before" run is from the previous day, 08-30 18:34, and
`4e1f11a` -- the sensor fix that splits an oversize text node instead of
dropping it, and which added some fourteen thousand addresses -- landed at
22:40, between the two. More units means more lineage clusters, which is where
the +40 came from. Both runs taken after that fix report `over_dedup` 617,
identically.

Two lessons, and the second is the one that keeps recurring here. A run
separated by hours is separated by every commit in those hours, so a
before/after across it is a comparison of code states and not of a change. And
the diagnosis only became available once `DedupScore` carried samples: the
counts alone supported a plausible, confident, wrong story about adjacency and
suppression, which is exactly what a count without an instance is for.

The 617 stands as a characterised gap rather than a regression. Its samples on
ja.wikipedia are navbox and citation links -- `Portal:物理学`,
`Category:物理学`, `Template:物理学サイドバー` -- lineage clusters at anchors
where the render draws no line at all. Whether those anchors should be drawn
is a separate question from ordering, and is not yet answered.

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
