# The whole design vision, read from the verbatim (2026-11-08)

Asked for by PLUGIN_GOAL (142): every verbatim on the ego, the computation
graph, panels, cells, gestures, rendering, syntax, assumptions, constraints and
extensions, **not filtered by built vs unbuilt**, read as the parts of one
design, with what older designs carried over, what was superseded, and where an
older design and the current intuition still pull apart and need a ruling.

Line numbers like `PG 4487` point into `docs/PLUGIN_GOAL.md`. Everything
written in plain text here is MY reading; your words are in quotes. Sources
read: the whole of PLUGIN_GOAL's verbatim, `RESERVOIR_DESIGN.md` (which holds
the mortegon dialect as distilled), `GRAPH_WORKBENCH_DESIGN.md`,
`NOTEBOOK_PANEL_DESIGN.md`, `CODE_ARTIFACTS_DESIGN.md`, `OPEN_WORK.md`.

---

## 0. The vision in one paragraph (my reading)

There is **one object model** and **two maps of it**. The object model is the
patricia trie of everything the reader touches -- web pages and their chunks,
vault notes, code, installed packages, model files, runs -- each a typed node
with a trie address. Every node has the **same panel**: an Obsidian-native
markdown cell, extended with Python-referencing syntax and `[query](results)`
retrieval, optionally paired with a live rendering (a browser at chunk, chunk
group, page or full-browser scope; a VS Code editor; a terminal; a model). The
**world map** is 3D: UMAP over the web and corpus, scaled once so nothing
collides. The **ego** is the reader's own craft: a computation graph of the
artifacts they have collected and written, with its own projection ("knowledge
keys"), flown like a Kerbal craft in first and third person, and edited on a
**2D plane** where panels stick, magnetise and compile. Compilation is the one
source of hard links: whenever one cell references another, through code,
markdown, a terminal call or a shared chunk object, a solid undirected
function-object link exists, and signal flow along it is shown as light. Every
"thing" is governed by a short code artifact (~25 lines listing all its
capabilities) whose markdown control panel is its user interface, so the code
and its instance are two linked nodes, not one blurred one.

---

## 1. The components

### 1.1 The trie: the one spine
- Universal link structure `domain/url-tail/xpath/markdown/content` (PG 24-28);
  local vault and code join it (PG 100-103). Re-navigation must not respawn
  nodes: "the patricia trie on the DB is the central spine for chunk handling,
  scanning, and web nav" (PG 4283).
- For the 3D view, the **patricia TREE**: content nodes only, single-path runs
  collapsed to one link, "guaranteed to be tree structured" (PG 1124-1134, 2147).
- The diff is one central object that both 2D and 3D forms read (PG 2092-2109).

### 1.2 The world map (3D)
- UMAP is "the central authority over the 3D graph coordinate layout" (PG 5377).
- Collisions are solved by **scaling the map, never by pushing**: one strict
  scale at which the closest pair just touches (PG 5017, 5070, "No nudging
  nodes" 5086). Motion is "a singular post-process that ensures
  stability/convergence on constraints within a limited time bound" (PG 5383).
- Unmapped live-scan diffs keep forces until mapped (PG 5017); saved diffs fold
  into their url node (PG 1519-1535); grey translucent = streaming (PG 1539).
- Url nodes 2-3x chunk size (PG 3283, 4468, 4554); one size within chunk view
  (PG 2684); no long links (PG 5340); no repulsion sphere (PG 2664).
- Rendering: glowing glass orbs as default, diffuse glow, black background,
  hovered images occlude other lights, ray-proximity reveal bounded to a
  cylinder (PG 2815, 3363-3389, 3043).
- Idle drift: "rotates both cartesian and color coordinates slowly but
  noticeably whenever there is no user activity" (PG 2706), tuned by
  PG 3063-3074.
- Re-fit without snapping: scale-aware ICP from the last registered camera pose
  (PG 3219-3222).

### 1.3 The ego: the craft, the cockpit and the user agent
- KSP: first-person "cockpit" and third-person views of a craft, and the craft
  is the 3D computation graph (PG 4487). Throttle, pause, flight plans for
  searches and anchored nodes; WASD plus Shift/Ctrl for throttle (PG 4487);
  switch between global map view and ego traversal (PG 4515: "This creates the
  'user agent'").
- Non-holonomic: moves along its heading, does not slide (item 116, PG 5017).
  Stateful motion (PG 4525); a change of hover target diffs the same trajectory
  (PG 4523); motion only when asked (PG 4552). Zoom and motion are independent
  (PG 4521). Q/R roll around the camera normal; arrows pan in the cockpit's
  frame: full 3 DOF from the keyboard (PG 4527-4529). Keys pressed are shown
  glowing beside the throttle (PG 4521). Text fields always keep their keys
  (PG 5017).
- No sliders and no Z/X/M; controls are symbol- and panel-pure, as in mortegon
  (PG 4531-4539).
- The ego is **one unit**: its own graph, separate from the UMAPped world, all
  connected in 3D: "this being where our 'cockpit' view really comes in"
  (PG 4791). Variables like `ego` are nodes inside the panel, fused, not
  duplicated (PG 4689).
- **Binding:** inputs and outputs of most of the computation graph forego
  world UMAP for "knowledge keys" of collected artifacts at the ego-UMAP level
  (PG 4815). 3D is "a unique umap to its non holonomic origin" with compact
  scaling "that enables zoom to pass into the microscope of the ego"; 2D is
  "the precise graph editor" (PG 4909).
- A web chunk joins the ego by a tag button on its billboard (PG 4815).
  Retrieval gets an ego-or-web field (PG 4815). The ego houses the reader's own
  generated artifacts (PG 4815).

### 1.4 The 2D plane: the computation graph editor
- The plane sits over the 3D view; 2D and 3D are shared and differ only in
  where they live (PG 4546). Panels are draggable and contained on the plane
  (PG 4703), and movable across panes (3D world, browser) (PG 5160).
- **Computation graphs are not contained by their panels**: they live on the
  plane and convert back to panel form (PG 5364). One gesture flips between
  the panel form and the undirected graph form (PG 5227).
- Panel and node are one layout parameterised by folding: collapsed to its root
  field, a panel is a node (PG 5017, item 110). Containment gesture groups
  linked fields (item 111). Recursive black boxes all the way down, from a
  few-line artifact to library base definitions, unnestable in both forms
  (PG 4815, 5017). Rank-1 expansion on a clicked ancestor (PG 4543).
- Tests are run on the plane, with the editor's tools: create and delete
  (PG 4774).

### 1.5 Cells: one notebook, many types
- The notebook vision: Obsidian panels become full Jupyter notebooks (PG 90-92);
  every panel is a notebook cell, and the computation graph is the fully
  rendered notebook, "the highest-level primal aggregate" (PG 4815).
- Cell types on record: **markdown** (extended), **code** ("the full set of
  vscode capabilities", PG 5162), **browser** (chunk, chunk group, page, full
  browser, PG 4815 and 5276), **chat model** (Mistral/Hermes 2 DPO, per token,
  prompts and responses as separate pickable cells, PG 5186), **terminal**
  (PowerShell, now magnetisable both ways, PG 5395), **kernel** (switchable with
  terminal, PG 105, 184), and **quantized-model nodes** (JEV for typed choices,
  deepseek-coder, Triplex for knowledge graphs; GGUF installed from the web as a
  typed panel, PG 3790-3798, 4152-4211).
- New cells come from a **retrieval bar over typed nodes**, not three buttons
  (PG 5162). Cell tools: new, delete, later, sooner, similar (PG 4907); similar
  subsumes soft links (PG 5164). Minimise and exit on every panel (PG 5162,
  5290). Ctrl+/Ctrl- resizes the notebook (PG 5166).

### 1.6 The one markdown panel
- Obsidian's own markdown panel, extended, left-snap like any note (PG 4703-4705).
- **The exact same code** for the browser's markdown half, node and code
  markdown, notebook markdown cells, the slate and the clipboard: "Not three
  different markdowns" (PG 5160); "I should only see one unified markdown
  panel" (PG 5364).
- The "mysterious third middle" between markdown and Python cells, kept as a
  markdown cell in Jupyter terms (PG 4743). Treated like a Python module, so
  triple-repeated `results` is a syntax error (PG 4725).
- Syntax: variables highlighted as links (Obsidian purple), with values left
  plain (PG 4689, 4712); plain prose must not be highlighted (PG 5284).
  Booleans hover to true and click to apply, with no "go" (PG 5284); numbers
  extend into an in-place horizontal slider over their detected range
  (PG 5002); key:value pairs with visual links in place of triples (PG 5000).
- Retrieval: `[query](scrollable results in place)`; plain triple retrieval
  with a properly engineered PageRank, no level heuristics (PG 5225); additive
  terms normalised to 0-1 (PG 4816).
- The clipboard is a markdown panel that aggregates on right-clicks. A
  right-clicked chunk sticks to the mouse until the next right-click, then
  lands in a cell or in its own panel on the plane (PG 5188).

### 1.7 Browsers, pages, chunks: one scope ladder
- Chunk renderers are "exceptional instances of full page views": a browser
  cell with a markdown counterpart, linked through the computation graph via a
  few abstract nodes (PG 5276). Chunk rung = a live browser framed to the
  chunk, fully interactive with the shadow DOM (PG 5227).
- Many browsers, each with tabs and its own session; the 3D graph follows the
  one in use (PG 4903); one browser's navigation must not leak into another
  (PG 5302).
- **Browser controls are code artifacts (VS Code panels)** referenced as
  controls in extended markdown (PG 5395); the browser panel's "cockpit" is its
  tools (PG 4815). The chunk object model in code is shared by the browser
  rendering and its markdown chunk, both linked and governing (PG 5395).
- Overlay: hover highlight in milliseconds; double-right-click pins (PG 1396);
  a right-click on an overlay box emerges as the 2D panel (PG 5160); toggle
  boxes on and off (PG 2729); uBlock (PG 3260); DDG for natural-text urls
  (PG 3262).
- Nothing written into pages; mutation observers only (PG 2116-2119).

### 1.8 Links: magnetism vs compilation (PG 5395, the newest rule)
- **Magnetism** is a TEMPORARY link for compilation serialisation, read
  top-to-bottom and left-to-right. Snapping on naked edges, no extra visuals
  (PG 5186). A chat cell's context is exactly the cells magnetised around its
  four edges, truncated on recursive links (PG 5186).
- **Hard links** exist whenever one cell references another "in any possible
  way": terminal calls, markdown references to objects in live code, browser
  and markdown cells attached to one chunk object in code (PG 5395).
  Magnetising never creates one (PG 5255).
- Solid computational links toggle solid or translucent with a right-click
  (PG 5227).
- "This doesn't affect panel/computation graph representations" (PG 5395):
  magnetism changes order, not drawing.

### 1.9 The governing-code architecture (PG 5395)
- Every "thing" has a governing code artifact in a standard high-level shape:
  **about 25 lines that list every capability of the object**. A markdown
  control panel on each instance links to those capabilities, and markdown
  nodes link undirectedly to interactive browser forms.
- Class vs instance are independent nodes inherently linked: forward-inverse,
  function-object memory lookups (PG 4905).

### 1.10 Retrieval and navigation fields
- `search` is the first computation-graph artifact: the minimal Python function
  (DB, DuckDuckGo, or both, as boolean nodes); the camera flies to hovered
  results (PG 4543).
- **The halo** (2D, ego only): polar layout, radius = similarity to the focus,
  angle = similarity among the results. Mouse velocity slides the surface,
  reversibly, with a visible shortest-path trace back to the origin; a
  navigated node becomes the new key; type-aware similarity (PageRank over
  datatypes and inheritance) (PG 4816, 4909, 5186).
- World search: "showing {k}/{n}"; a horizontal slider that brightens results;
  tiered url-then-chunk re-ranking; an exhaustive "more results" loop
  (PG 2716-2729, 3396-3440, 2932).

### 1.11 Code as graphs
- A code property graph (AST + CFG + PDG); property-graph edges; unified diff
  upsert from graph mutations (PG 3642-3657).
- An Occam's-razor compact KG: `a = b` is one triple, imports are triples
  (PG 4175); libcst (PG 4909, installed). Pydantic aggregate types generated
  from trie-path patterns across pages (PG 4168-4172).
- Only comments and docstrings are vectorised (PG 753).
- Through-stack agents: recursive graph-RAG tool calls, promises at the local
  MCP surface, frozen skeletons with dynamic ephemerals (PG 3808-3861).
  Designed, not built: "build up to these through-stack ideas incrementally"
  (PG 4150).

### 1.12 Visible computation
- Signal-flow glow animations, iterative and recursive, cell to readout to
  downstream cells (PG 4555, 5017). Active triples are "clearly visible
  lights" in 2D and 3D (PG 4909). Instant feedback when a black box is
  unnested (PG 4909).

### 1.13 The SLM and context
- One spine of single-hop tools, a system prompt per hop, chained prompts and
  synthesised leaves (PG 122-153).
- Rewind from the selected cell (PG 210-232); in the browser, right-clicked
  chunks are never re-sent (PG 694-710). Now also: magnetised context
  (PG 5186). See D-C below.

---

## 2. Inspirations, and what each contributes (my reading)

| inspiration | what it lends the design |
|---|---|
| Kerbal Space Program | The craft (the ego graph) with cockpit and chase views, throttle and staging, flight plans, non-holonomic motion and a map view vs a flight view. The cockpit is a node you can stick on the plane. |
| AI-driven programming languages | The markdown-Python middle: prose that is a module, `{ref}` variables, typed fields a model can fill (JEV), and code generated as graph mutations instead of whole files. |
| Interactive code graphs compiled over the graph | One compilation of the whole computation graph over all cell types; links come from references; signal flow is visible. |
| Jupyter | Cells and kernels, but extended over component artifacts, not artifact-centric code cells. |
| mortegon (the mothership) | The dialect: slates, `{ref}`, symbol-pure controls, the recursive reservoir, dual panel and graph views, rank-dominance collapse. |
| VS Code | Code cells with full editor capability; browser controls as code panels. |

---

## 3. Superseded, lucidly (no ruling needed)

| older | replaced by |
|---|---|
| A separate shadow-DOM chunk panel | Billboard in 3D plus the markdown side (PG 1026), then a framed live browser (PG 5276) |
| A hidden second view in the browser | Side-by-side sub-panel (PG 1166) |
| Spherical/quaternion UMAP (PG 409) | Dropped (PG 810), though see D-12 |
| Force-directed chunk view | UMAP only (PG 2653), then the scaled map (PG 5017) |
| The repulsion sphere and ring | Removed (PG 2664-2682) |
| Voronoi | Removed (PG 4342) |
| Level heuristics in `[]()` | Plain triple retrieval with PageRank (PG 5225) |
| Three new-cell buttons | A typed retrieval bar (PG 5162) |
| Sliders, Z/X/M, the agent strip | Symbol-pure cockpit (PG 4531-4539) |
| Several markdown panels | One unified panel (PG 5160, 5364) |
| Adaptive zoom coupled to motion | Independent (PG 4521) |

---

## 4. Old design vs current intuition: where a ruling is needed

These are the tensions I found. Each one names both sides.

- **T-1 The scaled map was turned OFF, and now it is the authority.**
  PG 5213 (11-02): "nodes seem out of view with umap-only ... we'll revert to
  our original older layout with more features". PG 5377-5383 (today): UMAP is
  the authority, with one bounded post-process. The strict scale reached 34-73
  on a streaming load and 3,475 on 16 nodes, because one near pair sets it for
  everyone. **Ruling:** keep the strict closest-pair scale, and accept that
  some nodes go out of view and the camera must fit? Or allow a bounded
  post-process that parts only the few closest pairs, so the scale follows the
  bulk of the map?
- **T-2 Two context rules for the chat cell.** Rewind from the selected cell
  (PG 210) and never-resend in the browser (PG 694) are older; magnetised cells
  around the chat cell are "the only context engineering needed" (PG 5186).
  Does magnetism replace rewind, or does rewind still apply inside a notebook?
- **T-3 Where the 2D editor lives.** Answered as a plane in the 3D view
  (RESERVOIR §9, item 50), but GRAPH_WORKBENCH §6 still asks whether it goes
  beside the 3D view (as mortegon did) and panels move across panes (PG 5160).
  Confirm: the plane in 3D is the only host, and panes are where panels may be
  dragged?
- **T-4 `{ref}` vs `[name](url)` in slates** (RESERVOIR §9 q2). The unified
  panel suggests one syntax everywhere. Which one?
- **T-5 A chunk note: one slate or card + markdown** (RESERVOIR §9 q3). PG 5276
  answers part of it (a framed browser plus a markdown counterpart, linked). Is
  that final?
- **T-6 Knowledge keys** (RESERVOIR §9 q7). My reading: the trie address plus
  a place in the ego's projection. Or did you mean a named index or an
  ontology?
- **T-7 The halo's sliding rule** (q8): pointer acceleration vs exact
  reversibility when speeds differ. Which wins?
- **T-8 The halo's gesture** (q9): click opens the halo, so open/close moves to
  double-click?
- **T-9 The scope-ladder gesture** (q6): wheel over the header for chunk ->
  page -> browser, or another gesture?
- **T-10 The 25-line governing artifact** (PG 5395, new). Is it a class whose
  public methods are the capabilities (the markdown control panel lists those
  methods as fields), or a declarative capability manifest the code
  implements?
- **T-11 What magnetism serialises.** Top-to-bottom then left-to-right, as one
  order over the whole magnetised group (row-major)? And is a terminal's
  output an input to the cell below it?
- **T-12 Idle drift vs stability.** Drift is your own feature (PG 2706), and
  today you reported the lag. Is drift camera-only (the map never moves), and
  may it be off by default?
- **T-13 Notebook outputs in retrieval by default?** (NOTEBOOK §8 q2.)
- **T-14 The default kernel interpreter** (NOTEBOOK §8 q3): the Store Python
  3.13 that has `domvec` on its path, or a separate environment?
- **T-15 Aggregates across pages** (GW §6): a trie-path pattern or hand-picked
  paths?
- **T-16 Rank-dominance collapse for every node** (GW §6, UR §Q.5)?
- **T-17 Item 107's one global scale vs the per-url telescope** (RESERVOIR
  12.8, G-115). The telescope is what made the endless glide loop today.
  Remove the telescope?

---


---

## 4b. Rulings (2026-11-08, PLUGIN_GOAL 145)

Ruled by: *"an interactive computational knowledge graph that extends jupyter
kernels to harness evolution using quantized language model kernels"*. The
sentence has three parts, and each ruling cites the one it rests on:
**[KG]** a computational knowledge graph, legible and stable; **[JK]** it
extends Jupyter kernels (cells, execution order, a namespace); **[QLM]**
quantized model kernels are cells that evolve the graph.

| | ruling | rests on |
|---|---|---|
| T-1 | UMAP places every node. ONE post-process follows each fit or update: a fixed iteration budget that resolves only overlapping pairs by the smallest displacement, anchored to the UMAP place. It converges and then everything is still. No global scale (it put the map out of view), no per-frame motion. | [KG] a graph you can read; PG 5377-5383 |
| T-2 | A chat (model) cell's context is the magnetised group, serialised in order: that is its execution order. With nothing magnetised, it falls back to Jupyter's rewind from the selected cell. Browser never-resend stays as the dedup rule inside either. | [JK] cells and order; [QLM] model as a kernel |
| T-3 | One host: the plane over the 3D view. Other panes (browser, 3D world) are places a panel can be dragged, not second editors. | [KG] one graph |
| T-4 | Both, by meaning. `{ref}` is a computational reference that compiles into a hard link (the kernel namespace). `[query](results)` is retrieval. Plain `[text](url)` stays a plain link. All three live in the one panel. | [JK] namespace; [KG] links from compilation |
| T-5 | Final: a chunk is a browser cell framed to the chunk, plus its markdown cell, both attached to one chunk object in code. | [KG] one object, two views |
| T-6 | Knowledge keys are the kernel namespace: each artifact's trie address (its key), its type, and its place in the ego's own UMAP. `{ref}` resolves through them. | [JK] namespace; [KG] |
| T-7 | Reversibility wins: the same path back always returns to the same node. Acceleration only scales distance and never breaks the return trace. | [KG] navigation must be retraceable |
| T-8 | Yes: a click opens the halo, a double-click opens or closes the panel. | [KG] retrieval is the primary act |
| T-9 | Wheel over a panel's header steps the scope chunk -> group -> page -> browser. | [KG] one object at many scopes |
| T-10 | A class. Its public methods ARE the capability list (about 25 lines); the markdown control panel is generated from those signatures as typed fields; an instance is a separate node linked to the class. | [JK] code is the kernel; [QLM] typed I/O a model can call |
| T-11 | Row-major: top to bottom, then left to right, across the whole magnetised group. A terminal's or kernel's output is an input to the next cell in that order. | [JK] execution order |
| T-12 | Idle drift moves the camera only, never the map, and is off by default (a toggle). | [KG] stability |
| T-13 | Yes, notebook outputs are retrievable, in the ego scope only by default; the web scope never sees them unless asked. | [QLM] outputs are what evolves |
| T-14 | Each workspace gets its own environment, created with it (item 144), so a new project inherits nothing. | [JK]; PG 144 |
| T-15 | A trie-path pattern. Its matches are the instances, its sub-paths the fields, and it generates the pydantic type. | [KG] types from structure |
| T-16 | Yes: rank-dominance collapse applies to every node in 2D and 3D. | [KG] legibility at scale |
| T-17 | Remove the per-url telescope. It is the second layout rule that fought the first (the endless glide loop). T-1's post-process is the only one. | [KG]; PG 5377 |

## 5. Engineering decisions still open (from this week)

- **D-A G-145 streaming-layer rework** (O(delta) node updates instead of a
  whole-graph rebuild per delta). Recommended yes.
- **D-B G-4: is 94% enough?**
- **D-C D-2/T-1, the chunk trie:** re-key to five levels? And may over-long
  single lines be split (R-C5)?
- **D-D D-12 spherical layout:** PG 810 dropped it, PG 818 asked to show it if
  it works. Closed, or measure once?
- **D-E Disk cleanup**, about 1.5-2.5 GB of deletions: go ahead?
- **D-F Relaunch Obsidian** (it closed during my last check), or will you?
- **D-G The motion post-process** (T-1 above) is the one blocking today's fix.

---

## 6. What this reading suggests to build first (a proposal, not a ruling)

1. Finish the layout rule (T-1, T-17), the base everything else is drawn on.
2. The unified markdown panel as one class used everywhere (1.6). Most panel
   bugs on record are panels that are not this one.
3. The cell registry: markdown, code, browser, terminal, chat and model as
   types behind one panel, with magnetism order (1.8) and reference-derived
   hard links (1.8, 1.9).
4. The governing-artifact pattern on the browser first (1.9): its ~25-line
   capability list, the markdown control panel and the chunk object shared by
   both views.
5. The ego as one unit with knowledge keys (1.3), then the cockpit views.
