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
`(2026-11-01) 62` is not `(2026-10-11) 62`.

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
| 2026-10-18, 186a-186n | Install three local quantized models; "local code -> agents through interface panels"; (186c) "hard type constraints and conventions per quantised model and task"; (186e) recover the mothership's (mortegon) recursive reservoir 2D computation-graph editor | `GRAPH_WORKBENCH_DESIGN.md`, rows `G-237..G-240` (Open; models declined for now, 2026-11-16 (165)) |
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

Where the verbatim record ends: 2026-11-21, item 166. Anything below that
line in any design is interpretation.

## 2. The designs already written, and what 166 does to each

| Document | Holds | After 166 |
|---|---|---|
| `CALLABLE_INTERFACE.md` | The safe small-model interface; single-hop toolspace | **Revived in spirit**: 166's tool panels are its natural successor -- one toolspace per artifact, small enough to sit in a quantized model's context |
| `NOTEBOOK_PANEL_DESIGN.md` | The kernel panel, outputs-in-markdown, vault-note addressing; §8 three open questions | Kept; its cells become the editor's unit |
| `GRAPH_WORKBENCH_DESIGN.md` | Code, models and workflows as graph nodes; the mothership's editor recovered | Kept for workflows and models; its "code as graph nodes" is narrowed by 166 (a) |
| `CODE_ARTIFACTS_DESIGN.md` | The codebase and PyPI packages drawn in 3D | **Superseded in its layout part by 166 (a)**, pending the reader's confirmation (§6 Q1) |
| `RESERVOIR_DESIGN.md` | The 2D/3D reservoir, cockpit, craft | Kept; §5 already corrected by (2026-11-01) 67 |
| `SEARCH_GRAPH_DESIGN.md` | Search as one node, I/O as hard links | Kept; it is the db-search tool panel's graph form |

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
   kernel (`(2026-11-01) 49`).
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
named where one exists). Nothing below is decided.

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

Counted: **25 calls exist, 0 are new** (2026-11-22, G-377 built: the fourteen that were new, plus `types` for G-388; it was 10 exist / 14 new before) (computed: `python -m domvec.tool_surface` reads these blocks and resolves each call against the kernel bootstrap; `tests/test_tool_surface.py`) -- and every new one sits on a route
or plugin action that already exists, so the surfaces are wrappers, not new
machinery. Two rows decide their shape: `G-378` (a tool panel is read-only
and cannot open the code behind it) and `G-380` (marimo-style: a call that
changes the world in place -- `go`, `pin`, `act`, `attach` -- is invisible to
name dataflow, so each returns a value that names what changed).

## 9. Research: permissive libraries against the verbatim (2026-11-21)

Asked for: "keep researching on marimo and other permissive libraries that
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
  marimo's runtime. This is the reader's call.
- **Graph edits that keep the code readable.** A regular code artifact is
  graph-editable (`G-378`); an edit made on the graph has to be written back
  into the cell without destroying it. LibCST reprints code losslessly, and
  its rule that a statement owns its trailing same-line comment is the exact
  form of a tool surface line (`G-377`).
- **The plane's editor.** The plane is already drawn in the 3D view
  (2026-11-01 50). Of the node editors, litegraph.js is the only one without a
  component framework -- the plugin uses none -- and it exports JSON; the
  others would bring React or Vue into the plugin. Whether any replaces the
  plane's own drawing is open.
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
| edges of the graph face (who reads whose names) | marimo's rules | built as `domvec/dataflow.py` (G-380); marimo's own analysis is internal, not a public API -- whether to call into it instead is open |
| a graph-face edit written back into the code face, comments and layout kept | LibCST (MIT, **installed**, 1.9.0) | not started -- the write-back half of G-378 |
| a module called as a node from another note | marimo's `app.embed(defs=...)` shape: free names in, definitions out | not started |
| the plane on which the graph face is drawn and edited, inside the 3D layout | litegraph.js (MIT, Canvas2D, no framework) or the plane's own drawing (`planepanels.ts`) | open -- the plane already exists in 3D |
| the agent that writes cells | smolagents `CodeAgent` (§10b) | not installed |
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

## 11. The mortegon docs, read against the computation graph editor (2026-11-21, asked in PLUGIN_GOAL 169)

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
| the panel / graph commute, node-count parity, undirected lines, no arrowheads (R.1, O.1, O.16) | the plane's two forms | the plane, `planepanels.ts` | the standing goal | a node editor (litegraph.js) only if it can draw undirected, arrowless links and stay in parity with the slate |
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
   `review`. Added below as `new`, for the reader to correct.
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
link("DuckDuckGo", "scanner")              # exists: left-click-drag in graph form (N.4)
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
dialect as distilled), §8-§11 above, and PLUGIN_GOAL 130-186. §12f names what
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
(this replaces 183's `![[...]]` / `[[...]]` encoding, 12f).

"One record, one place drawn open" (184 a). A record revealed inline AND open
as a panel would be two placements in 2D at once. Opening it as a panel
resolves its braces to external: they fold to their line, and a solid line
joins them to the panel.

### 12b. The one panel, the one grammar

- **The one markdown panel** is Obsidian's own markdown view, extended, the
  same code everywhere: billboard markdown, code and node markdown, notebook
  markdown cells, slates, the clipboard, chat (DESIGN_VISION 1.6; 5160 "Not
  three different markdowns"; 5364 "one unified markdown panel"; 131-132 "the
  slate is the markdown part of the notebook").
- **The grammar** is the slate's: tabs and newlines, names (spaces allowed,
  N.7), values, and `{ref}` as the only markup (RESERVOIR §3.1). Every field
  NAME is a variable, drawn as a node in Obsidian's purple link style; values
  stay plain (54, 55, 60); plain prose is never highlighted (137.9). It is a
  Python module written as markdown (62, 63'): a name bound twice is an error.
- **The gestures** are the native editor's plus UR §7.3.4 (RESERVOIR §3.3):
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
  cockpit's fields (`view`, `camera`, `throttle`, `keys`, `plan`, `play`,
  `search`) and the component fields sit in ONE slate. A separate "ego canvas"
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
- **Magnetism is placement and order, never a link** (136, 142, T-11). It
  serialises compilation, rows top to bottom then left to right, and gives a
  chat cell its context (T-2).
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
  surfaces are the rest.
- **Black boxes all the way down** (80, 112, RESERVOIR §12.4): a `{code://...}`
  field reveals its module's rank-1 definitions, each again a field, down to
  the compiled base. The reveal is the one in 12a, nothing separate.
- **The agent** (170.3, §10b-§11d) runs as smolagents steps. Each step is one
  code cell appended to a note, its observation that cell's output. Its
  context is the canvas read in compile order, each field as deep as it is
  revealed (rank-1 minimalism, N.14). Its editor calls (`create`, `link`,
  `invoke`, `commit`, `review`) are the reader's own gestures.
- **Chat** (182) is a note of records: a turn's prompt, prose and each code
  block are fields, and a code block carries the code-cell tools and typed
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
are listed at the end. Where the text below says "reading" it is mine.

### 13a. What binds the 2D editor -- the record, gathered

Every row is the reader's own words or a ruling on them. 187 replaces none of
them except where it says so, and recency decides any conflict (item 124).

| # | commitment | source |
|---|---|---|
| B1 | ONE record, many placements -- never copies kept in sync | 37, R.1, O.19, RESERVOIR §5 |
| B2 | the panel and graph forms COMMUTE: an edit in either round-trips losslessly | R.1, O.1, 135b |
| B3 | hard links come ONLY from compilation (a name defined and read, a `{ref}`, a terminal call, one chunk object); magnetism is order, never a link | 136, 142, T-4, T-11 |
| B4 | links are drawn UNDIRECTED, no arrowheads; the direction is computed | O.16, 170.2, G-383 |
| B5 | dataflow is marimo-style: dependencies read statically from definitions and reads; running re-runs the readers | 167 f, G-380 |
| B6 | cells run in the note's real Jupyter kernel; outputs live IN the markdown (trie content, one source of truth) | 49, NOTEBOOK §1, §4b |
| B7 | every thing has a governing class of ~25 lines whose public methods are its capabilities; class and instance are two linked nodes | 142, T-10, 89 |
| B8 | a TOOL panel is read-only, calls only, "implicit calls into the world itself"; a REGULAR code artifact is callable the same way AND explorable and graph-editable | 167 c, F.5-F.6, G-378 |
| B9 | a Python object enters as typed rows `name: Type = value`; a function is memory lookup to its inputs, its output type inferred by wiring | M.2-M.5, E.6, O.15 |
| B10 | the ONE markdown panel (Obsidian's own, extended) for every prose surface | 56, 133 c, 140 |
| B11 | a code artifact has ONE interface -- run, terminal, open, unnest, typed rows -- wherever it sits | 182 addenda, G-395 |
| B12 | the graph-view FORM goes; the nodes are the interactive typed artifacts themselves; in 2D only interface canvases, no circles | 182, 183 |
| B13 | no special effects; one uniform display of node and link | 158, 186 |
| B14 | gestures: single click edits in place; right-click reveals/folds; right-click on the base collapses the record to its node; double right-click deletes a link or reference; a press held past a debounce picks up, never a plain click | M.6-M.8, N.13, 110, 182 |
| B15 | the plane is fixed to the camera; shift-scroll zooms the 2D plane, plain scroll the 3D view; the ego at the centre of view | 158, 159, 146 |
| B16 | rank-1 minimalism; black boxes unfold recursively down to the base modules | N.14, R.3, 80, 112 |
| B17 | the base toolset: browser, database retrieval, code/kernels, terminals, chat | 166, 187 |
| B18 | signal flow is visible as light, in 2D and 3D | 99, 114 |
| B19 | the agent loop is smolagents' step; each step a cell | 170.3, G-384 |
| B20 | the bar: complex quantized-model workflows, custom tools written on the fly, in the same editor | 166 d-e, 187 |

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

What 187 does NOT change: B1-B11 and B14-B20. The slate grammar stays the
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
- **a prose note on the plane** is the same: the one markdown panel (B10) as
  a node body, with ports for the names it defines and reads.

This is the plane 183 described: interface canvases joined by links, where
the links are now the editor's own.

### 13d. One source of truth, three projections

The text of the note -- its markdown, its code cells and their outputs -- is
the only stored truth (B6, NOTEBOOK §1's "two sources of truth" argument). The
graph editor's own JSON (`graph.serialize()`) is **never stored as authority**.
It is rebuilt from the note, and a gesture on it is written back into the note
as text.

| projection | built from | written back by |
|---|---|---|
| **code**: the cells and the terminal | the note's text, run in its kernel (B6) | the reader typing |
| **object canvas**: a live object's own widget | the object's traits over the comm (§13e) | `model.set` + `save_changes` -> the trait in the kernel |
| **graph**: a node per cell, per live object and per function the note defines; a link per def/use edge | `dataflow.py` (B5) plus port definitions (§13d') | a drawn link becomes a line of code through LibCST; a deleted link removes it (§13f) |

In trie terms: the note is a `vault://` page and its cells are addresses on it
(`#cell n`, item 159). A node is a projection of one address. A link is a
def/use edge between two addresses, computed and never stored, and a widget
value is a trait whose assignment line sits at an address. Nothing in the
editor holds state the trie does not.

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
| a governing class's public method (B7) | a function node of the object (F.5) | -- | one `Output` per method | an output socket per method, called when the link is written |
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
  (item 4), so an object's canvas on the plane and its billboard in 3D are
  two `render`s of one model. Nothing is copied.
- *CSS goes in a shadow root*, as marimo hosts it. The AFM loads `_css`
  globally, and Obsidian's own styles are global too (B10), so a widget's CSS
  must not leak into the app.
- *A trait change is a dataflow event.* marimo's rule: "When a UI element
  assigned to a global variable is interacted with, marimo automatically runs
  all cells that reference the variable (but don't define it)". In ours, a
  `change:` from a view sets the trait in the kernel. `dataflow.rerun_plan`
  then runs the cells that read the object's name (B5), and their outputs
  re-render (B6). marimo also needs the wrapper `mo.ui.anywidget` for this to
  happen, so a trait change alone does not count as a definition. The same
  holds here: the comm bridge reports the change and the dataflow decides
  the re-run.
- *The terminal sees the same objects* (187 "terminal use"). A trait set from
  a terminal call into the kernel (`w.value = 3`) emits `update`, and every
  view redraws.

**The bridge that has to exist** (measured in `domvec/obsidian/kernel.py`):
`JupyterKernel.run` reads iopub only while a cell runs, and keeps `stream`,
`execute_result`, `display_data` (text/plain) and `error`. It drops
`comm_open`, `comm_msg` and the widget mimetype
`application/vnd.jupyter.widget-view+json`. So: an iopub reader thread per
kernel that keeps comm traffic at all times; a comm log with a sequence
number that the plugin long-polls; and `comm_msg` sent back on the shell
channel. `/chat_stream` is the only push channel today, so the long poll is
the same pattern.

### 13f. Links: drawn, compiled, undirected

- **A drawn link is code** (B3). Connecting A's output to B's input writes
  the binding into the note's cell: `b_in = a.out()` for a function, or
  `b.x = a.y` / `traitlets.link((a, "y"), (b, "x"))` for live objects. It is
  written losslessly through LibCST (installed). The edge then exists because
  the code defines and reads a name. A link that would not compile, or would
  close a cycle (`dataflow.CycleError`), is refused and never drawn.
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
  - `IS_CHANGED` / `fingerprint_inputs` is our `exact_hash` of the cell source
    (NOTEBOOK §4);
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
| dark grey theme | Obsidian's own look for markdown bodies (56); black slate for code (S.4) | the theme from Obsidian's CSS variables |
| its own canvas pan | the plane is fixed to the camera, the ego at the centre (159, 146) | the litegraph canvas is the plane's surface; the plane keeps its place |
| search box on double-click | new nodes from the retrieval bar over typed nodes (133 d) | the searchbox fed by the retrieval bar's typed nodes |

**DOM in a node.** A litegraph widget is drawn on the canvas. An Obsidian
editor and an AFM view are DOM. ComfyUI's front end overlays DOM widgets on
the canvas and re-places them from the canvas transform each frame, hiding
them below a zoom threshold. The panels on our plane are already DOM over the
3D canvas (`planepanels.ts`), so the same placement applies: a node's body is
its DOM, positioned by `ds` (the canvas's DragAndScale). Reading: below the
zoom threshold the node shows its title, which is the fold parameter of
item 110, not a separate mode.

### 13h. The base tools as live objects -- chat first

Each base tool (B17) is ONE live-object class. Its public methods are its
~25-line capability list (B7). Its traits are its state, and its read-only
class listing is its tool panel (B8). `kernel_objects.py` already boots
`search`, `Database`, `WebBrowser`, `Agent`, `Vault` and the editor calls
(`create`, `link`, `invoke`, `commit`, `review`, `answer`) into every kernel,
and `domvec/governing/browser.py` is the first governing class. Each becomes a
traitlets object with an AFM view.

**Chat first**, because 187 says chat models force the standard:
- `Chat(model, tools)` holds `messages` as a trait;
- its view is the conversation: a clear input box and typed blocks (G-394),
  each code block a cell with the one code interface (B11);
- tokens stream as `custom` messages, the protocol's free channel (171);
- the callback is marimo's `mo.ui.chat` shape: `model(messages, config)` may
  be a generator that yields DELTAS, which the view accumulates; a Stop
  cancels it (sync generators get `GeneratorExit`, async ones
  `CancelledError`);
- the agent is smolagents' `CodeAgent` (B19): each step is a cell, and a
  tool defined in a cell is a node on the plane AND a tool the agent is
  handed in the next step (B20).

### 13i. What stands from §12, what this replaces

| §12 | after 187 |
|---|---|
| 12a one record, placements | **stands** (B1). The placements gain the object canvas (§13e) and the graph node (§13c) |
| 12b one panel, the grammar, gestures, no effects, edit in place | **stands for prose and slates**. The gestures map onto the editor (§13g) |
| 12c the ego canvas is the ego slate's fields | **stands as the cockpit's record**. Its components are nodes on the plane, the ego slate's fields ordering them (compile order, 142) |
| 12d links from compilation | **stands**, made concrete by §13f |
| 12e governing class, tool panels, agents, chat | **stands**, each made a live object (§13h) |
| 12f 3D | **stands**: a 3D billboard is one more `render` of the same model |
| 12h G-401 (fields in the ego slate) | built; stands for the cockpit |
| 12h G-402/403 (reveal editable; resolved-external drop) | **superseded for code objects** by the object canvas and the editor's nodes; stands for prose fields |
| 12h G-404 (links only from compilation) | **stands** |
| 12h G-405 (the craft's circles hidden) | **stands** |
| 12h G-406 (code field reveals tools and typed rows) | **superseded** by §13d' (typed rows ARE ports and widgets) |
| 12h G-407 (browser field reveals its rendering) | **superseded** by the browser as a live object (§13h) |

### 13j. Packages -- what can be used, and what each needs

| package | licence | state (checked 2026-11-22) | for |
|---|---|---|---|
| `anywidget` | MIT | active; the AFM spec at 0.11 | live objects' Python side; pulls `ipywidgets` (BSD-3) |
| `@comfyorg/litegraph` | MIT | **archived**. Merged into `Comfy-Org/ComfyUI_frontend` (`src/lib/litegraph`) on 2025-08-05, and that repository is **GPL-3.0**. Only the npm releases published before the merge are confirmed MIT | the graphical side, in TypeScript |
| `litegraph.js` (jagenjo) | MIT | 0.7.18 the latest on npm; not confirmed maintained | the same, in JavaScript |

So: **code is never taken from ComfyUI_frontend's tree** (GPL-3.0). The
editor is a pinned, MIT-licensed litegraph release vendored into the plugin.
Reading: the last standalone `@comfyorg/litegraph`, because it is TypeScript
like the plugin and carries ComfyUI's widget work, frozen and owned here from
then on.

Every row above is a download, so each waits for a yes.

### 13k. Build order -- each a live check with a planted arm

| row | slice | proof (live) | planted |
|---|---|---|---|
| G-408 | the comm bridge: an iopub reader per kernel; a comm log with a sequence number, long-polled; `comm_msg` back on the shell channel | a comm opened by a cell is read in the plugin; a `comm_msg` sent from the plugin changes a value read back in the kernel | the reader off: the comm is never seen |
| G-409 | node definitions from the live namespace (§13d'): signatures, hints, traits | a function defined in a cell appears in the definitions with its ports; a default primitive is a widget, an object type a socket | hints ignored: every input a socket |
| G-410 | the AFM host in a plane panel, per the nine MUSTs | an anywidget made in a cell renders; set from a terminal, the view updates; set in the view, the kernel reads it; two views, one model | `save_changes` dropped: the kernel never sees the view's set |
| G-411 | litegraph on the plane: nodes from G-409, links from def/use, gestures per §13g, no arrowheads, one shape | the graph's links equal `dataflow`'s edges; a drawn link writes one line, a deleted one removes it, a cycle is refused | a link drawn without the write-back: the code and the graph disagree |
| G-412 | `Chat` as a live object (§13h) | tokens stream into the view; a code block runs as a cell; a tool defined in a cell is called by the agent | deltas accumulated in Python: the view gets whole messages |
| G-413 | the base tools as live objects: Search, Browser, Terminal, Kernel, from their governing classes | each tool panel lists its class read-only; an instance's trait changes re-run its readers | the dataflow event off: readers stay stale |

G-408 and G-409 need no download. G-410 to G-413 wait on §13j.

### 13l. Readings that are mine

None of these is a question: the record settles each, and they are written
here so a correction has somewhere to land.

- 182/183 + 187 = nodes that are their interfaces (§13c), by 182's own words
  and recency (124).
- The node-definition schema is one table (§13d'), from M.3 + ComfyUI +
  Langflow.
- litegraph's JSON is never authority (§13d), by NOTEBOOK §1's argument.
- The pinned MIT litegraph is the editor (§13j), by licence and language.

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
