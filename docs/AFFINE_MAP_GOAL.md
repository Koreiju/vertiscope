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
