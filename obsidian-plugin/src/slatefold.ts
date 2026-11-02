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
export interface FoldState {
  reveals: Record<string, string[]>; collapsed: boolean; graph?: boolean;
  /** Fields whose rank-1 children are folded away, by path (`ego/search`).
   *  ONE state for both forms (mortegon DOMAIN_MODEL 7.3.4: graph form "has
   *  no independent fold state; it stays in node-count parity with the
   *  panel"), and per-subtree: folding a parent keeps its children's entries. */
  folds?: string[];
}

/** The fields a fold state leaves visible, and each folded field's last child
 *  (the dialect's one rule: a folded field shows `{name}`, its subtree hidden). */
export function visibleFields(fs: SlateLine[], folds: string[] = []): { shown: SlateLine[]; folded: Map<number, number> } {
  const want = new Set(folds);
  const shown: SlateLine[] = [];
  const folded = new Map<number, number>();
  for (let i = 0; i < fs.length; i++) {
    const f = fs[i];
    shown.push(f);
    let end = i;
    while (end + 1 < fs.length && fs[end + 1].depth > f.depth) end++;
    if (end > i && want.has(f.path.join("/"))) {
      folded.set(i, end);
      i = end;
    }
  }
  return { shown, folded };
}

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
  /** `all`: every reveal of the slate -- a `{ref}` in a revealed row is a node,
   *  and opened (right-click) its own rows nest beneath it: black-box
   *  containment, one rank at a time (PLUGIN_GOAL 80; mortegon M.3). */
  constructor(readonly name: string, readonly lines: string[], readonly indent: number,
              readonly all: Record<string, string[]> = {}) { super(); }
  private sig(): string {
    const seen = new Set<string>();
    const walk = (n: string): string => {
      if (seen.has(n)) return "";
      seen.add(n);
      const ls = n === this.name ? this.lines : this.all[n] || [];
      return n + "[" + ls.map((l) => { const m = /\{([^}]+)\}/.exec(l); return l + (m && m[1] in this.all ? walk(m[1]) : ""); }).join("|") + "]";
    };
    return walk(this.name);
  }
  eq(o: RevealWidget): boolean { return o.indent === this.indent && o.sig() === this.sig(); }
  toDOM(): HTMLElement {
    const el = document.createElement("div");
    el.className = "domvec-slate-reveal";
    el.setAttribute("data-ref", this.name);
    const seen = new Set<string>([this.name]);
    const rows = (lines: string[], depth: number) => {
      for (const l of lines.length ? lines : ["(nothing at rank 1)"]) {
        const row = el.createDiv({ cls: "domvec-slate-reveal-line" });
        row.style.paddingLeft = `${(this.indent + depth) * 3}ch`;
        const text = l.replace(/\t/g, "   ");
        const m = /\{([^}]+)\}/.exec(text);
        if (!m) { row.setText(text); continue; }
        row.appendText(text.slice(0, m.index));
        const open = m[1] in this.all;
        const node = row.createSpan({ cls: "domvec-var domvec-slate-reveal-ref" + (open ? " is-revealed" : ""),
                                      text: open ? (m[1].split("#").pop() || m[1]) : m[0] });
        node.setAttribute("data-ref", m[1]);
        row.appendText(text.slice(m.index + m[0].length));
        if (open && !seen.has(m[1])) { seen.add(m[1]); rows(this.all[m[1]], depth + 1); }
      }
    };
    rows(this.lines, 1);
    return el;
  }
  ignoreEvent(): boolean { return false; }
}

/** A fold marker's brace, drawn round a folded field's name (not in the text). */
class BraceWidget extends WidgetType {
  constructor(readonly ch: string) { super(); }
  eq(o: BraceWidget): boolean { return o.ch === this.ch; }
  toDOM(): HTMLElement {
    const el = document.createElement("span");
    el.className = "domvec-fold-brace";
    el.textContent = this.ch;
    return el;
  }
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

/** The slate as a graph: one circle per VISIBLE field, undirected lines parent
 *  -> child, rows in the text's order (the signal flow), columns by depth.
 *
 *  The other side of ONE record (mortegon DOMAIN_MODEL 7.3.4): it has no fold
 *  state of its own -- it draws exactly the fields the panel form shows
 *  (node-count parity), a folded field braced `{name}` (the fold marker in
 *  both forms), and a revealed `{ref}`'s rank-1 lines as child nodes joined by
 *  undirected lines. Its gestures are the panel's, said once for both and
 *  handed to the cockpit as a `domvec-slate-graph` event: right-click folds /
 *  unfolds a node with children or reveals / folds a `{ref}`; a click on a
 *  braced node instantiates its rank-1 walk; a double-click opens the node's
 *  containment panel (panel form, the cursor on that field). Planted
 *  `__domvecPlantNoFoldParity`: every field drawn, the folds ignored. */
class GraphWidget extends WidgetType {
  constructor(readonly text: string, readonly st: FoldState) { super(); }
  private key(): string { return this.text + "\u0000" + JSON.stringify([this.st.folds || [], Object.keys(this.st.reveals).sort()]); }
  eq(o: GraphWidget): boolean { return o.key() === this.key(); }
  toDOM(view?: EditorView): HTMLElement {
    const all = parseSlate(this.text);
    const parity = !(window as any).__domvecPlantNoFoldParity;
    const { shown: fs, folded } = parity ? visibleFields(all, this.st.folds) : { shown: all, folded: new Map<number, number>() };
    const foldedKeys = new Set([...folded.keys()].map((i) => all[i].path.join("/")));
    // The nodes, in order: each visible field, then a revealed ref's lines.
    type GNode = { key: string; label: string; depth: number; path: string; line: number; cls: string; parent: number; ref?: string };
    const nodes: GNode[] = [];
    const lastAt: number[] = [];
    for (const f of fs) {
      const path = f.path.join("/");
      const isFolded = foldedKeys.has(path);
      const ref = (/^\{([^}]+)\}$/.exec(f.value.trim()) || [])[1];
      lastAt.length = f.depth;
      const parent = f.depth > 0 ? (lastAt[f.depth - 1] ?? -1) : -1;
      nodes.push({ key: f.key, depth: f.depth, path, line: f.line, parent, ref,
                   label: (isFolded ? "{" + f.key + "}" : f.key) + (f.value ? "  " + f.value : ""),
                   cls: "domvec-slate-graph-node" + (ref && !(ref in this.st.reveals) ? " is-ref" : "") + (isFolded ? " is-folded" : "") });
      const me = nodes.length - 1;
      lastAt[f.depth] = me;
      for (const m of f.value.matchAll(/\{([^}]+)\}/g)) {
        const lines = this.st.reveals[m[1]];
        if (!lines) continue;
        for (const l of lines.length ? lines : ["(nothing at rank 1)"]) {
          nodes.push({ key: "", label: l.replace(/\t/g, "   ").trim(), depth: f.depth + 1, path: path + "/{" + m[1] + "}", line: f.line,
                       parent: me, cls: "domvec-slate-graph-node is-revealed" });
        }
      }
    }
    const NS = "http://www.w3.org/2000/svg";
    const el = document.createElement("div");
    el.className = "domvec-slate-graph";
    const row = 26, col = 22, r = 7, pad = 12;
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("width", "100%");
    svg.setAttribute("height", String(pad * 2 + Math.max(1, nodes.length) * row));
    const at = nodes.map((n, i) => ({ x: pad + r + n.depth * col, y: pad + r + i * row }));
    const line = (a: number, b: number, cls: string) => {
      const ln = document.createElementNS(NS, "line");
      ln.setAttribute("x1", String(at[a].x)); ln.setAttribute("y1", String(at[a].y));
      ln.setAttribute("x2", String(at[b].x)); ln.setAttribute("y2", String(at[b].y));
      ln.setAttribute("class", cls);
      svg.appendChild(ln);
    };
    nodes.forEach((n, i) => { if (n.parent >= 0) line(n.parent, i, "domvec-slate-graph-edge"); });
    // A field naming another VISIBLE field of this slate by `{ref}` is wired to
    // it: a solid line (UR O.1a's resolved-external state).
    const byKey = new Map<string, number>();
    nodes.forEach((n, i) => { if (n.key && !byKey.has(n.key)) byKey.set(n.key, i); });
    fs.forEach((f) => {
      const i = nodes.findIndex((n) => n.path === f.path.join("/"));
      for (const m of f.value.matchAll(/\{([^}]+)\}/g)) {
        const j = byKey.get(m[1]);
        if (j !== undefined && j !== i) line(i, j, "domvec-slate-graph-link");
      }
    });
    nodes.forEach((n, i) => {
      const c = document.createElementNS(NS, "circle");
      c.setAttribute("cx", String(at[i].x)); c.setAttribute("cy", String(at[i].y)); c.setAttribute("r", String(n.key ? r : r - 2));
      c.setAttribute("class", n.cls);
      c.setAttribute("data-key", n.key);
      c.setAttribute("data-path", n.path);
      if (n.ref) c.setAttribute("data-ref", n.ref);
      svg.appendChild(c);
      const t = document.createElementNS(NS, "text");
      t.setAttribute("x", String(at[i].x + r + 6)); t.setAttribute("y", String(at[i].y + 4));
      t.setAttribute("class", "domvec-slate-graph-label" + (n.cls.includes("is-folded") ? " is-folded" : ""));
      t.setAttribute("data-path", n.path);
      t.textContent = n.label;
      svg.appendChild(t);
    });
    el.appendChild(svg);
    const nodeOf = (e: Event) => {
      const p = (e.target as Element)?.getAttribute?.("data-path");
      return p == null ? null : nodes.find((n) => n.path === p) || null;
    };
    const tell = (kind: string, n: GNode) => el.dispatchEvent(new CustomEvent("domvec-slate-graph", {
      bubbles: true, detail: { kind, path: n.path, ref: n.ref || "", line: n.line, folded: n.cls.includes("is-folded") } }));
    svg.addEventListener("contextmenu", (e) => {
      const n = nodeOf(e);
      if (!n || !n.key) return;
      e.preventDefault(); e.stopPropagation();
      tell("right", n);
    });
    svg.addEventListener("click", (e) => {
      const n = nodeOf(e);
      if (!n || !n.cls.includes("is-folded") || e.detail > 1) return;
      e.preventDefault(); e.stopPropagation();
      tell("unfold", n);
    });
    svg.addEventListener("dblclick", (e) => {
      const n = nodeOf(e);
      if (!n || !n.key) return;
      e.preventDefault(); e.stopPropagation();
      tell("panel", n);
    });
    // Left-drag from one node onto another WIRES them (UR N.4): the dragged
    // field gains `{target}` -- written into the slate's text, the record, so
    // the panel form shows the same link. Planted `__domvecPlantNoWire`.
    let from: GNode | null = null;
    svg.addEventListener("mousedown", (e) => {
      const n = nodeOf(e);
      if (e.button !== 0 || !n || !n.key) return;
      from = n;
    });
    svg.addEventListener("mouseup", (e) => {
      const src = from, dst = nodeOf(e);
      from = null;
      if (!src || !dst || !dst.key || src === dst || !view || (window as any).__domvecPlantNoWire) return;
      e.preventDefault(); e.stopPropagation();
      const ref = "{" + dst.key + "}";
      const f = all.find((x) => x.path.join("/") === src.path);
      if (!f || f.value.includes(ref)) return;
      const ln = view.state.doc.line(f.line + 1);
      view.dispatch({ changes: { from: ln.to, to: ln.to, insert: f.value ? " " + ref : "\t" + ref } });
      ((window as any).__domvecWireStats = (window as any).__domvecWireStats || { wired: 0 }).wired++;
    });
    return el;
  }
  ignoreEvent(): boolean { return true; }
}

/** The decorations a fold state makes over a document. */
export function foldDecorations(doc: Text, st: FoldState): DecorationSet {
  const b = new RangeSetBuilder<Decoration>();
  const t = titleLine(doc);
  if (t < 0) return Decoration.none;
  if (st.graph && !st.collapsed) {
    // Graph form: the slate's fields as nodes and lines, the same record.
    const from = doc.line(t).from, to = doc.line(doc.lines).to;
    b.add(from, to, Decoration.replace({ widget: new GraphWidget(doc.toString(), st), block: true }));
    return b.finish();
  }
  if (st.collapsed) {
    // The whole slate -- title and body -- as one circle.
    const from = doc.line(t).from, to = doc.line(doc.lines).to;
    b.add(from, to, Decoration.replace({ widget: new CircleWidget(doc.line(t).text.trim()), block: true }));
    return b.finish();
  }
  // Variables are NODES in the panel (PLUGIN_GOAL 54-55, 2026-11-01: "variable
  // entities like "ego" are shown as nodes within the panel", in Obsidian's
  // purple linked-markdown style): the slate's own name on its title line --
  // the header node, shown here when the panel is open -- and every `{ref}`.
  // Planted `__domvecPlantNoVarNodes`: plain text.
  const nodes = !(window as any).__domvecPlantNoVarNodes;
  // Folded fields: braces round the name (the fold marker, mortegon O.2), the
  // subtree's lines replaced. Doc line of each folded field -> its last child.
  const fsAll = parseSlate(doc.toString());
  const foldAt = new Map<number, number>();
  for (const [i, end] of visibleFields(fsAll, st.folds).folded) {
    if (fsAll[i].line + 1 !== t) foldAt.set(fsAll[i].line + 1, fsAll[end].line + 1);
  }
  let skipTo = 0;
  for (let i = t; i <= doc.lines; i++) {
    if (i <= skipTo) continue;
    const line = doc.line(i);
    const re = /\{([^}]+)\}/g;
    let m: RegExpExecArray | null;
    const ranges: [number, number, Decoration][] = [];
    let reveal: { name: string; lines: string[] } | null = null;
    if (i === t && nodes) {
      const lead = line.text.length - line.text.trimStart().length, name = line.text.trim();
      if (name) ranges.push([line.from + lead, line.from + lead + name.length, Decoration.mark({ class: "domvec-var domvec-var-title" })]);
    } else if (i !== t) {
      // Every field NAME is a variable too (item 60: "most/all variables
      // contained within the panel are actual variables ... Unhighlighted
      // parts ... only be the filled values"): the key, up to its tab.
      const lead = line.text.length - line.text.trimStart().length;
      const rest = line.text.slice(lead), tab = rest.indexOf("\t");
      const key = (tab < 0 ? rest : rest.slice(0, tab)).trimEnd();
      // A positional child (`- x`, `1. x`) is a value in a list, not a name.
      if (key && !/^([-*+]|\d+\.)\s/.test(key) && !key.startsWith("{")) {
        const folded = foldAt.get(i);
        if (nodes) ranges.push([line.from + lead, line.from + lead + key.length,
          Decoration.mark({ class: "domvec-var domvec-var-key" + (folded ? " is-folded" : "") })]);
        if (folded) {
          ranges.push([line.from + lead, line.from + lead, Decoration.widget({ widget: new BraceWidget("{"), side: -1 })]);
          ranges.push([line.from + lead + key.length, line.from + lead + key.length, Decoration.widget({ widget: new BraceWidget("}"), side: 1 })]);
          ranges.push([line.to, doc.line(folded).to, Decoration.replace({})]);
          skipTo = folded;
        }
      }
    }
    while ((m = re.exec(line.text))) {
      const name = m[1], a = line.from + m.index, z = a + m[0].length;
      if (name in st.reveals) {
        // Braces dropped on the revealed token (revealed-internal); the name a node.
        ranges.push([a, a + 1, Decoration.replace({})]);
        if (nodes) ranges.push([a + 1, z - 1, Decoration.mark({ class: "domvec-var is-revealed" })]);
        ranges.push([z - 1, z, Decoration.replace({})]);
        if (!reveal) reveal = { name, lines: st.reveals[name] };
      } else if (nodes) {
        ranges.push([a, z, Decoration.mark({ class: "domvec-var" })]);
      }
    }
    ranges.sort((x, y) => x[0] - y[0] || (x[2] as any).startSide - (y[2] as any).startSide);
    for (const [a, z, d] of ranges) b.add(a, z, d);
    if (reveal) {
      const indent = (/^\t*/.exec(line.text) || [""])[0].length;
      b.add(line.to, line.to, Decoration.widget({ widget: new RevealWidget(reveal.name, reveal.lines, indent, st.reveals), block: true, side: 1 }));
    }
  }
  return b.finish();
}

export const foldField = StateField.define<{ st: FoldState; deco: DecorationSet }>({
  // Drawn from the first frame: the variable nodes (items 54-55) need no fold
  // state, and a note opened afresh showed none until a fold or an edit.
  create: (s: EditorState) => ({ st: EMPTY, deco: foldDecorations(s.doc, EMPTY) }),
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
