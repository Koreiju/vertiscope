# The Obsidian bridge

Distilled web chunks as notes in a vault: readable as markdown, clickable as
a surface, and linked to each other by the page's own links so the graph view
shows the web graph.

`PLUGIN_GOAL.md` is the binding statement of what this bridge is ultimately
for — a live minimal browser in the panel, delta-streamed to graph and
database alike — and it wins wherever this design record disagrees with it.

This document records what was verified, the two constraints that shape the
design, and what is built so far.

## What was verified, not assumed

**A plugin can render interactive DOM inside a real note.**
`registerMarkdownCodeBlockProcessor` hands the plugin a live `HTMLElement`
inside an ordinary `.md` file, with lifecycle through `MarkdownRenderChild`
and `ctx.addChild`. DOM the plugin builds is not put through the sanitiser
that strips scripts and handlers from raw HTML written in markdown. So a
chunk can be a real note — which is what the graph view reads — and still
carry buttons that work.

**The native graph view has no plugin API.** The one community plugin that
extends it, `obsidian-extended-graph`, patches undocumented internals and
warns in its own README that graph settings can be lost and that rapid
interaction raises async errors. So the bridge does not touch it. Real
wikilinks in real notes make the native graph work with no plugin code at
all, and the 3D view owns a scene of its own.

**Obsidian parses links only in prose.** A link indented four spaces is
inside a code block and contributes nothing. This is not a footnote — see
the defect below.

## The two constraints

**Privacy.** `Workspace.mirror_path` names its files by digest on purpose:
"a listing that names the pages is the browsing history in plain sight." A
vault is precisely the opposite — a listable directory of readable names,
displayed by name in the graph. The export therefore reverses a deliberate
decision, so it is opt-in and the caller names the pages. It never walks the
workspace by default, and the sidecar binds loopback only, is read-only, and
does not log request paths.

**The note is a rendering, not a source.** Everything in a note is derived
from a `StoredChunk` and can be regenerated. The fence carries only a `cid`;
the plugin looks the rest up. A note that carried its own copy of the chunk
would drift from the store the moment either changed.

## Shape of a note

```markdown
---
vertiscope: chunk
cid: c752caf9bae8e0ca
url: "https://books.toscrape.com"
xpath: "/html/body/div/div/div/div/section/div[2]/div"
part: 0
---
- Page 1 of 50
- [[All products Books to Scrape - Sandbox-198e38|next]]

```vertiscope
cid: c752caf9bae8e0ca
```
```

The prose carries the graph; the fence carries the payload. That split is
forced by where Obsidian parses links.

## The defect this design already caught

The first working export produced 98 notes and 7 wikilinks and looked
finished. It was completely broken.

The renderer indents by DOM depth, so a chunk rooted a few elements down
opens at column 10. In CommonMark any line indented four or more spaces is an
indented code block, and Obsidian parses no links inside one. **82 of the 98
notes had a body that parsed as code, and all 7 wikilinks were unreachable.**
The graph would have shown 98 disconnected dots while every file looked right
in a text editor.

`_reflow` re-indents by nesting *level* at two columns per level, so the
hierarchy survives and the markdown stays list nesting. Verified with a real
CommonMark parser rather than an indentation heuristic — the heuristic was
over-strict and called two perfectly reachable links buried, which is its own
lesson: four spaces *inside a list* is nesting, and only four spaces
*starting a block* is code.

`tests/test_obsidian_export.py` asserts the property through the parser.

## Built

- `vertiscope/obsidian/export.py` — chunks to notes, rewriting `[words](target)`
  into `[[note|words]]` wherever the target is a page that was also exported.
  Reports both hits and misses, because a rewrite that resolves nothing looks
  exactly like one that works if only the hits are counted.
- `vertiscope/obsidian/sidecar.py` — loopback, read-only HTTP. `/chunk/<cid>`
  returns each line with its **address key**, render class and control flag;
  `/search?q=` is the `/` gesture's backend. The address is sent, not just
  the text, because the address is what lets a click in Obsidian name an
  element in the real page.
- `obsidian-plugin/` — manifest, build, and ~690 lines of TypeScript:

  - `types.ts` — the contract with `sidecar.py`. One file, because a field
    renamed on one side and not the other fails silently at runtime with an
    empty surface.
  - `sidecar.ts` — the client. Every method answers `null` rather than
    throwing: offline is a supported mode, and the surface says so instead of
    rendering as an empty chunk.
  - `surface.ts` — the chunk as something to look at and press, including
    **media billboards**. The distiller already draws `![alt](src)` with the
    page's own alt text, never the file name, so a billboard has a caption
    without guessing one.
  - `gesture.ts` + `linkgesture.ts` — **the `[]()` gesture, the retrieval
    interface** (`R-1`..`R-4`; the reader: *"all retrieval comes from the
    singular `[]()` interface"*). Typing `[query]()` in any note makes the
    bracket contents a query against the one `/search` ranking -- web pages,
    vault notes and source files together. The results open in a CodeMirror
    6 **block widget** under the line, so the lines below move down and stay
    editable (an `EditorSuggest` popup would cover them, which is why it is
    not used here); the list scrolls and pages as it nears its foot; a click
    infills the link between the parentheses -- a vault note's path, an
    exported page's note, else the page's address. Live check `R-3`.
  - `retrieval.ts` — the older **`/` gesture** through `EditorSuggest`, kept
    until the reader rules on it (`R-5`: it is a second retrieval surface
    beside `[]()`). Typing
    `/some query` offers the workspace's own chunks, ranked by three-form
    retrieval, and inserts the chosen passages inline with rules between
    them. What it inserts is ordinary markdown, which is the whole reason for
    doing it through the editor rather than a panel: the passage becomes part
    of the note, the note is a file, and its links are links the graph already
    understands. Retrieval that renders into a side panel leaves nothing
    behind.
  - `graph.ts` — the **3D view**, an `ItemView` of its own drawing
    `3d-force-graph`. Nodes are pinned at the fitted coordinates (`fx/fy/fz`)
    and the simulation is cooled immediately: running forces on top would
    drift the points off the embedding and quietly turn a UMAP of two vector
    spaces into a spring layout that happened to start there. Clicking a node
    opens the exported note, matched on the `cid` in frontmatter rather than
    the file name, because the exporter names notes for their first words and
    two chunks can begin the same way.
  - `vaultlinks.ts` — the passage's links become **vault edges**. Two things
    have to line up and neither is guessable from the passage: which chunk a
    link to a page lands on, which the sidecar reports from the exporter's own
    rule rather than the plugin reimplementing it; and which note holds that
    chunk, which only the vault knows, so the map is built from the notes
    themselves keyed on the `cid` the export writes into frontmatter. A target
    that was never exported is left as a web link — a working web link beats a
    wikilink to a note that does not exist, which Obsidian draws as a dangling
    node nobody can open.
  - `main.ts` — wiring, five commands, a ribbon icon, settings.

  **Remote media is off by default, and that is a privacy setting rather than
  a performance one.** A distilled page carries tracking pixels and per-user
  asset urls; fetching them from a vault tells those hosts the page was read
  again, at a new time, from a new address. With it off, media draws as a
  captioned placeholder that still says what the picture was.
- `vertiscope/obsidian/mcp.py` — an MCP server over the same functions, stdio
  JSON-RPC with no SDK dependency. `search`, `chunk`, `affordances`,
  `resolve_address`, `pages`. It deliberately does **not** expose note
  reading or writing: the vault already has an MCP server for that, and two
  would be two sources of truth for one set of files. It exposes what only
  the distiller has — the address trie, the three-form retrieval, and the
  affordances at a chunk. Read-only: `affordances` reports what could be
  pressed and the address that names it; pressing is not wired, because
  driving a real browser from an agent loop should be an explicit choice with
  its own gate rather than a capability arriving quietly beside search.

## The affordance defect, found and fixed here

The interactive surface is only worth switching to if it knows what is
pressable, and it did not. `interactive.links` is in `_SUPPRESSED_TAGS` for a
sound rendering reason — an anchor also yields its href and its words, so
drawing its control unit too would print `[a]` beside them — but
`_render_unit` suppressed by returning `None`, and a unit that draws no line
leaves no address. Suppressing the *rendering* silently discarded the
*address*, which is the only thing that says a line can be pressed.

Over the 136-page corpus: **89.8% of anchor affordances lost**, against 0.2%
of inputs and 0.1% of forms — which have no competing unit to be suppressed
in favour of. Anchors are 88% of every affordance, so the total was 79.6%.

`_carry_affordance` fixes it as a post-pass, and the numbers are now 0.4% and
0.6%. On the toscrape workspace the sidecar's controls by class went from
`group 54, button 51, link 0` to `link 113, group 54, button 51`, with chunks,
addresses, anchors and **link edges all unchanged**.

The first attempt promoted the control into `line.address`, which reads
better and broke the crawl: that slot is the only address the store keeps per
line, and `links_from` reads it back to build the frontier, so a page full of
anchors produced nothing. The affordance is therefore *carried* in `inline`,
and the sidecar finds it through `addresses_at(element)` rather than through
the line's stored address. Full write-up in
`notes/observations/2026-09-05-anchor-affordance-vanishes.md`.

Measured on a six-page toscrape workspace: 98 notes, 7 vault edges, 335 links
left pointing at the web (targets never scanned), 0 links buried in code.

## Open, in the order it matters

1. **Endpoint features offline.** A chunk is a readable, pressable surface,
   but not a self-contained runnable one: pressing a control still needs the
   sidecar, and anything live needs a browser. What works with no network at
   all is reading, retrieval and the graph.

Closed since this list was written:

* **Embeddings.** `index.embeddings` was `None` on every workspace built so
  far, so the layout ran frequency-only and reported `equalised: false`.
  Nothing was broken and nothing was missing: `Workspace.__init__` takes
  `embedder=None`, and nobody had passed one. `scripts/build_vault_workspace.py`
  does, and `flush_vectors` — the single write-side call, run once per
  completed page by design — fills the matrix.

  The cost is real and worth writing down. Chunks at the token window are
  full-length forward passes for nomic: 0.83s each on CPU against 0.27s on the
  GPU, which over this corpus is the difference between half an hour and an
  hour and a half. The embedder sits on the ingest path deliberately ("batch,
  not per-delta"), so the embedder's speed *is* the build's speed.

## The window was measured in the wrong unit

`context_window` was 1200 and nothing said what of. It was **characters** —
about 400 tokens — while every consumer downstream measures in tokens: an
embedder's input limit, a model's context, the budget a retrieval hit has to
fit into. So the knob that decides how much goes in a chunk was denominated in
a unit nothing downstream uses, and was about a twentieth of any real window.

`vertiscope/tokens.py` owns the unit now, and the count is over the **markdown
rendering** — the string the chunk actually becomes, link syntax and
indentation included — because that is what gets embedded, stored and served.
A budget enforced on one string and spent on another is not a budget. All
three measures now come off that same string: the token count, the frequency
vector (`freq.add(cid, chunk.markdown)`), and the semantic vector.

Three sites had to agree, and the third is the one that would have failed
quietly: `_render_sized`, `_emit_runs` (whose per-line cost was
`len(text) + 2 * depth`, a different unit summed against the same window), and
`_memo_key`, which now carries the unit — a cached character count served to a
token window makes every chunk three times too big and raises nothing.

`sensor.js` keeps its **character** budget: it pre-splits inside the page, and
a BPE tokeniser is not something to ship into one. `tokens.sensor_budget`
converts, so the two cutters still cut at the same granularity.

Measured over 40 corpus pages:

| | chunks | median tokens | fill of a 2048-token window |
|---|---|---|---|
| before (chars/1200) | 13,112 | 171 | 8.3% |
| after (tokens/2048) | 2,119 | 1,236 | 60.4% |

Not 100%, and it should not be: the chunker cuts at element boundaries and at
content-defined ones, so a chunk ends where its content ends or where the
window stops it, whichever comes first. What changed is that the window is now
the thing that stops it.

The note's frontmatter and the chunk payload both carry `tokens`, and the
surface's bar shows the fill. A number nobody can see is a number nobody
checks — which is how a window twenty times too small survived this long.

## The other form: distilled HTML

The vault had only the markdown form, so the surface **reconstructed** its
widgets: a `<button>` existed because a regex matched `( Add to basket )` in a
rendering. That works, and it is a reconstruction.

`vertiscope/obsidian/htmlform.py` is the form the goal also asks for — "a more
pure html extension to render original web content directly but still in
distilled, organized, and slim minimal-html chunks, where we can keep the
interactive and the static/media asset components". An `<input>` is an
`<input>` because the trie says the element at that xpath is a control, and
every element carries its own `url:xpath:taxonomy:content` address in
`data-vertiscope-address` — so a click maps back through the patricia trie to the
element the sensor found, not to the line the render drew.

**One payload, two forms.** This reads the very lines the markdown surface
reads, so a chunk cannot say one thing in markdown and another in HTML. They
travel together in one `/chunk` response for the same reason: two round trips
would let a surface hold two renderings of possibly two states.

**Untrusted by construction.** The content is scraped from the open web and
this HTML goes into a real, *unsanitised* DOM — the property the whole design
turns on, and it cuts both ways. So the tag set is a closed whitelist, every
text node is escaped, no attribute is copied from the page, and `_safe_url`
refuses every scheme but http/https/mailto and site-relative paths. The test
asserts against the **parsed tree**, not the string: `onerror` inside
`&lt;img src=x onerror=…&gt;` is escaped text a reader sees, not an attribute
a browser runs, and a substring search cannot tell those apart.

### Two media defects it exposed

Building it made both visible, because both produce markdown that reads fine
and HTML that cannot work.

`_join_inline`'s "a picture is not a sentence fragment" guard tested the raw
tag against `_OBJECT_CLASSES`, which holds the **sensor's** spellings (`image`,
`media`). The tagger names the same element `media.images`, so the guard never
fired for anything the tagger found — and an `<img>` yields two units at one
element (its tag-name fallback `img`, and its `src`) which share a tag and a
flow owner, with a relative `src` that `_looks_like_url` says no to. They
joined. Every tagger-found picture drew as `![images](img media/cache/….jpg)`:
a target with the element's name glued to the front, which is not a url and
cannot be fetched. It is asked of `render_class` now — "is this an object
rather than prose" is exactly what the eighteen classes answer, which is the
case that property's own docstring says to use it for.

And the caption named the taxonomy rather than the picture. An `<img>` carries
its `alt` as a `text.accessible` address at the same element, already sitting
in `text_at`, so "A Light in the Attic" was there while every picture on the
page drew as `![images]`.

| | glued/unfetchable src | captions in the page's own words |
|---|---|---|
| before | 71 | 0% |
| after | 0 | 42% |

The remaining 58% are pictures the page gave no alt for.

## One link, one edge

The gesture and the export both rewrite the same links, so they must land on
the same chunk. If they disagreed, a page linked from an inserted passage and
from an exported note would draw two edges to two chunks of one page, and the
graph would say something untrue about the web.

So the rule — a link contributes ONE edge, to the target page's first chunk,
which is what the store itself does — lives in `export.py` next to the export
that established it, and the sidecar serves it at `/links`. The plugin asks.
`test_link_targets_name_the_same_chunk_the_export_linked_to` reads the notes
the export actually wrote and checks every one it linked to is a chunk
`link_targets` names, rather than calling the helper twice and comparing it
with itself.

## The Selenium port

Pressing a control in a note presses it in a real browser. This is the only
write path in the bridge, and it is built so that "everything else is
read-only" stays true rather than becoming a thing that used to be true.

**Four gates, each because the one before it is not enough.**

1. **The server flag.** `serve(..., enact=True)`, from `--enact`, off by
   default. A plugin setting cannot be the gate: that is the client asserting
   something about itself, and the client is a page renderer inside an app
   the user installs plugins into. The process that owns the browser decides,
   and `/health` advertises the answer so the surface draws a read-only chunk
   as read-only instead of offering a button that 403s.
2. **The refusal set.** `live._refuse_check`, mirrored from `sensor.js` and
   tested against it — sign-in, checkout, delete, publish, send, consent. It
   raises rather than returning a no-op, for the reason recorded there: "a
   model that cannot tell a refusal from a completed action will believe it
   signed in."
3. **The address, not a selector.** A caller names a
   `url:xpath:taxonomy:content` address the store already holds. No arbitrary
   JavaScript, no arbitrary selector, no url the workspace never scanned. The
   patricia trie is the vocabulary of what can be touched.
4. **The fold, not the live DOM.** The element is found in the fold the vault
   was shown, via the REPL's own `_find_by_xpath`. A selector resolved fresh
   against the live DOM can name an element the fold never had — an overlay
   that appeared since, a consent wall — and then the surface and the action
   are discussing two different pages.

**Nothing that can be decided from the request alone may have a side effect.**
The refusal check and the argument validation both run before the driver is
acquired. An earlier ordering had them after, so refusing a sign-in link still
opened Firefox and loaded the page it was on — the refusal held and the harm
it exists to prevent had already happened — and `type` without text booted a
browser to be told so. `tests/test_obsidian_enact.py` asserts the ORDER, and
runs in 2.6s with no browser at all; if the ordering regresses those tests
fail rather than passing slowly.

Verified end to end in the running app: a control in `pages/Travel-632b38.md`
drove Firefox to the books.toscrape sandbox, found the element by xpath in the
fold, clicked it, and reported `did: press, detail: clicked` with the landed
url. The gate was then closed again; the sidecar runs read-only by default.

**One defect only the real app could show.** With the gate shut the plugin
reported "no answer from the sidecar" while the server was healthy and had
written a perfectly good 403. Obsidian renders from `app://obsidian.md`, so a
POST with `Content-Type: application/json` is cross-origin and NOT a simple
request: the browser sends an `OPTIONS` preflight first,
`BaseHTTPRequestHandler` answered 501 to a verb it had no handler for, and
`fetch` rejected before the POST was ever sent. GETs had worked from day one
because they are simple requests. The Node harness has no origin and no
preflight, so it could never have caught this.

### Shadow DOM, and why not an iframe

The distilled HTML renders into a **shadow root**, not into the note's own
tree and not into an iframe.

Not the note's tree, because this markup is a *web page's* structure and a
note is a styled document. Dropped in plainly it inherits every markdown rule
the theme has — paragraph spacing, list bullets, link colours, heading scales
— so a distilled page comes out looking like an essay about itself rather than
like the page.

Not an iframe, and this is where the ecosystem's answer and ours part company
for a reason worth recording. Obsidian has several plugins that render HTML in
notes — HTML Embed, HTML Viewer, HTML Docs, Polyglot Renderer, HTML Preview —
and they all sandbox in an iframe. They have to: they take *arbitrary* markup
from the user's vault, and arbitrary markup carries scripts. HTML Blocks is
the exception and it uses a shadow root per block, for exactly the style
reason above.

Ours is neither arbitrary nor scripted. `htmlform.py` emits a closed tag
whitelist with every text node escaped, no attribute copied from the page and
no scheme but http/https/mailto. So an iframe's isolation buys nothing here
and costs the two things that matter: our listeners could no longer reach the
elements to wire trie addresses to them, and Obsidian's own CSS variables
would not reach in to make a control look native. Custom properties *do*
inherit across a shadow boundary, which is what lets `SHADOW_CSS` be written
in `--text-muted` and friends and still follow the reader's theme.

**Completely private, and that is a property of the design rather than a
setting.** The sidecar is loopback-only, the notes are files, retrieval and
the graph run against the local store, and the distilled HTML fetches nothing
— its one outbound request is a picture, off by default. Nothing here needs
the internet except the scan that produced the corpus and, if the reader turns
it on, the pictures.

### The panel, and what sits at the top of it

The `vertiscope` fence is now the **first** thing in a note, where the properties
block used to be. It was last, which put the panel below however much prose
the chunk held — and Obsidian renders a reading view's sections lazily, so on
a long note the surface did not mount at all until someone scrolled to the
bottom.

The properties block itself is hidden (`propertiesInDocument: hidden`, the
vault setting Obsidian's own Appearance pane writes). The frontmatter stays —
`cid` is what the graph, the link map and the chunk pane resolve on — it is
just not drawn.

At the top of the panel is a two-state switch between **markdown** and
**shadow DOM**. Both states are shown with the live one marked, rather than
one button labelled with the other state: a lone button reading "markdown" is
ambiguous exactly where it matters, since it can equally mean "you are looking
at markdown" and "press for markdown", and a reader cannot tell which form is
on screen without recognising it.

### Cohesive structures

A group holding one picture and something to say about it is drawn as a
**card** rather than as stacked lines. A result row, a product tile and a
profile are all a picture with a title and a price and a button that belong
together, and four stacked lines lose the one thing the page's layout was
saying.

This is why `_Builder` holds a tree rather than a string of open and close
tags: a group cannot be classified until its contents are known, and a string
builder has already emitted the opening tag by then.

There is no geometry involved and there could not be — the sensor deliberately
captures none (`test_no_box_geometry`). What stands in for it is containment:
the distilled tree's nesting *is* the page's grouping, and the record rule
above now makes each of those groups a chunk of its own, so a chunk arrives
already localised to one cohesive thing.

## The projection, and why it is fitted in Python

`vertiscope/obsidian/layout.py`. The goal states it precisely — bring the
frequency vectors to the semantic dimensionality *first*, concatenate, then
one final UMAP — and the precision is the point. Tf-idf over a corpus is tens
of thousands of columns against a 768-wide embedding, so concatenating raw
hands the distance function to the lexical space by sheer count: the semantic
half would contribute about one part in fifty of every distance, and the
result would be a tf-idf layout with a rounding error in it. It would still
look exactly like a layout.

Three things had to be true, and only the first is what the goal says out
loud:

1. **Equal dimension.** Both halves reduced to the same width.
2. **Equal weight.** Equal dimension is not equal weight — a 768-wide tf-idf
   projection and a 768-wide embedding need not have the same magnitude, so
   each half is L2-normalised before the join. One line, easy to omit,
   impossible to notice missing.
3. **A width both sides can actually reach.** Truncated SVD cannot return
   more components than the sample count supports. Reducing the lexical side
   *towards* 768 and calling it equal gave 97 against 768 on a 98-chunk
   workspace — the same lopsidedness pointing the other way — and asking the
   embedding for 75 on a three-chunk workspace gave 2 against 75, a third
   way to get it wrong. The width is the minimum of both sides **and** the
   rank bound, so both reductions can deliver what they are asked for.

`halves.equalised` is asserted from the measured widths, not from the
intention. The first version reported `True` while doing (3) wrong.

### Six dimensions: three to stand in, three to be a colour

The fit is 6D. Three components place the node; three become hue, saturation
and value. Colour was a hash of the host, which is a **legend** and not a
measurement — it said which site a node came from, which the node's own label
already said. Spending three of the projection's dimensions on it means the
colour carries directions of the joint space the three spatial axes had no
room for, so two nodes that look alike are alike in a part of the space the
camera cannot show.

One fit, not two. A colour from a separate projection would be an unrelated
picture painted on top of the first, and two nodes sitting together would
carry unrelated hues for no reason a viewer could read.

Saturation and value are held inside bands (0.35–0.85, 0.45–0.95) rather than
mapped across their full range: a component landing at zero paints a node
black or grey — invisible against the pane, and indistinguishable from a node
the fit failed on. The bands keep **order**, which is what a viewer can read
off a colour, and give up only the two extremes nobody can see anyway.

Writing the test found the same class of defect this module keeps catching.
Neither reducer returns more components than the data has rank, so a
four-chunk workspace yields three however many are asked for — and `_umap`
padded the shortfall with columns of zeros. Colouring from those put every
node at hue 180 (the middle of the band, where `_hsv` sends a component with
no spread) while the report still said `hsv: true`. A constant colour claiming
to be a measurement is worse than the host palette, which at least says what
it is. `_umap` no longer pads; `fitted_dims` reports what came back beside
`requested_dims`; the colour is dropped when the fit could not produce it, and
the status bar says which of the two the reader is looking at.

Nodes also report their first picture, absolutised against the chunk's own url
— a viewer resolving a relative path would resolve it against the vault — so
the 3D view billboards a chunk with the thing it showed instead of drawing a
dot for it. Only fetched when the reader has remote media on: a graph that
quietly pulled a few hundred images the moment it opened would be the loudest
possible version of what that setting exists to prevent.

### Clicking a node

A node stands for a chunk, so clicking it opens **that chunk** — in its own
pane, as structured markdown or as the interactive HTML. It used to open the
exported NOTE, which is a page of a vault: frontmatter, the distilled
markdown, a fence, and whatever the reader has since written around it. The
note is still one button away, in the pane's own bar. One pane, reused —
opening a tab per click buries the graph you are clicking within a few nodes.

It runs in Python because the vectors, numpy and UMAP are already there, and
a projection fitted twice in two languages is two projections. The plugin
renders; it does not fit. The view names the spaces it was given on its own
status bar — a layout fitted on frequency alone and one fitted on both are
different pictures, and a reader who cannot tell them apart will read a
lexical clustering as a semantic one.

## Running it

The vault is the vertiscope repo itself, already registered with Obsidian. The
plugin installs into `.obsidian/plugins/vertiscope-bridge/` (gitignored) and is
enabled in `.obsidian/community-plugins.json`.

```
python -m vertiscope.obsidian export --workspace build/vaultws --vault .        --folder pages --all-pages
python -m vertiscope.obsidian serve  --workspace build/vaultws --port 8787
```

### Driving the real app

**Never by screenshot.** A screenshot answers less than the app can be asked
directly -- it shows what a pane looks like, not whether the plugin loaded,
which commands registered, or how many links the app actually resolved -- and
it captures whatever else is on the screen. Two of them here took in a private
browser window before the approach was abandoned.

**The devtool: `obsidian-local-rest-api`.** Installed into
`.obsidian/plugins/`, enabled, loopback HTTP on 27123 (rather than its
self-signed HTTPS port, which forces every client to skip verification), and
registered with Claude Code as an MCP server:

```
claude mcp add --transport http --scope local obsidian-vault        http://127.0.0.1:27123/mcp --header "Authorization: Bearer <key>"
```

Local scope, so the key stays out of the repo. It exposes `/vault/`,
`/commands/` and command EXECUTION over REST, and an MCP endpoint with
resources and tools.

`obsidian-cli-rest` ("REST and MCP server") was tried first and removed. Its
`search` tool works, but `execute` shells out to an `obsidian` CLI binary and
looks only at POSIX paths, so on Windows every call returns
`spawn obsidian ENOENT` -- and it surfaces that as an error in the GUI. It
also wants port 27124, which collides with local-rest-api's HTTPS port.

**Launch Obsidian for in-app runs with the window unthrottled.**

```
Obsidian.exe --remote-debugging-port=9222 --disable-backgrounding-occluded-windows --disable-renderer-backgrounding --disable-background-timer-throttling
```

Chromium throttles a window it considers covered to ONE frame a second, even
when it reports itself visible and focused -- and with the frames go the
timers and the 3D layout's simulation. Measured 2026-09-27: 984-1027 ms per
frame with Obsidian behind another window; `setBackgroundThrottling(false)`
did not help; these flags did (4 ms frames). A run on a throttled window
scores the throttle (D-35's hover took 5.2 s, G-94 measured a layout that
had settled for six ticks), so every fresh run now records its frame rate in
its label.

**The fallback: `obsidian-plugin/cdp.mjs`.**

It evaluates JavaScript inside a running Obsidian.
Launch it with `--remote-debugging-port=9222` and the renderer -- where `app`
lives -- is reachable over the Chrome DevTools Protocol. No plugin, no
dependency: Node has a built-in `WebSocket` and CDP is JSON over one.

```
node cdp.mjs "app.plugins.enabledPlugins.has('vertiscope-bridge')"
node cdp.mjs --file probe.js
```

This is a far better instrument than a screenshot. A screenshot shows what a
pane looks like; this says whether the plugin loaded, which commands exist,
what the view rendered, how many links Obsidian actually resolved, and what
threw. Screenshots were tried first and abandoned: they answer less and they
capture whatever else is on the screen.

**Restricted Mode is the thing that blocks an install.** Writing
`.obsidian/community-plugins.json` is not enough — Obsidian read the manifest,
listed the plugin as enabled, and still loaded nothing, because community
plugins were off for the vault. `app.plugins.isEnabled()` reports it and
`await app.plugins.setEnable(true)` turns it on.

### Running the plugin headless

`obsidian-plugin/harness.mjs` runs the BUILT plugin outside Obsidian against a
live sidecar: it stubs the `obsidian` module, loads `main.js`, and drives the
code-block processor, the retrieval gesture and the link rewrite for real.
`npm run harness`. It cannot check rendering, layout or the WebGL scene --
those still need the app -- and its stubs are a reading of the docs, so a
wrong stub hides the bug it was meant to catch.

Three defects it found on its first run, none of which types or the Python
tests could have seen:

* **Dot-prefixed notes were invisible.** A chunk whose first words are a
  relative url named itself `.. .. static oscar js bootstrap.min.js`, and
  Obsidian ignores dot-prefixed files outright. Two of the ninety-eight notes
  were written, indexed by nothing, and unreachable — while the export
  reported ninety-eight.
* **The sidecar refused connections in a burst.** `socketserver` defaults
  `request_queue_size` to 5, and a vault opens many chunks at once. One
  request in nine came back `ECONNREFUSED`.
* **The client gave up on the first failure.** One refused connection made a
  surface say "sidecar unreachable" and keep saying it, while every other
  surface on screen worked. It now retries once, and only on a thrown error —
  a 404 for a cid the store does not have is an answer, and asking twice makes
  it no truer.

Two more that only the running app could show:

* **Relative links became dangling graph nodes.** Obsidian treats
  `[words](relative/path)` as an INTERNAL link, so a page's own hrefs arrived
  as links to vault files that do not exist: **13 real edges and 263 dangling
  ones**. Some resolved by accident — `docs/index.html` matched
  `obsidian-plugin/node_modules/polished/docs/index.html`, so a book catalogue
  linked into a javascript dependency, an edge that is not merely useless but
  false. Unresolved links are now made absolute; dangling went to **0**.
* **Render marks leaked into control labels.** A form's button read
  `=== form ===` and a button would have read `( Add to basket )`. The marks
  are what the distiller draws to SAY a thing is a control, and the surface
  re-adds its own; the REPL strips them for the same reason.

### Verified in the running app

```
pluginLoaded       true          pageNotes       98
restrictedModeOff  true          resolvedEdges    7   (== the export's count)
commands              4          danglingLinks    0   (was 263)
sidecarAlive       true          graph  98 chunks · frequency · not equalised
```

## Sources

- [Obsidian developer docs](https://github.com/obsidianmd/obsidian-developer-docs)
- [obsidian-3d-semantic-graph](https://github.com/KHR0907/obsidian-3d-semantic-graph)
- [obsidian-extended-graph](https://github.com/ElsaTam/obsidian-extended-graph)
- [3d-graph (Hananoshika Yomaru)](https://github.com/HananoshikaYomaru/obsidian-3d-graph)
- [vault-mcp](https://github.com/robbiemu/vault-mcp)
