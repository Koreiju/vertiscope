# The ego canvas (PLUGIN_GOAL 183)

**Superseded 2026-11-22 by `COMPUTATION_GRAPH_EDITOR_SPEC.md` §12**, rewritten
from the record after 184-186. This file's `![[...]]` / `[[...]]` sections, the
separate canvas note and the nested panels are wrong against UR O.1a (a
brace's three states are fold state), item 54 (one ego) and item 136 (links
only from compilation); §12g lists each. Kept for its history.

The reader's words are in `docs/PLUGIN_GOAL.md` item 183 and its answers.
This file is my decomposition of them against what exists. Where it says
"reading", it is my interpretation and not yet confirmed.

## 1. What 183 replaces

| now | 183 |
|---|---|
| the ego as a 3D **craft** of circle nodes and lines (`craft.ts`, G-299); the cockpit slate `domvec/ego.md` as one node among them | the ego as ONE central **artifact canvas** on the plane: the cockpit and every ego artifact embedded in it |
| 2D circles: a minimized panel is a circle "header node" (items 54-55); the ground double-click flips panels to **graph form** (135b); a slate's graph form (G-281) | **none in 2D**: "in the 2D plane, we deal only with the interface canvases themselves" |
| the craft's membership rule (G-291: a slate, a note whose cell ran, a note on the plane) | the same rule seeds the canvas's sections; after that the canvas note IS the membership, edited by pull-out / push-in |
| 3D: the craft drawn as its own circle graph beside the world | 3D: "follow the graph formatting exactly as world" -- glowing nodes for the ego's chunks on its own UMAP, its artifacts' graph structure as links, canvases as **billboards** at the level of the node hovered |

## 2. The canvas note

`domvec/ego canvas.md`, frontmatter `domvec: canvas`. Its body is a list of
**sections**, one per line, in order:

    ![[domvec/ego]]                 an EMBEDDED component (drawn in the canvas)
    [[domvec/graph/notebook 3]]     a component PULLED OUT (its own panel; the link kept)

- **Contained = embedded** (`![[...]]`). One source of truth per component:
  the component stays its own note (the reader's answer: "Embeds").
- **Order = compile order** (item 142): the canvas's line order is the
  context order a model reads; dragging a section's header reorders the lines.
- In trie terms the canvas is a `vault://` page and each section a line of
  it; a section's component is the page that line links to.

## 3. The canvas panel (2D)

At the plane's centre, always at the centre of view. Each embedded section is
a header (its name, fold toggle) over the component drawn LIVE: the
component's note in a real editor, with its own tools (the run / terminal /
open / unnest and typed rows of G-395) -- "editable in place". A folded
section is its header alone and mounts no editor (23 editors open at once
would be the cost otherwise).

**Graph operations** (all four were asked for first):

1. **Pull out / push in.** Hold a section's header (the 182 debounce: a
   click is a fold, a press held still past 350 ms picks it up) and drop it
   off the canvas: the line becomes `[[...]]` and the component opens as its
   own panel where it was dropped. Drop a panel's card on the canvas: its line
   becomes `![[...]]` at the drop position and the card closes into the canvas.
2. **Links between panels.** The pulled-out panels and the canvas are joined
   on the plane by the links between their notes (wiki links, `{ref}`s, the
   canvas's own `[[...]]` lines), drawn as lines between card edges.
3. **Order.** A header dragged within the canvas moves its line.
4. **Fold / unnest.** A section folds to its header; a code section's unnest
   is the code cell's own (G-328/329).

## 4. The 3D view (reading, to be confirmed in the build)

- The ego's chunks drawn as the web world's are: glowing nodes, on the ego's
  OWN UMAP (G-303), its artifacts' links as edges.
- Hover a node: the canvas of that node's LEVEL is billboarded -- a higher
  rank node (a note; the canvas itself at the top) a more comprehensive
  canvas, a chunk its block.
- Select / click moves a component between the plane and the 3D map: included
  on the plane (a section, or a panel), or relegated to the 3D chunk map.

## 5. Build order

| row | slice | depends on |
|---|---|---|
| G-396 | the canvas note, seeded from the craft membership; the canvas panel at the plane's centre; embedded sections drawn live, folded by default except the cockpit | -- |
| G-397 | pull out / push in; reorder | G-396 |
| G-398 | links between the pulled-apart panels and the canvas, drawn on the plane | G-397 |
| G-399 | no circles in 2D: minimize-to-circle, the ground flip to graph form and the slate's graph form retired (their checks retired with them, by name) | G-396 |
| G-400 | 3D: the craft's circles replaced by the ego's chunk nodes on its UMAP and canvas billboards by level; plane <-> 3D include / relegate | G-396 |
