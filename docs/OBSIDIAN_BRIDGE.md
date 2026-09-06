# The Obsidian bridge

Distilled web chunks as notes in a vault: readable as markdown, clickable as
a surface, and linked to each other by the page's own links so the graph view
shows the web graph.

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
domvec: chunk
cid: c752caf9bae8e0ca
url: "https://books.toscrape.com"
xpath: "/html/body/div/div/div/div/section/div[2]/div"
part: 0
---
- Page 1 of 50
- [[All products Books to Scrape - Sandbox-198e38|next]]

```domvec
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

- `domvec/obsidian/export.py` — chunks to notes, rewriting `[words](target)`
  into `[[note|words]]` wherever the target is a page that was also exported.
  Reports both hits and misses, because a rewrite that resolves nothing looks
  exactly like one that works if only the hits are counted.
- `domvec/obsidian/sidecar.py` — loopback, read-only HTTP. `/chunk/<cid>`
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
  - `retrieval.ts` — the **`/` gesture** through `EditorSuggest`. Typing
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
  - `main.ts` — wiring, five commands, a ribbon icon, settings.

  **Remote media is off by default, and that is a privacy setting rather than
  a performance one.** A distilled page carries tracking pixels and per-user
  asset urls; fetching them from a vault tells those hosts the page was read
  again, at a new time, from a new address. With it off, media draws as a
  captioned placeholder that still says what the picture was.
- `domvec/obsidian/mcp.py` — an MCP server over the same functions, stdio
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

1. **The Selenium port.** Interactions on the surface drive a real browser.
   Read-only by default is deliberate: driving a live page must be an
   explicit choice, never a side effect of opening a note. The surface
   already reports the address it *would* act on, and both the sidecar and
   the MCP server are read-only by construction, so this is the one place a
   write path would have to be added deliberately rather than by extension.
2. **The gesture's links stay web links.** A passage the `/` gesture inserts
   keeps its internal links exactly as the distiller drew them. Rewriting
   them into wikilinks is the exporter's job and it can only do it for pages
   that were exported, which the gesture has no way to know. Wiring the two
   together — the exporter's name map, available to the gesture — is the
   piece that would make retrieval and the graph one surface.

## The projection, and why it is fitted in Python

`domvec/obsidian/layout.py`. The goal states it precisely — bring the
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

It runs in Python because the vectors, numpy and UMAP are already there, and
a projection fitted twice in two languages is two projections. The plugin
renders; it does not fit. The view names the spaces it was given on its own
status bar — a layout fitted on frequency alone and one fitted on both are
different pictures, and a reader who cannot tell them apart will read a
lexical clustering as a semantic one.

## Sources

- [Obsidian developer docs](https://github.com/obsidianmd/obsidian-developer-docs)
- [obsidian-3d-semantic-graph](https://github.com/KHR0907/obsidian-3d-semantic-graph)
- [obsidian-extended-graph](https://github.com/ElsaTam/obsidian-extended-graph)
- [3d-graph (Hananoshika Yomaru)](https://github.com/HananoshikaYomaru/obsidian-3d-graph)
- [vault-mcp](https://github.com/robbiemu/vault-mcp)
