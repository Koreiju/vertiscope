/**
 * The slate's own gestures in the native editor (G-278; RESERVOIR_DESIGN
 * §3.1-3.3; UR O.1a, M.6, N.8, S.5, V.5): on any note in the slate class,
 *
 * - right-click a `{ref}`: INTERNALIZE it -- the target's rank-1 lines shown
 *   indented under its line, read-only, the braces dropped (revealed-internal);
 *   right-click again: fold it back to the braced token. Only the rank-1
 *   lines: "only rank-1 expansions on clicked ancestor nodes" (item 36).
 * - right-click the title line: COLLAPSE the slate to its circle (the
 *   singular node); right-click the circle: open it again.
 *
 * - double left-click the body: flip PANEL and GRAPH form (G-281; UR M.7;
 *   item 37: "2D/3D representations are shared, just differing on where they
 *   live") -- the same record drawn as circular single-field nodes joined by
 *   undirected lines (UR O.16), one node per field (node-count parity), laid
 *   out in the fields' own order, which is the signal flow (item 35).
 *
 * Fold state is kept per note (UR N.8, "fold state preserved"). Nothing is
 * written into the note: reveals and the collapse are decorations, so the
 * slate's text -- the record -- is only ever what the reader typed. Block
 * decorations come from a state field (a view plugin may not make them),
 * as `chunkhalves.ts` does.
 */
import { EditorState, Extension, RangeSetBuilder, StateEffect, StateField, Text } from "@codemirror/state";
import { Decoration, DecorationSet, EditorView, WidgetType } from "@codemirror/view";

/** One field line of a slate: its depth, key, value, and where the value sits. */
export interface SlateLine { line: number; depth: number; key: string; value: string; valueFrom: number; path: string[] }

/**
 * The slate grammar, as `domvec/slate.py` has it: structure is indentation
 * (tabs, or a consistent run of spaces), a key and its value split by a tab
 * (or two or more spaces -- a name may hold single spaces). Frontmatter is
 * skipped.
 */
export function parseSlate(text: string): SlateLine[] {
  const lines = text.split("\n");
  let i = 0;
  if (lines[0] === "---") { i = 1; while (i < lines.length && lines[i] !== "---") i++; i++; }
  const out: SlateLine[] = [];
  const stack: string[] = [];
  let unit = 0;
  for (; i < lines.length; i++) {
    const raw = lines[i];
    if (!raw.trim()) continue;
    const lead = /^[\t ]*/.exec(raw)![0];
    let depth = 0;
    if (lead.includes("\t")) depth = lead.split("\t").length - 1;
    else if (lead.length) { if (!unit) unit = lead.length; depth = Math.round(lead.length / unit); }
    const body = raw.slice(lead.length);
    const m = /^(.*?)(?:\t+| {2,})(.*)$/.exec(body);
    const key = (m ? m[1] : body).trim();
    const value = m ? m[2] : "";
    const valueFrom = m ? raw.length - m[2].length : raw.length;
    stack.length = depth;
    out.push({ line: i, depth, key, value, valueFrom, path: [...stack, key] });
    stack.push(key);
  }
  return out;
}

export interface Reveal { name: string; lines: string[] }
/** One note's fold state: the `{ref}`s revealed (by name) and whether the slate is collapsed. */
export interface FoldState { reveals: Record<string, string[]>; collapsed: boolean; graph?: boolean }

export const setFolds = StateEffect.define<FoldState>();

const EMPTY: FoldState = { reveals: {}, collapsed: false };

/** The first slate line after any frontmatter: the title. */
export function titleLine(doc: Text): number {
  let i = 1;
  if (doc.lines >= 1 && doc.line(1).text === "---") {
    i = 2;
    while (i <= doc.lines && doc.line(i).text !== "---") i++;
    i++;
  }
  while (i <= doc.lines && !doc.line(i).text.trim()) i++;
  return i <= doc.lines ? i : -1;
}

class RevealWidget extends WidgetType {
  constructor(readonly name: string, readonly lines: string[], readonly indent: number) { super(); }
  eq(o: RevealWidget): boolean { return o.name === this.name && o.lines.join("\n") === this.lines.join("\n") && o.indent === this.indent; }
  toDOM(): HTMLElement {
    const el = document.createElement("div");
    el.className = "domvec-slate-reveal";
    el.setAttribute("data-ref", this.name);
    for (const l of this.lines.length ? this.lines : ["(nothing at rank 1)"]) {
      const row = el.createDiv({ cls: "domvec-slate-reveal-line" });
      row.style.paddingLeft = `${(this.indent + 1) * 3}ch`;
      row.setText(l.replace(/\t/g, "   "));
    }
    return el;
  }
  ignoreEvent(): boolean { return false; }
}

class CircleWidget extends WidgetType {
  constructor(readonly title: string) { super(); }
  eq(o: CircleWidget): boolean { return o.title === this.title; }
  toDOM(): HTMLElement {
    const el = document.createElement("div");
    el.className = "domvec-slate-circle";
    el.createDiv({ cls: "domvec-slate-circle-dot", text: this.title.slice(0, 18) });
    return el;
  }
  ignoreEvent(): boolean { return false; }
}

/** The slate as a graph: one circle per field, undirected lines parent ->
 *  child, rows in the text's order (the signal flow), columns by depth. */
class GraphWidget extends WidgetType {
  constructor(readonly text: string) { super(); }
  eq(o: GraphWidget): boolean { return o.text === this.text; }
  toDOM(): HTMLElement {
    const fs = parseSlate(this.text);
    const NS = "http://www.w3.org/2000/svg";
    const el = document.createElement("div");
    el.className = "domvec-slate-graph";
    const row = 26, col = 22, r = 7, pad = 12;
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("width", "100%");
    svg.setAttribute("height", String(pad * 2 + Math.max(1, fs.length) * row));
    const at = fs.map((f, i) => ({ x: pad + r + f.depth * col, y: pad + r + i * row }));
    // Lines first, under the circles: each field to its parent (the nearest
    // earlier field one level shallower).
    fs.forEach((f, i) => {
      if (f.depth === 0) return;
      for (let j = i - 1; j >= 0; j--) if (fs[j].depth === f.depth - 1) {
        const ln = document.createElementNS(NS, "line");
        ln.setAttribute("x1", String(at[j].x)); ln.setAttribute("y1", String(at[j].y));
        ln.setAttribute("x2", String(at[i].x)); ln.setAttribute("y2", String(at[i].y));
        ln.setAttribute("class", "domvec-slate-graph-edge");
        svg.appendChild(ln);
        break;
      }
    });
    fs.forEach((f, i) => {
      const c = document.createElementNS(NS, "circle");
      c.setAttribute("cx", String(at[i].x)); c.setAttribute("cy", String(at[i].y)); c.setAttribute("r", String(r));
      // A field whose value is a `{ref}` is drawn hollow: its node is elsewhere.
      c.setAttribute("class", "domvec-slate-graph-node" + (/^\{[^}]+\}$/.test(f.value.trim()) ? " is-ref" : ""));
      c.setAttribute("data-key", f.key);
      svg.appendChild(c);
      const t = document.createElementNS(NS, "text");
      t.setAttribute("x", String(at[i].x + r + 6)); t.setAttribute("y", String(at[i].y + 4));
      t.setAttribute("class", "domvec-slate-graph-label");
      t.textContent = f.value ? f.key + "  " + f.value : f.key;
      svg.appendChild(t);
    });
    el.appendChild(svg);
    return el;
  }
  ignoreEvent(): boolean { return false; }
}

/** The decorations a fold state makes over a document. */
export function foldDecorations(doc: Text, st: FoldState): DecorationSet {
  const b = new RangeSetBuilder<Decoration>();
  const t = titleLine(doc);
  if (t < 0) return Decoration.none;
  if (st.graph && !st.collapsed) {
    // Graph form: the slate's fields as nodes and lines, the same record.
    const from = doc.line(t).from, to = doc.line(doc.lines).to;
    b.add(from, to, Decoration.replace({ widget: new GraphWidget(doc.toString()), block: true }));
    return b.finish();
  }
  if (st.collapsed) {
    // The whole slate -- title and body -- as one circle.
    const from = doc.line(t).from, to = doc.line(doc.lines).to;
    b.add(from, to, Decoration.replace({ widget: new CircleWidget(doc.line(t).text.trim()), block: true }));
    return b.finish();
  }
  for (let i = t; i <= doc.lines; i++) {
    const line = doc.line(i);
    const re = /\{([^}]+)\}/g;
    let m: RegExpExecArray | null;
    const marks: [number, number][] = [];
    let reveal: { name: string; lines: string[] } | null = null;
    while ((m = re.exec(line.text))) {
      const name = m[1];
      if (!(name in st.reveals)) continue;
      // Braces dropped on the revealed token (revealed-internal).
      marks.push([line.from + m.index, line.from + m.index + 1]);
      marks.push([line.from + m.index + m[0].length - 1, line.from + m.index + m[0].length]);
      if (!reveal) reveal = { name, lines: st.reveals[name] };
    }
    for (const [a, z] of marks) b.add(a, z, Decoration.replace({}));
    if (reveal) {
      const indent = (/^\t*/.exec(line.text) || [""])[0].length;
      b.add(line.to, line.to, Decoration.widget({ widget: new RevealWidget(reveal.name, reveal.lines, indent), block: true, side: 1 }));
    }
  }
  return b.finish();
}

export const foldField = StateField.define<{ st: FoldState; deco: DecorationSet }>({
  create: (s: EditorState) => ({ st: EMPTY, deco: Decoration.none }),
  update(v, tr) {
    let st = v.st;
    for (const e of tr.effects) if (e.is(setFolds)) st = e.value;
    if (st === v.st && !tr.docChanged) return v;
    return { st, deco: foldDecorations(tr.state.doc, st) };
  },
  provide: (f) => EditorView.decorations.from(f, (v) => v.deco),
});

export function slateFolds(): Extension { return foldField; }

/** The fold state an editor holds now. */
export function foldsOf(view: EditorView): FoldState {
  return view.state.field(foldField, false)?.st || EMPTY;
}
