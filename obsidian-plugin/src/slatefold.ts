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
/** The cockpit as a PLAIN note (PLUGIN_GOAL 193-194): its settings are one
 *  python cell of `name = literal` lines, read as fields so the cockpit keeps
 *  its paths (`view`, `search/query`). A string's value is inside its quotes;
 *  `True`/`False` read as `true`/`false`. */
const SEARCH_KEYS = new Set(["query", "db", "duckduckgo", "where", "k", "n", "matching", "results"]);
export function isPlainCockpit(text: string): boolean {
  if ((window as any).__domvecPlantSlateOnly) return false;   // planted (G-418): the cell form unread
  const body = text.replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n?/, "").trimStart();
  return body.startsWith("#") && /^```python\s*$/m.test(text);
}
function parseCell(text: string): SlateLine[] {
  const lines = text.split("\n").map((l) => l.replace(/\r$/, "")), out: SlateLine[] = [];
  let i = lines.findIndex((l) => /^```python\s*$/.test(l));
  for (i++; i > 0 && i < lines.length && !/^```/.test(lines[i]); i++) {
    const m = /^(\w+)\s*=\s*(.*?)\s*$/.exec(lines[i]);
    if (!m) continue;
    let value = m[2], from = lines[i].indexOf(m[2], m[1].length);
    const q = /^(["'])(.*)\1$/.exec(value);
    if (q) { value = q[2]; from += 1; }
    else if (value === "True" || value === "False") value = value.toLowerCase();
    out.push({ line: i, depth: 1, key: m[1], value, valueFrom: from, path: SEARCH_KEYS.has(m[1]) ? ["ego", "search", m[1]] : ["ego", m[1]] });
  }
  return out;
}
export function parseSlate(text: string): SlateLine[] {
  if (isPlainCockpit(text)) return parseCell(text);
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
    // The slate's NAME -- the title line's first field, not its `{ref}`s (a
    // title "ego\t{unfolded} {view}" drew "ego\t{unfolded} {vi", seen 2026-11-22).
    el.createDiv({ cls: "domvec-slate-circle-dot", text: (this.title.split("\t")[0] || this.title).trim().slice(0, 18) });
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
/** Positions for the graph form: a force-directed layout (item 103). Seeded
 *  on a spiral by order, then relaxed: springs along parent links, pairwise
 *  repulsion scaled by label width, a weak pull to the centre. Planted
 *  `__domvecPlantTreeLayout`: the indented column it replaced. */
export function forceLayout(ns: { parent: number; w: number }[], kind: "force" | "tree" = "force"): { x: number; y: number }[] {
  const n = ns.length;
  if (kind === "tree") {
    const depth = ns.map(() => 0);
    ns.forEach((q, i) => { depth[i] = q.parent >= 0 ? depth[q.parent] + 1 : 0; });
    return ns.map((_, i) => ({ x: 20 + depth[i] * 22, y: 20 + i * 26 }));
  }
  const p = ns.map((_, i) => { const a = i * 2.39996, rr = 30 * Math.sqrt(i + 1); return { x: rr * Math.cos(a), y: rr * Math.sin(a) }; });
  const edges: [number, number][] = [];
  ns.forEach((q, i) => { if (q.parent >= 0) edges.push([q.parent, i]); });
  for (let it = 0; it < 320; it++) {
    const f = p.map(() => ({ x: 0, y: 0 }));
    for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++) {
      let dx = p[i].x - p[j].x, dy = p[i].y - p[j].y;
      let d = Math.hypot(dx, dy);
      if (d < 0.01) { dx = 0.01 * (i - j); dy = 0.01; d = Math.hypot(dx, dy); }
      // Labels run to the right: repelled more sideways, by their widths.
      const want = 34 + 0.5 * (ns[i].w + ns[j].w) * Math.abs(dx) / d;
      if (d < want * 1.15) {
        const k = 0.9 * (want * 1.15 - d) / d;
        f[i].x += dx * k; f[i].y += dy * k; f[j].x -= dx * k; f[j].y -= dy * k;
      }
    }
    for (const [a, b] of edges) {
      const dx = p[b].x - p[a].x, dy = p[b].y - p[a].y, d = Math.hypot(dx, dy) || 1;
      const rest = 40 + 0.2 * ns[a].w, k = 0.1 * (d - rest) / d;
      f[a].x += dx * k; f[a].y += dy * k; f[b].x -= dx * k; f[b].y -= dy * k;
    }
    const cool = 1 - it / 340;
    for (let i = 0; i < n; i++) {
      f[i].x -= 0.01 * p[i].x; f[i].y -= 0.01 * p[i].y;
      p[i].x += Math.max(-12, Math.min(12, f[i].x)) * cool;
      p[i].y += Math.max(-12, Math.min(12, f[i].y)) * cool;
    }
  }
  return p;
}

/** A graph node's key or value edited in place (item 104): an input over the
 *  text; Enter (or leaving it) writes the slate's TEXT -- the record -- and
 *  Escape leaves it as it was. */
function editInPlace(host: HTMLElement, target: SVGGraphicsElement, view: EditorView, all: SlateLine[], path: string, part: "key" | "value"): void {
  const f = all.find((x) => x.path.join("/") === path);
  if (!f) return;
  host.querySelector(".domvec-graph-edit")?.remove();
  const hr = host.getBoundingClientRect(), tr = target.getBoundingClientRect();
  const input = document.createElement("input");
  input.className = "domvec-graph-edit";
  input.value = part === "key" ? f.key : f.value;
  input.style.left = (tr.left - hr.left - 2) + "px";
  input.style.top = (tr.top - hr.top - 3) + "px";
  input.style.width = Math.max(60, tr.width + 40) + "px";
  host.appendChild(input);
  input.focus(); input.select();
  const stats = ((window as any).__domvecGraphEditStats = (window as any).__domvecGraphEditStats || { opened: 0, written: 0 });
  stats.opened++;
  const done = (write: boolean) => {
    if (!input.isConnected) return;
    const next = input.value;
    input.remove();
    if (!write) return;
    const ln = view.state.doc.line(f.line + 1);
    const indent = (/^\s*/.exec(ln.text) || [""])[0];
    const from = part === "key" ? ln.from + indent.length : ln.from + f.valueFrom;
    const to = part === "key" ? from + f.key.length : ln.from + f.valueFrom + f.value.length;
    if (next === (part === "key" ? f.key : f.value)) return;
    view.dispatch({ changes: { from, to, insert: next } });
    stats.written++;
  };
  input.addEventListener("keydown", (e) => {
    e.stopPropagation();
    if (e.key === "Enter") { e.preventDefault(); done(true); }
    else if (e.key === "Escape") { e.preventDefault(); done(false); }
  });
  input.addEventListener("blur", () => done(true));
  input.addEventListener("mousedown", (e) => e.stopPropagation());
}

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
    const r = 7, pad = 14;
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("width", "100%");
    // A GENERAL force-directed layout (PLUGIN_GOAL 103: "the graph layout is
    // supposed to be general force-directed form"; an indented column was a
    // tree printed sideways). Springs along the links, every pair repelled
    // by its labels' widths, a weak pull to the centre -- deterministic,
    // seeded by order, so a redraw lands where it was.
    const plantTree = !!(window as any).__domvecPlantTreeLayout;
    const at = forceLayout(nodes.map((n) => ({ parent: n.parent, w: 7 * (n.label.length + 2) })), plantTree ? "tree" : "force");
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    nodes.forEach((n, i) => {
      minX = Math.min(minX, at[i].x - r); maxX = Math.max(maxX, at[i].x + r + 10 + 7 * n.label.length);
      minY = Math.min(minY, at[i].y - r - 6); maxY = Math.max(maxY, at[i].y + r + 6);
    });
    if (!nodes.length) { minX = 0; minY = 0; maxX = 40; maxY = 40; }
    svg.setAttribute("viewBox", [minX - pad, minY - pad, maxX - minX + 2 * pad, maxY - minY + 2 * pad].join(" "));
    // At 1:1 -- text the size the slate's own text is; a graph wider than its
    // panel scrolls rather than shrinking its labels to nothing.
    svg.setAttribute("width", String(Math.round(maxX - minX + 2 * pad)));
    svg.setAttribute("height", String(Math.round(maxY - minY + 2 * pad)));
    (el as any).__layout = { kind: plantTree ? "tree" : "force", at: at.map((q) => ({ x: Math.round(q.x), y: Math.round(q.y) })) };
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
      // The key:value DUAL kept as one structured field (item 105), its two
      // parts each editable in place (item 104).
      const f = n.key ? fs.find((x) => x.path.join("/") === n.path) : undefined;
      if (f && !n.cls.includes("is-folded")) {
        const k = document.createElementNS(NS, "tspan");
        k.setAttribute("class", "domvec-graph-key"); k.setAttribute("data-path", n.path); k.setAttribute("data-part", "key");
        k.textContent = f.key;
        t.appendChild(k);
        if (f.value) {
          const v = document.createElementNS(NS, "tspan");
          v.setAttribute("class", "domvec-graph-value"); v.setAttribute("data-path", n.path); v.setAttribute("data-part", "value");
          v.setAttribute("dx", "6");
          v.textContent = f.value;
          t.appendChild(v);
        }
      } else t.textContent = n.label;
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
    // A single left-click EDITS (mortegon 7.3.4; item 104): the key or the
    // value under it, in place -- after a beat, so a double-click still flips.
    let editTimer = 0;
    svg.addEventListener("click", (e) => {
      const n = nodeOf(e);
      if (!n || e.detail > 1) return;
      if (n.cls.includes("is-folded")) { e.preventDefault(); e.stopPropagation(); tell("unfold", n); return; }
      const part = (e.target as Element)?.getAttribute?.("data-part");
      if (!part || !view || (window as any).__domvecPlantNoGraphEdit) return;
      e.preventDefault(); e.stopPropagation();
      const target = e.target as SVGGraphicsElement;
      window.clearTimeout(editTimer);
      editTimer = window.setTimeout(() => editInPlace(el, target, view, all, n.path, part as "key" | "value"), 260);
    });
    svg.addEventListener("dblclick", (e) => {
      window.clearTimeout(editTimer);
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
  // A plain note draws as Obsidian draws it: no slate layer (193-194).
  if (isPlainCockpit(doc.toString())) return Decoration.none;
  // RETIRED by PLUGIN_GOAL 183 ("in the 2D plane, we deal only with the
  // interface canvases themselves"; 182 "Both"): a stored `graph` flag draws
  // the panel. Planted `__domvecPlantGraphForm`: the graph form, as before.
  if (st.graph && !st.collapsed && (window as any).__domvecPlantGraphForm) {
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
      // PLAIN TEXT is not a field (2026-11-07: "all the regular text is
      // highlighted as variables with no reference for doing so"): a field is
      // indented under the title or carries the tab between its name and its
      // value. A sentence at the margin, a heading, is markdown. Planted
      // `__domvecPlantProseAsFields`: every line's start, as before.
      const field = lead > 0 || tab >= 0 || (window as any).__domvecPlantProseAsFields;
      if (field && key && !/^([-*+]|\d+\.)\s/.test(key) && !key.startsWith("{") && !key.startsWith("#")) {
        const folded = foldAt.get(i);
        if (nodes) ranges.push([line.from + lead, line.from + lead + key.length,
          Decoration.mark({ class: "domvec-var domvec-var-key" + (folded ? " is-folded" : "") })]);
        // An ACTION's value (back / forward / scan) reads false and shows
        // true under the pointer; a click acts (2026-11-07: "no 'go' for
        // booleans ... false with a hover to true"). Planted
        // `__domvecPlantNoActionHover`: plain text.
        if (tab >= 0 && /^(back|forward|scan)$/.test(key) && !(window as any).__domvecPlantNoActionHover) {
          const v0 = line.from + lead + tab + 1, val = rest.slice(tab + 1).trim();
          if (val) ranges.push([v0, v0 + rest.slice(tab + 1).length, Decoration.mark({ class: "domvec-var-action" })]);
        }
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
