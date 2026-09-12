# The Obsidian plugin — product requirements

`PLUGIN_GOAL.md` holds the user's two binding statements word for word and
outranks this file. This is their decomposition: every requirement traced to a
phrase in one of them, numbered so it can be argued about and measured.

**Status vocabulary.** `Done` means built *and* verified in the running app
over CDP, never by screenshot (X-2). `Partial` means built with a measured
shortfall, and the shortfall is stated. `Open` means not started. **`Defect`**
means something is built and CONTRADICTS the goal — those are not gaps to fill
but code to change, and they are listed first because they are the only
category where doing nothing makes things worse.

**Part I** is the decomposition: 112 numbered requirements, plus section 0b recording every judgment where the two statements disagreed. **Part II** keeps the measured findings from
the work so far, under their original `R-*` ids, as the evidence Part I cites.
Those ids are retired as requirements and retained as anchors.

---

## Part I — the decomposition

### 0. Defects: shipped code that contradicts the goal

| id | what is built | what the goal says | |
|---|---|---|---|
| D-1 | `layout.py` fits the projector on tf-idf **and** semantic jointly, equalised by width | *"quantized semantic (and not pre-umapped frequency) vectors are the primary embeddings space for the projector"* | **Defect** |
| D-2 | The trie is keyed `url : xpath : taxonomy : content` | *"a unified patricia trie of domain/url-tail/xpath/markdown/content-detection"* — five levels, and markdown is one of them | **Defect** |
| D-3 | The panel draws a read-only surface inside a code block | *"retrofitted to show their **base and original** markdown editors"* — the native, editable Obsidian editor | **Defect** |
| D-4 | `markdown.py` is tuned "17:1 toward leaving noise rather than risking loss" and `_dedupe` is element-scoped | *"full deduplication of repeat substrings that are essentially structural redundancies of the web pages themselves"* | **Defect** |
| D-5 | Markdown renders no tables at all | *"a hierarchically-header-structured markdown document with tables, images, web links"* | **Defect** |

D-1 is the cheapest and the most invalidating: dropping frequency from the fit
is a small change to `build_layout`, and it changes every stored position and
every hue. Do it before more projector work, not after.

### 0b. Resolutions by recency

Where the two statements disagree the later one wins. These are the judgments
that produced Part I, written down so they can be overturned rather than
inherited:

| the first statement asks for | the addendum says | resolution |
|---|---|---|
| chat contexts localized to a panel; **pull chunk panels into a new chat and aggregate**; chat within-chunk | *"add back the quantized chat feature as something **much smaller and minimal**"* | **Deferred, not dropped.** L-1..L-11 are the whole of the chat now: a rewind over the current notebook. Aggregation and cross-panel chat are out of this scope and survive as future work. |
| the **chained single-hop prompt architecture** — one generated system prompt per hop, outputs instructing the next, a final aggregate pass | *"put the LLM complexities aside"*, then a minimal embedded chat | **Deferred, not dropped.** Nothing in the addendum contradicts it; it is simply not this scope. It stays in `PLUGIN_GOAL.md` unnumbered. |
| *"no dedups"*, inside a list about elegance | *"full deduplication of repeat substrings that are essentially structural redundancies"* | **Deduplicate.** This is D-4, and it reverses how the phrase was read for most of the work so far. |
| the projector fitted on frequency **and** semantic | *"quantized semantic (and not pre-umapped frequency) vectors are the primary embeddings space for the projector"* | **Semantic only.** D-1. Frequency stays in retrieval (G-3). |
| panels "retrofitted to show their base and original markdown editors" | *"keep the original obsidian markdown panels in their native form as well"* | **No conflict** — both name the native editor. D-3 stands. |

### Two readings that are still ambiguous

**"Quantized"** is used as the name of the semantic axis
(*"frequency-quantized-pagerank"*), which reads as *the quantized model's*
embeddings — the f16 GGUF nomic already in use. It could instead mean
product-quantized vectors, which would be a storage and ANN decision that does
not exist today. Part I assumes the first.

**512 tokens is now fixed by recency** — *"the pre-set context window chunk
limit of 512 tokens"*. Recorded against it: measured over three corpus pages,
retrieval hit@1 was **83-90% at a 64-token window and 28-48% at 512**, with
the containing chunk's cosine falling 0.95 → 0.81. The instruction stands and
Part I follows it; the evidence is filed under R-C5 in Part II so the cost is
visible rather than forgotten.

### S. The scanner

| id | requirement | status |
|---|---|---|
| S-1 | Shadow DOM elements linked in **millisecond O(delta)** time | Partial |
| S-2 | MutationObservers on every chunk root *and* every nested shadow root | Partial — a shadow root attached after the walk is unobserved |
| S-3 | Content detection across the full taxonomy | Done |
| S-4 | Deduplication, efficient, in the same O(delta) budget | Open |
| S-5 | A **queue** mapping distilled markdown structures, in chunk-batches, to the vectorization steps | Open — `flush_vectors` is a separate per-page pass |
| S-6 | **tf-idf is global** to the full DB corpus, not per page | Verify |
| S-7 | Every page interaction is mutation-observed and persisted through the panel's browser half to db, vectors and trie | Open |
| S-8 | **Smooth, live-tuned steady scroll** per visit, tuned to Selenium's update rate, fine-grained and time-efficient | Open |
| S-9 | Pagination deliberately **not** automated — manual, in the browser views | By design |
| S-10 | Browser streams ported to the panels efficiently, *"completely and exactly mirroring features/calls to the original selenium"* | Partial — rrweb is the architecture; its shadow-DOM capture is the wrong half |
| S-11 | The 512-token window holds **throughout processing**, with a verification pass after the scan | Partial — 15.1× worst in the stored board, 5.9× in-process |
| S-12 | Every sensor→db stream reaches the graph view **and the opened *and closed* panel set, uniformly** | Open |

### T. The trie and the database

| id | requirement | status |
|---|---|---|
| T-1 | One trie keyed domain / url-tail / xpath / markdown / content-detection | **Defect D-2** |
| T-2 | It reconstructs the **full digital trace** of the page, not only its content | Partial |
| T-3 | Shadow DOM nodes localized to their **ancestors in the trie**, giving structural guarantees on the distilled HTML | Partial |
| T-4 | Intermediate trie paths reflected as **intermediate chunk-node linkages** | Open |
| T-5 | The **local vault** is in the trie | Open |
| T-6 | **Installed Python packages** are in the trie, per-package partitioned with main-DB links | Open |
| T-7 | Semantic vectors **and** hard graph links in the **same database** | Partial |
| T-8 | The trie is streamed to the panels' interactive side | Open |
| T-9 | The xpath **shape** exists as a second address dimension, never as the identity | Done |

### M. Markdown distillation

The quality bar is the Milkdown playground's left editable pane, on four named
axes: **structure, content, organizedness, completeness**.

| id | requirement | status |
|---|---|---|
| M-1 | The **full content** of the original in-browser HTML survives | Partial — reach 37.1% |
| M-2 | **Hierarchically header-structured** | Partial |
| M-3 | **Tables** | **Defect D-5** |
| M-4 | Images, web links, embedded links | Partial |
| M-5 | **Markdown panel links** to other panels | Partial — continuation links done, retrieval links absent |
| M-6 | Renders in regular / normal / **minified** form | Partial |
| M-7 | **No intermediated hierarchical fields** where a single trie path node was collapsed | Open — 39.0% of chunks carry one |
| M-8 | **Full deduplication of structural redundancy** | **Defect D-4** — 88% of in-chunk repetition is the page repeating itself |
| M-9 | A control is named by the page, never by the taxonomy | Done — 1,556 lines → 2 |
| M-10 | **Full structural preservation along content links in nested shadow DOM nodes** | Open |
| M-11 | Quality holds **at the interactive chunk level**, because the chunk is what gets embedded and its structure decides how representative the vectors are | Open |
| M-12 | Reading order matches the document | Done — 100% |

### G. The projector and the graph

| id | requirement | status |
|---|---|---|
| G-1 | Projector fitted on **quantized semantic vectors only** | **Defect D-1** |
| G-2 | Chunk embeddings batch-UMAPped **with their per-document source** — two node kinds, one fit | Open |
| G-3 | Retrieval stays **triple**: frequency × quantized-semantic × pagerank | Done |
| G-4 | **Inter-spatial normalization** — nodes discernible | Done — nn p50 0.757 → 5.657 |
| G-5 | Nodes visible at the default camera | Done — 0 → 3,135 of 3,135 on screen |
| G-6 | **Patricia-trie links drawn** | Open |
| G-7 | **Markdown retrieval links drawn** | Open |
| G-8 | **Module dependency links** for codebases and Python modules | Open |
| G-9 | …including modules inside **local PyPI packages** | Open |
| G-10 | **Vault directory** drawn as links | Open |
| G-11 | Three sources in one skeleton: web, vault, PyPI | Open |
| G-12 | **UMAP embeddings persisted to the db** and queried straight into the graph view | Open |
| G-13 | Re-projection **batched in a queue whose latency adapts** to the projection's own cost | Open |
| G-14 | **Graph linkage completeness** across trie, web links, markdown links | Partial — dangling edges 0; trie axis absent |
| G-15 | **Media present in the projector**, not only the panels | Partial — 73.8% textured |
| G-16 | Chunk deltas diffed **into the projector view** live | Open |

### P. The panels

**P-W — the per-chunk web panel**

| id | requirement | status |
|---|---|---|
| P-W1 | Specialized for the **interactive components** of webpages | Partial |
| P-W2 | The **native, editable** Obsidian markdown editor as one half | **Defect D-3** |
| P-W3 | The interactive HTML card as the other, one per chunk, boundary set by the sensor | Done |
| P-W4 | A **minimal form of the original browser** — not raw HTML, not a browser re-render; same content, structure and affordances | Partial |
| P-W5 | Interactable **against the database, offline** | Partial |
| P-W6 | **And** dispatched to the live page when online | Partial — `enact` exists, gated off |
| P-W7 | **Media in both halves** | Partial |
| P-W8 | A switch between the two halves | Done |

**P-C — the code artifact panel**

| id | requirement | status |
|---|---|---|
| P-C1 | Full code artifacts **viewable and editable standalone** | Open |
| P-C2 | **A terminal always directly below** the artifact | Open |
| P-C3 | Artifacts vectorized **by their comments and docstrings** | Open |
| P-C4 | **Docstrings and code docs more broadly** are the vectorized surface for codebases | Open |
| P-C5 | **Live delta updates to modules** in both halves and in the 3D view | Open |

**P-N — the retrieval-enhanced notebook panel**

| id | requirement | status |
|---|---|---|
| P-N1 | A **Jupyter kernel** panel, retrieval-enhanced | Open |
| P-N2 | **Switchable** between Jupyter kernels and PowerShell terminals | Open |
| P-N3 | A **toggle on a code block** opens terminal or kernel — possibly both at once | Open |
| P-N4 | A facade over Obsidian's vault interface exposing local kernels to the filestructure | Open |
| P-N5 | Notebooks are **dynamically recursively chunked** like webpages | Open |
| P-N6 | …and **continuously diff-updated to the db**, re-vectorized and re-assigned to chunks | Open |
| P-N7 | **One interface** centralizing retrieval and code research | Open |

**P-M — the native markdown panel, built outward**

| id | requirement | status |
|---|---|---|
| P-M1 | The **original Obsidian markdown panel survives in native form**, distinct from the notebook panel | Open |
| P-M2 | The same retrieval is added to the native default | Open |
| P-M3 | Code, kernel and terminal options are built **on top of** the native form | Open |
| P-M4 | Buttons that add new structural cells sit at the **very bottom** of the markdown | Open |
| P-M5 | The hovering chat sits **below the boundary of the scrollable markdown window** | Open |

**P-B — the browser notebook cell**

| id | requirement | status |
|---|---|---|
| P-B1 | A **fully-fledged regular browser view** in the cell — NOT constrained to a chunk | Open |
| P-B2 | Navigate exactly as in a normal browser, while scanning continues on the live page | Open |
| P-B3 | **Embed the native Selenium session view** in the cell if possible | Open |
| P-B4 | **Resizing the cell resizes the Selenium window** | Open |
| P-B5 | The passive MutationObserver sensor fires throughout — scroll, hover, interact — diffing DOM → DB in O(delta) ms | Open |
| P-B6 | **Left click** behaves exactly as in Firefox under Selenium | Open |
| P-B7 | **Hover** overlays the chunk structure on the page's own cartesian layout, showing the chunks embedded in it | Open |
| P-B8 | **Right click** locally indexes a chunk to its dual-view markdown panel inside the cell — this is what feeds the SLM context | Open |
| P-B9 | Right-click indexing covers the **static type set only**; interactive components are deferred to tool calls in much later iterations | By design |
| P-B10 | Dual per-chunk browser + markdown panels are reachable **from the projector** too | Open |

### R. Retrieval — the `[]()` gesture

| id | requirement | status |
|---|---|---|
| R-1 | Typing the four symbols makes the bracket contents a **semantic retrieval query** | Open |
| R-2 | Results in **scrollable whitespace immediately below the line** | Open |
| R-3 | The remaining editable lines stay **uninterrupted** — the panel is one cohesive unit. `EditorSuggest` overlays; a CM6 **block widget** reflows | Open |
| R-4 | Clicking a result **infills the link between the parentheses** | Open |
| R-5 | **All retrieval comes through this one interface** — web, vault, packages alike | Open |
| R-6 | Package retrieval applies a **vector-centroid pre-filter**, then partition-wise retrieval; the filter must not become a second interface | Open |
| R-7 | The docs are updated to match this gesture wherever they disagree | Open |

### L. The minimal embedded chat

Deliberately small. Everything below is the whole of it; the chained
single-hop architecture from the first statement is **not** in scope here.

| id | requirement | status |
|---|---|---|
| L-1 | A **quantized** small model — Nous Hermes 2 DPO 7B on local CUDA | Open |
| L-2 | Embedded **within the notebook panels**, at the bottom of the selected cell — markdown, code, or terminal/kernel | Open |
| L-3 | Context **begins at the last-most viewable cell in the current selection** and **rewinds backwards** through the notebook | Open |
| L-4 | It rewinds over the notebook **in its current state**, including terminal and kernel output — which is the norm for intermediate cells | Open |
| L-5 | The prompt/response panel **hovers and follows the scroll** | Open |
| L-6 | A **new rewind only when the cursor lands on a new cell**, not on scroll | Open |
| L-7 | The rewind is **injected into the user prompt** as the effective contextual history | Open |
| L-8 | The **user prompt decides how many further chunks** to rewind | Open |
| L-9 | Rewind size stays within a **safety factor of the max input token limit**, so sessions continue without compaction or one-shot restart | Open |
| L-10 | Also available **hovering over the native markdown panels** | Open |
| L-11 | Deferred by name: cell/code navigation, running things in the terminal, writing updates back to notebooks | Deferred |

### X. How the work is done

| id | requirement | status |
|---|---|---|
| X-1 | **Search GitHub for working codebases and examples at every step** — *"the most important drivers of success"* — so the code the model uses to touch the interface is visible | Standing |
| X-2 | Verify in the running app over devtools, **never by screenshot** | Standing |
| X-3 | Where a document contradicts the goal, the **document** changes | Standing |
| X-4 | Measure the distribution **before** writing an acceptance criterion | Standing — four criteria here were written first and all four were wrong |
| X-5 | Cleanups gate on **`accounted`**, not `covered` | Standing |

**X-6 — the build order is given, and it is not the order of these tables.**

The addendum states it as a sequence, so it is a requirement and not a
suggestion: the **native Obsidian markdown panel is the substrate**, and
everything is grown from it — *"we essentially build the native obsidian
markdown out into this more fully fledged interactive panel"*.

1. native markdown panel, kept in native form (P-M1)
2. + the same retrieval (P-M2)
3. + code, kernel and terminal options (P-M3, P-N)
4. + the hovering chat (L-10)
5. + **interactive web browser cells — explicitly "the final step"** (P-B)

P-M and P-N are therefore not peer panel types: P-N is P-M grown, and the
native form survives alongside it. P-B is last because *"the way browser
interactions and dual panel views work is slightly different, and particularly
so."*

---

## Part II — measured findings

Everything below is evidence for Part I, kept under the `R-*` ids it was
recorded against. Those ids no longer number requirements; they anchor
measurements. Where Part I cites a number, it comes from here.

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
| R-K2a | No contentless lines: a unit with neither words nor a target is not drawn | **Open** — 703 repeats, 2.79% of chunks |
| R-K2b | A chunk showing what the page itself repeats — faithful, or noise? | **Open** — a decision, 88% of the repeats |
| R-K3 | A control's name is the page's word for it, never the taxonomy's | Done — 1,556 → 2 lines |

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

**R-K2 — split, because the measurement says it is two things and the bar
can only be asked of one of them.**

The criterion first written here -- "chunks with a repeated line <= 2%" -- was
set before the repeats were looked at. Over 40 corpus pages, 1,438 of 10,014
chunks (14.36%) hold a repeat, and those repeats decompose:

| | lines | share |
|---|---|---|
| the page genuinely says it twice | **5,161** | **88.0%** |
| contentless -- mark only, no words | 703 | 12.0% |

So 2% is not reachable by removing renderer artifacts. Suppressing every
contentless line takes the figure from 14.36% to about 11.6%, and the rest is
the document repeating itself: a nav label in the header and again in the
footer, inside one chunk.

**R-K2a is the renderer's, and is a defect.** 703 lines carry a mark and
nothing else -- `![]` x551, `<#>` x72, `===  ===` x39, `[ ]` x11, and `![]
![]` x7 where two placeholders were inline-merged. A media unit with no alt
and no source, a link whose href is `#`, a form with no name: each says only
"a detector fired here", and drawing it fifteen times says it fifteen times.
279 chunks have no other kind of repeat, so this alone is 2.79% of all chunks.

The fix is not simply to drop them: a unit that draws no line leaves no
address, which is the failure `_suppressed_controls` exists for -- 89.8% of
anchor affordances were lost that way once. The line goes and the address
rides on `absorbed`, the mechanism already built for exactly this.

Measured over 40 corpus pages: **1,671 contentless lines, 2.27% of all
lines** -- `![]` x1,377, `===  ===` x159, `<#>` x85, `[ ]` x28, and a tail of
`![] ![]`, `</>`, `(  )` where two placeholders were inline-merged.

They split on whether dropping one costs an address:

| | lines | |
|---|---|---|
| another line survives at the same element | 782 | 46.8% |
| the only line at its element | 889 | 53.2% |

**And the obvious implementation is forbidden, which is the finding.** The
natural pass is chunk-level: walk a chunk's lines, drop a bare mark when
another line in that chunk shares its xpath, and hang the address on the
survivor. Two things kill it.

`absorbed` is deliberately NOT counted by `covered` -- its own comment says
why: "coverage must not move with the context window ... counting a collapse
as covered therefore made the set window-dependent by four addresses at
window 200, twice". So moving an address there LOWERS `covered`, which is the
opposite of the acceptance criterion.

Worse, the test itself is window-dependent. Whether another line at the same
element is in the same chunk is a fact about where the chunker cut. A rule
keyed on that would drop a line at one window and keep it at another, and
`test_no_address_is_lost_when_the_window_changes` exists for precisely that.

This codebase has made the same correction twice already, and written it
down: "a pass whose result must not depend on the descent belongs outside it"
(`_absorbed_by_element`), and the same reasoning in `_suppressed_controls`.
So the rule has to be **element-scoped over the trie**, where `_dedupe`
already lives: a unit that renders to a bare mark is dropped when another
unit AT THAT ELEMENT renders with words -- a property of the document, true
at every window.

That still only reaches the 46.8%. The remaining 889 are elements whose only
rendering is a mark: 643 images with neither an alt nor a source, 113
nameless forms, 84 links whose href is `#`. Those are upstream -- a media
detection with no alt and no src describes nothing, and the question is
whether the tagger should emit it at all.

**And the renderer cannot be where this is fixed.** `_dedupe`'s drops land in
`absorbed`, which `covered` excludes by design, so dropping 782 lines drops
782 covered addresses. "Contentless = 0 with `covered` unchanged" is not
achievable by dropping a line at all -- the line and the address are the same
thing at that point. There is also a reverted attempt on record at the
`_dedupe` call site: a containment-chain rule that hid repeated names, costing
"about a point of deduplication for four units of *loss*", with the verdict
"a rule that trades coverage for tidiness is the wrong trade at any exchange
rate". This one is different in kind -- it drops renderings that carry no
words at all, which is the "reason beyond `these strings match`" that comment
asks a future rule to have -- but the coverage arithmetic is the same and
rules the renderer out.

**Upstream, the detection itself is redundant.** Over 40 corpus pages, 1,634
of 4,404 media addresses (37.1%) have neither a source nor an alt, and their
value is literally the element's tag name. Counting every media `text()`
detection valued at its own tag: **2,245**, on `svg` x732, `img` x376,
`source` x370, `picture` x91, `video` x63.

`srcset` is NOT the gap -- the tagger already splits it into indexed
candidates, so a `<source>`'s real URLs exist as their own addresses. The
contentless thing is a SECOND detection at the same element whose accessor is
`text()`, on an element that has no text, falling back to the tag.

| | detections | |
|---|---|---|
| element keeps another address without it | **1,368** | 60.9% |
| element would lose its only address | 877 | 39.1% |

The 877 are `<svg>` x725, `<picture>` x91, `<video>` x60 -- an inline SVG
genuinely is a graphic with no source, and its address is the only thing
saying one is there.

**Built, measured, reverted.** The rule was implemented in the tagger exactly
as specified -- drop only where the element retains another address -- and it
did what it promised on its own terms, over 40 corpus pages:

| | before | after |
|---|---|---|
| addresses | 140,395 | 139,027 (**-1,368**, the predicted count) |
| distinct elements | 65,943 | **65,943** -- nothing orphaned |
| contentless lines | 1,671 | **949** (-43.2%) |
| chunks with a repeat | 14.36% | **12.71%** |
| **covered addresses** | 118,387 | 116,484 (**-1,903**) |

Coverage fell by 535 MORE than the addresses removed. Diffing the covered sets
over 12 pages: 589 addresses removed from the trie, 929 lost coverage, so
**340 addresses that still exist stopped being accounted for** -- 265
`media.images` and 75 `text.accessible`.

That is the trade `markdown.py` refuses at its `_dedupe` call site in exactly
these words: *"a rule that trades coverage for tidiness is the wrong trade at
any exchange rate."* 722 fewer contentless lines for 340 lost addresses is
that trade. Reverted.

**The mechanism is not understood, and two explanations have been wrong.**
The first guess was that the `![]` line is a carrier -- that the element's real
`src` and `alt` ride on it as `inline` -- which would make it contentless only
in appearance. Checked: all 819 `![]` lines carry **zero** inline addresses.
So that is not it either. Removing a detection also moved 105 chunk boundaries
and 2,177 lines, far more than the 1,368 detections removed, so something
downstream of the trie is reacting to the removal in a way neither guess
predicted.

Acceptance is unchanged in intent, but no further attempt should be made until
that mechanism is identified: a change that reduces coverage by an amount its
author cannot explain is not ready regardless of what it improves.

**R-K2b is not a defect and is not mine to decide.** 88% of the repetition is
in the page. Rendering it is *faithful*; suppressing it makes the artifact
cleaner than the thing it distils. The goal says "no dedups" in a list about
elegance, which reads as "the panel should not show the same thing twice" --
but this renderer's standing direction is the opposite, tuned "17:1 toward
leaving noise rather than risking loss", and `_dedupe` is element-scoped on
purpose. Cross-element dedup inside a chunk would drop addresses that name
real, distinct elements.

The question for the user: when a page puts the same words in its header and
its footer, should one chunk show them once or twice?

**R-K3 — the taxonomy word standing in for a name.**

Lines drew the category as the label: `[ ] input`, `( button )`,
`=== form ===`, and in the media path `![images]` from `address.subcategory`
used as an alt. A reader learns nothing from `[ ] input` that `[ ]` did not
already say — the mark states the affordance, and the tag repeats it in the
detector's vocabulary instead of the page's.

`_echoes_its_element` already answered the question ("is this value only the
element's own tag name") and was used in two places, neither of them the
render. Applying it there, and dropping the `subcategory` fallback on the
media alt:

| over 40 corpus pages | before | after |
|---|---|---|
| category-as-name lines | **1,556** | **2** |
| lines | 73,675 | 73,675 |
| covered addresses | 118,387 | 118,387 |
| chunks | 10,013 | 10,014 |
| chunks with a repeated line | 14.31% | **14.36%** |

*(The corpus-wide figure of 136 quoted earlier came from the 24 exported pages
and a narrower match that missed the `![images]` / `![video]` forms; 1,556 is
the same measurement done properly.)*

**And it made R-K2 marginally worse, which corrects a claim made here.** This
was recorded as "the direct cause of most of R-K2". It is not: removing a
false name does not remove the duplication underneath it. Fifteen unnamed
icons were fifteen identical `![images]` lines and are now fifteen identical
`![]` lines, and a few `![images]`/`![video]` pairs that differed only by
their category now collide — +0.05 points. The gain is 778x on the target and
the cost is 0.05 points on a neighbour, so it ships, but the two are not the
same defect and fixing one does not fix the other. R-K2 needs its own answer:
a unit with neither words nor a target carries nothing, and drawing it at all
is the actual duplication.

Also found, and small: 133 lines (0.56%) say one phrase twice --
`=== Toggle Table of Contents Toggle Table of Contents ===`, `( Change theme
Change theme )` -- from `_own_label` concatenating an element's own text with
a nested element repeating it.

Acceptance: category-as-name lines = 0; doubled-phrase lines <= 0.05%.

## L. What coverage means — the gate every cleanup collided with

Five iterations of markdown cleanup ran aground on the same number, so the
number was examined instead of the changes.

**`covered` answers "what did the render draw". It was being read as "what
does the system account for".** Those differ by `absorbed` — the spellings a
collapse dropped, an `aria-label` beside the text it duplicates, an `href`
hidden because the anchor says the words.

**The store never had the confusion.** `graphstore` maps an address to a
chunk from `address`, then `inline`, then a THIRD pass over `absorbed`, and
says why: reading only the first two "left 37,452 addresses over the corpus
with no chunk at all, 8,167 of them urls, and an edge they could not hang on".
An absorbed address has a chunk, hangs its edge, is findable. `covered` calls
it lost.

Measured over twelve corpus pages:

| | share of the trie's addresses | moved by re-chunking at 128 vs 512 |
|---|---|---|
| `covered` (address + inline) | 89.4% | 46 |
| `accounted` (+ absorbed) | **95.9%** | 227 |

**What this cost.** The nameless-media change (R-K2a) was reverted because
`covered` fell by 340 addresses that still existed. Re-measured against
accounting, it fell by **94**. The gate overstated the damage 3.6x, and a
change was reverted substantially on that.

**And the invariant everyone reasons from is weaker than believed.**
`covered` is not window-invariant either: 46 addresses move between window 512
and window 128 on twelve pages. `test_no_address_is_lost_when_the_window_
changes` passes because it runs on a SINGLE fixture page. Every argument in
this repo of the form "that would make the covered set window-dependent" rests
on a property that does not hold at corpus scale — including two reverts of a
value splitter earlier in this work.

**The settlement.**

* `covered` keeps its definition and its meaning narrows to what it always
  measured: lines drawn.
* `MarkdownChunk.accounted` is added — `address` + `inline` + `absorbed`,
  mirroring the store's three passes exactly, so the metric and the store
  cannot drift.
* **Cleanups are gated on `accounted`.** Gating on `covered` forbids the whole
  class by construction: drawing fewer redundant lines lowers it, because
  that is what such a change means.
* The window-invariance test should be re-pointed at page-level `accounted`
  and run over the corpus rather than one page. It currently certifies a
  property it does not check.

R-K1, R-K2a and R-E3a were all blocked by this and are unblocked by it —
under the correct gate, each still has to prove it costs no accounting.

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
