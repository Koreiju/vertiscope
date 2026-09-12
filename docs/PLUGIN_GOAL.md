# The plugin — standing goal

**Set 2026-09-09. Binding.** This is the plugin's equivalent of
`AFFINE_MAP_GOAL.md`: the user's own statement of what is being built, kept
word for word. Where any other document disagrees with this one, this one
wins and the other document is the thing to change.

`PLUGIN_PRD.md` decomposes the earlier prompts into 40 numbered, measurable
requirements. It is not superseded — it is *incomplete against this*. Several
of the sections below (the Jupyter/LLM half, the site-packages corpus, the
chained single-hop prompt architecture) have no requirement number at all yet.
Read this first, then that.

---

## The user's statement, verbatim

> We need an obsidian plugin that links interactive shadow DOM stream elements
> in millisecond O(delta) time, and reconstructing the full digital trace of
> the page over a unified patricia trie of
> domain/url-tail/xpath/markdown/content-detection. The patricia trie is what
> is streamed as well to the interactive side of the obsidian panels, which
> are retrofitted to show their *base and original* markdown editors with
> their interactive html cards. Each of these cards correspond to the chunk
> threshold set by the shadow DOM recursive sensor/scanner. We essentially
> re-render a minimal form of the original web browser in this html panel.
> This panel is not meant for presenting raw HTML or re-rendering something
> that a web browser does. This should render everything the same as a web
> browser, with options to interact with it via the database and offline.
> However, and more importantly to the patricia trie structure, when we
> interact with these obsidian-chunk-panel-browser renderings, we are still
> sending messages to the original webpage if there is an internet connection.
> Markdown rendering/distillation should be carefully tuned such that we
> obtain the full content of the original in-browser html, but as a
> hierarchically-header-structured markdown document with tables, images, web
> links, and markdown panel links (to other markdown panels) as appropriate.
> We treat links to other markdown documents per the editable portion of the
> original obsidian markdown editor side of the panels as rendered gestures
> (this might go against some of our docs so we need to update our docs to
> match this new gesture) where when the sequence of four `[]()` symbols are
> typed, the entry in the square brackets acts as a semantic retrieval
> feature, and the results are shown in some new filled/scrollable whitespace
> immediately below the line such that the remainder of the markdown panel
> editable lines are uninterrupted in rendering as a cohesive unit. Once a
> scrolled result is clicked, the link is infilled between the empty
> parentheses. Every stream from the sensor/scanner on the selenium side to
> the db must be persisted to live streamed updates to the obsidian graph view
> and the opened and closed panel set uniformly. Re-projections over umaps can
> be batched in a queue at a latency that adapts to match the time scaling of
> the umap updates. Every single interaction with the page is
> mutation-observed by the sensor and immediately persisted through the
> obsidian browser-half of the panel with O(delta) streaming as well to the
> database and vectorization, updates to the patricia trie, etc. The markdown
> panels that are rendered from the shadow DOM html must be such that they
> appear as regular/normal/minified form. We can use the editable-render-half
> (left hand side on the page: https://milkdown.dev/playground) of the
> Milkdown playground that matches the obsidian markdown editor panel style
> uniformly as a *quality* standard for how well/compacted and complete the
> shadow DOM browser renderings from live selenium. We should go for the same
> content standard of structuredness, completeness, and elegance (no dedups,
> headers and structures within markdown structures are appropriately and most
> simply matched without things like intermediated hierarchical fields when a
> singular path node of some form of structure like that is rendered from its
> shadow DOM and interactive browser half). We also need to pay attention to
> inter-spatial normalization on UMAP nodes since most are way too compressed
> together to see anything discernable. Ensure that UMAP projector embeddings
> are also saved to the db such that they are immediately queried to the graph
> view. Please also don't forget about graph linkage completeness along
> patricia trie, web links, and markdown links. Ensure that we are also
> matching and keeping our patricia trie efficient to our per-chunk links (as
> in, what are intermediate paths in our patricia trie are also reflected as
> such by the chunk node linkages). Image/media renderings should also be
> complete and present in both sides of the panels (markdown and web browser),
> as well as in the 3D inter-normed UMAP projector view. There must be some
> way to render/port streams from the browser via our sensors over to our
> panels efficiently. Perhaps there are some very niche packages for this?
> Completely and exactly mirroring features/calls to the original selenium?
> Also, note that each visit to each page should apply a smooth and live-tuned
> (per the updates on selenium) steady scroll to make sure that we are getting
> a fine-grained view of all dynamically rendered features on the page while
> also staying as time-efficient as possible. Pagination, however, is left to
> the per-chunk browser views to be manually interacted with.
>
> We also want to add an interactive language model feature to our obsidian
> markdown panels as well. This should include/extend also our obsidian panels
> into fully-fledged jupyter notebooks. The idea would be to centralize
> retrieval and code research into one interface where our chat contexts are
> localized to a panel, we can pull existing chunk panels into a new chat and
> aggregate or chat within-chunk as well, and run code experiments in the
> jupyter kernel terminals. This could also then open up generating new code
> artifacts and linked modules if we make the most of our vault interface that
> obsidian already has that can be directly provided a facade for to expose
> local jupyter terminals to the filestructure and space. This also means that
> code artifacts can be vectorized per their comments and docstrings and added
> to our database, where the local vault is a part of the patricia trie in the
> DB, and we can view live delta updates to modules as well in both sides of
> their panels and their UMAP 3D graph view. We will use local quantized Nous
> Hermes 2 DPO 7B on local CUDA as well. I think having full powershell
> terminals and notebook terminals would be best (with a toggle switch on a
> code block that opens a terminal/notebook kernel panel depending, possibly
> running both at the same time). Module dependencies and vault directory
> should also be shown as visible links in the UMAP. Full code artifacts
> should be viewable and editable as standalone as well. A terminal only below
> the artifact panel should always accompany the artifact. Finally, and this
> one's a doozy; we apply the same semantic chunking and triple-retrieval
> vectorization principles to not only our local vault, but also to the full
> set of installed python packages and their code modules as well. We will
> apply per-package database partitioning with main DB links for
> access/lookup, and retrieval here will apply an initial vector-centroid
> filter prior to fine-grained partition-wise retrieval. However, this filter
> is just a means to an end; all retrieval comes from the singular `[]()`
> interface. Look always for github packages and examples whenever considering
> anything about any feature or links you are focusing on as mentioned here.
> This is part of the verbatim.
>
> That being said, we want the context window for our small language model to
> be controlled. We will constrain all interactive workspace information to
> our system prompts that are live-updated during the chat context that
> exposes only single-hop endpoints for each component of the interactive
> interfaces (calling tools that navigate the current state of the workspace
> up or down, along with the current toolset for the plugin interfaces). The
> toolspace should be a singular spine that exposes single-hop actions that
> small language models can understand while simultaneously keeping a healthy
> receptive field for the main task and thought processes. All information
> flow to our language model will be constrained to the chunk panels only, but
> still with the hop navigatability over the patricia trie as well. So, the
> model can crawl between chunks as well as retrieve and link them. Another
> thing to note; since we are localizing to single-hop structural navigation,
> each hop gets its own custom system prompt depending on the workspace
> layout. We should design the LLM interface such that its prompts and outputs
> are chained together. There is a basic prompt injection instruction from the
> previous system in the chain, where the previous system's output instructs
> and informs the current system's input. The main hop-wise knowledge is
> stored and partially streamed to the system prompt on all things that can be
> made observable within reason and context window limits per the state of the
> current hop and action interfaces in the toolspace. Each model's output is
> then a current track of the thought process, and the relevant next-hop tool
> call. If models call tools multiple times and don't hop over the workspace,
> their sub-context windows persist accordingly. Once all chained call and hop
> instructions are completed, the leaf-wise outputs from the chain are
> synthesized and presented to the model/context in the main chat as a final
> aggregate-pass step. The ideal; partitioned inter-context thought streams,
> coupler-style inter-context hop and tool calls, and instructional primitives
> on the state and purpose of each hop in the workspace. This means a lot of
> system prompts and structured tests on chain input-output quality. We care
> both about the models knowing the full extent of the thought stream and how
> their current hop applies to the task/available choices.

---

## Addendum, 2026-09-12 — the projector, the panels, the scanner

**Also binding, and it OVERRIDES the statement above where the two differ.**
Two overrides are explicit and one settles a question the first statement left
ambiguous; they are listed under "What the addendum changes" below.

> [...] The UMAP 3D graph view with patricia trie and markdown rerieval-based
> links shown, as well as module dependencies for codebases and python
> modules, including those in local pypi packages. The full skeleton structure
> of linked data that comes from both web, the local project vault, and pypi,
> all their semantic vectors and hard graph-based links stored in the same
> database. For the time being, and this directly replaces any verbatim
> statements on this, we can consider that quantized semantic (and not
> pre-umapped frequency) vectors are the primary embeddings space for the
> *projector*, while we still apply triple-retrieval with
> frequency-quantized-pagerank searches. Chunk embeddings, since they are from
> the same model, can be UMAPped to the per-document source in batch. However,
> that which generates these chunk embeddings is very important, and discussed
> in the next point.
>
> The per-chunk panel view that is specialized for the interactive components
> of webpages (and the full and milkdown playground demo level quality of
> structure, content, organizedness, and completeness, however remaining
> within the pre-set context window chunk limit of 512 tokens throughout
> processing, perhaps with double-checks and balances after the initial shadow
> DOM selenium scanning sensor). The code artifact panel views with a terminal
> below them as well. Then, a third type of panel that is a
> retrieval-enhanced jupyter notebook kernel that can switch between jupyter
> kernels and powershell terminals.
>
> The scanner itself, using mutationobservers, content detection,
> deduplication efficiently in O(delta)-millisecond time with a queue that
> maps the distilled page's markdown structures in their chunk-batches to the
> vectorization steps (tfidf is global, though, to the full db corpus). This
> is where the quality of the markdown generated aligning itself to the
> milkdown playground standard of content (image, links, embedded links,
> headers, tables, etc) is most important. Not only do shadow DOM nodes need
> to be localized properly to their ancestors in the patricia trie for
> structural guarantees on the distilled HTML that retains these quality-based
> properties of the markdown output. they need to retain this high-quality
> markdown structure at the interactive chunk level so that semantic and
> frequency embeddings are most accurately representative. This also
> emphasizes the requirement for full structural preservation along content
> links in nested shadow DOM nodes, while also behooving the requirement for
> full deduplication of repeat substrings that are essentially structural
> redundancies of the web pages themselves.
>
> In all cases, web searches on github codebases and examples that work are
> the most important drivers of success at every step of the work's dynamic
> directions.

### The minimal embedded chat, and the panel types it lives on

> We will add back the quantized chat feature as something much smaller and
> minimal, and make it an embedded tool within the jupyter notebook panels; at
> the bottom of the cell that has been selected, either markdown, code, or the
> terminal/kernel, the context window for the small language model then starts
> at this "last-most viewable cell within current selection/focus" as the
> terminal point and re-winds backwards within the notebook in its *current
> state* (including terminal or kernel output display, where for intermediate
> cells this is the norm for where to rewind the context window from). The
> chat prompt and response panel is a *hovering one* that follows the user's
> scrolls and does not apply a new re-wind over the context window until the
> user has selected/interacted with a new cell (essentially apply a new
> re-wind whenever the cursor lands on a new cell, and this is injected into
> the user prompt as the effective contextual history, where the user prompt
> decides how many remaining chunks of tokens to rewind backwards for. Here,
> our jupyter notebooks are dynamically recursively chunked similarly to our
> webpages and continuously diff-updated to the db (including re-vectorization
> and chunk assignment). Since we may inject new re-winds intermittently but
> want to keep the sessions the same without compacting or re-starting with
> one-shot, the token limit for our re-winds are within a safety factor of the
> maximum token limit for an input prompt. We will keep this simple and as-is
> for now. Later on, we will return to add more things like cell and code
> navigation, running things in the terminal, writing updates to the
> notebooks, and so on.
>
> I should also note the requirement to keep the original obsidian markdown
> panels in their native form as well, which are different form the
> retrieval-enhanced notebook kernels. However, to add to the native markdown
> default with obsidian, we include similar retrieval as well. Then we build
> on this native form to include code, kernel, and terminal options. We also
> add the hovering chat ontop of the native obsidian markdown panels too. The
> buttons for adding the completely new structural cells are at the very
> bottom of the obsidian markdown, while the hovering chat is always below the
> boundary of the scrollable markdown window. So, we essentially build the
> native obsidian markdown out into this more fully fledged interactive panel.
> I think the final step would then be to add interactive web browser chunk
> cells as well to this set. However, the way browser interactions and dual
> panel views work is slightly different, and particularly so.
>
> The way the browser notebook cells with dual view would work in this
> instance would keep all the same scanning and O(delta) streaming properties
> the same. But, instead of constraining the browser views to their chunks, we
> apply a fully-fledged and regular web browser view to the cell. So, we can
> navigate the webpage exactly as we would in a regular browser, but the view
> of the browser port is such that we apply scanning while the live browser
> itself is being navigated. If there's a way to embed the native selenuium
> session view within the cell and allow the resizing of the notebook cells to
> affect the window size of the selenium browser, that would be best. So,
> similar to how we navigate code-spaces in jupyter code cells, our web
> browser view gives us access to the web itself but constrained to the
> notebook view. As we navigate the page (scrolling, hovering, interacting
> more generally), our passive mutationobserver sensor is always firing and
> tracing along the O(delta) millisecond *diff* updates from DOM to DB with
> the patricia trie. As this is happening, the chunk deltas are diffed to our
> projector view, where we can view the per-chunk browser and markdowns as
> dual panels from there as well. However, we can also use web browser
> notebook cells as well to navigate the web from this plugin. Left clicks in
> the browser do the same things as a regular firefox with selenium open.
> Hovering over the page, though, includes an overlay that highlights the
> chunk structures overtop of the page's native cartesian displays to show the
> effective chunks embedded within the page. Right clicks, then, would locally
> index chunks to their dual-view markdown panels within the browser cell,
> which is what feeds the SLM context. This includes the full type set we've
> tracked so far (but only the static things and not the interactive
> components that are meant for tool calls in much later iterations).
>
> Also, please don't forget about how docstrings are vectorized for codebases,
> and code docs more broadly speaking.

### What the addendum changes

**The projector's embedding space.** *"Quantized semantic (and not
pre-umapped frequency) vectors are the primary embeddings space for the
projector."* This replaces the joint fit `layout.py` performs today — tf-idf
and semantic each reduced to equal width, unit-normalised, concatenated, one
UMAP over both, with `equalised` reported from the widths. Frequency leaves
the PROJECTION and stays in retrieval. `halves` / `equalised` stop meaning
anything and go with it.

**Chunks and documents share one fit.** *"Chunk embeddings, since they are
from the same model, can be UMAPped to the per-document source in batch."*
Two node kinds in one space, fitted together — not two projections overlaid.

**"No dedups" is settled, and it means deduplicate.** The first statement's
"no dedups" sat in a list about elegance and could be read either way; it was
raised as an open question and this answers it: *"full deduplication of repeat
substrings that are essentially structural redundancies of the web pages
themselves."* When a page repeats itself structurally, the chunk shows it
once. This overrides `markdown.py`'s deliberate tuning "17:1 toward leaving
noise rather than risking loss" for the structural-redundancy case
specifically -- 88% of measured in-chunk repetition is the page repeating
itself, and it is now in scope.

**The window is enforced throughout processing.** *"Remaining within the
pre-set context window chunk limit of 512 tokens throughout processing,
perhaps with double-checks and balances after the initial shadow DOM selenium
scanning sensor"* — a verification pass after the scan, not only a cut at
render time.

> **Follow-up decision, 2026-09-12: the window is 256, not 512.** Taken in
> conversation after this statement, so it supersedes the figure above while
> leaving the requirement around it intact. 64 was chosen first and reverted:
> it splits a nav bar into three chunks of menu labels. 256 is the smallest
> window at which every structural property holds, and it beats 512 on
> retrieval by about ten points. See `PLUGIN_PRD.md` section 0b for the table.
> Also settled there: "quantized" means the f16 GGUF nomic already running,
> not product-quantized vectors.

**Deferred by name, so it is not an omission.** Cell and code navigation,
running things in the terminal, and writing updates back to notebooks are
explicitly "later on". Interactive components inside browser cells are "for
tool calls in much later iterations" — browser-cell right-click indexing
covers the static type set only.

---

## Addendum II, 2026-09-12 (later the same day) — the sensor's host, two duplications, and the order

**Also binding.** Taken in conversation after Addendum I, so it wins over both
statements above where they differ. It settles the browser substrate, opens a
line of investigation that is NOT yet a commitment, names a defect class that
had no requirement, and fixes the near-term order.

> Let's straddle the shipped core web viewer and take ownership of electron as
> we go, granted that there are still selenium-like interfaces that can perhaps
> overtake a firefox browser telling an electron browser what to see. Perhaps,
> instead, we explore any selenium-like links with electron itself such that we
> obtain the same sensor-like functionality while staying slim on web
> interfaces and able to control profiles from their base. This will also help
> with interactive interfaces that link to our O(delta) diff recursive chunking
> algorithm. One issue I'm flagging now is that we see a lot of both duplicate
> chunks (as in reassignment and diff-based index pop updates don't land
> straightforwardly) and also duplicate content within the markdown panel
> renderings. Repeat fields and such. Perhaps another part of what we will now
> take note of and at least verify the capabilities of to explore. Then, we
> move onward to the notebook kernel panel design first to nail it down
> correctly. This is where we bring in our electron sensor when ready, exposing
> the chunk scanning and selection highlighting for markdown rendering in the
> alternative panel by the user to annotate the context fed to our small
> language model. Then, we go for the hovering SLM bar itself and work out the
> details.

And, on the window, in the same exchange: **re-cut the corpus at 256 now**,
before the panel work, rather than building against the 512-token store.

### What Addendum II changes

**The browser substrate is "straddle", not "pick".** Obsidian ships a core
`webviewer` (disabled in this vault as of today) and it is to be used *and*
outgrown: take ownership of Electron as the work proceeds. This supersedes any
reading of P-B3 as "embed Selenium's own window or nothing".

**Selenium's ROLE is now an open question, not a fixture.** The verbatim asks
whether driving Electron directly can give "the same sensor-like
functionality" — with a named benefit, "staying slim on web interfaces and
able to control profiles from their base", and a named consequence, that it
"will also help with interactive interfaces that link to our O(delta) diff
recursive chunking algorithm". Note the framing: *"perhaps"*, *"explore"*,
*"at least verify the capabilities of"*. **This is a capability investigation
with a deliverable, not a decision to rip out Selenium.** A requirement that
records it as settled would be overstating the instruction.

**Duplication is two defects, not one, and they are at different layers.**
The verbatim separates them explicitly:

1. *"duplicate chunks (as in reassignment and diff-based index pop updates
   don't land straightforwardly)"* — a **trie/index** defect. The delta path
   re-admits a chunk it should have reassigned or popped, so the store holds
   two addresses where the page has one. This is upstream of any rendering.
2. *"duplicate content within the markdown panel renderings. Repeat fields and
   such."* — a **projection** defect, inside one chunk's render. This is the
   D-4 / M-8 structural-redundancy family, seen from the panel.

They must be measured apart. A single "duplication" number would mix an index
that double-counts with a renderer that repeats itself, and fixing either one
would move it — which is the denominator trap in `CLAUDE.md` exactly.

**The near-term order is given.** Re-cut at 256 → verify the duplication
capabilities → **notebook kernel panel design, nailed down first** → bring the
Electron sensor in *when ready*, exposing chunk scanning and selection
highlighting → **then** the hovering SLM bar. Note this REFINES X-6 rather
than replacing it: the notebook panel still grows from the native markdown
substrate, and browser cells still come last.

**Selection highlighting is a new gesture with a stated purpose.** *"Exposing
the chunk scanning and selection highlighting for markdown rendering in the
alternative panel by the user to annotate the context fed to our small
language model."* The user selects in the rendered markdown; the selection
annotates what the SLM is given. No requirement covered this — the panels
section had no notion of the reader marking context for the model.

---

## Standing instructions carried in the verbatim

Two of these are process rules, not features, and they bind every future
change:

1. **"Look always for github packages and examples whenever considering
   anything about any feature or links you are focusing on as mentioned here.
   This is part of the verbatim."** Search before building. The reason given
   is explicit later in the same prompt: *"we want to be able to see the code
   that our large language model is using to interact with our interface."*

2. **"this might go against some of our docs so we need to update our docs to
   match this new gesture"** — said of the `[]()` retrieval gesture. Where a
   document contradicts this file, the document is the thing that changes.

## The quality bar, named

The Milkdown playground's left-hand editable pane
(<https://milkdown.dev/playground>) is the *stated standard* for the markdown
half: "the same content standard of structuredness, completeness, and
elegance". This is a bar to measure against, not a library choice by itself.

Its negative form is specific and testable: **"no dedups, headers and
structures within markdown structures are appropriately and most simply
matched without things like intermediated hierarchical fields when a singular
path node of some form of structure like that is rendered."** A wrapper chain
collapsed into one node in the trie must not reappear as a chain of empty
headers in the markdown.

## What this asks for that the PRD does not yet number

Recorded here so the gap is visible rather than implied. **Most of what this
section once listed has since been numbered** — Nous Hermes is `L-1`, the
Jupyter/PowerShell panel `P-N1`/`P-N2`, the minimal browser `P-W4` and `P-B1`,
the `[]()` gesture `R-1..R-7`, persisted UMAP `G-12`, adaptive re-projection
`G-13`, inter-spatial normalization `G-4`, the PyPI corpus `T-6`/`G-9`, the
vault in the trie `T-5`, trie-faithful chunk linkage `T-4`, live-tuned scroll
`S-8`, uniform delta streaming `S-12`, and code artifacts `P-C1..P-C5`. A list
that keeps claiming a gap that has closed is worse than no list, because it
invites the same work twice.

What genuinely remains unnumbered, and why:

- **The chained single-hop prompt architecture** — one system prompt per hop,
  each generated from the workspace layout at that hop; the previous link's
  output instructing the next link's input; per-hop sub-context windows that
  persist while a model stays put; and a final aggregate pass that synthesises
  the leaf outputs back into the main chat. Deferred by `PLUGIN_PRD.md` §0b,
  not dropped: Addendum I's *"put the LLM complexities aside"* scopes it out
  of the minimal chat, and nothing contradicts it.
- **Structured tests on chain input/output quality** — named in the first
  statement as a deliverable. It belongs with the architecture above and is
  deferred with it.

## Research log

Kept here because the verbatim makes searching a standing rule, and a search
whose answer is not written down gets run again.

### Streaming the browser into the panel — rrweb, and why only half of it

[rrweb](https://github.com/rrweb-io/rrweb) is the same architecture the
verbatim describes: one full snapshot serialised to a node-id'd tree, then
*incremental snapshots* carrying only MutationObserver deltas, and a replayer
that rebuilds a live DOM from them. The transport format and the rebuilder are
the parts worth taking.

**Its capture half is the wrong half for us, and by exactly our axis.** Shadow
DOM support is reported incomplete: full snapshots render, but on incremental
change [nodes are removed and new ones are not pushed
correctly](https://github.com/rrweb-io/rrweb-snapshot/issues/71), and removals
inside a shadow root notify nothing. Since our entire substrate is shadow DOM
*and* our claim is O(delta), adopting rrweb's recorder would import a defect
precisely where we have no slack.

`wfh_chunk_engine.js::attachChunkObserver` already does the thing rrweb is
faulted for doing unreliably: it walks each chunk's subtree and attaches a
SECOND observer to every nested shadow root, because — its own comment —
"`subtree:true` does NOT pierce shadow boundaries".

**The hole we share, and it is testable.** The walk happens at attach time. An
element that calls `attachShadow()` *later* and populates it without any
light-DOM mutation is never observed, because there is no notification for
shadow attachment at all — the open WHATWG request for one is
[whatwg/dom#1287](https://github.com/whatwg/dom/issues/1287). Our re-chunk
re-attaches observers, so any light-DOM mutation heals it; a component that
mounts entirely inside a fresh shadow root does not. Worth a probe before it
is worth a fix.

### The `[]()` gesture — trigger yes, layout no

`EditorSuggest` is the native mechanism and it fits the trigger half exactly:
it fires on a regex over the line text before the cursor, and it is what
Obsidian's own `[[` wikilink and `#` tag completions use, so the popup is
themed and keyboard-navigable for free.

**It does not satisfy the stated layout requirement.** The verbatim asks for
results "in some new filled/scrollable whitespace immediately below the line
such that the remainder of the markdown panel editable lines are uninterrupted
in rendering as a cohesive unit". `EditorSuggest` renders a floating
`.suggestion-container` that *overlays* the lines below; it never reflows the
document, so the surrounding lines are covered rather than pushed.

The mechanism that pushes them is a CodeMirror 6 **block widget decoration** —
a `WidgetType` inserted as a block after the line, which the editor reflows
around. The ghost-text completion plugins
([copilot-auto-completion](https://github.com/j0rd1smit/obsidian-copilot-auto-completion),
[ai-autocomplete](https://github.com/Leoyishou/obsidian-ai-autocomplete)) use
the inline form of the same API.

So the build is a hybrid: `EditorSuggest`'s trigger regex and result model,
rendered into a CM6 block widget rather than the floating container.

### Notebooks and terminals

[JupyMD](https://github.com/d-eniz/jupymd) is closest to the verbatim's
description — markdown files behaving as `.ipynb`, live execution,
bidirectional sync through Jupytext.
[obsidian-jupyter](https://github.com/tillahoffmann/obsidian-jupyter) matches
the "toggle switch on a code block" more literally: a fence tagged `jupyter`
executes against a configured interpreter.
[Notebooks](https://community.obsidian.md/plugins/notebooks) embeds a real
Jupyter UI in a pane.

### Still unsearched

UMAP inter-spatial normalization; per-package vector partitioning with a
centroid pre-filter; terminal plugins; whether any package mirrors Selenium's
call surface into a remote panel.
