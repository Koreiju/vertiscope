/**
 * VS Code-grade code cell capabilities, both in standalone `CodeView` AND
 * adaptively inside fenced ```` ```code cell ```` blocks of native markdown
 * notes (`G-447`; PLUGIN_GOAL 133, 200 e).
 *
 * In trie terms: reads `vault://<vault>/<note>#cell <k>` source cells and
 * resolves completions, call signatures, hover documentation, syntax
 * diagnostics, and go-to-definition against earlier cells in the same note,
 * installed Python modules (`jedi`/`parso`), and `code://` CPG nodes
 * (`/code_intel`, `/code_nodes`). Outside runnable code fences in markdown,
 * every handler yields immediately so prose editing and `[]()` retrieval stay
 * native.
 */
import {
  Decoration, EditorView, ViewPlugin, keymap, lineNumbers,
  highlightActiveLine, highlightActiveLineGutter,
  type DecorationSet, type ViewUpdate,
} from "@codemirror/view";
import { Prec, RangeSetBuilder, StateEffect, StateField, type EditorState, type Extension } from "@codemirror/state";
import { findFences } from "./fences";
import {
  commentPrefixForLang, fenceContextAtText, isPythonLang, nextLineIndent, toggleLinesComment,
  type FenceCursorContext,
} from "./fencecode";

export interface CodeCellHost {
  codeNodes: (q: string) => Promise<any[]>;
  openCode: (url: string) => void;
  noteOfView?: (view: EditorView) => string;
  externalDefs?: (note: string) => { name: string; note: string }[];
  codeIntel?: (body: {
    op: "complete" | "signature" | "hover" | "goto" | "diagnostics";
    cells?: string[];
    code?: string;
    cell_index?: number;
    line?: number;
    col?: number;
    note?: string;
    external_defs?: { name: string; note: string }[];
  }) => Promise<any>;
}

export const codeCellStats = {
  built: 0,
  fence_built: 0,
  completions_asked: 0,
  completions_returned: 0,
  attr_cache_hits: 0,
  last_completion_ms: 0,
  auto_imports_applied: 0,
  signatures_shown: 0,
  hovers_shown: 0,
  definitions_opened: 0,
  cell_jumps: 0,
  comments_toggled: 0,
  diagnostics_drawn: 0,
  last_definition: "",
};
(window as any).__domvecCodeCell = codeCellStats;

const PAIRS: Record<string, string> = { "(": ")", "[": "]", "{": "}", '"': '"', "'": "'" };
const CLOSERS = new Set([")", "]", "}", '"', "'"]);

interface DiagRange { from: number; to: number; message: string }
const setFenceDiags = StateEffect.define<DiagRange[]>();

const fenceDiagField = StateField.define<DecorationSet>({
  create: () => Decoration.none,
  update(deco, tr) {
    deco = deco.map(tr.changes);
    for (const e of tr.effects) {
      if (!e.is(setFenceDiags)) continue;
      const ranges = e.value
        .filter((d) => d.from >= 0 && d.to > d.from && d.to <= tr.state.doc.length)
        .sort((a, b) => a.from - b.from)
        .map((d) => Decoration.mark({ class: "domvec-code-diag-err", attributes: { title: d.message } }).range(d.from, d.to));
      deco = Decoration.set(ranges, true);
    }
    return deco;
  },
  provide: (f) => EditorView.decorations.from(f),
});

function fenceAt(state: EditorState, pos?: number): FenceCursorContext | null {
  if ((window as any).__domvecPlantNoFenceVscode) return null;
  const p = pos ?? state.selection.main.head;
  return fenceContextAtText(state.doc.toString(), p);
}

/** Sub-millisecond client-side receiver attribute cache (`G-450`): `sig::receiver -> items`. */
const clientAttrCache = new Map<string, any[]>();

function importsSignature(cells: string[]): string {
  const out: string[] = [];
  for (const c of cells) {
    for (const ln of c.split("\n")) {
      const t = ln.trim();
      if (/^(?:import|from|def|class)\s/.test(t)) out.push(t);
    }
  }
  return out.join(";");
}

function makeOption(it: any, fenceOpenLine: number): any {
  const opt: any = {
    label: String(it.label || ""),
    type: it.type || "variable",
    detail: it.detail || "",
    info: it.info || undefined,
    boost: it.auto_import ? 3 : 5,
  };
  if (it.auto_import && fenceOpenLine >= 0) {
    const imp = String(it.auto_import);
    opt.apply = (view: EditorView, completion: any, from: number, to: number) => {
      const doc = view.state.doc;
      const bodyLine = Math.min(doc.lines, fenceOpenLine + 2);
      const insertPos = doc.line(bodyLine).from;
      const already = doc.toString().includes(imp);
      if (already) {
        view.dispatch({ changes: { from, to, insert: completion.label }, selection: { anchor: from + completion.label.length } });
      } else {
        const delta = imp.length + 1;
        view.dispatch({
          changes: [
            { from: insertPos, to: insertPos, insert: imp + "\n" },
            { from: from, to: to, insert: completion.label },
          ],
          selection: { anchor: from + delta + completion.label.length },
        });
        codeCellStats.auto_imports_applied++;
      }
    };
  } else if (typeof it.apply === "string") {
    const rawSnippet = it.apply;
    opt.apply = (view: EditorView, _completion: any, from: number, to: number) => {
      const ln = view.state.doc.lineAt(from);
      const indent = ln.text.match(/^[ \t]*/)?.[0] ?? "";
      const indented = rawSnippet.split("\n").map((l, idx) => (idx === 0 ? l : indent + l)).join("\n");
      view.dispatch({
        changes: { from, to, insert: indented },
        selection: { anchor: from + indented.length },
      });
    };
  }
  return opt;
}

/** Shared completion builder from `/code_intel` + `/code_nodes` + local words (`G-447`, `G-450`). */
async function buildCompletions(
  host: CodeCellHost,
  docText: string,
  cells: string[],
  cellIndex: number,
  line1: number,
  col0: number,
  wordText: string,
  wordFrom: number,
  isPython: boolean,
  notePath = "",
  fenceOpenLine = -1,
): Promise<any> {
  const t0 = performance.now();
  codeCellStats.completions_asked++;
  const seen = new Set<string>();
  const opts: any[] = [];
  const isAttr = wordText.includes(".");
  const tail = isAttr ? wordText.slice(wordText.lastIndexOf(".") + 1) : wordText;
  const receiver = isAttr ? wordText.slice(0, wordText.lastIndexOf(".")) : "";
  const attrKey = isAttr && receiver && !(window as any).__domvecPlantPolluteDotCompletions
    ? `${importsSignature(cells)}::${receiver}`
    : "";

  if (attrKey && clientAttrCache.has(attrKey) && !tail.startsWith("_")) {
    const cached = clientAttrCache.get(attrKey)!;
    codeCellStats.attr_cache_hits++;
    const tLow = tail.toLowerCase();
    const filtered = !tLow
      ? cached
      : cached.filter((o) => o.label.toLowerCase().includes(tLow));
    codeCellStats.completions_returned = filtered.length;
    codeCellStats.last_completion_ms = Math.round((performance.now() - t0) * 100) / 100;
    return {
      from: wordFrom + (wordText.lastIndexOf(".") + 1),
      options: filtered,
      validFor: /^\w*$/,
    };
  }

  if (isPython && host.codeIntel) {
    const extDefs = !isAttr && host.externalDefs ? host.externalDefs(notePath) : undefined;
    const res = await host.codeIntel({
      op: "complete",
      cells,
      cell_index: cellIndex,
      line: line1,
      col: col0,
      note: notePath || undefined,
      external_defs: extDefs,
    }).catch(() => null);
    for (const it of res?.items || []) {
      const label = String(it.label || "");
      if (!label || seen.has(label)) continue;
      seen.add(label);
      opts.push(makeOption(it, fenceOpenLine));
    }
    if (attrKey && opts.length && !tail) {
      clientAttrCache.set(attrKey, opts.slice());
      if (clientAttrCache.size > 128) {
        const firstKey = clientAttrCache.keys().next().value;
        if (firstKey !== undefined) clientAttrCache.delete(firstKey);
      }
    }
  }

  // G-450: NEVER pollute member attribute completions (`np.`) with top-level CPG nodes or buffer words (`import`, `numpy`)!
  const allowFallbackWords = !isAttr || !!(window as any).__domvecPlantPolluteDotCompletions;
  if (allowFallbackWords && tail.length >= 2) {
    const nodes = await host.codeNodes(tail).catch(() => []);
    for (const n of nodes) {
      const label = String(n.name || n.qname || "");
      if (!label || seen.has(label)) continue;
      seen.add(label);
      opts.push({
        label,
        detail: `${n.kind || "node"} ${n.qname || ""}`.trim(),
        type: n.kind === "class" ? "class" : n.kind === "function" ? "function" : "variable",
        boost: 2,
      });
    }
  }

  if (allowFallbackWords) {
    for (const m of docText.matchAll(/[A-Za-z_]\w{2,}/g)) {
      const w = m[0];
      if (w !== tail && !seen.has(w)) {
        seen.add(w);
        opts.push({ label: w, type: "text" });
      }
    }
  }

  codeCellStats.completions_returned = opts.length;
  codeCellStats.last_completion_ms = Math.round((performance.now() - t0) * 100) / 100;
  return {
    from: wordFrom + (wordText.lastIndexOf(".") + 1),
    options: opts,
    validFor: /^\w*$/,
  };
}

/** Fence-adaptive VS Code extensions for Obsidian's native markdown `EditorView` (`G-447`). */
export function fenceCodeExtensions(host: CodeCellHost): Extension[] {
  const R: any = require;
  const ac = R("@codemirror/autocomplete");
  const out: Extension[] = [fenceDiagField];

  // 1. Fence-scoped auto-suggest (Jedi + kernel stubs + CPG + cell symbols).
  const fenceCompletionSource = async (ctx: any) => {
    const fc = fenceAt(ctx.state, ctx.pos);
    if (!fc) return null;
    const lineObj = ctx.state.doc.lineAt(ctx.pos);
    const beforeLine = lineObj.text.slice(0, ctx.pos - lineObj.from);
    const w = ctx.matchBefore(/[\w.]+/);
    const afterImport = /\b(?:from\s+[\w.]*\s+import|import|from)\s+$/.test(beforeLine);
    if (!w && !afterImport && !ctx.explicit) return null;
    const wText = w ? w.text : "";
    const wFrom = w ? w.from : ctx.pos;
    if (!wText && !afterImport && !ctx.explicit) return null;
    return buildCompletions(
      host,
      fc.pyCells.join("\n") || fc.fence.body,
      fc.isPython ? fc.pyCells : [fc.fence.body],
      fc.isPython ? fc.pyCellIndex : 0,
      fc.cellLine,
      fc.col,
      wText,
      wFrom,
      fc.isPython,
      (ctx.view && host.noteOfView ? host.noteOfView(ctx.view) : ""),
      fc.fence.openLine,
    );
  };
  out.push(ac.autocompletion({ override: [fenceCompletionSource], activateOnTyping: true }));
  // Immediately open member completions when `.` is typed inside a Python fence (`np.` -> `array`, `zeros`, ...).
  out.push(EditorView.updateListener.of((u: ViewUpdate) => {
    if (!u.docChanged || (window as any).__domvecPlantNoFenceVscode) return;
    let typedDot = false;
    u.changes.iterChanges((_fA, _tA, _fB, _tB, inserted) => {
      if (inserted.toString() === ".") typedDot = true;
    });
    if (typedDot && fenceAt(u.state, u.state.selection.main.head)) {
      window.setTimeout(() => { try { ac.startCompletion?.(u.view); } catch { /* ignore */ } }, 0);
    }
  }));

  // 2. Go-to-definition (`Mod-click` or `F12`) inside a code fence.
  const gotoInFence = async (view: EditorView, pos: number): Promise<boolean> => {
    const fc = fenceAt(view.state, pos);
    if (!fc) return false;
    if (fc.isPython && host.codeIntel) {
      const got = await host.codeIntel({
        op: "goto",
        cells: fc.pyCells,
        cell_index: fc.pyCellIndex,
        line: fc.cellLine,
        col: fc.col,
      }).catch(() => null);
      const tgt = got?.target;
      if (tgt?.kind === "cell" && typeof tgt.cell_index === "number") {
        const destFence = fc.pyFences[tgt.cell_index];
        if (destFence) {
          const targetDocLine = Math.min(view.state.doc.lines, destFence.openLine + 1 + Math.max(1, Number(tgt.line || 1)));
          const ln = view.state.doc.line(targetDocLine);
          const anchor = Math.min(ln.to, ln.from + Math.max(0, Number(tgt.column || 0)));
          view.dispatch({ selection: { anchor }, scrollIntoView: true });
          codeCellStats.definitions_opened++;
          codeCellStats.cell_jumps++;
          codeCellStats.last_definition = `${tgt.name || "symbol"}@cell${tgt.cell_index}:L${tgt.line}`;
          return true;
        }
      }
      if (tgt?.url) {
        codeCellStats.definitions_opened++;
        codeCellStats.last_definition = String(tgt.name || tgt.url);
        host.openCode(String(tgt.url));
        return true;
      }
    }
    // Fallback to CPG `/code_nodes` lookup by identifier under `pos`.
    const line = view.state.doc.lineAt(pos), off = pos - line.from;
    let a = off, b = off;
    while (a > 0 && /[\w.]/.test(line.text[a - 1])) a--;
    while (b < line.text.length && /[\w.]/.test(line.text[b])) b++;
    const last = line.text.slice(a, b).split(".").pop() || "";
    if (!last) return false;
    const nodes = await host.codeNodes(last).catch(() => []);
    const hit = nodes.find((n: any) => n.name === last && /class|function|method/.test(String(n.kind)))
      || nodes.find((n: any) => n.name === last);
    if (!hit?.url) return false;
    codeCellStats.definitions_opened++;
    codeCellStats.last_definition = String(hit.qname || hit.name);
    host.openCode(String(hit.url));
    return true;
  };
  (codeCellStats as any).gotoInFence = gotoInFence;
  (codeCellStats as any).completeInFence = fenceCompletionSource;

  out.push(EditorView.domEventHandlers({
    mousedown: (e: MouseEvent, view: EditorView) => {
      if (!(e.ctrlKey || e.metaKey) || e.button !== 0) return false;
      const pos = view.posAtCoords({ x: e.clientX, y: e.clientY });
      if (pos == null || !fenceAt(view.state, pos)) return false;
      e.preventDefault();
      void gotoInFence(view, pos);
      return true;
    },
  }));

  // 3. Fence-scoped VS Code keymap (`Mod-/`, `Tab`, `Shift-Tab`, smart `Enter`, `F12`, auto-pairs).
  out.push(Prec.high(keymap.of([
    {
      key: "F12",
      run: (view: EditorView) => {
        const pos = view.state.selection.main.head;
        if (!fenceAt(view.state, pos)) return false;
        void gotoInFence(view, pos);
        return true;
      },
    },
    {
      key: "Mod-/",
      run: (view: EditorView) => {
        const sel = view.state.selection.main;
        const fcFrom = fenceAt(view.state, sel.from);
        const fcTo = fenceAt(view.state, sel.to);
        if (!fcFrom || !fcTo || fcFrom.fence.openLine !== fcTo.fence.openLine) return false;
        const lStart = view.state.doc.lineAt(sel.from).number;
        const lEnd = sel.to > sel.from && view.state.doc.lineAt(sel.to).from === sel.to
          ? view.state.doc.lineAt(sel.to).number - 1
          : view.state.doc.lineAt(sel.to).number;
        const rawLines: string[] = [];
        for (let ln = lStart; ln <= lEnd; ln++) rawLines.push(view.state.doc.line(ln).text);
        const nextLines = toggleLinesComment(rawLines, commentPrefixForLang(fcFrom.fence.lang));
        const fromPos = view.state.doc.line(lStart).from;
        const toPos = view.state.doc.line(lEnd).to;
        const inserted = nextLines.join("\n");
        view.dispatch({
          changes: { from: fromPos, to: toPos, insert: inserted },
          selection: { anchor: fromPos, head: fromPos + inserted.length },
        });
        codeCellStats.comments_toggled++;
        return true;
      },
    },
    {
      key: "Tab",
      run: (view: EditorView) => {
        if (ac.completionStatus?.(view.state) === "active" && ac.acceptCompletion?.(view)) return true;
        const sel = view.state.selection.main;
        const fc = fenceAt(view.state, sel.head);
        if (!fc) return false;
        if (sel.empty) {
          view.dispatch({
            changes: { from: sel.head, to: sel.head, insert: "    " },
            selection: { anchor: sel.head + 4 },
          });
          return true;
        }
        const lStart = view.state.doc.lineAt(sel.from).number;
        const lEnd = view.state.doc.lineAt(sel.to).number;
        const changes: { from: number; to: number; insert: string }[] = [];
        for (let ln = lStart; ln <= lEnd; ln++) {
          const line = view.state.doc.line(ln);
          changes.push({ from: line.from, to: line.from, insert: "    " });
        }
        view.dispatch({ changes });
        return true;
      },
    },
    {
      key: "Shift-Tab",
      run: (view: EditorView) => {
        const sel = view.state.selection.main;
        const fc = fenceAt(view.state, sel.head);
        if (!fc) return false;
        const lStart = view.state.doc.lineAt(sel.from).number;
        const lEnd = view.state.doc.lineAt(sel.to).number;
        const changes: { from: number; to: number; insert: string }[] = [];
        for (let ln = lStart; ln <= lEnd; ln++) {
          const line = view.state.doc.line(ln);
          const m = /^( {1,4}|\t)/.exec(line.text);
          if (m) changes.push({ from: line.from, to: line.from + m[0].length, insert: "" });
        }
        if (changes.length) view.dispatch({ changes });
        return true;
      },
    },
    {
      key: "Enter",
      run: (view: EditorView) => {
        if (ac.completionStatus?.(view.state) === "active" && ac.acceptCompletion?.(view)) return true;
        const sel = view.state.selection.main;
        if (!sel.empty) return false;
        const fc = fenceAt(view.state, sel.head);
        if (!fc) return false;
        const line = view.state.doc.lineAt(sel.head);
        const indent = nextLineIndent(line.text, sel.head - line.from, fc.fence.lang);
        const ins = "\n" + indent;
        view.dispatch({
          changes: { from: sel.head, to: sel.head, insert: ins },
          selection: { anchor: sel.head + ins.length },
          scrollIntoView: true,
        });
        return true;
      },
    },
  ])));

  // 4. Fence-scoped auto-closing brackets/quotes on character input.
  out.push(EditorView.inputHandler.of((view: EditorView, from: number, to: number, text: string) => {
    if (text.length !== 1) return false;
    const fc = fenceAt(view.state, from);
    if (!fc) return false;
    const nextChar = view.state.sliceDoc(to, to + 1);
    if (CLOSERS.has(text) && from === to && nextChar === text) {
      view.dispatch({ selection: { anchor: to + 1 } });
      return true;
    }
    const close = PAIRS[text];
    if (!close) return false;
    if (from !== to) {
      const wrapped = text + view.state.sliceDoc(from, to) + close;
      view.dispatch({
        changes: { from, to, insert: wrapped },
        selection: { anchor: from + 1, head: from + wrapped.length - 1 },
      });
      return true;
    }
    if (nextChar && !/[\s)\]};,:]/.test(nextChar)) return false;
    if ((text === '"' || text === "'") && from > 0 && /\w/.test(view.state.sliceDoc(from - 1, from))) return false;
    view.dispatch({
      changes: { from, to, insert: text + close },
      selection: { anchor: from + 1 },
    });
    return true;
  }));

  // 5. Signature help, symbol hover documentation, and inline syntax diagnostics.
  out.push(ViewPlugin.fromClass(class {
    private sigEl: HTMLElement | null = null;
    private hoverEl: HTMLElement | null = null;
    private sigTimer = 0;
    private diagTimer = 0;
    private hoverTimer = 0;
    private destroyed = false;
    private onMove: (e: MouseEvent) => void;
    private onLeave: () => void;

    constructor(private view: EditorView) {
      this.onMove = (e: MouseEvent) => this.scheduleHover(e.clientX, e.clientY);
      this.onLeave = () => this.hideHover();
      view.dom.addEventListener("mousemove", this.onMove);
      view.dom.addEventListener("mouseleave", this.onLeave);
      this.scheduleDiagnostics();
    }

    update(u: ViewUpdate) {
      if (u.docChanged || u.selectionSet) {
        this.hideHover();
        this.scheduleSignature();
      }
      if (u.docChanged) {
        this.scheduleDiagnostics();
      }
    }

    destroy() {
      this.destroyed = true;
      window.clearTimeout(this.sigTimer);
      window.clearTimeout(this.diagTimer);
      window.clearTimeout(this.hoverTimer);
      this.view.dom.removeEventListener("mousemove", this.onMove);
      this.view.dom.removeEventListener("mouseleave", this.onLeave);
      this.hideSig();
      this.hideHover();
    }

    private hideSig() { this.sigEl?.remove(); this.sigEl = null; }
    private hideHover() { window.clearTimeout(this.hoverTimer); this.hoverEl?.remove(); this.hoverEl = null; }

    private scheduleSignature() {
      window.clearTimeout(this.sigTimer);
      const state = this.view.state;
      const head = state.selection.main.head;
      const fc = fenceAt(state, head);
      if (!fc || !fc.isPython || !host.codeIntel) { this.hideSig(); return; }
      const ln = state.doc.lineAt(head);
      const before = ln.text.slice(0, head - ln.from);
      if (!before.includes("(") || /\)\s*$/.test(before)) { this.hideSig(); return; }
      this.sigTimer = window.setTimeout(() => void this.runSignature(), 140);
    }

    private async runSignature() {
      if (this.destroyed || !host.codeIntel) return;
      const head = this.view.state.selection.main.head;
      const fc = fenceAt(this.view.state, head);
      if (!fc || !fc.isPython) { this.hideSig(); return; }
      const got = await host.codeIntel({
        op: "signature",
        cells: fc.pyCells,
        cell_index: fc.pyCellIndex,
        line: fc.cellLine,
        col: fc.col,
      }).catch(() => null);
      if (this.destroyed) return;
      const sig = got?.signatures?.[0];
      if (!sig || !sig.name) { this.hideSig(); return; }
      const coords = this.view.coordsAtPos(head);
      if (!coords) { this.hideSig(); return; }
      if (!this.sigEl) this.sigEl = document.body.createDiv({ cls: "domvec-sig-tooltip" });
      this.sigEl.empty();
      const hd = this.sigEl.createDiv({ cls: "domvec-sig-head" });
      hd.appendText(sig.name + "(");
      (sig.params || []).forEach((p: string, idx: number) => {
        if (idx > 0) hd.appendText(", ");
        const sp = hd.createSpan({ text: p });
        if (idx === sig.index) sp.addClass("domvec-sig-active");
      });
      hd.appendText(")");
      if (sig.docstring) {
        this.sigEl.createDiv({ cls: "domvec-sig-doc", text: String(sig.docstring).split("\n").slice(0, 3).join("\n") });
      }
      this.sigEl.style.left = `${Math.max(8, Math.min(window.innerWidth - 360, Math.round(coords.left)))}px`;
      this.sigEl.style.top = `${Math.max(8, Math.round(coords.top - (this.sigEl.offsetHeight || 42) - 6))}px`;
      codeCellStats.signatures_shown++;
    }

    private scheduleHover(x: number, y: number) {
      window.clearTimeout(this.hoverTimer);
      if (!host.codeIntel || (window as any).__domvecPlantNoFenceVscode) return;
      const pos = this.view.posAtCoords({ x, y });
      if (pos == null) { this.hideHover(); return; }
      const fc = fenceAt(this.view.state, pos);
      if (!fc || !fc.isPython) { this.hideHover(); return; }
      this.hoverTimer = window.setTimeout(() => void this.runHover(pos, x, y), 350);
    }

    private async runHover(pos: number, x: number, y: number) {
      if (this.destroyed || !host.codeIntel) return;
      const fc = fenceAt(this.view.state, pos);
      if (!fc || !fc.isPython) return;
      const got = await host.codeIntel({
        op: "hover",
        cells: fc.pyCells,
        cell_index: fc.pyCellIndex,
        line: fc.cellLine,
        col: fc.col,
      }).catch(() => null);
      if (this.destroyed) return;
      const hv = got?.hover;
      if (!hv || (!hv.signature && !hv.docstring)) { this.hideHover(); return; }
      if (!this.hoverEl) this.hoverEl = document.body.createDiv({ cls: "domvec-hover-tooltip" });
      this.hoverEl.empty();
      this.hoverEl.createDiv({ cls: "domvec-hover-sig", text: hv.signature || `${hv.type || "symbol"} ${hv.name}` });
      if (hv.docstring) this.hoverEl.createDiv({ cls: "domvec-hover-doc", text: hv.docstring });
      this.hoverEl.style.left = `${Math.max(8, Math.min(window.innerWidth - 380, Math.round(x + 10)))}px`;
      this.hoverEl.style.top = `${Math.max(8, Math.min(window.innerHeight - 180, Math.round(y + 14)))}px`;
      codeCellStats.hovers_shown++;
    }

    private scheduleDiagnostics() {
      window.clearTimeout(this.diagTimer);
      if (!host.codeIntel) return;
      this.diagTimer = window.setTimeout(() => void this.runDiagnostics(), 550);
    }

    private async runDiagnostics() {
      if (this.destroyed || !host.codeIntel) return;
      if ((window as any).__domvecPlantNoFenceVscode) {
        this.view.dispatch({ effects: setFenceDiags.of([]) });
        return;
      }
      const text = this.view.state.doc.toString();
      const pyFences = findFences(text).filter((f) => isPythonLang(f.lang));
      if (!pyFences.length) return;
      const got = await host.codeIntel({ op: "diagnostics", cells: pyFences.map((f) => f.body) }).catch(() => null);
      if (this.destroyed || this.view.state.doc.toString() !== text) return;
      const marks: DiagRange[] = [];
      for (const d of got?.diagnostics || []) {
        const pf = pyFences[d.cell_index];
        if (!pf) continue;
        const docLineNum = pf.openLine + 1 + Math.max(1, Number(d.line || 1));
        if (docLineNum < 1 || docLineNum > this.view.state.doc.lines) continue;
        const ln = this.view.state.doc.line(docLineNum);
        const from = Math.min(ln.to, ln.from + Math.max(0, Number(d.col || 0)));
        const to = Math.min(ln.to, Math.max(from + 1, ln.from + Math.max(Number(d.end_col || 0), Number(d.col || 0) + 1)));
        if (to > from) marks.push({ from, to, message: String(d.message || "Syntax error") });
      }
      codeCellStats.diagnostics_drawn = marks.length;
      this.view.dispatch({ effects: setFenceDiags.of(marks) });
    }
  }));

  codeCellStats.fence_built++;
  return out;
}

/** Standalone `CodeView` extensions (`codeview.ts`), sharing the same `/code_intel` backend. */
export function codeCellExtensions(host: CodeCellHost): Extension[] {
  if ((window as any).__domvecPlantPlainCodeCell) return [];
  const R: any = require;
  const ac = R("@codemirror/autocomplete"), cmd = R("@codemirror/commands");
  const lang = R("@codemirror/language"), search = R("@codemirror/search");
  const out: Extension[] = [
    lineNumbers(), highlightActiveLineGutter(), highlightActiveLine(),
    lang.foldGutter(), lang.bracketMatching(), lang.indentOnInput(), lang.indentUnit.of("    "),
    ac.closeBrackets(), cmd.history(), search.highlightSelectionMatches(),
    lang.syntaxHighlighting(lang.defaultHighlightStyle, { fallback: true }),
  ];
  const cm5: any = (window as any).CodeMirror;
  const mode = cm5?.getMode?.({ indentUnit: 4 }, "python");
  if (mode && mode.name === "python") {
    out.push(lang.StreamLanguage.define({
      name: "python", startState: () => mode.startState(0), token: (s: any, st: any) => mode.token(s, st),
      languageData: { commentTokens: { line: "#" } },
    }));
    if (cm5.StringStream) out.push(cm5Highlight(cm5, mode));
  }
  const fromGraph = async (ctx: any) => {
    const w = ctx.matchBefore(/[\w.]+/);
    if (!w || (w.from === w.to && !ctx.explicit)) return null;
    const docText = ctx.state.doc.toString();
    const ln = ctx.state.doc.lineAt(ctx.pos);
    return buildCompletions(host, docText, [docText], 0, ln.number, ctx.pos - ln.from, w.text, w.from, true);
  };
  out.push(ac.autocompletion({ override: [fromGraph], activateOnTyping: true }));
  const gotoAt = async (view: EditorView, pos: number): Promise<boolean> => {
    const line = view.state.doc.lineAt(pos), off = pos - line.from;
    if (host.codeIntel) {
      const docText = view.state.doc.toString();
      const got = await host.codeIntel({ op: "goto", cells: [docText], cell_index: 0, line: line.number, col: off }).catch(() => null);
      const tgt = got?.target;
      if (tgt?.kind === "cell" && tgt.line) {
        const destLn = view.state.doc.line(Math.min(view.state.doc.lines, Math.max(1, Number(tgt.line))));
        view.dispatch({ selection: { anchor: destLn.from }, scrollIntoView: true });
        codeCellStats.definitions_opened++; codeCellStats.last_definition = String(tgt.name || "");
        return true;
      }
      if (tgt?.url) {
        codeCellStats.definitions_opened++; codeCellStats.last_definition = String(tgt.name || tgt.url);
        host.openCode(String(tgt.url));
        return true;
      }
    }
    let a = off, b = off;
    while (a > 0 && /[\w.]/.test(line.text[a - 1])) a--;
    while (b < line.text.length && /[\w.]/.test(line.text[b])) b++;
    const name = line.text.slice(a, b);
    if (!name) return false;
    const last = name.split(".").pop() || name;
    const nodes = await host.codeNodes(last).catch(() => []);
    const hit = nodes.find((n: any) => n.name === last && /class|function|method/.test(String(n.kind))) || nodes.find((n: any) => n.name === last);
    if (!hit?.url) return false;
    codeCellStats.definitions_opened++; codeCellStats.last_definition = String(hit.qname || hit.name);
    host.openCode(String(hit.url));
    return true;
  };
  out.push(EditorView.domEventHandlers({
    mousedown: (e: MouseEvent, view: EditorView) => {
      if (!(e.ctrlKey || e.metaKey)) return false;
      const pos = view.posAtCoords({ x: e.clientX, y: e.clientY });
      if (pos == null) return false;
      e.preventDefault(); void gotoAt(view, pos); return true;
    },
  }));
  out.push(keymap.of([
    { key: "F12", run: (v: EditorView) => { void gotoAt(v, v.state.selection.main.head); return true; } },
    { key: "Mod-/", run: cmd.toggleComment },
    ...ac.closeBracketsKeymap, ...ac.completionKeymap, ...cmd.historyKeymap,
    ...search.searchKeymap, ...lang.foldKeymap, cmd.indentWithTab, ...cmd.defaultKeymap,
  ]));
  (codeCellStats as any).gotoAt = gotoAt;
  codeCellStats.built++;
  return out;
}

const markCache = new Map<string, Decoration>();
function cm5Highlight(cm5: any, mode: any): Extension {
  const build = (view: EditorView): DecorationSet => {
    const b = new RangeSetBuilder<Decoration>();
    const doc = view.state.doc, last = view.visibleRanges.length ? view.visibleRanges[view.visibleRanges.length - 1].to : doc.length;
    const st = mode.startState(0);
    for (let i = 1; i <= doc.lines; i++) {
      const line = doc.line(i);
      if (line.from > last) break;
      const stream = new cm5.StringStream(line.text, 4);
      if (!line.text.length && mode.blankLine) mode.blankLine(st);
      while (!stream.eol()) {
        const style = mode.token(stream, st);
        if (stream.pos <= stream.start) { stream.pos++; continue; }
        if (style) {
          const cls = String(style).split(" ").map((x: string) => "cm-" + x).join(" ");
          let d = markCache.get(cls);
          if (!d) { d = Decoration.mark({ class: cls }); markCache.set(cls, d); }
          b.add(line.from + stream.start, line.from + stream.pos, d);
        }
        stream.start = stream.pos;
      }
    }
    return b.finish();
  };
  return ViewPlugin.fromClass(class {
    decorations: DecorationSet;
    constructor(view: EditorView) { this.decorations = build(view); }
    update(u: ViewUpdate) { if (u.docChanged || u.viewportChanged) this.decorations = build(u.view); }
  }, { decorations: (v: any) => v.decorations });
}
