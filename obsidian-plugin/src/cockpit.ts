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
import { FoldState, SlateLine, foldsOf, parseSlate, setFolds, titleLine } from "./slatefold";
export { parseSlate } from "./slatefold";
export type { SlateLine } from "./slatefold";

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
  T + "plan" + T + "{results}",
  T + "play" + T + "false",
  T + "search",
  T + T + "query" + T + "",
  T + T + "db" + T + "true",
  T + T + "duckduckgo" + T + "false",
  T + T + "k" + T + "8",
  T + T + "results" + T + "{results}",
  "",
].join("\n");

/** A slate's rank-1 lines (`refs.rank1` in Python): the title's first level
 *  of fields, `key<TAB>value` (a field with children shows as `{key}`); any
 *  other text, its first lines. */
export function rank1Of(text: string, limit = 12): string[] {
  const fs = parseSlate(text);
  const top = fs.filter((f) => f.depth === 0);
  if (top.length === 1) {
    const kids = fs.filter((f) => f.depth === 1).slice(0, limit);
    if (kids.length) return kids.map((f) => {
      const hasKids = fs.some((x) => x.depth === 2 && x.path[1] === f.key);
      const v = f.value || (hasKids ? "{" + f.key + "}" : "");
      return (f.key + (v ? "\t" + v : "")).slice(0, 120);
    });
  }
  const out: string[] = [];
  let body = text;
  if (body.startsWith("---")) { const e = body.indexOf("\n---", 3); if (e >= 0) body = body.slice(e + 4); }
  for (const line of body.split("\n")) {
    const t = line.trim();
    if (t && !/^(<!--|```|~~~|\||---)/.test(t)) out.push(t.replace(/^[#> ]+/, "").replace(/\t/g, " ").slice(0, 120));
    if (out.length >= limit) break;
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
  /** A `{ref}` resolved through the store, with its rank-1 lines. */
  ref(name: string): Promise<{ resolved: boolean; lines: string[]; cids?: string[]; url?: string } | null>;
}

export class Cockpit {
  stats = { applied: 0, wrote: 0, toggles: 0, slides: 0, row_hovers: 0, submits: 0, folds: 0, scroll_flown: 0, opened: 0 };
  /** Planted (G-283): the query compared with this slate's own memo, as before. */
  plantMemoQuery = false;
  /** Planted (G-280): the slate is text only -- nothing bound either way. */
  plantUnbound = false;
  /** The results internalized (true) or braced (false); kept across reloads. */
  resultsOpen = false;
  private writing = false;
  private playSeen = false;
  planStats = { resolved: -1 };
  private seenSlateQuery = "";
  private seenEngineQuery = "";
  private lastQuery = "";
  private lastSeen = { mode: "", throttle: -1, action: "", hitsKey: "", playing: false, query: "" };
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
    // A cockpit written before a field existed gains it (the plan, G-283).
    const text = await this.app.vault.read(f);
    if (!/^\tplan\t/m.test(text)) {
      await this.app.vault.modify(f, text.replace(/^(\tlast\t.*)$/m, "$1\n\tplan\t{results}\n\tplay\tfalse"));
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

  /** The slate class on every leaf whose note asks for it, the slate gestures
   *  on each (G-278), and the cockpit's own on the cockpit. */
  decorate(): void {
    for (const l of this.app.workspace.getLeavesOfType("markdown")) {
      const v: any = l.view;
      const on = isSlate(this.app, v?.file || null);
      (l as any).containerEl?.toggleClass?.("domvec-slate", on);
      if (on && v.contentEl && !this.slateHooked.has(v.contentEl)) this.hookSlate(v);
      if (on) this.restoreFolds(v);
      if (v?.file?.path === COCKPIT_PATH && v.contentEl && !this.hooked.has(v.contentEl)) this.hook(v);
    }
  }

  // ---- the slate gestures, on every slate note (G-278) ----------------------
  foldStats = { reveals: 0, folds: 0, collapses: 0, opens: 0, restored: 0, unresolved: 0, flips: 0 };
  /** Planted (G-281): a double-click on a slate flips nothing. */
  plantNoGraphForm = false;
  /** Double left-click: the slate flips between panel and graph form (G-281). */
  flipForm(v: any): boolean {
    if (this.plantNoGraphForm) return false;
    const cm = v?.editor?.cm, path = v?.file?.path;
    if (!cm || !path) return false;
    const cur = foldsOf(cm);
    const st: FoldState = { collapsed: false, reveals: { ...cur.reveals }, graph: !cur.graph };
    cm.dispatch({ effects: setFolds.of(st) });
    this.saveFolds(path, st);
    this.foldStats.flips++;
    return true;
  }
  /** Planted (G-280): `{keys}` resolves only inside the cockpit. */
  plantKeysCockpitOnly = false;
  /** Planted (G-278): right-clicks on a slate do nothing. */
  plantNoFolds = false;
  /** Planted (G-278): a note's rank-1 read from the store's rendered markdown, as first built. */
  plantRank1FromStore = false;
  private slateHooked = new WeakSet<HTMLElement>();
  private foldKey(path: string): string { return "domvec.slate.folds:" + path; }
  private loadFolds(path: string): FoldState {
    try { const s = JSON.parse(window.localStorage.getItem(this.foldKey(path)) || "null"); if (s && s.reveals) return s; } catch { /* a convenience */ }
    return { reveals: {}, collapsed: false };
  }
  private saveFolds(path: string, st: FoldState): void {
    try { window.localStorage.setItem(this.foldKey(path), JSON.stringify(st)); } catch { /* a convenience */ }
  }
  /** Put a note's kept fold state back on its editor -- whenever the editor
   *  holds none of it: Obsidian loads a note's text AFTER the leaf opens and
   *  replaces the editor state, so a restore at open was lost (G-278's check). */
  restoreFolds(v: any): void {
    const cm = v?.editor?.cm, path = v?.file?.path;
    if (!cm || !path) return;
    const st = this.loadFolds(path);
    if (!(Object.keys(st.reveals).length || st.collapsed || st.graph)) return;
    const cur = foldsOf(cm);
    if (Object.keys(cur.reveals).length || cur.collapsed || cur.graph) return;
    cm.dispatch({ effects: setFolds.of(st) });
    this.foldStats.restored++;
  }
  /** A `{ref}`'s rank-1 lines: the cockpit answers its own; a vault NOTE by
   *  its own text (the slate's record, through the slate grammar -- the
   *  store's rendered markdown leaked the frontmatter and flattened the tree);
   *  the store the rest (a page by title, else retrieval's top hit). */
  private async rank1(path: string, name: string): Promise<string[] | null> {
    const g = this.host.graph();
    // `{keys}` is the cockpit's sample stream, referenced from ANY node
    // (item 22: keys are "computation graph inputs to the sticked
    // node/panel dialect editor"): its current samples, newest first.
    if (name === "keys" && (path === COCKPIT_PATH || !this.plantKeysCockpitOnly)) return g?.agent?.keyLog?.length ? g.agent.keyLog.slice() : ["(no key yet)"];
    const want = name.trim().toLowerCase();
    const note = this.app.vault.getMarkdownFiles().find((f) => f.basename.toLowerCase() === want);
    if (note && !this.plantRank1FromStore) return rank1Of(await this.app.vault.cachedRead(note));
    const got = await this.host.ref(name);
    if (!got || !got.resolved) { this.foldStats.unresolved++; return null; }
    return got.lines;
  }
  /** A right-click on a slate: a `{ref}` internalized / folded, or the title collapsed / opened. */
  async slateGesture(v: any, x: number, y: number, target: HTMLElement | null): Promise<string> {
    if (this.plantNoFolds) return "planted";
    const cm = v?.editor?.cm, path = v?.file?.path;
    if (!cm || !path) return "none";
    const cur = foldsOf(cm);
    const st: FoldState = { collapsed: cur.collapsed, reveals: { ...cur.reveals } };
    if (target?.closest?.(".domvec-slate-circle")) {
      st.collapsed = false; this.foldStats.opens++;
    } else {
      const pos = cm.posAtCoords({ x, y });
      if (pos == null) return "none";
      const ln = cm.state.doc.lineAt(pos);
      const re = /\{([^}]+)\}/g;
      let m: RegExpExecArray | null, hit = "";
      while ((m = re.exec(ln.text))) { const a = ln.from + m.index, z = a + m[0].length; if (pos >= a && pos <= z) hit = m[1]; }
      if (hit && !(path === COCKPIT_PATH && hit === "results")) {
        if (hit in st.reveals) { delete st.reveals[hit]; this.foldStats.folds++; }
        else {
          const lines = await this.rank1(path, hit);
          if (!lines) return "unresolved";
          st.reveals[hit] = lines; this.foldStats.reveals++;
        }
      } else if (!hit && ln.number === titleLine(cm.state.doc)) {
        st.collapsed = true; this.foldStats.collapses++;
      } else return "none";
    }
    cm.dispatch({ effects: setFolds.of(st) });
    this.saveFolds(path, st);
    return "ok";
  }
  private hookSlate(v: any): void {
    const el: HTMLElement = v.contentEl;
    this.slateHooked.add(el);
    this.restoreFolds(v);
    el.addEventListener("contextmenu", (e: MouseEvent) => {
      const t = e.target as HTMLElement | null;
      const cm = v?.editor?.cm;
      if (!cm) return;
      // Only what is the slate's: a `{ref}`, the title, the circle.
      const pos = cm.posAtCoords({ x: e.clientX, y: e.clientY });
      const ln = pos != null ? cm.state.doc.lineAt(pos) : null;
      const onRef = ln ? /\{[^}]+\}/.test(ln.text) : false;
      const onTitle = ln ? ln.number === titleLine(cm.state.doc) : false;
      if (!(t?.closest?.(".domvec-slate-circle") || onRef || onTitle)) return;
      e.preventDefault(); e.stopPropagation();
      void this.slateGesture(v, e.clientX, e.clientY, t);
    }, true);
    el.addEventListener("dblclick", (e: MouseEvent) => {
      if (e.button !== 0) return;
      const t = e.target as HTMLElement | null;
      if (!t?.closest?.(".cm-content, .domvec-slate-graph")) return;
      if (this.flipForm(v)) { e.preventDefault(); e.stopPropagation(); }
    }, true);
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
    // The flight plan (G-283): `play` true flies the craft through `plan`'s
    // nodes -- `{results}`, the search's ranked targets -- at the throttle.
    const play = (this.field(fs, "play")?.value || "").trim() === "true";
    if (play && !a.playing && !this.playSeen) {
      const plan = (this.field(fs, "plan")?.value || "").trim();
      if (plan === "{results}" && g.searchState) { a.setPlan(g.searchState.targets.filter(Boolean)); a.play(true); }
      else {
        // Any other `{ref}`: its target through the store -- the plan flies
        // through its chunks' nodes, or its page's node when they are not
        // drawn (anchored nodes, items 8-9). Asynchronous; play starts when
        // the plan is known.
        const m = /^\{([^}]+)\}$/.exec(plan);
        if (m) void this.host.ref(m[1]).then((got: any) => {
          if (!got || !got.resolved) return;
          const ns = g.graph?.graphData?.().nodes || [];
          const byId = new Map<string, any>(ns.map((n: any) => [String(n.id), n]));
          const nodes = (got.cids || []).map((c: string) => byId.get(c)).filter(Boolean);
          if (!nodes.length && got.url && byId.get("page:" + got.url)) nodes.push(byId.get("page:" + got.url));
          this.planStats.resolved = nodes.length;
          a.setPlan(nodes); a.play(true);
        });
      }
    } else if (!play && a.playing) a.play(false);
    this.playSeen = play;
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
    // Against the ENGINE's query, not a memo of what this slate last sent:
    // another surface (the 3D field, a check) changing the search left the
    // slate believing its query still ran, and an edit back to it asked
    // nothing (2026-10-30, found by G-283). Planted `plantMemoQuery`.
    const current = this.plantMemoQuery ? this.lastQuery : f.query;
    this.seenSlateQuery = q;
    if (want !== current) {
      this.lastQuery = want;
      this.seenEngineQuery = want;
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

  /**
   * The halo's trigger (G-284; UR O.3): the cursor on a field of a STUCK slate
   * (any slate note but the cockpit, whose query already searches) that holds
   * literal text fires a halo of that text -- a field mixing text and `{ref}`s
   * asks with the ref names in place; a pure `{ref}` field fires none. Leaving
   * the field ends it.
   */
  haloStats = { asked: 0, ended: 0, last: "" };
  private haloQuery = "";
  private haloTick(): void {
    const g = this.host.graph();
    if (!g || typeof g.haloFor !== "function") return;
    const v: any = this.app.workspace.getActiveViewOfType(MarkdownView);
    let q = "";
    if (v && v.file && v.file.path !== COCKPIT_PATH && isSlate(this.app, v.file)) {
      const cur = v.editor.getCursor();
      const fl = parseSlate(v.editor.getValue()).find((f) => f.line === cur.line);
      const val = (fl?.value || "").trim();
      if (val && !/^\{[^}]+\}$/.test(val)) q = val.replace(/\{([^}]+)\}/g, "$1");
    }
    if (q === this.haloQuery) return;
    this.haloQuery = q;
    if (q) { this.haloStats.asked++; this.haloStats.last = q; void g.haloFor(q); }
    else { this.haloStats.ended++; g.haloEnd(); }
  }

  /** Once a frame or so: the agent's state and the results, into the text. */
  sync(): void {
    this.decorate();
    this.haloTick();
    const v = this.view(), g = this.host.graph();
    if (!v || !g || this.plantUnbound) return;
    this.decorate();
    const a = g.agent;
    const thr = Math.round(a.throttle * 100);
    if (a.mode === this.lastSeen.mode && thr === this.lastSeen.throttle && a.lastAction === this.lastSeen.action
        && this.hitsKey(g) === this.lastSeen.hitsKey && a.playing === this.lastSeen.playing
        && (g.searchField?.query ?? "") === this.lastSeen.query) return;
    let fs = parseSlate(v.editor.getValue());
    const put = (path: string[], value: string) => { const fl = this.field(fs, ...path); if (fl) { this.setValue(fl, value); fs = parseSlate(v.editor.getValue()); } };
    put(["view"], a.mode);
    put(["throttle"], String(thr));
    put(["last"], a.lastAction || "");
    // One record (item 37): whichever side changed LAST wins. A slate edit
    // not yet applied (Obsidian's editor-change can arrive after this tick)
    // is applied; only a query changed in the ENGINE (the 3D field) is
    // written back. Comparing the two alone overwrote the reader's edit.
    const f = g.searchField;
    const db = (this.field(fs, "search", "db")?.value || "").trim() !== "false";
    const sq = (this.field(fs, "search", "query")?.value || "").trim();
    if (f && db && !this.plantMemoQuery) {
      if (sq !== this.seenSlateQuery) { this.seenSlateQuery = sq; this.apply(fs); }
      else if (f.query !== sq && f.query !== this.seenEngineQuery) { put(["search", "query"], f.query); this.seenSlateQuery = f.query; }
      this.seenEngineQuery = f.query;
    }
    // A plan that finished, or a hand on the stick, sets `play` back to false.
    if (!a.playing && this.playSeen) { put(["play"], "false"); this.playSeen = false; }
    this.lastSeen = { mode: a.mode, throttle: thr, action: a.lastAction, hitsKey: this.hitsKey(g), playing: a.playing, query: g.searchField?.query ?? "" };
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
