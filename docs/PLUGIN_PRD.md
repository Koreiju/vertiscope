# The Obsidian plugin — product requirements

Every requirement here is traced to something the user actually asked for, and
each one carries the user's own wording. Where a requirement is paraphrased it
is marked as such; where it is quoted, the quote is exact.

This is the *what*. `OBSIDIAN_BRIDGE.md` is the *how* and *why* — the design
record, the defects found, and the reasoning behind each mechanism. When the
two disagree, this file says what was asked for and that one says what was
built; the disagreement is the bug.

`PLUGIN_GOAL.md` holds the user's verbatim statement of the whole plugin and
outranks this file: several things it asks for have no requirement number here
yet, and its closing section lists exactly which.

**Status vocabulary.** `Done` means built *and* verified in the running app
over CDP, never by screenshot (see R-I1). `Partial` means built with a
measured shortfall, and the shortfall is stated. `Open` means not started.

**47 requirements: 32 done, 8 partial, 7 open.**

Counted from the tables below, which are the authority. An earlier tally of
"41: 29 / 9 / 3" was given in conversation and was arithmetic error, not a
different reading — no requirement was added or dropped between the two.

---

## Measured baseline

These are the numbers the partial requirements are short against, all taken on
`build/vaultws512` — 24 pages of the frozen corpus, 3,136 chunks, a 512-token
window, real nomic embeddings.

| measure | value | what it means |
|---|---|---|
| structural reach | 35.2% mean, 18.5% median | share of a page's visible, non-wrapper elements under a chunk root that the chunk addresses |
| reading order | 76% | chunks whose addressed elements appear in document order |
| containment | 831/831 (100%) | ancestor pairs still nested after distillation |
| depth correlation | 1.00 | page nesting order vs drawn nesting order |
| duplicate chunks | 420 of 3,136 (13.4%) | markdown identical to another chunk |
| billboards | 187 of 253 textured (74%) | nodes carrying a picture that renders |
| resolved graph edges | 613, 1 dangling | vault edges from exported notes |
| chunks over window | 39 (1.2%) | single indivisible units |
| chunk size | median 199 tokens, p90 452 | against a 512-token window |

Two of these are **near-tautological and must not be read as design quality**:
`containment` and `depth correlation` come out perfect because the render
indents by trie depth and trie depth mirrors DOM depth. They confirm the
absence of a bug. They are not evidence that structure is preserved — `reach`
and `reading order` are, and those are the two that are short.

Reproduce with:

    python scripts/structural_fidelity.py --workspace build/vaultws512
    python scripts/xpath_shape_analysis.py --workspace build/vaultws512
    node obsidian-plugin/cdp.mjs --file obsidian-plugin/probes/graph-edges.js

---

## A. The panel — the artifact view

| # | Requirement | Status |
|---|---|---|
| R-A1 | "interactive interface that is slim with the markdown-centric chunks with interactives themselves" | Done |
| R-A2 | "distilled DOM rendered as interactive obsidian object structures … as shown by the rendered and interactive fields where 'properties' is" | Done |
| R-A3 | "we don't need 'properties' at the very top of each panel … remove this top panel" | Done |
| R-A4 | "at the very top of each panel, we can have a simple switch between the markdown and the shadow DOM button" | Done |
| R-A5 | The panel occupies the top of the note *(implied by R-A3: the panel takes the place properties vacated)* | Done |
| R-A6 | "the whitespace could be a little tighter to border the content" | Done |
| R-A7 | "there is quite a bit that is duplicated/exploded" — a chunk draws each thing once | Done |
| R-A8 | "remove the duplicate prose below the panel" | Done |
| R-A9 | "Images, interactive fields rendered properly" | Done |

**R-A2** renders into a shadow root carrying its own stylesheet, written in
Obsidian's own custom properties so a control follows the reader's theme.
Obsidian's native property rows are the visual reference.

**R-A3** is the vault setting Obsidian's own Appearance pane writes
(`propertiesInDocument: hidden`), not a plugin reaching around it. The
frontmatter stays — `cid` is what the graph, the link map and the chunk pane
resolve on — it is only not drawn.

**R-A4** shows *both* states with the live one marked. A single button
labelled with the other state is ambiguous exactly where it matters: it can
equally mean "you are looking at markdown" and "press for markdown".

**R-A6** verified 813px → 183px on one chunk, old spacing against new on the
same content.

**R-A7** verified live: 5 lines, 5 distinct, nothing repeated. A product card
had been drawing its title five times — the image's alt, the picture's
caption, the wrapping div's visible text, the anchor's `title`, and the
heading. All five are real addresses; markdown must spend a line on each
because a line is all markdown has, and HTML need not.

**R-A8** folds the prose into a collapsed callout rather than deleting it. A
callout is a blockquote, so the wikilinks in it are still parsed into the
graph, Obsidian's search still finds the words, and the file stays a
plain-text archive. Deleting outright would cost every vault edge unless the
links moved to frontmatter.

---

## B. Two forms, one distillation

| # | Requirement | Status |
|---|---|---|
| R-B1 | "markdown-centric chunks … **or** a more pure html extension to render original web content directly but still in distilled, organized, and slim minimal-html chunks, where we can keep the interactive and the static/media asset components" | Done — both |
| R-B2 | "Switch between read-only interactive web elements and markdown distillation renderings" | Done |
| R-B3 | "aligned to the same graph RAG database with triple retrieval" | Done |
| R-B4 | "a simple button or hotkey" | Done |

**R-B1** was offered as an either/or and both were built. The markdown form
*reconstructs* widgets from a rendering; the HTML form emits an `<input>`
because the trie says the element is a control. Both are built from **one
payload** — the same line-to-address alignment used twice — so a chunk cannot
say one thing in one form and something else in the other.

**R-B4** ships the switch and a command. No default hotkey: Obsidian asks
plugins not to claim one, and a conflict is silent.

---

## C. Structural fidelity — the weakest area

| # | Requirement | Status |
|---|---|---|
| R-C1 | "If there is a possible way to retain as much as the original web interface while keeping the distilled html something that could be rendered, that would be a big deal" | **Partial** — reach 35.2% |
| R-C2 | "the structures like boxes and nested things can stay and be reconstructed from the patricia trie path nodes perhaps if we stick to absolute xpaths" | **Partial** — reading order 76% |
| R-C3 | "matching cartesian coordinates kind of thing on the page (as in we keep all our structures distilled, but localized enough still such that we can render them as their intended cohesive structures)" | **Partial** — see the constraint below |
| R-C4 | "switch to a more generalized xpath structure that keeps absolute structure with agnostic array indices for multiple/repeat fields like menu items, paragraphs, search results" | Done — as a second field, not a replacement |
| R-C5 | "chunks should be at their context window limits and measured using markdown renderings for token counts" | **Partial** — one chunk is 15x the window |
| R-C6 | "Our chunking should be such that, for example, we get search results as singular chunks" | Done |
| R-C7 | "…and semantic + frequency vectors" | Done |

### Acceptance criteria for the partials

**R-C1 — reach ≥ 60% mean.** Today 35.2%. Some of the gap is deliberate
(dedup, suppressed taxonomies, hidden elements) and some is loss; nothing yet
separates the two, so the first task is to classify the unreached elements
before trying to reach them. A reach number that rises by un-suppressing noise
would be worse than the one it replaced.

**R-C2 — reading order ≥ 95%.** Today 76%: a quarter of chunks draw their
elements in an order the page does not present them in. Reading order is the
one structural property a reader notices immediately.

**R-C3 — a stated constraint, not a shortfall to close.** The sensor captures
**no box geometry, by design** (`tests/test_no_box_geometry.py` enforces it),
so literal cartesian coordinates are not available and cannot be without
changing the sensor's contract. What stands in for them is *containment*: the
distilled tree's nesting is the page's grouping, and the record rule (R-C6)
makes each group a chunk, so a chunk arrives already localised to one cohesive
thing. A group holding one picture with words beside it is drawn as a card.
**Accepting containment-as-geometry, or changing the sensor to capture boxes,
is a decision for the user — not one to settle by implementation.**

**R-C5 — the window is not enforced on a single oversized VALUE.**

Reported by the user, who opened the note; the board had it as MET. The
metric was `chunks_over_window`, which counts how MANY chunks exceed the
window and never by how much, so 1.2% read as met while one chunk sat at
**7,745 tokens against a window of 512 — fifteen times over**. The board now
carries `worst_overflow_ratio` beside it, with a bar of 1.5x, so this cannot
hide again.

It was read first as a chunking problem -- one value too big to cut -- and an
offset-splitter was written for it twice, and reverted twice, because the
worst chunk did not move. The user's own reading was the correct one:
**under-chunking**. Not a value that resists division, a value that should
never have existed.

data.gov.uk's publisher filter is a `<select>` of 1,511 `<option>` elements.
The tagger names a control with `_own_label`, which walks every descendant --
right for `<button><span>Menu</span></button>`, wrong here, because a
listbox's descendants are its OPTIONS, and the tagger already emits each one
as its own `interactive.inputs` detection at its own xpath. So the option list
was recorded twice: once as 1,509 addressed lines, and once more as a single
43,542-character label on the select. The reader got a wall of text with one
address for 1,511 things, sitting beside the same content properly addressed.

The browser is the authority on what a collapsed select draws, and
`analytics/groundtruth.py` already wrote the rule down -- "a `<select>` draws
the one value it holds". `_chosen_option` makes the tagger agree: the option
carrying `selected`, and otherwise nothing. Falling back to the first option
was tried and rejected as a fabrication -- this filter opens on an empty
`<option value="">`, so the box a reader sees is blank, and naming it after
the first real entry would report a filter as applied when it is not. The
control still renders (`[ ] select`), and the `<label for=publisher>` beside
it still says `Publisher`.

Measured over the frozen corpus, in-process, with the change toggled on
identical input:

| | before | after |
|---|---|---|
| worst chunk | 7,745 tokens (**15.1x**) | 2,997 tokens (**5.9x**) |
| chunks | 22,504 | 22,500 |
| distinct addresses | 335,982 | 335,982 |
| covered addresses | 287,763 | 287,762 |
| `chunks_over_window` | 0.72% | 0.72% |

Four chunks disappear -- the four aggregates, on the corpus's four listboxes.
No address is lost from the trie.

**What remains, and why it is a different problem.** The new worst chunk is
Project Gutenberg's *Pride and Prejudice*, `/html/body/p[1099]` -- Darcy's
letter, one genuine paragraph of 2,997 tokens. That IS a single indivisible
unit, and it is the case the offset-splitter was really for. Two constraints
bind any such split and the reverted attempts held neither:

* It cannot consult the window. `test_no_address_is_lost_when_the_window_
  changes` holds that the covered address set is identical at every setting,
  so cutting at the window would mint window-dependent addresses -- 713 of
  them, measured.
* It must run where every path sees it, not inside `_emit_runs`.

The vocabulary is already there: `text()@412` is a documented accessor form
and `sensor.js` cuts long text into budget-sized pieces addressed by offset.
The offline path does not yet.

Acceptance: `worst_overflow_ratio` <= 1.5x with the covered address set
unchanged across windows.

**R-C4 — the measurement, and what it says.**

    addresses                   23,654
    distinct by shape            2,831   (88.0% fewer)
    shapes covering >1 element   1,290   median 5, p90 31, max 1511
    of those, holding DIFFERENT content
                                 1,022   (79.2%)

The premise holds: the corpus really is mostly repeated templates. The naive
form does not: four shapes in five cover elements that say different things,
and `/html/head/script` alone covers three unrelated script urls. An address
is a *pointer* — the REPL presses it, `enact` resolves it against a live DOM,
the store keys chunks on it — and a shape cannot point at either sibling.

**The design that follows:** keep the indexed absolute xpath as the identity,
add the shape as a **second, derived field** on `ContentAddress`. Additive, so
no key changes and no rows migrate — the same rule `render_class` already
follows. It buys grouping across repeats, retrieval by template ("every result
row"), and stability across re-scans, since an inserted sibling shifts every
index and no shape.

**What it will not fix:** of the 420 duplicate chunks, only 97 are the same
template on the same page. Most duplication in the projector is repeated
*content* at unrelated places, which wants content-hash dedup — a separate
change (R-E3a below).

---

## D. Graph and links

| # | Requirement | Status |
|---|---|---|
| R-D1 | "plugs into Obsidian graph view" | Done |
| R-D2 | "Align markdown graph view links with web links with web chunks" | Done |
| R-D3 | "Clickable markdown deciding which vault artifact to inline hyperlink via the panel's full patricia trie address" | Done |
| R-D4 | "Source the right other plugin packages first to see how they work, then fork findings over" | Done |

**R-D1** deliberately does not touch Obsidian's own graph view. It has no
plugin API, and the one community plugin that extends it patches undocumented
internals and warns in its own README that settings can be lost. Real
wikilinks in real notes make the native graph work for free.

**R-D4** produced the decision behind the shadow root: of Obsidian's
HTML-rendering plugins, those taking *arbitrary* markup all sandbox in an
iframe, because arbitrary markup carries scripts. `html-blocks` is the
exception and uses a shadow root per block, for style isolation. Ours is
neither arbitrary nor scripted, so the iframe's isolation buys nothing and
costs the two things that matter — event wiring to trie addresses, and
Obsidian's CSS variables reaching in.

---

## E. The 3D projector

| # | Requirement | Status |
|---|---|---|
| R-E1 | "equivalent-dimensional pre-UMAP concatenations of the frequency vectors to the same dimensionality as the semantic ones, and then a final-stage concatenated UMAP with equal information dimensions" | Done |
| R-E2 | "some HSV dimensions as well to the UMAP to make it 6D" | Done |
| R-E3 | "Image and media billboards for distilled HTML" / "images should show in the 3D viewer" | **Partial** — 187/253 |
| R-E4 | "For each 3D node … when I click, I should only see the chunk itself as either structured markdown or interactive HTML" | Done |
| R-E5 | "3D projector has no viewable nodes" — the view must show its nodes | Done — **re-broken and re-fixed**, see R-J4 |

**R-E1** verified: `frequency + semantic · equal halves of 768 · equalised
true`, on real nomic vectors.

**R-E2** spends three of six components on hue, saturation and value from the
*same* fit. Colour was a hash of the host, which is a legend, not a
measurement. `fitted_dims` is reported beside `requested_dims` and the colour
is dropped when the fit could not produce it — asserted from the measured
width, never from the intention.

**R-E3 acceptance: ≥ 95% of nodes carrying a picture render it.** Today 74%.
The 66 failures are dead asset urls in a frozen corpus, not a code path — a
live re-scan is the test, not a fix.

**R-E5** was a real failure with two causes, both worth keeping in view: the
projection arrived off-origin at a scale that moved with the corpus, and
`zoomToFit` only adjusts distance along the current view direction, so a
camera inside the cloud is "fitted" from inside it. Measured: 0.32% of pixels
lit from inside, 5.56% from outside. The layout is delivered centred in a
known cube and the camera is *placed* before it is fitted; a **recentre**
button exists because a reader who orbits inside has no way back.

### Proposed, not yet requested

**R-E3a — content-hash dedup of chunks.** 13.4% of chunks are exact markdown
duplicates, and walking four hops from a real article lands on two distinct
nodes both reading "Games". This inflates the projector and the embedding
matrix. Flagged here because it was *observed*, not asked for; it needs the
user's call, since two identical chunks at different addresses are arguably
two real things.

---

## F. Retrieval and editing

| # | Requirement | Status |
|---|---|---|
| R-F1 | "a `/` gesture in the markdown panel rendering a Kindle/Kobo-style inline retrieval template" | Done |
| R-F2 | "Retrieval interlaced with content editing" | **Partial** |
| R-F3 | Triple retrieval — frequency · semantic · pagerank | Done |

**R-F2** inserts a retrieved passage into the note with its wikilinks
rewritten. What is not built is the *interlacing*: retrieval does not follow
the cursor, and editing does not re-fire retrieval. Acceptance is undefined
until the user says which of those two directions matters.

---

## G. The live-browser port

| # | Requirement | Status |
|---|---|---|
| R-G1 | "Selenium navigations ported from interactions with the shadow DOM distilled in its Obsidian form" | Done |
| R-G2 | "so the user scrolls and interacts in Obsidian while the Selenium remote browser does the real scanning and endpoint interactions" | **Partial** — no scroll |
| R-G3 | "or the graph RAG database purely when offline" | Done |

**R-G1** is the one write path in the bridge and it is off by default, behind
four gates: the server flag (`--enact`), the refusal set mirrored from
`sensor.js`, an address that must already be in the store, and same-page-only
navigation. Verified end to end: a control in a note drove Firefox to
books.toscrape and reported `did: press`.

**R-G2 acceptance: scrolling the panel drives the remote browser's scroll and
the resulting delta re-enters the store.** Today `enact` supports
`press | type | read` only. This is the half of the requirement that makes the
vault a *viewport* rather than a remote control, and it is the largest unbuilt
piece of the pivot.

---

## H. Private, and offline

| # | Requirement | Status |
|---|---|---|
| R-H1 | "Interact with artifacts as live or passive shadow DOM surfaces purely locally without internet" | **Partial** |
| R-H2 | "Interactive pages that are completely private?" | Done |
| R-H3 | "endpoint features that may or may not be locally runnable without internet connections" | **Open** |

**R-H2** is a property of the design rather than a setting: the sidecar is
loopback-only, the notes are files, retrieval and the graph run against the
local store, and the distilled HTML fetches exactly one kind of thing — a
picture — which is off by default. Fetching a page's assets from a vault tells
those hosts the page was read again, at a new time, from a new address.

**R-H1 acceptance: reading, retrieval and the graph work with no process
running.** Today the notes and the native graph do; the panel and the 3D view
need the loopback sidecar. Closing this means either shipping the chunk's HTML
into the note (which reintroduces the duplication R-A8 removed) or accepting
the sidecar as part of "local".

**R-H3** is untouched. A chunk is a readable, pressable surface, not a
self-contained runnable one.

---

## I. How the work is done

| # | Requirement | Status |
|---|---|---|
| R-I1 | "Enforce using MCP/plugin based devtools that can be searched and installed rather than screenshots whatsoever please" | Done |
| R-I2 | Search Obsidian's catalogue *and* the web before building *(paraphrased from two prompts)* | Done |

**R-I1 is binding and has a reason.** A screenshot answers less than a probe
and captures whatever else is on screen. Verification runs over CDP against
the live renderer — the plugin registry, the command list, the workspace, the
DOM, computed styles, WebGL draw calls. `obsidian-plugin/cdp.mjs` and
`probes/` are the instrument.

Two traps that made a working plugin look dead, both now handled in `cdp.mjs`:
Chromium suspends layout in an **occluded** window — a terminal in front of
Obsidian is enough — so every measurement returns zero; and Obsidian keeps a
**hidden source-view copy** of every rendered block under a `display:none`
ancestor, which `document.querySelector` finds first.

---

## J. The projector must be legible

From `PLUGIN_GOAL.md`: *"We also need to pay attention to inter-spatial
normalization on UMAP nodes since most are way too compressed together to see
anything discernable."*

| id | requirement | status |
|---|---|---|
| R-J1 | Adjacent nodes must be visually separable: the **median** nearest-neighbour distance is at least one rendered node diameter | **Open** — measured at 0.037x |
| R-J3 | The tightest crowding is duplicate content, not projection, and is answerable to `duplicate_chunks` — not to a spatial fix | **Open** |
| R-J4 | The camera frames the cloud from the DATA, never from node radius | Done — 0% → 100% of nodes on screen |
| R-J2 | Node size follows the layout's real local density, not an assumed uniform spacing | **Open** |

**R-J1 — measured, and it is not one bug but two assumptions 27x apart.**

Over the 3,135-node layout the sidecar serves today:

| | value | as % of the 882.5-unit bounding diagonal |
|---|---|---|
| nearest-neighbour p05 | 0.090 | 0.0102% |
| nearest-neighbour p50 | 0.757 | 0.0857% |
| occupancy, 32^3 grid | 182 of 32,768 cells | **0.56%** |
| half the nodes | 37 cells | 0.11% of the box |

The extent is NOT the problem, which matters because that is what was fixed
last time: `_EXTENT` centres and scales the cloud into a known cube, and the
cube is duly 600 x 540 x 356. Rescaling a clumped cloud leaves it clumped.
What is wrong is the distribution inside the cube.

**Half of it is one parameter.** `build_layout` passes UMAP's default
`min_dist=0.1`, which is the tight-packing setting. Refitting the same
vectors, same seed:

| min_dist | nn p50 % | nn p05 % | occupancy % | busiest cell | half the nodes in |
|---|---|---|---|---|---|
| **0.10** (ours) | 0.0733 | 0.0093 | 0.45 | 119 | 24 cells |
| 0.35 | 0.1786 | 0.0521 | 0.70 | 112 | 36 cells |
| 0.60 | 0.3353 | 0.1160 | 1.63 | 47 | 96 cells |
| 0.90 | 0.4445 | 0.1757 | 2.11 | 33 | 123 cells |

Monotone: 6.1x on median separation, **19x on the 5th percentile** — the
crowding that actually hides nodes — and 4.7x on occupancy, for one number and
a refit. It trades cluster tightness for even spacing, which is the right
trade for a surface whose job is browsing.

**R-J2 — and it is still not enough, because the renderer sizes for a cloud
it does not have.** `graph.ts` computes `spacing = 2 * extent / cbrt(n)` and
`relSize = spacing / 8`, with radius `cbrt(val) * relSize`. That is the
spacing of a *uniform* cloud. At n=3,135 it yields a node radius of roughly
10-20 units against a measured median separation of **0.76 units** — the
renderer is sized for neighbours about 27x further apart than they are, so
every node is drawn overlapping dozens of others. Even at `min_dist=0.9` the
median separation is only ~3.9 units, still well under one node diameter.

So the fix is both halves: spread the distribution, *and* size nodes from the
layout's real nearest-neighbour distribution rather than from `cbrt(n)`. The
layout already computes the positions; shipping their nn quantiles in the
report costs one `cKDTree` query and removes the renderer's need to assume.

**R-J3 — why the criterion is pinned at the MEDIAN, and was wrong at p05.**

The first version of R-J1 asked for the 5th-percentile separation to clear a
node diameter. That criterion cannot be met and should not be: the tightest
pairs are not a projection failure. Of the closest 5% of neighbour pairs,
**98.7% share a url and 54.5% share a title** — against 7.0% same-title among
the furthest quarter, and 22.8% over all pairs:

| pairs | same url | same title | same token count |
|---|---|---|---|
| closest 5% | 98.7% | **54.5%** | 30.1% |
| closest 25% | 96.0% | 42.3% | 24.0% |
| furthest 25% | 84.6% | 7.0% | 3.3% |
| all | 88.7% | 22.8% | 12.5% |

Those are near-duplicate chunks off one page. Their vectors are nearly
identical, so they land on each other — which is the projection being
*correct*. No `min_dist` and no normalization can separate points that mean
the same thing, and pushing them apart would draw a distinction the data does
not contain. That crowding is answerable to `duplicate_chunks` (13.2% on the
board), which is a chunking metric, and it belongs there.

The median is where the projection actually governs: 0.757 units against 41.0
for a uniform cloud of 3,135 points in this cube — **54x below uniform**,
where p05 is 456x below and mostly duplicates.

**Inter-spatial normalization, measured.** A per-axis quantile transform
(each axis through its own empirical CDF, so the order along every axis is
preserved exactly and only the spacing changes), applied to the layout as
served:

| | as served | quantile-normed |
|---|---|---|
| nn p50 (units) | 0.757 | **3.658** |
| nn p05 (units) | 0.090 | 0.469 |
| occupancy % | 0.56 | **3.41** |
| busiest cell | 71 | 36 |
| 10-NN neighbourhood kept | 100% (ref) | **80.2%** |

4.8x on the median for 20% of the local neighbourhood structure. That trade is
a decision, not an obvious win, and it is recorded here rather than taken.

**R-J4 — the camera was a node-size servo, and it emptied the pane.**

`zoomToFit` frames node bounding SPHERES, so the distance it chose was a
function of node RADIUS and not of where the nodes are. Measured over CDP on
this corpus: at `nodeRelSize` 5.124 it settled at 148.9, at 0.126 it settled at
3.67 — **40.6x apart, exactly the ratio of the radii** — and in both cases the
rendered node came out at 278.9 px. It holds apparent node size constant,
which is the wrong invariant for framing a cloud. With the cloud spanning
+/-380 it put the camera inside: nodes projected to (1076, 1029) and
(1323, 1718) against a 518 x 840 canvas, **0 of 3,135 on screen**. R-E5 was
marked Done and was not.

Replaced with a distance computed from the data: the layout centres on the
origin, so the cloud radius is the furthest node, and `R / sin(half-angle)`
puts a sphere of that radius in the frustum — the binding half-angle being the
smaller of vertical and horizontal, since a sidebar pane is usually taller than
it is wide. Verified: cloud radius 380.3, camera 1529.0, **3,135 of 3,135 on
screen**.

**R-J1/R-J2 — the criterion is satisfiable and insufficient, and now the gap
is a number.**

With R-J4 in place the sizing change was re-applied and both numbers held at
once: 100% on screen AND `nn_p50 / diameter` = 1.000. It still does not ship,
because at a camera distance of 1529 framing a radius-380 cloud one world unit
is 1.70 px, so a median node of 0.757 units draws at **0.45 px** — correct,
and invisible.

Legibility is two-sided, and the renderer can only satisfy one side:

* clear your neighbour — `diameter <= nn_p50`
* be visible — `diameter >= ~2 px`, which is 3.40 world units here

Both hold only when the median separation is at least **~4.5x** what the fit
delivers today (0.757 units, needs ~3.40). That is a projection change, not a
renderer one. Two candidates are measured above and either would clear it:
`min_dist=0.9` gives 6.1x on the median, and the per-axis quantile transform
gives 4.8x for 20% of the local neighbourhood structure. **This is the
decision that unblocks both R-J1 and R-J2.**

**Acceptance:** `nn_p50 / node_diameter >= 1.0`, computed from the layout the
sidecar serves and the renderer's own sizing, verified over CDP. Today that
ratio is **0.037** (0.757 units against a 20.5-unit diameter). R-J2 is the
half that closes it: a diameter taken from the layout's own `nn_p50` satisfies
this by construction, and means half of all nodes clear their nearest
neighbour instead of the renderer guessing a spacing the data never had.

## K. The markdown half, against the stated bar

`PLUGIN_GOAL.md` names the Milkdown playground's left pane as the quality
standard and gives its negative form, which is the testable half:

> *"no dedups, headers and structures within markdown structures are
> appropriately and most simply matched without things like intermediated
> hierarchical fields when a singular path node of some form of structure like
> that is rendered from its shadow DOM and interactive browser half"*

Measured over all 3,135 exported notes -- the artifacts a reader actually
opens, not the renderer in isolation.

| id | requirement | status |
|---|---|---|
| R-K1 | No intermediated hierarchical fields: a level of indentation holds more than one child, or it does not exist | **Open** — 39.0% of chunks carry one |
| R-K2 | No dedups: a chunk does not say the same thing twice | **Open** — 15.9% of chunks repeat a line |
| R-K3 | A control's name is the page's word for it, never the taxonomy's | **Open** — 136 lines |

**R-K1 — 39.0% of chunks, and the cause is that the collapse is global where
the property is local.**

| | |
|---|---|
| chunks with a pass-through level | 1,223 of 3,135 (**39.0%**) |
| such levels | 3,212 (1.02 per chunk) |

`_level_page` maps the set of depths that OCCUR ON A PAGE onto consecutive
integers, so "a chain of five wrappers costs one step instead of five" holds
only when those depths appear nowhere else on that page. On a real page they
do: the same depth carries genuine branching in another chunk, survives the
compaction, and still spends an indent in the chunk where it holds a single
child. `htmlform.py::_collapse` does not have this problem because it works on
the node tree locally -- and its own docstring credits `_level_page` with
already doing the job, which is the belief this measurement corrects.

Acceptance: pass-through levels <= 2% of chunks, with `reading_order`,
`containment` and `depth_rho` unmoved.

**R-K2 — 15.9% of chunks repeat a line.**

985 repeated lines out of 23,662 (4.2%). The worst are manufactured by the
renderer rather than present in the page: `![images]` fifteen times in one
note, `=== label ===` five times in another. When an element has no name the
renderer substitutes a constant, so N unnamed elements become N identical
lines -- duplication the page does not contain.

Acceptance: chunks with a repeated line <= 2%.

**R-K3 — the taxonomy word standing in for a name.**

136 lines draw the category as the label: `form` x78, `label` x34, `input`
x20, `button` x3. `![images]` is the same defect in the media path --
`address.subcategory` used as an alt. A reader learns nothing from `[ ] input`
that `[ ]` did not already say, and it is the direct cause of most of R-K2.

Also found, and small: 133 lines (0.56%) say one phrase twice --
`=== Toggle Table of Contents Toggle Table of Contents ===`, `( Change theme
Change theme )` -- from `_own_label` concatenating an element's own text with
a nested element repeating it.

Acceptance: category-as-name lines = 0; doubled-phrase lines <= 0.05%.

## What "fully realized" means

The pivot is realized when:

1. **R-C1** reach ≥ 60%, with deliberate suppression separated from loss.
2. **R-C2** reading order ≥ 95%.
3. **R-C4** the shape field exists as a second address dimension. *(met)*
4. **R-C5** `worst_overflow_ratio` ≤ 1.5x — the window enforced on a single
   oversized value, and not only on a chunk made of several.
5. **R-E3** ≥ 95% of picture-carrying nodes render, on a live scan.
6. **R-G2** scrolling in Obsidian drives the remote browser.
7. **R-H1** and **R-H3** either built, or explicitly dropped with the reason
   recorded here.
8. **R-C3** answered by the user: containment accepted as the stand-in for
   geometry, or the sensor's no-geometry contract changed.

Items 7 and 8 are decisions, not implementations, and they belong to the user.
Everything else is measurable and has a number above to move.
