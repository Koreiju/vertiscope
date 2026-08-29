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
