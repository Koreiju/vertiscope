# The 3D/2D computation-graph reservoir — design

*Design before code, for PLUGIN_GOAL 2026-10-29 items 1–29 ("we need to focus on the full
scope of the design of our 3D/2D computation graph reservoir. The mortegon docs are
substantial on all these factors, but we can now meld with our jupyter kernel design at
the mid-grain as well and our extra details on keyboard activations and interactive
extended-jupyter interfaces"). Sources, in authority order: your words in
`PLUGIN_GOAL.md`; the mothership's verbatim (`web_fiber_haptics/docs/USER_REQUIREMENTS_VERBATIM.md`
§A–§V, cited **UR §x**), its design (`DOMAIN_MODEL.md`, **DM §x**) and its newest card spec
(`BLACK_SLATE_GOAL.md`, **BS §x**); then this repo's `NOTEBOOK_PANEL_DESIGN.md` (**NB §x**)
and `GRAPH_WORKBENCH_DESIGN.md` (**GW §x**). Read in full for this: the verbatim A–V, DM §4,
§6.6, §7, BS §0–§15. Where a mothership rule and a later word of yours differ, yours wins;
each such case is named. Section 9 holds what is yours to decide.*

---

## 1. The reservoir, in one paragraph

The **3D projector is the world distribution** (UR M.1): every chunk the trie holds — web
pages, vault notes, code, packages — placed by the one global UMAP fit (G-2), plus the
**readouts** the computation graph produces, placed at its perimeter (DM §6.6.1, UR P.3–P.7).
The **2D editor is the reservoir's readout layer**: a graph of nodes in the mothership's
dialect — black slates whose structure is text (tabs and newlines), whose only markup is the
`{ref}` memory reference, and which flip losslessly between a panel (an aggregate) and a
computation graph (singular-field nodes, undirected lines) (UR N.2, O.1, R.1, T, V.5). A
**cell** of the extended-Jupyter notebook is the mid-grain of this graph: a function node whose
`{ref}` inputs are drawn from the trie, whose kernel run is the forward call, and whose stored
output is the readout (NB §2–§4; UR E.6, M.9). Running the graph over a sample stream is the
**rollout** (UR E.7, O.9–O.11): outputs settle asynchronously and stream to the projector as
deltas. The **user agent** is how a person moves through both: a stateful craft in 3D (ego
view) or the whole map (global view), steered from the keyboard, its controls themselves
nodes of the dialect — the cockpit is the "ego" 2D node (items 4, 10, 14, 22).

## 2. The three registers on this plugin's surfaces

| register (DM §1.5) | what it is here | where it lives today |
|---|---|---|
| **Real** — perceptions as geometry | the patricia trie `url : xpath : markdown : content` and the chunk projector over it; readouts at the perimeter | `domvec/trie.py`, the store, `projector.py`, `graph.ts` |
| **Imaginary** — the editable computation | slates and their graph form; cells and their kernels | native notes (D-3), kernel cells (P-N1, P-M4), not yet the dialect |
| **Symbolic** — verification | the live checks (`checks/live.mjs`) and the MCP tools: every gesture has a mirror that reads the app back | the harness (UR J.1 is this repo's standing rule already) |

## 3. The dialect, mounted on Obsidian

### 3.1 A slate is a note

The mothership rebuilt its card as "a single editable text surface … one pure-print text tree"
(BS §0). Obsidian already *is* that surface — the native editor, which D-3 made the markdown half
of every chunk panel. So **a slate is a note** in the slate class (frontmatter `domvec: slate`,
or a chunk note), and the plugin's job is the grammar and the gestures, not a new widget:

- **Visual (UR S.4):** the note's view takes the slate class — black fill, 1px silver border,
  serif white text, no header, no buttons. The cell strip of P-M4 is chrome under this rule
  and becomes a gesture in the slate class (§3.3).
- **Grammar (BS §3, UR N.7, N.10, O.20):** structure is tabs and newlines only; names may hold
  spaces; `{ref}` is the only markup; `name {}` is a new field's on-ramp; key-value vs
  multiline is inferred by consistent indentation. API objects render typed
  (`driver : WebDriver = {driver}`, read-only); user nodes render type-stripped (UR N.5, M.3).
- **Under the hood (BS §4):** the note's text is parsed into a record; `{ref}` tokens become
  edges; the store (the same Kuzu store as the trie) holds the record and the edges. A slate
  note is indexed like any vault note (G-7), so it is ALSO a page of the trie with addresses —
  which is what lets the 3D side place it and the halo retrieve it.
- **Three brace states (UR O.1a):** braced-hidden `{name}`; revealed-internal (the target's rank-1
  lines indented inline, braces dropped); resolved-external (a solid line to a node already on
  screen).

### 3.2 What `{ref}` points at — the trie address space

`{ref}` names a node. Here every node already has an address: a chunk (`https://…` + xpath),
a vault note (`vault://`), a code object (`code://`), a package symbol (`code://pypi/`). So
`{ref}` resolves through the store the way `resolve_address` does, by name first (a slate's
title, a chunk's title, a code symbol's qualified name) and by retrieval when the name is new —
the mothership's "unknown name auto-creates the node" (BS §5) becomes "unknown name opens the
halo". The existing `[]()` retrieval gesture (R-1..R-4) is this halo already (UR D.3: "as the
user types … retrieval radiates candidates"); its infill writes a link. In the slate class the
infill writes `{name}` instead — see question 2.

### 3.3 Gestures (UR §7.3.4 table, BS §5), in the native editor

| gesture | on | effect | mounts on |
|---|---|---|---|
| single left-click | a token | edit in place, borderless (UR M.8) | the native editor already does this |
| right-click | a `{ref}` | internalize ⇄ fold its rank-1 lines, fold state kept (UR M.6, N.8) | a CM6 decoration that inserts the target's rank-1 text read-only below the token, like D-3's hidden half |
| right-click | the title line | collapse the slate to its title: the circular node (UR S.5, V.5) | the D-3 half switch, generalised |
| double left-click | the body | panel ⇄ graph form (UR M.7) | opens / focuses the note in the 2D graph view (§6) |
| left-drag | token → node | wire a link; the target inherits I/O types (UR N.4) | graph view |
| double right-click | a `{ref}` | delete the link (UR N.13) | the editor removes the token; the edge goes with it |
| type `{` | anywhere | completion over node names; unknown → halo | the `[]()` suggest, re-keyed |
| Tab / Shift-Tab / Enter / `- ` / `1. ` | a line | re-parent / sibling / positional child — the graph restructures (UR R.5, N.12) | the native editor's own keys, re-parsed on change |

The mothership's `+→` / `+↓` plus-signs became keystrokes there (BS §3); the P-M4 `+ code`
strip is the same kind of chrome and goes the same way (§9, question 4).

## 4. The mid-grain: cells as function nodes

NB §2 already decided "P-N is P-M grown": a notebook is a native note with cells. The dialect
gives the cell its place:

- **The granularity ladder.** Fine: a field or `{ref}` token. **Mid: a cell** — one fenced
  code block. Coarse: a slate (panel). Whole: the graph (reservoir).
- **A cell is a functional-object node** (UR F.5, M.5, M.9). Its `{ref}` tokens are its inputs,
  declared on its FENCE LINE (```` ```python {Radix tree} {query} ````) and not in the code, where
  braces are Python's own (decided 2026-10-29 while building G-279; yours to overturn):
  before the kernel runs it, each `{ref}` in the cell is resolved and bound into the kernel's
  namespace by name (a chunk as its markdown and record, a slate as its record, a code symbol
  as the imported object). The run is the forward call; the stored `nb-output` block is its
  readout (the P-M4 / P-N3 machinery, built and confirmed).
- **The forward map is recorded** (UR R.6, DM §7.7): every run writes `FORWARD_MAPPED_TO` edges
  from its bound inputs to its output — the inverse lookup's ground truth, and the reservoir's
  memory of which inputs produced which readout.
- **The three base objects are kernel objects** (UR F.1–F.3, typed, read-only): `WebBrowser`
  (the sidecar's capture through the browser cell), `Database` (`search` over the store,
  `cypher` on Kuzu), `Agent` (the local model, L-1 — a download only with your go-ahead). They
  materialise in the namespace and as typed slates (`self:WebBrowser …`, UR M.3).
- **Iteration is the signal stream** (UR N.9, O.11, DM §4.6.1): a cell whose `{ref}` points at
  an iterable (`{chunk samples}`) runs once per sample on play; its output block shows ONE
  current readout; every sample's output goes to 3D. Only an external `{ref}` iterates.
- **The terminal pane stays a stream** (NB §4a): a shell has no address; a cell does.

## 5. The 3D side of the reservoir

- **One representation, two places** (item 37, 2026-10-30: "2D/3D representations are shared,
  just differing on where they live in either interface"; UR R.1, O.19). A computation-graph
  node is ONE record -- its slate text, its `{ref}` edges, its fold state, its current readout.
  The 2D panel and the 3D node are two PLACEMENTS of that record, not two models kept in sync:
  editing either writes the record, and the other redraws from it. Selection and view decide
  which placement is shown (item 42): stuck, it is a 2D panel; in flight, a 3D node.
- **UMAP over the ego reservoir -- CORRECTED twice, 2026-11-01.** As first written here (item
  43, 2026-10-30) every computation-graph node was placed by the GLOBAL fit among the web and
  vault chunks: "the reservoir is therefore not a separate picture". The reader's correction
  (PLUGIN_GOAL 67): *"the full ego computation graph as one unit, its own graph separate from the
  red of the UMAPped components, all interconnected in 3D"* -- so the reservoir IS a separate
  picture: the craft (5a). And the binding rule that followed (item 76): *"forego all UMAPping on
  things in the world-map at input-output most parts of the computation graph/reservoir in place
  of "knowledge keys" of variously collected artifacts at the ego-umap level and which is
  integrated with UMAP on the local ego-linked code artifacts"* -- the ego has its OWN projection
  (10.4), and the world fit no longer places the reservoir's inputs and outputs. G-291 (ego
  artifacts indexed as vault pages and placed by the global fit) is superseded in its placement;
  its indexing stays (the artifacts are still retrievable).

- **Readouts at the perimeter** (UR P.3–P.7, R.4; DM §6.6.1, §7.8.3): a node with no succeeding
  `{ref}` is terminal; its settled rendering is indexed as a chunk and placed on the projector's
  outer shell, asynchronously, as a delta on the existing stream. Hidden-state nodes never
  project. Passive readouts (no picture) rotate in hue (UR P.4).
- **The bisector node** (UR P.10; DM §6.6.4): one node per open graph, on the line between the
  centroid of its inputs' places and the centroid of its readouts'. Clicking it opens / closes
  the graph in 2D. Its links — inputs to it, it to readouts, url roots to their chunks — are a
  network independent of the fit (the G-241 overlay path already draws such links).
- **Rank-dominance collapse** (UR Q.3–Q.5): right-click a dominator folds what it dominates
  and isolates it. The url fold (G-84 / G-110) is its first case; the bisector folds its input
  and readout sets.
- **The halo transports** (UR O.18, V.4): retrieved nodes ride constant-similarity rays from the
  stuck slate as apex, sliding along them as the camera moves. The search lights (G-209) are
  this halo's lit half today; the transport is not built.

## 5a. The craft -- the ego computation graph as one unit (items 67-69, 75)

*Built 2026-11-01: `obsidian-plugin/src/craft.ts`; live check G-299.*

The reader's words, the two that define it: *"something like kerbal space program, where we can
see from both first person view within a "cockpit" as well as a 3rd person view, but for a
"craft" that is where our 3D computation graphs from our legacy mothership mortegon
specs/docs/code comes in"* (2026-10-29) and *"the full ego computation graph as one unit, its
own graph separate from the red of the UMAPped components, all interconnected in 3D ... this
being where our "cockpit" view really comes in"* (2026-11-01).

**What it holds.** Every computation-graph artifact in the vault, one record each (section 5's
"one representation, two places"):

| node | is | fused with |
|---|---|---|
| `ego` | the cockpit note, the craft's root | the cockpit's title node (item 54) -- one `ego` |
| note | a slate, or a notebook whose python cell has RUN (G-291's rule), or a note the plane's tools made or the plane shows | a slate IS its one tree |
| tree | a markdown tree in a notebook (the extended markdown cell, G-297) | -- |
| cell | a python cell (one kernel per note) | -- |

The vault is this repository, so a README's fenced example is not a kernel cell: first built
without the rule, the craft took in 106 notes, 498 "cells", most of them `node_modules`
READMEs. With it, 34 notes -- 32 of them probe notes earlier checks had failed to delete (an
editor's pending save rewrote them after the delete; the plane's delete tool now saves, closes,
then trashes).

**How it is linked -- "all interconnected".** `root` (every note hangs from `ego`, item 10's
"collapsed within the "ego" 2D node which corresponds to the cockpit"), `contains` (a note's
trees and cells), `order` (the note's one kernel runs its trees and cells in document order --
the signal flow of item 35), `ref` (a `{name}` in a tree or on a fence line naming another
artifact). Measured: every node reachable from `ego` (7 of 7; planted `plantNoLinks`, 1 of 7).

**Its I/O are links into the world, not nodes dissolved into it** (item 69; mortegon P.8: "a
node-edge network rendering independent of the UMAP embedding project, simply links between
nodes in the projector, to the computation graph itself"). A run's recorded input -- a chunk of
the world -- is a line to the cell's note in the craft. Measured: 1 I/O line for a cell reading
`{Radix tree}`.

**Where it is -- its own frame.** None of its nodes is a node of the fit's graph (0 of the
world's nodes are craft nodes): it is its own scene group. Its centre is where the agent last
FLEW in the ego view (the craft is the camera there); until it has flown, beside the world,
outside the fit's shell. A note's bearing from `ego` is, for now, its bearing in the world fit
-- superseded by the ego's own projection (10.4) when built.

**Third person and first person** (items 4, 68, 75). The map view (third person) frames the
world AND the craft side by side: the camera aims between them from across the line joining
them (looking along it, the craft sat on top of the world). Measured: craft at screen x 0.71,
world at -0.70. The ego view (first person) does not draw the craft -- the reader is in the
cockpit, and the panels on the 2D plane are the craft's inside (planted `plantAlwaysDrawn`:
drawn around the camera).

**Gestures on a craft node** (item 65): a click opens its panel on the plane (a cell or tree at
its line); a click on a node whose panel is open closes the panel back into the node; a node
whose panel is stuck on the plane is ringed.

*Not yet:* the ego's own UMAP and knowledge keys (10.4) placing the craft's nodes; the halo
(10.7) on craft nodes; zooming through the cockpit from third person into first.

## 5b. Panels on the plane -- every artifact, with the editor's tools (items 65-66)

*Built 2026-11-01: `obsidian-plugin/src/planepanels.ts`; live check G-298.*

*"The jupyter kernels/cells are supposed to also be the draggable 2D computation graph plane
type panels. You might see how graph/panel/kernel/nodes might integrate as one thing here."*
One record seen four ways: a NODE of the craft, its PANEL on the plane, its KERNEL when a cell
runs, its TREES as a Python module. A panel is Obsidian's own markdown view (item 56) in a leaf
outside the workspace tree, in a card on the plane; its header node is the note's name in the
link colour, in the inline title's place (the name drawn once, item 54); a slate's header is
its own title line.

**The editor's tools** (item 66: *"All tests should be on the 2D computation graph plane for
panel experiments, never their own view. This encourages the exercise of editor tools
accompanying the graph editor (i.e. create/delete etc)"*):

| tool | gesture |
|---|---|
| create | `+ notebook`, `+ slate` on the plane's strip: a note in `domvec/graph/`, opened on the plane |
| move | drag the header node; clamped to the plane |
| minimize / restore | right-click the header node (a slate: its own title collapse) |
| delete | double right-click the header node (mortegon N.13): saved, closed, the note to the vault's `.trash` |
| close into the node | click the craft node of an open panel |
| open from the node | click a craft node (or a bisector) |

Every live check of a panel now opens its probe through the desk (`__domvecPlane.leaf()`) and
deletes it through the delete tool (`__domvecPlane.trash`) -- 31 opens and 32 deletes converted.

Found on the way, both real: a cell's run took its note from the workspace's ACTIVE file (a
panel on the plane is never active, so the kernel ran and the output went nowhere); and a run
sent the note's text from the FILE, so a tree typed a moment before the run was not compiled
(NameError). Both now read the editor's own.

## 6. The user agent and the cockpit (items 1–29)

- **The craft is the camera, and it is stateful** (items 1, 17, 20–21; built: `useragent.ts`):
  velocity carried between hovers, the heading bent toward a new target, speed set by the
  throttle and independent of zoom, braking to a hard floor; the wheel zooms on its own.
  Motion keys act in the camera's own frame (item 23): W/S/A/D, arrows turning about the focus,
  Q/R rolling about the view normal. Shift/Ctrl throttle. Z, X, M deprecated (item 28).
- **Selective, and at the reader's zoom** (items 38–39, 46–48, 2026-10-30; built and confirmed
  live, G-285). A flight stops at the reader's OWN zoom distance (never nearer than the floor,
  nor nearer than the node fits the view) and ENDS there: the target is released and nothing
  moves the camera until the next hover or key. A drag on the canvas is a hand on the stick.
  A hovered browser panel (a fresh target per poll) is matched by id, so the camera goes where
  the hovered browser panel is. The wheel's floor keeps the zoomed node in view.
- **The cockpit is a node, not a HUD** (items 10, 24–25): the deprecated strip becomes ONE slate
  in the dialect — collapsed, a circle reading `ego`; internalized, its fields:

  ```
  ego
  	view	ego
  	throttle	25
  	keys	{keys}
  	plan	{flight plan}
  ```

  `view` and `throttle` are values the keys edit (Shift/Ctrl write `throttle`; editing the
  text writes it too — "symbol/panel pure", item 24); `keys` is an iterable whose current
  sample is the last key and its action (item 19 — the "lit" key is the visible signal, UR N.9);
  `plan` is the flight plan (below). Stuck into the 2D editor like any slate, it is always
  reachable in 2D, even collapsed (item 10).
- **Keys are graph inputs** (item 22): each key event is a sample on `{keys}`; any node may
  `{ref}` it — which is how the controls become "computation graph inputs to the sticked
  node/panel dialect editor".
- **First and third person** (item 4): ego view = the camera is the craft (cockpit); global view
  = the whole map with the craft as a node on it (the agent's position drawn, third person).
- **Zoom through the cockpit** (item 7): at the floor, a further wheel-in on the focused node
  opens its slate — 3D to 2D, the node's panel taking the screen; wheel-out returns.
- **Flight plans** (items 8–9): a node whose value is an ordered list of `{ref}` targets — a
  query's results, or anchored nodes. Play flies the craft through them at the throttle (the
  rollout's play/pause, UR E.7, applied to the craft); pause holds at the current target.

## 6b. `search` — the first computation-graph artifact (items 30–36)

The reader's words (2026-10-29): the search input is "a part of the controls"; `search` is "one
of the first computation graph artifacts". It is where the three forms meet, so it is built
first and each later artifact copies its shape.

**The slate** (panel form, in the cockpit — item 30):

```
search
	query	{}
	db	true
	duckduckgo	false
	k	8
	results	{results}
```

**The minimal Python** it stands for (item 32), bound in every kernel beside `Database`:

```python
search(query, db=True, duckduckgo=False, k=8)
```

`db` runs `Database.search` (the app's own retrieval); `duckduckgo` routes the query through the
BROWSER CELL (G-195's web search, captured and chunked like any page) — never a scraper of its
own; both merge by rank. The cell's readout is `results`, an iterable of `{ref}`s.

**Fields by type** (item 33): a boolean is a TOGGLE — a two-state node in graph form, a toggle
field when hovered in panel form; a continuous value (`k`) gets a slider in the dialect (one
slider, inside the slate — not the deprecated strip). A string (`query`) is the field itself.

**Two kinds of link, kept apart** (item 34; UR T.7): the `{query}` and `{results}` braces are the
dialect's markdown syntax (internalize/externalize, rank-1 folds); the call's own binding to
`Database` and the browser cell is a CODE link (resolved by the kernel, shown in the code view).
A gesture on one never acts on the other.

**Signal flow governs layout** (item 35; UR O.9–O.10, P, R.7): the order is `query` → toggles →
call → `results` → their nodes; the aggregate panels lay out in that order in 2D, and in 3D the
results are readouts at the perimeter, revealed as the rollout walks them.

**The camera** (item 31): a hovered result is flown to (selectively, §6); with none hovered,
the top-most ranked result in view of the results' scroll is.

**Gestures are local** (item 36): a click on an ancestor expands only its rank-1 links, in both
forms; nothing else unfolds.

## 7. Deprecated, and why

| what | by | replaced by |
|---|---|---|
| the agent's control strip, its slider and buttons | items 24–25 | the cockpit node (§6) |
| Z / X / M | item 28 | `throttle` / `view` fields |
| the retrieval sidebar idea, if it returns | UR S.3 | halos on the slate |
| structured card widgets | UR T.1, E.2 | one slate (D-3 began this) |
| arrowheads on links | UR O.16 | undirected lines |

## 8. Build order — procedural, each step checked live with a planted arm

0. **Defects first, jointly** (items 38–48, 2026-10-30): selective ego motion (G-285, done);
   the full chunk view in real time (G-286: positions-only ticks, per-picture patches, a
   rolling safety net); url nodes 5x (G-269).
1. **Slate grammar** (`domvec/slate.py`): print(record) → text, parse(text) → record + `{ref}`
   edges; round-trip identity on names with spaces, `name {}`, kv-vs-multiline, typed vs
   type-stripped (BS §11.3). Tests golden; planted: a colon-splitting parser fails them.
2. **Slate notes** in the native editor: the slate class (visual), `{ref}` resolution through
   the store, right-click internalize/fold with fold state kept, title-line collapse to the
   circle. Live check per gesture.
3. **Cells as nodes**: `{ref}` binding into the kernel; `FORWARD_MAPPED_TO` recorded per run;
   the three base objects in the namespace (Agent waits on the model download).
4. **The cockpit node** (§6) with **`search` in it** (§6b): replaces the deprecated strip; keys
   as `{keys}` samples; `search(...)` bound in the kernel.
5. **Graph form**: the 2D view (question 1) with circular nodes, undirected lines, node-count
   parity with the slate.
6. **Readout perimeter and bisector** in 3D; rank-dominance collapse generalised.
7. **Rollout** over `{chunk samples}`; flight plans on the same play/pause.
8. **Halo transport** along cone rays.

### 8b. Where the build stands (2026-10-30, end of day)

Every step below is built and seen working in the running plugin by a live check with a planted
arm (`obsidian-plugin/checks/live.mjs`, verdicts in `build_analytics/live_confirmations.md`).

| step | built | live check |
|---|---|---|
| 0 defects | ego motion selective (G-285); chunk view real time (G-286); garbage 0.72 MB a frame, was 99.6 (G-290); hover raycast only on change (G-293); relax frames p99 52 ms (G-170); url nodes 5x (G-269); only trusted input is the reader (G-289) | all Confirm |
| 1 grammar | `domvec/slate.py`, `parseSlate` / `rank1Of` (TS), `refs.rank1` (Py) | G-277, G-278 |
| 2 slate notes | slate class; `{ref}` internalize / fold with fold state kept; title collapse to the circle | G-278 |
| 3 cells as nodes | `{ref}` binding, runs recorded, `Database`, `search(query, db, duckduckgo, k)` | G-279, G-288 |
| 4 cockpit | the `ego` slate bound both ways to the agent and the search; toggles, slider, `{results}`, `{keys}` | G-280 |
| 5 graph form | double-click flips a slate to circles and undirected lines, node-count parity | G-281 |
| 6 perimeter / bisector | readouts on the shell along their UMAP bearing; one bisector per graph, click opens it in 2D, right-click folds what it dominates; the signal pulsing input -> bisector -> readout | G-282, G-292 |
| 7 rollout / plans | ▶▶ runs a cell once per sample of its first `{ref}`; flight plans through `{results}` or any `{ref}` | G-283, G-283-rollout |
| 8 halo transport | a stuck slate's literal field transports its retrieved nodes onto the camera's cone, sliding with the camera | G-284 |
| ego reservoir in UMAP | slate and run-cell notes indexed and placed by the global fit | G-291 |

Not built, named in the rows: deleting a halo result to bring in the next (O.14); the
three-metric similarity in the halo; left-drag wiring in graph form (UR N.4); the cockpit's
title collapse and `{keys}` as samples other nodes reference.

## 9. Yours to decide

*Item 37 narrows questions 1 and 5: the 2D and 3D forms are one record in two places, so the
answer to "where" is a placement, not a second model.*

**Answered 2026-11-01 (PLUGIN_GOAL items 50, 52):** question 1 -- *"A plane inside the 3D
view"*; question 5 -- the cockpit is the ego 2D node stuck in the 2D graph form (the reader's
2026-10-29 words), so on that plane. Questions 2-4 remain open.

1. **Where graph form lives.** An Obsidian view beside the 3D graph (as mortegon put it, GW §6),
   Obsidian's own Canvas (cards and edges native, but its file format owns the layout), or
   inside the 3D view as a plane.
2. **`{ref}` and links.** In a slate, should the halo's infill write `{name}` (the dialect) where
   it now writes `[name](url)`? And in ordinary notes — keep links, or adopt `{ref}` everywhere?
3. **What a chunk note becomes.** D-3 made it card + native markdown. Under the dialect the
   stuck chunk is ONE slate whose body is its deduplicated content tree (UR U.1) — the card
   folded under a `{ref}`. Replace, or keep both halves?
4. **The P-M4 cell strip.** Chrome under UR S.4. Keep it in ordinary notes and drop it in slate
   notes, or drop it everywhere for keystrokes?
5. **The cockpit's place.** Stuck in the 2D editor (as item 10 reads), or also pinned in a
   corner of the 3D view in its collapsed circle?

*Added 2026-11-01 with section 10:*

6. **The scope ladder's gesture** (10.2). A `scope` field stepped by wheel-in / wheel-out over
   the header (zoom-through, item 7) -- or another gesture you had in mind for chunk -> page ->
   live browser?
7. **"Knowledge keys"** (10.4). Read here as each artifact's trie address (its key) plus its
   place in the ego's own projection. Is that what you meant -- or a keyed index of another kind
   (named keys, the cockpit's `{keys}`, an ontology)?
8. **The sliding rule** (10.10). "Fast in a short distance is the same as slow in a long
   distance" is read as pointer acceleration (gain grows with speed), and "moving it back ...
   has the same effect" as reversibility. Those two pull against each other when the speeds
   differ -- which wins?
9. **The halo's toggle** (10.10). A click on a node / header opens the halo, so a craft node's
   click (today: open / close its panel) moves to a double-click. Agreed, or another gesture?
10. **libcst** (11.4, item 94). Concrete syntax trees keep comments and formatting the AST drops;
    it is a download (`pip install libcst`). Install it?
    **Answered 2026-11-01 (PLUGIN_GOAL 102): "approval to install granted"** -- installed.

## 10. The browser as a panel, the ego's own map, the halo that slides (items 71-86, 2026-11-01)

*Design before code for PLUGIN_GOAL items 71-86, the reader's message of 2026-11-01 (verbatim
there). Each subsection states the reader's words, what exists, the design, and what is my
reading rather than theirs. PRD rows G-300 to G-312.*

### 10.1 The browser cell as a panel on the plane (item 71)

*"our full web browser panel feature + all functionalities should be translated to its
draggable panel/computation graph analogue; includes "cockpit" for browser tools/actions on the
panel, as well as the actual web browser rendering the interactive HTML".*

What exists: the browser cell (`browser.ts`, a workspace view: address, back, forward, reload,
scan, live, save offline, offline, boxes, the chat strip, the "in graph" badge); the browser
hosted inside a notebook fence (`nbbrowser.ts`, a leaf outside the workspace tree -- the same
mechanism the plane's panels use); the reconstructed page (`panelview.ts`); chunk billboards.

Design: the browser is a panel on the plane like any other (5b), its view the existing
`BrowserView` in a plane leaf. Its tools become a **browser cockpit**: a slate whose fields ARE
the tools, bound both ways as the ego cockpit's are (G-280):

```
browser
	url	https://...
	back	{}
	forward	{}
	scan	false
	live	true
	offline	false
	boxes	false
	scope	page
```

A boolean is a toggle node (item 33); `back` / `forward` are actions (a click fires); `url` is
the field typed into. The browser's own toolbar stays for now (the reader can compare) and
goes when the slate covers every action (UR S.4, chrome).

### 10.2 One scope ladder: chunk -> page -> live browser (item 72)

*"the actual web browser rendering the interactive HTML, which was originally designed with the
intent of seamlessly flowing between chunk-level rendering/interactions and the full webpage and
*then* the actual browser itself, similar to the various gestures on various nodes to render the
panels at the selected scope of the computation graph nodes (i.e. adaptive/selective
abstractions)".*

Three scopes of one web artifact, each a rendering of the same trie address (`url : xpath`):

| scope | what draws | exists as |
|---|---|---|
| chunk | the chunk's markdown + its interactive wireframe; acts in place | billboard, chunk note (D-3) |
| page | the reconstructed page, every chunk of the url | the offline panel (`panelview.ts`) |
| live | the real browser at the url, scrolled to the xpath | the browser cell |

Design (my reading): the ladder is ONE panel whose `scope` field steps chunk -> page -> live and
back; the same gestures that change a computation-graph node's scope step it -- right-click on
the header (the base node) collapses toward the node (mortegon: right-click on the base node
collapses to self), and **zoom-through** (item 7: at the floor, wheel-in opens the node's panel)
steps outward: wheel-in over a chunk panel's header goes to page, again to live; wheel-out steps
back. Moving up keeps the address: the page opens scrolled to the chunk, the browser at the
chunk's xpath (the hovered-chunk highlight marks it). *Question 9.6.*

### 10.3 Every panel a notebook cell; the computation graph a rendered notebook (item 73)

*"this obviously makes each panel an extension of a jupyter notebook (as cells each) and so the
computation graph is the analogue to a fully rendered jupyter notebook as the highest-level
primal aggregate of panel-facing artifacts (code, web, markdown with retrieval and
code/computation graph links that render like queries as functional-object dialects, and verify
this rigorous statement in the mortegon docs)".*

**Verified against the mortegon docs (2026-11-01), part by part:**

| part of the statement | in mortegon? | where |
|---|---|---|
| a node and a panel are one artifact | **yes** | UR N.2 ("technically both computation and panel-based as a singular field primitive"); DM §7 line 374 ("the same record at different sizes") |
| the two forms commute | **yes** | UR R.1, O.1 (node-count parity) |
| code modules become computation-graph structure | **yes** | UR M.2 (modules -> recursive computation-graph nodes of singular values with memory references), M.3 (the panel is the base form of a Python API module) |
| links render like queries, functional-object dialect | **yes** | UR M.3 (curly-brace calls to external computation nodes; right-click compiles the next level of syntax tree), M.9 ("function calls ... have an automatic rendering property ... similar to memory reference lookup") |
| web artifacts as panels in the same graph | **yes** | UR N.2 (the duckduckgo url node referencing the `scan` function node), DM line 92 (urls aggregated over a panel), DM line 1624 (`{urls_panel}` into `WebBrowser.scan`) |
| **Jupyter / notebook** | **no** | the words "jupyter" and "notebook" occur nowhere in mortegon's docs |

So the structure is mortegon's; the NOTEBOOK framing is the reader's own, from 2026-10-29
(*"The full panel set of artifacts becomes, in fact, the various arranged cells and extensions
of our jupyter kernel cells with native obsidian markdown representations"*) and NB / P-N here.
The statement holds as a composition of the two: each panel is a cell (markdown, code, web --
extended), and the computation graph is the whole notebook rendered: the craft (5a) is its 3D
form, the plane its 2D form.

### 10.4 The ego's own projection: knowledge keys and ego-UMAP (items 74a, 76) -- BINDING

*"We will now make the binding rule to forego all UMAPping on things in the world-map at
input-output most parts of the computation graph/reservoir in place of "knowledge keys" of
variously collected artifacts at the ego-umap level and which is integrated with UMAP on the
local ego-linked code artifacts."*

The rule, as binding: the reservoir's inputs and outputs are NOT placed by the world fit.
Affected today: G-291 (ego artifacts placed by the global fit), G-282 (readouts moved to the
world's perimeter, the bisector between world centroids). Both are superseded in placement;
their links stay as I/O lines (5a).

**The ego set**: the craft's artifacts (5a) + web chunks tagged into the ego (10.5) + the
reader's own markdown / prompt panels (10.6) + the code artifacts linked to them (a cell's
imports resolved to `code://` symbols through the code property graph, `/cpg_edges`).

**The ego's projection**: its own fit over the ego set's embeddings (the same encoder, docs-only
for code per the 2026-11-01 ruling), separate from the world's; the craft's node places come
from it (replacing the world bearing used now). Small sets: UMAP needs ~15 points; below that
the places come from PCA of the same embeddings, and the fit is taken once the set passes 15.

**Knowledge keys -- my reading, not the reader's words** (*Question 9.7*): the term occurs
nowhere in either repository's docs. Read as: each collected artifact is placed and found by its
KEY -- its trie address (`url : xpath` for a web chunk, `vault://` path : line for a note's
tree or cell, `code://` module : qualname for code) -- and its position in the ego projection;
the key, not a world coordinate, is what links it to the world.

### 10.5 The tag: a web chunk joins the ego (item 74b)

*"including selected web chunk nodes with a simple tag button on the top of each of the
billboard panel renderings".* A `+ ego` tag on each billboard's top edge: pressed, the chunk
joins the ego set (stored in the store, keyed by cid -- survives a reload); it appears in the
craft as a `web` node linked to `ego`, with an I/O line to its world node; pressed again, it
leaves.

### 10.6 The reader's own panels live in the ego (items 74c, 77)

User-written prompts and markdown panels -- notes made on the plane, the notebook chat's prompts
-- are ego artifacts; they may link OUT to the world through markdown retrieval links (the
`[query](results)` overlay); a Jupyter kernel's cells likewise. Code brought in from the web (a
web code block opened as a cell, G-234) and code a local model writes in a notebook chat (L-2)
are ego artifacts: *"the ego houses user-generated artfiacts within the space of their
preferences and thoughts"*.

### 10.7 Retrieval gains a field: ego or web (item 78)

`search(query, db=True, duckduckgo=False, k=8, where="web")` -- `where` is `web` (the world's
store, today's behaviour) or `ego` (the ego set alone). In the cockpit's `search` slate, a field
`where` toggled between the two; in the sidecar, `/search?where=ego` restricts candidates to the
ego set's urls and cids.

### 10.8 I/O linked to the ego or the web, by a toggle (item 79)

Mortegon's signal flow and forward-inverse lookup (UR R.6, DM §7.7 -- built here as G-279's
recorded runs and the inverse map) decide WHAT a run read and wrote; the new toggle decides
WHERE those links point: each computation-graph node carries `maps ego|web`; at `ego` its input
and output links end on ego nodes (tagged chunks, notes), at `web` on the world's nodes. A
toggle node in graph form, a field in panel form (item 33).

### 10.9 Black-box containment, unfoldable recursively (item 80)

A `{ref}` to a code module is a black box: its panel shows the module's signature line; a
right-click unfolds its rank-1 contents (classes, functions -- mortegon M.3: "when these tokens
are right clicked ... they compile the next level of recursive syntax tree"), each again a
black box, recursively; folded, it collapses back. Built on `code://` addressing (Python's own
tree as the xpath) and the slate fold state (G-296).

### 10.10 The halo that slides -- 2D only, ego only (items 81-84)

*"when we click on a computation graph artifact (either node or panel form), we see a
polar-coordinate force-directed layout on similarity-based proximity diffs local to the node.
So, radial coordinates are similarity to the node ... and angular coordinates in 2D are the
lateral retrieved result similarities to each other."*

Against mortegon: DM §8.2.1 already makes the halo polar (`r = r_focal + r_inner + (1 -
normalized_score) * r_extent`); what is new is the ANGLE (theirs is free; here it is set by the
results' similarity to one another), the force-direction on local similarity diffs, the chunking
by renderability, and the sliding navigation.

**Layout.** Focus f, candidates = ego retrieval for f, cut to the top K that can be RENDERED at
the current size (K from the plane's area over a node's footprint -- "only the top-most
renderable retrieval results ever call this layout"). Radius `r_i = r0 + (1 - s_i) * R`, `s_i`
the ADDITIVE score (10.11) of i against f -- links count through the PageRank term. Angle: the
results' pairwise similarity matrix ordered around the circle (spectral seriation), then a few
force steps: angular attraction proportional to pairwise similarity, repulsion between
neighbours closer than a node's width -- so similar results sit side by side.

**Sliding** (my reading of the motion rule -- *Question 9.8*): with the pointer outside the
focus's panel or node, its motion is a velocity over the layout -- a cursor point that moves by
the pointer's xy delta (reversible: the same delta back returns to the same place), scaled so
that a fast short stroke and a slow long one travel alike (the gain grows with speed, as pointer
acceleration does). The node nearest the cursor point is the navigated one, lit; a line traces
the shortest path back to the focus over the halo's similarity graph.

**Sticking** (item 83): selecting the navigated node sticks it onto the plane as a panel -- linked
or not -- and slidable there like any panel.

**Toggling** (item 84; *Question 9.9*): proposed -- a click on a node or a panel's header node
without moving opens its halo (the reader's "when we click"); Escape or a click on the focus
closes it. Today that click opens/closes a craft node's panel, so one of the two moves.

### 10.11 Retrieval terms are additive (item 85)

*"Retrieval terms should be additive (i think, and normalized between 0 and 1 for their
components) rather than multiplicative."* Today `domvec/search.py` multiplies: `lexical *
semantic * pagerank`, and G-294 multiplied in the content factor. Mortegon's rank is also a
product (DM §8.1, the "triple product"). New:

`score = w_lex * lex~ + w_sem * sem~ + w_pr * pr~ + w_con * content`

each `~` term normalized to 0..1 over the candidate set (lexical / max lexical; cosine mapped
`(c + 1) / 2`; PageRank as its percentile), weights summing to 1 (default .35 / .40 / .10 /
.15). Measured against the old product on the G-294 queries before switching, and G-294's
boilerplate check re-run on it.

### 10.12 Build order (procedural, each live-checked with a planted arm)

*Where it stands, 2026-11-01 (late) -- verdicts in `build_analytics/live_confirmations.md`:*

| piece | built | live check |
|---|---|---|
| additive retrieval (10.11) | `search.py` `fuse="additive"`, content squared at 0.25 | G-310 Confirm; G-294 green on it |
| `where` ego / web (10.7) | sidecar `search_payload(where=)`, kernel `search(where=)`, cockpit `search/where` | G-306 Confirm |
| the `+ ego` tag (10.5) | billboard control, `/ego/tag`, `ego.json`, craft `web` nodes | G-306 (via the function the control calls) |
| the ego's projection (10.4) | `/ego/projection` (PCA under 15, UMAP from 15), craft places by knowledge key; craft notes drawn at size 0 in the world | G-303 written, running |
| the browser panel (10.1) | `browserpanel.ts`: one card, cockpit slate + `BrowserView`; url both ways, live / boxes toggles, back / forward / scan actions, `scope` kept | G-300 written; all but `scope page` seen |
| the halo that slides (10.10) | `planehalo.ts`; `/ego/pairwise` | G-309 written, running |
| I/O ego or web (10.8) | `maps` frontmatter chip on the header; `refs.resolve(allow=)`; craft I/O lines to ego nodes | G-307 written, running |
| reader's panels in the ego (10.6) | plane notes are ego artifacts, indexed, in the craft, cell or not | via G-299, G-309 |
| scope ladder's chunk rung (10.2), black-box unfold (10.9) | not built | -- |

1. Additive retrieval (10.11) -- touches every search; first, so every later piece ranks on it.
2. The `where` field (10.7) and the `+ ego` tag (10.5) -- the ego set becomes queryable.
3. The ego projection (10.4) placing the craft's nodes; world placement of I/O retired.
4. The browser panel and its cockpit slate (10.1); the scope ladder (10.2).
5. The halo that slides (10.10).
6. The I/O toggle (10.8); black-box unfolding (10.9).

## 11. Many browsers, typed navigation, the code graph web, visible computation (items 87-100, 2026-11-01)

*Design before code for PLUGIN_GOAL items 87-100 (verbatim there). PRD rows G-313 to G-322.*

### 11.1 Many browsers; the 3D graph follows the one in use (items 87-89)

Today one browser cell: 15 places in the plugin take `getLeavesOfType(BROWSER_VIEW)[0]` (graph 6,
main 5, verify 3, anomalies 1). Design: every `BrowserView` -- the standalone pane, each plane
browser panel, each notebook browser fence -- registers itself; the plugin keeps the one the
reader last INTERACTED with (pointer or key in it) as the active browser, and every one of those
15 places asks for it instead of the first. Hover-to-3D, fly-to, the in-graph badge, the web
search and the offline page follow whichever browser is in use. `+ browser` on the plane opens a
NEW instance each time (`domvec/browser 2.md`, ... -- one cockpit slate per instance), each its
own session (its webview partition, its tabs).

Item 89, read with mortegon M.2-M.5 and DM 9.6.1: the browser's cockpit slate and the code that
backs it are the class DEFINITION; each running browser is an INSTANCE -- separate nodes in the
craft, joined by an undirected `instance_of` line (the functional-object memory link: forward,
code -> instance; inverse, instance -> its code).

### 11.2 Cell-level tools: sooner, later, similar, and a soft-link field (item 90)

Beside `+ notebook` / delete, on each panel's header: **sooner** -- a fan of the ego's cells made
BEFORE this one (by creation time), opened as minimized nodes on an arc to its left; **later** --
those made after, to its right; **similar** -- the toggle for the 2D retrieval (the halo, 10.10);
and an **input field** that retrieves over soft links among the ego's cells (`where=ego`,
the field's text as the query), its results laid out by the same halo.

### 11.3 The halo re-keys on the navigated node; type-aware similarity (items 91-92)

*"nodes being navigated to (closest in 2d) are then the retrieval keys for the dynamic force
directed polar coordinate ... layout"*: when the slide rests on a result (a dwell of ~0.6 s), that
result becomes the FOCUS -- its own retrieval laid out around it, the trace extended back through
the previous focus. Similarity gains a TYPE term (item 92): each artifact's kind and layer of
abstraction -- note / cell / tree / chunk; for code, module / class / function / method -- with a
PageRank over the type graph (inheritance, containment, calls) giving each type's weight, so a
cell's halo holds cells, a method's holds methods of related classes. Added to the additive score
as one more 0..1 term (10.11).

### 11.4 The code graph web (items 93-95)

A GLOBAL LIBRARY graph built from Python's own syntax tree across the repository and the
installed packages the kernels import: nodes are named definitions (module, class, function),
edges are containment, inheritance, calls and imports -- "both named string subtypes and
adjacency based graph structures". PageRank over it is a retrieval term for code chunks
(item 93). Concrete syntax trees (libcst, item 94) keep comments and formatting, which the AST
drops: **a download, asked before installing** (question 9.10). The web view of it (item 95):
the code graph's nodes as an ego-UMAP network (frequency and encoder vectors, the triple
retrieval) beside the patricia trie's, translated into the node/panel dialect -- a module's
panel is its black box (G-308), its graph form the code graph's neighbourhood.

### 11.5 The ego's memory, live; 3D the microscope, 2D the editor (items 96-98)

The craft (5a) draws the ego's memory as it evolves: each run's recursive / iterative unroll
(rollout samples, G-283-rollout) adds its readout node and its undirected lookup links (forward:
input -> readout; inverse: readout -> inputs, G-279's recorded runs). 3D: the ego's own UMAP
(G-303), compact, and the wheel ZOOMS INTO it -- at the floor over a craft node, a further
wheel-in opens its panel on the plane (item 7's zoom-through, "the microscope of the ego").
2D: the plane is the precise editor where readouts are built.

### 11.6 Visible computation: active triples are lights (item 99)

A computation in flight is a triple -- subject (input), predicate (the cell / function), object
(readout). While a cell runs: its panel's header node glows on the plane; in 3D its craft node
and its I/O lines pulse in the signal colour (G-292's pulse, carried to the craft). Both views,
the same moment.

### 11.7 Typed panels and instant feedback (item 100)

From mortegon E.6, O.15, DM 9.6.1: a definition's panel is TYPED -- `name: Type = value` rows;
functions show their inputs' and output's types (inferred jointly: annotations top-down,
observed values bottom-up); a class shows `super: Base`. Unnesting a black box (G-308) shows its
typed rows AND, at once, the search's top results for that symbol -- the high-frequency rollout's
instant feedback.

### 11.8 Build order

1. Typed black-box rows + instant search on unfold (11.7) -- extends G-308.
2. The halo re-keys on the navigated node (11.3, first half).
3. Visible computation lights (11.6).
4. Cell tools sooner / later / similar / field (11.2).
5. Many browsers, active browser followed (11.1).
6. Type-aware similarity term; the code graph and its PageRank (11.3 second half, 11.4).
7. Zoom-through into the craft (11.5).
