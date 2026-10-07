/**
 * Is what the 3D view DRAWS a tree? (2026-10-04: "the patricia trie shown
 * clearly and guaranteed tree-structured".)
 *
 * Each url's drawn subgraph should be the trie's own shape: one root (the
 * page node, or the streaming root while no page node is drawn yet), every
 * other node hanging from exactly ONE parent, no cycle, and no edge reaching
 * into another url's subtree. Edges come from three places -- containment
 * edges the sidecar places, the streaming (force) tree, and the page star --
 * and `treeOnly` prunes only the first, so a node can hold a containment
 * parent and a streaming parent at once. This verdict counts over EVERY drawn
 * edge, whichever path drew it.
 *
 * Pure, so a module test can plant each defect without Obsidian.
 */
export interface TreeVerdict {
  ok: boolean;
  nodes: number;
  edges: number;
  /** Nodes with more than one distinct parent. */
  multiParent: number;
  /** Nodes on a parent cycle. */
  cyclic: number;
  /** Edges whose ends belong to different urls (not page-to-page). */
  crossUrl: number;
  /** Urls with more than one root (parentless node) drawn. */
  forests: number;
  /** Up to five offenders, for the record. */
  sample: { id: string; why: string; parents?: string[] }[];
}

const end = (x: any): string => (typeof x === "object" && x ? x.id : x);
const base = (u: string): string => String(u || "").split("#")[0];

export function treeVerdict(nodes: any[], links: any[]): TreeVerdict {
  const byId = new Map<string, any>(nodes.map((n: any) => [n.id, n]));
  const parents = new Map<string, Set<string>>();
  const sample: TreeVerdict["sample"] = [];
  let crossUrl = 0, edges = 0;
  for (const l of links) {
    const s = end(l.source), t = end(l.target);
    const a = byId.get(s), b = byId.get(t);
    if (!a || !b || s === t) continue;
    // Page-to-page edges are the corpus graph, not any page's trie.
    if (a.level === "page" && b.level === "page") continue;
    edges++;
    if (a.url && b.url && base(a.url) !== base(b.url)) {
      crossUrl++;
      if (sample.length < 5) sample.push({ id: t, why: `edge from another url's node ${s}` });
      continue;
    }
    (parents.get(t) || parents.set(t, new Set()).get(t)!).add(s);
  }
  let multiParent = 0;
  for (const [id, ps] of parents) {
    if (ps.size < 2) continue;
    multiParent++;
    if (sample.length < 5) sample.push({ id, why: "more than one parent", parents: [...ps].slice(0, 4) });
  }
  // A cycle: walking up from any node revisits one. Every parent is walked
  // (not only the first), so a cycle through a second parent is not missed.
  let cyclic = 0;
  const state = new Map<string, number>();            // 1 on the stack, 2 done
  const onCycle = new Set<string>();
  const visit = (id: string, stack: string[]): void => {
    const st = state.get(id);
    if (st === 2) return;
    if (st === 1) {
      for (let i = stack.lastIndexOf(id); i >= 0 && i < stack.length; i++) onCycle.add(stack[i]);
      return;
    }
    state.set(id, 1);
    stack.push(id);
    for (const p of parents.get(id) || []) visit(p, stack);
    stack.pop();
    state.set(id, 2);
  };
  for (const id of byId.keys()) visit(id, []);
  cyclic = onCycle.size;
  for (const id of [...onCycle].slice(0, Math.max(0, 5 - sample.length))) sample.push({ id, why: "on a parent cycle" });
  // One root per url: a parentless node that is not the page node, while the
  // page node is drawn, is a second root.
  const roots = new Map<string, string[]>();
  for (const n of nodes) {
    if (parents.has(n.id) || !n.url) continue;
    const u = base(n.url);
    (roots.get(u) || roots.set(u, []).get(u)!).push(n.id);
  }
  let forests = 0;
  for (const [u, rs] of roots) {
    if (rs.length < 2) continue;
    forests++;
    if (sample.length < 5) sample.push({ id: u, why: `${rs.length} roots`, parents: rs.slice(0, 4) });
  }
  return { ok: !multiParent && !cyclic && !crossUrl && !forests, nodes: nodes.length, edges,
           multiParent, cyclic, crossUrl, forests, sample };
}
