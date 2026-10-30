/**
 * The cockpit is a NODE, not a HUD (G-280; RESERVOIR_DESIGN §6, §6b): one
 * `ego` slate -- a vault note in the slate class -- whose fields ARE the user
 * agent's state and the search's, bound both ways. And the slate class itself
 * for any note that asks for it (G-278's visual: black fill, silver border,
 * serif white, no chrome; UR S.4, BS §0).
 *
 * The reader's words: "these controls will be stickable components of the
 * computation graph in the UI panel that can be readily accessible always in
 * their 2D graph form, even if collapsed within the "ego" 2D node which
 * corresponds to the cockpit" (item 10); "Ctrl and shift on throttle should
 * also be more symbol/panel pure. Maybe no slider at all" (item 24); "search
 * input panel should be a part of the controls" (item 30); booleans
 * "toggleable boolean nodes and panel-fields when hovered ... Continuous
 * values get sliders too I guess" (item 33); "only rank-1 expansions on
 * clicked ancestor nodes" (item 36); "2D/3D representations are shared"
 * (item 37).
 *
 * So the slate's TEXT is the record (a slate is a note, §3.1). Editing a
 * field's value writes the agent or the search; the agent's own changes
 * (Shift/Ctrl, the last key) are written back into the text. Gestures are
 * local to the token under the pointer: a click on `true`/`false` toggles
 * it; a hover over a number offers the dialect's one slider; a right-click
 * on `{results}` internalizes / folds its rank-1 rows (fold state kept); a
 * hover over a result row flies the camera to its node; Ctrl+Enter on the
 * query line asks the web (through the browser cell) when `duckduckgo` is
 * true -- typing alone never reaches the web (item 107).
 */
import { App, MarkdownView, TFile } from "obsidian";

export const COCKPIT_PATH = "domvec/ego.md";
const FOLD_KEY = "domvec.cockpit.results";

const T = "\t";
export const COCKPIT_TEXT = [
  "---", "domvec: slate", "---",
  "ego",
  T + "view" + T + "ego",
  T + "throttle" + T + "25",
  T + "keys" + T + "{keys}",
  T + "last" + T + "",
  T + "search",
  T + T + "query" + T + "",
  T + T + "db" + T + "true",
  T + T + "duckduckgo" + T + "false",
  T + T + "k" + T + "8",
  T + T + "results" + T + "{results}",
  "",
].join("\n");

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

export function isSlate(app: App, file: TFile | null): boolean {
  if (!file) return false;
  const fm = app.metadataCache.getFileCache(file)?.frontmatter;
  return !!fm && String(fm.domvec || "") === "slate";
}

export interface CockpitHost {
  /** The 3D graph view (its agent and its search engine), if open. */
  graph(): any;
  /** Ask the browser cell's web search (the 3D search button's path). */
  webSearch(q: string): boolean;
}

export class Cockpit {
  stats = { applied: 0, wrote: 0, toggles: 0, slides: 0, row_hovers: 0, submits: 0, folds: 0, scroll_flown: 0, opened: 0 };
  /** Planted (G-280): the slate is text only -- nothing bound either way. */
  plantUnbound = false;
  /** The results internalized (true) or braced (false); kept across reloads. */
  resultsOpen = false;
  private writing = false;
  private lastQuery = "";
  private lastSeen = { mode: "", throttle: -1, action: "", hitsKey: "" };
  private slider: HTMLElement | null = null;
  private hoveredRow = -1;
  private frontRow = -1;
  private hooked = new WeakSet<HTMLElement>();

  constructor(private app: App, private host: CockpitHost) {
    try { this.resultsOpen = window.localStorage.getItem(FOLD_KEY) === "1"; } catch { /* a convenience */ }
  }

  file(): TFile | null {
    const f = this.app.vault.getAbstractFileByPath(COCKPIT_PATH);
    return f instanceof TFile ? f : null;
  }

  /** Open the cockpit, creating its note on first use, beside the graph. */
  async open(): Promise<MarkdownView | null> {
    let f = this.file();
    if (!f) {
      if (!this.app.vault.getAbstractFileByPath("domvec")) await this.app.vault.createFolder("domvec").catch(() => undefined);
      f = await this.app.vault.create(COCKPIT_PATH, COCKPIT_TEXT);
    }
    let leaf = this.leaf();
    if (!leaf) {
      leaf = this.app.workspace.getRightLeaf(false) || this.app.workspace.getLeaf("split");
      await leaf.openFile(f, { state: { mode: "source", source: false } } as any);
    }
    this.app.workspace.revealLeaf(leaf);
    this.stats.opened++;
    this.decorate();
    return leaf.view instanceof MarkdownView ? leaf.view : null;
  }

  leaf(): any {
    return this.app.workspace.getLeavesOfType("markdown").find((l: any) => l.view?.file?.path === COCKPIT_PATH) || null;
  }

  view(): MarkdownView | null {
    const l = this.leaf();
    return l && l.view instanceof MarkdownView ? l.view : null;
  }

  /** The slate class on every leaf whose note asks for it, and the cockpit's gestures on its own. */
  decorate(): void {
    for (const l of this.app.workspace.getLeavesOfType("markdown")) {
      const v: any = l.view;
      const on = isSlate(this.app, v?.file || null);
      (l as any).containerEl?.toggleClass?.("domvec-slate", on);
      if (v?.file?.path === COCKPIT_PATH && v.contentEl && !this.hooked.has(v.contentEl)) this.hook(v);
    }
  }

  /** The note's text changed: read the fields into the agent and the search. */
  onEdit(file: TFile | null): void {
    if (this.writing || !file || file.path !== COCKPIT_PATH) return;
    const v = this.view();
    if (!v) return;
    this.apply(parseSlate(v.editor.getValue()));
  }

  private field(fs: SlateLine[], ...path: string[]): SlateLine | undefined {
    const want = path.join("/");
    return fs.find((f) => f.path.join("/") === want || f.path.slice(1).join("/") === want);
  }

  apply(fs: SlateLine[]): void {
    const g = this.host.graph();
    if (!g || this.plantUnbound) return;
    this.stats.applied++;
    const a = g.agent;
    const view = this.field(fs, "view")?.value.trim();
    if ((view === "ego" || view === "map") && view !== a.mode) a.setMode(view);
    const thr = Number(this.field(fs, "throttle")?.value);
    if (Number.isFinite(thr) && Math.abs(thr / 100 - a.throttle) > 0.004) a.setThrottle(thr / 100);
    const f = g.searchField;
    if (!f) return;
    const k = Number(this.field(fs, "search", "k")?.value);
    if (Number.isFinite(k) && k >= 1 && k !== f.k) f.setK(k);
    const q = (this.field(fs, "search", "query")?.value || "").trim();
    const db = (this.field(fs, "search", "db")?.value || "").trim() !== "false";
    // The store's ranking is `db`. Off, the field shows nothing of the store.
    const want = db ? q : "";
    if (want !== this.lastQuery) {
      this.lastQuery = want;
      f.input.value = want;
      void f.run();
    }
  }

  /** Ctrl+Enter on the query: the web too, when `duckduckgo` is true. */
  submit(): boolean {
    const v = this.view();
    if (!v) return false;
    const fs = parseSlate(v.editor.getValue());
    const q = (this.field(fs, "search", "query")?.value || "").trim();
    const ddg = (this.field(fs, "search", "duckduckgo")?.value || "").trim() === "true";
    if (!q || !ddg) return false;
    this.stats.submits++;
    return this.host.webSearch(q);
  }

  /** Write one field's value back into the text (the agent's own changes). */
  private setValue(fl: SlateLine, value: string): void {
    const v = this.view();
    if (!v || fl.value === value) return;
    this.writing = true;
    try {
      v.editor.replaceRange(value, { line: fl.line, ch: fl.valueFrom }, { line: fl.line, ch: fl.valueFrom + fl.value.length });
      this.stats.wrote++;
    } finally { this.writing = false; }
  }

  /** Once a frame or so: the agent's state and the results, into the text. */
  sync(): void {
    const v = this.view(), g = this.host.graph();
    if (!v || !g || this.plantUnbound) return;
    this.decorate();
    const a = g.agent;
    const thr = Math.round(a.throttle * 100);
    if (a.mode === this.lastSeen.mode && thr === this.lastSeen.throttle && a.lastAction === this.lastSeen.action
        && this.hitsKey(g) === this.lastSeen.hitsKey) return;
    let fs = parseSlate(v.editor.getValue());
    const put = (path: string[], value: string) => { const fl = this.field(fs, ...path); if (fl) { this.setValue(fl, value); fs = parseSlate(v.editor.getValue()); } };
    put(["view"], a.mode);
    put(["throttle"], String(thr));
    put(["last"], a.lastAction || "");
    this.lastSeen = { mode: a.mode, throttle: thr, action: a.lastAction, hitsKey: this.hitsKey(g) };
    this.writeResults();
  }

  private hitsKey(g: any): string {
    const f = g?.searchField;
    return (this.resultsOpen ? "1" : "0") + (f ? f.window.map((h: any) => h.cid).join("|") : "");
  }

  /** The results' rank-1 rows under `{results}` when internalized; none when folded. */
  private writeResults(): void {
    const v = this.view(), g = this.host.graph();
    if (!v || !g) return;
    const fs = parseSlate(v.editor.getValue());
    const res = this.field(fs, "search", "results");
    if (!res) return;
    // The rows already under it: every deeper line until the next at its depth or shallower.
    let end = res.line;
    for (const f of fs) if (f.line > res.line) { if (f.depth <= res.depth) break; end = f.line; }
    const f = g.searchField;
    const label = (h: any) => (f.labelOf ? f.labelOf(h) : h.url).replace(/[\t\n]+/g, " ");
    const indent = T.repeat(res.depth + 1);
    const rows = this.resultsOpen && f ? f.window.map((h: any, i: number) => indent + String(i + 1) + T + label(h)) : [];
    const lines = v.editor.getValue().split("\n");
    const have = lines.slice(res.line + 1, end + 1);
    if (have.join("\n") === rows.join("\n")) return;
    this.writing = true;
    try {
      const from = { line: res.line, ch: lines[res.line].length };
      const to = { line: end, ch: lines[end].length };
      v.editor.replaceRange(rows.length ? "\n" + rows.join("\n") : "", from, to);
      this.stats.wrote++;
    } finally { this.writing = false; }
  }

  /** Right-click on `{results}`: internalize / fold (rank-1 only, item 36). */
  toggleResults(): void {
    this.resultsOpen = !this.resultsOpen;
    this.stats.folds++;
    try { window.localStorage.setItem(FOLD_KEY, this.resultsOpen ? "1" : "0"); } catch { /* a convenience */ }
    this.lastSeen.hitsKey = "";
    this.writeResults();
  }

  /** The field under a screen point, and whether the point is on its value. */
  fieldAt(x: number, y: number): { fl: SlateLine; onValue: boolean; onRef: string } | null {
    const v: any = this.view();
    const cm = v?.editor?.cm;
    if (!cm) return null;
    const pos = cm.posAtCoords({ x, y });
    if (pos == null) return null;
    const ln = cm.state.doc.lineAt(pos);
    const fs = parseSlate(v.editor.getValue());
    const fl = fs.find((f) => f.line === ln.number - 1);
    if (!fl) return null;
    const ch = pos - ln.from;
    const onValue = ch >= fl.valueFrom && fl.value.length > 0 && ch <= fl.valueFrom + fl.value.length;
    const ref = /\{([^}]*)\}/.exec(fl.value);
    return { fl, onValue, onRef: onValue && ref ? ref[1] : "" };
  }

  /** The search's result rows, as field lines with their rank (1-based). */
  resultRows(): { fl: SlateLine; rank: number }[] {
    const v = this.view();
    if (!v) return [];
    const fs = parseSlate(v.editor.getValue());
    const res = this.field(fs, "search", "results");
    if (!res) return [];
    const out: { fl: SlateLine; rank: number }[] = [];
    for (const f of fs) {
      if (f.line <= res.line) continue;
      if (f.depth <= res.depth) break;
      const r = Number(f.key);
      if (Number.isInteger(r) && r >= 1) out.push({ fl: f, rank: r });
    }
    return out;
  }

  /** Toggle a boolean field (click on its value). */
  toggle(fl: SlateLine): boolean {
    const val = fl.value.trim();
    if (val !== "true" && val !== "false") return false;
    const v = this.view();
    if (!v) return false;
    this.stats.toggles++;
    v.editor.replaceRange(val === "true" ? "false" : "true", { line: fl.line, ch: fl.valueFrom }, { line: fl.line, ch: fl.valueFrom + fl.value.length });
    return true;
  }

  /** A number field's value set (the slider). */
  slide(fl: SlateLine, n: number): void {
    const v = this.view();
    if (!v) return;
    this.stats.slides++;
    v.editor.replaceRange(String(n), { line: fl.line, ch: fl.valueFrom }, { line: fl.line, ch: fl.valueFrom + fl.value.length });
  }

  /** A result row hovered (rank 1-based) or left (0): the hover's own path in 3D. */
  hoverRow(rank: number): void {
    const g = this.host.graph();
    const f = g?.searchField;
    if (!f) return;
    if (rank === this.hoveredRow) return;
    this.hoveredRow = rank;
    if (rank > 0) { const h = f.window[rank - 1]; if (h) { this.stats.row_hovers++; f.onHoverHit(h); } }
    else f.onHoverHit(null);
  }

  /** With no row hovered, the top-most result row in view of the slate's scroll is flown to (item 31). */
  scrolled(): void {
    if (this.hoveredRow > 0) return;
    const v: any = this.view(), g = this.host.graph();
    const cm = v?.editor?.cm;
    if (!cm || !g?.searchState) return;
    const top = cm.scrollDOM.getBoundingClientRect().top;
    const row = this.resultRows().find((r) => {
      const c = cm.coordsAtPos(cm.state.doc.line(r.fl.line + 1).from);
      return c && c.top >= top;
    });
    if (!row || row.rank === this.frontRow) return;
    this.frontRow = row.rank;
    const n = g.searchState.targets[row.rank - 1];
    if (n) { this.stats.scroll_flown++; g.focusOn(n); }
  }

  private hook(v: any): void {
    const el: HTMLElement = v.contentEl;
    this.hooked.add(el);
    el.addEventListener("mousedown", (e: MouseEvent) => {
      const at = this.fieldAt(e.clientX, e.clientY);
      if (!at) return;
      if (e.button === 0 && at.onValue && this.toggle(at.fl)) { e.preventDefault(); return; }
      if (e.button === 2 && at.onRef === "results") { e.preventDefault(); e.stopPropagation(); this.toggleResults(); }
    }, true);
    el.addEventListener("contextmenu", (e: MouseEvent) => {
      const at = this.fieldAt(e.clientX, e.clientY);
      if (at && at.onRef) { e.preventDefault(); e.stopPropagation(); }
    }, true);
    el.addEventListener("mousemove", (e: MouseEvent) => {
      const at = this.fieldAt(e.clientX, e.clientY);
      const row = at ? this.resultRows().find((r) => r.fl.line === at.fl.line) : undefined;
      this.hoverRow(row ? row.rank : 0);
      if (at && at.onValue && /^-?\d+(\.\d+)?$/.test(at.fl.value.trim())) this.showSlider(at.fl, e);
      else if (this.slider) { this.slider.remove(); this.slider = null; }
    });
    el.addEventListener("mouseleave", () => { this.hoverRow(0); });
    el.addEventListener("keydown", (e: KeyboardEvent) => {
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
        const cur = v.editor.getCursor();
        const fl = parseSlate(v.editor.getValue()).find((f) => f.line === cur.line);
        if (fl && fl.key === "query") { e.preventDefault(); e.stopPropagation(); this.submit(); }
      }
    }, true);
    v.editor?.cm?.scrollDOM?.addEventListener("scroll", () => this.scrolled(), { passive: true });
  }

  /** The dialect's one slider: over a number's value while hovered, gone when left. */
  private showSlider(fl: SlateLine, e: MouseEvent): void {
    const v: any = this.view();
    if (!v) return;
    const range: Record<string, [number, number]> = { throttle: [0, 100], k: [1, 50] };
    const [lo, hi] = range[fl.key] || [0, Math.max(10, Number(fl.value) * 2)];
    if (!this.slider) {
      this.slider = document.body.createDiv({ cls: "domvec-slate-slider" });
      this.slider.addEventListener("mouseleave", () => { this.slider?.remove(); this.slider = null; });
    }
    const s = this.slider;
    s.empty();
    const input = s.createEl("input", { type: "range" });
    input.min = String(lo); input.max = String(hi); input.step = "1"; input.value = String(Number(fl.value));
    input.oninput = () => {
      const fresh = parseSlate(v.editor.getValue()).find((f) => f.line === fl.line);
      if (fresh) this.slide(fresh, Number(input.value));
    };
    s.style.left = `${Math.round(e.clientX - 60)}px`;
    s.style.top = `${Math.round(e.clientY - 34)}px`;
  }

  unload(): void { this.slider?.remove(); this.slider = null; }
}
