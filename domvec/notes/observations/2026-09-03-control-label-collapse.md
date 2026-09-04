# The all-inline collapse costs every control inside prose its label

**Measured, fix prototyped and NOT shipped.** The numbers below are from a
working prototype; the reason it is not in the tree is at the bottom.

## What happens

`content_tagger` emits an element whose children are all inline as ONE text
unit at that element, and adds every descendant to `_skip_text_ids` so the
words are not counted twice. For

    <p>See the <a href="/rates">retreat rates</a> and
       <a href="/mass">mass balance</a>.</p>

that is **two** text units for five elements: `/p` and nothing else. Both
anchors hold an href and no words.

That is right for the words as PROSE and wrong for the same words as a
LABEL. The two are the same string with different jobs, and only one was
being recorded. Downstream:

* the render draws `</rates>` instead of `[retreat rates](/rates)`
* the REPL's acts listing names links after their targets
* `--reach` counts **1,175** controls over the corpus whose words the page
  shows and the fold does not address at them

The third is the largest single loss in the pipeline before vectorisation,
and it is one defect with one cause rather than a long tail.

## The prototype

A block in the interactive section emits the control's own label at its own
xpath, but only when the element would otherwise emit nothing, so it adds a
label where there was none and never a second copy of one.

The label must be built WITHOUT the node's own tail. `get_text(recursive=
True)` walks `iter_all()`, which yields self first and appends each node's
text AND tail, so the first attempt labelled the link `retreat rates and` --
swallowing the prose that follows it. Self's text plus each descendant's
text and tail is correct: `retreat rates`, `Hacker News`, `new`, `ask` all
came out right.

## What it buys and what it costs, over 30 corpus pages

| | baseline | prototype |
|---|---|---|
| controls whose words are unaddressed | 1,175 (corpus) | **0** |
| drawn | 98.29% | **99.66%** |
| rendered lines | 57,928 | 67,540 (+16.6%) |
| characters | 3,206,324 | 3,351,003 (+4.5%) |
| **chunks** | 6,718 | **7,344 (+9.3%)** |
| duplicate-line rate | 41.44% | 40.13% |

All 135 render and markdown tests pass with it.

## Why it is not shipped

The label lands on its own line, above the target:

    retreat rates  act(0)
    </rates>

where one line belongs:

    [retreat rates](/rates)  act(0)

So the +9.3% chunks -- a direct charge against the context-window budget the
whole recursive-chunking design exists to respect -- buys a representation
that is still wrong, and slightly worse to read than what it replaces.

## What the finished version needs

`_render_unit`'s `cat == "urls"` branch returns `f"<{value}>"` while
`text_at_node` sits unused in its signature. Drawing `_RENDER_FORM["link"]`
there, and consuming the standalone text unit the way `consumed` already
does for `category == "interactive"`, collapses the two lines into one --
which should take the +16.6% line growth back out and leave the label.

That is not a small edit. `_dedupe`'s comment records the exact bug it
invites: the href is hidden because the anchor speaks, and the words are
consumed because the link would draw them, so on a search-results page where
every title is an `<a>` inside an `<h2>` **both went and the result had no
title at all**. Whichever is dropped, exactly one has to remain, and the two
suppressions are computed in different passes.

Do the renderer half first, then the tagger half, and measure both against
`--reach` and the line/chunk counts above.

---

## Update, same day: the renderer half landed, the other two are blocked

**Landed (`c2f2758`).** `_render_unit`'s `urls` branch now draws
`[words](target)` and consumes the text unit. Suite green at 1666. It gets
SMALLER while gaining labels -- lines -14.8%, chunks -2.1%, chars +2.3% --
and moves the new `labelled` column from 28.92% to 37.08%.

That column had to be added because this change moved nothing `--reach` could
already see: `drawn` counts an xpath however its line reads, so a control
drawn as a bare destination scored the same as one drawn with its name.

**Blocked: the tagger half.** It contradicts a named invariant.
`test_an_inline_only_subtree_is_still_one_detection` asserts that for

    <p>See <a href='/a'>Alpha</a> and <em>Beta</em> for more.</p>

the address `/html/body/p/a` must NOT exist -- "prose with links in it stays
one line rather than shattering into a fragment per anchor". Emitting the
control's own label creates exactly that address. Four tests fail on it: that
invariant, both REPL pager tests, and `test_link_edges_reach_the_graph`.

This is a design decision and not a defect to fix quietly. The question it
poses: is a control's label a SECOND detection at the anchor, or does the
one-detection rule outrank a link's right to be named? The measured stake is
1,175 controls corpus-wide whose words the page shows and the fold does not
address, and roughly 34 points of the `labelled` column.

**Blocked: folding links into the sentence.** Substitutes each link's markup
back where its words sit in an ancestor's prose, so

    [retreat rates](/rates)
    [mass balance](/mass)
    See the retreat rates and mass balance .

becomes one line: `See the [retreat rates](/rates) and [mass balance](/mass) .`
with both anchors on `line.inline` and both markable by `read()`.

It fails `test_suppressed_units_are_a_deliberate_choice_not_a_leak`: 73 url
units vanish with no duplicate kept at the SAME element, because the href now
lives on the parent's line and the anchor's address survives only on
`inline`. That may be the `anchors`-vs-`covered` distinction this codebase
already draws, but the test states a contract and changing it to suit the
change is the wrong order of operations.

Two things learned building it, worth keeping whoever finishes it:

* **Match on any ANCESTOR, not the parent.** The collapse happens at the
  outermost all-inline element, often several levels up: `<body><span><b><a>`
  puts the text unit on `body` while the anchor sits at `body/span/b/a`.
  Keying on the parent found nothing on exactly the pages it exists for.
* **It must not live in the descent.** `_size_of` and `_descend` call
  `_render_sized` speculatively at every level they consider, so an
  O(lines x links) pass there runs many times per emitted chunk: the 30-page
  render went from 22.2s to past 500s. Hoisted to one pass per finished chunk
  it costs 23.3s, +5%. `render_trie`'s report block already records this
  hazard in its correctness form.

  The hoist has a price: sizing then measures the UNFOLDED text, so chunks
  come out under-filled -- 7,015 against 6,216 for the in-descent version.
  Recoverable by re-packing after the fold, if chunk count ever matters more
  than render time.

**If all three were adopted**, measured together on 30 pages: labelled
71.43%, controls with unaddressed words 0, drawn 99.66%, reachable 100.00%,
lines -25.5%, chunks +4.4%, render +5%.

**A caution on the `labelled` column itself.** It produced two false signals
while I was building this, both making the code look worse than it was. It
compares against `get_text(recursive=True)`, which pulls image alt text, so a
link correctly drawn as `[Western Europe sets new temperature record...]`
scored unlabelled because the parse saw the photo caption first -- roughly
2,000 of the cases behind an earlier "63% unlabelled" claim. And keying on
the first line carrying an address read the fold as a 10.6-point regression
that was really a tooltip line winning a `setdefault`. The second is fixed;
the alt-text confusion is not. Trust deltas measured the same way; treat the
absolute value as soft.
