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
if (typeof window !== "undefined") (window as any).__domvecNodeDefs = nodeDefs;

const portText = (p: Port) => p.kind === "widget" ? `${p.name} [${JSON.stringify(p.default)}]`
  : p.kind === "choice" ? `${p.name} ‹${(p.options || []).join("|")}›` : `${p.name} ●${p.type || "?"}`;

export function rowOf(d: NodeDef): string {
  const ins = [...d.inputs, ...(d.traits || [])].map(portText).join(", ");
  const out = d.node === "class" ? (d.outputs || []).map((o) => `.${o.name} → ${o.type || "?"}`).join(", ")
    : `→ ${d.output?.type || "?"}`;
  return `${d.node === "class" ? "class " : ""}${d.name}(${ins}) ${out}`.trim();
}

/** A default as Python writes it. */
export function pyLiteral(v: any): string {
  if (typeof v === "boolean") return v ? "True" : "False";
  if (typeof v === "number") return String(v);
  return JSON.stringify(String(v));
}

/** `text` with parameter `port` of def `node` (a class: its `__init__`)
 *  defaulting to `lit`; null when the signature is not found. Reads and writes
 *  only that one default, so the cell's other text is untouched. */
export function setDefault(text: string, node: string, port: string, lit: string): string | null {
  const head = new RegExp("(^|\\n)([ \\t]*)(def|class)[ \\t]+" + node + "\\b").exec(text);
  if (!head) return null;
  let at = head.index + head[0].length;
  if (head[3] === "class") {
    const init = /\bdef[ \t]+__init__[ \t]*\(/g; init.lastIndex = at;
    const m = init.exec(text); if (!m) return null; at = m.index + m[0].length - 1;
  }
  const open = text.indexOf("(", at); if (open < 0) return null;
  // The signature's parameters, split at depth 0.
  let depth = 0, start = open + 1;
  const parts: [number, number][] = [];
  for (let k = open; k < text.length; k++) {
    const c = text[k];
    if (c === "(" || c === "[" || c === "{") { depth++; continue; }
    if (c === ")" || c === "]" || c === "}") { depth--; if (depth === 0) { parts.push([start, k]); break; } continue; }
    if (c === "'" || c === '"') { const e = text.indexOf(c, k + 1); if (e < 0) return null; k = e; continue; }
    if (c === "," && depth === 1) { parts.push([start, k]); start = k + 1; }
  }
  for (const [a, b] of parts) {
    const seg = text.slice(a, b);
    if (!new RegExp("^\\s*" + port + "\\b").test(seg)) continue;
    const eq = seg.indexOf("=");
    if (eq < 0) return null;
    const lead = seg.slice(eq + 1).match(/^\s*/)![0], trail = seg.match(/\s*$/)![0];
    return text.slice(0, a + eq + 1) + lead + lit + trail + text.slice(b);
  }
  return null;
}

/** A trait's default in a class body: `name = traitlets.Int(3)` -> `Int(lit)`;
 *  null when the class or the trait line is not found. */
export function setTraitDefault(text: string, cls: string, trait: string, lit: string): string | null {
  const head = new RegExp("(^|\\n)class[ \\t]+" + cls + "\\b[^\\n]*:").exec(text);
  if (!head) return null;
  const re = new RegExp("(\\n[ \\t]+" + trait + "[ \\t]*=[ \\t]*[\\w.]+\\()([^,)]*)", "g");
  re.lastIndex = head.index + head[0].length;
  const m = re.exec(text);
  if (!m) return null;
  const at = m.index + m[1].length;
  return text.slice(0, at) + lit + text.slice(at + m[2].length);
}

export function drawDefs(card: HTMLElement | null | undefined, defs: NodeDef[],
                         edit?: (node: string, port: string, lit: string) => void): void {
  if (!card) return;
  let box = card.querySelector(":scope > .domvec-node-defs") as HTMLElement | null;
  if (!defs.length) { box?.remove(); return; }
  if (!box) box = card.createDiv({ cls: "domvec-node-defs" });
  box.empty();
  for (const d of defs) {
    const r = box.createDiv({ cls: "domvec-node-def" });
    r.dataset.node = d.name;
    if (d.doc) r.setAttr("aria-label", d.doc);
    r.appendText((d.node === "class" ? "class " : "") + d.name + "(");
    [...d.inputs, ...(d.traits || [])].forEach((p, i) => {
      if (i) r.appendText(", ");
      // B14: a widget is edited in place; a choice is picked in place. Planted
      // `__domvecPlantNoWidgetEdit`: text only, as G-409 first drew it.
      const isTrait = (d.traits || []).includes(p);
      if (edit && !(window as any).__domvecPlantNoWidgetEdit && (p.kind === "widget" || p.kind === "choice")) {
        r.appendText(p.name + " ");
        // A trait's widget writes the trait's own default (`level = Int(3)`).
        const commit = (lit: string) => edit(d.name, (isTrait ? "trait:" : "") + p.name, lit);
        if (p.kind === "choice") {
          const sel = r.createEl("select", { cls: "domvec-node-port" });
          for (const o of p.options || []) sel.createEl("option", { text: String(o), value: JSON.stringify(o) });
          sel.value = JSON.stringify(p.default);
          sel.onchange = () => commit(pyLiteral(JSON.parse(sel.value)));
          sel.dataset.port = p.name;
        } else if (typeof p.default === "boolean") {
          const cb = r.createEl("input", { cls: "domvec-node-port", type: "checkbox" });
          cb.checked = p.default; cb.dataset.port = p.name;
          cb.onchange = () => commit(pyLiteral(cb.checked));
        } else {
          const inp = r.createEl("input", { cls: "domvec-node-port", type: typeof p.default === "number" ? "number" : "text" });
          inp.value = String(p.default ?? ""); inp.dataset.port = p.name;
          inp.style.width = Math.max(3, Math.min(14, inp.value.length + 3)) + "ch";   // size does not apply to type=number
          inp.onchange = () => commit(typeof p.default === "number" ? String(Number(inp.value)) : pyLiteral(inp.value));
        }
        r.querySelectorAll("input,select").forEach((el) => el.addEventListener("mousedown", (e) => e.stopPropagation(), true));
      } else r.appendText(portText(p));
    });
    r.appendText(") " + (d.node === "class" ? (d.outputs || []).map((o) => `.${o.name} → ${o.type || "?"}`).join(", ") : `→ ${d.output?.type || "?"}`));
  }
}
