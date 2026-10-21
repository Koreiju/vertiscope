# The REPL is the browser, not a classifier

`PLUGIN_GOAL.md` carries this pivot into the plugin: the panel's browser half
renders as a browser would and dispatches interactions to the live page when
there is a connection.

## 1. What the measurements forced

Detection was rebuilt twice — a vocabulary bank with negative rejects, then
structural signals (GET query-form shape, numeric URL families, `rel=next`,
URL-parameter echo). Across 890 pages on 605 hosts it settled at:

```
search control found      70.1%
pagination found          41.3%
    ... enacted           21.9%
    ... actually advanced 15.8%
```

The second rebuild moved pagination a long way (3.9% → 15.8% advancement) and
search barely at all (65% → 70.1%). The structural signals did not *add* to
the vocabulary so much as **replace** it — `queryform` rose to 11.3% of
candidates while vocabulary hits fell from 15.9% to 4.7%.

That shape is the finding. Two independent approaches, one lexical and one
structural, converge on the same ceiling. The ceiling is not the classifier.
It is the premise: **there is no stable, learnable definition of "a search
box" or "a pager" across the open web**, because those are names for
intentions, and a page expresses intention in whatever way its author chose.

## 2. The pivot

Stop asking *what a control means*. Ask only *what it is and where it sits*.

> The REPL is a minimal browser. It renders every structure the page has, in
> the page's own arrangement, in ASCII, and the reader interacts with them
> directly. Nothing needs to be recognised as "search" for a reader to type
> into it, and nothing needs to be recognised as "pagination" for a reader to
> click it.

This is not a retreat. Classification was a *bottleneck we imposed on
ourselves*: we could only surface a control after naming it, so a control we
could not name was a control the reader never saw. Removing the naming step
surfaces everything.

It also dissolves a problem we spent a long time on. The enactment funnel —
detected 41%, enacted 22%, advanced 16% — exists because *we* were deciding
which control to press. In the new design the reader presses it. The funnel
is gone, not improved.

## 2b. Universal and objective: three tiers of evidence

The pivot only works if "render everything faithfully" is decidable without
judgement. It is, and the reason is measurable. Across five unrelated pages —
a search engine, an archive, a news site, an encyclopedia, a scraping
fixture — 9,315 elements yielded 2,392 affordances:

```
natively semantic (a/button/input/select/textarea/summary)  2,358   98.6%
explicit role=                                                 92    3.8%
any aria-*                                                    168    7.0%
opaque: no semantic tag, no role                                7    0.3%
```

**The web declares its own interactive structure, through HTML, 98.6% of the
time.** The part we genuinely cannot know is 7 elements in 2,392.

So evidence is tiered, and only the first two tiers may be load-bearing:

| tier | source | coverage | may decide |
|---|---|---|---|
| 1 | element type → ARIA role, per the HTML-AAM mapping; accessible name per AccName | 98.6% | yes |
| 2 | what the page declares: `role=`, `aria-*`, `rel=`, form `method`/`action` | ~4% | yes |
| 3 | what happens when acted on — the delta is the fact | the residual | yes |
| 4 | vocabulary, class names, label word lists | — | **hint only** |

Tiers 1 and 2 are *specifications*, not heuristics: HTML-AAM is a finite
published table, AccName a deterministic six-step algorithm. They do not grow
with the web, they do not need maintaining per site, and they are the same
computation every browser already performs for assistive technology — which
is the strongest possible evidence that they survive contact with the real
web, because screen readers have been driven by them for twenty years.

Tier 4 is where our search and pagination banks lived. That is why they
plateaued: a vocabulary is an unbounded list approximating an unobservable
thing.

### Objectivity: an independent oracle

We implement tiers 1 and 2 ourselves in the page, so we cannot validate them
against ourselves. The browser's own accessibility tree is the oracle —
computed by the engine, per spec, independently of our code. Where it can be
read (CDP `Accessibility.getFullAXTree`), agreement between our render and
the engine's tree is a mechanical check: walk both, compare node for node,
report the diff. No human decides whether a control was "really" search.

### Intent, when we actually need it

Sometimes we do want meaning — the universal bar wants to route a question to
*the page's own* search. That is still answerable objectively, by replacing
classification with **verification**:

> The search box is the field which, when submitted, changes the results.

Intent is not observable; consequences are. Type a token, submit, and see
whether the address or the result set changed accordingly. That is tier 3, it
is falsifiable, and it is what `verify` already does for pagination when it
insists a pager must actually advance the page.

The same rule retires the enactment funnel: we no longer need to decide in
advance which control is a pager. A control either produced a delta or it did
not, and the page told us which.

## 3. What replaces the taxonomy

`@taxonomy` stops being a semantic label and becomes a **render class**: what
to draw, not what it means.

| render class | drawn as | determined by |
|---|---|---|
| `heading` | `# … ######` by depth | tag |
| `text` | wrapped prose | text node |
| `link` | `[label]` | `a[href]` |
| `button` | `‹label›` | `button`, `[role=button]`, `input[type=submit/button]` |
| `field` | `[______]` with current value | `input`, `textarea` |
| `choice` | `label ▾` + options | `select`, `[role=combobox]` |
| `check` | `[x]` / `[ ]` | `input[type=checkbox/radio]` |
| `image` | colour bitmap or `alt` | `img`, `picture`, `svg` |
| `row` / `cell` | aligned columns | `tr`, `td`, `th` |
| `item` | `-` / `1.` | `li` |
| `group` | indentation only | block containers |

Every one of these is decidable from tag plus interactivity with essentially
no ambiguity. None requires knowing the author's intent. A search box renders
as a `field` because it is a field; a pager renders as `[2] [3] [Next ›]`
because those are links. Both work without being named.

The detection vocabularies are **demoted, not deleted**. They survive as
*hints* — used to order the page's affordances for a reader in a hurry, and
to label a group ("the field at the top of a query form") — but nothing about
correctness depends on them any more. A wrong hint costs a label; it no
longer costs a missing control.

### What must not be demoted

`refused()` stays exactly as strict. Safety was never a classification
problem: it is a denylist on *enactment*, and it applies whether the click
comes from the scroller or the reader. The one difference is that the reader
is now the one initiating, which is precisely the case where a wrong
autonomous press was most expensive.

## 4. The universal bar

One input, top of the screen, doing both jobs a browser needs:

```
┌──────────────────────────────────────────────────────────────────────┐
│ ▸ glacier retreat measurements                                       │
└──────────────────────────────────────────────────────────────────────┘
```

* **Looks like a location** — a scheme, a host, a dotted name, a path — then
  it is a location. Visit it.
* **Anything else** is a question, and a question fires *both* retrievals at
  once: the triple product over stored chunks, and a live DuckDuckGo scan.

The ambiguity is resolvable and rarely wrong: `example.com/docs` is a
location, `how do glaciers retreat` is not. Where it is genuinely ambiguous
(a bare word that is also a host) the bar prefers the question and offers the
location as the first row, because guessing wrong toward a search is
recoverable and guessing wrong toward a navigation is not.

## 5. Melding, in the page's own form

The results view is **DuckDuckGo's page**, rendered structure-natively — its
search field, its filters, its result rows, its "More results" control, all
in their real positions. Our stored chunks are inserted **into that same
structure**, using the row shape the page itself defines.

This is where the `shape` machinery already built earns a second life. The
sensor computes a tag-sequence shape per line and found that shapes repeat
overwhelmingly on list pages — 15 distinct shapes for 86 lines, 29 for 290.
The dominant repeating shape *is* the result-row template. So:

1. Sense the results page; group lines by shape digest.
2. The most frequent shape with ≥3 instances under one parent is the row
   template.
3. Render internal hits through that template: same nesting, same fields in
   the same order, same ASCII forms.
4. Interleave by rank, marked by provenance, not by a separate pane.

```
 ▏  🔍 glacier retreat measurements              Any time ▾   Region ▾
 ▏
 █   Satellite gravimetry of ice-sheet mass change
 █   nasa.gov › grace › data                                    ddg
 █   > Monthly solutions resolve basin-scale mass change …
 ▏
 █   Ice loss measured from orbit                                 ·
 █   archive.org › details › icelossorbit · §4 Methods         local
 █   > Satellite gravimetry resolves mass change at basin scale …
 ▏
 ▏   Glacier mass balance datasets
 ▏   wgms.ch › data                                              ddg
 ▼   ‹More results›
```

A reader sees one results page. The `local` / `ddg` marker is the only thing
we add, because a reader must be able to tell what came from where — but the
*form* is the site's, not ours.

Scrolling to the bottom shows whatever that page puts there. If it is a
"More results" button, it renders as `‹More results›` and pressing it presses
the real one. No pager needed detecting; it was rendered because it is a
button.

## 6. O(delta) is unchanged, and now reaches the view

Nothing about the sensor changes. It still folds the composed tree, still
maintains a digest per node, still emits only the chunks whose digest moved.
Every variant and the comparison against the original deep serializer remain
exactly as valid — they measure the chunking substrate, which this pivot does
not touch.

What the pivot *adds* is that the same delta now drives rendering:

```
mutation → dirty path → fold → changed chunks → changed render lines
```

Today a delta produces changed chunks and the whole document is re-rendered
from the accumulated set. Under the pivot, a chunk carries enough to draw
itself — render class, depth, label, value, and the address to enact — so a
changed chunk repaints its own lines and nothing else. The view becomes
O(delta) too, which matters exactly where it always mattered: a feed that
appends while you read.

The chunk record gains three fields and loses none:

```
kind     the render class above
enact    the address to click/type into, when interactive
state    current value / checked / expanded, for controls
```

`kind` replaces the semantic taxonomy in the address's `@taxonomy` slot. The
`@regex-addr` slot keeps its job as provenance — now recording *why this was
drawn this way* rather than *what we thought it meant*.

## 7. What we measure instead

The old acceptance question — "was search detected?" — is retired with the
premise that produced it. Two better ones replace it, and both are objective:

**Fidelity.** Every interactive element in the composed tree should appear as
an affordance in the render, in document order, at the right nesting depth.
That is countable: `interactive elements in DOM` vs `affordances rendered`,
per page, with the misses listed. No judgement about meaning is involved.

**Enactability.** Every rendered affordance should be activatable — its
address resolves, and acting on it produces a delta. Also countable, and it
subsumes what the old enactment funnel was trying to measure without needing
any control to be classified first.

Retrieval keeps its existing measures: the triple product, the falsifiable
"a query with no answer returns none", and the variant sweep against the
original serializer.

## 8. Migration

Nothing here requires a rewrite; it is mostly a re-pointing of parts that
exist.

1. **Add the render class** to `taxonomyOf` as a second return value,
   computed from tag and interactivity. Keep the semantic label alongside it
   as a hint. Both travel in the existing address.
2. **Teach the renderer the classes** — the REPL already draws links,
   headings, tables and fields; extend to `button`, `choice`, `check`,
   `group`, and make every affordance carry its enact address.
3. **Collapse the bar.** One input replaces `open` and `search`; route by
   location-vs-question. Keep the commands as aliases for scripting.
4. **Meld** by extracting the dominant row shape from the live results page
   and rendering internal hits through it.
5. **Stop autonomous enactment.** The scroller keeps scrolling; it stops
   pressing. `refused()` stays for reader-initiated actions.
6. **Swap the acceptance checks** in `verify` from detection rates to
   fidelity and enactability.

Steps 1, 2 and 6 are the load-bearing ones. Steps 3–5 are small once the
render classes exist.

## 9. What this costs

Honesty about the trade: a reader loses the *summary* a classifier gives —
"this page has a search box and a pager" — and gains the page itself. For an
autonomous crawler the classifier is what you want; for a reader driving a
browser, the page is. This design chooses the reader, and the crawler keeps
what it needs anyway, because the hints survive as hints.

The other cost is that fidelity is a harder bar than detection. Rendering
every affordance faithfully means the misses are visible: a control we draw
in the wrong place is obvious in a way that a control we failed to classify
never was. That is a feature — it is the same reason the sweep's control arm
was worth building.
