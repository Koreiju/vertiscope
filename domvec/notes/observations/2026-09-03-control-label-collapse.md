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
