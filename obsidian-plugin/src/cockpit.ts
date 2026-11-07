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
import { makeDraggable, type PlaceStats } from "./planecard";
export { parseSlate } from "./slatefold";
export type { SlateLine } from "./slatefold";

export const COCKPIT_PATH = "domvec/ego.md";
/** Remembered: the cockpit lives on the plane (items 52-53). */
const DOCKED_KEY = "domvec-cockpit-on-plane";
const FOLD_KEY = "domvec.cockpit.results";

const T = "\t";
export const COCKPIT_TEXT = [
  "---", "domvec: slate", "---",
  "ego",
  T + "view" + T + "ego",
  T + "throttle" + T + "25",
  T + "keys" + T + "{keys}",
  T + "last" + T + "",
  T + "plan" + T + "{search.results}",
  T + "play" + T + "false",
  T + "search",
  T + T + "query" + T + "",
  T + T + "db" + T + "true",
  T + T + "duckduckgo" + T + "false",
  T + T + "where" + T + "all",
  T + T + "k" + T + "8",
  T + T + "results",
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

/** A notebook: a note with code cells that is not itself a slate. */
export function isNotebook(app: App, file: TFile | null): boolean {
  if (!file || file.extension !== "md") return false;
  const c = app.metadataCache.getFileCache(file);
  return !!c?.sections?.some((x: any) => x.type === "code");
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
      await this.app.vault.modify(f, text.replace(/^(\tlast\t.*)$/m, "$1\n\tplan\t{search.results}\n\tplay\tfalse"));
    }
    // On the 2D plane over the 3D view when a graph is open (items 50, 52-53).
    const onPlane = await this.dock();
    if (onPlane) { this.stats.opened++; return onPlane; }
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

  /**
   * The cockpit STUCK on the 2D plane over the 3D graph (PLUGIN_GOAL 52-53,
   * 2026-11-01: "The current ego control panel is detached from the 2D
   * computation graph plane overtop of the 3D graph editor"). The same note in
   * the same native editor -- every slate gesture, the sync both ways -- held
   * in a leaf outside the workspace's tree (as the notebook's browser cell
   * is), in a card on the plane; its title folds it to the ego node's circle
   * and back. A sidebar copy is closed: one cockpit. Planted `plantSidebar`:
   * the cockpit stays a sidebar note.
   */
  planeLeaf: any = null;
  card: HTMLElement | null = null;
  plantSidebar = false;
  dockStats = { docked: 0, undocked_sidebar: 0 };
  async dock(): Promise<MarkdownView | null> {
    if (this.plantSidebar) return null;
    const g = this.host.graph();
    const plane: HTMLElement | null = g && typeof g.plane === "function" ? g.plane() : null;
    const f = this.file();
    if (!plane || !f) return null;
    await this.migrateModule(f);
    if (this.planeLeaf && this.card && plane.contains(this.card) && this.planeLeaf.view?.file?.path === COCKPIT_PATH) {
      this.card.removeClass("is-collapsed");
      return this.planeLeaf.view instanceof MarkdownView ? this.planeLeaf.view : null;
    }
    this.undock();
    // ONE ego card. A plugin reload makes a new cockpit while the plane
    // outlives the old one, and each reload left its ego card behind -- the
    // plane filled with stacked copies (2026-11-07, the reader's screenshot).
    // Planted `__domvecPlantKeepOrphans`: left, as before.
    if (!(window as any).__domvecPlantKeepOrphans) for (const old of Array.from(plane.querySelectorAll(".domvec-cockpit-card"))) old.remove();
    const Leaf = (this.app.workspace as any).activeLeaf?.constructor ?? (this.app.workspace.getMostRecentLeaf() as any)?.constructor;
    if (!Leaf) return null;
    // No head of its own (item 54: "the duplicative "ego" part should
    // actually be fused"): open, the header node is the slate's own title
    // line; minimized -- the slate's own collapse, a right-click on that
    // title -- the card is that node alone (`syncCard`).
    const card = plane.createDiv({ cls: "domvec-plane-card domvec-cockpit-card" });
    const leaf = new Leaf(this.app);
    card.appendChild(leaf.containerEl);
    await leaf.openFile(f, { state: { mode: "source", source: false } });
    this.planeLeaf = leaf;
    this.card = card;
    // Draggable by its header node, contained in the plane (item 57).
    this.undrag = makeDraggable(card, plane, "domvec-plane-card:ego", this.placeStats);
    // One cockpit: the sidebar's copy goes.
    for (const l of this.app.workspace.getLeavesOfType("markdown")) {
      if ((l.view as any)?.file?.path === COCKPIT_PATH) { l.detach(); this.dockStats.undocked_sidebar++; }
    }
    this.dockStats.docked++;
    try { window.localStorage.setItem(DOCKED_KEY, "1"); } catch { /* a convenience */ }
    this.decorate();
    return leaf.view instanceof MarkdownView ? leaf.view : null;
  }

  /** The card minimized exactly when its slate is collapsed to the header node. */
  syncCard(): void {
    if (!this.card || !this.planeLeaf) return;
    this.card.toggleClass("is-collapsed", !!this.planeLeaf.containerEl.querySelector(".domvec-slate-circle"));
  }

  /** The cockpit's `search/results` field. */
  isResultsField(fl: SlateLine): boolean { return fl.key === "results" && fl.path.includes("search"); }

  /** The cockpit's slate as the Python module it is (PLUGIN_GOAL 62): its
   *  first form bound `results {results}` (a name defined as itself) and
   *  `plan {results}` (nothing at module scope by that name). Rewritten once
   *  to the dotted reference and a plain field; the rows go beneath it. */
  async migrateModule(f: TFile): Promise<boolean> {
    const text = await this.app.vault.read(f);
    let next = text.replace(/^(\tplan\t)\{results\}\s*$/m, "$1{search.results}").replace(/^(\t\tresults)\t\{results\}\s*$/m, "$1");
    // The search's `where` (item 78), written once into a cockpit made before it.
    if (!/^\t\twhere\t/m.test(next)) next = next.replace(/^(\t\tduckduckgo\t.*)$/m, "$1\n\t\twhere\tall");
    if (next === text) return false;
    await this.app.vault.modify(f, next);
    return true;
  }

  /** Off the plane (its graph closed, or the plugin unloading). */
  placeStats: PlaceStats = { drags: 0, clamped: 0 };
  private undrag: (() => void) | null = null;
  undock(): void {
    this.undrag?.(); this.undrag = null;
    try { this.planeLeaf?.detach(); } catch { /* gone */ }
    this.card?.remove();
    this.planeLeaf = null;
    this.card = null;
  }

  leaf(): any {
    if (this.planeLeaf && this.card?.isConnected && this.planeLeaf.view?.file?.path === COCKPIT_PATH) return this.planeLeaf;
    return this.app.workspace.getLeavesOfType("markdown").find((l: any) => l.view?.file?.path === COCKPIT_PATH) || null;
  }

  view(): MarkdownView | null {
    const l = this.leaf();
    return l && l.view instanceof MarkdownView ? l.view : null;
  }

  /** The slate class on every leaf whose note asks for it, the slate gestures
   *  on each (G-278), and the cockpit's own on the cockpit. */
  decorate(): void {
    const leaves: any[] = this.app.workspace.getLeavesOfType("markdown");
    if (this.planeLeaf && this.card?.isConnected) leaves.push(this.planeLeaf);
    // The plane's other panels (PLUGIN_GOAL 65): a slate there is a slate.
    for (const l of (window as any).__domvecPlane?.leaves?.() || []) if (!leaves.includes(l)) leaves.push(l);
    for (const l of leaves) {
      const v: any = l.view;
      const on = isSlate(this.app, v?.file || null);
      (l as any).containerEl?.toggleClass?.("domvec-slate", on);
      // A NOTEBOOK's markdown is a slate (PLUGIN_GOAL 131-132: "the slate is
      // the markdown part of the notebook"): its lines outside the code fences
      // take the slate's form and gestures; the fences stay cells. Planted
      // `__domvecPlantNotebookPlain`: notebooks' markdown plain, as before.
      const nb = !on && isNotebook(this.app, v?.file || null) && !(window as any).__domvecPlantNotebookPlain;
      (l as any).containerEl?.toggleClass?.("domvec-nb-slate", nb);
      if ((on || nb) && v.contentEl && !this.slateHooked.has(v.contentEl)) this.hookSlate(v);
      if (on) this.restoreFolds(v);
      if (v?.file?.path === COCKPIT_PATH && v.contentEl && !this.hooked.has(v.contentEl)) this.hook(v);
    }
  }

  // ---- the slate gestures, on every slate note (G-278) ----------------------
  foldStats = { reveals: 0, folds: 0, collapses: 0, opens: 0, restored: 0, unresolved: 0, flips: 0,
                field_folds: 0, field_unfolds: 0, node_to_panel: 0 };
  /** Planted (G-281): a double-click on a slate flips nothing. */
  plantNoGraphForm = false;
  /** Double left-click: the slate flips between panel and graph form (G-281). */
  flipForm(v: any): boolean {
    if (this.plantNoGraphForm) return false;
    const cm = v?.editor?.cm, path = v?.file?.path;
    if (!cm || !path) return false;
    const cur = foldsOf(cm);
    // The SAME record, the other form: reveals and folds carried whole.
    const st: FoldState = { ...this.copyFolds(cur), collapsed: false, graph: !cur.graph };
    cm.dispatch({ effects: setFolds.of(st) });
    this.saveFolds(path, st);
    this.foldStats.flips++;
    return true;
  }

  /** A fold state copied whole -- every gesture starts from all of it (a
   *  right-click once rebuilt it from two fields and dropped the graph flag). */
  private copyFolds(cur: FoldState): FoldState {
    return { collapsed: cur.collapsed, graph: cur.graph, reveals: { ...cur.reveals }, folds: [...(cur.folds || [])] };
  }

  /** Fold or unfold a field's rank-1 children (mortegon 7.3.4, M.6): its name
   *  braced and its subtree hidden in BOTH forms; per-subtree state kept. */
  toggleFieldFold(v: any, fieldPath: string, open?: boolean): boolean {
    const cm = v?.editor?.cm, path = v?.file?.path;
    if (!cm || !path || this.plantNoFolds) return false;
    const st = this.copyFolds(foldsOf(cm));
    const folds = new Set(st.folds);
    const fold = open === undefined ? !folds.has(fieldPath) : !open;
    if (fold) folds.add(fieldPath); else folds.delete(fieldPath);
    st.folds = [...folds];
    cm.dispatch({ effects: setFolds.of(st) });
    this.saveFolds(path, st);
    if (fold) this.foldStats.field_folds++; else this.foldStats.field_unfolds++;
    return true;
  }

  /** The field on a doc line (1-based), and whether it has children. */
  private fieldAtLine(cm: any, lineNo: number): { path: string; hasKids: boolean } | null {
    const fs = parseSlate(cm.state.doc.toString());
    const i = fs.findIndex((f) => f.line + 1 === lineNo);
    if (i < 0) return null;
    return { path: fs[i].path.join("/"), hasKids: i + 1 < fs.length && fs[i + 1].depth > fs[i].depth };
  }

  /** The graph form's gestures, said once for both forms (`GraphWidget`). */
  private async graphGesture(v: any, d: { kind: string; path: string; ref: string; line: number; folded: boolean }): Promise<void> {
    const cm = v?.editor?.cm;
    if (!cm) return;
    const f = this.fieldAtLine(cm, d.line + 1);
    if (d.kind === "right") {
      if (f && (f.hasKids || d.folded)) { this.toggleFieldFold(v, d.path); return; }
      if (d.ref) await this.toggleReveal(v, d.ref);
    } else if (d.kind === "unfold") {
      this.toggleFieldFold(v, d.path, true);
    } else if (d.kind === "panel") {
      // A graph node opens its containment panel: panel form, the cursor on it.
      if (this.flipForm(v)) {
        const ln = cm.state.doc.line(Math.min(d.line + 1, cm.state.doc.lines));
        cm.dispatch({ selection: { anchor: ln.from }, scrollIntoView: true });
        this.foldStats.node_to_panel++;
      }
    }
  }

  /** Reveal / fold a `{ref}`'s rank-1 lines (the right-click on a reference). */
  async toggleReveal(v: any, name: string): Promise<string> {
    const cm = v?.editor?.cm, path = v?.file?.path;
    if (!cm || !path || this.plantNoFolds) return "none";
    const st = this.copyFolds(foldsOf(cm));
    if (name in st.reveals) { delete st.reveals[name]; this.foldStats.folds++; }
    else {
      const lines = await this.rank1(path, name);
      if (!lines) return "unresolved";
      st.reveals[name] = lines; this.foldStats.reveals++;
    }
    cm.dispatch({ effects: setFolds.of(st) });
    this.saveFolds(path, st);
    return "ok";
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
    if (!(Object.keys(st.reveals).length || st.collapsed || st.graph || (st.folds || []).length)) return;
    const cur = foldsOf(cm);
    if (Object.keys(cur.reveals).length || cur.collapsed || cur.graph || (cur.folds || []).length) return;
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
    const st: FoldState = this.copyFolds(cur);
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
      } else if (!hit) {
        // A field with rank-1 children: its fold toggles (braced, subtree hidden).
        const f = this.fieldAtLine(cm, ln.number);
        if (!f || !f.hasKids) return "none";
        return this.toggleFieldFold(v, f.path) ? "ok" : "none";
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
      // A `{ref}` INSIDE a revealed box: the next rank of the black box opened,
      // or folded again (PLUGIN_GOAL 80) -- the same reveal state, by name.
      const inner = t?.closest?.(".domvec-slate-reveal-ref") as HTMLElement | null;
      if (inner && inner.dataset.ref) {
        e.preventDefault(); e.stopPropagation();
        void this.toggleReveal(v, inner.dataset.ref);
        return;
      }
      // Only what is the slate's: a `{ref}`, the title, the circle.
      const pos = cm.posAtCoords({ x: e.clientX, y: e.clientY });
      const ln = pos != null ? cm.state.doc.lineAt(pos) : null;
      const onRef = ln ? /\{[^}]+\}/.test(ln.text) : false;
      const onTitle = ln ? ln.number === titleLine(cm.state.doc) : false;
      const atLine = ln ? this.fieldAtLine(cm, ln.number) : null;
      const onFoldable = !!atLine?.hasKids && !(v?.file?.path === COCKPIT_PATH && /\/search\/results$/.test(atLine.path));
      if (t?.closest?.(".domvec-slate-graph")) return;    // the graph says its own (below)
      if (!(t?.closest?.(".domvec-slate-circle") || onRef || onTitle || onFoldable)) return;
      e.preventDefault(); e.stopPropagation();
      void this.slateGesture(v, e.clientX, e.clientY, t);
    }, true);
    // The graph form's gestures (`GraphWidget`): the same fold state.
    el.addEventListener("domvec-slate-graph", (e: Event) => { void this.graphGesture(v, (e as CustomEvent).detail); });
    el.addEventListener("dblclick", (e: MouseEvent) => {
      if (e.button !== 0) return;
      const t = e.target as HTMLElement | null;
      if (!t?.closest?.(".cm-content, .domvec-slate-graph")) return;
      // On a graph NODE the graph says it itself: that node's containment
      // panel, the cursor on it (7.3.4) -- not a bare flip.
      if (t.closest(".domvec-slate-graph") && (t as Element).getAttribute?.("data-path") != null) return;
      if (this.flipForm(v)) { e.preventDefault(); e.stopPropagation(); }
    }, true);
  }

  /** The note's text changed: read the fields into the agent and the search. */
  onEdit(file: TFile | null): void {
    if (this.writing || !file || file.path !== COCKPIT_PATH) return;
    const v = this.view();
    if (!v) return;
    this.apply(parseSlate(v.editor.getValue()));
    // The text and the agent agree now: that is what sync has SEEN. Without
    // this, an edit (throttle 30) followed by the agent returning to the value
    // sync last saw (55) read as "nothing changed", and the card kept saying
    // 30 while the craft flew at 55 (found live, 2026-11-01). Planted
    // `plantStaleSeen`.
    const g = this.host.graph();
    if (g && !this.plantStaleSeen) {
      const a = g.agent;
      this.lastSeen = { ...this.lastSeen, mode: a.mode, throttle: Math.round(a.throttle * 100), action: a.lastAction, playing: a.playing };
    }
  }
  /** Planted: an applied edit leaves sync's memory of the agent as it was. */
  plantStaleSeen = false;

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
      if ((plan === "{search.results}" || plan === "{results}") && g.searchState) { a.setPlan(g.searchState.targets.filter(Boolean)); a.play(true); }
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
    // Ego or web (item 78): the search's `where`, a three-state field.
    const where = (this.field(fs, "search", "where")?.value || "").trim();
    if (typeof g.setSearchWhere === "function" && g.setSearchWhere(where) && f.input.value.trim()) void f.run();
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
    const pl: any = (this.app as any).plugins?.getPlugin?.("domvec-bridge");
    const v: any = pl?.activeView ? pl.activeView() : this.app.workspace.getActiveViewOfType(MarkdownView);
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
  private dockCheckAt = 0;
  sync(): void {
    // A cockpit open in the sidebar (a restored layout), or one whose card a
    // rebuilt graph dropped, goes (back) onto the plane -- checked every 2 s.
    const now = Date.now();
    if (!this.plantSidebar && now - this.dockCheckAt > 2000) {
      this.dockCheckAt = now;
      const inSidebar = this.app.workspace.getLeavesOfType("markdown").some((l: any) => l.view?.file?.path === COCKPIT_PATH);
      // Lost to a rebuilt graph, or to a reload of the plugin or the app: the
      // cockpit LIVES on the plane, and that is remembered (a reload once
      // left no cockpit anywhere, its sidebar copy having been closed).
      let remembered = false;
      try { remembered = window.localStorage.getItem(DOCKED_KEY) === "1"; } catch { /* a convenience */ }
      const lost = (!!this.planeLeaf || remembered) && !this.card?.isConnected;
      const g = this.host.graph();
      if ((inSidebar || lost) && g && typeof g.plane === "function" && g.plane()) void this.dock();
    }
    this.decorate();
    this.syncCard();
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
      // The results FIELD (item 62: `results {results}` defined itself): its
      // rows are its children, opened and folded by a right-click on it.
      if (e.button === 2 && (at.onRef === "results" || this.isResultsField(at.fl))) { e.preventDefault(); e.stopPropagation(); this.toggleResults(); }
    }, true);
    el.addEventListener("contextmenu", (e: MouseEvent) => {
      const at = this.fieldAt(e.clientX, e.clientY);
      if (at && (at.onRef || this.isResultsField(at.fl))) { e.preventDefault(); e.stopPropagation(); }
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
  /** The detected range of a continuous field (item 106): the named ones as
   *  they are; a fraction 0..1; else up to the value's next power of ten
   *  (symmetric about zero for a negative one). */
  static rangeOf(key: string, value: number): { lo: number; hi: number; step: number } {
    const named: Record<string, [number, number]> = { throttle: [0, 100], k: [1, 50] };
    if (named[key]) return { lo: named[key][0], hi: named[key][1], step: 1 };
    const isInt = Number.isInteger(value);
    if (!isInt && value >= 0 && value <= 1) return { lo: 0, hi: 1, step: 0.01 };
    const m = Math.pow(10, Math.max(1, Math.ceil(Math.log10(Math.abs(value) + 1e-9))));
    return { lo: value < 0 ? -m : 0, hi: m, step: isInt ? 1 : m / 100 };
  }
  sliderStats = { shown: 0, slid: 0, wheel: 0, last: null as any };
  /** The hovered NUMBER extends outward into a horizontal slider, in place
   *  (PLUGIN_GOAL 106: "the number is supposed to extend outwards with a
   *  horizontal-scrollable-slider in-place of the hovered continuous float
   *  within its detected ranges") -- not a bar above it: the strip starts
   *  where the number is drawn, at its line's height, the live number at its
   *  left; the wheel scrolls it a step at a time. */
  private showSlider(fl: SlateLine, _e: MouseEvent): void {
    const v: any = this.view();
    const cm = v?.editor?.cm;
    if (!v || !cm) return;
    const ln = cm.state.doc.line(fl.line + 1);
    const a = cm.coordsAtPos(ln.from + fl.valueFrom);
    if (!a) return;
    const { lo, hi, step } = Cockpit.rangeOf(fl.key, Number(fl.value));
    if (this.slider && this.slider.dataset.line === String(fl.line)) return;
    this.slider?.remove();
    const s = document.body.createDiv({ cls: "domvec-slate-slider" });
    this.slider = s;
    s.dataset.line = String(fl.line);
    s.addEventListener("mouseleave", () => { s.remove(); if (this.slider === s) this.slider = null; });
    const num = s.createSpan({ cls: "domvec-slate-slider-num", text: fl.value.trim() });
    const input = s.createEl("input", { type: "range" });
    input.min = String(lo); input.max = String(hi); input.step = String(step); input.value = String(Number(fl.value));
    const write = (x: number) => {
      const val = Math.max(lo, Math.min(hi, Math.round(x / step) * step));
      const shown = step < 1 ? String(Math.round(val * 1000) / 1000) : String(Math.round(val));
      num.setText(shown);
      input.value = String(val);
      const fresh = parseSlate(v.editor.getValue()).find((f) => f.line === fl.line);
      if (fresh) this.slide(fresh, Number(shown));
      this.sliderStats.slid++;
    };
    input.oninput = () => write(Number(input.value));
    s.addEventListener("wheel", (we: WheelEvent) => {
      we.preventDefault(); we.stopPropagation();
      const d = Math.abs(we.deltaX) > Math.abs(we.deltaY) ? we.deltaX : -we.deltaY;
      this.sliderStats.wheel++;
      write(Number(input.value) + (d > 0 ? step : -step));
    }, { passive: false });
    s.style.left = Math.round(a.left) + "px";
    s.style.top = Math.round(a.top) + "px";
    s.style.height = Math.max(18, Math.round(a.bottom - a.top)) + "px";
    this.sliderStats.shown++;
    this.sliderStats.last = { key: fl.key, lo, hi, step, left: Math.round(a.left), top: Math.round(a.top) };
  }

  unload(): void { this.slider?.remove(); this.slider = null; this.undock(); }
}
