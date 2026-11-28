# The computation graph editor — consolidated specification (draft 1)

*Started 2026-11-21 for PLUGIN_GOAL item 166 (f): "begin thinking about how we
should be consolidate our design specifications and plans, documenting
everything precisely and carefully with our existing verbatim transcripts."
This is that first step: the record gathered in one place, the existing
designs mapped against it, what 166 changes measured, and what is open. It is
NOT yet the "much more complete and self-consistent 2D computation graph
interface design" -- that comes after, from this, plus web research (166 f).*

**Authority.** Only the reader's own words bind: `PLUGIN_GOAL.md` (and, for
the sensor, `AFFINE_MAP_GOAL.md`). Every other document cited here --
including this one -- is a reading. Item numbers in `PLUGIN_GOAL.md` restart
in each dated series, so every citation below carries its date:
`(2026-11-01) 62` is not `(2026-10-11) 62`. §12-§14 are the exception: they
cite the latest series by bare number, under the rule at §13's head.

> **193 and 194 (2026-11-24) bear on most of §12-§13 (F-118, F-129).**
> 193: "you're totally overdoing the work required for the markdown panels".
> A panel is a plain Obsidian note, rendered natively; the purple `{ref}`
> chips go; a Python cell is Obsidian's own code block; one "interface"
> generalizes every canvas type. 194: "the suggestions can override our
> syntactic treatments as well in our custom markdown panels, since we then
> offload that to code cells ... that still run and compile on the
> reservoir in the 2D editor". My reading of 194 answers the links
> question: links are compiled, from code cells (def/use), as 136 and T-4
> ruled. The custom syntax is a "nice to have", not required.
> - **Withdrawn**: the slate's markdown syntax as the editor's grammar --
>   chips and field rows (§12b-§12c), §13h's search node as a slate field,
>   the fence-line `{ref}` across notes (§13d, O-6), G-401's fields and what
>   seeds them (O-10); and the slate dialect §5, §11b and §11c build on
>   (mortegon T.5's "in-text ... specialized editor-specific syntaxes",
>   N.10's `{ref}`, G-379), which 194, the later word, overrides. Kept as
>   found in the code until the reader confirms
>   this reading; nothing deleted yet.
>   The cockpit (`ego.md`) is itself a slate in that dialect, and its
>   fields drive the search (G-372) and the view. Whether it becomes code
>   cells too is part of the same confirmation (F-133).
> - **Stands**: the node editor over CODE cells (§13d'-§13g, G-409, G-411,
>   litegraph, O-1). 194 (g) keeps "our findings on graphical code design
>   interfaces with our package research" beside the live objects (187:
>   G-408, G-410, G-412, G-413). O-5, O-7, O-8 and O-11 stand.

>
> **Calls made 2026-11-24 on the reader's leave ("use your best judgement"):**
> 194 as read: new compile and link work lives in code cells (G-380's
> dataflow); the cockpit stays a slate, drawn plain (G-415), so search and
> view keep working. 193 (b)'s `#` query is not adopted: an Obsidian tag
> stops at the first space, so only one word would be highlighted, and
> every real tag would fire a search; `[query]()` stays the gesture. O-5:
> records and readouts cross notes, live values stay per note. O-11: an
> unnest stays read-only; 166 holds until an unnest is built. G-416 (two
> embeddings, one over interface types) is built (G-416). 194 (f), composing
> a group into a new thing, is `commit` (G-386, seen live); its member links
> are still wiki links, O-7's owed change. The covering cards are gone from
> the plane. Done in this pivot: G-415 (plain panels), G-408 (comm
> bridge), G-417 (sparkle), G-38's check repaired.
---

## 1. The record, by date

What the reader has said about the editor, its cells, its tools and its
agents, oldest first. Quotes are the reader's; the right-hand column is
where it was read into a design.

| Date, item | What the reader asked (reading in brief; quotes verbatim) | Read into |
|---|---|---|
| 2026-09-09 | The most convenient interface "a small language model could interact with safely ... simple and separable for the REPL" | `CALLABLE_INTERFACE.md` (superseded in framing by the chained single-hop toolspace in `PLUGIN_GOAL.md`) |
| 2026-10-11, Addendum II | "we move onward to the notebook kernel panel design first to nail it down correctly" | `NOTEBOOK_PANEL_DESIGN.md` (`P-N1..P-N10`, `P-M*`) |
| 2026-10-18, 162-170 | Code artifacts; (170) the installed PyPI base drawn in 3D as projected chunks, layout chosen by measurement | `CODE_ARTIFACTS_DESIGN.md`, rows `G-233..G-241` |
| 2026-10-18, 186a-186n | Install three local quantized models; "local code -> agents through interface panels"; (186c) "hard type constraints and conventions per quantised model and task"; (186e) recover the mothership's (mortegon) recursive reservoir 2D computation-graph editor | `GRAPH_WORKBENCH_DESIGN.md`, rows `G-237..G-240` (Open; models declined for now, 2026-11-16 (165), though the four files are on disk, §10c) |
| 2026-10-29, 1-29 | The 3D/2D computation-graph reservoir; the cockpit and the craft ("something like kerbal space program ... first person view within a 'cockpit' as well as a 3rd person view") | `RESERVOIR_DESIGN.md` |
| 2026-11-01, 49 | Cells run in real Jupyter kernels (`jupyter_client`, `ipykernel`) | built |
| 2026-11-01, 50 | The 2D editor is a PLANE inside the 3D view, not a second pane | built (G-299 and kin) |
| 2026-11-01, 51 | Every code artifact embeds its PROSE only (G-52's rule) | `tokens.for_model` |
| 2026-11-01, 62-63 | A slate IS a Python module written as a markdown tree (names in nested namespaces, `{ref}` resolved by Python scoping, Python's errors); the "missing link" between Jupyter's markdown and code cells -- a third cell kind compiled into the note's kernel | built in part (`slate_check`) |
| 2026-11-01, 65 | One thing seen four ways: graph NODE, PANEL, KERNEL cell, tree | built in part |
| 2026-11-01, 67-70 | The ego computation graph is ONE unit in 3D -- the craft | built, `G-299` live pass 2026-11-21 |
| 2026-11-04, 130-132 | Browser and ego panels "one-to-one the same with the markdown cells in all jupyter notebooks"; "the 'slate' is the markdown part of the notebook" | -- |
| 2026-11-04, 133 | Panels move across panes; a right-click makes a STUCK 2D panel (not the clipboard); ONE markdown panel, the same code, for billboard, code/node panel and notebook cell; a RETRIEVAL BAR over every typed node in place of `+ notebook / + slate / + browser`; code cells with VS Code's capabilities; minimize/exit; Ctrl +/- resize | built in part (`G-82` live pass 2026-11-21) |
| 2026-11-14, 157-159 | Code cells, the ego plane on the camera, the retrieval cell | built in part |
| 2026-11-15, 163-164 | The search's own computation graph -- revised the same day to ONE retrieval node whose inputs and outputs are hard links | `SEARCH_GRAPH_DESIGN.md` (revision section) |
| **2026-11-21, 166** | Only browser-scanned code is projected; the codebase leaves the 3D layout; base TOOL PANELS of ~25 lines of Python per toolspace (db search, web search, the browser, scanned interactive chunks); slim-context agents for quantized local models; code + markdown as one computation-graph unit; the editor as a general Python + markdown notebook-cell interface composing programs into quantized agentic workflows | this document |
| 2026-11-21, 167-170 | Answers: the codebase leaves layout and indexer; tool surfaces as calls only; tool panels read-only, regular code artifacts callable and graph-editable; the dialect kept; marimo-style dataflow; GGUFs ported from the browser; tool panels searchable; links undirected; smolagents' step | §6, §11e; G-375..G-384 |
| 2026-11-21/22, 171-181 | Streaming on CUDA; the stick layout; rulings; through-stacks deprecated and synthesised; the one model table | `THROUGH_STACK_SYNTHESIS.md`; G-385..G-393 |
| 2026-11-22, 182 | Chat as typed building blocks; the graph-view FORM goes, the artifacts ARE the nodes; one interface per code artifact | G-394, G-395 |
| 2026-11-22, 183-186 | The ego as one central canvas; then native panels; then seamless; then "NO SPECIAL EFFECTS" and "a conclusive plan" | §12; G-396..G-405 |
| **2026-11-22, 187** | Established interactive-object APIs over the in-markdown syntax; the graphical side is an existing permissive node editor for Python modules | §13; G-408..G-413 |
| 2026-11-22, 188-191 | The cross-check goal, no agents, design docs with fragments only; code tools on canvases scoped as app tools vs workspace code; eleven late-transcribed messages; every session prompt in the check (85 recovered, PLUGIN_GOAL's 2026-11-22 inventory) | §13n, §14 |
| 2026-11-24, 192 | Hover previews of billboards in 3D; does fly-to still work; "I don't know what these dotted lines are" | G-414; the craft gate (G-405) deployed; F-105 |
| **2026-11-24, 193** | "you're totally overdoing the work required for the markdown panels": plain Obsidian notes; the purple nodes removed; a `#` query as the retrieval gesture; code blocks as cells; one interface for every canvas type, two query embeddings | the head note; F-118 |
| **2026-11-24, 194** | the suggestions override the custom syntax in markdown panels; it moves to code cells that run and compile on the reservoir; measurements coupled at the code's interface; every output shown for i/o and vectorization, re-indexed by diffs; the terminal a standard interface type; groups of artifacts compose; live objects alongside the graphical code interfaces | the head note; F-129 |
| 2026-11-24, 195 | retrieval with the ego: results stay in their own canvases, drawn outside the ego's; each rendered canvas and its agent-facing tool interface in one editor, as a callable object whose base form is the string an agent sees; where a graph begins and a canvas ends, why and when | §13m (canvas / graph); F-138 |
| 2026-11-27, 200 | `panels: fly-to` on hovered 3D chunk nodes and browser panels; deeper cell-graph connectivity & collapsed lone cells under typed headings in `ego.md` via `[title](link)`; persistent multi-turn quantized chat context with `O(delta)` pinned chunks; centralized `+ chat` in `cellbar.ts`; fence-adaptive VS Code editor tools | G-443..G-447 |
| **2026-11-27, 201** | deprecate purple `slate_N` variable notes in favor of `# Title` + ` ``` ` cells; pull-apart & unified panel/graph dialect with `[cell title](cell link)` and recursive containment compilation (clicking node compiles panel; right-clicking header folds); cursor-exit fence evaluation & inline tracebacks; low-latency full VS Code helpers; direct cross-notebook variable DAG compilation (resolves O-5); `ego.md` as default system prompt + chat cell system prompt & `Chat.send` streaming; interactive recursively chunked ` ```tool ` cells with slim dict schemas (`search`/`back`/`forward`/`chunks: bool`), `back`/`forward` stack, and vanishing upward history above the cell; unified vertical `[]()` retrieval matching 3D `SearchField` | G-448..G-454 |
| 2026-11-28, 202 | Root `AGENT_HANDOFF.md` synchronizing `G-443`–`G-454` with Claude's `afc636d` (`G-433`–`G-442`), parallel lock-free task split, and procedural MCP verification checkpoints | `AGENT_HANDOFF.md` |
| 2026-11-28, 203 | Single-instance Obsidian & sidecar concurrency lease inside the MCP harness (`.domvec/mcp_session.lock`, wait-or-deliberate-busy return, `close_existing=False` reuse, zero coupling to freehand markdown artifacts) | G-455 |
| **2026-11-28, 204** | Re-center `AGENT_HANDOFF.md` and merge rules squarely on the Nov 27–28 pivot (`Items 200`–`203`); localize active code scope & module splits onto pulled-apart cell-graph + `[title](link)` containment, VS Code fenced Graph-RAG coding harness, cross-notebook Python DAG, and recursive ` ```tool ` + quantized chat loops while freezing superseded pre-pivot surfaces | `AGENT_HANDOFF.md` |
| 2026-11-28, 205 | Claude takes Track B (`AGENT_HANDOFF.md` §5.2) and commits `G-443`–`G-455` baseline (`d38b7e7`) | `AGENT_HANDOFF.md` |
| 2026-11-28, 206 | Map Claude's open pre-pivot rows onto Items `200`–`201` in `AGENT_HANDOFF.md` §5.4 | `AGENT_HANDOFF.md` |
| **2026-11-28, 207** | Unify web markdown chunks & editor cells via cursor-gated ` ``` ` notation (cursor inside = markdown + chunk ` ```tool ` affordances; cursor outside = rendered page); minimal gym Python API mirroring tool cells (`Browser.chunks` Soup-style + inlaid interactions + Selenium `ActionChain`, replacing graphical node editor); `ego.md` as plain notebook example of full toolspace APIs + docs (no fancy per-view ego features); ephemeral library UI vs. artifact-scoped procedural ` ```tool ` calls bridging notebooks/modules, users & agents; embedding-model-scoped docstring + artifact-link retrieval & code-editing tools; mutual transcript links in `AGENT_HANDOFF.md` | G-456..G-460; `AGENT_HANDOFF.md` |

Where the verbatim record ends: 2026-11-28, item 207 (it was 166 when this table was first written). Anything below that
line in any design is interpretation.

## 2. The designs already written, and what 166 does to each

| Document | Holds | After 166 |
|---|---|---|
| `CALLABLE_INTERFACE.md` | The safe small-model interface; single-hop toolspace | **Revived in spirit**: 166's tool panels are its natural successor -- one toolspace per artifact, small enough to sit in a quantized model's context |
| `NOTEBOOK_PANEL_DESIGN.md` | The kernel panel, outputs-in-markdown, vault-note addressing; §8's three questions, all since answered (§4a, T-13, 148) | Kept; its cells become the editor's unit |
| `GRAPH_WORKBENCH_DESIGN.md` | Code, models and workflows as graph nodes; the mothership's editor recovered | Kept for workflows and models; its "code as graph nodes" is narrowed by 166 (a) |
| `CODE_ARTIFACTS_DESIGN.md` | The codebase and PyPI packages drawn in 3D | **Superseded in its layout part by 166 (a)**; confirmed and widened to the indexer by 167 Q1 ("Layout and indexer", G-375) |
| `RESERVOIR_DESIGN.md` | The 2D/3D reservoir, cockpit, craft | Kept; §5 already corrected by (2026-11-01) 67 |
| `SEARCH_GRAPH_DESIGN.md` | Search as one node, I/O as hard links | Kept; its node is the cockpit's `search` field (§13h); its stage panels were withdrawn by 164 |

## 3. What 166 (a) changes, measured

On the live workspace (`project-noumen`, sidecar 8794, 2026-11-21): **216 of
409 stored pages (53%) are the repository's own code** -- 148 `code://repo`,
68 `code://plugin` -- the rest 170 `https`, 1 `http`, 22 `vault`.

Rows whose subject 166 (a) removes from the layout, to be marked superseded
once the reading is confirmed: `G-8`, `G-9`, `G-51` (modules and imports as
graph pages), `G-104`, `T-6`, and the layout half of `G-233..G-241`
(`(2026-10-18) 170`). What does NOT go: code that arrived by scanning a web
page (a code block on a page is a chunk like any other), and the code
*knowledge graph* the sidecar computes (`code_kg`, `cpg_*`, `codegraph`) --
166 removes the codebase from the 3D *layout*, not from the store. Whether it
should leave the store and the code-sync indexer too is §6 Q1.

## 4. The tool panel -- the constraints the record sets

From 166 and the items it builds on:

1. **One panel, one toolspace**, roughly **25 lines of Python**, that "show[s]
   the full capability" of that toolspace (166).
2. Named toolspaces: **db search**, **web search** ("two different 'tool
   panels'"), the **browser**, **scanned chunks with interactive structures**
   (166). The rest of "the full toolspace of our app" is to be grouped the
   same way.
3. A panel is a **code panel**: a notebook code cell (`(2026-11-01) 65`, one
   thing seen as node / panel / kernel cell / tree), run in the note's real
   kernel (`(2026-11-01) 49`). *(Later, 167 c: a TOOL panel is read-only,
   calls only (§13n); what runs is a reader's or an agent's call of it.)*
4. Code and markdown are **one computation-graph unit** (166 d), which the
   slate already is: a Python module written as a markdown tree
   (`(2026-11-01) 62-63`).
5. A tool's inputs and outputs are **hard links** in the graph (`(2026-11-15)
   164`) -- the search node is the first instance.
6. Sized for **quantized local models**: an agent holds "the handfuls of
   toolspaces they can handle in context at a time" (166 c); type
   constraints per model and task decide how outputs enter the graph
   (`(2026-10-18) 186c`).

The surface those panels would wrap, today: **~90 sidecar routes** and **~40
MCP tools**. No quantized model holds that; a handful of 25-line panels is
the reduction 166 asks for. A first grouping, offered for the reader to
correct, not decided:

| Toolspace | Wraps (existing) |
|---|---|
| db search | `/search`, `/search_pages`, `/chunk`, `/resolve`, `/pages`, `/ref` |
| web search | the browser cell's web search (`onWebSearch`), `/capture` |
| browser | navigate, pin, scroll, `/browser_state`, `/snapshot` |
| scanned chunks (interactive) | `/addresses`, affordances (the MCP `affordances` tool), enact |
| kernel / notebook | `/kernel`, `/note`, `/slate_check` |

## 5. Reference material: the reader's duck.ai session (2026-11-21)

The reader asked about editors that combine code, markdown and graph
compilation. What the model answered -- unverified, to be checked against the
projects' own pages before anything rests on it:

- **marimo** -- reactive notebook; cells' dependencies inferred from which
  variables each cell reads and defines; saved as plain `.py`; markdown via
  `mo.md(...)`, able to embed computed values. Closest in spirit to the slate
  (`(2026-11-01) 62`: names, scoping, a module).
- **JupyterLab** -- distinct code / markdown / raw cells in kernel order;
  extensions such as `jupyterlab-myst` allow inline Python expressions in
  markdown. Closest to the kernel protocol already in use (`(2026-11-01) 49`).
- **Typeflow**, **Nodezator** (Unlicense), **Ryven** (archived; editor MIT,
  `ryvencore` LGPL-2.1), **python-node-editor** (MIT) -- node editors that
  build nodes from Python callables and export graphs as Python code; none
  shown to interleave markdown with code.
- Its conclusion, which matches this project's direction: no existing tool
  combines a markdown-and-code document with a compiled graph; pair a
  notebook model with a graph engine.

The reading this suggests (not a decision): the slate's def/use names give
marimo-style dependency edges for free, and the kernel already runs the
cells -- the graph is derived from the notebook, not drawn separately.

### 5a. Checked against the projects' own pages (2026-11-21)

**marimo -- confirmed, and more precise than the summary.** Dependencies are
found STATICALLY, without running the code: each cell is parsed for the
global names it defines and the names it reads without defining; an edge
runs from a cell to every cell that reads one of its definitions, and the
cells form a DAG. Running a cell runs the cells that read its definitions;
order comes from the variables, not the page. Rules that matter for this
design:
- every global is defined by exactly ONE cell (the slate already raises "the
  same name bound twice in one namespace", `(2026-11-01) 62`);
- names prefixed `_` are local to a cell;
- mutations and attribute assignments are NOT tracked -- an in-place change
  in another cell does not re-run dependents;
- type annotations count as references unless written as strings;
- a setup cell runs first and may read nothing from other cells;
- `marimo check` lints for double definitions and cycles.
Sources: [Running cells](https://docs.marimo.io/guides/reactivity/),
[Understanding dataflow](https://docs.marimo.io/guides/editor_features/dataflow/),
[Key concepts](https://docs.marimo.io/getting_started/key_concepts/).

**jupyterlab-myst -- confirmed, with a limit.** The `{eval}` role puts a
kernel value inline in a markdown cell; a `jupyterlab-myst:executor` plugin
sends the expressions to the active kernel when the markdown cell is
"executed"; a markdown cell holding expression output is untrusted until the
notebook is run. Only single inline expressions -- a multi-line `{eval}`
block was still an open request in Dec 2025 (issue #286). Sources:
[jupyterlab-myst](https://github.com/jupyter-book/jupyterlab-myst),
[issue #286](https://github.com/jupyter-book/jupyterlab-myst/issues/286),
[MyST quickstart](https://mystmd.org/guide/quickstart-jupyter-lab-myst).

**Licences -- confirmed:** Nodezator, The Unlicense (public domain); Ryven,
MIT, over ryvencore, LGPL-2.1. **Not confirmed:** that Ryven is archived,
and that Nodezator or Ryven export a graph as Python code -- the search
found neither; read the repositories before relying on it. Sources:
[Nodezator](https://github.com/IndieSmiths/nodezator),
[Ryven](https://github.com/leon-thomm/Ryven),
[ryvencore](https://github.com/leon-thomm/ryvencore).

**What this means for §6 Q5** (a consequence, not a choice): marimo's model
fits the slate almost exactly -- the slate already has unique names per
namespace and `{ref}`s resolved by scoping, so the dependency edges can be
READ from the slate rather than drawn. Its one sharp edge for agent tools is
the untracked mutation: a tool that changes the store in place (capture,
purge, pin) re-runs nothing downstream, so such tools would have to return a
new value, or name a version, to be visible as dataflow.

## 6. Answered (2026-11-21, PLUGIN_GOAL 167) -- rows G-375..G-381, D-54

| Q | Answer (verbatim) | Row |
|---|---|---|
| 1 codebase | "Layout and indexer" | `G-375` |
| 2 the 25-line bound | "we have a table at the very beginning of our readme on what would become the 25-line tool surfaces as python calls only with comments at the end, or something equally minimal" | `G-377` |
| 3 which toolspaces | "see above" -- the README's pane table | `G-376` |
| 4 who writes tools | tool panels read-only, "implicit calls into the world itself"; regular code artifacts callable the same way plus full exploring and graph editing; the dialect kept "very carefully"; the notebook browser cell must scan and act as a regular tab | `G-378`, `G-379`, `D-54` |
| 5 dataflow | "marimo style" | `G-380` |
| 6 models | "no", but GGUFs ported in from browser download links as their own artifact type | `G-381` |

So §4's grouping by sidecar route is withdrawn: the toolspaces are the
README's six panes (3D graph, the ego, browser cell, panels, notebook /
slates, search), and a tool surface is calls only, a comment at each line's
end.

## 6b. The questions as they were asked

1. **How far does the codebase go?** Out of the 3D layout only (the store
   and the code knowledge graph kept, e.g. for agents to search), or out of
   the store and the code-sync indexer as well?
2. **The ~25-line bound**: per panel, per tool function, or a soft target?
   Is the panel the tool's *interface* (signatures + docstrings, the body
   elsewhere) or its whole implementation?
3. **Which toolspaces**, beyond the four named, make "the full toolspace of
   our app"? §4's grouping is a guess.
4. **Who writes the tool panels when new tools are made "along the way"** --
   the reader, an agent in the editor, or both -- and does a new tool enter
   the graph the moment its cell runs?
5. **Dataflow model**: marimo-style (dependencies inferred from names, cells
   re-run when inputs change) or Jupyter-style (explicit kernel order, edges
   drawn by hand)?
6. **Models**: 186's three-model plan was declined for now (2026-11-16, 165).
   Does 166 change that, or are the tool panels to be designed first, model
   choice after?

## 7. Next

*Done since: §6 answered (167), §5 checked (§5a), and the design written as
§10-§13.*

- Confirm §1's reading of 166 and answer §6.
- Verify §5 against the projects' own documentation (web research, as 166 f
  allows), and add what that research turns up.
- Then: the complete, self-consistent 2D interface design for
  notebook-kernel workflows with ~25-line tools -- stated against the
  numbered rows it will add to `PLUGIN_PRD.md`.

## 8. Draft tool surfaces -- one per README pane (G-376, G-377), for the reader to correct

The substrate already exists: `domvec/obsidian/kernel_objects.py` boots
read-only objects into every note's kernel -- `search`, `Database`,
`WebBrowser`, `Agent`, `Vault` -- each calling the sidecar's own routes, so a
cell "sees exactly what the app sees and cannot write the store behind the
lifecycle's back". Those are already "implicit calls into the world itself"
(167 c). Below, each pane as calls only, a comment at each line's end.
**`# exists`** marks a call that runs in a kernel today; **`# new`** marks a
call the surface needs and the kernel does not have yet (the route behind it
named where one exists). Drafted undecided; G-377 has since built every call.

```python
# search -- the store's retrieval
search("radix trie", k=8)                 # exists: ranked chunks, lexical x pagerank x semantic
search("radix trie", where="ego")         # exists: only the ego's artifacts and tagged chunks
search("radix trie", duckduckgo=True)     # exists: asks the browser cell; results arrive as captures
similar(cid, k=8)                          # exists: /search?ref= (G-372 step 2) -- a chunk's neighbours
Database.cypher("MATCH (p:Page) RETURN count(p)")  # exists: read-only, writes refused
types("article")                           # exists: G-388 -- types mined from trie-path patterns across pages
```

```python
# browser cell -- the live page
WebBrowser.url                             # exists: what the cell shows now
WebBrowser.go("https://en.wikipedia.org/wiki/Trie")  # exists: carried out when the cell ends
WebBrowser.chunks()                        # exists: the stored chunks of the page shown
WebBrowser.pin(xpath)                      # exists: the right-click pin -> a stuck plane panel (133 b)
WebBrowser.controls()                      # exists: the page's interactive fields, by address (affordances)
WebBrowser.act(address, value)             # exists: act on a field in place through its trie address
```

```python
# panels -- a chunk's two forms
chunk(cid)                                 # exists: /chunk -- the markdown, each line with its address
page_form(cid)                             # exists: /snapshot/<cid> -- the saved page form, or None
resolve(url, xpath)                        # exists: /resolve -- the chunk that draws an address
```

```python
# 3D graph -- the world
focus(cid)                                 # exists: fly to a node (the plugin, not the sidecar)
unfold(url)                                # exists: /unfold -- a page into its chunks
pages(contains="wiki")                     # exists: /pages -- stored page urls
```

```python
# the ego -- the tool space as one graph
ego()                                      # exists: /ego -- its nodes and links
attach(cid)                                # exists: tag a chunk into the ego
view("third")                              # exists: first / third person (G-333's camera field)
```

```python
# notebook / slates -- the computation graph itself
Vault.read("notes/Lattice.md")             # exists: the vault's files
Vault.write("notes/out.md", text)          # exists: inside the vault only, never .obsidian/.git
Agent.ask("summarise", context=hits)       # exists: the sidecar's local model, one session per kernel
check(slate)                               # exists: /slate_check -- the dialect's own errors (2026-11-01 62)
```

Counted: **25 calls exist, 0 are new** (2026-11-22, G-377 built: the fourteen that were new, plus `types` for G-388; it was 10 exist / 14 new before) (computed: `python -m domvec.tool_surface` reads these blocks and resolves each call against the kernel bootstrap; `tests/test_tool_surface.py`) -- and every one that was new sat on a route
or plugin action that already existed, so the surfaces are wrappers, not new
machinery. Two rows decide their shape: `G-378` (a tool panel is read-only
and cannot open the code behind it) and `G-380` (marimo-style: a call that
changes the world in place -- `go`, `pin`, `act`, `attach` -- is invisible to
name dataflow, so each returns a value that names what changed).

## 9. Research: permissive libraries against the verbatim (2026-11-21)

Asked for (verbatim in PLUGIN_GOAL 190): "keep researching on marimo and other permissive libraries that
would help with our true design verbatim". Each entry names the row it could
serve, what the project's own pages say (with the link), and -- marked as
such -- how it might fit. Nothing here is adopted; every "fit" is a reading.

| Library | Licence | Serves | What its own pages say |
|---|---|---|---|
| **marimo** | Apache-2.0 | `G-380`, `G-378` | Dependencies read statically, a DAG over cells (§5a). `app.embed()` runs a notebook and returns its output and **defined variables**; values passed in through `defs` replace the cells that would define them; `clone()` gives independent copies. Functions and classes defined in a notebook can be imported by other programs. Stored as pure `.py`. |
| **smolagents** | Apache-2.0 | 166 (c, d), `G-377` | `CodeAgent` writes its tool calls **as Python** (the default); one step can loop over several tool calls; the project claims ~30% fewer steps than JSON tool calls (its own claim). Runs local small models (Transformers, Ollama) but calls a 3B model "a bit weak for agentic behaviours", and raises Ollama's 2,048 context to 8,192. Its local executor "must not be used as a security boundary". |
| **Jupytext** | MIT | `G-379` | A notebook as plain text: `# %% [markdown]` and `# %%` cell markers (percent format), or markdown formats for prose-heavy notebooks; a text file paired with the `.ipynb`, the text holding the inputs, the `.ipynb` the outputs. |
| **LibCST** | MIT | `G-378`, `G-377` | A lossless concrete syntax tree: reprints the exact input, comments and whitespace kept; a statement owns the comments directly above it and its trailing same-line comment. |
| **litegraph.js** | MIT | the plane | Canvas2D node editor, no component framework; graphs export as JSON; the engine runs in the browser or Node. |
| **xyflow** (React/Svelte/Vue Flow) | MIT | the plane | Component-framework node UIs; asks (does not require) attribution. |
| **Rete.js**, **BaklavaJS** | MIT | the plane | Framework-style visual-programming editors (BaklavaJS on Vue, in TypeScript). |
| **gguf** (from llama.cpp) | MIT | `G-381` | Reads and writes GGUF; `gguf_dump` and `examples/reader.py` print a file's key-value metadata and tensors. Python 3.10+. |
| **llama-cpp-python** | MIT | `G-381` | Runs GGUF models; its chat formatting reads `tokenizer.chat_template` from the file's metadata. |

Sources: [marimo App API](https://docs.marimo.io/api/app/),
[marimo FAQ](https://github.com/marimo-team/marimo/blob/main/docs/faq.md?plain=true),
[marimo licence](https://github.com/marimo-team/marimo/blob/main/LICENSE),
[smolagents](https://github.com/huggingface/smolagents),
[smolagents guided tour](https://github.com/huggingface/smolagents/blob/main/docs/source/en/guided_tour.md),
[Jupytext](https://jupytext.readthedocs.io/),
[Jupytext formats](https://jupytext.readthedocs.io/en/latest/formats-scripts.html),
[LibCST](https://github.com/Instagram/LibCST),
[LibCST docs](https://libcst.readthedocs.io/),
[litegraph.js](https://github.com/jagenjo/litegraph.js/),
[xyflow licence](https://github.com/xyflow/xyflow/blob/main/LICENSE),
[Rete.js](https://github.com/retejs/rete/),
[BaklavaJS](https://github.com/newcat/baklavajs),
[gguf-py](https://github.com/ggml-org/llama.cpp/blob/master/gguf-py/README.md),
[llama-cpp-python](https://github.com/abetlen/llama-cpp-python).

### 9a. How these could fit -- readings, not decisions

- **The tool surface IS what a code agent emits.** 166 (d) wants "quantized
  language model input and output formats that include their own code
  artifacts". smolagents' `CodeAgent` is exactly that loop: the model reads
  tool signatures and writes Python calling them. A §8 surface -- calls only,
  a comment per line -- is then both the tool's documentation AND a sample of
  the code the agent is expected to write back. The open risk is model size:
  the project itself finds a 3B model weak and 2,048 tokens too small, which
  is the case for keeping each surface to ~25 lines (`G-377`).
- **A notebook becomes a callable tool.** marimo's `app.embed(defs=...)` is
  the shape 166 (e) asks for -- "lightweight and modules composition of
  python programs": a notebook's free names are its inputs, its definitions
  its outputs, and another cell can call it. In this project's terms that is
  a slate or notebook appearing as ONE node whose hard links (2026-11-15 164)
  are its free names in and its definitions out.
- **Use marimo's rules, or marimo?** Its public API is the App level; the
  dataflow analysis is internal. Two paths: depend on marimo and store
  notebooks as its `.py`; or keep the slate dialect (`G-379`) and compute the
  same def/use DAG with the standard `ast` module, marimo's rules (§5a) as
  the specification. The second keeps the dialect intact; the first gets
  marimo's runtime. *Answered by 167: "marimo style" (Q5) with the dialect
  kept "very carefully" (Q4), so the second path, built as `dataflow.py`
  (G-379, G-380).*
- **Graph edits that keep the code readable.** A regular code artifact is
  graph-editable (`G-378`); an edit made on the graph has to be written back
  into the cell without destroying it. LibCST reprints code losslessly, and
  its rule that a statement owns its trailing same-line comment is the exact
  form of a tool surface line (`G-377`).
- **The plane's editor.** The plane is already drawn in the 3D view
  (2026-11-01 50). Of the node editors, litegraph.js is the only one without a
  component framework -- the plugin uses none -- and it exports JSON; the
  others would bring React or Vue into the plugin. Whether any replaces the
  plane's own drawing was open; 187 answered it (§13c, §13j).
- **GGUF as an artifact.** The `gguf` reader gives a downloaded model's
  architecture, quantisation and chat template from its metadata, without
  loading the weights -- enough for its panel (`G-381`) to say what it is
  before anything runs it; `llama-cpp-python` would run it.

### 9b. Withdrawn (2026-11-21, PLUGIN_GOAL 168)

Three library-by-library choices were posed here. The reader answered that
posing them shows the design vision had not been weighed against the whole
verbatim (168 a), and that the libraries are to be INTEGRATED so that the
realisation is complete, not picked between (168 c). §10 takes the design
first. The provisional note that stood under the first choice records only
what was built before 168 (`domvec/dataflow.py`); §10a places it.

## 10. The design first, then the libraries that complete it (2026-11-21, PLUGIN_GOAL 168)

### 10a. What the verbatim converges on -- a reading, to be confirmed

*Corrected by §11b (2026-11-21): mortegon's older verbatim puts the two faces
as PANEL and GRAPH form, with the code entering both as typed rows -- not a
separate code face.*

168 a names the convergence: "to graphically design python programs and
modules with a dual interface on kernel cells". Gathered from the record,
the parts it converges from:

| The record says | Where |
|---|---|
| a slate is a Python module written as a markdown tree; the markdown panels are extended to Python's syntax and stay markdown cells | 2026-11-01 62, 63' |
| node / panel / kernel cell / tree are one thing | 2026-11-01 65 |
| the computation graph editor is a general Python and markdown notebook cell interface, for quantized agentic workflows, lightweight module composition of Python programs | 166 (d, e) |
| tool panels: read-only code artifacts, "implicit calls into the world itself"; regular code artifacts are called the same way AND graph-editable | 167 (c) |
| the dialect of graph and cells is kept with great care | 167 (d) |
| marimo-style dataflow | 167 (f) |
| a ported GGUF is its own panel / cell type | 167 (g) |
| the ego as a computational reservoir; the 2D plane editor integrated with the 3D layout, which moves in first and third person, always centred | the standing goal |

Read together -- my reading: **one object with two faces.** A note is a
module; its cells (python fences, slate trees, tool panels, model cells) are
its nodes, each addressed `vault://<note>#cell <n>` (2026-11-11 159). The
**code face** is the note read top to bottom; the **graph face** is the same
cells drawn as nodes on the plane, with an edge wherever one cell reads a name
another defines. Neither face is stored separately: both are projections of
the note's text through the trie, so an edit in either is an edit to the same
text, and the other face redraws from it. A module composes into another by
being called: its free names are its inputs, its definitions its outputs.

Under that reading, each library is a part of one machine, not an option:

| Part of the machine | What fills it | Status |
|---|---|---|
| edges of the graph face (who reads whose names) | marimo's rules | built as `domvec/dataflow.py` (G-380); marimo's own analysis is internal, not a public API -- answered by 167: our own, by marimo's rules (§9a) |
| a graph-face edit written back into the code face, comments and layout kept | LibCST (MIT, **installed**, 1.9.0) | not started -- the write-back half of G-378 |
| a module called as a node from another note | marimo's `app.embed(defs=...)` shape: free names in, definitions out | not started |
| the plane on which the graph face is drawn and edited, inside the 3D layout | litegraph.js (MIT, Canvas2D, no framework) or the plane's own drawing (`planepanels.ts`) | answered by 187: an existing node editor, a pinned MIT litegraph (§13j) |
| the agent that writes cells | smolagents `CodeAgent` (§10b) | installed (checked 2026-11-22, §10d); not yet wired |
| the model behind each agent task | GGUFs through llama.cpp: GPT4All today (**installed**, 2.8.2), llama-cpp-python for constrained output | §10c |
| what a ported model is, before it runs | `domvec/gguf_meta.py` (G-381) | built |

### 10b. smolagents in depth, against that machine

What the library is, from its own documentation (Context7
`/huggingface/smolagents`, read 2026-11-21):

* **The agent writes code as its action.** `CodeAgent(tools, model,
  additional_authorized_imports, planning_interval, executor_type,
  executor_kwargs, use_structured_outputs_internally, code_block_tags, ...)`.
  `ToolCallingAgent` is the JSON-call alternative.
* **A tool is a typed Python function.** `@tool` on a function with type
  hints and an `Args:` docstring, or a `Tool` subclass with `name`,
  `description`, `inputs`, `output_type`, `forward`. All of it is "baked into
  the agent's system prompt" -- the tool's documentation IS what the model
  reads. `ToolCollection.from_mcp(...)` turns an MCP server's tools into
  smolagents tools.
* **Any model can be plugged in.** Subclass `Model` and implement
  `generate(messages, stop_sequences, ...)`, returning an object with
  `.content`; the method may take a `grammar` for constrained generation.
  Built-in: `TransformersModel`, `LiteLLMModel` (Ollama: raise `num_ctx` to
  8,192), `VLLMModel`, `MLXModel`, OpenAI-compatible servers.
* **Execution.** `executor_type` is `local`, `blaxel`, `e2b`, `modal` or
  `docker`. The local executor interprets the AST operation by operation:
  imports refused unless authorised, submodules refused unless authorised
  (`random._os` is caught), loops capped at 1,000,000 iterations. And yet,
  per its SECURITY.md, the local executor is not a security boundary.
  Managed agents are not supported on the remote executors.
* **Memory is a list of steps.** `agent.memory.steps` holds `TaskStep` and
  `ActionStep`; an agent can be run one step at a time (`agent.step(...)`),
  and the memory edited between steps. `step_callbacks` run after each step;
  `final_answer_checks` can refuse an answer and make the agent continue.
* **Multi-agent.** `managed_agents=[...]` lets a manager agent call others
  as if they were tools.

How each fits the machine -- readings, not decisions:

1. **An agent's run is a notebook.** Each `ActionStep` is one code cell and
   its observation is that cell's output. Run one step at a time, each step
   can be written into the note as a cell -- so an agent's work appears in
   BOTH faces: the code face as cells, the graph face as nodes whose edges
   come from the same dataflow (`dataflow.py`). The reader can edit a step's
   cell and the dataflow marks what is now stale. This is the "quantized
   agentic workflows" of 166 d given the dialect of 167 d.
2. **The tool surface is the tool listing.** smolagents puts each tool's
   signature and docstring into the model's prompt. A §8 tool surface --
   calls only, one comment per line -- is that same information in its most
   compact form, so the surface can be the text a small model is given
   (G-377), and `tool_surface.py` already checks every line against the
   kernel. A tool panel (read-only, 167 c) maps to a smolagents `Tool` whose
   `forward` calls a sidecar route -- the kernel objects
   (`kernel_objects.py`) already make exactly these calls.
3. **The executor is the note's own kernel.** Rather than smolagents' local
   interpreter, the agent's code could run in the Jupyter kernel the note
   already has, through a custom `PythonExecutor`. Then an agent's cell and
   the reader's cell share one namespace and one dataflow. Trust: the kernel
   objects are read-only on the store and `Vault.write` stays inside the
   vault, but a kernel is not a sandbox either -- the same caveat smolagents
   states about its own executor. Where untrusted model code must be
   contained, `docker` is the only listed executor that runs on this machine
   without an outside service.
4. **Constrained output for small models.** `generate` accepts a grammar.
   llama.cpp's server takes a GBNF `grammar` or a `response_format` JSON
   schema per request (only a subset of JSON Schema converts to a grammar,
   per its GBNF guide). For a 7B Q4 model, a grammar that only allows a
   fenced Python block calling the listed tools would remove a whole class of
   malformed steps. Unverified here: how llama-cpp-python's
   `create_chat_completion` maps `response_format` -- its own docs were not
   found in this search.

### 10c. Quantized models by task -- what is on this machine

Every row below is a file already on disk, described by `domvec/gguf_meta.py`
from its header (G-381); nothing was downloaded. "In use" means the code loads
it today.

| Task | Input -> output | Model on disk (quant, context) | Status |
|---|---|---|---|
| embedding chunks (the projector's vectors) | text -> 768-d vector | `nomic-embed-text-v1.5` / `v1`, f16 GGUF via GPT4All `Embed4All` | **in use** (`core/embedding_service.py`) |
| chat about chunks (`Agent.ask`, `/chat`) | prompt + chunk context -> reply | Nous-Hermes-2-Mistral-7B-DPO, Q4_0, 32,768 | **in use** (`chat.py`) |
| writing cells -- a code agent | tool surface + note -> Python cell | Qwen2.5-Coder-7B-Instruct, Q4_0, 131,072 | on disk, unused |
| JSON tool calls (`ToolCallingAgent`) | tool schemas -> one JSON call | Hermes-2-Pro-Mistral-7B, Q4_K_M, 32,768 | on disk (HF cache), unused |
| planning between steps (`planning_interval`) | task + memory -> plan | DeepSeek-R1-Distill-Qwen-7B / 14B, Q4_0, 131,072 | on disk, unused |
| long-context reading (a whole note or page) | many chunks -> summary | Meta-Llama-3.1-8B-Instruct, Q4_0, 131,072 | on disk, unused |

*Corrected 2026-11-22 (cross-check, §14 F-9).* "Every file on disk" was
wrong: four more GGUFs are in `~/.cache/gpt4all` and are rows of
`models.ROLES` (G-393):
- `deepseek-coder-6.7b-instruct.Q4_K_M` (role `coder`);
- `triplex-Q4_K_M` (`triplex`);
- `OpenJev-Flash-9B-Q4_K_M` and `OpenJev-Q4_K_M` (`jev` and its large
  alternative).

They are the downloads GRAPH_WORKBENCH §4 records as approved on 2026-10-18.
The later record speaks of them as not yet downloaded: 165 answered "Not now"
to G-237..G-240's downloads, and 179's default-model answer says "needs
G-237's downloads; Qwen until then". The disk says the files are present. So
what is open for those rows is wiring and use, not a download.

The task column is my reading of which file suits which task, from each
header's architecture, context length and chat template. No model has been
run against any task here; a measured row needs a harness probe with a
planted arm (a malformed-step rate with the grammar on and off, say).

Two things the table shows that the design has to answer. First, GPT4All is
already the llama.cpp runtime in this process, so a smolagents `Model` over
GPT4All's `generate` adds no new engine -- but GPT4All exposes no grammar, so
constrained output needs llama-cpp-python or llama-server beside it. Second, a
GGUF ported from the browser (G-381) can be offered for a task by the same
header fields this table was built from.

### 10d. Open, for the reader

*Answered 2026-11-21 (169): 3 "double-check and explain to me in my own
terms", answered by §11's correction of 10a; 4 "yss", and smolagents and
llama-cpp-python are installed (checked 2026-11-22).*

* Does the reading in 10a -- one object, two faces, through the trie -- state
  the vision, or does it miss something the verbatim holds?
* Installing `smolagents` (Apache-2.0) and `llama-cpp-python` (MIT) are
  downloads, and wait for a yes.

Sources: [smolagents](https://github.com/huggingface/smolagents) (read through Context7 `/huggingface/smolagents`),
[secure code execution](https://github.com/huggingface/smolagents/blob/main/docs/source/en/tutorials/secure_code_execution.md),
[SECURITY.md](https://github.com/huggingface/smolagents/blob/main/SECURITY.md),
[models reference](https://github.com/huggingface/smolagents/blob/main/docs/source/en/reference/models.md),
[memory tutorial](https://github.com/huggingface/smolagents/blob/main/docs/source/en/tutorials/memory.md),
[llama.cpp GBNF guide](https://raw.githubusercontent.com/ggml-org/llama.cpp/HEAD/grammars/README.md),
[llama-server structured output](https://dominguesm.github.io/llama-crab/en/server/structured/).

## 11. The mortegon docs, read against the computation graph editor (2026-11-21; the request is PLUGIN_GOAL 190, transcribed late)

Asked for: "for our computation graph spec, methodically go through all parts
of the mortegon docs that touch on similar things, and allow that to inform
further architecture consolidation and design research."

### 11a. Method, and what earlier passes had already recovered

The mortegon docs are the local clone `C:\Users\isaac\Documents\web_fiber_haptics\docs`
(branch `feat/v3.0-phase-9-cascaded-renderer`, last commit 2026-09-13): 112
markdown files, 1,871 sections. Their own precedence puts the verbatim first
(`USER_REQUIREMENTS_VERBATIM.md`, cited **UR**), then `DOMAIN_MODEL.md` (**DM**),
then objects, features, constraints, architecture, specs (`DOC_MAP.md` §0.1).

1. Every section of every file was scored against nine editor themes (graph
   editor, node/edge, card/slate/panel, cell/notebook/kernel, Python object and
   compile, agent/model/tool, dual/black box/collapse, ref/dataflow, ego/3D).
2. Read in full, in the docs' own order of authority: UR §E, §F, §I, §J, §M,
   §N, §O, §P, §Q, §R, §S, §T (every editor-bearing verbatim section); then DM
   §7.8 (the reservoir), §9.6 (Python-native API trees), §12.2, §12.6 (the
   agent's tick, the user and agent authoring together), §16.4, §16.6;
   `ontological_warp.md` §3A.2-§3A.7 (base objects, compile, agents).
3. Measured which UR items domvec's design docs (`RESERVOIR_DESIGN`,
   `GRAPH_WORKBENCH_DESIGN`, `DESIGN_VISION`, `DESIGN_SPACE`,
   `NOTEBOOK_PANEL_DESIGN`, this spec) already cite: **57 of the 111 numbered
   items in §E-§T; 54 not.** The count is by citation pattern, so a paraphrase
   without its number reads as uncited.

Of the 54, these bear on 166-168 directly, and §11b-§11d use them:
F.3, F.6 (the Agent's signature; the read-only sentinel), N.11 (computation
graphs and agents in one "unified conceptual program model"), N.14 (rank-1
minimalism), O.20-O.21 (typed agent templates), O.22 (one search space over
data AND computation), P.1, P.5, P.11, P.12 (the reservoir rollout), S.1-S.2
(no separate editor fixture), E.8, E.10 (SLM-sized chunks, token streaming),
J.3-J.5 (the RAG, round-trip and iterated-compile scenarios).

### 11b. What mortegon says about the dual interface -- and what it corrects in §10a

§10a read the dual interface as a **code face** (the note read top to
bottom) and a **graph face**. Mortegon's verbatim draws the two faces
differently, and is the older record:

*Superseded in part (2026-11-22): 182 retired the graph FORM and the flip
gesture, and 187 made the 2D node the artifact's own interface in a node
editor. The commute below now holds between the CODE and the graph editor
(B2, §13c, §13d). The typed rows (M.2-M.5) stand as ports (§13d').*

* **The two faces are PANEL form and GRAPH form.** "If a panel is double left
  clicked, it is compiled into computation graph form, which has similar
  folding over right click properties, but in graph space with pure links
  between nodes" (UR M.7). "I create a new node that is technically both
  computation and panel-based as a singular field primitive that is simply
  visually restructured in regards to its context graph" (N.2).
* **They commute.** "integrate a new functionality that commutes the
  node-panel dual-representation" (R.1) -- an edit in either form round-trips
  into the other; graph form stays "in node-count parity" with the panel
  (O.1); markdown gestures (dashes, tabs, numbers, newlines) restructure the
  graph (R.5).
* **Python programs enter BOTH faces as trees of typed rows.** "Module
  structures ... are completely translated to recursive structures of
  computation graph nodes of singular values with memory reference from other
  nodes to build the original object model" (M.2); the panel form is
  `name: Type = {ref}` rows (M.3, DM §9.6.1). A property whose type is a class
  unfolds into that class (M.4); a function is "automatic memory lookup to
  inputs" (M.3), its output type inferred from what it is wired to (M.5, E.6).
* **`{ref}` is a memory-access activation.** "any curly brace field, really
  just means an activation to a memory access procedure somewhere else in the
  app" (N.10). Compile walks those references lazily, revealing each node "as
  the computation reaches them" (O.9); cycles are refused
  (`ontological_warp` §3A.5).
* **The panel is a black markdown slate.** "a tree-structured graph editor that
  is completely in-text and parsed with specialized editor-specific syntaxes"
  (T.5), the data connections "only under-the-hood" (T.6).

So, corrected reading: **the code is not a third face beside these two.** A
Python program enters the editor as a tree of typed rows. The rows read as a
panel (the slate's text) or as a graph (singular fields joined by lines), and a
gesture flips between the two. 167's "regular code artifacts ... would have the
full capabilities of exploring and graph editing" is this unfolding applied to
a code artifact. The slate dialect domvec already has (`{ref}`, names with
spaces, a binding refused twice, `slate_module.py`) is mortegon's panel
syntax carried over.

### 11c. Architecture consolidation -- mortegon's parts, domvec's state, and what library integrates each

| Mortegon part (verbatim) | What it is | In domvec now | Row | Integrates with |
|---|---|---|---|---|
| `{ref}` as memory-access activation (N.10); names with spaces (N.7) | the slate's reference | `slate_module.py` resolves and compiles `{ref}` | G-379 | -- |
| compile = lazy back-reference walk, reveal-as-it-walks, cycles refused (§3A.5, O.9, O.13) | the execution order | `dataflow.py`: order, stale set, `CycleError` | G-380 | marimo's rules for the static half; mortegon adds the lazy reveal |
| functions as memory lookup; closest-inverse lookup (E.6, M.5, DM §7.7) | an unbound input found from its output's type | forward-inverse, G-279 | -- | not in marimo, smolagents or any library surveyed -- domvec's own |
| a Python object materialised read-only: `read_only`, `no_datablock`, `backing_pointer` to the live callable (F.5, F.6, DM §9.6) | the **tool panel** | `kernel_objects.py` objects; the §8 surfaces | G-378 | Python's `inspect` and `typing` for the typed rows; the body is never shown, as F.6 and 167 c both say |
| user-authored panels that compile; edits written back (R.1) | the **regular code artifact** | slate, `compile_module` | G-378 | LibCST (installed) for writing a graph edit back into Python source losslessly |
| the panel / graph commute, node-count parity, undirected lines, no arrowheads (R.1, O.1, O.16) | the plane's two forms | the plane, `planepanels.ts` | the standing goal | a node editor (litegraph.js) only if it can draw undirected, arrowless links and stay in parity with the slate. After 182/187 the parity is with the CODE (§13d), and arrowless is litegraph's default (§13f) |
| the agent uses the user's own primitives: `create_card`, `link`, `invoke`, `commit_subgraph`, `request_user_review`; "the cards *are* the API" (§3A.2, §3A.7, DM §12.6.1) | co-authorship | -- | 166 d | smolagents `CodeAgent`: those five become tool-surface calls, and each agent step is a cell |
| the editor is not a separate fixture -- its mutations are intrinsic to the panel scheme (S.1, S.2) | no editor object | -- | -- | the editor's calls sit on the same routes the plane's gestures use |
| the Agent's `template`: one typed template fills the prompt AND parses the output, written in the slate's own text pattern, not raw JSON schema (F.3, O.20, O.21) | typed model I/O | -- | 166 d | a llama.cpp grammar or JSON schema made from the slate's typed rows; smolagents `final_answer_checks` |
| perceive -> transform -> emit, one tick; emitter actions are editor calls (DM §12.2) | the agent loop | -- | 166 d | smolagents' step loop; `step_callbacks` write each step as a cell |
| token streaming from the agent (E.10) | live output | `/chat_stream` | -- | `CodeAgent(stream_outputs=True)` |
| outputs larger than a chunk are chunked again for the SLM (E.8) | sizing for small models | the chunker | 166 c | the 25-line surface is the same idea for tools |
| the 3D map is the world; the compute graph is a reservoir; its typed readouts are the perimeter, streamed into 3D as deltas; a computation-graph node on the bisector of input and output centroids (M.1, P.3-P.10, DM §7.8) | the computational reservoir | `RESERVOIR_DESIGN.md` | the standing goal | -- |
| one search space over data AND computation: panels, functional objects and whole subgraphs embedded beside chunks, so a task can find the subgraph that does it (O.22) | finding the right tool | -- | 166 c | see question 1 below |
| rank-1 minimalism is a pro-pattern (N.14); "recursive minimalism with memory-function maximalism" (R.3) | the governing principle | -- | 166 c | -- |

### 11d. What this changes

1. **One principle, said twice.** 166 asks for agents "slim on context and
   maximal on capabilities"; mortegon asked for "recursive minimalism with
   memory-function maximalism" (R.3) and called rank-1 minimalism "extremely
   important" (N.14). The ~25-line tool surface is rank-1 minimalism applied
   to the toolspace: each line one capability, nothing below it shown.
2. **The tool panel already had a precise definition.** Mortegon's
   materialised Python object -- `read_only`, the body never projected
   (`no_datablock`), a pointer to the live callable -- is 167's tool panel
   ("special read-only and no way of exploring the underlying codebase ...
   implicit calls into the world itself"), five months earlier. Those three
   invariants are what G-378 can be tested against.
3. **The agent needs the editor's own calls.** Mortegon's agent authors with
   the user's primitives, and the cards ARE its API (§3A.2). So the §8 surfaces
   lack one surface: the editor's own -- `create`, `link`, `invoke`, `commit`,
   `review`. Added below; all five exist since (each marked `exists`;
   `kernel_objects.py` boots them, §13h).
4. **smolagents takes LangGraph's place in the same role.** Mortegon
   integrated GPT4All under LangGraph (E.10) and read a LangGraph node as a
   card (§3A.6). smolagents' step is the same unit in code form: a step is a
   cell, its observation the cell's output, and its tool calls are calls on
   the surfaces. The typed template (O.21) is what a grammar enforces for a
   small model.
5. **§10a is corrected by §11b.** The two faces are panel and graph, the code
   enters as typed rows, and the dual commutes.

```python
# the editor -- the graph itself, by the same calls the gestures make (mortegon §3A.7, S.1)
create("scan for duckduckgo url", "{scan}")  # exists: a node, panel and graph at once (N.2)
link("DuckDuckGo", "scanner")              # exists, but writes a wiki link today; owed: a compiled link (O-7)
invoke("DuckDuckGo")                       # exists: run the walk; nodes reveal as reached (O.9)
commit("research agent")                   # exists: keep a subgraph as one node (3A.7)
review("DuckDuckGo", "is this the right source?")  # exists: ask the reader before going on (3A.7)
```

### 11e. For the reader -- three questions the record does not settle

*Answered 2026-11-21 (PLUGIN_GOAL 170): 1 yes -> G-382; 2 undirected -> G-383;
3 smolagents' step -> G-384.*

1. **Are tool panels and subgraphs embedded and searchable?** O.22 put
   panels, functional objects and whole subgraphs in the same retrieval space
   as chunks, so a task finds the subgraph that does it. 166 removed the
   codebase from the projector and kept "only the most base interfaces as
   code tools". Do those tool panels (and user subgraphs) get vectors and a
   place in 3D, as O.22 had it -- or are they found only by name?
2. **Direction in graph form.** O.16: "no arrowheads anywhere", links are
   undirected lines. marimo-style dataflow (167 f) has a direction -- definer
   to reader. Is the direction computed but drawn undirected, as O.16 says?
3. **The agent loop.** Mortegon's tick was perceive -> transform -> emit
   under LangGraph. Does smolagents' code-writing step replace it -- each step
   a cell in the note -- or does the tick stay as the outer loop with
   smolagents inside the transform?

## 12. The connected plan (2026-11-22, asked in PLUGIN_GOAL 186)

186: "There was never really a conclusive plan on all these facets connecting
together." This section is that plan. It invents nothing: each part is a
decision already on record, and the work here is to put those decisions
together. The sources are `DESIGN_VISION.md` (the whole-vision review, 142,
ruled by 145), `RESERVOIR_DESIGN.md` §3, §4, §5, §10 and §12 (the mortegon
dialect as distilled), §8-§11 above, and PLUGIN_GOAL 130-186. §12g names what
my 183-185 slices got wrong against this record.

### 12a. One record, many placements -- the governing rule

"One representation, two places" (RESERVOIR §5, item 37; mortegon R.1, O.19).
A thing -- a note, a cell, a chunk, a browser, a tool, a model, a run -- is
ONE record: its slate text, its `{ref}` edges, its fold state and its current
readout. What the reader sees are PLACEMENTS of that record, never copies kept
in sync:

| placement | where | when (159, 183, RESERVOIR §5) |
|---|---|---|
| a field, folded | one line of another record's text: `name {ref}` | braced-hidden |
| a field, revealed | the target's rank-1 lines indented inline under that line, in the same grammar | revealed-internal |
| a panel | its own Obsidian markdown view on the 2D plane, joined by a solid undirected line to every field that references it | resolved-external ("stuck") |
| a node | a glowing node in 3D on the ego's own UMAP; hovered, it billboards its record revealed to its level | in flight |

The first three are mortegon's three brace states (UR O.1a; RESERVOIR §3.1):
"braced-hidden `{name}`; revealed-internal (the target's rank-1 lines indented
inline, braces dropped); resolved-external (a solid line to a node already on
screen)". **A brace's state is fold state, not text.** The note keeps
`{outline_note}` whichever way it is drawn, so no gesture rewrites the line
(this replaces 183's `![[...]]` / `[[...]]` encoding, 12g).

"One record, one place drawn open" (184 a). A record revealed inline AND open
as a panel would be two placements in 2D at once. Opening it as a panel
resolves its braces to external: they fold to their line, and a solid line
joins them to the panel.

### 12b. The one panel, the one grammar

- **The one markdown panel** is Obsidian's own markdown view, extended, the
  same code everywhere: billboard markdown, code and node markdown, notebook
  markdown cells, slates, the clipboard, chat (DESIGN_VISION 1.6; 133 "Not
  three different markdowns"; 140 "one unified markdown panel"; 131-132 "the
  slate is the markdown part of the notebook").
- **The grammar** is the slate's: tabs and newlines, names (spaces allowed,
  N.7), values, and `{ref}` as the only markup (RESERVOIR §3.1). Every field
  NAME is a variable, drawn as a node in Obsidian's purple link style; values
  stay plain (54, 55, 60); plain prose is never highlighted (137.9). It is a
  Python module written as markdown (62, 63'): a name bound twice is an error.
- **The gestures** are the native editor's plus mortegon's gesture table (DM §7.3.4;
  UR M.6-M.8, N.13; RESERVOIR §3.3):
  - a single left-click edits in place (M.8, 104);
  - a right-click on a `{ref}` reveals or folds it;
  - a right-click on the title collapses the record to its title, so the panel
    becomes its node (110);
  - typing `{` completes names, and an unknown name opens the halo;
  - Tab, Shift-Tab and Enter restructure the tree;
  - a double right-click on a `{ref}` deletes the link;
  - a press held past the debounce picks a field up (182): dropped on the
    plane it is resolved external (a panel), dropped on a field line it is
    referenced there.
- **NO special effects** (186, 158 "No fancy shapes"). A component is not a
  box, a chip, a fold triangle or a hover toolbar. It is a field. Revealing
  it draws its lines in the same grammar, at the same left margin and
  indentation, on the same surface (185 "one uniform canvas surface").
- **Editable where shown** (M.8, 104): a revealed line of a vault record is
  edited in place and the edit is written to the record it belongs to. The
  exception is a web chunk's markdown: "The markdown view of a cell must be
  its own cell, and cannot be editable" (151). The page owns it.

### 12c. The ego canvas

- **The ego is the tool space** (158): "a more compact representation of the
  *tool space* of the ego (i.e. web browser, attached artifacts, interactions
  with the database, etc)". Its records are the cockpit (`ego`), the browsers,
  the search (164, a single retrieval node), the notebooks, the chats, the
  tagged chunks (74b) and the reader's own notes (77). It does NOT hold the
  repository's code (158, 166).
- **The canvas is the ego's record, written as fields.** The ego slate
  `domvec/ego.md` already IS that record (54, 62). The canvas is that slate
  with one field per component in compile order (142): `outline_note
  {outline_note}`, `search {search}`, `browser {browser}`. Revealing a field
  draws the component inline. Order is the order a model reads (T-2, T-11:
  row-major). Whether the canvas is `ego.md` itself or a second note that
  references `{ego}` first is decided by 54's "one ego, not two" (the next
  paragraph).
- **One ego** (54, 184 a). The canvas and the cockpit are one record. The
  cockpit's fields (`view`, `camera`, `throttle`, `keys`, `last`, `plan`,
  `play`, `unfolded`, `search`, as `ego.md` holds them on 2026-11-22) and the
  component fields sit in ONE slate. A separate "ego canvas"
  note beside `ego.md` repeats "ego" -- the duplication 54 ruled out.
- **At the centre of view** (183, the standing goal): the canvas is the plane's
  central panel, and the plane is fixed to the camera at a constant distance
  from the HUD (159).

### 12d. Links: from compilation only

- **Hard links come only from compilation** (136, 142): one record references
  another "in any possible way" -- a `{ref}` in a slate or on a fence line, a
  name a cell defines and another reads (marimo-style def/use, G-380, §5a), a
  terminal call, two records attached to one chunk object. They are drawn
  undirected (170.2, O.16); the direction is computed, not drawn. They are
  solid when active, translucent when toggled off with a right-click (135d).
- **Magnetism is placement and order, never a hard link** (136, 142, T-11).
  142 calls it "a temporary link for compilation serialization": it lasts
  while the nodes touch, is never drawn, and is never written. It
  serialises compilation, rows top to bottom then left to right, and gives a
  chat cell its context (T-2).
  T-11 adds what it carries: "A terminal's or kernel's output is an input to
  the next cell in that order", so magnetism passes a READOUT (the output
  as it stands in its note, B6) along the order, whichever notes the cells
  belong to. Built so far for one reader only: a chat's context
  (`planepanels.ts`, `chatContext`), which reads the magnetised notes' text
  in compile order.
- **A plain `[text](url)` or wiki link is a plain link** (T-4), not a
  computational one. `[query](results)` is retrieval.

### 12e. Computation, tools and agents -- the same records, run and called

- **Cells are function nodes** (RESERVOIR §4): a fence's `{ref}`s are its
  inputs, bound into the note's kernel before the run; the run is the forward
  call, recorded (`FORWARD_MAPPED_TO`); the output written into the note is
  the readout. A `{ref}` to an iterable runs per sample: the rollout.
- **Dataflow** (G-380): marimo's rules over the slate's names. An edit marks
  stale exactly what reads it. A world-changing call returns a value that
  names what changed (§8).
- **Every thing has a governing class** (T-10, 142): about 25 lines whose
  public methods are its capability list. Its markdown control panel is
  generated from those signatures as typed fields, and an instance is a
  separate record linked to its class (89). A tool panel is that class
  revealed read-only, calls only, the body never shown (167 c, F.5-F.6,
  G-378). The browser's is built (`domvec/governing/browser.py`). The §8
  tool surfaces are a different grain: one per TOOLSPACE, listing the calls
  on those classes and globals (§13m).
- **Black boxes all the way down** (80, 112, RESERVOIR §12.4): a `{code://...}`
  field reveals its module's rank-1 definitions, each again a field, down to
  the compiled base. The reveal is the one in 12a, nothing separate. It
  unfolds workspace code and installed libraries only; an app tool shows its
  rows and stops (§13n, boundary 2).
- **The agent** (170.3, §10b-§11d) runs as smolagents steps. Each step is one
  code cell appended to a note, its observation that cell's output. Its
  context is the canvas read in compile order, each field as deep as it is
  revealed (rank-1 minimalism, N.14). Its editor calls (`create`, `link`,
  `invoke`, `commit`, `review`) are the reader's own gestures.
- **Chat** (182) is ONE note holding its turns: each turn's prompt, prose and
  each code block are addressable chunks of that note (182's answer, G-394),
  and a code block carries the code-cell tools and typed
  rows wherever it is drawn (182 addenda, G-395).
- **Browsers** (T-5, 72, 137.4): a chunk is a browser cell framed to the chunk,
  plus its markdown cell, both attached to one chunk object in code. The scope
  ladder runs chunk -> group -> page -> browser (wheel over the header, T-9).
  A browser field revealed in the canvas shows its governing fields, and its
  live rendering at the field's scope (185: "similar seamlessness rendering
  markdown chunks and browsers in their canvas views").

### 12f. 3D: the same records, in flight

- The ego is its OWN UMAP (76, 146), compact (149), drawn "exactly as world":
  glowing nodes for its records and chunks, links for its compiled references
  (183), "one uniform display of node and links" (158). The craft's circles
  and dashed edges are the "deprecated node-based graph view artifacts" (186),
  retired by 182 and 183.
- A hovered node billboards its record revealed to its level: higher rank,
  more of the tree (183).
- **In flight vs stuck** (RESERVOIR §5, 159): double-click a linked node and
  the ego flies until the camera plane meets it; at that intersection the
  record becomes a placement on the 2D plane. Relegating it folds it back into
  flight (183).
- Readouts go on the perimeter with their bisector (G-282). Per 76, readouts
  belong to the EGO's projection, not the world's shell (RESERVOIR §10.4
  already notes G-282's placement as superseded). Signal flow is drawn as
  light (99, 114).
- The vehicle is non-holonomic, with first and third person views, always at
  the centre of view (116, 146).

### 12g. What my 183-185 slices got wrong against this record

| built | the record | so |
|---|---|---|
| a separate note `domvec/ego canvas.md` beside `ego.md` | 54: one ego, the duplicative part fused | the canvas fields go INTO the ego slate |
| `![[x]]` contained / `[[x]]` pulled out, rewriting the line on each gesture | O.1a: a brace's three states are fold state; the text stays `{x}` | `{x}` fields; state in the fold record |
| nested Obsidian leaves in a card (184), seamless CSS over them (185) | 12b: revealed-internal is the target's lines inline in the same grammar | reveal, editable in place; no nested editors |
| fold triangles, "nested" and "in canvas" chips, hover tools | 186, 158 | removed |
| G-399: a card dropped on a card writes a wiki link | 136: "magnetizing new panels together doesn't create new links" | reverted. It corrupted the canvas note with `[[browser]]` x3 |
| G-398: lines drawn between notes that share a wiki link | 136, 142, T-4: lines come from compilation | lines drawn from `{ref}`s and def/use |
| the craft's circles still drawn in 2D and 3D | 182, 183, 186 | hidden now; G-400 draws the ego as world nodes |

### 12h. Build order

| row | slice | rests on |
|---|---|---|
| G-401 | the ego slate holds the canvas: one field per component, `name {ref}`, in compile order, seeded from the tool space (158); the separate canvas note and the nested-leaf machinery removed; braces kept, state in the fold record | 54, O.1a, 186 |
| G-402 | revealed-internal is EDITABLE: a revealed line of a vault record is edited in place and written to its own record; a web chunk's reveal stays read-only (151) | M.8, 104, 151 |
| G-403 | resolved-external: holding a field past the debounce and dropping it on the plane opens the record as a panel and folds its braces to external, with a solid line; dropping the panel back on a field line reveals it again; one placement open | 182, 184 a, O.1a |
| G-404 | links from compilation only: G-399's card-on-card link reverted; the plane's lines drawn from `{ref}`s and def/use, undirected, with the right-click toggle | 136, 142, 135d, 170.2 |
| G-405 | the craft's circles and dashed edges gone from 2D and 3D (plant restores them); then G-400: the ego as world nodes on its UMAP, billboards by level, double-click flight to the plane | 182, 183, 159 |
| G-406 | a code field revealed carries its cell tools and typed rows; a tool field reveals its governing class's ~25 lines; an agent step appended as a cell | 182, T-10, 170.3 |
| G-407 | a browser field revealed draws its governing fields and its live rendering at the field's scope, seamless with the surface | 185, T-5, T-9 |

## 13. The 2D graph editor after 187 -- established live-object APIs and an existing node editor, integrated with the whole record (2026-11-22)

187: "favor established APIs and packages for the graphical and interactive
code structures rather than our in-markdown syntax ... the 'graphical' side
is the graph editor for python modules and similar pre-existing permissive
github repos". Then twice: "do thorough research to integrate the new ideas
with your current research on the docs and the design for our 2D graph
editor".

**Read for this section, in full:** this spec §1-§12; `RESERVOIR_DESIGN.md`
(all, §1-§12); `GRAPH_WORKBENCH_DESIGN.md`; `DESIGN_VISION.md` with its
rulings (4b, 4c); `SEARCH_GRAPH_DESIGN.md`; `NOTEBOOK_PANEL_DESIGN.md`;
`THROUGH_STACK_SYNTHESIS.md`; `EGO_CANVAS_DESIGN.md`; the head of
`CALLABLE_INTERFACE.md`; PLUGIN_GOAL's verbatim from 2026-10-29 through 187;
mortegon's UR §E, §F, §M-§T; the PRD rows G-277..G-400. External pages read
are listed at the end. The cross-check (§14) has since read on through 191
and every prompt of the session (§14a). Where the text below says "reading" it is mine.

**How items are cited in §12-§14.** PLUGIN_GOAL's item numbers restart in
each series (the rule at the head of this spec). A bare number cites the
series that opens at PLUGIN_GOAL's "**2026-10-29**" (the reservoir prompt)
and runs to 2026-11-22: items 1-152 in its running text, 153-191 under dated
headings. Older series reuse most of those numbers (e.g. Addendum X's 133,
and Addendum XI's (2026-10-18) 162-186), so a citation of an older series
always carries its date, e.g. `(2026-10-18) 186c`. A message from either
"Recovered verbatim" inventory has no number and is cited by its UTC date
and time, e.g. `2026-11-08 17:43`. UR, DM and BS are
mortegon's documents. B1-B21 refer to §13a, and T-1-T-17 to DESIGN_VISION §4.

### 13a. What binds the 2D editor -- the record, gathered

Every row is the reader's own words or a ruling on them. 187 replaces none of
them except where it says so, and recency decides any conflict (item 124).

| # | commitment | source |
|---|---|---|
| B1 | ONE record, many placements -- never copies kept in sync | 37, R.1, O.19, RESERVOIR §5 |
| B2 | the two sides COMMUTE: an edit in either round-trips losslessly (R.1). Since 182 the two sides are the CODE and the GRAPH editor; the old panel/graph-form flip is retired (B12) | R.1, O.1, 135b, 182 |
| B3 | hard links come ONLY from compilation (a name defined and read, a `{ref}`, a terminal call, one chunk object); magnetism is a TEMPORARY link (142's word) for compile order: never a hard link, never drawn or written | 136, 142, T-4, T-11 |
| B4 | links are drawn UNDIRECTED, no arrowheads; the direction is computed | O.16, 170.2, G-383 |
| B5 | dataflow is marimo-style: dependencies read statically from definitions and reads; running re-runs the readers | 167 f, G-380 |
| B6 | cells run in the note's real Jupyter kernel; outputs live IN the markdown (trie content, one source of truth) | 49, NOTEBOOK §1, §4b |
| B7 | every thing has a governing class of ~25 lines whose public methods are its capabilities; class and instance are two linked nodes | 142, T-10, 89 |
| B8 | a TOOL panel is read-only, calls only, "implicit calls into the world itself"; a REGULAR code artifact is callable the same way AND explorable and graph-editable | 167 c, F.5-F.6, G-378 |
| B9 | a Python object enters as typed rows `name: Type = value`; a function is memory lookup to its inputs, its output type inferred by wiring | M.2-M.5, E.6, O.15 |
| B10 | the ONE markdown panel (Obsidian's own, extended) for every markdown surface: prose notes, slates, chat, the clipboard (§12b) | 56, 133 c, 140 |
| B11 | a code artifact has ONE interface -- run, terminal, open, unnest, typed rows -- wherever it sits | 182 addenda, G-395 |
| B12 | the graph-view FORM goes; the nodes are the interactive typed artifacts themselves; in 2D only interface canvases, no circles | 182, 183 |
| B13 | no special effects; one uniform display of node and link | 158, 186 |
| B14 | gestures: a single click in a body edits in place, on a title opens the halo (T-8); right-click reveals/folds; right-click on the title (mortegon's "base node", the header) collapses the record to its node; double right-click deletes a link or reference; a press held past a debounce picks up, never a plain click | M.6-M.8, N.13, 110, 182 |
| B15 | the plane is fixed to the camera; shift-scroll zooms the 2D plane, plain scroll the 3D view; the ego at the centre of view | 158, 159, 146 |
| B16 | rank-1 minimalism; black boxes unfold recursively down to the base modules | N.14, R.3, 80, 112 |
| B17 | the base toolset: browser, database retrieval, code/kernels, terminals, chat | 166, 187 |
| B18 | signal flow is visible as light, in 2D and 3D | 99, 114 |
| B19 | the agent loop is smolagents' step; each step a cell | 170.3, G-384 |
| B20 | the bar: complex quantized-model workflows, custom tools written on the fly, in the same editor | 166 d-e, 187 |
| B21 | two kinds of code tool on canvases: APP tools, calls only, dependencies never visible; WORKSPACE code, fully explorable (§13n) | 167 c, 189 |

### 13b. What 187 changes

187 changes two things, and the rows above decide everything else.

1. **A code object's interactive form is an established API, not our
   markdown grammar.** "Python objects that can be interacted with in this way
   that is more structurally verbose and more well informed than our
   syntactic approach". The standard for a Python object with live, typed,
   observed state, drawn as its own interface and usable from code and a
   terminal, is the **Jupyter widget** (traitlets on the Python side, the
   kernel's comm channel between) with **anywidget's AFM** as the front-end
   contract (§13e).
2. **The graphical side is an existing node editor**, not the plane's own
   drawing (§13c).

187 names its precedent: "similar to how we tried with our ego card, but of
course generalized to code objects". That is the cockpit slate bound both
ways to the agent and the search (G-280, RESERVOIR §6): editing `view`
switches the camera, and Shift/Ctrl write `throttle` back into the text. A live object is that two-way binding,
made standard and given to every code object. The cockpit stays a slate
(B10).

What 187 does NOT change: B1-B11 and B14-B21. The slate grammar stays the
form for PROSE notes and the cockpit, which are markdown (B10). 187 scopes its
change to "the graphical and interactive code structures".

### 13c. 182/183 and 187 are one requirement

On the surface they conflict. 182 and 183 took the node-graph FORM out of 2D
("completely do away with the 'graph view' form", "circles gone in 2D", "in
the 2D plane, we deal only with the interface canvases themselves"). 187 puts
a node graph editor on it. Read together they are one requirement, and
182 says which: "the nodes are the interactive typed artifacts themselves ...
in fully interactive and uniquely toolable form".

What 182/183 retired was the ABSTRACT node: a circle standing for an artifact
drawn elsewhere (G-281's graph form, the craft's circles). An editor in the
ComfyUI lineage has no such node. Each node IS the object's interface: its
inputs as sockets, its parameters as inline widgets, and its preview (an
image, a text, a live DOM element) in the node's own body. So:

- **a node on the plane is the object's canvas**, with ports on its edges. It
  is never a circle (B12, B13);
- **folded to its title** (litegraph's `collapse()`), it is the
  panel-and-node fold parameter of item 110. That is the only "node form"
  left, and it is the same record folded (B1);
- **a slate on the plane** is the same: the one markdown panel (B10) as a
  node body, with ports for the names its trees define and read (a slate tree
  is a cell, `dataflow.py`). A plain prose note defines no names and has no
  ports. It is a panel on the plane, as before.

This is the plane 183 described: interface canvases joined by links, where
the links are now the editor's own.

### 13d. One source of truth, three projections

The text of the note -- its markdown, its code cells and their outputs -- is
the only stored truth (B6, NOTEBOOK §1's "two sources of truth" argument). The
graph editor's own JSON (`graph.serialize()`) is **never stored as authority**.
It is rebuilt from the note, and a gesture on it is written back into the note
as text.

**Rebuilt in O(delta), and timed.** The binding goal asks for O(delta) and
for each phase timed on its own (CLAUDE.md: the goal paragraph, and constraint 4). Today
`dataflow.graph(text)` re-parses every cell of the note on each call, which
is O(cells), not O(delta). For the editor, an edit re-parses only the cells
whose `exact_hash` changed (constraint 5b: a projection keys on the exact
hash). It re-joins edges only over the names those cells define or read,
and redraws only those nodes and links. One input lies outside the cell
(constraint 5c): a slate tree's refs depend on which names the rest of the
note defines. So a change to the note's set of defined names invalidates
every slate tree that reads one of those names. The editor's rebuild is
its own timed phase, beside the fold and the projections.

| projection | built from | written back by |
|---|---|---|
| **code**: the cells and the terminal | the note's text, run in its kernel (B6) | the reader typing |
| **object canvas**: a live object's own widget | the object's traits over the comm (§13e) | `model.set` + `save_changes` -> the trait in the kernel |
| **graph**: a node per cell (the grain below); a link per def/use edge | `dataflow.py` (B5) plus port definitions (§13d') | a drawn link becomes a line of code through LibCST; a deleted link removes it (§13f) |

**The grain of a node is the CELL**, because the cell is the unit the
dataflow knows (`dataflow.py`: a cell's defs and refs; one definition per
name). A cell node's rank-1 ports are its refs (in) and its defs (out). Two
kinds of cell give the editor its typed ports:

- **a call cell**, one binding of a callable or a class: `hits = search(query,
  k=8)`. Its inputs are the callable's parameters (§13d'), and its output is
  the name it binds. Placing a node from the retrieval bar writes a new call
  cell with the defaults (into which note is O-5). This is the ComfyUI-like
  node.
- **any other cell** (a function body, a class, a script, a slate tree). Its
  ports are its plain refs and defs. Unfolding one of its defs reveals that
  definition's typed rows (§13d'), which is the black-box unfold of 80 and
  112, at rank-1 (N.14).

A live object is the output of the call cell that made it, and its traits
are rows of that node. One more node is not a whole cell: a slate field
resolved external (§12a) is drawn as its own node for as long as it is
resolved. It is a placement of a row of its slate's cell, and its ports are
that field's `{ref}`s and its sub-fields (the search node, §13h).

In trie terms: the note is a `vault://` page and its cells are addresses on it
(`#cell n`, item 159). A node is a projection of one address. A link is a
def/use edge between two addresses, computed and never stored, and a widget
value is a literal argument of a call cell, at that cell's address. A live
object's trait is kernel state, reported into its cell's output (§13e).

What the editor keeps itself is PLACEMENT only: each node's position, size
and fold. It is kept the way the plane already keeps its panels' places,
keyed by the cell's address. Edges, ports and values are never kept, because
they are read from the note. Placement still matters: magnetised nodes are
read row-major for compile order and for a chat's context (T-2, T-11). That
is order, a temporary link in 142's word, never a hard link (B3).

**The note is the boundary of def/use.** Each note has its own kernel
(`kernel.py` keys kernels by note) and its own dataflow (`dataflow.py` reads
one note's cells). So a def/use link, and §13f's write-back, join two cells
of ONE note. Between notes the record has one HARD link: a `{ref}` on the
reading cell's fence line (12d, G-279), which binds the named RECORD,
resolved before the cell runs, and never another kernel's value. A link
drawn from cell n of note A to a node of note B therefore writes
`{A#cell n}` on B's fence line. That is the cell address the outline already
uses (`refs.py`: `{Note#cell 2}`), and it binds that cell's record: its
source and its readout. A fence-line ref resolves only note and page TITLES
today, so a cell address there would fall through to retrieval's top hit
(O-6). The plane today makes every new panel a new
note (`planepanels.ts`, `create`, under `domvec/graph/`), so this boundary
decides what most drawn links on the plane can mean. Passing a VALUE between
notes, and so which note a node placed from the retrieval bar is written
into, is not settled by the record (O-5). The record does give two paths
across notes, and both carry a record or its readout: the hard link, a
fence-line `{ref}` (G-279; T-4 and T-6: `{ref}` resolves through "the kernel
namespace" by trie address), and magnetism's temporary link, whose order
passes a cell's output to the next (T-11, §12d). What neither carries is a live Python
object: a value that exists only in one note's kernel. A third path is a reading, not
the record: §9a and §10a read 166 e ("lightweight and modules composition of
python programs") as a note CALLED like a function, its free names in and
its definitions out (marimo's `app.embed(defs=...)` shape). That would carry
values across notes without one shared kernel. It is "not started" (§10a),
and is one of O-5's options.

### 13d'. Ports from Python -- the node-definition layer

Every editor in the ComfyUI and Langflow lineage has the same layer. The
backend publishes a definition per node type, read from a Python class, and
the front end registers node types from it. ComfyUI's `/object_info` returns,
per node: inputs, outputs, `output_is_list`, `output_node`, and the input
order. Langflow's `Component` lists `inputs` and `outputs`, each output named
for the method that computes it. Mortegon's M.3 typed panel is the same
information written as rows. **The three are one schema**, and B7/B9 already
fix ours.

| ours (B7, B9) | mortegon | ComfyUI | Langflow | in the editor |
|---|---|---|---|---|
| a function's parameter of a primitive type, with a default (`k: int = 8`) | `k: int = 8` row | an input WITH options (`("INT", {"default": 8})`) | `IntInput` | an inline **widget**, edited in place (B14) |
| a parameter of an object type, or a `{ref}` value | `driver: WebDriver = {driver}` | a bare-type input (`("IMAGE",)`), socket-only | `HandleInput` | an input **socket** |
| a `Literal[...]` parameter | -- | a combo list | `DropdownInput` | a combo widget |
| the return, annotated | `scanner: {FunctionOutPutType}` | `RETURN_TYPES` | `Output(method=...)` | an output socket, its type from the annotation, else inferred by wiring (M.5, O.15) |
| a governing class's public method (B7) | a function node of the object (F.5) | -- | one `Output` per method | an output socket per method; linking it writes `b_in = a.method()` into the reading cell, so the method runs when that cell runs |
| a trait of a live object | a property row (F.5) | -- | -- | a widget mirrored over the comm, or a socket when linked |
| read-only tool class (B8) | `read_only`, `no_datablock` (F.6) | -- | -- | a node with sockets and no body code to open |

The rule a widget-vs-socket choice needs is ComfyUI's, and it matches M.3. A
primitive with a value is a widget. A type a value cannot be typed into is a
socket. `force_input` turns a widget into a socket, which is exactly
mortegon's "a literal row becomes `{ref}`".

**Where the definitions come from:** the kernel, not a registry. A sidecar
route asks the note's kernel for `inspect.signature` and `typing.get_type_hints`
of every function and class the note defines, plus the traits of every live
object (`HasTraits.traits()`). The plugin registers node types from that
answer, so a function written in a cell is a node the moment the cell runs.
That is "custom made code tools on the fly with the same editor interface"
(B20), and it is ComfyUI's `object_info` sourced from a live namespace
instead of a plugin directory.

### 13e. Live objects: the comm bridge and the AFM host

**The protocol, as specified.** An ipywidgets model is a comm with target
`jupyter.widget`. `comm_open` carries the state, `comm_msg` carries
`method: "update"` (state deltas), `"custom"` (free messages) or
`"request_state"`, and `comm_close` ends it (the ipywidgets message spec,
protocol version 2). anywidget objects are ipywidgets models whose front end
is the AFM module in the `_esm` trait (a string or a file path; `_css`
optional and loaded globally).

**The AFM contract a HOST implements** (anywidget's AFM page, the spec as of
anywidget 0.11). Each item is a MUST:

1. load the module as an ES module;
2. implement `AnyModel` per instance -- `get`, `set`, `off`,
   `on("change:x")` (no arguments), `on("msg:custom", (msg, buffers))`,
   `save_changes`, `send(content, callbacks, buffers)`;
3. run `initialize({model, signal})` once per instance and await it before
   any `render`;
4. run `render({model, el, signal, host})` once per view, so several views
   may share one model;
5. abort `signal` when the instance is destroyed or the view removed;
6. run any returned cleanup when its signal aborts;
7. keep a registry of bindings keyed by model;
8. resolve `"anywidget:<model_id>"` through `host.getWidget` and
   `host.getModel`;
9. cascade teardown to child views.

A hook that throws fails that phase: abort, and report it.

**What it means here.**
- *Views are placements* (B1). Two views of one model are the AFM's own case
  (the fourth obligation above), so an object's canvas on the plane and its billboard in 3D are
  two `render`s of one model. Nothing is copied.
- *CSS goes in a shadow root*, as marimo hosts it. The AFM loads `_css`
  globally, and Obsidian's own styles are global too (B10), so a widget's CSS
  must not leak into the app.
- *A trait change is a dataflow event.* marimo's rule: "When a UI element
  assigned to a global variable is interacted with, marimo automatically runs
  all cells that reference the variable (but don't define it)". In ours, a
  `change:` from a view sets the trait in the kernel. `dataflow.rerun_plan`
  then runs the cells that read the object's name (B5), and their outputs
  re-render (B6). This closes a gap the dataflow has by itself. A trait set
  in place is a mutation, and marimo's rules, like `dataflow.py`, do not see
  mutations (§5a). marimo closes it for widgets with an explicit wrapper. Here
  the comm bridge plays that part: it reports which object changed, and the
  dataflow treats that report as a fresh definition of the object's name.
- *Where a live object's state lives* (B6). Its traits are kernel state, as
  every variable is. What reaches the note is the cell's output: a text
  snapshot of the traits (trie content, retrievable, NOTEBOOK §6 steps 4-5) and the
  view's identity, so reopening the note can find the live object again
  while its kernel lives. Jupyter keeps widget state in the notebook's
  metadata, and this keeps it in the output block. Reading.
- *The terminal sees the same objects* (187 "terminal use"). A trait set from
  a terminal call into the kernel (`w.value = 3`) emits `update`, and every
  view redraws.

**The bridge that has to exist** (measured in `domvec/obsidian/kernel.py`):
`_JupyterKernel.run` reads iopub only while a cell runs, and keeps `stream`,
`execute_result`, `display_data` (text/plain) and `error`. It drops
`comm_open`, `comm_msg` and the widget mimetype
`application/vnd.jupyter.widget-view+json`. So: an iopub reader thread per
kernel that keeps comm traffic at all times; a comm log with a sequence
number that the plugin long-polls; and `comm_msg` sent back on the shell
channel. `/chat_stream` is the only push channel today: one HTTP response
held open and flushed per token, which fits a turn that ends. A comm lives
as long as its kernel, so the plugin long-polls the comm log by sequence
number instead, and a dropped poll resumes from the last number it saw.
Either way the plugin opens the request; the sidecar never calls the
plugin.

### 13f. Links: drawn, compiled, undirected

- **A drawn link is code** (B3), written into the READING cell (node B's
  below), never into a new one. Within one note, as here; across notes it
  is a fence-line `{A#cell n}` instead (§13d). Dropping A's output `hits` on B's input `items` rewrites one
  argument of B's call cell: `summary = summarise(items=hits)`, where the
  argument was a literal (a widget) or another name. For two live objects, B's
  call cell gains one binding line, `b.x = a.y`, or a two-way trait link where
  both are live. The edit is lossless through LibCST (installed). The edge
  then exists because B's cell reads a name A's cell defines; it is the
  dataflow edge, not a stored link. A link that would not compile, or would
  close a cycle (`dataflow`'s cycle error), is refused and never drawn.
- **A deleted link removes its line.** A double right-click on the link does
  it (N.13).
- **Undirected** (B4). litegraph's `render_connection_arrows` defaults to
  `false`. Its ports still sit left (in) and right (out), which is direction
  in placement only, the computed direction 170.2 allows.
- **Active vs off** (135d): a right-click on a link toggles it solid or
  translucent. Off means the binding line is commented out, so the code view
  shows the same thing.
- **The editor never executes.** litegraph's `onExecute` / `runStep` engine
  is not used. The kernel runs (B6) and the dataflow orders (B5). ComfyUI's
  own caching is the same idea as ours, under other names:
  - "only executes nodes that might produce a different result" is the stale
    set;
  - ComfyUI re-runs a node whose inputs or widgets changed (`IS_CHANGED` /
    `fingerprint_inputs` refine that). Ours re-runs a cell whose source changed
    (its `exact_hash`, NOTEBOOK §4) or whose upstream re-ran (the stale set);
  - `not_idempotent` is §8's world-changing call, which must return a value
    naming what changed.
- **Signal flow as light** (B18): a run lights its node and pulses its links.
  That is G-321/G-331's pulse, drawn on the editor's links.

### 13g. The editor on the plane -- litegraph's defaults against the record

| litegraph default | the record | so |
|---|---|---|
| wheel zooms the canvas | plain wheel zooms 3D; shift-wheel zooms the plane (159) | `processMouseWheel` acts only with shift |
| right-click opens a context menu | right-click reveals/folds; on the title, folds the record to its node (B14) | `processContextMenu` replaced: title -> `collapse()`; a row -> its reveal |
| clicking a link opens a menu | double right-click deletes, right-click toggles (N.13, 135d) | link handlers replaced |
| a node drags at once | a press held past the debounce picks up; a click edits (182) | drag starts after the hold |
| node shapes: box, round, card | one shape (158, 186) | one shape, no per-kind decoration |
| dark grey theme | node bodies are Obsidian's own panels (56, 184); a slate keeps its slate class (G-278) | links, ports and titles take Obsidian's theme colours; nothing else is styled |
| its own pan and zoom | the plane is fixed to the camera at a constant distance, with the ego at the centre (159, 146) | the plane does not move with the 3D camera. The editor's pan and zoom ARE the plane's: shift-wheel zooms and a drag on empty plane pans. The 3D camera moves only the world behind it |
| search box on double-click | new nodes from the retrieval bar over typed nodes (133 d) | the searchbox fed by the retrieval bar's typed nodes |
| a click selects | a click on a node's TITLE opens its halo (T-8, 81); a click in its BODY edits in place (M.8) | title click -> the halo; a double-click on the title opens or folds the node (T-8), the same fold as the right-click on the title (M.6, 110), two ways to one action; body clicks reach the body |
| groups (a framed region holding nodes) | the containment gesture: Alt+click gathers the folded nodes linked to a node (111, G-327) | containment IS a group, made only by that gesture; "linked" means hard links (§12d), never wiki links (T-4; the app still reads wiki links, O-7) |
| no edge snapping | magnetism: nodes snap on bare edges, setting compile order row-major and a chat's context, a temporary link, never a hard link (134 c, 136, 142, T-2, T-11) | snapping added, as ONE settle when a node is released (below); order read from it; no line drawn |
| node size by its content | Ctrl+= / Ctrl+- resize a notebook (133 h); a panel sizes to what it shows (110) | sized to content; the keys scale the selected node |

**DOM in a node.** A litegraph widget is drawn on the canvas. An Obsidian
editor and an AFM view are DOM. ComfyUI's legacy front end (its DOM-widget
script, read from mirrored copies, not current source) overlays DOM widgets on
the canvas and re-places them from the canvas transform each frame, hiding
them below a zoom threshold. The pattern does not depend on their current
code. The panels on our plane are already DOM over the
3D canvas (`planepanels.ts`), so the same placement applies: a node's body is
its DOM, positioned by `ds` (the canvas's DragAndScale). Reading: below
the zoom threshold the node shows its title, which is the fold parameter of
item 110, not a separate mode.

**Nothing on the plane moves by itself.** 141 (2026-11-08) rules motion
for the layout: "a singular post-process that ensures stability/convergence
on constraints within a limited time bound", not "gaseous chunks moving
erratically forever". Two recovered messages from the same day (2026-11-08
17:43 and 18:33) name the cost of breaking that: "significant and severe
lag", and "jostling when there wasn't before". On the plane that means:
- a node moves only while the reader drags it;
- magnetism is ONE settle when the node is released, done within a fixed
  bound, and then nothing moves;
- the editor redraws, and re-places its DOM bodies, only when a node, a
  link or the plane's pan and zoom changes, never every frame;
- the idle drift turns the 3D camera and cycles the 3D colours (T-12, 150;
  "rotates both cartesian and color coordinates", DESIGN_VISION 1.2). The
  plane is fixed to the camera, so the drift never moves a node, and the
  plane's nodes and links take Obsidian's theme colours, which do not
  cycle.

**The gesture help** (159: "a hoverable button that expands into a full
panel of instructions on the gestures on the 2D computation graph") lists
exactly this table's "so" column, so the help and the editor cannot
disagree. It is a panel only while it is hovered and folds back to its
button when the pointer leaves. A readout that stays open over the view is
the defect the reader reported at 2026-09-24 05:04: "The logs on the panel in the
3D graph now cover the actual UI view".

### 13h. The base tools as live objects -- chat first

Each base tool (B17) is an APP tool (§13n) and ONE live-object class. Its public methods are its
~25-line capability list (B7). Its traits are its state, and its read-only
class listing is its tool panel (B8). `kernel_objects.py` already boots
`search`, `Database`, `WebBrowser`, `Agent`, `Vault` and the editor calls
(`create`, `link`, `invoke`, `commit`, `review`, `answer`) into every kernel,
and `domvec/governing/browser.py` is the first governing class. Each becomes a
traitlets object with an AFM view.

**Chat first**, because 187 says chat models force the standard:
- `Chat(model, tools)` holds `messages` as a trait, as a mirror only. The
  chat note's turns are the record (182, G-394; §13d: the note's text is the
  only stored truth). The trait is loaded from the turns, and each turn is
  written back into the note as a `## You` / `## <model>` turn;
- its view is the conversation: a clear input box and typed blocks (G-394),
  each code block a cell with the one code interface (B11). It is ONE view
  in three hosts (182: "One component, three hosts"): the browser strip, the
  notebook chat and the plane's chat note. Each host supplies only the
  context -- pinned web chunks, the rewound cells (T-2), the magnetised
  panels -- as an input to the call, never as chat state. G-394 built the
  plane's host; the other two are still their own (PRD G-394);
- tokens stream as `custom` messages, the protocol's free channel (171).
  The tokens themselves come from the stream that already exists: the
  sidecar's model on CUDA (G-385, seen live under load) and the chat panel it
  was wired into (2026-11-22 01:19: "wire the token stream into
  the app's chat panel"; G-394). The comm is a second hop for the same
  stream, not a second model or a second stream. G-385-load's bar (gap p50
  under 30 ms while the embedder runs) holds for the token as the VIEW
  receives it, not only as the sidecar sends it;
- the callback is marimo's `mo.ui.chat` shape: `model(messages, config)` may
  be a generator that yields DELTAS, which the view accumulates; a Stop
  cancels it (sync generators get `GeneratorExit`, async ones
  `CancelledError`);
- the agent is smolagents' `CodeAgent` (B19): each step is a cell, and a
  tool defined in a cell is a node on the plane AND a tool the agent is
  handed in the next step (B20);
- a block, or a selected range of lines, dragged off a turn (after the
  hold, 182) becomes its own node, linked back to its source address and
  usable in retrieval and dataflow (182's answer "Select + drag").

**The search node** (164) is the cockpit's `search` field (`ego.md`: `query`,
`db`, `duckduckgo`, `where`, `k`, `n`, `results`). It is drawn as its own
node on the plane by resolving that field external (§12a, G-403), a
placement of the same record (B1). It is a slate field, not a call cell,
because the cockpit stays a slate (§13b). Its fields have the shape a call
cell's widgets have, since they are the arguments of the `search` app tool,
and `results` is its output. Its output links run to the results, which
are chunks, not cells. So each is a `{ref}` from the
`{results}` brace to that chunk (12d), drawn to the result's node when it is
on the plane and recomputed with every search, never stored ("Live search
only", 164).

### 13i. What stands from §12, what this replaces

| §12 | after 187 |
|---|---|
| 12a one record, placements | **stands** (B1). The placements gain the object canvas (§13e) and the graph node (§13c) |
| 12b one panel, the grammar, gestures, no effects, edit in place | **stands for prose and slates**. The gestures map onto the editor (§13g) |
| 12c the ego canvas is the ego slate's fields | **stands as the cockpit's record**: its fields order the ego's components (compile order, 142). A PROSE component still reveals inline (12a). A code-object component is a node on the plane |
| 12d links from compilation | **stands**, made concrete by §13f |
| 12e governing class, tool panels, agents, chat | **stands**, each made a live object (§13h) |
| 12f 3D | **stands**: a 3D billboard is one more `render` of the same model |
| 12h G-401 (fields in the ego slate) | written, uncommitted, deployed 2026-11-24 (PRD Partly; O-3); stands for the cockpit |
| 12h G-402/403 (reveal editable; resolved-external drop) | **superseded for code objects** by the object canvas and the editor's nodes; stands for markdown records, prose notes and slates alike (B10), so for the cockpit's fields too (the search node, §13h) |
| 12h G-404 (links only from compilation) | **stands** |
| 12h G-405 (the craft's circles hidden) | **stands** |
| 12h G-406 (code field reveals tools and typed rows) | **superseded** by §13d' (typed rows ARE ports and widgets) |
| 12h G-407 (browser field reveals its rendering) | **superseded** by the browser as a live object (§13h) |

### 13j. Packages -- what can be used, and what each needs

| package | licence | state (checked 2026-11-22) | for |
|---|---|---|---|
| `anywidget` | MIT | active; the AFM spec at 0.11 | live objects' Python side; pulls `ipywidgets` (BSD-3) |
| `@comfyorg/litegraph` | MIT | **archived**. Merged into `Comfy-Org/ComfyUI_frontend` (`src/lib/litegraph`) on 2025-08-05, and that repository is **GPL-3.0**. The npm releases published before the merge are listed as MIT, but no release's own licence file has been read yet (O-1) | the graphical side, in TypeScript |
| `litegraph.js` (jagenjo) | MIT | 0.7.18 the latest on npm; not confirmed maintained | the same, in JavaScript |

So: **code is never taken from ComfyUI_frontend's tree** (GPL-3.0). The
editor is a pinned litegraph release, its MIT licence read in the release
itself before it is vendored into the plugin (O-1).
Reading: the last standalone `@comfyorg/litegraph`, because it is TypeScript
like the plugin and carries ComfyUI's widget work, frozen and owned here from
then on.

Every row above is a download, so each waits for a yes. The litegraph rows
stand under 194 (g), for code cells.

### 13k. Build order -- each a live check with a planted arm

| row | slice | proof (live) | planted |
|---|---|---|---|
| G-408 | the comm bridge: an iopub reader per kernel; a comm log with a sequence number, long-polled; `comm_msg` back on the shell channel | a comm opened by a cell is read in the plugin; a `comm_msg` sent from the plugin changes a value read back in the kernel | the reader off: the comm is never seen |
| G-409 | node definitions from the live namespace (§13d'): signatures, hints, traits | a function defined in a cell appears in the definitions with its ports; a default primitive is a widget, an object type a socket | hints ignored: every input a socket |
| G-410 | the AFM host in a plane panel (a node body once G-411 lands), per the nine MUSTs | an anywidget made in a cell renders; set from a terminal, the view updates; set in the view, the kernel reads it; two views, one model | `save_changes` dropped: the kernel never sees the view's set |
| G-411 | litegraph on the plane: nodes from G-409, links from def/use, gestures per §13g, no arrowheads, one shape | the graph's links equal `dataflow`'s edges; an edit to one cell re-parses that cell only (rebuild timed as its own phase); a drawn link within a note writes one line (across notes, one fence-line `{A#cell n}`, §13d, which waits on O-6), a deleted one removes it, a cycle is refused | a link drawn without the write-back: the code and the graph disagree |
| G-412 | `Chat` as a live object (§13h) | tokens stream into the view, gap p50 under 30 ms at the view (G-385-load's bar); a code block runs as a cell; a tool defined in a cell is called by the agent | deltas accumulated in Python: the view gets whole messages |
| G-413 | the base tools as live objects: Search, Browser, Terminal, Kernel, from their governing classes | each tool panel lists its class read-only; an instance's trait changes re-run its readers | the dataflow event off: readers stay stale |

G-408 and G-409 need no download. G-410, G-412 and G-413 wait on §13j's
`anywidget`. G-409 and G-411 stand under 194 (g), over code cells; a
slate's fields are no longer their nodes (head note). G-410's host is a
plain panel or a code cell's node (my reading of 193 (a) and 194).

A slice lands only with the plugin's existing live checks still passing:
"I need something like this to work with our whole plugin without
degrading the plugin's functions" (2026-11-08 19:16). The checks that drive
the removed canvas API (O-2) are retired by name with the PRD's superseded
rows, never left failing.

"Live" means one thing here: each proof is a check in the MCP harness
(`checks/live.mjs`, run through `confirm`), driven in the running app,
reloading the plugin first, with its planted arm run the same way. Not a
script, and not an agent. The reader's words: "I still think you could work
more to integrate the MCPs with improved perception over the full space of
things we are tracking" (2026-09-21 01:05), and "from here on out, run
all harnesses yourself, never use agents, this is a rule. Always test with
the MCP-first" (2026-11-15 21:48). The check reads the editor's state as data
through the harness (nodes, ports, links, the note's text). "Screenshots
must be sparing ... capture the interface at the data structure level"
(2026-09-20 20:28). A screenshot is taken only when the question is what
a person sees. G-394's two defects that passed the DOM check were found
that way.

### 13l. Readings that are mine

None of these is a question: the record settles each, and they are written
here so a correction has somewhere to land.

- 182/183 + 187 = nodes that are their interfaces (§13c), by 182's own words
  and recency (124).
- The node-definition schema is one table (§13d'), from M.3 + ComfyUI +
  Langflow.
- litegraph's JSON is never authority (§13d), by NOTEBOOK §1's argument.
- The pinned MIT litegraph is the editor (§13j), by licence and language.
- The search node is the cockpit's `search` field resolved external
  (§13h), by 164's "one node" and the cockpit staying a slate (§13b).

### 13m. Terms -- one meaning each

Several words in the record carry two meanings. Each is pinned here, with
where it comes from. A term not listed is used in its plain sense.

| term | means | not to be confused with | source |
|---|---|---|---|
| **record** | one thing (note, cell, chunk, browser, tool, model, run): its text, its edges, its fold state, its current readout | a copy of it | 37, RESERVOIR §5 |
| **placement** | where a record is drawn: a field (folded or revealed), a panel or node on the plane, a node in 3D, a view of a live object | a second record | §12a, §13d |
| **field** | (the editor's grammar no longer, 194, head note) one line `name value` of a slate, with the lines indented under it (its sub-fields, as `search`'s in `ego.md`); the value may be a `{ref}` | a widget (below) | 62, UR E.4 |
| **slate** | a note whose tree is a Python module written in markdown (the cockpit is one) | a code cell | 62, 63' |
| **panel** | Obsidian's own markdown view, wherever markdown is shown (prose notes, slates, chat); 193: "regular obsidian panels exactly"; the custom syntax the app adds on top is withdrawn by 194 (head note) | a node body that is not markdown | 56, 133 c, 140, 193 |
| **cell** | one fenced code block of a note, or one top-level slate tree: the unit of dataflow, within its note (§13d) | a panel | 49, G-380 |
| **call cell** | a cell that binds one call of a callable or a class; the editor's typed node | any cell | §13d |
| **node (2D)** | a cell drawn in the editor: its body the cell's interface, its ports its inputs and outputs; folded to its title it is the fold parameter of 110. Also a slate FIELD resolved external (§12a), drawn as its own node while it is (the search node, §13h) | the retired abstract circle (182, 183) | §13c |
| **node (3D)** | a record placed in the world or the ego's UMAP: a glowing orb, billboarding its record when hovered | the 2D node | 183, 12f |
| **port / widget / socket** | a node's input or output; a WIDGET when its value is a literal edited in place, a SOCKET when it is linked by a name | the comm protocol's "widget" (a live object) | §13d' |
| **live object** | a Python object with typed, observed state synced to its views over the kernel's comm channel (a Jupyter widget, front end per AFM) | a widget port | §13b, §13e |
| **view** | one drawing of a live object's model; many views share one model | a placement of a markdown record | §13e |
| **interface** | 193 (d): ONE interface that generalizes every canvas type -- code (editor tools, a terminal), web chunks (components acting on the live browser), the rest. A query makes two embeddings; 193 names one, natural language over the interface types, and the other (over content) is my reading | a tool surface; a UI widget | 193 |
| **canvas** | the interactive surface of an artifact (182's "interface canvases"). The EGO canvas is the cockpit's record ordering the ego's components (§12c) | a separate canvas note (retired, §12g) | 182, 183, §12c |
| **canvas / graph** (195 d; my reading, to be corrected) | WHERE: a canvas is ONE record drawn whole -- its text, its controls, its string form -- and ends at that record's edge. A graph begins at the first link between two records: a compiled def/use, a call of a tool, a search's link to a result chunk (computed per search, never stored, 164; its spelling as a `{ref}` goes with the slate syntax under 194). No graph lies inside one canvas. WHY: a canvas is what the reader acts on in place (the REPL is a browser); a graph is what moves between records (dataflow, retrieval, an agent's calls). WHEN: a canvas becomes graph when it is unnested into its records (a note into its cells, a page into its chunks, a tool into its calls); folding returns it to one canvas. A retrieval result therefore stays a node in its OWN canvas, outside the ego's (195 a) | a canvas drawn as a graph form (182 retired the flip) | 195, 182, 112 |
| **plane** | the 2D surface fixed to the camera, in the 3D view, where nodes and panels sit; the editor's pan and zoom | an Obsidian pane | 50, 159 |
| **ego / cockpit / craft** | the ego is the reader's tool space; the cockpit is its slate (`ego.md`); the craft WAS its 3D form (circles and dashed edges), retired from view (G-405) until G-400 draws the ego as world nodes on its own UMAP, flown first or third person | -- | 54, 67-69, 146, 158, 186 |
| **tool space (of the ego)** | the ego's set of tools and attached artifacts: browsers, retrieval, notebooks, chats, tagged chunks | a toolspace | 158 |
| **toolspace** | one group of the app's capabilities, one per README pane (3D graph, ego, browser cell, panels, notebook/slates, search) | the ego's tool space | 166, 167 b, G-376 |
| **governing class** | the ~25-line class of one THING whose public methods are its capabilities; an instance is a separate, linked record | a tool surface | 142, T-10, 89 |
| **tool surface** | one TOOLSPACE written as calls only, a comment per line: the calls on the governing classes and globals in that pane | a governing class | 166, 167 b, G-377 |
| **tool panel** | the canvas form of an APP tool: a tool surface or a governing class shown as a READ-ONLY code artifact, calls visible, bodies never | a regular code artifact (explorable, graph-editable) | 167 c, G-378, F.6 |
| **app tool** | a capability shipped with the app, shown as calls only, its dependencies never visible (§13n) | workspace code | 167 c, 189, G-378, G-382 |
| **workspace code** | code made in the project workspace, fully explorable, editable and unfoldable down to base modules (§13n) | an app tool | 167 c, 189, 112 |
| **hard link** | an edge that exists because code defines a name another cell reads, or a `{ref}` resolves (withdrawn with the slate syntax under 194, my reading; head note), or two records share one chunk object; drawn undirected | a **temporary link**: magnetism, placement order while nodes touch (142), never drawn or written; a plain or wiki link (never a hard link: 194, compiled from code cells, head note); a retrieval link `[query](results)`, or 193 (b)'s suggested `#` query | 136, 142, T-4, 193 |
| **readout** | a cell's stored output; on the perimeter, a terminal node's rendering placed in 3D | a view | RESERVOIR §4, §5 |

### 13n. Code tools on canvases -- app tools and workspace code (189)

189: "make sure that code tools on canvas interfaces are also clearly defined
and scoped for app-based tools without their dependencies visible, and the
code that is made in the project workspace itself". Two kinds, told apart by
WHERE the code lives and WHO owns it. Everything else follows from that:
what a canvas shows, how far it unfolds, what can be edited, how it is found.

| | **app tool** | **workspace code** |
|---|---|---|
| what it is | a capability that ships with the app: the kernel's boot objects (`search`, `Database`, `WebBrowser`, `Agent`, `Vault`, the editor calls), the app's governing classes (`domvec/governing/`), each toolspace's tool surface (§8) | code made IN the project workspace: a note's cells and slates, functions and classes a reader writes, code a chat or an agent writes (G-394, G-384), code brought in from a scanned page into a note (G-234) |
| owned by | the app | the reader (and the agents working for them) |
| address | `tool://kernel/<Name>`, `tool://pane/<pane>` (G-382) | `vault://<note>#cell <n>` (159) |
| on its canvas | its CALLS only: each method or call with parameters, types, defaults and return type, one comment per line, the docstring as prose. A skeleton like this, never more: `search(query: str, k: int = 8, where: Literal["web","ego"] = "web") -> Results  # ranked chunks` | everything: the source, its typed rows editable in place (G-378), and the code tools run / terminal / open / unnest (B11) |
| hidden | the bodies, its imports, the modules and routes it calls, the store behind it (167 c: "no way of exploring the underlying codebase"; F.6: `read_only`, `no_datablock`) | nothing of its own |
| how far it unfolds | its typed rows only. A row whose type is itself an app type unfolds to THAT type's rows, never to an implementation | down its dependencies (80, 112, G-328): another workspace note to its cells; an installed library to its definitions, read from the installed source, READ-ONLY; the base modules at the bottom. An app tool it calls stops the unfold at the app tool's rows |
| editable | never: "read-only" means its code cannot be opened or edited; its calls still act on the world (`go`, `pin`, `act`, `Vault.write`), each returning a value that names what changed (§8) | in place: values, types, renames written back losslessly (G-378); links drawn in the editor (§13f) |
| as a node (§13d) | two ways. Its tool panel placed on the plane is a node with sockets and no body code to open (§13d'). A reader's CALL of it is a call cell, workspace code and editable, whose ports are the tool's parameters; unfolding the callable shows the read-only listing | its cells are nodes with ports; its functions and classes are callables for further call cells |
| as a live object (§13h) | the base tools: the view and the traits are visible, the implementation is not | a reader's own live-object class: fully visible |
| found by | retrieval over `tool://` pages, placed in 3D (G-382, 170 a) | retrieval over vault pages; the reader's own artifacts live in the ego (77, RESERVOIR 10.6) |
| embedded as | like every code artifact (51): its comments and docstrings, which carry a calls-only listing's meaning; a vector from its rendered panel per G-382 (170 a) | its prose only: docstrings and comments, never the code (51, G-52) |
| from the 3D layout and the index | always present (not repository code) | present as vault pages |

Four boundaries make the scope exact:

1. **The app's own source never appears.** `code://repo` and `code://plugin`
   are out of the layout AND the index (167 a, G-375). An app tool is the
   app's surface, never its codebase.
2. **A dependency is visible exactly when it is not the app.** A workspace
   unfold goes through other notes and installed libraries to the base modules
   (112). It stops at an app tool's rows, and nothing in an app tool unfolds.
   An import of the app's own package from a workspace cell counts as the
   app: it shows the imported names' rows, as an app tool, never their source.
   The kernel has that package on its path (T-14, 148), so this case is real.
3. **Tools made on the fly are workspace code** (187: "custom made code tools
   on the fly with the same editor interface"). A function written in a cell
   is a node and an agent's tool the moment its cell runs (§13d'), and it
   stays fully explorable. Nothing written in the workspace is promoted into
   an app tool.
4. **Names.** A workspace cell may reuse an app tool's name, and the cell's
   definition then wins for that kernel's life (THROUGH_STACK_SYNTHESIS 1g,
   tested). 181 asked and got "[No preference]", so it stays as found, my
   choice (F-84). So the canvas says which kind a name resolves to. Nodes
   keep one shape (B13); a tool panel, and an app callable wherever its rows
   are shown, carries mortegon's read-only mark instead (F.6's lock), the
   one difference. A
   workspace definition that shadows an app name carries the name of the app
   tool it hides.

**An installed library, unfolded (193 e).** Boundary 2 reads its definitions
READ-ONLY and says nothing of the index. 193 (e): "general pypi packages
could be recursively chunked, vectorized, and tooled as interfaces if we
assume the unnesting on dependencies action is taken on the code canvas
interface", by "a similar web stream dynamic". 166 has only browser-scanned
code projected in 3D. 193 is the later word, but it says "could", so what
an unnest indexes is O-11.

Sources (read 2026-11-22):
[anywidget AFM](https://anywidget.dev/en/afm/),
[anywidget, Getting started](https://anywidget.dev/en/getting-started/),
[ipywidgets message spec](https://github.com/jupyter-widgets/ipywidgets/blob/689bc46a14e81c83c97ff8534b4eda6dfa46f574/packages/schema/messages.md),
[marimo anywidget](https://docs.marimo.io/api/inputs/anywidget/),
[marimo on anywidget](https://marimo.io/blog/anywidget),
[marimo interactivity](https://docs.marimo.io/guides/interactivity/),
[marimo chat](https://docs.marimo.io/api/inputs/chat/),
[ComfyUI custom node properties](https://docs.comfy.org/custom-nodes/backend/server_overview),
[ComfyUI walkthrough](https://docs.comfy.org/custom-nodes/walkthrough),
[ComfyUI V3 schema](https://docs.comfy.org/custom-nodes/v3_migration),
[ComfyUI node definition JSON](https://docs.comfy.org/specs/nodedef_json_1_0),
[ComfyUI object_info](https://docs.comfy.org/api-reference/cloud/node/get-all-node-information.md),
[ComfyUI JS objects](https://docs.comfy.org/essentials/javascript_objects_and_hijacking),
[Langflow custom components](https://docs.langflow.org/components-custom-components),
[Langflow licence](https://github.com/langflow-ai/langflow/blob/main/LICENSE),
[Comfy litegraph configuration](https://github.com/comfy-org/litegraph.js/blob/master/_autodocs/configuration.md) (through Context7),
[Comfy litegraph LGraphNode](https://github.com/comfy-org/litegraph.js/blob/master/_autodocs/api-reference/LGraphNode.md) (through Context7),
[@comfyorg/litegraph README](https://cdn.jsdelivr.net/npm/@comfyorg/litegraph@0.17.2/README.md),
[litegraph.js](https://github.com/jagenjo/litegraph.js),
[litegraph.js on jsDelivr](https://www.jsdelivr.com/package/npm/litegraph.js),
[ComfyUI_frontend](https://raw.githubusercontent.com/Comfy-Org/ComfyUI_frontend/main/README.md),
[ComfyUI_frontend on ecosyste.ms](https://awesome.ecosyste.ms/projects/github.com%2FComfy-Org%2FComfyUI_frontend),
[smolagents](https://huggingface.co/docs/smolagents/v1.7.0/reference/agents),
[Ryven](https://github.com/leon-thomm/Ryven), [Elyra](https://pypi.org/project/elyra/),
[Hamilton](https://pypi.org/project/sf-hamilton/1.43.1/).

## 14. Cross-check ledger (2026-11-22, for the reader's goal: "keep cross-checking ... until ... no more mistakes, inconsistencies, or unclear terms")

The whole set, re-read at every pass. Scope: this spec, the sibling designs
(RESERVOIR, GRAPH_WORKBENCH, DESIGN_VISION, SEARCH_GRAPH, NOTEBOOK_PANEL,
THROUGH_STACK_SYNTHESIS, EGO_CANVAS, CALLABLE_INTERFACE's head), PLUGIN_GOAL
from 2026-10-29 to 195, mortegon UR §E, §F, §M-§T, the PRD rows they
cite, and every prompt the reader sent in this session's transcript
(2026-09-12 to 2026-11-23 UTC, 238 messages; from F-59). Kinds: **M** a mistake, **I** an inconsistency between documents or
with the app, **U** an unclear term or step.

| # | kind | where | finding | resolution |
|---|---|---|---|---|
| F-1 | I | spec §1 | the record table stopped at 166 | rows to 191 added; "record ends" updated |
| F-2 | U | spec §12-§13 | bare item numbers, while numbers restart per series and older series reuse most of 1-186 | citation rule at §13's head |
| F-3 | U | spec §13d | a node was "per cell, per live object and per function", while the dataflow is per cell | the node is the cell; a call cell is the typed node; definitions unfold as rows |
| F-4 | U | spec §13f | where a drawn link's code is written | into the READING cell: one argument, or one binding line |
| F-5 | I | spec §13e vs B6 | a live object's state is kernel state, but B6 puts outputs in the markdown | a text snapshot and the view's identity are the cell's output (reading) |
| F-6 | U | spec §13e | the sentence on marimo's wrapper | rewritten: the comm report counts as a fresh definition, closing the mutation gap |
| F-7 | M | spec §13g | "black slate for code (S.4)" had no source | node bodies are Obsidian's panels (56, 184); slates keep G-278's class |
| F-8 | U | spec §13g | how the editor's pan relates to the plane fixed to the camera | the editor's pan and zoom ARE the plane's; the 3D camera moves only the world |
| F-9 | M/I | spec §10c, GRAPH_WORKBENCH §4, PLUGIN_GOAL 165/179 | "every file on disk" omitted four GGUFs; the record calls them not downloaded, the disk has them | §10c corrected; the contradiction stated in both docs |
| F-10 | U | throughout | canvas, tool space vs toolspace, tool surface vs tool panel vs governing class, widget, node (2D/3D) | §13m, one meaning each |
| F-11 | I | PRD | G-281, G-323, G-396, G-397, G-398 read Confirm for forms 182-186 retired | marked Superseded, the old verdict kept |
| F-12 | I | PRD vs spec | §12h's G-401..G-407 and §13k's G-408..G-413 had no rows | rows added, statuses as built |
| F-13 | M | spec §13i | "G-401 built" -- written, uncommitted, not seen live | corrected (PRD Partly) |
| F-14 | I | RESERVOIR §3.3, §5a, §5b, §8, §9, §12.1 | the graph-form flip, the circles, minimize-to-circle, open questions all answered, the strict scale | head note naming each override |
| F-15 | I | DESIGN_VISION 1.4, T-12, 4c | the flip gesture (182), drift off (150), "open" rows since built | head note |
| F-16 | I | GRAPH_WORKBENCH §6 | "the 2D editor's host" still asked | answered by 50; head note |
| F-17 | I | NOTEBOOK_PANEL §1, §2, §4a, §7 | subprocess-first (49), the `+` buttons (133 d), terminals as cells (142), no interactive outputs (187) | head note |
| F-18 | U | SEARCH_GRAPH | what the one retrieval node is under 187 | a call cell in the editor; head note. Corrected by F-78: the cockpit's `search` field, resolved external |
| F-19 | I | UR S.4 vs 133 f | "no x, no minimizer" vs "minimize and exit" on panels | recency (124): 133 f; noted in RESERVOIR |
| F-20 | I | 186 vs 187 | "NO SPECIAL EFFECTS" vs a node editor's title bars and ports | 187 is later and scoped to code objects; prose stays fields; §13g allows one shape and nothing styled beyond theme colours |
| F-21 | M | first §13 | `@comfyorg/litegraph` named as a live MIT package | archived and merged into a GPL-3.0 repository; only a pinned pre-merge release (§13j) |
| F-22 | M | first §13 | the AFM contract as one hook | setup + draw, signals, the host, nine obligations (§13e) |
| F-23 | M | spec §12 intro | "§12f names what my slices got wrong" -- it is §12g | corrected |
| F-24 | U | spec §12b | "5160", "5364" were PLUGIN_GOAL line numbers among item numbers | cited as items 133, 140 |
| F-25 | M | spec §12b, RESERVOIR §3.3 | "UR §7.3.4" -- UR has no §7; the gesture table is DM §7.3.4 | corrected in both |
| F-26 | I | spec §12c | the cockpit's fields listed without `last` and `unfolded`, which `ego.md` holds | listed as the file holds them |
| F-27 | M | spec §12e | chat turns called "fields" | 182's answer: ONE note; turns, prose and code blocks are addressable chunks |
| F-28 | I | T-9 ruling vs G-301 and the governing browser class | the scope ladder has FOUR rungs in the ruling (chunk, group, page, browser) and THREE in the class (chunk, page, live) | open, O-4 |
| F-29 | U | spec B2 | "panel and graph forms commute" after 182 retired the graph form | B2 restated: code and graph editor commute |
| F-30 | M | spec §13c | "a prose note ... with ports for the names it defines" -- prose defines no names | slates have ports; plain prose has none |
| F-31 | M | spec §13d trie paragraph | "a widget value is a trait" -- a port widget is a literal argument; a trait is a live object's state | both stated separately |
| F-32 | M | spec §13d' | "a method's output called when the link is written" | it runs when the reading cell runs |
| F-33 | U | spec §13e | "(item 4)" read under the citation rule as PLUGIN_GOAL 4 | "the fourth obligation above" |
| F-34 | M | spec §13f | ComfyUI's change test equated with our source hash | stated as theirs (inputs/widgets) vs ours (source hash or upstream re-run) |
| F-35 | U | spec §13g, B14 | the halo click (T-8), containment (111), magnetism (134 c), Ctrl resize (133 h) were unmapped onto the editor | four rows added; B14 restated |
| F-36 | U | spec §13i | how 12c's "reveal inline" and "nodes on the plane" coexist | prose components reveal; code objects are nodes |
| F-37 | U | spec §13, item 189 | "code tools on canvas interfaces" were not scoped into app tools (dependencies hidden) and workspace code (explorable) | §13n; B21; two terms |
| F-38 | I | spec §2, §7, §9a, §10d, §11c | questions shown open that 167, 169 and 187 answered; §11c's slate parity | each marked answered in place |
| F-39 | I | spec §13n vs B13 | "never look the same" against "one uniform display" | one shape; the read-only mark (F.6) the only difference |
| F-40 | U | spec §13n | "read-only" app tools whose calls change the world | read-only is about the CODE; calls act and name what changed |
| F-41 | I | PLUGIN_GOAL vs spec §9, §11, §13 | eleven of the reader's messages were acted on, two of them quoted in the spec, but never transcribed (against 101) | backfilled verbatim as item 190, dated |
| F-42 | I | PRD G-280, G-296, G-383 | Confirm rows still naming the circle collapse and the graph form | a dated scope note on each; the standing parts kept |
| F-43 | U | spec §12e vs §13m | "the §8 surfaces are the rest" made tool surfaces governing classes | §12e restated: a different grain, per toolspace |
| F-44 | U | spec §13n | a workspace cell importing the app's own package would expose app source through the unfold | boundary 2: such an import shows rows only, as an app tool |
| F-45 | I | RESERVOIR §12.4, GRAPH_WORKBENCH §3 | `code://repo` boxes in the unnest, and a code KG over the repository's CPG, after 167 Q1 / G-375 removed the repository from the index | head notes: both now apply to web code and workspace code; the app's own modules are app tools |
| F-46 | M | spec §13j | pre-merge `@comfyorg/litegraph` releases called "confirmed MIT"; only listings were seen | "listed as MIT"; the licence is read in the release itself (O-1) |
| F-47 | U | spec §13g | the DOM-widget overlay stated as ComfyUI's current behaviour | sourced to its legacy script, as read; only the pattern is used |
| F-48 | U | spec §13h vs 182 | the pulled-out piece of a chat turn under the editor | its own node, linked back to its source address |
| F-49 | U | spec §13b vs 187 | 187's "similar to how we tried with our ego card" was unread | the cockpit's two-way binding (G-280) as the precedent; the cockpit stays a slate |
| F-50 | U | spec §13g vs 159 | the 2D gesture help after the gestures change | the help lists §13g's mapping |
| F-51 | U | spec §13 | §13n stood before §13m | moved after the terms |
| F-52 | I | spec §14 | the ledger's scope and F-1 still said 187 | 191 |
| F-53 | U | spec §13m | "tool panel" and "app tool" overlapped without a stated relation | a tool panel is the canvas form of an app tool |
| F-54 | I | spec §13n vs 51 | an app tool "embedded as its rendered listing" against "every code artifact embeds its PROSE only" | stated under 51, with G-382's rendered-panel vector (170 a, the later ruling) |
| F-55 | M | spec §13d | "Nothing in the editor holds state the trie does not" -- node positions are editor state, and magnetism's order depends on them | placement (position, size, fold) is the editor's only state, keyed by address; edges, ports and values never |
| F-56 | M | spec §13g | the zoom-threshold reading had landed inside the gesture-help paragraph | moved back under "DOM in a node" |
| F-57 | U | spec §13g vs T-8, M.6 | T-8's double-click (open/close) and the title right-click (fold) on one node | the same fold, two ways |
| F-58 | U | spec §13h vs §13n | the base tools' kind | app tools |
| F-59 | I | PLUGIN_GOAL vs the session transcript | 84 of the reader's 238 prompts in this session were in no record and one only in part, against 101 | recorded verbatim, by UTC time: PLUGIN_GOAL "Recovered verbatim (2026-11-22 inventory)" |
| F-60 | U | spec §13g vs 141 and 2026-11-08 17:43, 18:33 | magnetism "snapping added" said nothing of WHEN things move; the record rules one bounded settle, and the reader reported lag and jostling from continuous motion | "Nothing on the plane moves by itself": drag, one settle on release, redraw on change only, drift turns the camera only |
| F-61 | U | spec §13g vs 2026-09-24 05:04 | the gesture help "expands into a full panel" without saying when it folds; a readout left open over the view was a reported defect | a panel only while hovered |
| F-62 | I | spec §13h vs G-385, G-394, 2026-11-22 01:19 | `Chat`'s tokens over the comm stated as if no stream existed; one is seen live, wired into the chat panel, with a measured bar | the comm is a second hop of that stream; G-385-load's bar holds at the view; G-412's proof carries it |
| F-63 | U | spec §13k vs 2026-09-21 01:05, 2026-11-15 21:48, CLAUDE.md | "a live check" did not say through what | MCP harness checks (`checks/live.mjs` via `confirm`), plugin reloaded first, planted arm alike; never a script or an agent |
| F-64 | U | 150's reading vs 2026-11-08 17:43 | 150 is read as drift wanted ON (overriding T-12); the recovered 17:43 asked continuous motion off "for now" and "back on for after decisions" | no conflict: the off was temporary by the reader's own words, which supports the reading. The 2D plane is unaffected either way (F-60) |
| F-65 | M | spec §13e | "`/chat_stream` is the only push channel today, so the long poll is the same pattern": `/chat_stream` is a held-open response flushed per token, not a long poll | the two told apart, and why the comm log long-polls |
| F-66 | U | B14 vs §13g | "right-click on the base" (B14) and "on the title" (§13g) for one gesture | B14 names it the title, mortegon's "base node" (RESERVOIR §10.2) |
| F-67 | U | spec §13f | "(B's)" read as a B-commitment of §13a | "node B's below" |
| F-68 | U | spec §13d, §13f vs `kernel.py`, `dataflow.py`, `planepanels.ts` | def/use links and their write-back were stated without the note boundary: kernels and dataflow are per note, and the plane makes each new panel its own note | the boundary stated; across notes a drawn link is a fence-line `{ref}` (G-279); a value between notes is open, O-5 Refined by F-74 and F-81 |
| F-69 | U | spec §13k vs 2026-09-20 20:28 | how a live check reads the editor | as data through the harness; a screenshot only when what a person sees is the question |
| F-70 | I | spec §13d vs the binding goal (O(delta), phases timed; CLAUDE.md goal, constraints 4, 5b, 5c) | "rebuilt from the note" with no cost; `dataflow.graph` re-parses every cell per call | re-parse cells whose `exact_hash` changed, re-join their names, a slate tree's neighbourhood invalidation stated; the rebuild a timed phase; G-411's proof carries it |
| F-71 | M | spec §12a | "`![[...]]` / `[[...]]` encoding, 12f" -- that table is §12g | corrected |
| F-72 | I | spec §12e vs §13n | the `{code://...}` unfold "down to the compiled base" without the app-tool stop | stated: workspace code and libraries unfold; an app tool stops at its rows |
| F-73 | I | spec B3, §12d, §13d, §13g, §13m vs 142 | the spec said magnetism is "never a link"; the reader's own word (142) is "a temporary link for compilation serialization" | the reader's term kept: a TEMPORARY link, never a hard link, never drawn or written |
| F-74 | I | spec §12d, §13d, O-5 vs DESIGN_VISION T-4, T-6, T-11 | T-11's second half (a terminal's or kernel's output is an input to the next cell in magnetism's order) was missing, and O-5 said the `{ref}` was the only path across notes | §12d carries T-11 (built only for a chat's context); §13d and O-5 name both paths, a record and a readout; O-5 narrowed to a LIVE value |
| F-75 | U | spec §13g vs DESIGN_VISION 1.2 | the drift "rotates both cartesian and color coordinates"; whether colours cycle on the plane was unsaid | camera and 3D colours only; the plane keeps the theme's colours |
| F-76 | U | SEARCH_GRAPH 164 vs spec §13d | 164's result outputs "as hard links" against nodes that are cells, while results are chunks | a `{ref}` link per result, record-level (12d), drawn when placed, recomputed per search; stated in §13h and SEARCH's head |
| F-77 | I | SEARCH_GRAPH §6 | three questions shown open; 164 answered two and made the third moot | marked in SEARCH's head note |
| F-78 | M | F-18's resolution, SEARCH_GRAPH head | the search node called "a call cell"; in `ego.md` it is the `search` subtree of the cockpit slate, and the cockpit stays a slate (§13b) | a slate field resolved external as its own node (§12a, G-403), call-cell-shaped; §13h and SEARCH's head corrected |
| F-79 | I | spec §13d, §13m vs §12a, §13h | "the grain of a node is the CELL", while a slate field resolved external (the search node) is drawn as its own node | both kinds named: a cell, or a field resolved external, a placement of its cell's row |
| F-80 | I | NOTEBOOK §5 vs 2026-09-20 20:28, §13k | "never a screenshot" against "screenshots must be sparing", and against G-394's defects found only by a screenshot | head note: data first, a screenshot for what a person sees |
| F-81 | M | spec §13d (written in F-68) | "the record has one link" across notes, then "two paths" in the same paragraph; and a cross-note link wrote `{A}`, which binds note A whole, not the cell drawn from | one HARD link and one temporary link named; the link writes `{A#cell n}`, the outline's cell address; resolving it on a fence line is O-6 |
| F-82 | I | spec §13h vs §13d, 182, G-394 | `Chat` "holds `messages` as a trait" beside the chat note's turns: two authorities for one conversation | the note's turns are the record; the trait mirrors them and each turn is written back |
| F-83 | U | spec §13i, PRD G-402, G-403 vs §13b, §13h | the two rows were scoped to "prose", while §13b keeps prose notes and the cockpit slate apart, and the search node rests on G-403 for a slate field | scoped to markdown records: prose notes and slates (B10); B10 and the term "panel" say "markdown" for the same reason |
| F-84 | I | THROUGH_STACK_SYNTHESIS 1g, §4 vs PLUGIN_GOAL 181 | shadowed core names "held for the reader" with options listed, after 181 asked and was answered "[No preference]" | marked: left as found, my choice, reversible; §13n boundary 4 shows the resolution |
| F-85 | I | GRAPH_WORKBENCH §6 vs DESIGN_VISION T-15, T-16 | two of §6's three questions shown open, ruled by T-15 and T-16 and built (G-388, G-389) | head note: §6 answered in full |
| F-86 | M | spec O-5, NOTEBOOK head; DESIGN_VISION T-14 and 4c vs 148 | O-5 cited T-14 as "one environment per workspace"; the reader answered T-14 in 148: "No, share one", one interpreter for every workspace. DESIGN_VISION still shows T-14's ruling and "needs you" | O-5 cites 148; DESIGN_VISION's head note gains it; O-5's point stands (an interpreter is not a namespace) |
| F-87 | I | DESIGN_VISION §5 vs 148 | D-B, D-C, D-D and D-E shown open, answered in 148; D-G built as T-1 | head note |
| F-88 | U | spec §13h vs 182's second answer | `Chat` as one live object said nothing of 182's "One component, three hosts", each supplying its own context | one view in three hosts; the context an input from the host, never chat state; two hosts still separate (G-394) |
| F-89 | U | spec §13f vs §13d | §13f's write-back read as covering every drawn link; it holds within one note | pointer to the cross-note form |
| F-90 | M | spec §9a vs F-38 | F-38 claimed §9a marked answered; it still ended "This is the reader's call" | marked: answered by 167 Q4, Q5 (the dialect kept; `dataflow.py`) |
| F-91 | I | spec §1-§4, §8 | the date-citation rule stated for the whole spec while §12-§14 cite bare numbers; models "declined" without the files on disk; NOTEBOOK's §8 "open"; SEARCH as "the tool panel's graph form"; §4's tool panel as a kernel-run cell before 167 c; §8 "nothing decided" and "every new one" after G-377 built all | each restated in place |
| F-92 | I | spec O-5, §13d vs §9a, §10a | O-5 omitted the spec's own reading of 166 e, a note called as a module (free names in, definitions out), which would carry values across notes | named in §13d and as one of O-5's three options |
| F-93 | I | spec §10a vs §10d, 187, 167 | §10a's table still said smolagents "not installed", the plane's editor "open", and marimo's analysis "open" | installed; answered by 187 (§13j); answered by 167 (§9a) |
| F-94 | I | spec §11b, §11d vs 182, 187 | the corrected reading still had a gesture flipping panel and graph FORMS, and §11d said the five editor calls were "added as `new`" while §8 counts them as existing | §11b noted as superseded in part (the commute is code <-> graph editor); §11d says all five exist (booted by `kernel_objects.py`) |
| F-95 | M | spec §14a vs §13k | §14a's row for 2026-11-08 19:16 cited a rule in §13k ("every slice keeps the plugin's checks green") that §13k did not state | stated in §13k, with O-2's retired checks; also the 2026-09-23 22:56 row credited the browser's hover highlight to F-70, corrected |
| F-96 | U | spec §13m vs F-79, `ego.md` | "field" defined as one line, while the search field holds sub-fields | a field includes the lines indented under it |
| F-97 | U | spec §13n | an app tool "as a node" had "the read-only listing" as the node's body, blurring the reader's call cell (editable) with the tool it calls | the call cell is workspace code; the tool's listing is what its callable unfolds to; boundary 4 places the read-only mark there and cites 181's answer (F-84) |
| F-98 | I | spec §13n (F-97's wording) vs §13d' | F-97 made the call cell an app tool's only node; §13d' also draws the tool class itself as a node with sockets | both named: the tool panel as a node, and the reader's call cell |
| F-99 | I | RESERVOIR §1, §3.3, §4, §6, §6b, §8, §8b, §10.1, §10.2, §11.2, §11.4, §12.8 | read line by line: graph form, circles, the old cockpit fields, `Agent` as a download, the browser cockpit slate, three rungs, `+` buttons and soft links, libcst asked, the telescope -- all overridden later and not in its head note | head note extended, each named with what overrides it |
| F-100 | I | app vs T-4, §12d, §13f: `editorcalls.ts` `link`, `planepanels.ts` `linkedTo`, `magnetized`, the wire drop; RESERVOIR §12.3; spec §11d | wiki links stand in for hard links: `link()` writes one, containment and chat context read them, while the plane draws only `{ref}`s (G-404) | O-7; §11d's comment and §13g's containment row say so |
| F-101 | I | GRAPH_WORKBENCH §2, §4, §5 | read line by line: a 2026-10-18 "now" column, DeepSeek-Coder as a chat role, llama-cpp-python "needs installing", downloads "under way", through-stack agents still designed -- each overridden later | head note extended |
| F-102 | I | NOTEBOOK §4a vs §3, §6 step 4 | §4a named the output's class `output`; §3 allows existing categories only, and the build wrote `text.output`; step 4 credited §3 with naming it | §4a says `text.output`; step 4 credits §4a |
| F-103 | U | NOTEBOOK §6 step 2, step 5, §8 q2 | a dangling "§4b"; two `[[]]` spellings of the retrieval gesture that R-7 counted as fixed; `"x = 1\nprint(x)"` printed with raw line breaks, splitting the sentence | step 4 named; `[query]()`; the escapes restored |
| F-104 | I | app: `shell.py` `interpreters()`, `tests/test_obsidian_shell.py`; NOTEBOOK §6 step 6 | `GET /interpreters` marked every Jupyter kernelspec `runnable: false` "because P-N1 is Partial", while P-N1 is Confirm and the pool drives `python3` over the Jupyter protocol; a test held the stale claim | runnable is `python3` exactly when the pool would start it; the test has a planted arm (forced subprocess kernel: nothing runnable); NOTEBOOK head note |
| F-105 | I | spec §1, §14 scope vs PLUGIN_GOAL 192 | the record table and the ledger's scope stopped at 191 | 192 added; record ends 2026-11-24 |
| F-106 | I | app (G-414 `hover3d`) vs §12f | §12f: "a hovered node billboards its record revealed to its level: higher rank, more of the tree"; G-414 previews chunk nodes and does nothing over a page or path node | O-8 |
| F-107 | M | PRD G-414 | status "Open" for a row built and passed by its live check with a planted arm; that state is `Confirm` | Confirm |
| F-108 | U | spec O-5 | three ways a live value could cross, then "Either ... or" offering two of them again | the repeated sentence removed |
| F-109 | I | spec O-3 vs the app | O-3 said G-401, G-404, G-405 were not seen live; the 2026-11-24 rebuild deployed them. G-405's craft gate measured live (192: the dotted lines gone); a `domvec/ego canvas.md` card shows on the plane, the note §12c ("one ego") and §12g retire | O-3 restated (its first wording blamed G-401: F-112) |
| F-110 | I | PRD G-401, G-404, G-405 vs O-3 (F-109) | the rows still said "not seen live" after the rebuild deployed them | each row says deployed, and what was measured |
| F-111 | U | PLUGIN_GOAL 192 "Read as" (a) | "the hover's own path, as a browser hover does": a browser hover flies the camera (G-215), the 3D hover (G-414) does not | the billboard path named (`hoverPanel`), the flight excluded, the reason marked as my reading |
| F-112 | M | spec O-3, F-109, PRD G-401 (my wording) | the plane's `domvec/ego canvas.md` card was attributed to G-401; `egocanvas.ts` reads that note once as a seed (`OLD_CANVAS_PATH`) and opens only the cockpit (`openCanvas`). The card is a panel left open on the plane from the G-396 era | O-3 and G-401 say so |
| F-113 | M | NOTEBOOK head note (my pass-19 wording) | "the chat panel and the retrieval bar carry" the hovering SLM bar, citing 133 d: the record never names the bar's fate, and 133 d's retrieval bar is over typed nodes | marked as my reading; the parts named (the chat panel, 84's naked search field) |
| F-114 | U | spec F-109, O-3; PRD G-405 (my wording) | "seen" used for a harness measurement, where this project keeps "seen" for the reader or a `confirm.mjs` check (`CLAUDE.md`, the `Confirm` state) | "measured live", and who has not seen it |
| F-115 | I | app: G-401 vs its PRD row and §12h | §12h says the separate canvas note is "removed" and the row "read once and retired"; `sync` does trash it, but runs only from `openCanvas`, which only live checks call -- the note is still in the vault and on the plane. F-112's wording also left the trash step out | O-3 and G-401 say so; an entry point is owed (O-3) |
| F-116 | I | spec §14a (2026-11-08 17:41 row) vs O-3 | "the one decision for the reader is O-5" while O-3 records a second question asked of the reader | the design decision told apart from the layout question |
| F-117 | I | spec §12c, §12h G-401 vs PRD G-401 and `planepanels.ts` `canvas.members` | the slate's fields are seeded from "the tool space (158)" in the spec, from "the craft membership" in the row and the code; the two sets differ (browsers, chats, tagged chunks), and the craft is retired | O-10 |
| F-118 | I | spec §12b-§12c, §13d'-§13g, O-1, O-6, O-10; PRD G-401, G-409, G-411 vs 193 | the spec builds its own renderer: chip fields, a vendored node editor, ports and widgets. 193 asks for plain Obsidian notes and code blocks, the purple nodes removed | suspended at the spec's head, pending the reader's answer on links; nothing deleted until then |
| F-119 | I | spec §13e | cited "NOTEBOOK §4b", the section F-103 found does not exist | NOTEBOOK §6 steps 4-5 |
| F-120 | U | spec §13e | `JupyterKernel.run`; the class is `_JupyterKernel` (`kernel.py`) | named as in the code |
| F-121 | I | spec head note (F-118) vs §13h | the suspension named §12b-§12c and §13d'-§13g, not §13h's search node, a slate field resolved external and drawn as a node | named |
| F-122 | I | spec §13n boundary 2 vs 193 (e), 166 | an unfolded installed library is read-only and unindexed in §13n; 193 (e) says it "could" be chunked, vectorized and tooled by the web's stream; 166 projects only browser-scanned code | stated under §13n; O-11 |
| F-123 | U | spec §13m vs 193 (d) | "interface", 193's one generalizing term, had no entry | a row |
| F-124 | I | spec §13m vs 193 (a), G-405, §12f | "panel" was Obsidian's view "extended"; the craft "is" the ego's 3D form while retired | panel cites 193; the craft WAS, until G-400 |
| F-125 | U | spec §13m hard link vs 193 (b) | the retrieval link named only `[query](results)` | the `#` suggestion named; wiki links point to the open question |
| F-126 | I | spec §13j, §13k vs the 193 head note | the build order and the packages still put G-409 and G-411 and litegraph on the path, and G-410 "a node body once G-411 lands" | each names its suspension; G-410 in a plain panel, as my reading |
| F-127 | M | spec §13m `interface` (my pass-27 row) | the second of 193's two query embeddings stated as "over content"; 193 names only the one over interface types | the second marked as my reading |
| F-128 | I | PRD vs 193 | 193 was transcribed and read, never decomposed into rows | G-415 (a, c), G-416 (b, d); (e) is O-11, (f) a download |
| F-129 | I | spec head note, §13j, §13k (F-118, F-126) vs 194 | the node editor was suspended with the markdown syntax; 194 moves compilation into code cells and keeps the graphical code interfaces and the package research | the syntax withdrawn (my reading, to be confirmed); the node editor over code cells stands |
| F-130 | I | PRD G-38 vs its live check (O-9) | Confirm while its check failed: the planted banner was added only on hover 2 and never measured when hover 2 found no new chunk | the plant moved to the first landed hover; passes both arms (`402c5a2`); O-9 closed |
| F-131 | I | spec §13m (panel, field, hard link) vs 194 | the glossary still called the links question open and the panel's additions suspended | each cites 194's withdrawal |
| F-132 | I | spec §5, §11b, §11c vs 194 and the head note | the slate dialect (T.5's in-text editor syntax, N.10's `{ref}`, G-379's compile) was not named among what 194 withdraws, though §11b calls it "mortegon's panel syntax carried over" | named in the head note's withdrawn list; mortegon's words yield to 194, the later word |
| F-133 | U | spec head note (194's withdrawn list) | the withdrawal named the slate dialect and the ego slate's component fields, but not the cockpit, a slate whose fields drive search (G-372) and the view | named as part of the reader's confirmation |
| F-134 | I | RESERVOIR (76 slate/`{ref}` passages), GRAPH_WORKBENCH, DESIGN_VISION, SEARCH_GRAPH, NOTEBOOK head notes vs 193-194 | no sibling's head note named 193 or 194, though each builds on the slate syntax they withdraw | a pointer in each head note; THROUGH_STACK and CALLABLE_INTERFACE use none of it; EGO_CANVAS is already superseded |
| F-135 | I | PRD head vs 193-194 | the PRD's head did not name the slate-syntax withdrawal its G-372, G-379, G-401, G-403 rows sit under | a paragraph pointing to the spec head note |
| F-136 | U | PRD status vocabulary vs its rows and `CLAUDE.md` | four states defined (`Done`, `Partial`, `Open`, `Defect`); the rows use `Confirm`, `Partly` (32) beside `Partial` (19), `Superseded`, `Standing` | all defined; `Partial` as the older spelling |
| F-137 | I | PRD head | "128 numbered requirements"; `design_state` counts 579 rows | both counts, dated |
| F-138 | U | spec §13m vs 195 (d) | "canvas" and "node" were defined, but not where a graph begins and a canvas ends; 195 asks where, why and when | a `canvas / graph` row, marked as my reading |
| F-139 | M | spec §13m `canvas / graph` (my F-138 row) | named "a result's `{ref}`" as a link kind, the syntax 194 withdraws in the same document's head note | the link named by what it is (a search's link to a result, computed per search); the `{ref}` spelling tied to 194 |
| F-140 | I | spec §13m `hard link` vs the head note (194) | a resolved `{ref}` still listed as a hard link's source | marked withdrawn with the slate syntax |

**Passes that found nothing new** (2026-11-24; pass 34 then found F-132 in §5 and §11): pass 32 re-read pass 31's edits and every "suspend" left in the docs (only ledger history). Pass 33 read `egocanvas.ts` and `canvasparse.ts` whole against §12c: its disagreements are already F-115 (the migration runs only from `openCanvas`) and O-10 (the comment says tool space, `canvas.members` reads the craft). Field order is join order, appended, which is compile order (142). What remains waits on the reader: 194's reading, O-5, O-11, the covering cards.

**Still open** -- O-1 to O-4, O-6 to O-8 and O-10 are work the design names (O-6 and O-10 withdrawn with the slate syntax if the reader confirms 194's reading; O-9 closed); O-5 and O-11 are questions for the reader:

- O-1. The pinned litegraph release's own licence file must be read before
  it is vendored (§13j); only third-party listings say MIT.
- O-2. `checks/live.mjs` still drives G-396..G-398 through the removed canvas
  API, and G-399 part 4 expects a card-on-card link that G-404 now refuses.
  The app and its checks disagree until those checks follow the PRD's
  superseded rows.
- O-3. G-401, G-404 and G-405 are written, not committed, and deployed
  by the 2026-11-24 rebuild (F-109). G-405 is measured working through the
  harness, not yet seen by the reader (F-114).
  G-401's `sync` reads the old `domvec/ego canvas.md` once, as a seed, then
  moves it to the vault's trash, and draws no card for it (F-112). Nothing in
  the app calls `openCanvas`, the one caller of `sync`; only live checks do
  (F-115). So the migration has not run, and the note is still open on the
  plane as a panel from the G-396 era, the note §12c's "one ego" retires.
  G-401 needs an entry point the reader reaches (the cockpit's opening, or
  plugin load). With the clipboard card
  it covers the 3D view's chunk nodes, so hover and click reach none of them
  there. Closing it is the reader's layout, asked 2026-11-24.
- O-4. The scope ladder: T-9 rules chunk -> group -> page -> browser
  (from 137.4, "chunk groups"); the governing browser class and
  G-301 step chunk -> page -> live. The ruling is the later word: the class
  gains a `group` rung.
- O-5. **Closed 2026-11-27 (`201 d`, `G-451` Confirm).** The reader ruled:
  *"variables in one notebook could be referenced directly in others without
  special links or anything. Then, we truly take the computation graph approach
  to code chunk sequencing in a standard program compilation where variables
  that depend on variables from other notebooks are computed before their own."*
  Built in `domvec/dataflow.py` (`workspace_graph`, `compile_plan`),
  `domvec/obsidian/sidecar.py` (`_post_kernel` `pickle`/`base64` live value
  export/import across per-note kernels), and `obsidian-plugin/src/dataflowrun.ts`
  (`upstreamFor`, cross-note `after`), with `.is-var-dep` edges drawn on the 2D
  plane and in `Craft`. (Was: **For the reader.** A LIVE value passed between nodes of two
  different notes. Today each note has its own kernel. Across notes the
  record gives a fence-line `{ref}` (a record, G-279, T-4, T-6) and
  magnetism's order (a readout, T-11), never an object living in another
  kernel (§13d). Three ways a live value could cross: the plane's nodes share
  one kernel; a note is called as a module, its definitions returned
  (§9a, §10a, my reading of 166 e); or cross-note links stay at records
  and readouts. The answer also decides which note
  a node placed from the retrieval bar is written into. The record does not
  say. 148 answered T-14 with "No, share one" (one interpreter for every
  workspace, nothing downloaded), which is the Python environment and its
  packages, not one kernel or one namespace. Per-note state is NOTEBOOK §4's design ("a note is the unit a
  reader thinks in"), mine and written before the plane held nodes, not a
  ruling.
- O-6. A fence-line `{ref}` naming a cell (`{Note#cell n}`, the outline's
  grammar) is not resolved: `refs.resolve` matches note and page titles,
  then falls back to retrieval. A drawn cross-note link (§13d) needs it.
- O-7. Wiki links still stand in for hard links in the app, against T-4
  and §12d. The editor call `link(a, b)` (`editorcalls.ts`) and the retired
  graph form's wire drop append a markdown wiki link. Containment
  (`linkedTo`, G-327) and a chat's context (`magnetized`) read the metadata
  cache's resolved links. The plane draws only compiled `{ref}`s (G-404), so
  a `link()` call makes a link that is neither drawn nor compiled. Each
  must write or read compiled links: a fence-line `{ref}` or a def/use.
- O-8. A 3D hover previews a chunk node's billboard (G-414) and nothing
  over a page or path node; §12f wants every level billboarded, a higher
  rank revealing more of the tree (F-106).
- O-9. Closed 2026-11-24 (F-130): G-38's planted banner was added only on
  hover 2; it now lands on the first hover that registers, and both arms
  pass.
- O-10. What seeds the ego slate's fields. §12c and §12h say the tool
  space (158: the cockpit, browsers, the search, notebooks, chats, tagged
  chunks, the reader's notes). PRD G-401 and `planepanels.ts`'s
  `canvas.members` say the craft's membership: its `note` nodes, which
  G-291 makes of slates and of notes whose cell has run. Browsers, chats
  and tagged chunks are not among them, and the craft itself is retired
  (G-405 hides it; its nodes are still computed). G-401 should read the
  tool space's own records (F-117).
- O-11. **For the reader.** Does unnesting a code canvas's dependencies
  index the installed library it reaches: chunked, vectorized and given
  tool interfaces by the web's stream (193 e), so it is placed in 3D against
  166's "only browser-scanned code"? Or does it stay a read-only unfold
  (§13n boundary 2)? Its code models (193 f) wait on a download yes.

### 14a. The recovered prompts, one by one (F-59)

Each of the 85 prompts in PLUGIN_GOAL's 2026-11-22 inventory, read whole
against §12-§13, with what it bears on the editor. Quoted up to 70
characters; the full text is in the inventory. Counts: 10 bear on the editor (two of them only confirming what stands), 10 on how it is verified, 1 on the process of deciding, 64 on neither.

| UTC | prompt | bearing |
|---|---|---|
| 2026-09-12 22:14 | What project are we in? | none for 2D: operational (session, build, git, process) |
| 2026-09-12 22:15 | please switch to domvec, or whichever folder holds our running obsi... | none for 2D: operational (session, build, git, process) |
| 2026-09-12 22:16 | Are the PRD and goal docs you're referencing the verbatim requireme... | none for 2D: about the record or the process |
| 2026-09-12 22:22 | Now, please check on the running and open obsidian, connect the var... | none for 2D: operational (session, build, git, process) |
| 2026-09-12 22:59 | A switch to a kernel run and then a command terminal when switching... | editor: the kernel/terminal switch; stands as NOTEBOOK §4a and B11's run / terminal |
| 2026-09-12 23:22 | reload obsidian so it sees the notes | none for 2D: operational (session, build, git, process) |
| 2026-09-12 23:29 | wire the build to write straight into the vault plugin dir | none for 2D: operational (session, build, git, process) |
| 2026-09-12 23:32 | start on vault-note addressing into the trie | editor: stands -- a node is one `vault://<note>#cell n` address (§13d) |
| 2026-09-12 23:47 | commit it once the suite is green | none for 2D: operational (session, build, git, process) |
| 2026-09-12 23:48 | just kill it and run the targeted tests instead | none for 2D: operational (session, build, git, process) |
| 2026-09-12 23:59 | keep going with step 2 | none for 2D: operational (session, build, git, process) |
| 2026-09-13 00:07 | put the kernel in the sidecar | editor: stands -- the kernels, and so the comm bridge, live in the sidecar's kernel pool (§13e) |
| 2026-09-13 00:20 | keep going with step 4 | none for 2D: operational (session, build, git, process) |
| 2026-09-13 00:47 | Are you fully seeing the obsidian interface with mcp tools to the e... | verification: F-63 |
| 2026-09-13 00:55 | Are you able to interact at least with our existing panels? Perhaps... | verification: F-63 ("see and touch exactly what I can") |
| 2026-09-13 01:00 | Look around github until all perception gaps are filled, ideally wi... | verification: F-69 ("ideally without images") |
| 2026-09-13 03:31 | I hit my usage limit while you were working, but it has reset now.... | none for 2D: operational (session, build, git, process) |
| 2026-09-13 03:45 | Reopen everything. Assess your unknowns with self awareness of ever... | verification: F-63 |
| 2026-09-13 03:54 | keep going with step 6 | none for 2D: operational (session, build, git, process) |
| 2026-09-13 04:11 | keep going with step 7 | none for 2D: operational (session, build, git, process) |
| 2026-09-13 04:31 | fix D-8 first | none for 2D: operational (session, build, git, process) |
| 2026-09-13 15:03 | Let's continue on our new design. Please bring everything up again | none for 2D: operational (session, build, git, process) |
| 2026-09-13 15:16 | Let's continue building, making sure you're always interfacing with... | verification: F-63 |
| 2026-09-13 21:46 | Collapse capture and place into one round trip | none for 2D: operational (session, build, git, process) |
| 2026-09-13 23:38 | Let's continue | none for 2D: operational (session, build, git, process) |
| 2026-09-14 04:08 | What's next on the PRD? | none for 2D: operational (session, build, git, process) |
| 2026-09-14 04:31 | Both lease | none for 2D: operational (session, build, git, process) |
| 2026-09-19 22:50 | Where are the files for our set of design verbatim prompts located? | none for 2D: about the record or the process |
| 2026-09-19 22:51 | Where's our PRD? | none for 2D: about the record or the process |
| 2026-09-19 23:01 | write Addendum IV | none for 2D: about the record or the process |
| 2026-09-19 23:10 | Now re-derive the PRD rows against Addendum IV | none for 2D: about the record or the process |
| 2026-09-20 01:57 | I find that opening a few pages re-sets all the UMAP embeddings for... | none for 2D: 3D UMAP |
| 2026-09-20 19:59 | There are significant degradations in the quality of the features d... | verification: F-63, F-69 |
| 2026-09-20 20:28 | Again, I will repeat our main focus for you to consider the next st... | verification: F-69 |
| 2026-09-20 20:30 | Restarted our session. you should be able to see all the new tools.... | verification: F-63 |
| 2026-09-20 22:55 | The two layer UMAP and force directed unfold on the patricia trie h... | none for 2D: 3D layout |
| 2026-09-21 01:05 | I still think you could work more to integrate the MCPs with improv... | verification: F-63 |
| 2026-09-22 05:08 | Nodes in the 3D viewer are still way too clumped together. Remember... | none for 2D: 3D layout |
| 2026-09-22 05:24 | Fix the LinksTo query and the live capture, then verify | none for 2D: 3D |
| 2026-09-22 05:48 | Fix the _local_positions shell scaling | none for 2D: 3D |
| 2026-09-23 01:46 | I'm seeing nodes way too jumbled together and tries that aren't DAG... | none for 2D: 3D trie layout |
| 2026-09-23 22:41 | Are claude web fetches from the local network? | none for 2D: operational (session, build, git, process) |
| 2026-09-23 22:56 | fix the missing images on the fan-out nodes. you will have to bring... | editor in part: timing every phase (F-70); the hover highlight is the browser's, the rest the 3D pipeline |
| 2026-09-23 23:16 | go ahead with the pipeline trace and time profile | none for 2D: 3D pipeline |
| 2026-09-23 23:31 | yes, prove the placement hypothesis and fix it | none for 2D: 3D placement |
| 2026-09-24 00:19 | What are the next steps? Assess from the global perspective. | none for 2D: operational (session, build, git, process) |
| 2026-09-24 00:20 | How about the time-profiled pipeline and integrating all that with... | editor in part: the timed pipeline (F-70) |
| 2026-09-24 00:40 | The profile technically exists, but much more detached from the bro... | none for 2D: the 3D pipeline readout |
| 2026-09-24 05:04 | The logs on the panel in the 3D graph now cover the actual UI view.... | editor: F-61 |
| 2026-09-26 19:11 | Go ahead with the fresh-workspace test runner | none for 2D: operational (session, build, git, process) |
| 2026-09-26 21:03 | Is the cron loop still running? | none for 2D: operational (session, build, git, process) |
| 2026-10-07 01:26 | Let's pick up where we left off | none for 2D: operational (session, build, git, process) |
| 2026-10-07 02:05 | Never mind, you fixed the dual issue | none for 2D: operational (session, build, git, process) |
| 2026-10-07 08:46 | The app was quit while you were working. Please continue from where... | none for 2D: operational (session, build, git, process) |
| 2026-10-12 03:37 | are tests currently running? | none for 2D: operational (session, build, git, process) |
| 2026-10-19 02:01 | wouldnt be this repo but nearby folders that the repo is in likely | none for 2D: model files (§10c, F-9) |
| 2026-10-19 02:04 | perhaps explore faster models of jev that also use deepseek, it thi... | none for 2D: models (§10c, F-9) |
| 2026-10-21 00:01 | can you please remove all secrets and push to a brand new remote (p... | none for 2D: operational (session, build, git, process) |
| 2026-10-21 00:19 | logged into github. please push like i asked | none for 2D: operational (session, build, git, process) |
| 2026-10-21 00:26 | please very quickly start the sidecar again | none for 2D: operational (session, build, git, process) |
| 2026-10-29 23:53 | Let's bring the mortegon back up | none for 2D: operational (session, build, git, process) |
| 2026-10-29 23:54 | please close this thing | none for 2D: operational (session, build, git, process) |
| 2026-10-29 23:58 | Thank you. Let's bring our full obsidian plugin sidecar etc back up | none for 2D: operational (session, build, git, process) |
| 2026-10-30 12:00 | take the older PRD rows next in order | none for 2D: operational (session, build, git, process) |
| 2026-11-01 21:49 | please continue, bringing the app back up | none for 2D: operational (session, build, git, process) |
| 2026-11-04 23:23 | We have about 17% of our weekly token limit, so we need to make it... | none for 2D: about the record or the process |
| 2026-11-07 00:22 | conductor we have a problem | none for 2D: operational (session, build, git, process) |
| 2026-11-07 16:45 | Please continue on all open glitches I had noted to you. There were... | none for 2D: about the record or the process |
| 2026-11-07 16:50 | Including what you found in transcripts | none for 2D: about the record or the process |
| 2026-11-08 17:41 | Please clearly and legibly state all decisions needed from me | the process: the one design decision for the reader is O-5, stated in §14; closing the covering cards (O-3) is the reader's layout, asked 2026-11-24 |
| 2026-11-08 17:43 | Continuous motion currently in our 3D graph, causing significant an... | editor: F-60, F-64 |
| 2026-11-08 18:33 | There is still significant jostling when there wasn't before. I thi... | editor: F-60 |
| 2026-11-08 19:16 | I need something like this to work with our whole plugin without de... | editor: "without degrading the plugin's functions" -- every slice keeps the plugin's checks green (§13k) |
| 2026-11-08 20:17 | If you haven't noticed, things are broken | none for 2D: operational (session, build, git, process) |
| 2026-11-09 01:37 | Please also commit and push to our remote branch whenever the next... | none for 2D: the recenter is a 3D camera action; the plane is fixed to the camera |
| 2026-11-09 06:49 | please also screen for and remove all secrets and personal data thr... | none for 2D: operational (session, build, git, process) |
| 2026-11-09 07:00 | Alright. lets continue, we have tons of ego interface completion le... | none for 2D: operational (session, build, git, process) |
| 2026-11-14 18:33 | I got some transcripts from 3-5 days ago with antigravity locally w... | none for 2D: older defects from another tool's transcripts |
| 2026-11-15 01:43 | I reset the GPU driver, check if it cleared | none for 2D: operational (session, build, git, process) |
| 2026-11-15 02:01 | keep going on the open list while it warms up | none for 2D: operational (session, build, git, process) |
| 2026-11-15 21:10 | You're wrong. look at the original suggestion for things like impec... | none found for 2D: a design-skill suggestion, its object unrecorded |
| 2026-11-15 21:48 | from here on out, run all harnesses yourself, never use agents, thi... | verification: F-63 |
| 2026-11-22 00:11 | why does the vault need reindexing each time? this seems inefficient | none for 2D: vault indexing |
| 2026-11-22 01:19 | wire the token stream into the app's chat panel | editor: F-62 |
| 2026-11-22 10:04 | done gaming, go ahead with the restart and re-runs | none for 2D: operational (session, build, git, process) |
