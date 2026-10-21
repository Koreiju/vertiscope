# Code artifacts — design against the record (2026-10-18)

Binding text: `PLUGIN_GOAL.md` Addendum XI, items (162)–(170), in the reader's
own words. Rows: `PLUGIN_PRD.md` `G-233`–`G-241`. This note maps them onto
what already exists, says what is new, answers the layout question (170) as
a proposal to be MEASURED, and orders the work. Where it names something the
reader did not say, it says so.

## 1. What is already on record and built

| Record | What exists | Where |
|---|---|---|
| `G-49`, `G-11` | The repository, the vault and installed packages are in the trie beside the web: `code://<root>/<path.py>`, `code://pypi/<pkg>/…` | `vertiscope/source.py`, `vertiscope/packages.py` |
| `G-49` addressing | A Python file is addressed by its OWN syntax: `/module[1]/class[1]/function[1]/code[1]`, docstrings and comments as their own units | `source.tag_source` |
| `G-8`, `G-51` | Imports are links (`LinksTo`), the relationship a hyperlink uses — one graph, not two | `source._import_targets` |
| `G-52`, `P-C3`, `P-C4` | Code is vectorised by its comments and docstrings ONLY; 66.2% of this repo's rendered tokens are code and are dropped from the encoder | `tokens.for_model` |
| `G-104` | Each installed package is a tree-shaped projection with directory and import edges (141 module pages, 132 tree edges, 264 import edges seen live) | `POST /package`, projector |
| `R-6` | Package retrieval: a vector-centroid pre-filter, then partition-wise ranking, inside the one `/search` | `ThreeFormIndex._prefilter_code` |
| `P-N1`, `P-N2` | A python kernel per note (`POST /kernel`) and shells per pane (`GET /interpreters`) | sidecar `kernel.py`, `shell.py` |
| `P-N5` | Notes and their cell outputs chunk through the same recursive descent as pages | `vertiscope notes` |
| MCP | The workspace is already an MCP server (search, chunk, resolve_address, …) | `vertiscope/obsidian/mcp.py` |
| store | Kuzu is a PROPERTY graph: typed nodes, typed edges with properties (`Anchors {ord}`) | `vertiscope/graphstore.py` |

Open on record: `P-C1` (artifact viewable/editable standalone), `P-C2`
(terminal below it), `P-C5` (live module deltas), `P-N3` (a toggle on a
code block opens kernel or terminal), `P-N4`, `P-N6`, `G-105` (package
chunks into notebook cells as code prototypes), `L-*` (the small local chat,
Nous Hermes 2 DPO 7B named, deferred).

## 2. What Addendum XI adds, per item

**(162) Web code blocks — `G-233`.** The defect seen: huggingface's code
sample arrived as syntax-highlighting spans (`pre/code`, `pre/code/span[5]`)
split over two chunks, and the copy button beside it was its own chunk
reading "button". The fold makes a `pre` ONE atomic code unit — its composed
text whole, addressed at the `pre` — and the address continues below it by
the code's own syntax with `tag_source`, so a page's code sample and a repo
file are addressed alike: `https://…/pre` + `/module[1]/function[1]/code[1]`.
In trie terms: the `pre` node becomes the root of a code subtree, keyed the
same way `code://` keys files. An unlabeled control renders no text.

**(163) One class, one interface — `G-234`.** Web blocks, `code://` files and
note code cells are the same artifact: same chunker (`tag_source`), same
vectorised surface (`G-52`), same panel (`P-C1`/`P-C2`/`P-N3`). Nothing
new is invented: this is `P-C*` reached from three sources.

**(164) The CPG — `G-235`.** The AST is already the address (`G-49`). Added:
CFG (statement order within a function) and PDG (`DATA_FLOWS_TO`, def → use),
`CALLS`, `INHERITS` — as kuzu REL tables with properties (`line`,
`arg_passed`), the reader's (2). `IMPORTS` exists as `LinksTo`. Built over
every code artifact, incrementally per file (the reader's
`incremental_update`), which is the trie's own O(delta) rule.

**(165) Graph-diff upsert — `G-236`.** A mutation of the CPG compiled back to
source (`ast` + `difflib`), compile-checked, applied as a unified diff, and
re-ingested — the path `P-C5`'s live deltas take into the store and the view.

**(166) Models — `G-237`.** OpenJEV (typed choices), DeepSeek-Coder 6.7B
(code), Triplex (text → triples). Embeddings stay nomic. **Question for the
reader**: do these join or replace the recorded Nous Hermes 2 DPO 7B chat?

**(167) NL-first prototyping — `G-238`.** Docstring → wireframe (signature)
→ body, each step a retrieval over the CPG + docstrings + web knowledge.
Lands in `G-105`'s notebook cells.

**(168) Through-stacks — `G-239`.** Recorded verbatim; to be designed WITH
the reader. What already exists to build it from: per-pane kernels and
shells (an agent's isolated terminal), the MCP server (an agent's tool
surface), the trie (its addressable context), the store (the workspace
graph its calls become edges of). The other assistant's names — nine
layers, `Promise<T>`, `ValidatedCodeTransformation`, residuals — are NOT the
reader's and are not adopted until the reader says so.

**(169) Plugins — `G-240`.** The plugin already has this shape in one place:
every planted arm is a named switch on a stable core. A slot registry is
the general form; designed with (168).

## 3. The layout question (170) — a proposal, to be measured

The reader asks which form works best for the CPG's triple form (AST + CFG +
PDG), the docs/comments, and the code. Proposal: **both, at two scales** —
the same split the web graph already runs (UMAP fit for pages, forces inside
a page's room).

| What | Placed by | Why |
|---|---|---|
| Docstring / comment units | **UMAP** on their embeddings (`G-52`) | the only embedded surface; meaning decides where they sit |
| Module, class, function | home = its docstring's UMAP point, or its AST parent's when it has none | the code is not embedded (`G-52`), so it borrows a position from what is |
| AST (`CONTAINS`) | the containment tree: room + `contain` force, as pages contain chunks today | the tree is the address; drawn as the hierarchy |
| CFG (statement order) | **force-directed** links inside the function's room | order is local; a chain inside one room |
| PDG (`DATA_FLOWS_TO`), `CALLS`, imports | **drawn, not forces** — typed, coloured, toggleable edges | as forces they would drag semantic positions toward call structure and erase what UMAP measured |

Node kinds: Module, Class, Function, Statement (CFG), Variable (PDG),
Docstring/Comment. Edge types: CONTAINS, CFG, DATA_FLOWS_TO, CALLS, IMPORTS,
INHERITS — each its own style and a toggle. Interface per node: the code
artifact panel (`P-C1`) with the kernel/terminal toggle (`P-N3`).

**How it is decided, not argued** — three layouts (pure UMAP, pure force,
the hybrid) scored on the same package:

* semantic fidelity: k-NN recall of each docstring node against its
  embedding-space neighbours (UMAP wins by construction; the question is
  what the hybrid loses);
* structural legibility: mean drawn length and crossings of CFG and PDG
  edges (force wins by construction; the question is what the hybrid gains);
* motion: drift of settled nodes (`G-108`).

Planted arm: the same scores with the edge kinds shuffled, so a layout that
"wins" on structure must beat a structure it does not have.

## 4. Order of work

1. `G-233` — the `pre` as one code unit in the fold, sub-addressed by
   `tag_source`; the hover shows the code; unlabeled controls carry no text.
   (Begun 2026-10-18.)
2. `G-235` — CFG + PDG + CALLS edges in the store over `code://` first (one
   ingest path exists), then web code blocks.
3. `G-241` — the three-layout measurement on one package, then the chosen
   layout with typed edges and toggles.
4. `G-234` / `P-C1` / `P-N3` — the code artifact panel reached from all three
   sources.
5. `G-236` — graph-diff upsert, round-tripped through re-ingest.
6. `G-237`–`G-240` — after the reader's answers on models and on the
   through-stack design.
