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
similar(cid, k=8)                          # new: /search?ref= (G-372 step 2) -- a chunk's neighbours
Database.cypher("MATCH (p:Page) RETURN count(p)")  # exists: read-only, writes refused
```

```python
# browser cell -- the live page
WebBrowser.url                             # exists: what the cell shows now
WebBrowser.go("https://en.wikipedia.org/wiki/Trie")  # exists: carried out when the cell ends
WebBrowser.chunks()                        # exists: the stored chunks of the page shown
WebBrowser.pin(xpath)                      # new: the right-click pin -> a stuck plane panel (133 b)
WebBrowser.controls()                      # new: the page's interactive fields, by address (affordances)
WebBrowser.act(address, value)             # new: act on a field in place through its trie address
```

```python
# panels -- a chunk's two forms
chunk(cid)                                 # new: /chunk -- the markdown, each line with its address
page_form(cid)                             # new: /snapshot/<cid> -- the saved page form, or None
resolve(url, xpath)                        # new: /resolve -- the chunk that draws an address
```

```python
# 3D graph -- the world
focus(cid)                                 # new: fly to a node (the plugin, not the sidecar)
unfold(url)                                # new: /unfold -- a page into its chunks
pages(contains="wiki")                     # new: /pages -- stored page urls
```

```python
# the ego -- the tool space as one graph
ego()                                      # new: /ego -- its nodes and links
attach(cid)                                # new: tag a chunk into the ego
view("third")                              # new: first / third person (G-333's camera field)
```

```python
# notebook / slates -- the computation graph itself
Vault.read("notes/Lattice.md")             # exists: the vault's files
Vault.write("notes/out.md", text)          # exists: inside the vault only, never .obsidian/.git
Agent.ask("summarise", context=hits)       # exists: the sidecar's local model, one session per kernel
check(slate)                               # new: /slate_check -- the dialect's own errors (2026-11-01 62)
```

Counted: **10 calls exist, 14 are new** (computed: `python -m domvec.tool_surface` reads these blocks and resolves each call against the kernel bootstrap; `tests/test_tool_surface.py`) -- and every new one sits on a route
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
