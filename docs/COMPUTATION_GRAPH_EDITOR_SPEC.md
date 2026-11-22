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

Counted: **10 calls exist, 14 are new** -- and every new one sits on a route
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

### 9b. For the reader to decide

1. marimo as a dependency (its `.py` format and runtime), or marimo's rules
   implemented over the slate dialect?
2. smolagents' `CodeAgent` as the agent loop over the tool surfaces, or the
   loop written in the editor itself, as cells?
3. A node-editor library for the plane, or keep drawing it ourselves?
