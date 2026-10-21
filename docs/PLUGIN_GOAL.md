# The plugin — standing goal

**Set 2026-09-09. Binding.** This is the plugin's equivalent of
`AFFINE_MAP_GOAL.md`: the user's own statement of what is being built, kept
word for word. Where any other document disagrees with this one, this one
wins and the other document is the thing to change.

`PLUGIN_PRD.md` decomposes these prompts into numbered, measurable
requirements -- 223 rows as of Addendum IV. It is not superseded — it is
*incomplete against this*. Several of the statements below (the Jupyter/LLM
half, the chained single-hop prompt architecture) still have no requirement
number at all. Read this first, then that.

**And the order matters.** Addenda I through III were written before their
direction was decomposed; Addendum IV was written six days after, which meant
`G-22`..`G-71` spent that week citing conversation nobody could read. The rule
is now in `CLAUDE.md`: new direction is transcribed here BEFORE it becomes a
numbered row.

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

## Addendum III, 2026-09-13 — the projector's coordinates

**Also binding.** Taken in conversation, so it wins over the statements above
where they differ. It concerns the projector only, and it is the third time that
surface has been re-specified — `D-1` moved it to the semantic space alone, and
this moves the space it is projected *into*.

> Also, for our UMAP, we'll use spherical/quaternion coordinates and quaternion
> distances between points where we center our focus on the origin.

### What it changes

**The output space is a sphere, not a cube.** `layout.py` fits into Euclidean
ℝ³ and then rescales into a cube of half-width `extent`. This asks for the
embedding itself to live on a sphere — UMAP calls that an `output_metric`, and
it changes the *fit*, not a transform applied after one.

**The metric between points becomes angular, not straight-line.** Two chunks are
near each other when the angle between them is small. That is a different
question from "how far apart are they in the box", and it is the one a sphere
makes natural.

**The origin is the centre, and that is a claim about the camera too.** `recentre`
exists in the graph view because a Euclidean cloud has an arbitrary centre and
the camera can end up *inside* it — the view's own comment records a camera at
z = −230 inside a cloud spanning ±249. On a sphere centred at the origin that
cannot happen: every point is at radius 1, so any camera outside the unit sphere
sees the whole of it. `TrackballControls`' target is already `(0,0,0)`.

### What it does not yet decide, and must

**"Spherical" and "quaternion" are two different embeddings**, and the phrase
gives both. Recorded as a question rather than resolved by picking one:

* **S² — the ordinary sphere.** `output_metric="haversine"`, two components read
  as latitude and longitude, mapped to a point on the unit sphere for drawing.
  It ships with gradients in umap-learn 0.5.9 and is the documented path.
* **S³ — unit quaternions.** Four components, normalised; the distance between
  two is the geodesic angle `2·arccos(|⟨p,q⟩|)`, with the absolute value there
  because `q` and `−q` are the same rotation. This is what "quaternion distances"
  says literally. umap-learn ships no such metric, so it is a custom
  `output_metric`: a numba function returning the distance **and its gradient**,
  which the optimiser requires.

**And the colour axis is unresolved by either.** The fit is six-dimensional
today: three components place a node and three colour it as HSV, which is the
whole point of `fitted_dims: 6` — hue MEASURES a direction the camera has no
room for. S² gives two components and S³ gives four; neither leaves three over.
So a choice is forced: fit more components than the position needs and colour
from the remainder, or derive colour from the quaternion itself (a rotation has
a natural three-parameter reading), or drop the claim that colour measures
anything and let it become a legend again — which `D-1`'s reasoning argues
against.

Until that is settled, any implementation would be choosing it silently.

**Read Addendum IV's "Addendum III, dropped and then restored" before
acting on this section.** On 2026-09-13 the spherical metric was dropped
and then rescinded twenty-one minutes later; it is shipped and applied to
the whole store. Only the COLOUR question above is still open, and it is
narrower than this section reads on its own.

---

## Addendum IV, 2026-09-13/14 - the second chunking stage, the browser cell

**Also binding.** Two days of direction taken in conversation, recovered from
the session record and kept word for word.

**It was written six days late, and that is the defect this addendum also
records.** `G-22`..`G-71` were decomposed from these prompts on the 13th and
14th; the transcription happened on the 19th. For those six days seventy
numbered rows cited conversation nobody could read, and reconstructing them
turned up two prompts that had left no requirement at all and one that
REVERSED Addendum III. `CLAUDE.md` now carries the rule: the transcription
comes first.

Ordered as it was given, with the clock. The prose inside the quotes is the
user's throughout; the headings and the notes under them are not.

---

### The projector's nodes are not all the same shape

> Note that billboards must get their own diameters because they're larger
> square panels and not small nodes too

> Like billboard panels, not markdown panels

*`G-21`'s collider radius. 827 of 5,337 chunks draw as square panels and
were being given a sphere's: 1.93 units reserved for a thing drawing at
12.73. The second line corrects my first reading -- I had taken "panels"
to mean the Obsidian markdown panels.*

### Links are missing from the picture

> Force direction works, but I don't see the patricia and inter-markdown
> and other links anywhere

> Nodes aren't linked in the 3D GUI when clicking to unfold.

*Two reports a day apart, of the same absence in two places, both correct.
The first was a regression I had just caused -- removing d3's link force
also removes its id resolver, and 2,961 edges silently held strings
instead of nodes. The second was never built at all: `unfold` returned
nodes and no edges. `G-6`.*

### The duplications, and what a token is

> I'm also seeing a lot of content duplicate style errors throughout
> (repeat chunks, repeat content within, repeat images, etc)

> Literally just exclude from the counting part but keep everything else
> the same

> url tails can contribute to frequency vectors but not quantized semantic
> embeddings, which get the pure text without links at all.

*`G-22`, `G-23`, `G-24`, `G-25`. The middle line narrowed my proposal: the
render keeps its links and only the COUNT changes. The third splits the
two vectors -- lexical keeps url path words as terms, the encoder gets
prose alone. Measured afterwards: 52.5% of every rendered token in the
corpus was a link target.*

### The long statement - two-stage chunking, the browser cell, retrieval

Sent 18:54 with five screenshots: two chunks selected far apart in the
projector, a chunk panel reading "104 tok - 41% of 256" whose content was
one avatar and one link, a cluster of visually identical nodes, and that
cluster's chunk showing eight words of plain text. Re-sent at 20:30 with
"Run the scan over 100 new pages now. I'll also repeat our focus, which is
progressing well so far:" in front of it, unchanged otherwise.

> You can also see in the two images, I've selected one chunk further up
> (green) and one chunk way further down (green also). I would suspect one
> piece of evidence to hold onto here is the fact that these chunks, once
> stripped to text only, would affect the partitioning count to be more
> conservative with its sub-chunking problems, which may also help with
> deduplication as well. Perhaps we could inform dedup with intra-
> embedding metrics on a DOM page? And for that matter, an algorithm that
> can also intelligently sinkhorn/anneal the chunks that are actually the
> same thing, but just outside of our existing metrics and heuristics that
> constrain the context windows. I would suggest the context windows
> aren't necessarily hard constraints, but obviously necessary and worth
> staging first with embedding dedup and merging second, since then we can
> begin with an appropriate window that is in fact still a subset of the
> max context window (remember, we chose 256 because of the hit@1).
> Perhaps this is where DBSCAN comes in, but to a more nearest-neighbors
> feature-metric aggregation kind of thing. I've also attached a couple
> more images of the same example chunk; most of the tokens are, in fact,
> link text that does not count towards the overall chunk window limit,
> since this new limit assumes only the bare text (alts, etc). Worth
> consideration to build and test for.
>
> One thing to mention about the dedup; it should happen over the db-side
> representation of the aggregate DOM chunks first and foremost since
> we're still getting duplicate chunks in a lot of cases currently. The
> embedding-side aggregation (dbscan etc) would enable a more intelligent
> partitioning of per-page chunks that begins recursively, and then
> bridges to embeddings with DBSCAN. Since we are focused on coarse-to-
> fine localized to shadow DOMs, we're not doing this for all shadow DOMs
> at a time, so we can make this a second stage to the *chunking* process
> which is not necessarily a completely new thing that happens outside of
> the scanning process itself. We can likely get away with DBSCAN on the
> quantized semantic chunks only, since frequency vectors are not
> dimension efficient and simply are there for the fine-grained
> preservation in retrieval, while larger-scale chunking and dedup merges
> can happen as a second stage after our 256 vectorization. We can keep
> the original 256-style chunks and their embeddings underneath, but a
> merge layer would be what actually indexes the overall high-level chunks
> that can then still be retrieved as 256, but represented, structured,
> and presented as the similarity-merged ones. There would have to be some
> careful determination between what counts as more or less 'exact'
> duplicates and what counts as 'should be merged as a larger chunk'. I
> don't think substring matching would work as well here, so it would have
> to be a careful metric thing. Perhaps if there is no other
> straightforward way, we include frequency vectors in dedup but as their
> own steps in the process. It could be that we first establish duplicate-
> links and *then* merge. If we can clearly see a "within this percent
> distance of the closest neighbor compared to the max of the closest
> neighbor distances" for just quantized encoder embeddings for the first
> stage, then good. Then, we *could* use frequency vectors post-dedup to
> double-check the deduped chunks that can be merged. Now that i think
> about it a little more though, it sounds like if we only used embeddings
> to dedup for merges and tried to establish structure, then we would also
> make good use of the overall retrieval mechanism that includes pagerank.
> Perhaps if we just applied this overall retrieval metric to the soft
> adjacency matrix of the shadow DOM in its current state, or otherwise
> when we exceed some N samples of DOM chunks from the recursive text-only
> token window, that says that 'this is when we get statistically
> significant discriminative value on dedup and triple-retrieval chunk
> matching'. Since our pairwise distance matrix is established with
> structural queues from pagerank as well as coarse and fine encodings
> from our quantized and frequency vectors, then our sinkhorn/annealing
> embedding-chunking could localize to their page structures. We may,
> though, have use for other tree-based structural metrics on our patricia
> paths instead of pagerank since the domain of the problem is focused on
> embedding-based locality. However, if pagerank solves an eigenvalue
> problem of relevance metrics, then it would be more appropriate a metric
> for structural-based linked aggregation. I would suggest starting with
> just the quantized nous embeddings to start and seeing/experimenting
> with sample sizes and effects on overall aggregate accuracy. It could be
> also that LCA path metrics could be more appropriate for inter-
> structural similarity to aggregate spatially-like subchunks with higher
> embedding similarity. Let's add this to the PRD and perhaps focus on
> this for now. Then, we can return to our original designs on
> notebook+terminal+chat+webbrowser panels. Remember that the webbrowser
> notebook cells should be actual electron browser cells, resizable within
> the notebook, as well as allowing it to resize along with the rest of
> the notebook within its panel window. And again, this is where our
> scanning will really be happening once this component is complete. Since
> all of these are centered on the browser cell, let's get to work on this
> one next. Perhaps to start you can open the actual Electron browser
> if/since you found that it works. See if there are MCP tools on github
> that can help out with development specifically on this as we migrate
> our existing sensor scanning and our new embedding-based aggregation
> (along with our regular text-only subchunk window updates). Then you can
> add the 'highlight hovered chunk' feature which will also validate our
> structural-dual-embedding aggregation/dedup step after the primary
> scanning processes are ready and have vectorize the text-components of
> the chunks properly (again, link tokens still count in frequency vectors
> but quantized semantic embeddings get text-only from the page). We
> should still be very careful about headers, fields, and formatting like
> the previous crypto stock panel that showed a good example (so we
> include these fields and formattings in our text vectorizations as well.
> I could suggest link-free markdown for quantized embeddings while
> keeping the pure and full markdowns as their original representations of
> the webpage in our obsidian panels as they currently are in the images I
> provided. I would suspect online dedup-aggregation/annealing would be an
> important aspect of deduping continuous scan streams in our O(delta)
> millisecond *diff updates* to our current patricia-structured scans. If
> there is a memory-efficient way of tracking/tracing the similarity
> matrix over time that is diff-efficient (so re-vectorizing only the
> affected chunks either in merging or splitting), that will help with
> continuous real-time streaming and UMAP projection batch minimization
> when updating our obsidian 3D graph GUI. However, these updates can't
> break our new force-directed features, which are highly appreciated and
> work with billboard image panels just fine. Thank you. The fifth image
> attached shows the value in focusing on dedup integrations as we migrate
> scanning sensors to electron. An entire cluster can be clearly seen of
> the *exact same chunk* which means we're still getting dedup leakage
> from somewhere. If you can find an efficient fix to this one without
> needing any embeddings (while still ensuring that these new features are
> delivered as well), then excellent! I'd also like to note the strange
> fact that the chunk of the fifth image is just text (shown in sixth
> image). This shows that it's a *real* dedup and chunk leakage problem.
> We will ensure work on our current scanning sensor heuristics try their
> best first, and then we will also add these embedding-based merges since
> they can help us with aggregating chunks to our original max context of
> 512 tokens anyways for display and all intents and purposes. Scoring the
> merged chunks takes the same token counting strategy as per our
> quantized semantic embeddings (markdown, but pure-text only that is
> link-free). Also, to the "Press Down Arrow" thing; I would imaging
> interactive components here are leaking as well. One of our design
> requirements is that we have interactive components in shadow DOM
> representations of browser chunks that has a lot deeper ties to
> interactions with their actual page if an internet connection exists. As
> in, through the patricia-trie, we can click on interactive components in
> the shadow DOM view and see effects in the browser. I would almost say
> that this work is actually still largely focusing on the actual Electron
> browser itself that would then selectively just render the sub-chunk
> browser views that have links to the remainder of the page underneath
> the hood for all chunks we click in the 3D graph view. However, this
> should not be mistaken for browser cells themselves. It might even be
> simpler to scroll to the chunk view in a standalone browser cell that
> has scanned chunk correspondences, essentially keeping the same browser
> session open and navigating to the different pages (scrolling into view)
> when the chunks are clicked in the GUI. So perhaps we simplify the
> browser cell (as a standalone electron) and this collapses the three
> different representations to one, really, and then the key distinction
> between the two different instances being whether or not the browser
> cell is part of a notebook or its own standalone thing. I would think
> the feature for hovering over chunks in the browser and seeing them
> highlighted as the same chunks in the overall 3D GUI representation with
> all of our embedding-related dedup second-stage updates to our scanner,
> as well as the migration to electron from selenium, would go hand-in-
> hand as the same move over sections in the PRD. Of course, the
> bookkeeping for these things has to happen in the database. When I say
> "browser cell panel" I mean the electron browser in one
> switchable/toggleable view and the right-click selected markdown (full
> markdown, essentially the same full markdown but actually rendered as a
> native obsidian panel in a switchable second view). So we can track the
> chunks scanned and O(delta) diff rendered in our 3D umap projector
> (staying batch-efficient as previously stated) through our electron
> browser GUI as well. I should only see a minimal highlight on the
> hovered electron chunks with 3D GUI correspondence without banners on
> the chunk details since they are already visible. The right click
> gesture ports the full-content markdown to the other view within the
> same panel. This obsidian-native markdown panel on the other side of the
> same standalone browser cell is also the same for when this panel is a
> cell within a notebook kernel panel as well. One gives a more collapsed
> view of the other, but the completeness of functionalities are the same.
> I also think we could get away with a hoverable chat panel on the
> standalone browser window as well that collects the right-click selected
> *full* markdowns as context efficiently so that the same chunks are
> *never* re-sent to the context window, meaning the delta-diff updates to
> the context window of the chat works similar. This is only for the
> browser component, and so re-wind logic in a notebook kernel overall
> stays the same. Chat outputs would be in a panel below the web-selected
> markdown, and essentially aim to follow the standard conversational
> structure of the chat, all in markdown. Perhaps the delta diff selection
> thing here really actually means isn't a box at all, and simply the
> right-clicked elements after the most previous response are included in
> the very next prompt (pre-injected into the markdown obsidian panel, and
> then injected into the prompt during conversations). In all cases, the
> aim would be to keep the continuous chat-based markdown styling and
> injection for conversations with language models that are shown in the
> notebook panel clearly as well as one continuous interactive *thing*
> that respects the context injection and rewind rules still. I think this
> would work if outputs and conversations were simply added to existing
> notebook cells that are selected. I would almost imagine, as well, a
> natural extension of the browser side would be a more persistent
> retrieval panel above the electron browser itself. Retrieval results
> would be *overlaid* within the browser, with selected results navigating
> to the pages. Note this should not mean script injection into the
> standard electron pages, but be a layer above as its own link to our 3D
> graph gui via the database under the hood, but still sends interactions
> to navigate to the url and chunk location in the electron browser. Since
> this is part of the standalone browser panel, it should be the exact
> same for the notebook cell. This is different from the retrieval
> interface and gesture within obsidian-native markdown panels, where
> chunks are inserted directly. However, if that retrieval feature works,
> then I'm sure we could also rig it as an overlay to the electron
> browser.

*Decomposed as `G-26`..`G-35` (the second stage) and `G-36`..`G-48` (the
browser cell, the chat, the overlay, the Selenium migration). "within this
percent distance of the closest neighbor compared to the max of the
closest neighbor distances" is `aggregate.py`'s merge radius verbatim;
`MERGE_WINDOW` 512 comes from "aggregating chunks to our original max
context of 512 tokens anyways".*

### The scan is not visible where it is supposed to be

> I don't see the scans running in the new browser panel like I would hope
> for our work

*Not decomposed at the time, and it should have been: the Electron panel
existed and the scanning still ran through Selenium behind it. It became
`G-47` only during the next session's streaming work.*

### The codebase is part of the corpus

> One other thing I think was mentioned earlier; including the codebase
> and not just web scans (as in our local codebase and our vault, as well
> as generally PyPi packages locally installed) is what enables us to see
> the scanning scripts that are running in our browser panel. So, we can
> see the code that runs the browser scans and also see it happen in the
> browser panel itself. Remember this means dependencies are tracked
> throughout.

> And also remember what I said on only vectorizing comments and
> docstrings and not the actual code itself.

*`G-49`..`G-52`, all four still open. Both prompts say "remember" -- they
are restatements of direction given earlier and lost, which is itself the
argument for this file.*

### The order of the aggregation work

> Let's make the next pass about a continuous sensor scanning over shadow
> DOMs as I navigate the browser manually and see all the chunk updates
> streamed live to the GUI. Afterwards, if not done yet, we add the
> embedding similarity aggregation with pagerank or LCA distance matching.

> Now add the embedding similarity aggregation with DBSCAN

> Now wire aggregation into the scan and capture settle and showing merged
> chunk panels

*`G-47`, `G-65`, `G-26`, `G-34`. "as I navigate the browser manually" is
the requirement and not a setting for it: not a batch scan that happens to
be watchable, but the reader's own browsing AS the scan.*

### The two windows, and what each is for

> With merged chunk embeddings for UMAP, let's take an averaging approach,
> or better yet, re-vectorize.

> That being said, 512 max context window for text-only tokens. The
> projector shows the aggregated vectors while the retrieval still runs on
> the 256 chunks.

*`G-27`, and the store's `group_embedding` column -- a merge group holds a
second vector of its own rather than borrowing its lead's, which is the
"better yet" branch. The 512/256 split is the shape of the two stages: the
projector draws merged groups, retrieval ranks 256-token chunks.*

### UMAP is transformed, not refitted

> UMAP when pre-fitted has a projection-like transform function for
> batches so we don't have to re-fit every time, but incrementally every
> time the number of total shadow DOMs scanned (per url tails) doubles.

*`G-67`. `Projection.transform` and the doubling schedule in `layout.py`
are this sentence.*

### Addendum III, dropped and then restored

This is the exchange Addendum III does not have, and without it that addendum
reads as an open question when the metric half of it is settled. In order,
over thirty-seven minutes:

> Also, we should apply the updates to our UMAP metric throughout our
> current projector chunks with the quaternion distance and spherical
> coordinates, as well as the full aggregation steps for the chunks that
> are currently in db that need this too

> We'll drop the spherical and quaternion stuff. Let's focus more on
> faster streaming and feedback for scanning and seeing the updates in the
> projector.

Then, on being shown the fitted spherical metric actually running:

> Wait.. back up... It works?

> If spherical UMAP works, and our aggregation is wired, please show that
> it works by processing everything we currently have in our DB with these
> parts of the scanning pipeline. You can also make processing
> asynchronous.

*So: the drop at 21:39 was rescinded at 22:00, and spherical UMAP with
quaternion distance STANDS -- `vertiscope/obsidian/spherical.py`, applied to
the whole store. What Addendum III left open was narrower than the metric
and is still open: whether the third angle is spent on a colour axis (S3)
or the fit is S2 and colour becomes a legend again. Nothing here answers
that. `G-17`, `G-18`, `G-19`.*

### The second long statement - the collapsed view, offline, the overlay

Sent 23:17, after the streaming pass landed. This is the source of
`G-53`..`G-67`, and until the 19th it had no verbatim record at all.

> Let's return to faster O(delta) diff chunk streaming with semantic
> aggregation while I live-navigate the browser manually and see streaming
> updates to the graph layout per diff-based updates to the overall full-
> structure chunks from our embedding methods... Actually there; perhaps
> we develop on this part next; integrating live aggregation and refining
> our O(delta) diff streams to our projector through updates to our db.
> Note also that the current panels that open should be a fallback format
> offline for the regular electron browser in how we display these
> structures. Also unsure of the loading... portion of the current open
> panel and whether or no this is a panel interactions thing or if we can
> somehow instead explore deeper interactive mappings in our patricia trie
> and our electron browser. The thing here is ideally, we could toggle the
> option to save the full webpage as it is presented live in the electron
> browser for offline use. I also don't see any work yet on the in-browser
> retrieval overlay so we could also touch on that next as a way of
> exploring the full vs primitive chunk vectors and how they are
> interacted with. We could apply a retrieval mechanism that goes coarse-
> to-fine on full chunks as they are shown in the graph editor, then
> obtaining within-shadow-DOM retrieval for top-k, efficiently ranking the
> most relevant parts from different shadow DOM pages within our 256 pure-
> text window limit. I'm almost thinking that we keep the current shadow
> DOM chunk node display panels as a latent thing still generated to the
> DB and use it as a billboard panel that opens within the 3D gui when the
> node is clicked (and still draggable etc). Then, alongside in tandem,
> the main electron selenium sensor opens and scrolls to the chunk to be
> the 'panel' based representation. I'm almost tempted to say that we
> infill offline-saved pages with what we have traced when saving the page
> source with our traced chunks (should saved offline page sources not
> provide their full layout), or if internet is disabled, instead opening
> the fully rendered scrollable page reconstructed from the scan trace,
> seeing still the billboarded panel that we currently have as a more
> 'main' panel within obsidian rather than in the UMAP projector. Also,
> the fps on the current editor with so many pages is quite slow. Perhaps
> a collapsed view of just the shadow DOM pages with unfolding expanding
> views over clicks and retrievals could be implemented. It could also
> correspond to showing the fine-grained retrieval results of full chunk
> panels selectively only displaying the chunks live with the most recent
> debounced retrieval query in the electron retrieval overlay. The thing
> about the current panels as well (as you see opened) is that they aren't
> interactive with the original electron page either, so bringing the
> current shadow DOM panels over to the 3D GUI and keeping things wired to
> the original electron browser, while applying *dynamic unfolding* over
> the current patricia trie to show clicks and fine-grained-only retrieval
> results. For unfolding, we'll keep it tracked with how many results have
> been continuously scrolled through on the electron browser overlay. Make
> sure the PRD gets TLC on this. Though, diff O(delta) streaming
> throughout needs a lot more PRD too to see how close to the millisecond
> level we can get from sensor-scanning in the electron browser, dedup-
> vectorize-dedup-aggregate-vectorize, and projections through the async
> batched queue of UMAP transforms.

*`G-53` (draw pages, not chunks) and `G-54` (dynamic unfolding) come from
the FPS sentence; `G-56` from "most recent debounced retrieval query";
`G-57`/`G-58` from the billboard-and-browser-in-tandem passage;
`G-59`..`G-62` from the offline-fallback passage, including the infill
rule for a saved source that does not carry its layout; `G-63`/`G-64` from
coarse-to-fine within the 256 pure-text window; `G-66` from "how close to
the millisecond level"; `G-67` from "the async batched queue of UMAP
transforms". "Make sure the PRD gets TLC on this" appears here for the
second time.*

### Retrieval is scrolled, and clicking scopes it

> I'll also mention that continuous scrolling over ranked retrieval is
> more appropriate than top-k, but top-k in click expansions is still
> useful. Perhaps clicking is always linked with the query in the current
> electron browser that was last interacted with and in-view. So, despite
> global ranks, clicking a full shadow DOM node would be scoped to the
> shadow DOM url, and then when the node is right-clicked, the scope to
> global re-applies, and we have the scoping retrieval results also follow
> the exact same mechanics of unfolding in the overlay. When I say
> "unfolding" it's more of an unraveling over the chunk's singular
> patricia trie path.

*`G-69`, `G-70`, `G-71`, and the sharpening of `G-54`. The last sentence is
the whole cost argument, and the reason `unfold` walks a path rather than
a subtree: a path is O(depth), a subtree is O(everything beneath it).*

### The order taken after that

> Let's do the collapsed page view and unfolding

> Let's do the retrieval overlay next

> Wire the projector click to scope, then G-55 and G-56

*`G-53`..`G-56`, then `G-63`, then `G-70` before `G-55`/`G-56`. Recorded
because the ORDER was chosen by the user each time, not by the numbering.*

### A defect report with no detail, and why it is kept

> Seeing a lot of degradation in the GUI that wasn't there before. Please
> see for yourself

*Four regressions, every one mine, all introduced by the collapse to pages:
the caption said "96 chunks" over 96 pages, every page drew at one size,
the billboards were gone, and the overlay previews had become raw
markdown. Kept verbatim because a report this general is the signal that a
surface stopped being looked at, which is information the four individual
fixes do not carry.*

---

### Addendum IV's own occasion

The prompt that caused this file to be written. It is about method rather than
the product, and it binds how the work is shown:

> How should we work from our current design state with what we have in
> our application in a way that I can see what improvements and updates
> are being made, and in a way that you can also do just the same as you
> build in the remaining design items, of which there are quite many from
> my own prompt history from previous and current conversations. We should
> likely organize all the remaining items and requirements and open
> questions for both your own ability to see and effect change and for my
> ability to confirm on my side, as well as for the open design items per
> the interpretations of my original prompts, and very carefully so tested
> against what is currently recorded as design features. Please account
> for the totality of the contexts in which updates to design items are
> made and persist throughout.

*"tested against what is currently recorded as design features" is the
operative clause, and it cannot be met while the record stops six days
short. It produced `build_sweep/design_state.py` (a computed status
column, because the maintained one drifted sixteen rows in a week), the
`Confirm` state for work measured but not yet seen by a person, and this
addendum.*

---

## Addendum V, 2026-09-22/23 - one streaming projector, and the pipeline wired into the plugin

> I also suspect an improvement to this dual based approach would be best.
> Instead, stream O(delta) diff chunk updates in queue based batches to a
> fitted UMAP projector that incrementally re-fits for every 2x growth in the
> number of total chunks (as their aggregate 512 token form from their
> components), which resides downstream directly from the similar
> vectorization and electron browser navigation panel that runs recursive
> shadow DOM mutationobserver chunk extraction on the *fullest* possible set
> of content detection dictionaries that can be collected throughout our
> current code space and possibly some improvements from the diff as well.

> A small black box on the bottom right corner that, when hovered, shows the
> actual live processing that the real scanning pipeline is actually running
> in the real app on the actual electron browser with meaningful feedback on
> hovering chunks, streams to the projector, and most importantly, the thing
> about our force-directed layout: all chunks, as in the 256 context window
> limited ones, are embedded and sent to the projector for transforms with
> intermittent refits.

> I don't think the plugin yet surfaces the full pipeline throughout,
> including the way our 3D graph layout is now computed.

> What I mean is, the pipeline is disconnected in what it computes from what
> it is supposed to supply to our various panels. I'm not talking about
> measurement harnesses anymore. I'm talking about the actual features of the
> plugin itself not being up to date with the current pipeline you have built
> with measurements for. I don't see any of the updates happening in the
> pipeline if its processing is the original code that is wired into our
> plugin, which was the original intent of the ask.

*What this changes, read against Addenda I-IV. "Instead" replaces the
dual approach -- a page-level UMAP with a separate per-page layout for each
unfolding -- with ONE fitted projector over chunks, the aggregate (merge
group) vector standing for its 256-token members as Addendum IV's "the
projector shows the aggregated vectors" already said. Positions in every
panel come from that projector: the default page view, an unfolding, a live
capture. The last two quotes are the acceptance test: a pipeline that is
measured but does not decide what the panels draw has not been built.*

---

## Addendum VI, 2026-09-26 - verification inside the app, and one place for each form of a chunk

> The two confirmation passes are still running in the background. But since
> these are running without Obsidian open, my suspicion is that there's a
> hidden opportunity to bring all the tests/sweeps/etc you've been running in
> some terminals _*into obsidian*_ as a *plugin-facing component for all
> test/script layers for fully-observable verification in the actual app
> itself via various MCP tools and layers. I'd also like you to remove the
> segregated statistics panels on scans etc. It's not that the feature itself
> is undesired, because if you can see it and I can see it, it's importnant.
> However, it shouldn't start taking up a non-negotiable space that is
> separate from the rest of the plugin's GUI features. If the statistics are
> for the scanning pipeline, it then becomes a simple open/closed scrollable
> readout that can be collapsed to a small black box on the bottom right
> corner as an overlay *within* the electron browser that the MCP tools will
> always see (and be able to select expand and collapse to show the human),
> but the way the statistics and scan readouts are presented. Also, I'm seeing
> a separate panel with the old shadow DOM/markdown panels of the chunks,
> which I want to keep as a concept, but here's what I want changed about the
> way these two forms of the chunk are presented: the shadow DOM form of the
> rendered chunk should be show as a billboarded 2D panel within the 3D gui
> rather than a third panel in the overall UI. The markdown form should be
> ported over to the right-click second view on the electron browser. This
> separation of concerns enables full-span chunk persistence, both to
> presentable 3D gui and in markdown form on the right-click. Plus, you have
> skipped a *lot* of the details I originally specified in previous prompts on
> chunk highlighting when hovered on the electron browser as another overlay
> that matches the cartesian coordinates of what's rendered in the actual
> browser, where right clicks persist the chunk that is then
> overlay-highlighted and sends the markdown render to the markdown-side
> panel. When this happens, the shadow DOM billboard is also opened and
> persists with what is put in the markdown-side of the electron browser. So,
> whatever is on the markdown panel is also opened as a shadow DOM billboard
> in the 3D graph GUI, where we can see the web content associated with any
> chunk nodes represented by only one of their image billboards which expands
> to viewing the total chunk as a billboard. Remember, please, to keep this
> interlaced with the rest of the tests for our full-scan O(delta) diff
> streaming in millisecond-time profiles as per the traces throughout our
> electron and our 3D graph editor. And make sure that all of these tests and
> scripts have a full Obsidian MCP layer that runs all tests through the
> *actual* plugin itself while live in the Obsidian GUI. So, very much like
> hardware in the loop testing.

*What this changes, read against Addenda I-V. Three things. (1) Every check
runs THROUGH the running plugin -- hardware in the loop -- and is driven and
read by MCP tools; a check that runs in a terminal against a closed app has
verified nothing a reader sees. (2) Statistics get no pane of their own: the
scanning pipeline's readout is the collapsible box in the Electron browser's
bottom-right corner, which the MCP tools can see and expand or collapse.
(3) A chunk has two forms and each has one home: its rendered shadow-DOM form
is a billboard in the 3D graph, its markdown form is the browser's
right-click second view -- and they are one selection: hover outlines the
chunk at its on-screen coordinates, right-click pins that outline, sends the
markdown to the markdown side, and opens the billboard, which stays open as
long as the markdown does. A chunk node shows one of its pictures and expands
to the whole chunk. The separate chunk pane goes.*

Follow-up the same day: *"Make sure you also got all my previous prompts on
the same highlight-on-hover mentions/features."* (Collected into `G-78`..`G-80`
with their sources: Addendum I's overlay "overtop of the page's native
cartesian displays", Addendum IV's "minimal highlight ... without banners"
and "switchable second view", 2026-09-22's "clear highlight (non-blinding)"
and "recursively chunked first".)

---

## Addendum VII, 2026-09-26 - UMAP over page centroids only; the patricia TREE, opened whole

> Also, when time, when you go to make a final report back, please do also
> tell me about what processing is happening on embedding/UMAP side, and
> whether or not we still have force-directed patricia tries on our
> subchunks, which are the 512-token limit form of the aggregate 256-limit
> original subchunks, which are what are used in the actual retrieval itself.
> Please verify the context window limiting and sanctioning of subchunks vs
> chunks to their respective UIs; the retrieval panel(s) and the 3D graph.
> Also, please inform me on what the requirements say about what
> tokens/content are included in token counting on window thresholding for
> both 512 and 256 token limit chunks. So; what is counted and what is not
> for both... Are they the same or different in the requirements? How about
> in the code?
>
> A fork in the road on the best rendering pipeline appears in the case of
> investigations on the first point (UMAP/trie rendering in the 3D graph). If
> we are UMAPing the entire set of 512-chunk embeddings from averages on their
> subchunk embeddings, if we are UMAPing efficient averages of sub-chunks for
> a scanned page, and if millisecond time constraints bar umapping over the
> full set of chunks vs UMAPing only the global subchunk centroids for each
> scanned url path (upper half of the patricia trie's code partitions). In the
> case where we are UMAPing all chunks to 3D, we will move instead to only on
> the global centroids for each page. When I say global centroid, this is of
> our triple-retrieval mechansim; pagerank, frequency, quantized transformer
> embeddings. Perhaps, depending on what vectors are sent to UMAP, we could
> compute centroids on the triple retrieval mechanism where pagerank weights
> concatenated centroids over the semantic and frequency embeddings, since
> these are computed anyways for our 256-retrieval mechanism. I'm also unsure
> of whether or not our Hit@1 measurements used triple mechanism or just
> quantized. Depending, though, on millisecond time profiles, it may be more
> efficient just to compute the quantized embeddings and use those for
> retrieval, which also enables more efficient averaging, so we may go with
> that instead. Anyways, UMAP is only applied to the averages over pages, and
> then clicking one page I think (rather than recursively open at each level
> for each click) we should expand out the full patricia trie at the same time
> for one shadow DOM. Left-clicks on nodes expand, right clicks contract them
> back to their central UMAP nodes vs force-directed chunks. One thing I will
> note is that this means you can scrub all the complexities on the per-fold
> opening/closing logic and keep opening and closing force-directed layouts
> *that* simple. We are also seeing persistent errors with force-directed
> where, I think, the current patricia trie is not actually a 'tree'
> structure that allows for efficient use of space and repulsion forces,
> because nodes are connected to multiple ancestors perhaps or something that
> means they are over-constrained and cannot properly fan out as a real tree
> structure clearly would in the GUI. Instead, we have these triangular
> lattice structures because I think, depending on how you're interpreting
> the structure of the trie vs the tree of the shadow DOM, the trie might be
> designed for fast retrieval with a higher perplexity on path nodes that
> indexes every intermediate node and their leaves to their closest common
> ancestors, which is what deviates the trie structure from the original
> shadow DOM tree structure. I think there was mention originally that the
> "patricia tree" part and the "trie" got combined, but info on "tree" vs
> "trie" got a little muttled that we can visit now. In our case, we're
> actually interested (for our 3D graph GUI) in the patricia tree because we
> can see the tree-like structure that disregards intermediate path lengths to
> ultimately root and leaf nodes. So, the patricia component is a way of
> saying that the tree structure we're concerned with is actually the subtree
> of all the content nodes detected in the full shadow DOM tree. That means
> our graph GUI representation shows these intermediate path nodes, if they
> go from one root to one leaf, as a single link rather than a collection of
> links between the actual full set of path nodes. I think, also, regardless
> of the perplexity/density of trie vs tree connections between shadow DOM
> nodes, the upper limit on max link length in force-directed layouts is
> still wayyyyy too low. The max link lengths need to be much longer.

*What this changes, read against Addenda V-VI. It supersedes Addendum V's
chunk-level fit for the 3D graph: UMAP runs over one centroid per PAGE only
(the triple mechanism's centroid -- pagerank weighting concatenated semantic
and frequency centroids -- or the quantized embedding alone, whichever the
millisecond profiles favour). A page opens, on one left-click, into its
WHOLE patricia tree at once -- the subtree of the page's content nodes in the
shadow DOM, with every single-child chain of intermediate elements collapsed
to one link -- laid out force-directed around the page's UMAP node; a
right-click closes it back to that node. Per-step unravelling (`G-54`) and
its territory logic go. The drawn structure must be a TREE (one parent per
node), and its links far longer than today. It also asks four questions to be
answered from the documents and the code: what the embedding/UMAP side does
now; whether subchunk trees are force-directed; how the 256 retrieval unit
and the 512 display unit are each confined to their UI; and what the
requirements and the code each count as tokens for the two windows.*

Follow-up the same day, after using the pinned overlays:

> Overlay rendering works, but is super super slow and inaccurate, and I'm
> wondering if that's because we're not async on the stages of processing in
> our scanning pipeline, where our chunking algorithms would be blocked by
> downstream vectorization before we see the actual chunk-based overlays. I'm
> also worried about the actual chunk mechanics on the context windows
> because I'm hovering over a heading and a paragraph and seeing two
> different chunks, but I'm sure that this should be one chunk. The hovers
> need a 1 second or longer latency currently to show their overlay, the
> overlays are in the correct position and update somewhat but are extremely
> slow in doing this which is concerning. I actually like the direct side-by
> side sub-panel on the electron so this might actually replace its
> duplicitous hidden second-view panel that was our original, but we will now
> favor a more direct side-by-side with electron browser as still the main
> focus and the right-clicked chunks still as the side-panels. I hope you've
> entered this and the most previous prompt into our verbatim on this as
> well. Once there, re-assess the landscape of the features from a
> bird's-eye-view and propagate the necessary updates and changes downwards
> to the details as necessary. Make sure you consider all factors and
> connections between these features when going to design new code, so that
> you're not making a whole bunch of filament-like single-shim changes in
> place of more fully informed designs from the full totality of the context
> of these new verbatim requirements.

*What this adds. The overlay is the scanning pipeline's fastest output and
must not wait on anything downstream of chunking -- vectorisation above all.
A heading and the paragraph it heads are one chunk to a reader, and the
overlay must show the unit a reader means. The side-by-side markdown panel
REPLACES the switchable second view (Addendum IV's "switchable second view"
is superseded): the Electron browser stays the main surface and pinned
chunks are side panels. And the method is binding: design from the whole of
Addenda V-VII before code -- see `docs/DESIGN_VII.md`.*

Decisions the same day, on the two choices `DESIGN_VII.md` left open:

> On the choices you cited for just your most recent response only; text
> only and link free are the same, and make hover-pin the 256 limit. Of
> course, this is within a margin of error depending on the percentage
> increase from the limit to the very next chunk merge. If this is closer to
> 512 than 256 in the merge after the context limit, keep the previous,
> otherwise include the merge as the final chunk. This should be pretty
> lenient to edge cases where we include headings as well.

*Read as: (1) "text-only" (512) and "link-free" (256) are ONE counting rule.
(2) Hover and pin outline the 256 chunk, not the 512 group. (3) The 256 cut
is lenient: when the next merge would take a run past 256, the run takes it
anyway if the result is still nearer 256 than 512 (under 384), and stops
before it otherwise -- which is what keeps a heading with the paragraph it
heads.*

Later the same day, mid-loop:

> While working in the loop, i would almost suggest also making sure to tear
> down the current db so that all new tests run in a fresh and empty db

*Read as: no check scores the long-lived working store. Each test run starts
from an empty store that the plugin fills by browsing, so everything a check
reads was written by the code under test. Built as
the corner box's "fresh store" button (`Verifier.runFresh` in
`obsidian-plugin/src/verify.ts`) -- run by the app itself, since "All tests
run inside of the GUI"; the working corpus is left alone.*

---


## Addendum VIII, 2026-09-26 - audit the app against the design, by using it

> Before you really get going, please revisit the original design prompts and
> investigate through direct interaction and records how well our features
> are actually behaving, making sure to keep track of the peripheral changes
> in the app as well. Playing around with different interactions in the app
> that the design would imbibe yourself, seeing if the app really lives up to
> the ideals, and then see what kinds of improvements can really be made, and
> how so too while factoring in how the verbatim maps to the harness/mcp/tests/
> plugin interactions and user stories, how db refreshes run with every test
> suite interfacing with real actions in the app itself, etc. I'd suggest
> starting another cron /loop

*What this adds. Before more building: an AUDIT of the running app against
the verbatim, done by using it -- the interactions the design implies,
performed in the app, with their records kept -- including the PERIPHERAL
changes an interaction causes (other panes, the corner box, the graph, the
store), not only the one it targets. Each finding is traced along one chain:
verbatim sentence -> user story -> requirement row -> check / MCP tool / test
-> what the app actually did. And the store behind every test suite is fresh,
filled by real actions in the app (the fresh-store runner above). Findings
and the chain live in `docs/AUDIT_VIII.md`.*

Later the same day:

> make sure to prioritize feature delivery that you yourself can verify over
> MCP versus something like diverging designs away from the main GUI plugin.
> All tests run on the plugin itself.

*Read as: the order of work is FEATURES in the plugin, each verified by the
agent through the MCP tools against the running app -- ahead of design
documents, side harnesses or tooling that live beside the plugin rather than
in it. There is one way to run a test: through the plugin. Any path that runs
a check outside it (a terminal re-implementation, a Python probe standing in
for a check) is removed rather than kept alongside.*

And, minutes later:

> All tests run inside of the GUI and you observe the results within the app
> itself as you build features on the other side

*Read as: the verdict is READ OFF THE APP -- the corner box's check list as
it renders, and the app window itself -- not off a terminal log or a JSON
file written beside it. Building happens on one side (the code), observing on
the other (the running GUI).*

And:

> One important feature add is to ensure that the first handful of scans are
> rendered with a full force-directed layout as a fallback while waiting for
> the first projector fit to complete and for transformed nodes to be
> streamed to the GUI. I think this would in fact do best to show the
> live-scanning abilities truly *as fast as possible* while awaiting the
> projector's fit/transforms and even the embeddings aren't needed for this
> layout, so keeping the force-directed layout and fully expanded and
> updating diffs as they are stream in truly O(delta) milliseconds straight
> from the electron's recursive mutationobserver shadow DOM chunking
> basically prior to vectorization and projection/fitting over UMAP. Add this
> to the requirements doc and please do see it is integrated soon along with
> the rest of the features. Make sure to still, though, touch on all the
> interrelations of this new feature with other requirements, interactions,
> sequences of actions and full set of apparatus state expectations for
> different phases as test contracts that are verifiable ontop the harness
> MCP surfaces themselves (state-space expectation sequence tests within the
> real and actual plugin and Obsidian GUI).

*What this adds. Before the projector has a fit, the graph is NOT empty: the
first scans draw at once as a fully expanded force-directed tree built from
the chunking alone -- no embedding, no UMAP -- and every drain updates it by
its delta, in milliseconds. When the fit and its transforms arrive, the same
nodes move to the projector's positions. The requirement comes with its
contracts: the phases of the apparatus (empty, force fallback, fitting,
projected) and the state each surface must show in each, checked as ordered
sequences in the running plugin through the MCP surfaces. PRD `G-89`.*

And, minutes later:

> One other chea-shot idea is to use force-directed layouts as a first and
> primary representation, but in priority before a UMAP, and for UMAP
> projections, the priority is first on global chunk averaging on per-page
> and then fitting, but a transform over the full chunk set is cheap as well.

*Read as: the force-directed layout is not only a stand-in until the fit --
it is the FIRST and PRIMARY representation, always available, with UMAP after
it in priority. For UMAP the order is: average each page's chunks (the page
centroid, Addendum VII), fit on those; then transform the FULL chunk set
through that fit, which is cheap. Amends `G-89` (force first, not only a
fallback) and `G-83` (page-centroid fit first, all chunks by transform).*

And, refining both:

> Please also make sure the layout priorities are only on the diff that is
> queued to the vectorization and projection itself, where when a projector
> fit has truly completed for the full set of pages with then a projector
> transform pass on the diff updates to chunks themselves, the layouts
> collapse to the main page-node view with the projected chunks collapsed
> once passed through the UMAP projector's transform, and after the UMAP
> projector is re-fit over the full set of page embedding centroids, so
> somewhat asynchronous updates to both fit and transform queues are needed,
> and while we await those, we still expose the full diff set of new chunks
> without vectorization or umap yet as force-directed layouts. So, the
> force-directed first kind of layout is more of a priority immediately when
> scanning, and also intermediately when global averages have already
> obtained a fitted UMAP but then there's another async wait on
> projection/transforms to the queue of new chunk diffs in O(delta)
> themselves that are transformed from the centroid fits.

*Read as: the force-directed layout is not a PHASE that ends at the first
fit; it is how the pending DIFF is drawn. Every chunk a drain produces that
has not yet been through the transform is drawn force-directed, hung from its
page -- before any fit, and equally after one, while new diffs wait in the
vectorization and transform queues. The fit is over the page centroids and
refits asynchronously; transforms run on the chunk diffs, O(delta). When a
chunk's transform lands, its force node COLLAPSES into the page-node view
(the default view draws pages, with projected chunks collapsed into them).
Two queues, both asynchronous -- fit, transform -- and the force layout
covers whatever either has not reached yet. Replaces `G-89`'s C6/C7, which
had the force tree end at the first fit.*

And:

> And please make sure the millisecond time profiles for force-directed
> layouts and fastest-to-3D updates from page scanning the O(delta) diff
> chunks are measured between the electron browser (and its ability to
> highlight the most recently diff-updated chunk set immediately as overlays
> immediately after in-page recursive chunk scanning with the 256 context
> windows) and the 3D GUI itself.

*Read as: two outputs of one drain, timed from the same instant and shown
side by side -- (a) the browser outlining the chunk set that drain just
changed, as an overlay, right after the in-page chunking; (b) those chunks
appearing in the 3D graph as force nodes. Both are O(delta) and neither waits
on the sidecar. PRD `G-90`.*

Correcting the reading above, after seeing it run:

> i'm actually seeing degraded features; updates to the 3D projector have
> completely stalled to only the global pages. What this force-directed-first
> is meant to do is be the temporary and immediate layout prior to the first
> UMAP fit and, while collapsed, if the global node were expanded,
> force-directed would still be there before the UMAP transform on the queue
> of chunk diffs.

> Nodes are *way* too jumbled together. likely another degradation on
> force-directed side

*Read as: (1) the projector's own updates must keep flowing exactly as
before -- chunk nodes from captures and the stream are not withheld. (2) The
force-directed layout is the temporary, immediate layout BEFORE the first fit;
once the fit is drawn, it appears only INSIDE a page node the reader has
expanded, for that page's chunk diffs still waiting on the transform. A
collapsed page shows no force nodes. (3) Force nodes must be laid out as a
tree -- springs to their parent, spacing between them -- never left to pile up
under a projector layout that has those forces switched off.*

> So, like, still several bugs in how I would anticipate the fastest,
> instant, and most visually efficient and clean 3D layout from streaming to
> 3D from our electron scanning.

> The overlay from the recursive chunks is actually a lot slower than I would
> imagine it could theoretically be (overlay is shown, its chunks are
> updates, and the overlap itself is updated all in the single-digit
> millisecond domain, async with downstream vectorization, and immediately
> before piping recursive diffs without a UMAP fit update to the 3D GUI.

*Read as: the diff overlay's budget is SINGLE-DIGIT milliseconds from the
drain -- shown, its chunks updated, its boxes placed -- asynchronous to
vectorization, and done BEFORE the diff is piped to the 3D graph. It measured
p50 53 ms because it made a second round trip into the page for the boxes;
they must come back with the drain itself (read by a geometry step beside the
fold, never inside it -- `invariants.c2`).*

> Also, right-clicking a lot of overlays but still getting "nothing under the
> cursor"

> I think double-right-click with a certain debounce would actually be better
> for pinning. That keeps regular right click interactions for the electron
> browser for options, opening in a new tab, etc.

*Read as: pinning moves to a DOUBLE right-click (two within a short
debounce); a single right-click is the browser's own context menu -- open a
link in a new tab, copy, navigate -- which the cell did not have. (The
"nothing under the cursor" was the event's window coordinates handed to the
page as page coordinates; fixed in `fae7374`.)*

> Also, electron browser navigation (including retrieval overlay, back,
> forward, refresh, url, scan, etc) should be fully tested in your harness
> yourself to fix any and all degradations on features compared to our PRD

*Read as: every control of the browser cell -- the address bar, back,
forward, reload, scan, live, and the search box's retrieval overlay -- is
exercised through the plugin by a live check, the way a reader uses it, and
whatever has degraded against its PRD row is fixed.*

> Seeing degradation on chunk margin thresholds where the following from the
> suffix tree site shows the header, the first four, and the fifth thing as
> three separate chunks, despite being part of the same definition.

(The pasted content: Wikipedia's *Suffix tree* "Definition" -- a heading, a
lead sentence ending "is defined as a tree such that:", and a five-item list
whose items carry inline math.)

> Also, are the colorful nodes chunks, and if so, are they fitted to UMAP at
> all?

*Read as: the chunker splits one definition -- heading, lead, list -- into
three chunks; the lenient cut (decided earlier the same day, `G-86`) must keep
a heading with what it heads and a list with its lead, within the 256
window's leniency. And a question to answer with evidence: what the coloured
nodes are and where their positions come from.*

> Tackle what's open, but first collect the full list because there's still a
> lot of bugs with the real-time streaming layouts because the different diffs
> an 3D nodes and 2D browser highlights can get a little involved, and I see
> some room for improvement on this end as well (including UMAP transforms and
> *when* collapses to page centroid nodes happens for all subchunk/chunk nodes
> already projected from the fitted UMAP transform.

*Read as: before fixing, COLLECT the full list of open defects -- above all in
real-time streaming: how a drain's diff reaches the 3D nodes and the 2D
browser highlights, the UMAP transforms that place chunks, and WHEN chunk and
sub-chunk nodes that the fitted transform has already placed collapse back
into their page's node. Then work through it.*

> Also, on the billboards in the 3D panels on persisted double right click
> selected nodes; there should be a 'minimize' button and the 'x' button
> should just remove it from the 3D GUI, but if the panel is clicked on its
> palette in the 2D browser where the slate of double-right clicked panels
> are collected, the panel re-expands in the 3D viewer.

*Read as: a pinned chunk's billboard gets a MINIMIZE button (collapses to its
title bar); its x removes it from the 3D view ONLY -- the pin, its side-panel
card and its outline stay; clicking the card in the browser's side panel (the
slate of pinned chunks) brings the billboard back, expanded. The side card's
own x still lets go of all three. Amends `G-78` ("closed together").*

---


## Addendum IX, 2026-09-27 - one loop, judged by the eye; the stream's order of events; everything on a page; notebooks next

> Please merge/synthesize the two running loops and re-run them, also
> incorporating our shift in design features without de-focusing on the
> totality of the context of *all* our requirements, **no matter whether or
> not they are reported or measured to be completed or accomplished, there is
> likely hidden detail underlying more requirements that are predicates to
> what is already in our PRD, and each modality of our full app's play loop
> needs to be properly situated with foundational conceptacles that ensure
> stable interactions between each component of our main features. There is
> also likely a forgotten gap on some other panels (like jupyter nodebooks
> with web browsers), but before we get there, we need to focus solely on the
> various successes and abilities to properly assess both with sparing visual
> snapshots and MCP-based measurements that are informed by what information
> in the snapshots is missed by the MCP, and the judgements of this
> information is from the perspective of what a human user would most likely
> say about the visual feedback component of the app, and allow that to
> better inform both MCP design as well as the app's design overall. Make sure
> you get all of this in a new and unified loop cron on 30 minute intervals,
> including the crucial influencing factors I am mentioning here. The human's
> visual evaluation should be what informs our app's design for both features
> and MCP-based interaction testing. This can most likely also be done by chat
> agents as well. However, "what the human would say" is honestly both a
> combination of what the requirements are intended to state as overall
> feature-experience implications, and what the human qualitatively speaking
> from visual feedback and the intended effects and visual distributions of
> our force-directed, UMAP, etc, and most importantly the when and how of each
> of our steps in layout rendering:
>
> * Initial force-directed layout on chunk diffs that are from most current
>   streams from the web browser, and these are preceded by the in-browser
>   shadow DOM recursive chunking algorithms themselves, where first the
>   recursive mutationobserver chunking updates on the 256 token context
>   window first produce the highlight-when-hover panels in the milliseconds
>   (and you must always check for improvements to this end to get as close to
>   near-instant, single-digit millisecond or even microsecond updates from the
>   mutations to the chunk diffs in O(delta) to the overlay), and then these
>   chunk diffs (still following necessary deduplication, though, and all
>   insights learned on the *git* diff of our recursive chunking algorithm
>   content completeness and deduplication efficiency/full content coverage
>   precision and that sort of thing) are then immediately streamed to the 3D
>   gui where they are rendered. These two steps should happen *before* even
>   saving to DB if possible/necessary, where DB saves are after the full
>   pipeline stream in the GUI has completed, and this is also where
>   vectorization would naturally happen as well so the two steps segmented
>   there in the sequence of processing would make the most sense. So, these
>   immediate streams on O(delta) as chunk diffs are updates on the browser
>   side are first rendered with force-directed layouts without an upper bound
>   on link lengths and perhaps more lenient/relaxed attractive forces (rather
>   than strong repulsion). Then, once the chunks are streamed to the DB and
>   queued for vectorization, umap fits, and chunk projection, that is where
>   the later priorities of 3D rendering schemes come into play. The
>   processing on UMAP can actually be simplified even more so than our
>   requirements already have stated. We can simply vectorize the chunk diffs
>   (ensuring deduplication on DB-side as well, including vectorization steps,
>   perhaps some tests for this, and new tests once the old ones pass to
>   double-check for new edge cases) and immediately compute the subchunk
>   centroid and project it over the currently fitted UMAP (or fit for the
>   first time once reached an appropriate number of scanned pages has been
>   reached for a UMAP fit). As soon as the diffs are confirmed saved to the
>   DB, but before they are vectorized and UMAP fit, the force-directed layout
>   persists, but *those specific nodes that have been confirmed saved to db
>   are then collapsed to their root url nodes, even if their roots haven't
>   even been projected or fitted to yet*, and the root nodes are simple
>   force-directed as well until projected and streamed back to the frontend
>   3D layout. However, note that force-directed subchunks are replaced with
>   UMAP projections (with some force direction afterwards for simple things
>   like collision boundaries defined as the diameter multiplied by some
>   safety factor for space between real nodes by some extra invisible barrier
>   length that I would argue is integer-valued in its safety factors). So, as
>   soon as the db pings back that the one node in the diff from any set of
>   the streams has been saved, that one node collapses (still force-directed
>   only until umap projections return) to its root. When the roots are
>   clicked, all nodes expand and show a complete tree structure on the
>   patricia trie. When the roots that are uncollapsed are clicked again, all
>   the chunks for that page collapse back. UMAP coordinates for projected
>   chunks are saved to DB, but not their force-directed updates. All
>   coordinates in the DB for all 512-chunks are re-projected over the UMAP
>   upon a new re-fit on an updated set of the full web history of urls/pages.
>   Chunk colouring is also a component of UMAP fits, note that, but also
>   force-directed layouts initialize to simple translucent nodes to signify
>   chunks that are part of a stream through the diff and that are more
>   temporary signals that this is the streaming happening at the current
>   time while scanning is happening.
> * Please make sure *all content that could possibly be detected, whether it
>   be text; json; images; videos; media; and so on are being detected* and I
>   would again suggest intelligent and planned searches over the git diff for
>   these things as well. While this is happening, you will also have to
>   confirm that all images are actually presented in the 3D GUI, and that
>   re-fetches aren't required by locally saving the media in a workspace
>   cache somewhere along with its original web data.
> * Please test on more difficult and larger-scale pages like archive,
>   youtube, instagram, amazon, facebook, netflix, imdb, duckduckgo,
>   richardmille (which has difficult-to-spot rotating panels with JSON),
>   bandcamp (a live-events updates on the set of albums just released,
>   challening adapting subchunks and updating over full diffs over time) etc
> * Snapshot only important intermediate steps, see what the measurements
>   miss from the requirements, fix up the measurements and then the app that
>   that order, make this part of the new synthesized loop
> * shadow DOM panels in the 3D gui for opened 512 chunk nodes aren't
>   necessarily 'interactive on their xpaths' and so the buttons are just
>   stale. I think *some* amount of html-based rendering improvements on these
>   chunk panels in the 3D viewer are also in order.
> * We should also go over some more of the older design documents and more
>   previous requirements on designs for jupyter kernels with terminals and
>   web browser cells as well, now that our browser panel is basically all
>   set. There are quite a few details on these designs that have already been
>   recorded and identified somewhere in our docs. There are also some points
>   in the older docs about bringing in our local set of python packages and
>   structuring them similarly to how we're doing it for our web interface.
>   So, we'd render each python package as a tree-structured UMAP projection
>   on the chunked comments/code docs, and show the full dependencies on
>   variables to modules to directories as well, but within a chunk-localized
>   setting. This is where our parts on notebook kernels get really fun,
>   because one thing that can be crucially linked is this chunk-based map of
>   locally installed python packages and bringing these chunks into code
>   prototypes in jupyter python cells on a notebook. This includes our own
>   codebase for the project. I think some other design docs also discuss
>   heavily on chats with chat models and protocols for how chat inputs and
>   outputs are formatted with our notebook kernels. We can iterate on the
>   chat-side details later, but jupyter notebooks with all our extended
>   features and connections to our `pip list` of python packages as web
>   chunks are our next steps that we can also begin building toward
>   simultaneously with the quality-related components of our web streaming
>   and 3D layout interfaces themselves.
> * All of these updates must be collected into our current PRD.
> * Currently when using the app, I see that the chunk overlay and streaming
>   from the electron scanning completely degrades when navigating to a new
>   page which is suspicious

*Read as, in the order the stream runs (this replaces the order `G-89` and
`G-91` assumed, where a chunk collapsed only once the TRANSFORM had placed
it):*

1. **Mutation -> chunk diff -> overlay**, in the page, O(delta), single-digit
   milliseconds or better; the overlay (hover highlights) is the first thing
   drawn. Always measured, always pushed lower.
2. **Diff -> 3D, before the store.** The deduplicated diff streams straight
   to the graph and is drawn FORCE-DIRECTED: no upper bound on link length,
   relaxed attraction rather than strong repulsion, TRANSLUCENT nodes that say
   "this is streaming now".
3. **Store, then embed.** The capture is written after the GUI has drawn it;
   vectorization follows the write. Deduplication holds on the store side
   too, including the vectors (tests, then new edge-case tests once those
   pass).
4. **Saved -> collapse to the root, per node.** The moment the store confirms
   a node saved, THAT node collapses into its page's root node -- before any
   vector, before any projection, even if the root itself is not projected
   yet. An unprojected root is itself force-directed.
5. **Embedded -> projected.** Each new chunk's vector is projected through
   the current UMAP fit right away (the sub-chunk centroid, projected), or the
   first fit runs once enough pages are scanned. A projection REPLACES the
   force position; a light force pass afterwards only keeps collision
   spacing: diameter x an INTEGER safety factor, plus an invisible margin.
6. **Root click toggles the whole tree**: click a collapsed root, all its
   chunks expand as the complete patricia tree; click again, they collapse.
7. **Persistence**: UMAP coordinates are stored per chunk; force positions
   never are. A re-fit (over the whole page history) re-projects every
   stored 512-chunk. Colour comes from the fit.

*And around that order:*

- **One loop**, 30 minutes, replacing the build loop and the audit loop.
  Each pass is judged the way a person looking at the app would judge it:
  sparing screenshots at the steps that matter, compared against what the
  MCP measured; where the picture shows something the measurement missed,
  the MEASUREMENT is fixed first, then the app. Every requirement is in
  scope, "Done" rows included -- their predicates are where hidden detail
  hides.
- **Everything on a page is detected**: text, JSON, images, video, media.
  Images reach the 3D view, and media is cached in the workspace with its
  source so nothing is fetched twice.
- **Hard pages**: archive.org, YouTube, Instagram, Amazon, Facebook, Netflix,
  IMDb, DuckDuckGo, Richard Mille (rotating panels fed by JSON), Bandcamp
  (a live feed of new releases -- sub-chunks that keep changing).
- **Billboards render HTML**: the opened chunk's panel should look like the
  chunk, and its controls should not pretend to be live when they are not.
- **Notebooks next**, in parallel with the quality work: gather what the old
  design docs already decided about kernels, terminals and browser cells;
  each installed Python package rendered as a tree-shaped projection of its
  chunked comments and docs, with dependencies from variable to module to
  directory; package chunks pulled into Jupyter cells as code prototypes; our
  own codebase included. Chat protocols later.
- **A defect**: navigating to a new page, the overlay and the streaming
  "completely degrade".

> I'd like you to double-check the detail of the new loop task because I
> think it might skimp on plugin-mcp-test alignment where all tests are run
> directly through the app in ways that are observable to the tools and
> yourself

*Read as: the loop must not let a terminal probe, a pytest pass or a number
read from outside stand in for the app. Every test runs IN the app, started by
the app's own control, and its result is something the MCP tools and I can
observe in what the app renders. A probe's finding becomes a live check and an
MCP-visible field before it counts. (The first draft of the loop said "a check
or an MCP field", which allowed exactly that shortcut; rewritten the same
hour.)*

> Also, I'm sure sidecar needs refreshing

> Also, please do find where our full transcript for the conversation is
> stored and make sure to capture *all* details from my prompts that aren't
> superseded by later prompts in the current cron loop

*Read as: every prompt in the transcripts, verbatim, with what became of it
-- live, superseded (by which), one-off, question -- and the loop reads the
live list each pass. Built as `vertiscope/analytics/prompt_ledger.py`, writing
`docs/PROMPT_LEDGER.md` (137 prompts, 2026-09-12 onward; forty-odd were
never transcribed here, among them the observability rules, the DAG and
clumping reports, the billboard fields and the collider factor).*

> Note the panel rendering of the chunk in both GUI locations (3D billboard
> and 2D clipboard) are discontinuous with how the text/html is rendered in
> the original webpage, which is a bug

(With a screenshot: DuckDuckGo's Search Assist answer pinned. The page shows
one sentence -- "A **suffix trie** is a trie data structure ..." -- and both
the billboard and the side card show it as three bullets, "A", "suffix trie",
"is a trie data structure ..."; buttons appear as "( Search Assist )"; the
source favicons show as "//external-content.duckduckgo.com/... could not be
found"; a raw "/?q=suffix+tree&ia=chat" stands in for a control.)

*Read as: a chunk's two panel forms must read like the page -- inline runs
stay one line of text, controls look like controls (or say they are inert),
images load. A DEFECT (`D-36`), and it is `G-102`'s predicate.*

> I repeat, the rendering on our two chunk-level panels does not match how
> they are rendered in the browser

(With a screenshot: DuckDuckGo, a result card pinned. The page draws a
favicon, a site name, a breadcrumb url, a blue title, a bold-led snippet and
three thumbnails. The billboard shows "image", then "https://" as a link
followed by raw `[www.global-traceability.com › en › radix-tree](https://...)`;
the side card shows "( Block this site from all results )" and every
thumbnail as `"//external-content.duckduckgo.com/iu/?u=..." could not be
found`.)

*Read as: patching the distilled reconstruction is not the fix -- a panel
rebuilt from markdown lines cannot look like the page, because it is not the
page's HTML. Both panels render what the BROWSER renders for that chunk: its
own elements, read from the live page when the chunk is pinned (a read, on
demand, like the box peripheral -- nothing written into the page), with the
computed styles that decide how text and pictures look, absolute urls,
scripts and handlers stripped, shown in a sandboxed frame. The distilled
markdown stays available beside it; the stored distilled form is the offline
fallback.*

> Also, chunk streaming is heavily degraded currently (interacting with the
> page and loading new diffs does not meet the millisecond chunk overlay
> requirement at all, and overlays for completely new diff updates are
> completely broken and have not been observed for several minutes)

*Read as: a defect in the running app (`D-37`). Measured the same hour, on a
DuckDuckGo query the store had never seen, "More results" clicked: the
overlay was painted 4-9 ms after each drain, but most of a new drain lands
OFF SCREEN (17 of 33, 13 of 17), and the outline was a 1.2 s flash -- gone
before the reader scrolls to the new results, and never drawn again. So the
new diff is, to the reader, never outlined. The outline has to last the way
the 3D node does: a streaming chunk stays outlined, following the page as it
scrolls, until the store confirms it saved (Addendum IX step 4), and for a
minimum time once it is on screen.*

> the 3D layout is still too jumbled after collapse. I'm also not seeing as
> comprehensive and real web a test suite over the URLs as I had requested

*Read as: two gaps. (1) After the streaming nodes collapse, the picture that
remains -- projected page and chunk nodes -- is still jumbled: `G-93` measured
only the streaming layout, and nothing measures the collapsed one as a reader
sees it (on screen, in drawn sizes). Addendum IX's collision rule applies
there: diameter x an INTEGER safety factor plus an invisible margin, which
replaces the quarter-radius factor of `G-21`. (2) The live suite browses
fixtures and a handful of Wikipedia pages; the hard pages named in Addendum
IX (archive.org, YouTube, Instagram, Amazon, Facebook, Netflix, IMDb,
DuckDuckGo, Richard Mille, Bandcamp) must be browsed IN THE APP and scored
there, each page, each requirement the stream carries.*

> make the page-centroid UMAP the default projector

*Read as: `G-83` becomes the default. The fit is over one centroid per page
(Addendum VII; Addendum IX: "fit for the first time once reached an
appropriate number of scanned pages"), and -- because Addendum IX still gives
every chunk UMAP coordinates, stored and re-projected on every refit -- each
chunk's vector is transformed through that same page fit. So the centroid is
the SEMANTIC one (the chunks' own space); the triple centroid is not in the
space a chunk vector can be transformed from.*

> UMAP should be able to fit_transform and do simple transforms given the
> pre-fit, no? Perhaps search the web too

> If there's a way to incrementally re-train online for new embeddings, that
> might work. The suggestion there would be to train on just the diff updates
> and assume previous fits are fixed. Also, training on subchunks happens only
> after they are first projected through the previously fitted transform,
> before the re-fit with the new diffs. There is likely a way UMAP supports
> previous parameter persistence while also enabling for new fits on new
> batches.

> Also, whichever of your finds supports our local cuda runtime, that should
> also be included in online updates

*Read as: the projector learns ONLINE. A new diff is first placed through the
fit that exists (transform), and only then trained on, with what was fitted
before held fixed and the model's parameters carried forward; the training
runs on the local CUDA runtime where the method supports it.*

*What was measured before building (2026-09-27, real corpus):*

- *umap-learn 0.5.9 `transform` of the training points returns
  `embedding_` exactly, so fit and transform do agree on fitted points.*
- *Chunk transforms through a PAGE fit land nearest their own page only
  19-23% of the time: individual chunks mean something nearer other pages.
  So chunks are drawn in their page's neighbourhood (UMAP direction kept,
  scaled) and their true coordinates stored.*
- *`UMAP.update` exists (undocumented on the API page): it appends the new
  points and re-optimises ALL of them from the previous embedding. On 100
  pages + 26 new: a common shift of 5.1, then old pages move a median 37%
  of the page spacing (p90 137%) -- far less than a fresh fit (95% / 294%
  after the best rotation), but previous positions are not held fixed.*
- *Local GPU: RTX 4070 Laptop, 8 GB; PyTorch 2.6 + CUDA 12.4 and CuPy
  present; RAPIDS cuML absent (not native on Windows); TensorFlow absent, so
  umap-learn's ParametricUMAP cannot run. The method that does what is asked
  -- network weights persisted, trained on the new batch with a landmark loss
  holding previous embeddings fixed (umap-learn's own "landmarked parametric
  UMAP" recipe), and transform = the network, identical for fitted and new
  points -- is a parametric UMAP in PyTorch, on CUDA.*

> Nothing showing in the obsidian browser. It's currently a blank screen

> Current 3D layout seems scattered and like the nodes may not be pages/url
> nodes and show leakage

> Not much of our scanning layout is good, a lot of it is way too far from
> the original set of nodes, even though there is "sufficient" spacing apart

> Also, I don't think "refit" is applying the cuda form, and I don't know if
> incremental updates on the CUDA form are actually there yet. Depending on
> fit times, it might be a lot faster on CUDA than CPU, and we should be
> seeing much faster layout streaming updates from using CUDA

*Read as: (1) the Obsidian window had hung (the renderer answered nothing,
not even the debugger) and the browser cell showed nothing -- recovered by a
browser-side reload; the cell now reopens its last page and the harness can
recover a hung window itself. (2) Page nodes must read as pages, and nothing
that is not a reader's page may be in the picture: two of the store's pages
were MY probes' DuckDuckGo queries (purged). (3) Nodes drawn while scanning
must stay near the nodes they belong to -- spacing is not the measure;
distance from their own page and from the picture is. (4) The refit button,
the online training on diffs, and the streaming updates must all run the
CUDA model, and be visibly faster for it.*

> While cool, the densely packed maybe not tree structures should be less
> interconnected and a simple tree. Second image has a sample panel/card from
> the page. Also, there are way too many nodes without images billboarded when
> they are known to exist. Even missing .icon (micro icons usually seen in the
> browser tab and search results), similar to the 'wikipedia' item but for the
> remainder of url-level nodes and also as many chunks as possible, and just
> show the most relevant image or one of the images in chunks with multiple
> images, perhaps using css-scaled size (so, post-rendered size, since html
> rendering on our card panels as chunks is still not in the state it should
> be... the 3D gui is not reflecting the same structure of panel as in the
> clipboard on the 2D electron browser).

(With two screenshots: an open page -- EUR-Lex, "33 chunks merged" -- drawn as
a dense web of links among large chunk spheres; and a billboard opened from a
node, showing the distilled markdown with fragments "- , by Armon Dadgar",
"- (the creator of", not the page-like panel the side card shows.)

*Read as: (1) an open page is a SIMPLE TREE -- one parent per node, no web of
cross links. (2) Every url-level node shows its site's icon (favicon, as in
the tab and search results) and every chunk that has a picture shows one --
the most relevant, chosen by its RENDERED size in the page. (3) The 3D
billboard shows the chunk the way the 2D side card does (the page's own
rendering), not the distilled lines.*

> Total scan feature loss seen at
> https://duckduckgo.com/?q=radix+trie+planted962&ia=web

> Significant chunk highlight-when-hovered lag after extensive scrolling on
> https://discourse.julialang.org/latest. The millisecond bound is not
> followed for overlay highlights in the electron browser on chunks, and
> neither with 3D force-directed chunk node diff rendering. Not that the
> feature is nonexistent or doesn't work for a first couple seconds, but
> there's some false reason for the lag because it should be simple enough to
> continuously stream diffs from the mutationobservers to the electron overlay
> to the 3D gui without having to wait for database write queues. Perhaps
> there's an LRU cache overload going on because the queue's max length has to
> be extended, or otherwise ensure asynchronous streaming of the force-directed
> chunks is unblocked by downstream processes, which is the main intention
> anyways.

*Read as: (1) a page left open across a store switch lost its scanning (fixed:
the run returns the cell to the reader's page, freshly loaded). (2) The
millisecond bound must hold for as long as a reader scrolls, not only for the
first seconds: overlay and force-directed 3D diffs stream from the observers
and never wait on the store; whatever grows with a long session (a queue, a
cache, a per-drain scan) is the defect.*

> Tests aren't validating on the original websites

*Read as: a defect is confirmed fixed on the website it was SEEN on, not on a
fixture built to resemble it. The lag was reported on discourse's /latest and
the scan loss on a DuckDuckGo results page; a check that passes on
`busy_feed.html` or `result_cards.html` says the mechanism works, not that the
reader's page does. Every check whose defect came from a named site runs on
that site, judged by an observer independent of the code under test, with its
planted arm on the same site. A fixture may stay as a secondary, controlled
arm, never as the one that is judged.*

> Tests aren't validating on the original websites, the measurement was from
> the julia forums I think

> Also, force-directed layouts have incorrect geometries and constraints

(With a screenshot: the Wikipedia globe as an open page's billboard, its
chunks bunched in clumps along a ring around it rather than spread, some
drawn on top of the globe, straight edges from two "+" nodes above and below
fanning to many chunks, and a bundle of edges converging on an undrawn point
beneath the page; a few chunks far outside the ring.)

*Read as: (1) the lag was measured on discourse.julialang.org/latest, so D-40
is judged THERE. (2) The open page's layout breaks its own constraints: no two
drawn nodes may overlap (the page's billboard included), the disc must spread
its chunks rather than clump them on a ring, an open page is a simple tree (no
edges from other nodes into its chunks, no hub that is not drawn), and nothing
is flung outside its page's room.*

> Layouts still collapsing to something likely non force directed. This is a
> flat circle which surprises me

(With a screenshot: the Wikipedia page open, its favicon at the centre, its
chunks as one even ring of dots around it, math-formula pictures scattered
along the ring, and long straight edges from two hubs near the centre -- one
fanning to most of the ring, including chunks on its far side.)

*Read as: the geometric placement that replaced the sunflower (a radial tree
on the disc, every node pinned to its slot, no collision, no forces) is not
what was asked for. An open page is laid out BY FORCES -- links along the
tree, collision by the integer collider, gentle charge, held in the page's
room -- as the streaming nodes already are; a geometric layout may seed it,
never replace it. And the edges drawn must be the tree that was laid out.*

> Ring layouts still showing instead of force directed

(With a screenshot: the Julia forum's /latest open in the browser cell, and in
the 3D pane its chunks as a dense ring of dots around an empty centre.)

> Don't know why live diff streams in the 3D graph editor keep re-facing the
> growing force-directed form of tree nodes where the structure is always
> facing the camera and adjusting its orientation; this is an unneeded
> addition that needs to be removed without breaking the functionality of
> what is force-directed

*Read as: (1) a flat star (229 rows under one page) must not become a ring --
the forces fill a disc or ball. (2) Nothing in the layout follows the camera:
not the seeding of streamed nodes (laid in the camera's plane) and not an
orbit (the tree turned to face it). The tree is seeded in 3D from its own
structure and directions and laid out by the forces alone; the reader's
camera moves around it.*

> I'm honestly unsure if the UMAP layouts are being followed at all either,
> along with force-directed layouts. The immediate streaming of diffs *does*
> work, but I had detailed quite a few steps for 3D layouts depending on where
> each diff node was in the processing pipeline. I've made a few updates as
> well. Please chase this processing sequence down and fix what discrepancies
> between how the app currently behaves and my described features and
> processing (folding in when the diffed nodes are saved to the DB, changing
> to UMAP coordinates after a re-fit and `update()` style transform
> incrementally over the new nodes. Depending on GPU runtimes, perhaps update
> with the full set of chunks, or just the centroided pages, or the former for
> few pages and the latter for tens to hundreds.

*Read as: every diff node's 3D position follows WHERE IT IS in the pipeline,
and that has to be traced and shown stage by stage, not assumed: drained ->
force-directed (translucent) -> saved to the store -> folded into its page ->
vectorized -> placed by the fit's `update()`-style transform (incremental,
new nodes only) -> moved to fresh UMAP coordinates after a refit. The online
update's scope is chosen by measured GPU cost: every chunk while pages are
few, page centroids once there are tens to hundreds.*

> I'll also raise my suspicions here about deduplication and duplicate nodes
> in the 3D graph view, whether this exists or not.

*Read as: measure it, both ways -- the same chunk drawn twice in the 3D view
(a force node beside the stored node it became; the same content under two
cids; the same cid under two ids), and the same chunk stored or embedded
twice -- and state what exists, with a planted duplicate that the measure
must catch.*

> Idle's never going to finish. Been at it for an hour

> I think your pipeline checks are breaking down now

> Force-directed scans in rapid fire on the julia page are fast and
> responsive, but the force directed layout in 3D is way too chaotic between
> scan updates

> I'm also surprised that the database ingests leave out so many diffed chunks
> for *so long*

*Read as: (1) gate runs on the reader's use of the APP, not the machine. (2)
The streaming tree stays CALM between updates: what is drawn holds still, only
the newcomers settle, and they start where they belong -- no full reheat per
drain. (3) A diff reaches the store in about one capture's time however fast
the page drains: queued drains of one page ride in one capture, and the
backlog is measured.*

> Alrighty. Fresh new computer reboot. Can you please bring everything back up?

> Obsidian's froze up after scrolling over julia panels

> Also might be worth running targeted batches of tests on the
> plugin-in-the-loop with obsidian open for various things and entries in our
> current collection of specs and architecture notes throughout the project
> history. I've also attached a more recent snapshot of the search results and
> I've noticed some hidden deduplication catches that I think may have been
> covered in our original copy of @vertiscope/reference/dom_deep_serializer.py.
> Please do recommend an additional set of focused feature-wise module tests
> that don't trade memory and context size for completeness and coverage.
> Fuller detail and more nested directories are favored on requirement lofting
> and design notes over the current set of designs. This is a formal model of
> the software architecture governed by the most up-to-date smooth integral
> over the full design history. It is separate from the software itself but
> informs the design to track updates on requirements and dependency changes
> for careful localization on feature degradations, for example. We are also
> concerned with filling out the rest of our current software with the
> remainder of the pending requirements and features that have yet to be
> formalized as a proper software model and built in to our current plugin,
> again, tested with plugin-in-the-loop. I've also attached another very
> zoomed in photo of a potential force-directed or interpretation form of
> degradation on the 3D layout. This layout is likely a lot simpler than what
> is being designed over. Make sure to track it, and make sure that it gets
> built properly. Please also ensure that we're using GPU and `update()` based
> batch re-fits on our UMAP models and that these are harnessed into what is
> observable to yourself, so that we can clearly integrate UMAP
> transformations with the remainder of the preceding steps in the main
> scanning pipeline [i.e. vectorization on chunk diff updates, those updates
> coming from the 3D graph editor, the diff on those updates are streamed from
> the recursive chunking algorithm that produces overlays on the electron
> browser, and these highlighted overlays (which need to be in a very much
> lighter and un-tinted color but keeping some tint and borders still, just
> fainter on tint/border but a little bit higher luminosity while keeping
> translucency reasonable), and so on]. Also, we're frozen again after a few
> scrolls on the julia forums. Not sure where in the pipeline it is, but I
> would suggest adding a memory profile along with a time profiler if you
> haven't already. Please ensure that you're centralizing everything to this
> main pipeline that we keep running into (that includes rendering as deeper
> inlaid parts of the processing now, each with different time constraints)
> with the plugin harness that is used for the *full* pipeline.

(With two screenshots. (1) The browser cell's corpus search for
"consultancy" on the Julia forum's /latest: results 1 and 3 are the same
topic row -- "Looking for job or consultancy / Jobs / ufechner7's profile" --
at 77 and 118 tokens, result 2 another grouping around the same row. (2) The
3D pane zoomed on the forum's page: a star of straight edges from one centre
to ~200 chunks, balls and small avatar billboards in a dense ball that
overlaps neighbouring pages' icons.)

> Frozen again

> I'd suggest adding a simple rapid scroll and hover feature while listening
> and watching for this site specifically (time-memory-profile dentistry)

> I'd also like you to include the updates on the 3D graph viewer as well,
> ensure that the diff updates are sent from the browser/electron scanner and
> received on the other end within the same diff update latency and
> proportion in rendering. I think there might be some blockage on the 3D side
> where we stop seeing any updates from the scanner side at all.

*Read as: (1) D-38 is a renderer OUT OF MEMORY (Chromium: "Renderer process
oom") -- profile memory as well as time, in the one pipeline harness, with a
rapid scroll-and-hover stress gesture on the site where it happens. (2) The
store keeps near-duplicates of one topic row under different groupings and
addresses; the reference serializer pruned identical SUBTREES by a Merkle
signature wherever they sat -- recover that. (3) A formal, nested
requirements/design model, separate from the code, integrating the whole
design history, localizing degradations. (4) Focused feature-wise module
tests, cheap in memory and context. (5) The rest of the pending requirements
built, plugin-in-the-loop. (6) The star-shaped layout is a degradation:
tracked and built properly. (7) GPU `update()` batch refits, observable,
joined to the pipeline's earlier stages. (8) Overlays: much lighter,
near-untinted, fainter tint and border, a little brighter, still translucent.
(9) Everything -- rendering included, each stage with its own time bound --
centralized in the full-pipeline harness. (10) Every diff the scanner sends
reaches the 3D view within the same latency, in the same proportion.*

**Ruling, 2026-09-28** (asked: *"What should an open page draw?"* -- the Julia
forum's /latest drew ~1,000 stored topics as 2,467 nodes and 1,476 textures).
The user chose:

> Everything stored

-- the option offered with the note "Keep drawing the page's whole history;
I'd attack the cost with instancing and texture atlases instead." Recorded as
`.design/Q/001.md`.

*Read as: an open page draws every chunk stored for it; the render budget is
met by HOW the scene is drawn (instancing, an atlas), never by drawing less.*

> Try again

> See our current 3D gui. The force-directed methods are still throwing
> glitches. You'll need to improve the fidelity of your MCP tooling harness to
> capture the details of what anomalous and specific behavior I'm describing.
> Get inventive.

*Read as: (1) the harness must SEE motion -- per frame, per node, per force,
per pipeline event -- and at the scale the glitch lives (an open page's
chunks are a 9-pixel dot at the default zoom), exposed as MCP tools; (2) the
glitches it finds in the force-directed view are defects to fix, each with a
planted arm.*

**2026-10-04** -- the user story, from an empty workspace:

> I think one thing about force-directed layouts is there is likely a more
> convenient approach that uses obsidian's original force-directed layout.
> I'm also seeing some concerning behavior in the GUI but I think it's hard
> to pin. Let's first visit the interface from the regular user story. We
> will start with opening up the plugin, sidecar, MCP harnessing for
> yourself, and obsidian. We will begin with a completely empty workspace.
> This refresh component must be built-in for testing vs regular usage. I
> will then navigate myself on a page and we will track each step of the
> pipeline together. I'd like to understand the complete time profile and
> processing results for each step in the pipeline reported here in-chat by
> you as well. One consistent issue I think keeps appearing is that we have
> way too many force-directed nodes that are persisted in the 3D layout when
> new scans come in. Not that the nodes aren't registering correctly when
> message passing between the electron browser and the 3D layout, but when
> the diffs are updated to the 3D gui, I don't know if there is a complete
> set of deduplication/queue processing to vectorization/persistence issues
> etc. If I'm wrong about this and it's just the pace of the scroll/scans
> being at extremely high throughput on diffs, then please do tell me.
> However, I might suggest here that we centralize deduplication etc on
> diffs throughout the pipeline in a centralized place on the backend that
> then can facilitate mappings... Or otherwise, assign some amount of
> object/class design that makes a singular diff update on the scan side
> compatible with the same set of 3D and 2D representations within the same
> object on the scan diff (deduplication should also be checked here, along
> with the remainder of measures/precision/coverage/completeness
> tests/metrics that we track on the electron scan side. I will also
> instruct you, and please remember to do this part especially, is
> double-check and reference our current designs with our previous
> iterations that were geared towards different end-goals. These might
> appear presently in modules but also in the diff. I recommend spawning
> haiku (ideally in simple, concrete, and determinist-friendly tasks
> covering the semantic space of expertise and knowledge we are trying to
> track our findings against with principles) or sonnet agents for the
> parallel tasks as necessary. We ideally can centralize our diff along one
> track of object that interfaces both with the 3D layout forms on patricia
> tries/trees and the forms in our electron browser like overlay, markdown,
> shadow DOM (which is still not yet interactive per the original page in
> its representations, but this needs to also be ensured working for our
> user story). I should also make note that this scanning diff research
> should include content detection methods and approaches; double check on
> the diff at various points for when findings were to negate or confirm
> any of the designs presently in our current scanning approach on the
> electron browser that attempts to completely avoid any detectable
> injection except for required mutationobservers, but with zero contact
> with "the page itself" such that we don't throw off trackers or even break
> pages. We must also ensure that the layout of our panels are concise at
> the deduplication level as well. We must furthermore make an effort to fix
> the current shadow DOM view of the chunk panels since it may be more apt
> to direct HTML representations on the distill chunk patricia samples.
> Interactive components of our shadow DOM views and panels must be linked
> to the patricia trie and also interface directly with the webpage itself
> (i.e. clicking a button or link on the chunk opens the browser to first
> navigate and scroll to the chunk and then take the action on the
> component in-silico that then performs the update action/event on the
> browser). We will also have to improve the layout of the retrieval results
> as well in the electron overlay, since the current layout is somewhat
> inaccessible to fully "see" and understand. We must ensure all images
> found in pages are also present in the 3D layout, but so that we don't
> overlap multiple images for the same URL node. We must also review our
> current UMAP update layout on GPU for the queue diffs, along with our
> current approaches on embedding vectorization. Remember that I think we
> are taking averages of the chunk embeddings. Also, UMAP fit updates I
> don't know/think are persisting to the UI. Depending on update speed, we
> can explore re-fit "updating" on the full set of page chunks at a time;
> balancing local context with global representations. This would be a UMAP
> model applied to *all* scanned chunks from all URLs (noting diff updates
> on chunk mutations; revectorization; and re-mapping), but the re-fit
> update is only on the set of URL chunks. If re-update latency is good, we
> will use this for 3D coordinate streaming that is a simple switch between
> force-directed and UMAP fitted to 3D with the full set of chunks always
> shown unless we apply our right-click gesture to the URL nodes. We have to
> be careful, again though, about dedup and diff updates respecting these
> in a centralized way that interfaces chunks to both 2D and 3D views. We
> must also make sure our patricia trie is shown clearly and also
> *guaranteed to be tree structured*.

*Read as, in order: (1) bring everything up -- Obsidian, plugin, sidecar,
the MCP harness -- on an EMPTY workspace, through a built-in switch between
a test workspace and the reader's own; (2) the user browses; the pipeline is
traced step by step and its time profile and results reported in chat;
(3) say plainly whether the persisting force nodes are a dedup/queue/
vectorize/persist defect or only throughput; (4) one diff object, deduped
once, that every 2D and 3D form reads (overlay, markdown, shadow DOM,
patricia tree, UMAP), with the scan-side metrics checked on it; (5) research
the earlier iterations -- modules and git history -- including content
detection and the zero-contact sensor, with parallel haiku/sonnet agents;
(6) Obsidian's own force-directed graph as a candidate; (7) interactive
shadow-DOM/HTML chunk panels wired to the trie and acting on the live page;
(8) a readable retrieval overlay; (9) every page image in 3D, one per URL
node; (10) UMAP over all chunks with per-URL refit updates, persisted to the
UI, as a switch against force-directed; (11) the patricia trie drawn clearly
and guaranteed a tree.*

**2026-10-06** -- images, and a searchable history:

> Numerous nodes are missing at least one of a full set of images that are
> not currently being detected. Please review our current set of detections
> in our full set of docs. I would almost recommend a simple graph RAG MCP on
> the full git diff that auto-updates recursive chunks on things like logs,
> docstrings, and the like. That would allow you to more formally search over
> the fully available code-space of possible previous information and
> findings that are relevant to the current issues faced or design questions
> to introspect on.

*Read as: (1) nodes lack images the page has -- a chunk or page whose full
set of pictures is not all detected; review every image detection the docs
record, against what pages actually hold; (2) a graph-RAG MCP over the whole
git history (diffs, commit messages, logs, docstrings) whose chunks update
on their own as the history grows, so earlier findings and design decisions
can be searched when a new issue or design question comes up.*

Then, the same evening:

> Also, it might be just the way the images in chunks are, but many images
> for nodes seem duplicative. If dedup is truly working completely and it's
> not a chunk uniqueness issue but instead an image icon thing, then okay.

> Also, please don't diverge to just the diff graph RAG mcp from the current
> task. I would almost recommend a minimal adpater plugin design that does
> vectorization efficiently but queries still directly over the git logs.
> Recommended good references:
>
> https://github.com/jjaakkola/git-diff-mcp-server
> https://github.com/cyanheads/git-mcp-server

*Read as: (3) many nodes show what look like the same images -- decide
whether that is a dedup or chunk-uniqueness defect or only shared icons;
(4) the history tool is secondary to the current task, and MINIMAL: an
adapter that queries git's own logs directly, with efficient vectorization
beside it rather than a second store of the whole history.*

> Overlay and green register overlays for new chunks/diffs are still quite
> laggy. Latency should be single digit millisecond.

*Read as: (5) from a page mutation to its overlay (and the green box that
registers a new chunk or diff) being drawn: single-digit milliseconds.*

> Uh oh! Phantom nodes and weirdness/3d rendering lag on layouts and
> loose/stale 3D artifacts (nodes and links). I also found that the chunks
> seem too closely packed together. If that is a scaling issue then good. If
> that is a UMAP issue then hmm. The lagging chunks initialized into a
> perfect sphere and note really the 'diff' over the patricia trie at all.
> Not a lot of tree structure going on either from my view of things. The
> diff should be sort of like a trickling effect over the emerging diff on
> the active and open tree structure of how the chunks are organized on the
> page. Not sure if this is always being followed for many different
> navigations to different websites. The UMAP fit speed checkts/tests should
> also be obtained from the true in-app latency, and then speed improvements
> should be made there as well. Attached photo is of a clicked panel not
> rendering. This has begun to happen quite a bit now. I would suggests
> getting some good tests in order along with investigating the
> degradation. It was working fine before. Impressive from early
> assessments.

*(The photo: ourworldindata's population grapher in the cell; in the 3D
view a chunk's billboard is open with its header -- url, `markdown`,
`shadow DOM` -- and an empty body.)*

*Read as: (6) phantom nodes, stale nodes and links left behind, and render
lag in the 3D view; (7) chunks packed too closely -- say whether it is the
view's scale or the UMAP; (8) streamed chunks start on a sphere instead of
growing as a diff over the page's open patricia tree -- a trickle down the
tree as it emerges, on every site; (9) UMAP fit speed measured as the IN-APP
latency, then made faster; (10) a clicked panel renders empty, now often --
a REGRESSION: find it, and put tests in place that would have caught it.*

> Also the tracked overlay actually slides off the page's bounds.

*Read as: (11) the overlay that tracks a chunk on the page is drawn outside
the page's visible bounds.*

> Also, the chunking speed might be pretty slow, and I'm wondering also if
> the overlay registers the detections 'immediately'. Again, tests, speed
> profiles, improvements without breaking things, the works.

*Read as: (12) chunking speed profiled and improved; whether the overlay
registers each detection immediately -- tested, profiled, improved without
regressions.*

> I think, also, now, the page/markdown panel views should be simplified a
> little. Perhaps try instead just using obsidian's default markdown renderer
> in this panel view rather than having this switching between markdown and
> 'shadow DOM', since our webpage rendering view is basically the correct
> result. I also think the header of the panel should show the full patricia
> trie address, if at all possible. Also, the panels could be a little bit
> bigger in the markdown panel view, at least resizing centered by the button
> clicked at the top right corner of the panel to get the page and markdown
> sizing unique. Also, the attached image doesn't actually render anything.
> The html-side of the chunk also doesn't update (just shows some blank grey
> mask), even though the second image shows that there is content (that is
> correctly diff-updated I think, just not its page-rendering mirror).

*(Two photos of an allrecipes chunk billboard: in `shadow DOM` a broken
image whose url leaks as caption text from `:max_bytes(150000)` on; in
`markdown` the chunk's lines, image and link lines with full urls.)*

*Read as: (13) the panel has two forms only -- the PAGE (the live page's own
rendering of the chunk) and MARKDOWN drawn by Obsidian's own renderer -- no
markdown/shadow-DOM switch; (14) the panel's header is the chunk's full
patricia-trie address; (15) the markdown form is larger, and switching forms
with the top-right button resizes the panel about its centre, each form with
its own size; (16) the image renders; (17) the page form follows the chunk's
diffs instead of showing a stale grey mask.*

> I should note that this lacking in webpage updates on chunks in their
> panels is even happening for nodes with image billboards being clicked on.

> One other thing that might work good for umap/force directed is voronoi
> repulsion thresholds on link lengths. Difficult but maybe doable.

*Read as: (18) the stale page form also affects nodes drawn as image
billboards; (19) a candidate for both layouts: Voronoi-cell-based repulsion,
with thresholds on link lengths.*

> Clicking on a page node no longer works (might be diff or something
> blocking)

> Surprisingly, archive.org is not being picked up at all. I know for a fact
> this is a nested shadow node issue

> Also, image is attached, not sure if what I'm seeing is tests on the
> artifacts or actual degradations... Looks voronoi

> Jumbled rendering bug spotted in the Wikipedia quadrant, not sure if this
> is a recent patricia trie/tree update or no. I'd like to see the full
> patricia tree rendered. Also, the umap clusters are still quite small, and
> still quite closely packed for each URL. I don't even think we need
> voronoi, but maybe we do, for a max bound distance that telescopes the
> chunk distances from their centroid url node radially within some bounds,
> which still preserves the UMAP geometries.

*(Photos: long straight edges fanning from a few points across the 3D view;
an unfolded Wikipedia page as a dense ball of ~770 chunk nodes with tree
edges crossing everywhere.)*

*Read as: (20) a click on a page node must unfold it; (21) archive.org's
content lives in nested shadow roots and must be read; (22) the full
patricia tree of a page drawn so it can be seen as a tree; (23) each page's
UMAP cluster is too small and too dense: telescope its chunks' distances
from the page node RADIALLY into bounds (a maximum distance), keeping the
UMAP geometry -- directions and the order of distances.*

> Also, still nothing on archive even being detected still, I don't think.
> There aren't any overlays for the chunks and I don't see anything
> registering in the 3D graph editor.

> Also, most images and media are not registering in nodes on
> https://johnwick.movie/film/john-wick-chapter-3-parabellum. There's a lot
> of rich video, audio, and images, but I'm not sure if the chunks are
> making it through here either. This is likely another shadow DOM issue.
> Remember, though, about the boundaries on what is preferable to run as
> script injections, since we are trying to minimize write access to the DOM
> itself whatsoever whilst still managing mutationobservers. If
> mutationobservers means injection, then we do that.

*Read as: (24) every image, video and audio a page holds reaches its chunk
and its node; (25) the boundary on contact: the DOM is read, never written;
MutationObservers are the one accepted injection.*

> Please make sure audio detection is working for this page as well

> And movies/videos and images. There are a lot here and I bet you could
> screenshot the page and then puzzle-piece the images from the chunks with
> our current obsidian plugin with the mcp toolspace you currently have
> until we clearly have fully detected all the possible elements and content
> we're after. Also, please use this and archive.org as pages to test all of
> our current features on. Rendering in the page-original panel form will be
> a challenge for dynamic renders. But we have to ensure feature-completeness,
> so these are good challenges.

*Read as: (26) audio, video and images on johnwick.movie all detected;
(27) a visual coverage instrument: screenshot the page and account for every
visible picture, video and background against the chunks, until nothing is
missing; (28) johnwick.movie and archive.org as the test pages for every
current feature, including the page-original panel form on dynamic renders.*

> I also think over-chunking might be happening somewhat, since overlays are
> quite large and span lots of text. Could be a truly large context window,
> but I forget the maximum threshold size. From what I see, I would guess in
> the 128 to 256 token range, maybe even 512. At least from the on billboard
> I hovered over on the main page. Of johnwick

*Read as: (29) overlays look too large -- say what one outlines and its size
limit, and make the outlined unit the stored chunk's size.*

**2026-10-10** -- prove it in practice, end to end:

> Let's return to our current task. Please bring everything back up and
> continue your work using the app harness and tests etc. Please also check
> whether or not what we're testing is really making it into our code in
> practicality. That means perhaps use the harness to navigate new webpages
> yourself, scrolling, hovering on overlays and pinning the relevant things to
> the clipboard with a right-click, seeing all the nodes populate into the 3D
> graph, get umapped within their url domain node's scope, perhaps also ensure
> that we still run global umapping when there is latent activity in the app
> that doesn't stream new chunk diffs to the 3D graph and database. Please also
> verify rigorously that all content that is eventually streamed into their
> full chunk form is properly and presently displayed in their panel form, and
> that at least one image (if not the unique and identifying image of the
> chunk) is also shown in the 3D graph billboard.

*Read as: (30) a check passing is not the feature working -- drive the real
app on pages new to the store (navigate, scroll, hover the overlays,
right-click pin to the clipboard) and see the result in the GUI; (31) every
streamed chunk reaches the 3D graph and is UMAP-placed inside its own url /
domain node's scope; (32) when the app is idle -- no new chunk diffs reaching
the graph or the store -- the GLOBAL UMAP still refits; (33) every chunk that
finishes streaming shows its FULL content in its panel, present and correct;
(34) a chunk's 3D billboard shows at least one of its images, ideally the one
that identifies it.*

**2026-10-10, continued** -- while the app was in use:

> Flying to chunk nodes in the 3D project while hover on 2D browser overlays
> has degraded in function quickly, but was working for a little bit

> Also, overlay chunk feature degradation spotted on the same site. This
> should be all one chunk, but it is erroneaously split up into subchunks for
> the same card. *(a screenshot of one julialang.org/latest topic row)*

> Not sure why there's this clumping happening, whether it's UMAP or something
> else. If UMAP, ensure that it's a scaled local fit. If it's a global UMAP
> fit, let's ensure the scale of the global map is correct, while keeping the
> URL nodes close enough together to each other with their own zoom-out scale
> map of their global nodes in the 3D projector. If possible, the global map
> would be only on the chunks, with centroids still at the center. Ensure no
> force-direction on attraction to the URL node is ever present, perhaps a
> spherical threshold radius to the root node on chunks should this be the
> case, should force-directed still influence node coordinates post-UMAP.
> *(a screenshot: the forum's chunks packed in a ball on its page node)*

*Read as: (35) hover-to-fly must not depend on a busy store; (36) the overlay
outlines the stored chunk -- one topic row is one card, one outline; (37) say
whether the clump is UMAP or the forces; a local fit is SCALED; a global fit
has the right scale, url nodes near each other, each with its own zoom-out
map; ideally the global map is fitted on CHUNKS, with each url's centroid at
the centre of its chunks; (38) no force ever attracts a chunk to its url node
after UMAP -- at most a spherical radius bound around the root.*

> Also, fly-to-node should zoom initially, but preserve user zoom while still
> tracking during fly-throughs

> Perhaps we also do some kind of debounce on continuous tracking and
> re-setting the zoom action for 'new navigations'

> "Page" button doesn't work. Please also ensure you're writing test for these
> to track the feature space as well, definitively. *(a screenshot: a forum
> row's panel in its markdown form, header `.../tbody/tr[166]`, a "page" button)*

> Also, retrieval breakdown during a scan over a large page. Perhaps a db lock
> .wal issue *(a screenshot: legislation.gov.uk/ukpga/2018/12/contents, query
> "science" everywhere, 1123 in the force tree)*

> Also, zoom persistance with continuous fly-through debounce still doesn't
> register.

> For some reason I'm witnessing a contraction in what seem like UMAPped nodes.
> This is where I think force-directed post-umap is warranted, but done with
> the original residual coordinates as phantom coordinates to keep the nodes
> closer to their original locations while enforcing collision and attraction
> constraints with a radius/diameter safety factor on collision spheres. This
> should not affect click and drag. Also, showing hovered panels in the 3D gui
> when hovered on the 2D browser should persist, but disappear after a minute
> maybe.

> Please also ensure you attend to *all* my recent feedback i've provided on
> this day and time in our transcripts.

*Read as: (39) the first flight of a navigation zooms; later flights keep the
reader's zoom and only re-aim; (40) tracking is debounced, and the zoom reset
fires once per new navigation; (41) the panel's page button works or says why
not, and every one of these behaviours has a test that tracks it; (42) search
keeps answering while a large page is being stored; (43) = (39) seen working
in the app; (44) after UMAP, a force layout keeps each node near its fit
position (the fit as a phantom anchor), with collision spheres at a safety
factor and attraction constraints -- no contraction -- and dragging a node is
unaffected; (45) a panel opened by hovering in the browser stays open after
the hover ends and closes by itself after about a minute (this replaces
"closes when the hovering stops", 2026-10-06); (46) every item from today,
(30)-(45), is attended to.*

> Perhaps we can persist per-URL node fits (i.e., fitting UMAP within the full
> chunk set within a url) and then call global updates more intermittently
> with our umap-cuda package that I think is live. So, we fit umap first to the
> per-url nodes that are newly scanned (also async projections and fits for
> streamed deltas so that we don't wait with grey force-directed while
> hierarchical fits are happening), and perhaps also thinking about how async
> local-global fits can work more generally with projections intermittently
> for scans and diff streams.

*Read as: (47) a LOCAL UMAP per url, fitted over that url's full chunk set and
persisted; the GLOBAL fit updated intermittently on the GPU (umap-cuda);
(48) a newly scanned page is fitted locally first, and streamed deltas are
projected into the local fit asynchronously, so nodes do not sit grey and
force-directed while a hierarchical fit runs; (49) the general shape: local
fits and projections per scan and per diff, a global fit refreshed
intermittently -- designed, not improvised.*

> Weird behavior where I click the markdown button to view the other rendered
> form, I see it momentarily, but then the whole panel disappears, and returns
> to the original *(a screenshot: a Monarch butterfly panel; it was the
> harness's own drive cycling panels while the reader used the app)*

> I should also never see the notification that something that we have already
> chunked and tracked is inaccessible. All the data must be saved and mapped
> fully and comprehensively across representations in our graph database. Even
> media. The full set to render everything normally after scanning, so that even
> when the connection isn't present, we still can render the originally scanned
> chunk before the shadow scripts removed the informations. I'm talking about the
> banner that says I need to scroll to the chunk back into view. I also thought
> that this was done automically when clicked anyways. Perhaps this is another
> feature degradation that should be fixed and tested for. *(a screenshot: a
> johnwick.movie panel reading "Page form unavailable: none of its 6 elements
> are on the page now -- scroll to where it was")*

*Read as: (50) a harness drive never runs over the reader -- it stops the
moment the reader is active; (51) no panel ever says a scanned chunk is
unavailable: its page form, styles and media are SAVED at scan time and mapped
in the graph, so it renders as scanned with the page gone, the connection
down, or the page's own scripts having removed it; (52) clicking a chunk
brings it into view on the page as well; (53) a test holds each of these.*

> Buttons on the page aren't persisted to the HTML chunk, this should be present
> and graceful to degradation since they seem like shadow DOM nodes *(screenshots:
> johnwick.movie's footer -- Shop, Text Updates, Email Updates, LEGAL, FOLLOW)*

> Image aspect ratio rendering is weird on the HTML rendering panel forms of the
> chunk panel billboard views in the 3D browser. This is an open chunk whose
> aspect ratio is correct in markdown view, but not in HTML. *(screenshots: the
> Ballerina hero squeezed, its play button a flat line)*

> Fly to hovered degradation spotted as well when navigated to a new website
> *(screenshots: johnwick.movie's cast grid; a markdown panel of broken
> `assets/img/...` pictures)*

> Force-directed and UMAP fitted node renderins on diff streams problem;
> force-directed is frozen and persists even after UMAP has projected/fitted on
> .update() to umap-cuda. *(a screenshot: a grey star of streamed nodes on a
> hi.wikipedia page beside its coloured placed chunks; a panel reading "(no
> lines stored for this chunk)")*

*Read as: (54) every control and picture of a chunk is in its page form,
degrading gracefully at a panel's width; (55) a picture or drawn shape keeps
its aspect ratio in the page form; (56) hover flies to the stored chunk on
every page, a freshly navigated one included; relative pictures in the
markdown form resolve against the page's base; (57) streamed nodes fold the
moment their chunks are stored and placed -- none stays frozen beside the
fit.*

> I should only see a single most recently hovered and flown to panel persist
> its billboard rendering, not multiple. Again, ensure you are building and
> testing everything in our current transcripts. *(a screenshot: two
> hi.wikipedia hover panels open at once, one reading "(no lines stored for
> this chunk)")*

> The following method of feature degradation on the dual panel representation
> shall be deprecated, with full rendering, completeness, and matching
> guarantees as appropriate for both panel views. *(a screenshot: a
> legislation.gov.uk panel in markdown form with its "page" button struck
> through)*

*Read as: (58) at most ONE hover panel persists -- the most recent; a hover
opens no panel for a chunk with nothing to show; every item of today is
built and tested; (59) no degraded panel state: both forms always render,
complete and matching -- the page form is what the page drew (live or saved)
plus every line it did not draw, or the store's own rendering when nothing
was drawn; the markdown form is every line.*

> Duplicate image found in the HTML render on ko.wikipedia on the higgs boson
> *(a screenshot: the picture shown twice, then `[[ 77 ]](#cite_note-...)` lines)*

> Not sure why this two-form appears here, whether new diff streams make it into
> the projector's queue and re-fits okay *(a screenshot: a grey streamed tree
> beside a coloured placed cloud)*

> Navigated to the archive page. I think streaming update leakage is happening
> during chunking and in the dual panel renderings. I have a feeling also
> fly-to-hovered might have degraded here as well because of blockage in
> graceful update registers to chunk diff streams and leakage between the two
> panels. One, the web-panel, should gracefully update to new streamed diffs
> while the markdown might be quicker to render. The faster render of the
> possibly two dual diffs, along with the per-field chunk degradation on
> overlay, tells me there's discontinuity and leakage somewhere in this
> feature. Since the summary panel is probably within a safe margin of the
> context window limit for chunks, I would suspect this is why the case is
> present here. Again, fixing *and* testing for all of these things.
> *(a screenshot: archive.org's item metadata list)*

*Read as: (60) the complete page form never repeats what the page drew -- a
picture at another size, a footnote mark; (61) every streamed diff reaches the
queue, the fit and the fold, and it is SHOWN that it does; (62) the overlay
and the panels show one unit for a field list that fits the window -- not one
per field -- and the page form follows new streamed diffs gracefully while
the markdown form may draw first; fly-to holds on such pages; every one of
these fixed and tested.*

> Significant render lag on streamed updates and saves to the 3D viewer from the
> browser. Might be a blocking issue with data persistence versus immediate
> diff-based updates and response in the app itself.

> Phantom links and clumping tells me the central URL node collision radius
> boundary was not enforced per a couple prompts ago

> The collision boundary sphere on the central node should be scaled large
> enough such that this overlap isn't an issue. I'd suggest this boundary is a
> healthy third or so from the minimum distance between any other URL nodes
> (same-level distance bounds on attraction). Again, remember that we need the
> original UMAP coordinates to still persist as part of the force-directed
> adjustments *from* the UMAP for these cases over overlaps. This should happen
> for projections, local url node level .updates(), and global .update() calls,
> all on umap-cuda.

> Weird phantom open-links spotted...

> It's an empty nodes problem maybe... Hovering on chunk overlays in the browser
> flies to them

*Read as: (63) diffs appear at once whatever the store is doing -- persistence
never blocks the app's response; (64) the url node's collision sphere is about
a third of the distance to its nearest url node and no chunk enters it; the
post-UMAP adjustment starts FROM the UMAP coordinates, which persist as the
phantom anchors, after every projection, local update and global update;
(65) no link is drawn to a node that is not where its page is; (66) a hover
flight lands on a node the reader can see.*

> Please ensure everything is processing async and as fast as possible
> everywhere that these processes and links apply between our various
> interfaces and intricacies.

*Read as: (67) every stage between the page, the plugin, the sidecar, the store
and the fit runs asynchronously -- none waits on another it does not need --
and each is measured and made as fast as it can be.*

> Overlay panel showing in the 3D GUI is now extremely slow... watch out for
> that in time profiling

> overlays flicker on github

> chunking degradation seen in
> https://culinarypedia.com/2026/05/01/the-best-chicken-dishes-from-diners-drive-ins-anddives/

> open link degradation spotted on current page

> obsidian froze

> no longer frozen. really slow though. id like the same feature set with
> significant speedups

> not bad speedup for so many nodes. maybe we can render images within closest
> distance to the ray normal projection of the mouse proximity at a time for
> efficient details while staying fast

> immediate lag after clicking a node. perhaps force-directed has something to
> do with it

*Read as (2026-10-11): (68) a hover draws ONE outline, once -- never the page's
box first and the stored unit's after it; (69) a section heading opens the
chunk of what it heads and never closes the chunk before it; (70) no drawn
link ends where no node is drawn; (71) the app never freezes, and at tens of
thousands of nodes keeps every feature it has while running markedly faster --
no per-frame or per-tick work over nodes that cannot change; (72) pictures
are drawn for the nodes nearest the pointer's ray -- the shortest distance
from the node to the ray cast through the mouse -- a bounded set at a time,
spheres elsewhere; (73) clicking a node responds at once: the force layout
does not re-run over the whole graph for one click.*

> force sphere does the opposite of what its intent is... linked nodes are
> within the sphere because the boundary is too high maybe, or doesn't apply to
> the linked chunks of the actual url node

> hover images also only apply for chunk view. not url view.

> chunking degradation and invisible panels spotted in the chunk node view.
> image hovers and speed are back to normal. thank you!

> re-right clicking doesn't open chunks back up in chunk view

> force fields still broken

> i dont think the chunk view needs force-directed, might also slow things
> down and we can rely on UMAP only for this view

*Read as (2026-10-11): (74) the url node's sphere is a third of the distance to
its nearest url node as the nodes are DRAWN, and none of its own chunks is
inside it; (75) the pointer-ray picture limit is for chunk view -- url nodes
always draw their pictures; (76) a page's hover map and panels are there
whenever its page is; (77) a second right-click on a folded url node opens it;
(78) chunk view runs no force simulation: every node sits at its UMAP
coordinates.*

> Remove the repulsion sphere entirely please

> Giant clumping problem

*(The second sent with a screenshot of the url view: one cloud of very large,
overlapping chunk spheres around a url node, beside two clouds of small ones.)*

*Read as (2026-10-11): (79) item (74) is withdrawn -- there is no exclusion
sphere around a url node; its chunks keep clear of its DRAWN body only, as any
two nodes keep clear of each other; (80) a page's chunks are not drawn as a
clump of large overlapping spheres: no two chunks of a page overlap as drawn.*

> Repulsion sphere is still there... You can see the ring. Please ensure that
> the ring feature is removed and we just have regular functionality

*(Sent with a screenshot of the url view: an arc of url nodes across the top,
and an open page's chunks around their url node.)*

> Double check the repulsion sphere is gone. I think it is now.

> why are nodes different sizes in the chunk view? I'd like consistent node
> sizes if possible

> if its an image size thing then okay, no worries

> Try again

*Read as (2026-10-11): (81) no ring -- nothing is pushed onto a shell around an
open url node. The sphere is gone from the loaded code (checked live). The
other thing that can draw a ring is the room pass (D-49), which moves CLOSED url
nodes out to twice an open page's bound; whether it is "the ring feature" was
asked and is not answered, so it stands until the reader rules. (82) chunk view
draws its nodes at one size "if possible". Measured: the variation is mostly
NOT image size -- the spacing pass shrinks 96.5% of nodes, by their nearest
neighbour; pictures are 1.24x; copies up to 1.41x. One size costs overlap in
the densest clusters; asked, not answered. "Try again" re-ran the checks the
reader's activity had stopped.*

> We want to push this to a remote branch. We already have a mothership repo
> on "mortegon" but we should open a new repo for this one too. We should name
> the project different from vertiscope, remove all secrets and personal info, and
> then push to the new repo. I think the name of the project should be named
> "labyrintalis". before we push, we should add a latent feature that rotates
> both cartesian and color coordinates slowly but noticeably whenever there is
> no user activity. also, let's bring our retrieval bar as instead a
> middle-bottom field/panel that is 'naked' meaning just showing the search
> box itself with maybe a translucent "search" prompt for the user to fill in
> that is replaced by the user's input. also, we will add a search rule to our
> retrieval that means we both do a global search over our database, and also
> search duckduckgo automatically, following a simple auto-scroll and clicking
> 'more results' each time. while the diff streams, we have a specific overlay
> rule for search and retrieval; a horizontal scroll bar accompanies below the
> user search input overlay on the 3D graph panel. It begins at the very left.
> The number of search results (i.e. 'top k' in backend terms) is reported
> beside the search bubble as "showing {k}/{n} results". the 'k' value is a
> field the user can input new integers for to get current top-k. Then, as the
> user scrolls horizontally, that governs how many chunks in the top-k results
> are actually visible on screen. These nodes are the only nodes visible while
> a user searches. All other nodes become *translucent-ish* in a way that makes
> them colorless but still applying a glassy lens material effect while the
> 'result' chunk nodes apply a "brightening" or "point source light" effect
> from their original nodes that reflects off the glassy lensing of the nodes
> that aren't shown in the results. This requires specialized materials
> libraries and rendering engines... Perhaps there's a simple blender add to
> our obsidian plugin's 3D view that would work for this? The closer to the
> user's scrolled delta index, the brighter. We also add a toggle to the
> browser overlay that *shows* the overlay chunk bounding boxes as on or off,
> while keeping the regular functionality the same, just a difference
> basically of the alpha-ing. And also, the current bounding boxes are slow in
> their responses quite generally (scrolling, updating, streaming, identifying
> chunk regions, etc) and I think now would be a good time for all the
> speedups and optimizations that you can think of applying to our current
> chunking algorithm and diff streaming mechanism that works still in
> O(delta), gets correct and full set of content detections right (even for
> nested shadow nodes and their resulting location and coordinates on overlays
> which aren't always accurate for a few pages so test on them all, like
> archive etc), and also hovering over the overlays and seeing their panels in
> the 3D graph view are not immediate for new diff streams, and have a
> specific latency at nominal operation after the chunks are fully streamed
> into their end result HTML panels and their nodes are projected, fitted, and
> updated. so, latency on opening the fully rendered panels and some spotty
> nonbehavior when the diff is streamed into its grey-nodes, projected nodes,
> local url updated nodes, and the full umap update (also make sure each of
> these are actually working and running and updates are making it to the 3D
> panel view through some harness/mcp links if you need, for each of these
> steps, getting the time profiles reported directly at the point of the
> interface, but still carrying provenance on the time profile over the
> backend and so on).

*Read as (2026-10-11), in the order given -- the push is LAST ("before we push,
we should add ..."):*

*(83) **Idle drift.** With no reader activity, the 3D scene's positions AND
its colours rotate, slowly but noticeably; any activity stops it.*

*(84) **The naked search field.** The retrieval bar becomes one field at the
middle-bottom of the 3D panel: the input alone, a translucent "search"
placeholder replaced by what the reader types.*

*(85) **Two sources per search.** A query searches the whole store AND
DuckDuckGo, automatically: the browser cell scrolls the results and presses
"more results" each time, and what it finds streams in as a diff. (Pressing a
page's button is acting on the page -- `G-46`'s direction, asked for here by
name; nothing is written into the page's document.)*

*(86) **k and n, beside the field.** "showing {k}/{n} results"; k is an
integer field the reader edits to set top-k.*

*(87) **A horizontal scroll under the field**, starting at the very left. Its
position decides how many of the top-k result nodes are drawn: during a search
ONLY those are drawn as themselves.*

*(88) **Glass and light.** Every other node is colourless, translucent, glassy
-- a lens; each shown result is a point light at its own node, lighting the
glass; the nearer a result is to the scrolled index, the brighter. The reader
asks whether a "simple blender add" would do it: that is a question to answer,
not an instruction -- Blender does not run inside Obsidian's renderer, and the
3D view is three.js, whose physical materials (transmission, IOR) and point
lights are where this has to be built.*

*(89) **An overlay toggle** in the browser cell: the chunk outlines shown or
not, by alpha only; hover, pins and every function behave the same.*

*(90) **Speed and correctness of the overlay and the stream**: outlines respond
at once to scrolling, updates, streaming and region identification; the
chunking and diff stream stay O(delta); every content detection is found,
nested shadow roots included, and its overlay coordinates are right -- tested
on EVERY corpus page, archive.org among them.*

*(91) **The hover-to-panel path is immediate at every stage of a stream** --
grey (streamed) nodes, projected nodes, the url's local update, the full UMAP
refit -- and at nominal operation after; each stage is shown to RUN and to
reach the 3D panel, with its time profile reported at the interface and its
provenance carried back through the backend.*

*(92) **Then the push.** The project is renamed **labyrintalis**, every secret
and personal detail is removed, and it is pushed to a NEW repository, separate
from the mothership on "mortegon". Creating and pushing are outward-facing:
the repository's owner and visibility are confirmed with the reader first.*

> showing 12/11 results, and I'm seeing a lot more chunks than that... and
> I'm sure there's more results that return... all disconnected, but the
> rendering looks really amazing, scrolling works perfect, and i can still
> see images on overlays, so excellent progress there.

*(Sent with a screenshot of the 3D panel mid-search: glass orbs, a few lit
results, the field reading "protocol · showing 12 / 11 results".)*

> at the same time, I think we're supposed to still see "all the nodes" just
> translucent for not in scroll

> lets standardize the latent glowing glass orbs as the default, with the
> light sources adjusting per the query scroll window. pls dont forget about
> the rotating xyzhsv

*Read as (2026-10-11): (86) amended -- k is never shown above n, and n is the
ranking's own count of matching chunks (the sidecar answering it had not been
restarted, so the field counted its 11 hits). (88) amended -- every node stays
visible during a search: those outside the scroll window as translucent glass,
not hidden. (93) **The glowing glass orb is the default look of a node**,
search or no search: each in its own colour, glowing faintly from within;
during a search the light sources are the results inside the scroll window.
(83) restated: the idle turn rotates position AND colour -- "xyzhsv" -- and the
colour turn applies to the orbs.*

> we should also fly to the top result similar to hover overlays and showing
> their panels and so on. same link and idea. but I also dont see more than
> one glowing node in search results when there should be more. works at the
> chunk view level though which is nice

> also, lets add a soft brightness gradient to the scroll slider so that we
> can smoothly brighten on soft integer result nodes

> please also keep track of the rotating xyzhsv and the other comments ive
> made in our most recent parts of our transcript. time profile,
> responsiveness, translucent glass orbs as the norm with a latent glow when
> none are retrieved, streaming and node layout pipelines time optimization
> that work unaffected by the retrieval results (since that's just a
> brightness and fly-to-node thing)

> also seems like youre thresholding on the number of total results. perhaps
> that could also be another user input field for total results.

*Read as (2026-10-11): (94) a new query flies the camera to its top result and
opens its panel, by the hover's own path. (95) the slider is SOFT: a continuous
index, so the next result brightens in smoothly as the slider passes it, and
the track itself carries the gradient. (96) **Retrieval is a look, not a
change to the scene**: it brightens and flies, and the streaming and layout
pipelines run exactly as they would without it -- no node placed, moved or
removed for a search; a result whose chunk is not drawn lights the node that
stands for it. (97) n -- the total results -- is a field the reader sets too,
beside k. The rest restates (83) "xyzhsv", (90) responsiveness, (91) time
profiles and (93) glass orbs with a latent glow as the norm when nothing is
retrieved.*

> tests should auto-resume after I interact with the GUI/plugin
> some nodes are not the same level of glass and translucent, and are their
> older materials without glow\

*Read as (2026-10-11): (98) a check run PAUSES when the reader uses the app and
RESUMES on its own after quiet -- not ends; a check the reader's input landed
in is run again, its first verdict being the reader's as much as the app's.
(99) every node is the same glowing glass: a picture is held inside an orb of
its own colour, and a streaming node is an orb with a dimmer glow -- no node
keeps the old opaque or plain-translucent material.*

> we dont need spheres over images, but hovered-inner-glow works well. we can
> switch between node and image reveals as was the same as the older
> functionality

*Read as (2026-10-11): (99) amended -- a REVEALED picture is drawn as the
picture alone, no orb over it; unrevealed, the node is its glowing orb: the
switch between node and image is the old one. The hovered node's inner glow
stays.*

> a little too clumped together... not sure what the stage of
> projection/.update fitting we're at here, perhaps *some* amount of
> force-directed is still worth, but not to the extent that we have to break
> our memory bank or see nodes exploding everywhere because of force
> superpositions

*(Sent with a screenshot of chunk view: a page's orbs and pictures piled on
one another around its url node.)*

> still a few other features that were requested need following up on too.
> just not to lose track of progress

> still seeing older nodes in tests

*(Sent with a screenshot of the url view: opaque spheres among the pictures.)*

*Read as (2026-10-11): (100) chunk view gets SOME separation, bounded: one
collision relax after its layout lands -- no live simulation, so no forces to
superpose, each node leashed to its UMAP point, memory flat. Item (78)'s "UMAP
only" stands for the simulation; this is a single bounded pass. (101) no node
is drawn in the old material, in the app or in a check: a picture not yet
loaded is its glowing orb meanwhile. (The checks' planted arms draw the old
look on purpose, briefly.) And the requested features are tracked to the end:
the list is the PRD rows G-155..G-171.*

> there should be the glowing effect for when nodes are hovered over. for
> images, keep the images but still add the glow effect. same idea though;
> nodes glow the same way as image billboards are revealed for their hovered
> nodes within a certain region of the mouse on the camera normal

*Read as (2026-10-11): (102) nodes near the pointer's ray GLOW -- the same
region that decides which pictures are revealed, graded by nearness to the
ray: an orb glows brighter from within, a picture keeps its image and glows
(brightened, a soft light at its edge).*

> also, I don't know if the chunks are linked correctly to each other along
> the hierarchical DOM structures over their patricia trie paths... it looks
> like a shortcut where there's just all the recursive chunks linked to their
> root URL node. Perhaps investigate further, since this is a recurring item
> that needs continuous clarity on its representations in the 3D graph viewer

> node hover and image/glow features seem to work but have a noticeably slow
> latency

*Read as (2026-10-11): (103) a page's chunks are linked along the patricia
trie -- each to its nearest enclosing chunk -- never all to the url node, on
every page, however its chunks were streamed in; and this is checked
continuously, not once. Measured: Dril 261/263 and Okapi 182/182 agree with
the trie, RFC 9110 drew all 1,172 off its url node (stored containment is
linked per drain). (104) hover, glow and picture reveal respond at once:
pointer to glow measured 49-113 ms in chunk view, most of it an 80 ms throttle
and a full re-sync per change.*

> also, scrolling and 'more results' in search should be an exhaustive while
> loop until no deltas or something like the more results button isn't there.

*Read as (2026-10-11): (105) the web half of a search has no fixed round
count: it scrolls and presses "More results" in a loop that ends only when a
round adds no results (no delta) or the button is gone -- and says which of
the two ended it. A newer query still cancels it.*

> also, i notice no diff update on retrieval results and effects on the scroll
> bar

*(Sent with a screenshot of the search field: "monkey", "showing 20 / 50
results · 55 matching", the scroll bar a flat grey track.)*

*Read as (2026-10-11): (106) while a query stands, what streams in (the web
half's pages, any capture) updates the RESULTS as a diff -- the matching
count, the ranks, the lights -- without the reader asking again; and the
scroll bar SHOWS it: the soft brightness gradient of item (97) drawn on the
track, moving with the window and the result count.*

> also, the search button should trigger web search, not auto-updates piped
> also to the search browser

*Read as (2026-10-11): (107) typing ranks the store as it goes (the field's
auto-update) and touches the browser cell NOT AT ALL; the web half runs only
when the reader presses the search button -- read here as the button beside
the field and Enter in it, the keyboard's form of the same press.*

> i can't interact with the result boxes. i type a number and am instantly
> kicked out

*(Sent with a screenshot of the field holding a live check's query, "okapi
giraffe relative habitat a", showing 8 / 50.)*

*Read as (2026-10-11): a field the reader is typing in keeps the keyboard:
the browser cell navigating or pressing "More results" for a search never
takes focus from it; and no check types into the reader's field while they
use it.*

> also i keep switching to 'chunk' view and re-fitting keeps re-running, but
> we should be persisting these layouts to the entities in our database.

*Read as (2026-10-11): (108) a layout, once fitted, is STORED on the
entities it places -- each chunk's (and page's) position in the database
beside it -- and switching to a view reads the stored positions instead of
fitting again; a fit runs only for what has no stored position yet, or when
the reader asks for a refit.*

*(Found on reading the code: the server does not refit on a switch -- 0
latent refits, the fit loaded from its stored pickle -- but the CLIENT does
two things every switch: item (100)'s collision relax runs again from the
UMAP points, moving every node, and the status reads "fitting…" while it
only reads positions.)*

> also, up and down arrow keys when the cursor is in the integer boxes should
> modify the values up and down at adaptive speeds depending on how long the
> hold has been

*Read as (2026-10-11): (109) in the k and n fields, Up and Down step the
value by one, and holding the key steps faster the longer it is held; the
view follows as it steps.*

> why are some of the spheres like GIANT?

*Read as (2026-10-11), with the reader's earlier "I'd like consistent node
sizes if possible" / "if its an image size thing then okay": chunk view
draws every sphere at one size, pages among them; only pictures differ.
(Measured live: the DuckDuckGo page node, 605 members, radius 9.43 against a
median chunk's 0.22.)*

> also, both jumbling and extreme latency on the diff streams

*(Sent with a screenshot: the DuckDuckGo page's chunks as large overlapping
translucent orbs, piled over the page node.)*

*Read as (2026-10-11): (110) a page streaming in -- the web half's results
page above all, growing with every "More results" -- places each NEW chunk
once and leaves the ones already placed where they are (no jumbling), and
reaches the view with low latency however large the page grows. Measured
live before any change: the projector's per-page local fit last ran on the
DuckDuckGo page -- 534 chunks, 1,072 ms -- and moved 598.*

> new streams work a little better but still some leftover jumbling

> but the latency is still pretty rough

*(Found on reading the live state: the plugin then running was the build
before the size fixes; streaming placeholders drew at 10x a chunk and 1,587
unrevealed favicon chunks at 14x; a chunk-view layout cost 42-66 s in the
sidecar, reading every page's anchors, and a capture waited 21 s in
transport behind it -- end to end 45.8 s for one drain.)*

> I can't enter things in the search bar but I should be able to through the
> patricia trie

*(Sent with a screenshot of a hovered chunk's panel on the DuckDuckGo page:
the page form with its search box holding "okapi giraffe relative habi", and
the markdown below it, `[ ] okapi giraffe relative habitat a` and
`( Clear )`.)*

*Read as (2026-10-11): (111) a field drawn in a panel -- the page form's
input and the markdown's `[ ]` -- is typed into IN PLACE, and what is typed
reaches the live page's element through its trie address (the panel's line
names the address; the browser cell holds the element), the way the
reader's own keyboard would.*

> more jumbling

*(Sent with a screenshot of the build then running -- before the size fixes
were loaded: the page sphere and the favicon orbs at their old sizes.)*

> i don't think the mouse needs to be revealing images a long ways away. the
> mouse was in the top right corner of the screen, and it was like no matter
> how far, the images from a far-away url would still reveal, which I think
> means ray projection vs regular cylindrical bounds on the mouse with ray
> projection in a similar manner.

*(Sent with a screenshot of url view, pictures revealed across the whole
pane.)*

*Read as (2026-10-11): (112) the region around the pointer's ray is
BOUNDED: a cylinder about the ray, so a node is revealed (and glows) only
within a fixed distance of the ray; with nothing in it, nothing is revealed.
The ranking inside it stays by nearness to the ray. (The code then took the K
nearest with no bound at all, so K pictures were always revealed somewhere.)*

> also not sure if I'm seeing the xyzhsv rotations taking effect yet

*(Found on reading the live state: 0 drift starts since the reload -- the
drift was gated off whenever a query stood in the field, and one did.)*

> hsv rotation seems pretty slow

*Read as (2026-10-12): the idle turn runs with a query standing too (item
83 with 93's "pls dont forget about the rotating xyzhsv"), and the hue turns
faster: the wheel in about 30 s, not 2 minutes.*

> physical rotation could be slower... im feeling dizzy

*Read as (2026-10-12): the camera's orbit turns a third as fast -- a full
turn in about 5 minutes, not 100 s; the hue keeps its 30 s.*

> hsv rotation could be a lot faster, physical rotation could be somewhat
> faster

*Read as (2026-10-12): hue 0.8 rad/s (the wheel in about 8 s); orbit 0.035
rad/s (a turn in about 3 minutes -- between the 5 minutes just set and the
100 s that made the reader dizzy).*

> glowing effects are completely invisible now

*(Found: the cylinder at 4% of the cloud was about 40 px at the usual zoom,
and the glow was graded by RANK among what fell inside -- one node at the
pointer, no visible glow. Widened to 12% meanwhile.)*

> more jumbling and the ray projections still span too far, and I think
> previous versions before i had spotted the problem in the first place might
> be best

*(Sent with a screenshot of chunk view: large overlapping orbs. Found: the
"one size" of item (G-181) was `val` 1 -- radius 2.65 -- against a median
chunk's 0.19, every orb fourteen times too big; the relax then spaced them at
that size.)*

*The reader's answer, asked which earlier behaviour (2026-10-12): "Tight
circle, glow too" -- the first bounded version (about a 40 px circle), with
the glow kept visible in it, graded by distance. And the one size is the
median chunk's.*

> chunk overlay issue that might be overcomplicated compared to the original
> context window cutoff rule at the very next parent level

*(Sent with a screenshot of arXiv's stat.ML listing in the browser cell: a
chunk's outline from the authors of entry [8] into the title of [9].
Found on reading the stored chunk: its lines run in document order through
[8] and [9], but the ADDRESSES they carry do not -- "Title: A Critical
Look ..." keyed to `dd[6]`, its authors to `dd[7]`, its subjects to `dd[8]`,
"[9]" to `dd[6]/.../a` -- so every box the overlay draws from them is
elsewhere. Under investigation; the chunking rule itself is not yet shown to
be at fault.)*

*Read as (2026-10-12): (113) every line of a chunk names the element it
draws, so its outline in the browser is where the line is. (Two causes fixed
-- a lost anchor read positionally, and a write skipped while its addresses
moved; one intermittent cause open, PRD G-186.)*

> arrow keys while hovering on the 3D panel and not the search box should be
> for precise panning

*Read as (2026-10-12): (114) with the pointer over the 3D view and no text
field focused, the arrow keys pan the camera -- small, precise steps across
the screen, faster the longer a key is held (as item 109's fields step); in
the search field they stay the field's.*

> clicking and dragging empty space somehow drags a nearby (up close to the
> camera) but distant node on xy coordinates for some reason

*(Found, 2026-10-12: the invisible pick proxies kept the size they were made
at -- 21,808 of 22,229 stale, the worst 21.5x the drawn node -- and the
"covers the ray" test sized nodes by `val`, not as drawn. Read as: a node is
picked only where it is DRAWN.)*

*The reader's answers, asked 2026-10-12 (AskUserQuestion): the room-pass
"ring" -- "Remove it"; the sidecar -- "Yes, enable --enact"; stale anchors --
"Clean them now". (The store-wide stale-anchor figure the question quoted
was a measurement artifact, corrected in PRD G-186.)*

> the nodes could be a little larger/brighter by default and the links could
> be a little smaller... so that I see more color and less of the links, while
> still clearly seeing the links visible

*Read as (2026-10-12): (115) by default, nodes a little larger and brighter
(more of their colour shows) and links a little fainter/thinner -- still
clearly visible.*

> significant lag experienced here

*(Said right after (115) went live: nodes 1.25x and brighter, links fainter.)*

> clicking on a node after clicking on another node gives no response in the
> browser, either scrolling to page or navigating to the url prior to

*(Sent with a screenshot: an IMDb chunk's panel open over the 3D view.)*

*Read as (2026-10-12): every click on a node reaches the browser cell --
navigating to its page, or scrolling to it when the page is already open --
however many clicks came before.*

### 2026-10-17

> please continue. you've have to bring our app back up. we've added some
> tools to our mcp surface to help. please use them and debug them as well.

> we had some extra changes added since the last time we left off (last
> week). I'd suggest reviewing some of those, noting we favored reverting to
> the original state we (you and me) left off at before we made our changes.
> I'd like you to have a look at our diff and see if you could build some of
> the things back in, but with the design thinking in mind rather than the
> code itself. the reason i say this is because the work that was attempted
> was not the best quality.

*The diff is `c4648c1` on `backup/ahead-conversation-20261015` (the MCP
tools were carried back staged). The conversation that produced it left no
record this repo can read, so what it was FOR is read off the diff, and every
reading below is mine, not the reader's:*

*(116) the cloud is framed where it is: a cloud whose middle is off the origin
-- a fresh store with a page or two is the extreme -- is still framed whole
(the diff moved every node to the origin, which breaks stored places; read
as: the camera moves, the map does not). (117) the probe attaches to the
workspace window, not the vault picker. (118) layout geometry "pure UMAP" --
no quantile spread, no containment, no depth compression: a change to how
EVERY layout looks, against deliberate earlier decisions; not rebuilt
without the reader's word. (119) the MCP tools that start, stop and inspect
the app: kept and debugged -- a status that called a busy sidecar dead, a
start that killed a running store, a launch that would reset the reader's
plugin settings, a reload that awaited the call that hangs, a reframe read
mid-flight.*

> experiencing significant and persistent un-settling on camera placement and
> 3D coordinates

*(Said while the framing probe ran with a once-only idle gate and a
subtract-restore that threw nodes the other way; stopped, then asked.)*

*The reader's answers, asked 2026-10-17 (AskUserQuestion): un-settling after
the probes stopped -- "Stopped now"; live probing -- "Yes, when I'm idle
(Recommended)"; pure UMAP (118) -- "Keep current layout".*

---


## Addendum X, 2026-10-17 - the phased projection pipeline, registered camera, panels, the browser, and scaling instead of collisions

*Asked (AskUserQuestion, 2026-10-17) after G-93 was measured: a new page's
grey tree cannot know its place until the projector answers (0.6-2.3 s);
"Accept one glide / Wait for placement / Fade, don't glide". The reader
chose the first and went on, verbatim:*

> accept one glide. please ensure we are following our phased pipeline here
> where we get complete projections over the page (with debounce that is
> time-synched to the adaptive expected latency on umap-cuda.update() calls
> on the local url node's domain) as the first priority for all chunks that
> are vectorized to the url. Then we get local and global updates as
> mentioned, with similar adaptive latency debounces that inform themselves
> by the O-complexity of the local projections, local updates, and global
> updates. One other thing I'll point out here is that when we currently
> call a re-fit on the full set of UMAP chunks, our camera snaps to the
> 're-center view'. Perhaps we could apply efficient scale-aware ICP over the
> URL nodes so that we render the 3D coordinates from their closest most
> previous registered camera pose. That way, things are less 'snappy'. I'm
> also going to point out here that hovering over the browser chunk bboxes
> works very well, and we want to keep this reliable and functional part of
> our pipeline. However, I notice a few things that I think should be
> brought up as feature updates for our current framework:
>
> 1 Hovering over chunk overlays is good latency and responds quickly to the
> rendered set of 3D billboard panels in their dual-view form. I'd maybe add
> a toggle to switch on and off the panels always opening on fly-to nodes
> and instead opening when a right-click action is made.
>
> 2 some images in the rendered chunk panels don't show up, usually on
> recipe websites I think, a few of them we already have in our db and 3D
> graph, I'd suggest hooking up some kind of MCP interface, such as the once
> suggested later, for unified and efficient (slim-surface) graph-rag-web
> interactions, with your own development tools extensions to check the
> content-completeness on rendering to streamed interactive chunk diffs.
>
> 3 I'm wondering if we could get async streaming on markdown and rendered
> shadow DOM chunk panels so that we can view the base-content
> extracted/detected on the diff tree in just their markdown form as
> grey-nodes, with shadow-DOM streaming adaptively at this stage of diff
> streaming to the 3D graph. depending on when/where vectorization happens,
> likely at the very end since it's complete to the content-set with minimal
> diff updates there too if those are truly present in measurements (i.e.
> latent interactions that might retrieve new DOM components over the
> network), we can efficiently demarcate rendering requirements as preceding
> the vectorization and thus projection pass.
>
> 4 Currently, interacting with scans on bluesky show that nodes scanned
> temporarily are disappearing, and also right/left clicking on the url
> nodes don't explode/collapse as I would anticipate for scanned nodes.
> also, embedded media is missing. the nodes are registered, but the content
> is missing.
>
> 5 there are two web-nav button-sets for going "back and forward". please
> fix.
>
> 6 please add uBlock origin to our browser immediately
>
> 7 please default natural-text inputs to the web-browser url bar as
> duckduckgo search inputs (no need to scroll)
>
> 8 for multi-url and fast navigations on the 3D diff stream and layout
> phases, I notice some diffs disappear from the rendering/layout queue, so
> please make sure that we are able to persist rendering on grey nodes
> streamed as diffs a few seconds ago on one page while the same thing
> happens on successive pages.
>
> I will also ask here about the various hidden details that accompany our
> main UMAP phased pipeline like boundaries and collisions. In our work with
> the antigravity session, we explore the idea of staying exact to the
> original UMAP projections without applying drift-based adjustments to
> collisions on nodes.
>
> Instead, we will take a different approach. We will apply an adaptive
> scaling at our two different levels: the url-nodes and their chunk
> contents. We will first apply scaling at the url node level to ensure that
> the nodes, retaining their constant diameter size, are scaled up from an
> intentionally-kept centroid computed directly from the chunk coordinates
> that sets the url node placements (which I will also mention here should
> be double or triple the size of the chunk nodes so that interacting with
> page expansion/collapsing is more accessible, and this is also part of the
> chunk-level 3D rescale from the URL node centroid origin in their relative
> coordinate frame of reference). So, the adaptive scaling *expands* (in
> most cases, contracts otherwise) as necessary such that the minimum
> separation distance between the chunk coordinates are twice the chunk node
> diameters. In cases where the minimum is higher, we scale down. Then, we
> apply similar per-diameter scaling on the larger set of URL nodes, with
> their own diameter and separation distance constants that accompany
> expansion/contraction rules. We, of course, perform this about an
> instantiated centroid node that represents the web browser as a minimal
> MCP surface with at most one tool call over the set of largely web browser
> interaction from a graph-RAG interface on the vectorized DB.
>
> We will take some time to design the MCP tool space more specifically, so
> we'll keep the centroid as just a gauge-point placeholder for now until we
> are ready to really dive in to how the node interacts with its web-data
> interfaces through an interactive extension to graph RAG over the patricia
> trie with vector retrieval aspects and more attention to detail on URL
> domain and web tree navigation with chunk-based retrieval managed with
> regular web interactions such as scrolls and click, so we essentially
> simulate the rendered minimal interactive webpage from the perspective of
> the graph RAG database. If I remember correctly, we have some clear
> interaction policies for webpages on the side of our tool already, so in
> theory, we could even differ the way the results are presented depending
> on which level of graph RAG query is set, whether at the web, domain, or
> in-page scopes. In any case, we organize and present chunk interactions as
> atomic units that enable their own per-page navigations as well as
> navigation over the rendered/retrieved set of rendered inter-web chunk
> results, where direct interactions with each chunk are enabled by
> selection and interactions. this will be important for proving out
> complex interactions over a set of chunks from different URL domains
> efficiently. Moreover, re-rendering surfaces at different levels of the
> interactive retrieval artifact (i.e. at the per-chunk level and following
> up on deeper navigation traces) could accompany page navigations such as
> "back" and "forward". So, for going "up" to the results and "down" to
> their per-page traces are different somewhat from going 'back and
> forward', but effectively trace back to the origin of the retrieval
> artifact when going "up" from per-page trace navigations, which themselves
> stream and render on the interactive retrieval artifact as diffs.

*Asked in the same question set (G-94): pages buried behind others are
spaced fine in 3D and line up in depth inside site clusters; "Judge it in
3D / Flatter depth / Smaller at full view". The reader: "Smaller at full
view".*

*Read as (2026-10-17), mine, to be decomposed in the PRD as G-193 on:*

*(120) the phased projection pipeline, in priority order: first a COMPLETE
projection of every vectorised chunk of the page, debounced to the measured
latency of the local fit's update for that url's domain; then local and
global updates, each debounced by its own measured cost (which scales with
its size). (121) a full refit does not snap the camera to "recentre": the new
url-node coordinates are registered onto the previous ones (scale-aware
ICP / similarity Procrustes over the url nodes) and the camera keeps its
pose in that registered frame. (122) keep: hovering a browser chunk box
drives the 3D billboards with good latency. (123) a toggle: billboards open
on fly-to (as now) or only on a right-click. (124) images missing from chunk
panels (recipe sites), including ones the store and graph already hold; a
development tool (MCP) that checks a rendered panel's content-completeness
against the streamed chunk. (125) grey nodes show their markdown at once;
the shadow-DOM panel streams in after; vectorisation and projection come
last, so rendering never waits for them. (126) Bluesky: scanned nodes
vanish; left/right clicks on a scanned page's url node do not unfold or
fold it; embedded media missing though the nodes are registered. (127) one
set of back/forward buttons, not two. (128) uBlock Origin in the browser
cell. (129) natural text typed in the url bar searches DuckDuckGo. (130)
fast multi-page navigation: grey nodes streamed seconds ago on one page
persist while the next page streams. (131) layout geometry: no collision
drift -- positions stay the UMAP's; instead an adaptive SCALE about each url
node's chunk centroid so the minimum chunk separation is twice the chunk
diameter (expand or contract), then the same over the url nodes about a
browser centroid node with their own constants; url nodes 2-3x a chunk's
size. (132) the browser centroid is a gauge-point placeholder for a future
one-tool MCP graph-RAG surface (web / domain / in-page scopes, chunks as
atomic interactive units, "up"/"down" between results and per-page traces
distinct from back/forward) -- to be DESIGNED with the reader before built.
(133) at full view (the whole corpus in frame) nodes draw smaller; full size
when zoomed in.*

> we should also add a liminal diffuse-glow effect to our chunk nodes since
> they're currently pretty small and only reflect light rays through each
> other rather than something truly 'latent and luminal' where we can see the
> chunk nodes as brightness points since they're so small

*(Said 2026-10-17 while G-206 drew nodes at half size at full view.) Read as
(134): every chunk node carries a soft, additive, diffuse glow in its own
colour, sized so that even a node a pixel or two across reads as a point of
light -- emitted brightness, not only the glass lens's reflections.*

> way too low glow and dark halo rings around the nodes

> also, perhaps ensure the background is also black and not grey

> the node glow could be broader and less concentrated at their centers, or a
> more smooth rolloff on the glow distance/luminosity and concentration (power
> vs diffuse)

*(Said 2026-10-17 over the first cut of (134): the dark rings were the halo
writing alpha onto the transparent canvas; fixed, the glow widened and made
mostly diffuse, the background black.)*

> hovering over nodes shows no image overlays in the chunk view, but the light
> distributions are much better.

> i think the hovered node images should occlude other light sources so that
> we can see the presented node images without the light-source occlusion

*Read as (2026-10-17): (135) in chunk view a hovered node presents its picture
at a size a reader can see (it was drawn at the one orb size, about a pixel,
and pending in the atlas); a presented picture covers the glow of nodes
around and in front of it.*

> we should add the same glowing effect as the default for retrieval
> renderings. retrieval takes quite a long time so perhaps we could try tiered
> retrieval on url nodes that are most similar first and then per-node
> sub-chunk re-ranking for later url nodes in the retrieval readout. also, the
> way our result {k}/{n} modifiable fields are all out of whack (they don't
> work for updates right, don't exceed a 50 result limit to cover the full set
> of retrieved results, and the numerator and denominator are mixed up).
> perhaps since we use a tiered result system here too, we modify updates on
> the 3D graph according to most recent re-ranked set over the URL
> similarities.

*Read as (2026-10-17): (136) a search's rendering uses the same glow as the
default view. (137) tiered retrieval: rank url nodes first (most similar
pages), then re-rank each page's chunks, page by page, into the readout --
the first results land fast, later pages refine. (138) the k/n fields: k the
results shown (numerator), n the results retrieved (denominator), editable
updates that take effect, no 50 cap -- n reaches the full retrieved set.
(139) the 3D graph follows the most recent re-ranked set over the url
similarities, tier by tier.*

> we should also darken nodes in front of the hovered node images (if they
> are present, and there often is at least one icon image to present as the
> node billboard).

*Read as (2026-10-17): (140) while a picture is presented under the pointer,
the nodes between the camera and it are drawn dark -- orb and glow.*

> rotating xyzhsv stalls out after some time, and it could debounce a lot
> faster

*Read as (2026-10-17): (141) the idle turn keeps turning for as long as the
reader is away -- nothing that is not the reader stops it -- and starts after
a few seconds of quiet, not twenty.*

*Asked (AskUserQuestion, 2026-10-17): which fraction the k/n fields read --
the reader: "shown / retrieved"; uBlock's download -- "Yes, download it".
Then, defining the two words:*

> shown means all nodes present in the 3D ui. retrieved means the most recent
> set of update retrieval results streaming over our efficient hierarchical
> re-ranking and streaming retrieval updates adaptively, not necessarily
> diffs, but diffs are integrated into re-ranking and re-url retrieval
> updates (i.e. retrieval new URL nodes and re-rank, then retrieve their
> containing chunks and re-rank, updating the current set of most recent
> retrieved chunks for all current URLs)

*Read as (2026-10-17): (142) k = SHOWN, every result node present in the 3D
view; n = RETRIEVED, the current set from the hierarchical pipeline: rank url
nodes (new ones retrieved and the set re-ranked), then retrieve each url's
chunks and re-rank them, the current set replaced by the most recent ranks for
all current urls -- streamed adaptively; a diff (what streamed into the store)
feeds the next url and chunk re-rank, it is not itself the update.*

> panel fly to and right click on hovers doesn't function on the toggle

*Read as (2026-10-17): (143) the G-196 toggle must govern the hover the
reader actually makes -- the browser cell's chunk overlays -- not only the 3D
pointer: in right-click mode a hover flies without opening a panel, and a
right-click on the hovered chunk opens it.*

> also, scrolling over archive org still throws tons of chunk leakage because
> nested shadow nodes keep mutating older data in-place, but we need to
> robustly queue/diff/and track the full set of unique chunks so we don't
> have to wait for processes to complete. this might go along with the async
> test/rendering streaming to panels prior to vectorization. The main point
> should be that we ensure that we stream chunk diffs and update robustly for
> the edge case of scrolling over archive. We also need to ensure that the
> streamed diffs don't pipe-out because of constant mutation updates. ensure
> to work this in with the rest of the things still open.

*Read as (2026-10-17): (144) on archive.org, nested shadow roots rewrite
already-seen content in place while the reader scrolls; the stream must keep
the full set of UNIQUE chunks -- queued, diffed and tracked by identity -- so
an in-place rewrite updates its chunk instead of leaking a new one, nothing
waits on a slower stage to finish, and constant mutation never stalls or
floods the diff stream (it must not "pipe out").*

> remember, we have to persist chunk streams no matter how fast interactions
> are on the page. we also have a lot of lag in hovering to rendering which
> tells me we haven't reached that phase of the task set yet

*Read as (2026-10-17): (145) a chunk stream is never dropped, however fast the
reader acts on the page (scrolls, navigations, hovers) -- the bound is on
cost, never on what is kept; and the hover-to-panel latency is measured and
brought down, phase by phase.*

*Asked (AskUserQuestion, 2026-10-17): the graph store is 63 GB for 65k
chunks and 1.5M addresses; checkpoints hold it 1-3 min and reads cost
100-300 ms; may it be compacted? The reader:*

> this is where our efficient data storage techniques shall now come into
> play. optimization on performance in general as much as possible. thank you
> for bringing this up.

*Read as (2026-10-17): (146) the store is rebuilt compact, by efficient
storage techniques measured against what the 63 GB actually holds, with
performance optimised throughout; no write is lost in the switch and the
original is kept until the reader says otherwise.*

> still quite a bit of work to do with archive

> will have to navigate back to archive and rerun, maybe the homepage and test
> from there

> very serious url and chunk degradation that must be fixed and tested for as
> an edge case

> ill keep the most recent one open for you to catch up with your mcp as well

*(Sent 2026-10-17 with screenshots: on archive.org a hovered result tile
opened the search page's hidden "Feedback Survey" container and the corner
box read "0/0 in graph"; then, on a TMDB person page, a hover opened an
archive.org chunk's panel.) Read as (147): a hover resolves only to a chunk
of the page the browser shows -- never another page's, whatever the order of
navigation, loading and the sensor's messages -- tested as an edge case; and
every check of "which page is this" agrees on the document, not on a url the
page rewrote.*

> hovering over vhs vault inbox does not display the correct shadow chunk

*(Sent 2026-10-17 with a screenshot of the archive.org homepage.) Read as
(148): hovering a tile inside archive.org's nested shadow roots opens THAT
tile's chunk -- its own title, count and picture -- not a neighbour's, not
the grid that holds it, not a stored container far above it.*

> hovering on archive changes and is consistently incorrect. also going back
> to previous pages repeats a scan entirely without efficient diff updates.
> we should also add a horizontal overlay of retrieval results above the
> search bar that is linked to the scroll bar below the search and matches
> the scrolling scale over the overlay with the node highlights, and
> hovering scroll results includes the fly-to-node feature. please work on
> the existing task set and add each of these to the list of items still
> open. retrieval is also back to a slow response, maybe some performance
> updates there are in order, same goes for clicking nodes to see their
> panels. also, result numerator and denominator work but are maxed out at
> 2000 rather than the proper upper limit. also, scans are slow to register
> older chunks. Perhaps priority on the oldest pushed diff updates and
> vectorization/projection/fitting in batches is in order rather than having
> to wait so long for things to register at the very end. also, zooming lags
> heavily for throughput streams (maybe some throttling here) and for some
> reason we have these huge nodes popping up in the way of tiny result nodes
> and I'm wondering why the discrepancy and how well our scaling is
> implemented for this. also, zooming out while scanning doesn't persist
> over later node hovers by the search-scroll-scan. perhaps we can make the
> adaptive scale adjustment include per-hover updates for url-contained node
> coordinates such that hovered urls are temporarily re-scaled so that their
> image overlays/billboards don't overlap with each other within an
> increased separation distance. this re-sets to the older adaptive-scaled
> transform that was set after the umap fits/projections at the url-node
> containment level

*(Sent 2026-10-17 with screenshots: archive.org tiles Podcasts, Radio
Stations, Thingiverse Archive and Operating System Software each opened a
DIFFERENT tile's panel -- Television Archive News Search Service, a bare
"/details/podcasts" line set, APK Archive, Cratediggers; a search for
"cowboy" reading "showing 2000 / 2000 results - 29 retrieved of 587
matching" with very large page orbs in front of small result orbs; and
billboards stacked over each other on a hovered url.) Read as, one item per
request, each added to the open list:*

*(149) archive.org hover is consistently a neighbour: the panel must be the
hovered tile's own, and it must stay right as the page's virtual list
rewrites its tiles in place (148 restated with evidence that it is
systematic, not occasional).*

*(150) going BACK to a page already scanned resumes from what was kept: the
page's chunks are diffed against the new visit, not rescanned and re-sent
whole.*

*(151) a horizontal strip of retrieval results above the search bar, tied to
the scroll bar below the search: its scroll position and scale match the
strip, results in it are highlighted as their nodes are, and hovering a
result there flies to its node.*

*(152) retrieval is slow again: measure where the time goes and bring it
down.*

*(153) clicking a node to open its panel is slow: measure and bring it down.*

*(154) k/n work but cap at 2000: the bound is the number actually matching
(the "of N matching"), not a fixed 2000.*

*(155) a scan registers its older chunks late: the OLDEST pushed diffs go
first, and vectorization, projection and fitting run in batches as the scan
goes, rather than everything landing at the very end.*

*(156) zoom lags heavily while a stream is flowing: throttle the stream's
work so a zoom stays smooth.*

*(157) why are some nodes huge, in the way of tiny result nodes? Explain the
size discrepancy and check how well the scaling is implemented for it.*

*(158) a zoom-out made while scanning is lost at the next hover the
search-scroll-scan makes: the reader's zoom persists.*

*(159) adaptive scale per hover: a hovered url's contained nodes are
temporarily spread so their pictures and panels do not overlap within a
larger separation distance; when the hover ends they return to the
adaptive-scaled transform set after the UMAP fit, at the url-node
containment level.*

> retrieval usage is buggy. thanks for the excellent improvements though

*(Sent 2026-10-18, after the store rebuild, the k/n bound, tiered pages by
what they hold, the results strip and the zoom fixes.) Read as (160): using
retrieval in the app misbehaves -- what exactly is to be found by using it as
the reader does, and fixed.*

> the fly-to/right-click should also toggle for hovering retrieval results on
> their scrolled ranks

*Read as (2026-10-18): (161) the panels toggle (G-196/G-215) governs the
results strip as it governs the browser hover: in right-click mode hovering a
result on the strip flies to it without a panel and a right-click on it opens
the panel; in fly-to mode a hover flies and opens it.*

*Where (131) meets "Keep current layout" (asked minutes earlier, about the
quantile spread, containment and depth compression): (131) replaces the
collision drift and, by the reader's "exact to the original UMAP
projections", the containment pull; the spread and DEPTH are not named
again and stay until the reader says otherwise.*

---

## Addendum XI, 2026-10-18 - code artifacts: chunking, the code property graph, local models, and through-stack agents

*Sent with a screenshot: on huggingface.co/QuantFactory/Triplex-GGUF, the
pointer over the page's Python code sample opened a panel reading only
"button" -- the copy button's chunk, not the code. The reader then pasted
two of their own earlier messages to another assistant, with that
assistant's replies between them. The reader's words are transcribed here
verbatim; the assistant's replies were AI-written, are NOT authority, and
are summarised in one note below so the record says what was in front of
the reader.*

> code artifact chunking issue; a good time to begin entering the realm of
> coding artifact chunking along our current recursive web chunking suite. I
> also have a lot more ideas to share here:

The reader's first pasted message, verbatim:

> i just saw a video about self-evolving agent harnesses that I thought looked
> cool. I learned about the "everything is a plugin" framework and would love
> to learn more. ive also previously read about ways to represent python
> codebases as knowledge graphs with several functions:
>
> 1. "Knowledge Graph" $\rightarrow$ Code Property Graph (CPG): We don't just
> want a generic knowledge graph. We want a CPG, which combines three
> structures: the Abstract Syntax Tree (AST) (syntactic hierarchy), the Control
> Flow Graph (CFG) (execution order), and the Program Dependence Graph (PDG)
> (what you aptly called "signal flow" or data flow).
>
> 2. "RDF Triples" $\rightarrow$ Property Graph Edges: Standard RDF triples
> (Subject-Predicate-Object) are a bit too rigid. In a CPG, we use Property
> Graphs (like Neo4j) where edges have context (e.g., (Node:Function_A)
> -[CALLS {line: 42, arg_passed: 'user_id'}]-> (Node:Function_B)).
>
> 3. "Unified Diff Upsert": This is the hardest but most valuable part.
> Instead of asking an SLM to rewrite a whole file, the SLM outputs a
> topological change to the graph. The underlying Python engine uses ast and
> difflib to parse the graph mutation back into source code and generate a
> standard unified diff patch.
>
> ```json
> {
>   "toolkit_metadata": {
>     "package_name": "slm-cpg-harness",
>     "version": "1.0.0",
>     "description": "A lightweight Code Property Graph (CPG) toolspace for SLM code generation, enabling semantic code retrieval, data flow tracing, and AST-aware graph diff upserts.",
>     "core_ontology": {
>       "nodes": ["Module", "ClassDef", "FunctionDef", "Variable", "AST_Snippet"],
>       "edges": ["IMPORTS", "CONTAINS", "CALLS", "DATA_FLOWS_TO", "INHERITS"]
>     }
>   },
>   "system_architecture": {
>     "database_layer": "In-memory NetworkX or local Neo4j instance with pgvector for fused Cypher/Vector search.",
>     "ast_parsing": "Python's native `ast` module combined with `tree-sitter` for cross-language support.",
>     "mutation_engine": "AST-to-source unparsing (e.g., using `astor` or `unparse`) combined with Python's `difflib.unified_diff`."
>   },
>   "tools": [
>     {
>       "name": "query_cpg_signal_flow",
>       "description": "Fuses natural language semantic search with Cypher graph traversal. Retrieves a topological code trace including dependencies, call chains, and data flow paths ('signal flow') for a specific concept.",
>       "parameters": {
>         "type": "object",
>         "properties": {
>           "natural_language_intent": {
>             "type": "string",
>             "description": "The semantic query to map to vector embeddings (e.g., 'Where is the user authentication token validated?')"
>           },
>           "cypher_structural_constraint": {
>             "type": "string",
>             "description": "Optional Cypher query to enforce graph structure. Example: MATCH (a:FunctionDef)-[r:DATA_FLOWS_TO*1..3]->(b:Variable {name: 'auth_token'}) RETURN a, b"
>           },
>           "max_depth": {
>             "type": "integer",
>             "default": 3,
>             "description": "How deep to traverse the dependency graph and AST child nodes."
>           }
>         },
>         "required": ["natural_language_intent"]
>       },
>       "returns": {
>         "type": "object",
>         "description": "A serialized CPG trace representing the execution and data flow.",
>         "schema": {
>           "trace_id": "string",
>           "affected_modules": ["string"],
>           "signal_flow_graph": [
>             {
>               "source_node": {"id": "string", "type": "string", "code_snippet": "string"},
>               "edge_type": "string",
>               "target_node": {"id": "string", "type": "string", "code_snippet": "string"}
>             }
>           ]
>         }
>       }
>     },
>     {
>       "name": "upsert_graph_diff",
>       "description": "Takes a list of graph edge mutations (representing the SLM's desired logic changes) and compiles them into a unified diff. It traverses the AST to safely apply 'signal flow' alterations without hallucinating syntax.",
>       "parameters": {
>         "type": "object",
>         "properties": {
>           "target_file_path": {
>             "type": "string",
>             "description": "The module being mutated."
>           },
>           "graph_mutations": {
>             "type": "array",
>             "description": "The property graph representations of the desired code changes.",
>             "items": {
>               "type": "object",
>               "properties": {
>                 "mutation_type": {
>                   "type": "string",
>                   "enum": ["ADD_NODE", "ADD_EDGE", "DELETE_NODE", "DELETE_EDGE", "MODIFY_PROPERTY"]
>                 },
>                 "subject_node_id": {"type": "string"},
>                 "predicate": {"type": "string", "description": "e.g., CALLS, DATA_FLOWS_TO"},
>                 "object_node_id": {"type": "string"},
>                 "python_ast_payload": {
>                   "type": "string",
>                   "description": "The literal Python code snippet to inject if ADD_NODE (e.g., 'def new_validator(token): return True')"
>                 }
>               },
>               "required": ["mutation_type", "subject_node_id"]
>             }
>           }
>         },
>         "required": ["target_file_path", "graph_mutations"]
>       },
>       "returns": {
>         "type": "object",
>         "description": "The resulting source code diffs to be applied to the filesystem.",
>         "schema": {
>           "status": "string",
>           "unified_diff": "string",
>           "compilation_check": "boolean"
>         }
>       }
>     },
>     {
>       "name": "ingest_source_to_cpg",
>       "description": "Parses raw source code into the Code Property Graph. Deconstructs regular code into its AST hierarchy, Control Flow Graph, and Program Dependence Graph.",
>       "parameters": {
>         "type": "object",
>         "properties": {
>           "file_paths": {
>             "type": "array",
>             "items": {"type": "string"},
>             "description": "List of local file paths to ingest."
>           },
>           "incremental_update": {
>             "type": "boolean",
>             "default": true,
>             "description": "If true, only recalculates the graph for modified files and their immediate dependency radius."
>           }
>         },
>         "required": ["file_paths"]
>       },
>       "returns": {
>         "type": "object",
>         "schema": {
>           "nodes_added": "integer",
>           "edges_added": "integer",
>           "orphaned_nodes_removed": "integer"
>         }
>       }
>     }
>   ]
> }
> ```
>
> also, I realize that the type-strict schema of a locally runnable openjev
> model (https://huggingface.co/openjev/openjev-GGUF, OpenJev-Q4_K_M.gguf) would
> enable simple categoricals and choices on graph-based data. we also have a
> quantized coding agent
> https://huggingface.co/TheBloke/deepseek-coder-6.7B-instruct-GGUF#:~:text=Each%20model%20is%20pre-trained%20on%20project-level%20code,data%20in%20both%20English%20and%20Chinese%20languages.
> finally, we have a web browser scraper capable of extracting simple
> interactive chunk-sets from webpages (in general) that we can apply a general
> text knowledge graph extractor (quantized model) to
> https://huggingface.co/QuantFactory/Triplex-GGUF#:~:text=List%20all%20available%20models%20*%20QuantFactory%2FTriplex-GGUF.%20*,quantized%20version%20of%20SciPhi%2FTriplex%20created%20using%20llama.cpp.
> what I'm wondering is how semantic knowledge graph rag queries could inform
> code autocomplete and prototyping via natural language docstrings and
> code-type wireframes first, then autocompleting each code component. The
> knowledge graph would consist of the code diff knowledge graph, the code
> docstrings (semantic natural language, code documentation), and the original
> semantic knowledge graph from queries on web source chunks. the eip harness
> would be atomized on this simple through-stack chain of components that link
> to other components with a similar structure.
>
> for interconnected through-stacks, agents-as-graph-rag-tools are structured
> for recursive calls on queries to existing and hypothetical through-stack
> agents, which are autonomously constructed upon query fields not resolving to
> encourage agent "freedom of thought". the agent would be the through-stack and
> a system prompt with its various self-harness mcp tool calls enabled and
> integrated directly with their code. This means that agents keep context
> structured to their atomized knowledge-based code harnesses at the quantized
> model level with limited context windows and receptive fields. their
> development space would be isolated to their personal terminals and still able
> to aggregate over local code-knowledge harness bases. so, agent through-stacks
> would be able to develop and debug on their isolated local code artifact and
> remaining knowledge and documentation and experiment with the code component as
> a primary mcp tool surface that calls and experiments through development
> terminals as well. so each agent debugs its local feature/functionality within
> its context and still aggregates global knowledge through self-discoverable
> queries. recursive graph rag tool calls enforce feedback promises on finalized
> artifacts as themselves aggregate of recursive calls over the code graph of
> local knowledge tools that retains through-stacks the ability to accumulate the
> progression of code components back to the base promise type/structure that
> signifies feedback on a validated discovery of code transformation on
> datatypes. the through-stacks integrate the code, documentation, knowledge
> base, and context-wise workflows (debugging, calls, tests, new
> developments/integrations on local components, navigating the web and
> knowledge base and generating new knowledge graphs). each recursive graph rag
> node call is part of the forward-propagating workflow on interconnecting
> through-stacks within their localized contexts of their agents; it's a
> communication link on the knowledge-based dependency graph and so on of the
> overall code workspace itself. what would the design of all of this look like
> in one simple demo code module?

The reader's second pasted message, verbatim:

> thanks. seems like we could improve on the clarity and completeness of the
> full set of originally prompted/described features (we're making positive
> progress thus far) and our meta-harnessing with residual-driven frozen
> bases/dynamic contribution and skeleton/ephemerals. the deterministic
> structure compilation, though, is where our own skeletal/ephemeral
> architecture passes this boundary into a self-propagating recursive call set
> that continues to morph and evolve and may then exhibit some form of
> periodicity by recursive/recurrent calls to new instantiations of
> through-stack agents that are dynamically reconstructed for the various
> skeletal-to-ephemeral graph RAG queries. the promises coincide with queries on
> novel recursive calls on through-stack agents in the code and knowledge graph.
> a prompt is just another input to the same recursive tool call that holds the
> through-stack's context and enables recursive calls to the same tool over
> different graph RAG surfaces on through-stacks, both existing and newly
> constructed. reconstruction and self-repair are also part of the same
> meta-harness for through-stack agents. jev, deepseek-coder, and knowledge
> graph models support the agent's workflow capabilities internally as
> jev-directed workflow calls on the skeleton that pass messages over
> ephemerals to other through-stacks, potentially. promises live at the local
> through-stack mcp tool surface and auto-update. They represent components of
> the tool call's I/O that are built-in to the local code modules and also
> propagate as new features through the through-stack graph.
>
> You may generate as many modules as necesary, taking all my prompts and your
> findings into consideration.

And a moment later:

> please also integrate with other notes on code artifact interactions and
> interfaces per what the PRD has on record

*Note on the pasted assistant replies (NOT authority -- AI-written): they
proposed a "nine-layer through-stack" (model router, receptive field, system
prompt + MCP surface, code artifact, local KG, workflow state, promise,
communication ports, feedback sink), a uniform `WorkspaceNode` openable as a
through-stack, a `Promise<T>` algebra (delegate / resolve / roll_up) with a
base type `ValidatedCodeTransformation` carrying `learned` edges and
`residuals`, a meta-harness (spawn from residual, repair, reconstruct,
structural edits on detected periodicity), and finally a `PluginRegistry`
whose plugins may only fill named slots. Those names are the other
assistant's, not the reader's; where a row below uses one, it is marked as a
reading to be confirmed.*

*Read as (2026-10-18), each item tied to what is already on record:*

*(162) **Web code blocks are code artifacts.** A `<pre>`/`<code>` sample on a
page is one artifact, not syntax-highlighting spans: its text whole, and its
address continued BELOW the `pre` by its own syntax -- the same addressing
`vertiscope/source.py` gives `code://` files (`/module[1]/function[1]/code[1]`,
`G-49`). A hover on it shows the code, never its copy button; an unlabeled
control does not read as the word "button". This is the screenshot's defect
and the "begin" of the request.*

*(163) **One class of code artifact, one interface.** Web code blocks, the
repository and installed packages (`code://`, `G-49`, `G-9`, `T-6`), and code
cells in vault notes (`P-N5`) are chunked, addressed, vectorised (`G-52`:
comments and docstrings only) and SHOWN the same way: the code artifact panel
(`P-C1` viewable and editable standalone, `P-C2` a terminal below, `P-C5` live
deltas) with the code-block toggle that opens a kernel or terminal (`P-N3`).*

*(164) **A Code Property Graph in the store.** Over every code artifact: the
AST hierarchy (CONTAINS), control flow (CFG), data flow (PDG,
DATA_FLOWS_TO), CALLS, IMPORTS and INHERITS -- as property-graph edges with
context (`{line, arg_passed}`), in the same kuzu property graph the trie
already lives in; imports are already links (`G-8`, `G-51`).*

*(165) **Unified-diff upsert from a graph mutation.** A change is expressed
as a mutation of the CPG (ADD_NODE / ADD_EDGE / DELETE_* / MODIFY_PROPERTY),
compiled back to source with `ast` and `difflib`, compile-checked, and
applied as a unified diff -- which is also how `P-C5`'s live module deltas
reach the store and the 3D view.*

*(166) **Three local quantized models with distinct roles.** OpenJEV
(type-strict categorical choices over graph data), DeepSeek-Coder 6.7B
instruct (code), Triplex (text -> knowledge-graph triples over web chunks).
On record already: nomic f16 for embeddings, and Nous Hermes 2 DPO 7B named
for the chat (Addendum I, `L-1`, deferred). Whether the three add to or
replace that choice is to be confirmed.*

*(167) **Natural-language-first prototyping.** Docstrings and code-type
wireframes come first, then each component is completed, informed by graph
RAG over three graphs: the code-diff graph, the docstrings, and the web
knowledge graph (Triplex triples). This meets `G-105` (package chunks as
code prototypes in notebook cells) and `R-5` (one retrieval interface).*

*(168) **Through-stack agents.** An agent is a through-stack: a quantized
model, a bounded context, its own isolated terminal and local code artifact,
and its MCP tools generated from that code. Agents call each other through
recursive graph-RAG tool calls -- existing ones, or new ones constructed when
a query does not resolve -- and each call is an edge on the workspace's
dependency graph. A prompt is one more input to the same recursive tool
call. Promises live at the stack's MCP surface, update with its code, and
roll results up to a base promise: a validated code transformation on a
datatype. A meta-harness reconstructs and repairs stacks; skeleton (frozen
base) and ephemerals (dynamic contribution, messages between stacks) are
kept apart; recurrence of the same stack is detected. To be designed WITH
the reader before code.*

*(169) **Everything is a plugin.** Extensions fill named slots of a stable
core and may only tighten it; removing them leaves the core running.*

And while that was being recorded:

> there was also plans to include our locally installed pypi package base as
> embedded and projected chunks in our 3D graph view. perhaps either umap or
> just force-directed, what form works best for our triple-form knowledge
> graph representation, code docs/code comments, and the code itself.
> multiple edge types and specialized nodes and interfaces per the knowledge
> graph form might be in order.

*Read as (2026-10-18): (170) the installed PyPI package base is in the 3D view
as embedded, projected chunks (on record: `G-9`, `T-6`, `G-104` -- each
package a tree-shaped projection with dependencies variable -> module ->
directory); the layout is CHOSEN for what the view carries -- the
triple-form knowledge graph, the code's docs and comments (the vectorised
surface, `G-52`), and the code itself (not vectorised) -- UMAP,
force-directed, or a combination, decided by measurement; and the knowledge
graph's form gets its own node kinds, edge types and interfaces rather than
everything drawn as one kind of orb on one kind of line.*

The reader, correcting the reading of "triple-form":

> the triple-forms I'm talking about are the two others that accompany the AST

*So (170)'s "triple-form knowledge graph" is the CODE PROPERTY GRAPH's three
structures of (164): the AST, and with it the control-flow graph (CFG) and
the program dependence graph (PDG, data flow) -- not subject-predicate-object
triples. The layout question is: how the AST tree, the CFG's execution order
and the PDG's data flow are drawn together with the docs/comments and the
code, each as its own edge type.*

> empty links on some archive nodes

*(Sent 2026-10-18 with a screenshot: an archive.org search-result tile's
panel -- picture, title, item stats -- with no link to the item.) Read as
(171): a tile is an anchor to its item page, and the panel opened for any
part of it must carry that link; a unit chosen INSIDE the anchor left the
anchor's own href behind. (If the reader meant the 3D view's edges, this
reading is to be corrected.)*

> hovering over non-imaged nodes still blocks un imaged nodes from being
> effectively hovered over their panel previes

> archive org updates may have broken suchunking to some extent

*(Sent 2026-10-18 with a screenshot: on a github README, three hover panels
open at once, each holding ONE bullet of a "Prerequisites" list, the panels
stacked over the graph.) Read as (172): an open hover panel must not stop the
pointer reaching the nodes beneath it -- a preview is not a wall; and (173)
the list-item rule made for archive.org's tiles (an item is the unit however
few lines it has) cut prose lists into one panel per bullet -- a list of
small items is ONE unit.*

> url node centroids seem off in many cases

*(Screenshot: url nodes sitting at the edge of their chunks' fans, not
among them.) Read as (174): a url node stands at the centroid of its
chunks (on record, `G-106`: "its page at the centroid of its chunks").*

> broken chunks spotted on anna's archive

*(Screenshot: a search result's metadata line -- language, format, size,
year -- framed by a chunk box that cuts across the result.) Read as (175):
a result card on annas-archive is chunked across its boundaries; the box
drawn does not match one unit.*

> annas archive re sets from ddos guard

*(Screenshot: the download page behind "Please wait 69 seconds".) Read as
(176): a DDoS-guard check that reloads the page resets the scan; the stream
must survive the guard's reload (the page is the same document once the
check passes).*

Also in this stretch, verbatim, so the record is whole:

> Do this task here: “Fix failing moved-subtree re-address test”

*(Done 2026-10-18, `8a262d0`/`4d50da4`: the receiver refused re-parented
moves; `tests/test_composed_tree.py` 20 pass with two planted arms.)*

The reader's `/compact` request (the command itself failed on a session
limit; its words are direction):

> with a focus on most recent progress on open items on your side, current
> set of open items, new set of directions to add, and a set of priorities for
> different tasks to complete and fully test/validate with your MCP tools for.

> please ensure all recent messages are fully captured

> there isnt a download process for pdfs and subsequent chunking for us and
> there really should be

*(Sent with a screenshot: annas-archive's "Download now" page and a copy
field holding the file's url.) Read as (177): a PDF the reader reaches --
a download link, a file url -- is fetched, kept, and chunked like a page:
its text recursively chunked into the trie under its own url, vectorised
and drawn, with the same panels.*

> also getting 502 on annas archive

> ddos guard on annas archive .pk

*(Screenshots: annas-archive.gl answering "502 Bad Gateway / nginx", and
annas-archive.pk showing DDoS-Guard's "Checking your browser before
accessing".) Read as (178): a server error page and a bot-check
interstitial are page STATES, not the page's content -- they are not stored
as the url's chunks, and the stream resumes on the real page when the site
lets it through (with (176)). The check itself is the site's: the browser
cell runs it as any browser would and nothing here works around it.*

> please ensure to resolve hyperlink tails to their domains. also, what are
> the "inherits" and "calls" buttons for?

*(Sent 2026-10-18 with a screenshot: the transformers quicktour open in the
browser cell, and a streamed chunk's panel reading "run inference with /
/docs/transformers/v5.20.1/en/main_classes/pipelines#transformers.Pipeline /
Pipeline" -- the link's destination shown as the page wrote it.) Read as
(179): a link's destination is shown resolved against its page --
`https://huggingface.co/docs/...`, never a bare `/docs/...` tail -- in every
panel, streamed or stored. The question about the buttons is a defect of the
view: two switches (`calls`, `inherits`, added for `G-241`'s code-graph
edges) stood in the bar on every page, where they switch nothing and nothing
said what they are.*

> layered/nested subchunking error (i think) where hovering over
> sub-components of the same overall chunk only renders those components in
> the same node. also nodal collapse on hovering on other chunks. ensure
> fixes are built and tested alongside the remainder of the trace of our new
> tests and builds. Nodal collapse means hovering over different chunks
> renders really fast and completely when the full-chunk region is hovered,
> however each panel comes from the same node. I'm skeptical as well if you
> also paid attention to some previous prompts in the transcript a few
> compactions ago about making the rendering happen asynchronously *and*
> prior to diff-updated vectorization, so seeing immediate response on
> rendering first and getting vectorization and projection layouts as a
> downstream task that doesn't block immediate diff rendering feedback and
> response, but also serving as the primary step prior to vectorization.
> So, the panels could theoretically render in their gray node layouts right
> out the gate.

*(Sent 2026-10-18 with three screenshots of bandcamp radio: a show card's
panel, and two track rows' panels -- "Majid's Whisper", "Fire! Featuring
Stacy Epps" -- each headed `https://bandcamp.com/radio/1010?from=bc_radio_page
: /`, opened from one place in the 3D view.) Read as (180), three parts:
(a) a hovered part of an item -- a track row's cover, its title block -- is
not a unit; the item is, and every part of it opens the same panel;
(b) each unit's panel leaves from a node of its OWN -- one level below its
chunk, grey until the chunk is stored -- never from a position shared with
the other units of its chunk or its page; (c) rendering is the FIRST step: a
fresh page's chunks are drawn as grey nodes and their panels open from the
sensor's tree before anything is stored, embedded or placed, and those
follow without blocking it.*


Then, while the inventory below was being taken:

> a lot of diff scans not yet at least projected after vectorization

*(Sent 2026-10-18 22:26 UTC, while a verify run and probes were scanning
bandcamp and the Julia forum.) Read as (181): a scanned chunk does not stay
grey -- once vectorized it is drawn at its projected place, and the grey node
it started as goes; nothing is left grey that the store will never place.*

> please cover what's still open. please also take inventory of all my own
> prompts and requirements from this and last week's transcripts to see if
> they've properly been interpreted and landed.

*Read as (182): (a) work the open rows; (b) every message typed since
2026-10-04 matched to where it is recorded, what it became, and whether that
landed -- `docs/PROMPT_INVENTORY.md`, regenerated by
`scripts/prompt_inventory.py`.*

The reader's answers to four questions asked 2026-10-18 (AskUserQuestion),
verbatim:

*Rewritten feed items -- old versions kept as grey nodes the store never holds (G-253):*

> look through our diff, docs, and prompt transcript a little closer to get
> a better understanding of managing uniqueness and diff streaming/updates
> that preserve previous states presented from earlier times should
> sufficient uniqueness constraints hold for the two independently.

*Read as (183): no ruling yet on fade-or-store; first, research how this
codebase -- its git history, its docs, the transcript -- has handled
uniqueness and diff streaming that PRESERVES earlier states, and whether
uniqueness constraints hold for the two (the stream's versions and the
store's addresses) independently; then decide from that.*

*Obsidian's own force graph as a candidate (G-259):*

> evaluate against obsidian, but each for 3D

*Read as (184): evaluate the current 3D view against Obsidian's graph,
each in 3D -- the comparison is between 3D layouts, not Obsidian's 2D view.*

*The labyrintalis push (G-165):*

> Prepare, don't push

*Read as (185): a renamed, scrubbed copy prepared locally for review; no
push.*

*Models and agents (G-237, G-239):*

> we will install the models and begin conceptualizing how to smoothly
> translate from local code to agents with an additional set of interface
> panels in the 3D editor. we might even so as naturally ask ourselves with
> our current plugin design how we would open code from a webpage like
> huggingface for each of the models, and 'installing' them as entities in
> our 3D graph workspace as specialized panel nodes. we'd probably do best
> with building up to these through-stack ideas incrementally within what
> would naturally flow out of the plugin's billboard panel interface design.
> we'd first need to identify a unified way of managing installing and
> running models straight from their web sources in our plugin GUI. getting
> hard type constraints and conventions on various quantized models and
> tasks would then allow us to know how to manage their output artifacts in
> the 3D graph layout. since we are truly trying to capture the essence of
> building workflows with various models and artifacts, i would suggest now
> be a good time to revisit the extent we have rendered knowledge graphs of
> our code and can run code panels before we touch agents. since code and
> workflows are interlaced, I would suggest going through our mothership
> project's design docs (mortegon) and seeing how much of the recursive
> reservoir 2D computation graph editor with dual-panel-graph-view you can
> find. recovering those crucial details is of primary importance to then
> extending on our web navigation to extracting patricia trie patterns from
> pages per their chunk panels but rendered in their graph form, then
> brought in to a 2D graph editor view as well (also showing the dual panel
> and graph views, there's lots of design thought gone into this part),
> where we can then create new nodes as ontologies and aggregates of
> multiple patricia trie paths that themselves access a multitude of pages,
> which then give way to auto-rendered strict pydantic aggregate types that
> are formal data structures that agents can operate on with their various
> workflows and tools/code. since we have three different knowledge graph
> representations of python code, we'd have to design a compact knowledge
> graph that combines from each original type to provide the true overall
> occam's-razor knowledge graph of what the code both is and does. 'a = b'
> would be one triple. so would be package imports. then, the code panels
> from our web scans would go straight to code knowledge graphs, web panels
> would go straight to knowledge graph from our triplex model. a 2d graph
> space, in that case, would be designed around through-stack nodes that
> have their own planning/orchestration, web nav, vector-knowledge graph
> search priorities, and essentially other quantized model calls in
> workflows. for the case of quantized models, their input/output types
> would ideally be strict-native; so parsing rules on natural output formats
> for each type of model: chat models have markdown with some embedded code,
> so it would be a fused/hybrid form of the two knowledge graph types
> described, the triplex model would be knowledge graphs from natural
> language text, and jev nodes would expose the set of input-output types
> per the schemata and design as open in some of the panels in the browser
> webpage currently in our plugin you can access from our MCP. perhaps our
> mortegon docs can help fill us in on some of the blanks here with how code
> and workflows convert seamlessly in graph editors/intracive panels as a
> CAD tool. this is more likely design work in some parts that is to be
> continued and in other parts things we can build in now and directly, like
> the code knowledge graphs and ways of parsing models with types directly
> from the web, installing them (if gguf detected, I'd suppose another
> component of our content detection is special files like .zip, json, .tar,
> .gguf, .csv, etc) and 'rendering them' locally as graph nodes. depending
> on the specialized type of node extracted as a chunk from the web,
> including special files, we standardize interactive panels for each type.
> for tables on pages and csv, we have a simple table view (which we
> currently don't have rendering correctly for one of the open wikipedia
> panels, which can also extend to csvs and the like if detected on pages).
> but more importantly, for various GGUF models, we have these panel
> interfaces that give us access to their strict types and most natural
> style of input/output protocols to the rest of the artifacts in the graph
> (i.e. JEV's output schemas, code input-output datatypes over a black-box
> python module that produce strict types in memory as parts of the overall
> workspace knowledge graph, the triplex model which directly outputs
> knowledge graphs linked to scanned chunks that are force-directed layouts
> without vector embeddings other than what is linked to their source
> chunks). do your best on this and don't give up easily on thinking about
> how to best simplify coding as a 2D graph editing CAD with special
> gestures that embrace collapsion and adaptive localization to black-box
> panels (i.e. a black-box i/o panel is what accompanies these interactive
> entities in our knowledge graph) or otherwise visual computation graph
> design that interlinks semantic web navigation and search with specialized
> interactions on various quantized models that then contribute novel
> artifacts to the same 3D layout. think of what is most guaranteed along
> these lines of thinking, consult our mortegon docs, and see what kind of
> initial and simplest guaranteed's we'd be able to obtain for the *design*
> and some building as well.

*Read as (186), numbered for the rows below it, in the order given:*
*(186a) install the three models and conceptualise local code -> agents
through interface panels in the 3D editor, built up incrementally from the
billboard panel design; (186b) a model is opened from its web page
(huggingface) and INSTALLED as an entity of the 3D workspace -- a
specialised panel node; one unified way to install and run models from
their web sources in the plugin; (186c) hard type constraints and
conventions per quantised model and task, which decide how their output
artifacts enter the graph; (186d) BEFORE agents: revisit how far code is
rendered as knowledge graphs and code panels can be run; (186e) primary:
recover from the mothership project's (mortegon) design docs the recursive
reservoir 2D computation-graph editor with its dual panel / graph views;
(186f) patricia-trie patterns extracted from pages' chunk panels, rendered
as graphs and brought into that 2D editor (dual panel and graph views),
where new nodes are ontologies and aggregates of many trie paths across
many pages, giving auto-rendered strict pydantic aggregate types agents
operate on; (186g) one compact 'Occam's-razor' code knowledge graph
combining the three Python representations (AST, CFG, DFG) -- `a = b` one
triple, an import one triple -- of what code IS and DOES; (186h) web code
panels go straight to code KGs, web text panels to KGs by the Triplex
model; (186i) the 2D space built around through-stack nodes with their own
planning, web navigation, vector/KG search priorities and model calls;
(186j) strict-native I/O per model kind: chat = markdown with code (a
hybrid of the two KG kinds), Triplex = KG from text, JEV = the I/O types
of its schemata, shown in panels; (186k) special files detected as
content -- .zip, .json, .tar, .gguf, .csv -- and rendered locally as graph
nodes, one standard interactive panel per node type: tables (pages and
CSV) in a simple table view -- one open Wikipedia panel renders a table
WRONGLY now -- and GGUF models with their typed I/O; (186l) the black-box
I/O panel that accompanies each interactive entity; Triplex output as
force-directed graphs linked to their source chunks, no embeddings of
their own; (186m) coding as 2D graph-editing CAD: gestures for collapse
and adaptive localisation into black-box panels, a visual computation
graph joining semantic web navigation and search with model interactions
that add artifacts to the same 3D layout; (186n) find the most GUARANTEED,
simplest first steps -- design where it must be, building where it can be
(code KGs, typed model parsing from the web, installing GGUFs, special
files as nodes).*

### Recovered verbatim (2026-10-18 inventory)

*Messages from 2026-10-04 to 2026-10-18 that were acted on but never
transcribed here -- found by the inventory (182). Their words, by UTC time;
where each landed is in `docs/PROMPT_INVENTORY.md`. Recorded late, so no
row decomposed from them could be checked against them when it was written.*

**2026-10-04 19:36**

> Clicking on the node that is scanned does nothing

**2026-10-04 19:42**

> Reverted to light mode for some reason

**2026-10-04 19:43**

> Yes, reinstall CUDA torch and build the central diff object

**2026-10-04 19:46**

> Re-navigating back to a previous page re-spawns existing nodes. This is
> where the patricia trie on the DB is the central spine for chunk handling,
> scanning, and web nave. The 3D layout *seems* to work, but I'd like you to
> verify the findings and research on our UMAP updates per my most recent
> prompt on the chunk-wise per-page UMAP updates on cuda using a global UMAP
> model .

**2026-10-04 19:47**

> Overlays seem too transparent as well on the electron browser

**2026-10-04 19:48**

> Still also seeing no right-click on central url nodes collapsing the
> chunks into the node and expanding the full UMAPped chunk set.

**2026-10-04 19:49**

> Perhaps run some coding agents in parallel for all the task updates on
> these

**2026-10-07 02:04** *(with 1 image)*

> Still no updates rendering on the page side for the panel (image
> attached). I don't think the image panels are rendering either on their
> node billboards.

**2026-10-07 02:04**

> Please make sure the design of the mcp server is also just as observant
> for these kinds of things.

**2026-10-07 02:04**

> And the older dual-panel (more complicated, likely) is still there

**2026-10-07 02:06**

> But yeah also to your point, duplicate image still in that markdown there.

**2026-10-07 02:16**

> yeah, I don't see any diff updates for navigating on this page either, at
> least I don't see nay

**2026-10-07 02:18**

> Scrolls on this page leave stale billboards as well but update immediately
> for mouse movements/new page elements rendering on mutationobservers, if
> that's what our sensor is doing.

**2026-10-07 02:19**

> Also, hovering overlays should zoom-focus the camera in the 3D editor on
> the specific chunk, no matter placement in the diff, with focus persisting
> on force-directed updates.

**2026-10-07 02:21**

> Voronoi diagrams essentially diverge completely from the centroids without
> preserving UMAP geometries. But we need UMAPs to be scaled, perhaps by a
> minimum distance to the center as a threshold, so that our scales aren't
> wacky. Removing voronoi might be the move in place of this.

**2026-10-07 02:22** *(with 1 image)*

> Hovering over the options in the attached image do not produce chunks
> because overlays are missing, another detection issue on shadow nodes and
> nesting, or similar

**2026-10-07 02:24**

> Billboard overlays still lagging inplace (not moving) when scrolling on
> this page. Please ensure to complete all tasks that are still open and not
> just diverging to each ask and point made in specific. Please keep a task
> ledger perhaps.

**2026-10-07 02:24**

> Or otherwise follow the task ledger.

**2026-10-07 02:29**

> Also, the camera doesn't 'fly' for hovering over different chunks and
> zooming the billboards into place. Perhaps also, when this flying happens,
> this also opens the panels on the 3D side, but closes them when the
> hovering stops.

**2026-10-07 02:31** *(with 1 image)*

> Nodes are way too closely packed together now on the UMAP fit

**2026-10-07 02:32**

> Continuous fly-zoom-following still doesn't work. Please also ensure our
> PRD is getting the updates, along with the set of current tasks. I think
> our PRD might be where the new set of tasks are supposed to go. Please
> move them in if so. There might be a more recent document for our purposes
> that tracks our current progress here.

**2026-10-07 02:34**

> Billboards don't close, are *very slow* to render, and don't show anything
> at all. However, flying to nodes works perfectly now. Please ensure you're
> capturing this in our tests along with your fixes.

**2026-10-07 02:36**

> Billboards are slow to close when not hovered. Please make sure that
> you're doing speed profiles and improvements for responsiveness as well,
> and as necessary. Rendering the billboard pages is a little faster but
> could be sped up much more too. This could also be capture in the MCPs for
> observability.

**2026-10-07 02:38**

> Flickering over the GUI now (could be the overlays), and flickering on the
> billboards that try to open when hovered but close, then try again, then
> close.

**2026-10-07 02:38**

> Yeah... Rendering on the billboards can definitely still be sped up more.

**2026-10-07 06:21**

> Recycling-render is still an issue.

**2026-10-07 07:16**

> Archive overlays do exist but are oversized.

**2026-10-07 07:21** *(with 1 image)*

> Still overlay oversizing. Also not sure if the popup chunks are captured
> as well and linked correctly

**2026-10-10 23:38** *(with 1 image)*

> Still seeing overlay degradation

**2026-10-11 05:58**

> obsidian froze

**2026-10-11 06:17** *(with 1 image)*

> frozen again and image hovering stops working in chunk view

**2026-10-11 06:26**

> frozen again

**2026-10-12 03:44**

> exhaustive more results works

**2026-10-12 03:56** *(with 1 image)*

> more jumbling

**2026-10-12 04:10**

> loading's taking quite a long time

**2026-10-12 04:12**

> loading takes several minutes instead of seconds

**2026-10-17 23:13**

> archive still not registering correctly

**2026-10-18 16:22**

> please free up some disk space

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

### Electron as the sensor's host — searched, then measured (2026-09-12)

Addendum II's S-13 question. The search said it was possible; the measurement
said by how much. Findings are in `PLUGIN_PRD.md` §N; what the *search* gave:

- **Playwright drives Electron over CDP**, and can attach to an already-running
  instance launched with `--remote-debugging-port` — the same mechanism
  `obsidian-plugin/cdp.mjs` already uses against Obsidian on 9222.
  [ElectronApplication](https://playwright.dev/docs/api/class-electronapplication),
  [electron-agent-tools](https://github.com/svvysh/electron-agent-tools),
  [electron-test-mcp](https://github.com/lazy-dinosaur/electron-test-mcp).
- **`<webview>` is deprecated in advice if not yet in API.** Electron's own
  docs: *"Chromium's webview is undergoing dramatic architectural changes...
  consider alternatives, like iframe, a WebContentsView, or an architecture
  that avoids embedded content altogether."* This changes what `P-B3`/`P-B4`
  should be built on.
- **`preload` is the sensor's injection point**, not `executeJavaScript`: it
  runs before page scripts, and a fold that must not miss the first mutation
  needs that ordering. `executeJavaScript` on `dom-ready` is re-injection.
- **`session.fromPartition('persist:…')`** is *"profiles from their base"*,
  exactly — an isolated persistent profile per partition string.

### The `[]()` retrieval gesture — the closest prior art (2026-09-12)

[**bbawj/obsidian-semantic-search**](https://github.com/bbawj/obsidian-semantic-search)
is `R-1`/`R-4` already built, with a different trigger: a `LinkSuggest` class
extending Obsidian's `EditorSuggest`, fired by a `{{...}}` pattern, running
semantic search over the text inside the braces and **inserting a formatted
markdown link on selection**.

What that settles and what it leaves: `EditorSuggest` gets the *trigger* and
the *infill* for free, so `R-1` and `R-4` are a known quantity. The work is
`R-2` and `R-3` — results in *scrollable whitespace immediately below the
line*, with the surrounding editor uninterrupted. `EditorSuggest` overlays a
popup; it does not reflow the document to make room, which is what the
requirement describes. The PRD already records that tension in `R-3`; this
confirms the split rather than resolving it.

Also in this space, all embedding-backed inline suggesters worth reading for
the popup mechanics: [semantic-backlinks](https://github.com/brightwav3/semantic-backlinks)
(lexical hits instantly, semantic hits below, snippet preview), the
`Inline Link Suggestions` community plugin (underlines plain-text mentions,
opt-in semantic), and `Smart Connections`.

### Local models inside Obsidian (2026-09-12)

Surveyed for `L-1`, and the conclusion is that none of it is needed as a
dependency: the workspace already runs GPT4All + nomic on CUDA in Python behind
the sidecar, so the plugin's job is to call a local HTTP endpoint, not to host
a model. Read for UI patterns only — `Lantern` (desktop-only, llama.cpp-class
models, a grounded *cited* chat over your notes, which is the closest thing to
`P-N10`'s annotated context), [vault-llama](https://github.com/tomhan518/vault-llama),
[obsidian-local-llm-helper](https://github.com/manimohans/obsidian-local-llm-helper),
`Local LLM Hub`.

### Still unsearched

UMAP inter-spatial normalization; per-package vector partitioning with a
centroid pre-filter; terminal plugins (`P-N2`'s separate pane needs a pty —
nothing read yet); whether any package mirrors Selenium's call surface into a
remote panel (`S-10`) — though §N makes that question smaller, since an
Electron host would not need the mirror at all.
