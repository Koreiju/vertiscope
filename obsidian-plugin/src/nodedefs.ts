/**
 * Node definitions from the live namespace (G-409; PLUGIN_GOAL 187, UR
 * M.3-M.5, spec §13d'). After a python cell runs, the note's kernel says
 * which functions and classes its cells define, with their ports; a plane
 * card draws them lo-fi at its foot, one row per node:
 *
 *     scan(url ●str, k [8], mode ‹fast|deep›, driver ●object) → list
 *
 * `[v]` is a widget (a primitive with a default), `‹a|b›` a choice (a
 * Literal), `●T` a socket, `→ T` the output (`→ ?` = inferred by wiring).
 * A function is a node the moment the cell that writes it runs (B20).
 *
 * In trie terms: reads the note kernel's namespace and writes nothing into the
 * note; the rows are a readout keyed by the note's vault:// path. Planted
 * `__domvecPlantAllSockets` (sidecar side): every port a socket.
 */
export type Port = { name: string; type: string | null; kind: "widget" | "socket" | "choice"; default?: any; options?: any[] };
export type NodeDef = { name: string; node: "function" | "class"; inputs: Port[]; output?: { type: string | null };
  outputs?: { name: string; type: string | null }[]; traits?: Port[]; doc: string };

export const nodeDefs: Record<string, NodeDef[]> = {};
(window as any).__domvecNodeDefs = nodeDefs;

const portText = (p: Port) => p.kind === "widget" ? `${p.name} [${JSON.stringify(p.default)}]`
  : p.kind === "choice" ? `${p.name} ‹${(p.options || []).join("|")}›` : `${p.name} ●${p.type || "?"}`;

export function rowOf(d: NodeDef): string {
  const ins = [...d.inputs, ...(d.traits || [])].map(portText).join(", ");
  const out = d.node === "class" ? (d.outputs || []).map((o) => `.${o.name} → ${o.type || "?"}`).join(", ")
    : `→ ${d.output?.type || "?"}`;
  return `${d.node === "class" ? "class " : ""}${d.name}(${ins}) ${out}`.trim();
}

export function drawDefs(card: HTMLElement | null | undefined, defs: NodeDef[]): void {
  if (!card) return;
  let box = card.querySelector(":scope > .domvec-node-defs") as HTMLElement | null;
  if (!defs.length) { box?.remove(); return; }
  if (!box) box = card.createDiv({ cls: "domvec-node-defs" });
  box.empty();
  for (const d of defs) {
    const r = box.createDiv({ cls: "domvec-node-def", text: rowOf(d) });
    r.dataset.node = d.name;
    if (d.doc) r.setAttr("aria-label", d.doc);
  }
}
