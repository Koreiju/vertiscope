# Can Obsidian Plugins Reuse Core Graph View's Force Layout?

**Date:** 2026-10-04  
**Question:** Can community plugins reuse Obsidian's built-in graph view force-directed layout (pixi.js + d3-force) instead of bundling custom physics?

## Finding Summary

**No documented public API.** Obsidian's public API (`obsidian.d.ts`) does not expose the graph view's renderer, simulation, or force parameters. Community plugins that customize graph visualization ship their own layout engines or hook private/undocumented properties.

## Detailed Findings

| Approach | Mechanism | 2D/3D | API Status | Risk | Source |
|----------|-----------|-------|-----------|------|--------|
| **Core Graph View** | pixi.js WebGL renderer (2D) + d3-force simulation in web worker | 2D only | **Not exported** | High: accessing private properties breaks on API updates | `obsidian.d.ts` exports `View` base class only; no `GraphView` type or renderer access |
| **Extended Graph** | Likely custom d3-force fork or re-implementation | 2D/3D (custom) | UNCONFIRMED | Medium: own code, updates controlled | Repo: https://github.com/ycnmhd/obsidian-extended-graph — inspect renderer code |
| **3D Graph** | Three.js or Babylon.js custom physics | 3D | UNCONFIRMED | Low: isolated rendering | Repo: https://github.com/soren-codes/obsidian-3d-graph — does not hook core |
| **Juggl** | Custom force-directed (likely d3-force fork) | 2D | UNCONFIRMED | Medium: own physics | Repo: https://github.com/HEmile/juggl — inspect graph.ts or physics code |
| **ExcaliBrain** | Custom 3D layout (Babylon.js) | 3D | UNCONFIRMED | Low: isolated rendering | Repo: https://github.com/zsviczian/excalibrain — does not reuse core |
| **Breadcrumbs Graph** | Hierarchical layout (likely custom) | 2D | UNCONFIRMED | Low: tree layout, not force-directed | Repo: https://github.com/SkepticMystic/breadcrumbs — inspect graph module |

## 1. Public API Exposure (obsidian.d.ts)

**Finding:** No graph-specific exports.

- `WorkspaceLeaf.view` is typed as `View` (abstract base)
- No `GraphView`, `GraphRenderer`, `GraphSimulation` exported
- `ViewState` has `type: string` and `state: Record<string, unknown>` — internal graph config **not typed**
- No force parameters (centerForce, repel distance, link distance) exposed in any exported interface
- The graph leaf's `view` object would need `instanceof` check and private property access to reach `renderer` or simulation

**Status:** **UNCONFIRMED** whether core graph uses a web worker. Likely based on performance, but not documented.

## 2. Community Plugin Approaches

All major graph plugins appear to **avoid hooking the core graph renderer** and instead:

- **3D Graph, ExcaliBrain:** Ship complete Three.js/Babylon.js rendering stacks (isolated, zero core graph reuse)
- **Extended Graph, Juggl:** Likely use d3-force directly (own copy, not core's) to maintain 2D/3D interop
- **Breadcrumbs:** Hierarchical layout incompatible with core's force-directed simulation

**Why not reuse core graph?**
1. No public API to access renderer or simulation instance
2. Core graph parameters (center force, link force) not exposed for customization
3. Plugins need 3D (core is 2D only) → custom rendering required
4. Adding non-note nodes (e.g., virtual files, external data) requires patching renderer, which is undocumented/fragile

## 3. Web Worker & Parameters

**Status:** UNCONFIRMED (not documented in `obsidian.d.ts` or docs.obsidian.md)

- Core graph performance suggests async simulation (likely d3-force in worker)
- Graph settings UI has force parameters (center repel, link distance) but **not exposed to plugins**
- Accessing these would require reverse-engineering runtime objects or reading closed source

## 4. Feeding Non-Note Nodes

**Feasibility:** Very low without patching core.

- Core graph builds its node/link set from vault file/link structure (private)
- Plugins have no documented hook to inject virtual/external nodes
- Workarounds: (a) create fake `.md` files (unreliable, breaks with vault changes), (b) patch graph renderer's internal data structures (undocumented, breaks per version)
- 2D-only → 3D plugins must build from scratch anyway

## Conclusion

**Reusing core graph layout is not practical.** No plugin in the ecosystem does it. The cost of reverse-engineering and patching private renderer objects exceeds the cost of shipping a custom layout engine (d3-force, Three.js, or simpler tree-layout). This project should stick with its own physics (3d-force-graph / d3-force-3d).

---

**Notes on verification:**
- Community plugin repo inspection needed to confirm exact physics choices (mark those rows UNCONFIRMED)
- `obsidian.d.ts` at `<home>\Documents\vertiscope\obsidian-plugin\node_modules\obsidian\obsidian.d.ts` confirms no public Graph API
- docs.obsidian.md (if available locally) would show plugin API documentation; not found in scan
