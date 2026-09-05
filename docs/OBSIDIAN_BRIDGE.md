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
- `obsidian-plugin/` — manifest, build, and `src/main.ts`: the code-block
  processor, the markdown/interactive toggle, and the settings tab. Offline
  is a supported mode and says so on the surface rather than rendering as an
  empty chunk.
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

1. **Media billboards.** Images and video are addressed already; the surface
   renders them as text.
2. **The `/` retrieval gesture.** `EditorSuggest` is the hook. The sidecar
   route and the MCP tool both exist.
3. **The 3D view.** `3d-force-graph` + `umap-js`, following
   `obsidian-3d-semantic-graph`. The projection the goal asks for is specific:
   bring the frequency vectors to the semantic dimensionality *first*, then
   concatenate, then one final UMAP — so the two spaces contribute equal
   information rather than whichever happens to be wider.
5. **The Selenium port.** Interactions on the surface drive a real browser.
   Read-only by default is deliberate: driving a live page must be an
   explicit choice, never a side effect of opening a note.

## Sources

- [Obsidian developer docs](https://github.com/obsidianmd/obsidian-developer-docs)
- [obsidian-3d-semantic-graph](https://github.com/KHR0907/obsidian-3d-semantic-graph)
- [obsidian-extended-graph](https://github.com/ElsaTam/obsidian-extended-graph)
- [3d-graph (Hananoshika Yomaru)](https://github.com/HananoshikaYomaru/obsidian-3d-graph)
- [vault-mcp](https://github.com/robbiemu/vault-mcp)
