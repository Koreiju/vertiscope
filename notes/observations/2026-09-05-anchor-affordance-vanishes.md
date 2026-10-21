# The anchor's affordance vanishes from the render

2026-09-05, found while building the Obsidian interactive surface.

## What happens

The tagger creates two addresses at every anchor, and `is_control` correctly
separates them:

| tag | `is_control` | `render_class` | value |
|---|---|---|---|
| `interactive.links` | **true** | link | `the next page` |
| `urls.internal` | false | link | `/next.html` |

The render keeps the second and discards the first. On

```html
<p>See <a href='/next.html'>the next page</a> now.</p>
<a href='/solo.html'>Solo link</a>
```

it draws

```
line='See [the next page](/next.html) now.'  anchor=text.visible   control=false
     inline   urls.internal                                        control=false
line='[Solo link](/solo.html)'               anchor=urls.internal  control=false
     absorbed text.visible                                         control=false
```

The `interactive.links` address appears nowhere — not as the line's anchor,
not in `inline`, not in `absorbed`. It is not collapsed into something else;
it is gone.

## How much, and of what

The loss is **specific to anchors**. Every control address the tagger made
was checked against every address the render kept anywhere — as a line's
anchor, in `inline`, or in `absorbed` — over the full 136-page corpus:

| control tag | made | survive | lost |
|---|---:|---:|---:|
| `interactive.links` | 71,866 | 7,325 | **89.8%** |
| `interactive.buttons` | 1,881 | 1,705 | 9.4% |
| `interactive.inputs` | 5,394 | 5,385 | 0.2% |
| `interactive.forms` | 1,655 | 1,654 | 0.1% |
| `interactive.event_handlers` | 495 | 495 | 0.0% |
| **total** | **81,291** | **16,564** | **79.6%** |

Anchors are 88% of every affordance on the corpus, and they are the class
that loses nine tenths of itself. Everything else is essentially intact,
which is what makes this diagnosable: the render does not discard controls in
general. An anchor has a competing unit at the same element — `text.visible`,
or the `urls.*` value — and the anchor's own affordance address is the one
that loses. The tenth that survives is the anchors with no competitor.

A ten-page sample first put links at 84.1% and the total at 79.3%, so the
figure is stable across page mix rather than driven by a few outliers.

## Why it matters

A consumer asking a line "are you an affordance?" gets **no** for roughly
five out of six hyperlinks. On the six-page toscrape workspace the sidecar
reports 105 controls across 98 chunks, all `button` or `group`, not one
`link` — on a site that is almost entirely anchors.

That is the whole premise of the read-only interactive surface: it would draw
most hyperlinks as dead text while looking like it had rendered the page.

## Why `absorbed` does not cover it

`absorbed` was built last commit precisely so that collapse stops meaning
loss, and it does record the `text.visible` drop on the solo anchor. But the
`interactive.links` address is not dropped by `_dedupe` — it is never made
into a unit the render considers, so nothing records it. Non-destructive
collapse only protects what reaches the collapse.

This is the second time the same shape has appeared. `repl._KIND_BY_TAG`
carries the note: "after the address's taxonomy slot became the render class
every one of these fell through to TEXT — so the page drew its controls and
the REPL treated them as prose." Same defect, different consumer.

## The related gap

Separately, `absorbed` addresses are carried on `MarkdownLine` and read by
nothing outside `markdown.py`. `graphstore._link_hyperlinks` builds `chunk_of`
from `line.address` and `line.inline` only, so an absorbed url gets
`cid is None` and its edge is dropped — the same defect the comment directly
above that code describes for `inline`, one field later. Measured over the
136-page corpus: **37,452 absorbed addresses have no chunk at all, 8,167 of
them urls.** Broken down by accessor the urls are mostly `src` (2,660),
`srcset` (1,167) and `href` (685), and a sample of the hrefs is dominated by
head `<link rel>` rather than navigational anchors — so the *edge* loss is
probably small, but the addresses are genuinely unindexed and nothing says so.

## Fixed

`_carry_affordance`, a post-pass in `render_trie` fed by
`_suppressed_controls(trie)`. Trie-derived and run outside the descent, for
the reason `_absorbed_by_element` and the prose fold both record: anything
gathered inside `_render_sized` moves with the context window, because that
function runs speculatively at every level the chunker considers.

The control is appended to `inline`. The address slot is never touched.

### The version that was wrong

The first attempt promoted the control into `line.address` where the line WAS
the anchor — a solo link on its own line — and demoted the url to `inline`.
It read better, and it broke the crawl.

`line.address` is the only address the store persists per line: `Anchors` is
one address per line by contract, keyed on `ord`, and `Workspace.links_from`
reads it back through `addresses_of` to build the frontier, because "no
separate link extractor: a link is a `urls.*` address, which the trie already
holds". Promoting the control pushed the anchor's `urls.internal` address out
of the store, and a page full of anchors produced an empty frontier.
`test_links_come_from_the_stored_addresses` caught it in the full suite —
1 failed, 1687 passed — which is exactly what that test was written for.

The correction is that `inline` is enough for the two things that were
actually missing: `covered` accounts for the affordance, and
`graphstore._link_hyperlinks` gives it a chunk. It is NOT enough for a
consumer reading the store, because `inline` is not persisted either — so
`obsidian.sidecar.chunk_payload` asks `addresses_at(element)` instead, which
already exists for precisely this ("every address at one element"). Widening
the `Anchors` contract was the alternative, and one-address-per-line is
depended on by the jsonl round-trip, the depth recovery and the REPL alike.

### Result

| control tag | before | after |
|---|---:|---:|
| `interactive.links` | 89.8% lost | **0.4% lost** |
| `interactive.inputs` | 0.2% | 0.2% |
| `interactive.buttons` | 9.4% | 9.4% |
| `interactive.forms` | 0.1% | 0.1% |
| **total** | **79.6% lost** | **0.6% lost** |

7,325 surviving anchor affordances became 71,592, and no other class moved —
the fix is targeted rather than a general loosening.

The end-to-end measure named below held: on the six-page toscrape workspace
the sidecar's controls by render class went from `group 54, button 51,
link 0` to `link 113, group 54, button 51`. `link` stopped being zero without
`button` or `group` inflating. Chunks (98), addresses (1,616), anchors (817)
and **link edges (5)** are all unchanged, and the **crawl frontier is back to
21** from the empty list the promoting version produced — which is the guard
that matters: the affordance did not cost the graph.

Buttons remain 9.4% lost. That is a separate, much smaller defect and is not
this one.

## What was considered

Decide where the affordance lives before changing the render. Two candidates:

1. **Keep the control address as the line's anchor** where an element has
   one, and let the url ride as `inline`. This makes `is_control` true on the
   line that draws the link, which is what every consumer already asks. It
   changes which key the positional `anchors` contract returns for those
   lines, so the jsonl round-trip, depth recovery and the REPL all need
   re-checking — that contract has broken four things at once before.
2. **Record it in `absorbed`** and have consumers ask
   `any(a.is_control for a in line.all_addresses())`. Cheaper and safer, but
   it makes affordance a question you have to know to ask, and the REPL bug
   above is what that costs.

(1) is the honest fix and (2) is the reversible one. Either way the measure
to watch is the sidecar's control count by class: `link` and `field` must
stop being zero, without `button` and `group` inflating.
