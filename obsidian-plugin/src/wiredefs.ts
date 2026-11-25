/** G-238: a cell's wireframe components and their completion order (pure; complete.ts uses them). */
const NL = String.fromCharCode(10);

/** A top-level `def` of a cell: its name, its lines, and whether it is still a
 *  wireframe (a docstring and only `...` / `pass` under it). */
export interface WDef { name: string; from: number; to: number; text: string; doc: string; wire: boolean }

export function defsOf(code: string): WDef[] {
  const lines = code.split(NL), out: WDef[] = [];
  for (let i = 0; i < lines.length; i++) {
    const m = /^def\s+(\w+)\s*\(/.exec(lines[i]);
    if (!m) continue;
    let j = i + 1;
    while (j < lines.length && (!lines[j].trim() || /^\s/.test(lines[j]))) j++;
    while (j > i + 1 && !lines[j - 1].trim()) j--;
    const text = lines.slice(i, j).join(NL);
    const dm = text.match(/("""|''')([\s\S]*?)\1/);
    const rest = dm ? text.replace(dm[0], "") : text;
    const body = rest.split(NL).slice(1).map((l) => l.trim()).filter(Boolean);
    const wire = !!dm && body.length > 0 && body.every((l) => l === "..." || l === "pass");
    out.push({ name: m[1], from: i, to: j, text, doc: dm ? dm[2].trim() : "", wire });
    i = j - 1;
  }
  return out;
}

export function isWireframe(code: string): boolean { return defsOf(code).some((d) => d.wire); }

/** The wireframes in completion order: a component whose docstring names
 *  another wireframe comes after it (callees first); otherwise source order. */
export function orderDefs(defs: WDef[]): WDef[] {
  const wire = defs.filter((d) => d.wire), names = new Set(wire.map((d) => d.name));
  const needs = new Map(wire.map((d) => [d.name, [...names].filter((n) => n !== d.name && new RegExp("\\b" + n + "\\b").test(d.doc))]));
  const out: WDef[] = [], seen = new Set<string>(), busy = new Set<string>();
  const visit = (d: WDef) => {
    if (seen.has(d.name) || busy.has(d.name)) return;
    busy.add(d.name);
    for (const n of needs.get(d.name) || []) visit(wire.find((w) => w.name === n)!);
    busy.delete(d.name); seen.add(d.name); out.push(d);
  };
  wire.forEach(visit);
  return out;
}

