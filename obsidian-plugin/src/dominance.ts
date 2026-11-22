/**
 * Rank-dominance (G-389; PLUGIN_GOAL 175 b: "Every node can fold its
 * dominated neighbours, in 2D and 3D alike"; UR Q.3-Q.5).
 *
 * RANK is a node's degree in the graph as drawn. A neighbour `m` of `d` is
 * DOMINATED by `d` when `d` outranks it and `d` is `m`'s highest-ranked
 * neighbour (ties by id, so every node has exactly one candidate dominator).
 * The fold is the closure: what `m` dominates in turn goes with it, never
 * crossing back through `d` and never taking a `keep` node (the ego).
 *
 * The page fold (G-110) is this rule's first case: a page outranks each of
 * its chunks and is each chunk's top neighbour. The trie fold (T-16) is the
 * same gesture with the trie's prefix order standing in for rank.
 *
 * Planted `PLANT_DOMINANCE_ALL`: every lower-ranked neighbour is taken,
 * dominated elsewhere or not -- the fold then swallows nodes another node
 * owns, which the live check is built to catch.
 */
export const DOMINANCE_PLANT = { all: false };

export interface DomEdge { a: string; b: string }

export function dominatedBy(ids: string[], edges: DomEdge[], root: string, keep: Set<string> = new Set()): string[] {
  const adj = new Map<string, Set<string>>();
  for (const id of ids) adj.set(id, new Set());
  for (const e of edges) {
    if (e.a === e.b || !adj.has(e.a) || !adj.has(e.b)) continue;
    adj.get(e.a)!.add(e.b); adj.get(e.b)!.add(e.a);
  }
  if (!adj.has(root)) return [];
  const rank = (x: string) => adj.get(x)!.size;
  const above = (x: string, y: string) => rank(x) > rank(y) || (rank(x) === rank(y) && x > y);
  const top = (m: string): string | null => {
    let best: string | null = null;
    for (const k of adj.get(m)!) if (best === null || above(k, best)) best = k;
    return best;
  };
  const out: string[] = [], seen = new Set<string>([root]);
  const walk = (d: string) => {
    for (const m of adj.get(d)!) {
      if (seen.has(m) || keep.has(m) || !above(d, m)) continue;
      if (!DOMINANCE_PLANT.all && top(m) !== d) continue;
      seen.add(m); out.push(m); walk(m);
    }
  };
  walk(root);
  return out;
}

// The live check (`G-389`) asks the rule itself, on a graph it builds.
if (typeof window !== "undefined") (window as any).__domvecDominance = { dominatedBy, DOMINANCE_PLANT };
