# The graph workbench: code, models and workflows as graph nodes

*Design for PLUGIN_GOAL items 186a-186n (2026-10-18), with what was
recovered from the mothership project. Your words are in `PLUGIN_GOAL.md`
(Addendum XI, the answers of 2026-10-18); the mothership's are quoted by
section from `web_fiber_haptics` (`github.com/Koreiju/mortegon`, branch
`feat/v3.0-phase-9-cascaded-renderer`), `docs/USER_REQUIREMENTS_VERBATIM.md`
(cited **UR §x**) and `docs/DOMAIN_MODEL.md` (cited **DM §x**). Nothing here
is a decision you have not made; section 6 lists what is open.*

---

## 1. What the mothership already designed

mortegon is "the mortise-and-tenon joint between the 3D DOM scanner (the
spatial scene) and the 2D concept-graph editor (the symbolic computation
surface)". Its 2D editor was designed in detail across UR §C, §E, §F, §M,
§P, §Q, §R, §S, §T. The load-bearing parts, in its own terms:

**The card (UR §S.4, §T.1-T.8).** One black markdown slate -- thin silver
border, black infill, white serif text, "no x, no minimizer, no top bar
whatsoever" -- rendering a pure text tree of `name: value` rows over a typed
data block that stays "under the hood". A card that sticks to the editor
"should literally be just the panel summary from the scanned-rendered
sample" (T.2). It is "a tree-structured graph editor that is completely
in-text" (T.5).

**The typed panel form (UR §M.2-M.5, DM §9.6.1).** A Python object is a
card of typed fields whose values may be `{references}` to other nodes:

```
self:WebBrowser
   NO_CHANGE_LIMIT: int = 3
   driver: WebDriver = {driver}
   scanner: {FunctionOutPutType} = {scan}
```

Hovering a token expands its *next-rank type graph* (superclass,
properties, constructor parameters). A function expands to loosely linked
typed input and output fields; "forward calls linked to a function node via
equality of an input on the right and an output type on the left infer
output types" (M.5). Functions are "automatic memory lookup to inputs"
(M.3).

**The gestures (UR §M.6-M.8, §Q.3-Q.5, §R.5, §T.7, DM §7.3.4).**

| gesture | does |
|---|---|
| hover a token | its next-rank type graph, previewed |
| right-click a token | expand / collapse its next-rank links, fold state kept |
| right-click the card's base | collapse the whole card to its `self` node |
| double-left-click a card | compile it into computation-graph form (same folding, in graph space) |
| single-left-click | edit the token in place -- a borderless blinking cursor |
| markdown gestures (dash, tab, number, newline with text) | restructure the computation graph on the other side |
| in-card internalise / externalise | pull a linked object or graph into the card, or push it out to its own node |
| right-click a root (url, compute-graph node) in 3D | collapse what it dominates (rank-dominance); right-click again to unfold |

**The two sides commute (UR §R.1).** "Edits made in either representation
(the unfolded panel's field-tree, or the decomposed computation-graph
children) round-trip losslessly into the other."

**Compile (UR §E.1-E.11).** One recursive, syntax-agnostic descent (JSON,
lists, indented trees, HTML element trees, text) into `name: value` nodes;
`+->` adds a child and `+v` a sibling; `{var}` links; functions infer their
I/O types as they emerge; an output wired without its input is completed by
a *closest-inverse lookup* (E.6, DM §7.7); play/pause runs the rollout and
edits at any node (E.7); intermediate values render as child nodes (E.11).

**The base objects (UR §F).** `WebBrowser.web_query(url, ?query, samples)`,
`Database.search(semantic_query) / cypher(query)`,
`Agent.agent(meta_prompt, prompt, ?pydantic_output_template)` -- each
decomposed into object, property and function nodes (F.5).

**The reservoir (UR §M.1, §P, DM §7.8).** "Our 3D map is our
world-distribution ... our computation graph becomes a reservoir computer
with a generative readout property." Inputs are inverse lookups over xpath
chunk patterns (P.2); a rollout cascades render-compile to the *readout
nodes* -- "the final-most recursive unfolded nodes ... the perimeter" (P.3);
readouts stream to the 3D projector as deltas, asynchronously, as their
paths settle (P.6, P.7); only the perimeter is projected, as rendered panels
(R.4). A computation graph is ONE node in 3D, on the bisector between its
inputs' centroid and its outputs' centroid, linked to its input roots and
its perimeter nodes by a link network independent of the UMAP (P.8-P.10,
DM §6.6.4); clicking it opens the graph in the editor.

**The aim (UR §R.3).** "Recursive minimalism with memory-function
maximalism."

---

## 2. Where vertiscope already stands against it

| mortegon concept | in vertiscope now | gap |
|---|---|---|
| the card = panel summary of a scanned sample (T.2) | the billboard panel: a chunk's markdown at its trie address, live controls (G-111), page form (G-130) | not a black slate; not editable as a tree |
| `{ref}` fields, typed panel form (M.3) | none | -- |
| hover / right-click fold, collapse to `self` (M.6) | right-click folds a url node (G-110); a unit node per hovered part (G-251) | no fold inside a panel |
| double-click compiles to graph form (M.7) | `code://` chunks have a code property graph by the SAME addresses (G-235); `cpg_mutate` writes a graph change back as a diff (G-236) | no panel -> graph view |
| commuting dual (R.1) | `cpg_mutate`: a graph edit compiles to source, and re-ingesting rebuilds the graph -- **a commuting pair already, for code** | for code only; not for web chunks |
| the 3D map as world distribution (M.1) | the projector over every stored chunk (pages, vault, code) | -- |
| readout perimeter -> projector deltas (P.7) | grey nodes stream, are saved, projected (G-252, G-253) | nothing produces readouts yet |
| bisector compute-graph node (P.10) | a node at a computed place with a link network independent of UMAP: the `calls`/`inherits` overlay (G-241) is the same drawing path | no compute-graph node |
| base objects (F) | the sidecar's routes are these objects already: scan (WebBrowser), `/search` + kuzu (Database), GPT4All (Agent) | not exposed as nodes |
| closest-inverse lookup (E.6) | retrieval over the same vectors (tiered search, G-210) | -- |

The single most guaranteed observation: **for code, the dialectic already
commutes**. A function chunk, its CPG and its source are three projections
of one trie address, and a graph mutation round-trips to source and back
(`tests/test_cpg_mutate.py::test_applied_and_reingested_the_store_graph_follows`).
Everything below builds from that pair outward.

---

## 3. The compact code knowledge graph (186g)

You asked for one "Occam's-razor" graph of what code *is* and *does*, from
the three representations; "`a = b` would be one triple. so would be package
imports."

The three, as stored (G-235): AST (containment), CFG (order and branches),
DFG (a value's definition reaching its use). Their union is redundant for
a reader: CFG edges between straight-line statements say nothing a line
number does not, and AST containment is the address itself
(`/module/class/function/stmt[3]`). The compact graph keeps what is not
derivable from the address:

| triple | from | example |
|---|---|---|
| `(scope, DEFINES, name)` | AST: a def, class, assignment target, import alias | `(module, DEFINES, pipe)` |
| `(name, ASSIGNED_FROM, expr-name)` | DFG: each name read on the right of an assignment | `a = b` -> `(a, ASSIGNED_FROM, b)` |
| `(scope, IMPORTS, qualified)` | AST import | `(module, IMPORTS, transformers.pipeline)` |
| `(scope, CALLS, qualified)` | CALLS, resolved by qualified name | `(run, CALLS, mylib.pipeline)` |
| `(class, INHERITS, qualified)` | INHERITS | `(Store, INHERITS, dict)` |
| `(function, TAKES, param)`, `(function, RETURNS, name)` | AST args, return | `(run, TAKES, x)` |
| `(stmt, BRANCHES_ON, name)` | CFG true/false edges: the names a branch tests | `(stmt[2], BRANCHES_ON, value)` |

Every subject is a trie address, so a triple is drawn, hovered and opened
exactly as a chunk is. Each triple names the CPG edges it summarises, so the
compact graph is a VIEW of the full one, never a second store that can
drift (the rule CLAUDE.md 5c states for cached verdicts). Built in
`vertiscope/code_kg.py`, section 5.

The same triple vocabulary is the target for the two other producers you
named: a web code panel goes straight to it (186h -- already, through the
web code CPG), a web text panel goes to triples by Triplex (186h), and a
chat model's answer, markdown with code, is the HYBRID: its prose by
Triplex, its code blocks by the code KG (186j).

---

## 4. Files and models as typed nodes (186b, 186c, 186j, 186k, 186l)

**A file is content** (186k). A link whose destination is a `.gguf`,
`.csv`, `.json`, `.zip`, `.tar(.gz)`, `.parquet`, `.safetensors` is a
special file: detected where the link is (its trie address), stored as a
`File` record `{url, name, ext, kind, size?}` linked to its chunk, and
drawn as its own node hung from that chunk (the unit-node path of G-251).
One panel per kind:

| kind | panel | its typed I/O |
|---|---|---|
| table (`<table>`, `.csv`) | a simple table view (rows x columns) | `rows: list[dict[str, str]]` |
| `.json` | the field tree of its parsed value (UR §E.1's syntax-agnostic descent) | the value |
| archive (`.zip`, `.tar`) | its member list | `members: list[str]` |
| `.gguf` | the model card: architecture, quant, size, context, the role; an **install** field | per role, below |

**Installing a model** (186b) is that panel's field, not a verb typed
anywhere (CLAUDE.md hard constraint 2): the GGUF's link is where it was
found (a Hugging Face file list is a page like any other), the panel shows
its size and quantisation, and installing writes it to the local model
directory and turns the file node into a **model node**. A model node has a
black-box I/O panel (186l) whose ports are its role's types:

| role (186j) | input | output | parsed into |
|---|---|---|---|
| chat (Nous Hermes, DeepSeek-Coder) | `prompt: str`, `meta_prompt: str`, `?schema` | markdown with code | hybrid: prose -> Triplex triples, code -> code KG |
| Triplex | `text: str`, `entity_types: list[str]`, `predicates: list[str]` | JSON triples | `(subject, predicate, object)` linked to the source chunk; force-directed, no embedding of its own (186l) |
| OpenJEV | `schema` (its typed categoricals) | a typed object | the object's field tree (a card) |
| embedder (nomic) | `text` | vector | -- (the projector's) |

**The models on disk (2026-10-18, approved downloads into `~/.cache/gpt4all`):**

| model | file | size | base | fits 8 GB VRAM |
|---|---|---|---|---|
| DeepSeek-Coder 6.7B Instruct | `deepseek-coder-6.7b-instruct.Q4_K_M.gguf` | 4.08 GB | DeepSeek | yes |
| Triplex | `triplex-Q4_K_M.gguf` (`SciPhi/Triplex` `quantized_model-Q4_K_M.gguf`) | 2.39 GB | Phi-3 | yes |
| OpenJev 27B | `OpenJev-Q4_K_M.gguf` | 16.55 GB | -- (27B) | no: mostly CPU/RAM |
| OpenJev Flash 9B | `OpenJev-Flash-9B-Q4_K_M.gguf` | 5.63 GB | Qwen3.5-9B | yes |

You asked for faster JEV models that also use DeepSeek. Across ~1,200
Hugging Face listings for JEV, decision-model, typed-decisions and
system-one, none has a DeepSeek base (by name or `base_model` tag). The
fast member of the family is the publisher's own **OpenJev Flash 9B**:
same request/response API as the 27B ("move to the 27B where you need the
extra accuracy, without changing client code"), 1.6x faster on equal
hardware by its card, and the one that fits this GPU. The trade-off is
therefore Flash 9B by default, 27B where a decision needs the accuracy --
one node kind with a size field, not two kinds.

**JEV is not a chat model, and that decides its runtime.** Its card: "The
answer is read from the scores at the first output position, one score per
option. Fixed calibration settings turn those scores into probabilities."
Its I/O is a typed request -- a `state` text and named `questions`, each a
`choice` over up to 52 options, a `score` over ordered levels, or a `noul`
yes/no -- and a typed answer: a probability per option. That is exactly
186c's hard type constraint, and it needs the logits of the first output
position. `gpt4all` (installed) generates text and does not expose them;
`llama-cpp-python` does (`logits_all`), and needs installing -- with CUDA, a
compiled wheel -- and its llama.cpp must support the Qwen3.5 architecture.
Both are checks before a JEV node can run; the panel can show its typed
request form before then.

The guarantee for "strict-native" output is mechanical, not hoped for: a
role's parser either yields its type or reports why it did not, and an
output that does not parse is shown as text with that reason, never
silently coerced.

---

## 5. What is built now, and what is guaranteed

Ordered by how much is already certain:

1. **The compact code KG** -- a deterministic function of the stored CPG
   (`vertiscope/code_kg.py`), tested against a fixed module: built.
2. **Special files detected and stored** -- the link's destination and its
   extension are already in the trie: built, with a planted arm.
3. **Model registry and typed runner** -- a GGUF on disk is a model node;
   running it is `gpt4all` (installed) with the role's parser; the three
   downloads you approved are under way (`~/.cache/gpt4all`).
4. **Triplex over a chunk** -- once its file is local: text in, triples out,
   linked to the chunk's address.
5. **Table view** -- one open Wikipedia panel renders a table wrongly now;
   found and fixed against the page.

Design that continues with you (section 6): the 2D editor view itself, the
reservoir rollout over chunk patterns, aggregate pydantic types from trie
paths across pages (186f), through-stack agents (186i, G-239).

---

## 6. Open, for you

- **The 2D editor's host.** An Obsidian view beside the 3D one (the plugin
  hosts both today), or a canvas inside the 3D view? mortegon put it beside.
- **Aggregates across pages (186f).** A trie-path PATTERN
  (`/html/body/main/article[*]/h2`) over many pages is the natural type
  generator: its matches are the instances, its sub-paths the fields. Is a
  pattern the unit you meant, or a hand-picked set of paths?
- **Rank-dominance collapse (UR §Q.5)** generalised to every node in 3D and
  2D: the url fold (G-110) is its first case.
