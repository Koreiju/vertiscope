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

**Part I** is the decomposition: 128 numbered requirements, plus section 0b recording every judgment where the two statements disagreed. **Part II** keeps the measured findings from
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
| ~~D-6~~ | ~~The delta path re-admits a chunk it should have reassigned or popped~~ | **WITHDRAWN 2026-09-12 — not demonstrated.** The evidence for it was a metric that could not tell two real siblings from one re-addressed node. `--resolvable`: 0 unresolvable of 719. `--drift --kind insert`: 0 stale, 0 lost over ~190 moved addresses ×3. See §M.3 for what remains untested | — |
| D-8 | A `src` detection and an `alt` detection at one `<img>` are drawn as TWO media lines, so the url and its caption are separate and the url's line has no text | *"image, links, embedded links"* at the Milkdown bar, and `M-11`'s chunk-level quality | **Defect** — 365 of 835 media-bearing chunks (§M.5.1) |
| D-9 | A chunk rooted at a `<tr>` carries its cells' VALUES and none of their names, though the header at the same `td[n]` position is in the trie | `M-10` full structural preservation; `M-11` the chunk is what gets embedded | **Defect** — 44 of 79 row chunks (§M.5.2) |
| ~~D-7~~ | ~~A media element with no alt text renders as a bare `![images]`~~ | **WITHDRAWN 2026-09-12 — not a defect.** Already fixed by `499fd6d` (M-9). Filed against `vaultws512`, built 34 minutes BEFORE that commit. On the 256 re-cut: **0 bare placeholders, 1,073 named**. See §M.0 | — |

**D-1 is FIXED** (2026-09-12, `layout: the projector fits on semantic alone`).
`build_layout` fits the semantic space alone; frequency is demoted to the
no-embeddings fallback and `fitted_on.semantic` names which happened. Verified
against the running plugin over CDP: `/layout` reports `spaces: ["semantic"]`
across 3,135 nodes. `halves` and `equalised` are gone with the machinery they
described. 19 tests, including a non-vacuity arm that fails if the embeddings
are ignored.

**Both D-6 and D-7 were withdrawn the same day they were filed**, and the two
failures had one cause: a metric invented for the occasion instead of the
instrument the repo already had. §M.0 and §M.3 record them, because the method
error is more reusable than either finding would have been.

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

**The window is 256** (decided 2026-09-12, after the addendum named 512). The
addendum's figure was reconsidered against two measurements that pull opposite
ways:

| window | hit@1, three pages | over window | record tests |
|---|---|---|---|
| 64 | **85 / 90 / 83%** | 13.3% | nav AND prose split |
| 128 | 60 / 75 / 65% | 7.8% | prose splits |
| **256** | 45 / 48 / 58% | **2.5%** | **all 11 pass** |
| 512 | 48 / 28 / 45% | 1.0% | all pass |

Retrieval favours small monotonically; structure favours large. 256 is where
they meet — every structural property holds and it still beats 512 by about
ten points of hit@1 while filling half the window rather than a third. **512
is dominated: it wins on no measurement.** 64 was tried first and reverted
because a nav bar split into three chunks of menu labels, against
`test_a_nav_bar_is_not_a_record_set`'s own reason — "a menu item is not a
retrievable unit".

The 64 column is an upper bound on its own advantage: those probes are
verbatim lines, which favours short chunks mechanically. The direction held on
three unrelated pages, so 256-over-512 is safe; 64-over-256 wants paraphrased
probes first.

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
| S-11 | The **256-token** window holds **throughout processing**, with a verification pass after the scan. A target, not a ceiling: a single indivisible unit may exceed it | Partial — **0.4%** over on the 256 re-cut (21 of 5,337; max 370, mean 103). Better than the 2.5% previously recorded. The *verification pass* is still absent, which is what keeps this Partial |
| S-12 | Every sensor→db stream reaches the graph view **and the opened *and closed* panel set, uniformly** | Open |
| S-13 | **Investigate** whether Electron can be driven directly to give "the same sensor-like functionality" as Selenium — deliverable is a capability verdict with evidence, NOT a migration | **Verdict delivered (§N)** — yes: `BrowserWindow`/`WebContentsView` + `session.fromPartition` + `preload` + `webContents.debugger`, all reachable from plugin code; MutationObserver attaches; and Electron loaded apnews.com in 26.4 s where geckodriver timed out at 40 s. Migration NOT decided — §N.4 lists what is untested |
| S-14 | Whatever hosts the sensor must keep **profile control "from their base"** and stay "slim on web interfaces" | **Available on the Electron host** — `session.fromPartition('persist:…')` gives an isolated persistent profile, verified (§N.2). Counter-cost in §N.4: Chromium's version becomes Obsidian's, not ours |
| S-15 | One page's failure must not end a corpus run; every failure is named and the exit code is non-zero | **Done** — `cmd_scan` collects per-page failures; a 24-page re-cut had been aborted by apnews.com alone |

### T. The trie and the database

| id | requirement | status |
|---|---|---|
| T-1 | One trie keyed domain / url-tail / xpath / markdown / content-detection | **Defect D-2** |
| T-2 | It reconstructs the **full digital trace** of the page, not only its content | Partial |
| T-3 | Shadow DOM nodes localized to their **ancestors in the trie**, giving structural guarantees on the distilled HTML | Partial |
| T-4 | Intermediate trie paths reflected as **intermediate chunk-node linkages** | Open |
| T-5 | The **local vault** is in the trie | **Done** — `domvec/vault.py` + `Workspace.index_note` + `domvec notes <dir>`. Addressed `vault://<vault>/<path>` with markdown's tree as `section`-wrapped xpath steps; 18 docs indexed to 786 chunks / 2,697 addresses and retrievable. Module dependencies and the directory tree as UMAP links (`G-8`/`G-10`) are still Open |
| T-6 | **Installed Python packages** are in the trie, per-package partitioned with main-DB links | Open |
| T-7 | Semantic vectors **and** hard graph links in the **same database** | Partial |
| T-8 | The trie is streamed to the panels' interactive side | Open |
| T-9 | The xpath **shape** exists as a second address dimension, never as the identity | Done |
| T-10 | A delta that moves content must **retire the address it left** — the trie must not hold an address the page does not have | **Holds, on what has been tested** — `--drift --kind insert` repaired ~190 moved addresses with 0 stale and 0 lost, 3 of 3 exact; `--resolvable` 0 of 719 unresolvable. Not yet tested on a live/mutating page (§M.3) |

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
| M-13 | A media element renders with something that **distinguishes it** — alt text, a filename, or `![]`, never the taxonomy | **Done** — `499fd6d`; on the 256 re-cut 0 of 1,073 media render as a taxonomy placeholder. Filed briefly as D-7 against a stale store and withdrawn (§M.0) |

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
| G-17 | The projection's **output space is spherical**, fitted with an angular metric rather than rescaled into a cube afterwards | Open — Addendum III |
| G-18 | Points are **quaternions and the distance between them is the quaternion distance** — the geodesic angle on the unit 3-sphere, `2·arccos(\|⟨p,q⟩\|)`, absolute because `q` and `−q` are one rotation | Open — Addendum III. umap-learn ships no such metric; it is a custom `output_metric`, a numba function returning the distance AND its gradient |
| G-19 | The view is **centred on the origin** | Open — Addendum III. A sphere of radius 1 about the origin makes `recentre` unnecessary by construction: the camera cannot end up inside the cloud, which is the failure `graph.ts` records a camera at z = −230 inside a cloud spanning ±249 |
| G-20 | **Force-directed relaxation seeded from the UMAP embedding** — UMAP initialises, the simulation converges | Open — Addendum III. This OVERTURNS `graph.ts`'s current `d3AlphaDecay(1).d3VelocityDecay(1)`, which freezes the simulation on the stated ground that "the coordinates are already the answer" |
| G-21 | **Nodes never overlap**: spherical colliders, with a **quarter-distance safety factor** on the radius | Open — Addendum III. `d3-force-3d`'s `forceCollide` is already present beneath `3d-force-graph` and separates nodes to at least `radius(a) + radius(b)`; the safety factor is ours on top |

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
| P-C2 | **A terminal always directly below** the artifact — a kernel *run-and-output surface*, not a shell prompt (P-N2 §4a) | Open |
| P-C3 | Artifacts vectorized **by their comments and docstrings** | Open |
| P-C4 | **Docstrings and code docs more broadly** are the vectorized surface for codebases | Open |
| P-C5 | **Live delta updates to modules** in both halves and in the 3D view | Open |

**P-N — the retrieval-enhanced notebook panel**

| id | requirement | status |
|---|---|---|
| P-N1 | A **Jupyter kernel** panel, retrieval-enhanced | **Partial** — a python kernel runs cells per note, gated behind `--kernel`, via `POST /kernel`; the button is live in both rendering paths. NOT Jupyter-protocol (subprocess; see `NOTEBOOK_PANEL_DESIGN` §1) and not yet retrieval-enhanced |
| P-N2 | **Switchable** between Jupyter kernels and PowerShell terminals. Resolved §4a: a *kernel run in place*, a *command terminal* in a **separate pane** | **Partial** — shells switchable from discovery (`GET /interpreters`) and running per pane; Jupyter kernels are *listed* but not driven — the sidecar runs a subprocess, not the protocol |
| P-N3 | A **toggle on a code block** opens terminal or kernel — possibly both at once. Under P-N2's resolution "both" is the panel running its kernel *while* a separate pane holds a terminal: two panes, no special layout | Open |
| P-N4 | A facade over Obsidian's vault interface exposing local kernels to the filestructure | Open |
| P-N5 | Notebooks are **dynamically recursively chunked** like webpages | **Partial** — a note and its stored cell outputs chunk through the same recursive descent a page does (`domvec notes`); outputs are addressed `…/output[n]` and retrievable. Not yet *dynamic*: re-indexing is a command, not a diff on save (`P-N6`) |
| P-N6 | …and **continuously diff-updated to the db**, re-vectorized and re-assigned to chunks | Open |
| P-N7 | **One interface** centralizing retrieval and code research | Open |
| P-N8 | **Chunk scanning is exposed in the panel** — the reader can see the chunk boundaries the sensor drew | **Done** — a CM6 gutter marks every chunk's extent with its token count and flags any over the window, computed live by `POST /chunk_preview` through the same pipeline indexing uses. Editor only; reading view has no gutter |
| P-N9 | **Selection highlighting over the rendered markdown**, in the alternative panel | Open |
| P-N10 | That selection **annotates the context fed to the SLM** — the reader marks what the model is given, rather than the model taking the whole panel | Open |

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
| P-B3 | **Embed the native Selenium session view** in the cell if possible | Open — **build on `WebContentsView`, not `<webview>`**: Electron advises against the webview tag, and `remote.WebContentsView` is reachable from plugin code (§N.1) |
| P-B4 | **Resizing the cell resizes the Selenium window** | Open |
| P-B5 | The passive MutationObserver sensor fires throughout — scroll, hover, interact — diffing DOM → DB in O(delta) ms | Open |
| P-B6 | **Left click** behaves exactly as in Firefox under Selenium | Open |
| P-B7 | **Hover** overlays the chunk structure on the page's own cartesian layout, showing the chunks embedded in it | Open |
| P-B8 | **Right click** locally indexes a chunk to its dual-view markdown panel inside the cell — this is what feeds the SLM context | Open |
| P-B9 | Right-click indexing covers the **static type set only**; interactive components are deferred to tool calls in much later iterations | By design |
| P-B10 | Dual per-chunk browser + markdown panels are reachable **from the projector** too | Open |
| P-B11 | **Straddle the shipped core `webviewer`** and take ownership of Electron as the work proceeds — use it, then outgrow it. (It is currently *disabled* in this vault's `core-plugins.json`.) | Open |

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

**X-7 — Addendum II refines that order for the near term.** It does not
replace X-6; the notebook panel still grows from the native substrate and
browser cells still come last.

1. **Re-cut the corpus at 256** — done first so nothing downstream is measured
   against a window the goal no longer names.
2. **Verify the duplication capabilities** — §M.1 and §M.2 above; *"at least
   verify the capabilities of to explore"*.
3. **Notebook kernel panel design, nailed down first** — *"we move onward to
   the notebook kernel panel design first to nail it down correctly"*.
4. **Bring the Electron sensor in when ready** — the phrase is *"when ready"*,
   so S-13's verdict gates this rather than a date.
5. **Then the hovering SLM bar** — *"then, we go for the hovering SLM bar
   itself and work out the details"*.

Note what moved: the hovering chat was item 4 of X-6 and is item 5 here,
behind the notebook panel. Nothing was dropped.

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

## M. The two duplications, measured apart

Addendum II flags *"a lot of both duplicate chunks ... and also duplicate
content within the markdown panel renderings"*. Those are two layers, and the
first thing to do with them is refuse to add them together.

### M.0 — the first measurement was wrong, and how

It was taken against `build/vaultws512`. That store was written **2026-09-09
22:38:46**; commit `499fd6d` — *"markdown: the taxonomy is not a name — 1,556
lines → 2"*, which is `M-9` — landed **23:12:36 the same evening, 34 minutes
later**. The corpus had been rendered by pre-fix code.

What that produced: `![images]` appeared 1,575 times and 40% of all in-chunk
repetition was traced to it, so it was filed as **D-7**. On the 256 re-cut,
rendered by current code, **0 of 1,073 media carry a taxonomy placeholder**.
The defect had been fixed three days before it was reported, and `499fd6d`'s
own comment describes the exact symptom: *"a page with fifteen unnamed icons
rendered `![images]` fifteen times, telling a reader nothing except which
detector fired"*. D-7 is withdrawn.

**The rule this adds to `CLAUDE.md`'s list.** *A rendering claim must be
measured against a corpus rendered by the code under test.* The existing rules
cover the page moving (`--drift --kind none`) and the denominator being wrong;
neither covers the **instrument having changed since the corpus was written**.
A store is not neutral evidence — it is a recording of what some past version
of the renderer did, and its mtime is part of its meaning.

The cheap guard: compare the store's mtime against `git log -1 --format=%ad`
for the module whose output is being scored, before quoting a number.

Two further caveats on the numbers below, both stated rather than buried:

- **The corpora differ by one page.** apnews.com refuses automation (403 to
  curl, a 40s navigation timeout) and is absent from the 256 store. It was the
  single largest contributor to every duplication figure on the 512 store —
  removing it alone took bare media from 1,575 to 675 — so no 512↔256 delta
  below is a clean window comparison.
- **Neither store has a link graph** (`links`: 3 and 0). Both were scanned
  without `--follow`, so the pagerank factor is near-uniform and the triple
  product is effectively a pair product. Any retrieval figure taken on these
  stores understates what `G-3` describes.

### M.1 — duplicate CHUNKS: how many, and what they are

Identical rendered markdown at more than one address. **Measured on
`build/vaultws256` (5,337 chunks, 23 pages), current code**, read-only.

| | 256 (valid) | 512 (stale code — reference only) |
|---|---|---|
| duplicate groups | **105** | 147 |
| redundant chunks | **246 of 5,337 — 4.6%** | 163 of 3,135 — 5.2% |
| groups whose addresses are siblings in one parent | **99** | 36 |
| groups in structurally unrelated places | **6** | 111 |

**The duplicates are real; the first diagnosis of them was not.** That middle
row was initially read as an index-shift defect and filed as `D-6`. It is not:
sibling addresses are what a repeated list looks like, and §M.3 shows why the
test could not tell the two cases apart. All 105 groups currently read as
`D-4`/`M-8` — **the page repeating itself** — which Addendum II puts in scope:
*"full deduplication of repeat substrings that are essentially structural
redundancies of the web pages themselves."*

Which pages carry them:

| url | groups |
|---|---|
| developer.mozilla.org/en-US/docs/Web/CSS | 37 |
| archive.org/details/texts | 19 |
| discourse.julialang.org/latest | 17 |
| arxiv.org/abs/1706.03762 | 10 |
| ar.wikipedia.org — Physics | 7 |

That distribution is itself the argument for `D-4`: a CSS property index, a
reference list and a forum's latest-topics page are documents whose *structure*
is repetition. A defect in the delta path would not concentrate there.

The `512 → 256` shift in the last two rows is **not** a change in the page.
A 256-token window cuts more often, so which repetitions come out
byte-identical changes with the window. Both columns are window-conditioned,
which is why §M.3 ends by asking for a measure over content hashes rather than
over chunk boundaries.

### M.2 — duplicate CONTENT: one chunk's render repeats itself

Repeated non-blank lines *within* a single chunk, on the 256 store.

| | 256 (valid) | 512 (stale code) |
|---|---|---|
| chunks with ≥1 repeated line | **211 of 5,337 — 4.0%** | 492 of 3,135 — 15.7% |
| repeated lines | **621 of ~40k — 2.9%** | 980 — 4.1% |
| of those, bare media placeholders | **0** | 389 — 40% |
| of those, a label echoed at both ends | **0** | 91 — 9% |

Both named causes are gone: the first with `499fd6d` (§M.0), the second with
it, since `Deprecated. Not for use in new websites. Deprecated` was the
taxonomy echoing a label it should never have drawn.

What remains is **621 lines with no identified cause**, and that is the honest
state: a residue, not a diagnosis. It is smaller than the flag implied and it
has not been explained.

### M.3 — D-6 withdrawn: the metric could not tell two siblings from one move

The evidence for `D-6` was: *"N% of duplicate-chunk groups differ only by a
positional index in the xpath"*, computed by blanking every `[n]` and seeing
whether the addresses collapsed to one skeleton.

**That test cannot distinguish the two cases it was built to separate.** Any
two siblings share a skeleton once their ordinals are blanked. Looking at what
it actually matched:

```
…/section[12]/div[2]/div/div/ol/li[41]/span[2]/span[3]
…/section[12]/div[2]/div/div/ol/li[69]/span[2]/span[3]
…/section[12]/div[2]/div/div/ol/li[125]/span[2]/span[3]
```

Those are entries 41, 69 and 125 of an Arabic Wikipedia reference list. They
exist *simultaneously* and carry identical text. The page repeats itself —
`D-4` — and the test called it an index shift.

**The `div` vs `div[3]` case that looked decisive was also misread.**
`sensing.py::_name_test` emits a bare tag when the ordinal is 1:

```python
return f"{tag}[{ordinal}]" if ordinal > 1 else tag
```

So `div` *is* `div[1]`, and `/…/div[2]/div/bsp-header` against
`/…/div[2]/div[3]/bsp-header` names the first and third children — two real
containers, each holding a header. Addresses are ordinal-stable by
construction; the sensor's `stepFor` always emits an explicit ordinal and only
the formatter elides `[1]`.

### The instruments that actually answer the question

Both already existed. Neither was used before the defect was filed.

**`--resolvable`** — *"ask the page whether every address in the trie names a
node it has"*. It is the only oracle independent of both the fold and the
walk, which is exactly the independence a claim about phantom addresses needs.

| | |
|---|---|
| pages | 2 (books.toscrape.com, danluu.com) |
| addresses asked | 719 |
| **unresolvable** | **0** — names nothing in the page |
| **mismatched** | **0** — resolves, holds something else |

**`--drift --kind insert`** — mutate, repair, score the repaired trie against a
fresh full map. This is the delta path, which is what Addendum II's phrase is
about.

| page | mutations | recall | **stale** | **lost** | wrong | moved |
|---|---|---|---|---|---|---|
| books.toscrape.com | 1 | 100.0% | **0** | **0** | 0 | 190 |
| books.toscrape.com | 3 | 100.0% | **0** | **0** | 0 | 192 |
| books.toscrape.com | 5 | 100.0% | **0** | **0** | 0 | 194 |

3 of 3 exact. An insertion moved ~190 addresses and **not one went stale** —
`stale` being precisely *"addresses the trie holds and the page does not"*,
which is the defect as stated.

### What this does NOT establish

Stated plainly, because a withdrawal that overclaims is the same error
inverted:

- **One page carried it.** danluu.com was excluded — *"no drawn repeated
  group"*, a page that could not fail. Two pages asked, one scored.
- **Both pages are static.** The flag may well be about pages that move on
  their own, and coinmarketcap's ticker is the known hard case. `--drift` on a
  moving page needs its `--kind none` null arm first.
- **Only `insert` was run.** `delete` and `relocate` are the gestures where a
  pop is most likely to be missed, and `relocate` is the one that matches
  *"reassignment"* most literally.
- **The store-side observation was real even though the diagnosis was not.**
  105 duplicate-chunk groups exist on the 256 store. They now read as `D-4`,
  the page repeating itself, which `M-8` already covers and which Addendum II
  puts in scope. The duplicate chunks the user saw are real; what was wrong
  was attributing them to the index path.

So `D-6` is withdrawn as *not demonstrated*, not as *disproved*. The next run
is `--kind delete` and `--kind relocate`, each against its own `--kind none`
arm, on a corpus that includes a page known to move.

### M.5 — three reported 2026-09-13, then measured

Reported from the app against chunk `98b0c576` of `coinmarketcap.com`, whose
root is `…/table/tbody/tr[91]` — **a table row**, which turns out to explain two
of the three. Measured on `build/vaultws256` (5,337 chunks, current code) before
anything was filed, because `D-6` and `D-7` were both filed from bad
measurements and both withdrawn within hours.

#### M.5.1 — one image, two lines

| | |
|---|---|
| chunks containing media | 835 of 5,337 |
| **same url with an empty alt AND a named alt** | **365** — 44% of them |
| url appearing with only an empty alt | 348 |

**Cause, from the addresses rather than the picture.** Two detections sit at one
`<img>`, and the renderer draws each as its own line:

```
line 0   image | src|media.tag/img   …/td[3]/div/div/a/span/img   ![](…34466.png)
line 1   image | alt|media.tag/img   …/td[3]/div/div/a/span/img   ![PENGU logo](…34466.png)
```

Identical xpath, different accessor. That is not an indexing fault —
`ContentTag`'s own docstring makes `(xpath, category, subcategory, source_attr,
sub)` the key, so `src` and `alt` are legitimately two detections of one
element. **The defect is in the projection**: a url and its caption are one
image, and drawing them as two lines both doubles the media and produces the
"empty image with no text" that was reported, because the line carrying the url
is the one WITHOUT the alt.

This is adjacent to `D-7`, which was withdrawn correctly — `499fd6d` stopped the
taxonomy being drawn as a caption. It did not merge the two accessors, and that
is the part still outstanding.

#### M.5.2 — naked fields: a row without its headers

| | |
|---|---|
| chunks rooted at a `<tr>` | 79 |
| **rows carrying ≥3 unlabelled values** | **44** |

`90`, `0.14%`, `0.78%`, `16.00%`, `$455.28M`, `62.86B PENGU`, `-4.07` — every
one a value with no name. The names are real and in the page; they are in the
table's header row, which is not in this chunk because the chunk is the row.

**And the names are recoverable, which is what makes this a defect rather than a
limit.** The addresses carry the column:

```
cell | text()[0] | table.*   …/tr[91]/td[2]/p/text()[1]      90
cell | text()[0] | table.*   …/tr[91]/td[4]/div/span/text()[1]  $0.007242
cell | text()[0] | table.*   …/tr[91]/td[5]/span/text()[1]   0.14%
```

`td[n]` is the column index, and the header for column *n* is the table's
`th[n]`. So a cell can be named by the header at its own position, from the trie,
with no new detection.

Why it matters beyond looking wrong: `M-11` says quality must hold *at the
interactive chunk level, because the chunk is what gets embedded and its
structure decides how representative the vectors are.* A row of bare numbers
embeds as almost nothing — `0.14% 0.78% 16.00%` has no subject — so these 44
chunks are close to unretrievable by meaning, whatever the retrieval stack does.

#### M.5.3 — duplicate chunks, still

Reported as still present. §M.1 counted 105 duplicate-content groups on this
same store and attributed them to `D-4`, the page repeating itself; nothing has
been done about `D-4`, so the report is consistent with that and with the two
findings above, which produce visible duplication inside a single chunk without
producing duplicate chunks.

**Not separated yet.** What is missing is whether the duplicates being seen are
§M.1's 105 groups or the 365 within-chunk image pairs — the two look identical
from the panel and have different fixes. Next: re-take §M.1's count and compare
group-for-group, not count-for-count.

### M.4 — the standing lesson### M.4 — the standing lesson

Two defects filed and both withdrawn within hours, with one shared cause:
**a metric invented for the occasion, when the repo already had an
instrument.** `D-7` was measured against a store older than its own fix; `D-6`
was measured with a discriminator that could not discriminate. `--resolvable`
and `--drift` existed the whole time, and both were built precisely because
this project has made this class of error before.

`CLAUDE.md` gains the first lesson (compare the store's mtime to the module's
last commit). The second belongs beside it: **before writing a measurement,
check whether `domvec.analytics` already answers the question.** A fresh metric
has no non-vacuity arm, no null arm, and no history of having been wrong in a
known way — the existing harness has all three.

---

## N. S-13 — can Electron host the sensor? Measured, in the running Obsidian

Addendum II asks this as an investigation: *"there are still selenium-like
interfaces that can perhaps overtake a firefox browser telling an electron
browser what to see. Perhaps, instead, we explore any selenium-like links with
electron itself such that we obtain the same sensor-like functionality while
staying slim on web interfaces and able to control profiles from their base."*

`S-13`'s deliverable is a capability verdict with evidence. This is it, taken
over CDP against the live Obsidian (`X-2`), not from documentation.

### N.1 — what the renderer actually reaches

Obsidian 1.13.7 runs **Electron 39.8.3 / Chromium 142 / Node 22.22.1**, with
`nodeIntegration` on and `@electron/remote` exposed to plugins. From plugin
code:

| via `require('electron').remote` | |
|---|---|
| `BrowserWindow` | function |
| `WebContentsView` | function |
| `BrowserView` | function (deprecated by Electron) |
| `session` + `session.fromPartition` | object / function |
| `app`, `webContents`, `webFrameMain` | available |
| `getCurrentWebContents().debugger` | **present — CDP from inside** |

`<webview>` is also available, but **Electron now advises against it**:
*"Chromium's webview is undergoing dramatic architectural changes... consider
alternatives, like iframe, a WebContentsView, or an architecture that avoids
embedded content altogether."* So `P-B3`/`P-B4` should be built on
`WebContentsView`, not the `<webview>` tag. That is a correction to the
obvious reading of those rows.

### N.2 — the verdict: yes, and it is demonstrated

Driven from plugin code in the running app, with **no Firefox and no
geckodriver**:

| step | result |
|---|---|
| isolated persistent session `persist:domvec-probe` | obtained — this is *"profiles from their base"* |
| hidden `BrowserWindow` on that partition | created |
| navigate to `https://books.toscrape.com` | loaded |
| `executeJavaScript` in the page | title, **542** DOM nodes, **94** anchors |
| **`MutationObserver` attached to `document.body`, subtree** | **true** — the fold's own primitive works |
| `webContents.debugger` | available |
| teardown | destroyed |

`preload` is the injection point the sensor needs: it runs *before* page
scripts, which is required for a fold that must not miss the first mutation.
`executeJavaScript` on `dom-ready` is the fallback for re-injection.

### N.3 — the finding that is not about tidiness

**Electron loaded a page Firefox cannot.** `apnews.com` refuses automation: it
returns 403 to curl and timed out the Selenium/geckodriver scan at 40,000 ms,
which is why the 256 re-cut holds 23 pages and not 24.

| | Firefox + geckodriver | Electron `BrowserWindow` |
|---|---|---|
| `https://apnews.com` | **TimeoutException at 40,000 ms** | **loaded in 26,350 ms** |
| DOM nodes | — | 10,161 |
| anchors | — | 1,772 |
| body text | — | 22,340 chars |

That is not a performance argument, it is a **coverage** argument: the corpus
is currently missing a page because of the host, and the alternative host
reaches it.

### N.4 — what this does not settle

The verdict is *the capability exists and one real advantage is measured*. It
is not yet a decision to migrate, and Addendum II did not ask for one.

- **26.4 s is not fast.** It is inside Firefox's timeout but not comfortably.
  One load, one page; no distribution behind it.
- **`sensor.js` was not run.** `MutationObserver` attaching proves the
  primitive; it does not prove the fold, the taxonomy, or `repairMs`.
- **O(delta) is unmeasured on this host.** Every timing in
  `build_analytics/` was taken under Gecko. They are not transferable, and
  re-taking them is the real cost of this migration.
- **Closed shadow roots stay closed** (hard constraint 6). Electron changes
  nothing here and must not be presented as a way in.
- **`shadowRootsReachable: 0`** in the probe is a property of
  books.toscrape.com, not a shadow-traversal result. Untested.
- **Chromium version is Obsidian's, not ours.** Today it is 142. We ship
  `geckodriver.exe` and control that; an Electron host inherits whatever
  Obsidian ships and upgrades when Obsidian does. That is a real loss of
  control traded for one fewer binary.
- **Single-engine risk.** `invariants.a1` and `c1` compare composed-tree walks,
  and the addressing convention was developed against Gecko. Moving to Blink
  changes DOM edge cases; the invariants have to be re-run, not assumed.
- **Detectability.** apnews admitting Electron where it refused geckodriver is
  today's behaviour of one site's bot detection, not a property. It can change
  and it is not a guarantee for other pages.

### N.5 — the cheap next step

Run the existing sensor against an Electron-hosted page and compare the map to
the Gecko one for the *same url*, address by address. `invariants.a1` already
does this comparison; it needs a second host, not a new measure — which is
`M.4`'s lesson applied before making the same mistake a third time.

---

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
