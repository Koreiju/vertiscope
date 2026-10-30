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
- **UMAP over the ego reservoir** (item 43: "UMAP happens on the ego reservoir for all
  computation graph nodes as artifacts of various kinds"). Every computation-graph node -- a
  cell, a slate, a readout, the cockpit, a search and its results -- is an ARTIFACT with an
  embedding (its rendered text through the same encoder the chunks use), placed by the same
  global ParametricUMAP `transform` as pages and chunks (G-270's global scope). The reservoir is
  therefore not a separate picture: its nodes sit among the web and vault chunks they read and
  write, and a readout lands beside what it resembles. New nodes are a delta on the stream
  (online `transform`, no refit).

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
