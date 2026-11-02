/**
 * Panels on the 2D plane: every computation-graph artifact, not only the
 * cockpit (PLUGIN_GOAL 65-66, 2026-11-01: "The jupyter kernels/cells are
 * supposed to also be the draggable 2D computation graph plane type panels.
 * You might see how graph/panel/kernel/nodes might integrate as one thing
 * here." -- "All tests should be on the 2D computation graph plane for panel
 * experiments, never their own view. This encourages the exercise of editor
 * tools accompanying the graph editor (i.e. create/delete etc)").
 *
 * One record, seen four ways (RESERVOIR_DESIGN 5, 5a): a note is a NODE of
 * the craft in 3D, its PANEL here, its KERNEL when a cell runs, its TREES as
 * a Python module (G-297). A panel is Obsidian's own markdown view of the
 * note (item 56), held in a leaf outside the workspace tree as the cockpit's
 * is, in a card on the plane: draggable by its header node and contained in
 * the plane (item 57), minimized to that node (items 54-55).
 *
 * The header node is the note's name in the link colour -- the inline title's
 * place, so the name is drawn once (item 54: "the duplicative "ego" part
 * should actually be fused"). A slate draws its own title line as the header
 * node, so a slate's card adds none.
 *
 * The editor's tools (item 66): on the plane's own strip, `+ notebook` and
 * `+ slate` create a note and open it here; on a panel, a right-click on the
 * header node minimizes it to the node and back, a double right-click deletes
 * it (mortegon N.13) -- the note to Obsidian's trash, recoverable -- and a
 * click on the craft's node closes the panel back into the node.
 */
import { App, MarkdownView, TFile } from "obsidian";
import { clampToPlane, makeDraggable, type PlaceStats } from "./planecard";
import { isSlate, COCKPIT_PATH } from "./cockpit";

export interface PlaneHost {
  /** The plane over the 3D view, when a graph is open. */
  plane(): HTMLElement | null;
  /** A panel opened or closed: the craft redraws its stuck rings. */
  changed?(): void;
  /** A note just shown in a panel (the plugin's notebook bookkeeping). */
  opened?(file: TFile): void;
  /** The `+ browser` tool: the browser cell as a panel (item 71). */
  openBrowser?(): void;
  /** A click (no drag) on a panel's header node: its halo (item 81). */
  headerClick?(path: string): void;
  /** The soft-link field's query: the halo laid out for it (item 90). */
  haloQuery?(path: string, query: string): void;
  /** The ego's notes (the craft's), for the sooner / later fans (item 90). */
  egoNotes?(): string[];
}

export interface PlanePanel { path: string; card: HTMLElement; leaf: any; head: HTMLElement | null; undrag: () => void; cleanup?: () => void }

/** Where new notes made by the tools go. */
export const PLANE_FOLDER = "domvec/graph";
const OPEN_KEY = "domvec-plane-panels";

// No heading: the header node IS the note's name (item 54, drawn once).
const NOTEBOOK_TEXT = (_name: string) => "```python\n\n```\n";
const SLATE_TEXT = (name: string) => `---\ndomvec: slate\n---\n${name}\n\tvalue\t\n`;

export class PlaneDesk {
  panels: PlanePanel[] = [];
  stats = { created: 0, opened: 0, closed: 0, deleted: 0, minimized: 0, restored: 0, own_view: 0 };
  place: PlaceStats = { drags: 0, clamped: 0 };
  /** Planted (item 66): panels open in a workspace tab, off the plane. */
  plantOwnView = false;
  private toolsEl: HTMLElement | null = null;
  /** The panel the reader last touched, and when: a plane panel is never
   *  the workspace's active leaf, so "the note the reader is in" asks here. */
  focusedPath = "";
  focusedAt = 0;
  focus(path: string): void { this.focusedPath = path; this.focusedAt = performance.now(); }
  focusedView(): MarkdownView | null { return this.focusedPath ? this.viewOf(this.focusedPath) : null; }
  private restored = false;

  /** The panels open on the plane, remembered across a reload (a convenience:
   *  the cockpit's card is remembered the same way). */
  private remember(): void {
    try { window.localStorage.setItem(OPEN_KEY, JSON.stringify(this.panels.map((p) => p.path))); } catch { /* a convenience */ }
  }
  private async restore(): Promise<void> {
    if (this.restored) return;
    this.restored = true;
    let paths: string[] = [];
    try { paths = JSON.parse(window.localStorage.getItem(OPEN_KEY) || "[]"); } catch { /* a convenience */ }
    for (const path of Array.isArray(paths) ? paths : []) {
      const f = this.app.vault.getAbstractFileByPath(String(path));
      if (f instanceof TFile) await this.open(f);
    }
  }

  constructor(private app: App, private host: PlaneHost) {}

  /** Every leaf on the plane (for the plugin's "which views show this note"). */
  leaves(): any[] {
    this.prune();
    return this.panels.map((p) => p.leaf);
  }

  panelOf(path: string): PlanePanel | null {
    this.prune();
    return this.panels.find((p) => p.path === path) || null;
  }

  private prune(): void {
    this.panels = this.panels.filter((p) => p.card.isConnected);
  }

  /** The plane's own tool strip: create a panel. */
  ensureTools(): HTMLElement | null {
    const plane = this.host.plane();
    if (!plane) return null;
    if (this.toolsEl && plane.contains(this.toolsEl)) return this.toolsEl;
    const el = plane.createDiv({ cls: "domvec-plane-tools" });
    for (const kind of ["notebook", "slate"] as const) {
      const b = el.createEl("button", { text: "+ " + kind, cls: "domvec-plane-tool" });
      b.dataset.kind = kind;
      b.onclick = (e) => { e.preventDefault(); e.stopPropagation(); void this.create(kind); };
    }
    if (this.host.openBrowser) {
      const b = el.createEl("button", { text: "+ browser", cls: "domvec-plane-tool" });
      b.dataset.kind = "browser";
      b.onclick = (e) => { e.preventDefault(); e.stopPropagation(); this.host.openBrowser!(); };
    }
    this.toolsEl = el;
    void this.restore();
    return el;
  }

  /** The `+ notebook` / `+ slate` tool: a new note, opened on the plane. With
   *  `text`, the note is written with it (the checks build their probes here). */
  async create(kind: "notebook" | "slate", opts: { path?: string; text?: string } = {}): Promise<any> {
    let path = opts.path || "";
    if (!path) {
      if (!this.app.vault.getAbstractFileByPath(PLANE_FOLDER)) await this.app.vault.createFolder(PLANE_FOLDER).catch(() => undefined);
      for (let i = 1; ; i++) {
        path = `${PLANE_FOLDER}/${kind} ${i}.md`;
        if (!this.app.vault.getAbstractFileByPath(path)) break;
      }
    }
    const folder = path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "";
    if (folder && !this.app.vault.getAbstractFileByPath(folder)) await this.app.vault.createFolder(folder).catch(() => undefined);
    const name = path.slice(path.lastIndexOf("/") + 1).replace(/\.md$/, "");
    const text = opts.text ?? (kind === "slate" ? SLATE_TEXT(name.replace(/\s+/g, "_")) : NOTEBOOK_TEXT(name));
    const f = await this.app.vault.create(path, text);
    this.stats.created++;
    return this.open(f);
  }

  /** A note as a panel on the plane: the card it already has, or a new one. */
  async open(file: TFile, opts: { line?: number; leaf?: any; state?: any;
                                  mount?: (card: HTMLElement) => Promise<(() => void) | void> } = {}): Promise<any> {
    const plane = this.host.plane();
    if (this.plantOwnView || !plane) {
      // Off the plane: the note in a tab of its own (the planted arm, or no 3D view open).
      this.stats.own_view++;
      const leaf = this.app.workspace.getLeaf("tab");
      await leaf.openFile(file, { state: { mode: "source", source: false } } as any);
      return leaf;
    }
    let p = this.panelOf(file.path);
    if (!p) {
      const Leaf = (this.app.workspace as any).activeLeaf?.constructor ?? (this.app.workspace.getMostRecentLeaf() as any)?.constructor;
      if (!Leaf && !opts.leaf) return null;
      const card = plane.createDiv({ cls: "domvec-plane-card domvec-panel-card" });
      card.dataset.path = file.path;
      // A cascade, so a second panel is never under the first.
      const n = this.panels.length;
      card.style.right = "auto";
      card.style.left = `${12 + 28 * (n % 8)}px`;
      card.style.top = `${44 + 28 * (n % 8)}px`;
      const slate = isSlate(this.app, file);
      let head: HTMLElement | null = null;
      if (!slate) {
        card.addClass("has-head");
        head = card.createDiv({ cls: "domvec-plane-head" });
        head.createSpan({ cls: "domvec-plane-head-node", text: file.basename });
        // The node's I/O toggle (item 79): its inputs and outputs linked to
        // the ego or to the web -- the note's own `maps` frontmatter.
        const chip = head.createSpan({ cls: "domvec-plane-maps" });
        const paint = () => {
          const m = String(this.app.metadataCache.getFileCache(file)?.frontmatter?.maps || "web");
          chip.setText(m === "ego" ? "ego" : "web"); chip.toggleClass("is-ego", m === "ego");
        };
        paint();
        // The cell's tools (item 90): the ego's cells before / after it,
        // fanned out; similar -- the halo; a soft-link field.
        const tool = (text: string, cls: string, act: () => void) => {
          const b = head!.createSpan({ cls: "domvec-plane-cell-tool " + cls, text });
          b.onmousedown = (e) => e.stopPropagation();
          b.onclick = (e) => { e.preventDefault(); e.stopPropagation(); act(); };
        };
        tool("‹ sooner", "is-sooner", () => { void this.fan(file.path, -1); });
        tool("later ›", "is-later", () => { void this.fan(file.path, 1); });
        tool("similar", "is-similar", () => this.host.headerClick?.(file.path));
        const field = head.createEl("input", { cls: "domvec-plane-softlink", attr: { placeholder: "soft links…" } });
        field.onmousedown = (e) => e.stopPropagation();
        field.onkeydown = (e) => { if (e.key === "Enter" && field.value.trim()) { e.preventDefault(); this.host.haloQuery?.(file.path, field.value); } };
        chip.onmousedown = (e) => e.stopPropagation();
        chip.onclick = async (e) => {
          e.preventDefault(); e.stopPropagation();
          const now = String(this.app.metadataCache.getFileCache(file)?.frontmatter?.maps || "web");
          await this.app.fileManager.processFrontMatter(file, (fm: any) => { fm.maps = now === "ego" ? "web" : "ego"; });
          window.setTimeout(paint, 300);
          this.host.changed?.();
        };
      }
      const leaf = opts.leaf || new Leaf(this.app);
      card.appendChild(leaf.containerEl);
      await (leaf.__openFile || leaf.openFile).call(leaf, file, opts.state || { state: { mode: "source", source: false } });
      const fpath = file.path;
      const undrag = makeDraggable(card, plane, "domvec-plane-card:" + file.path, this.place, () => this.host.headerClick?.(fpath));
      clampToPlane(card, plane);
      p = { path: file.path, card, leaf, head, undrag };
      // The panel is the note's as soon as the note shows; anything mounted
      // beneath it (the browser under its cockpit) arrives after -- a browser
      // booting for seconds once hid the panel itself (G-300).
      this.panels.push(p);
      this.hook(p);
      if (opts.mount) { const pp = p; const undo = await opts.mount(card); if (undo) pp.cleanup = undo; clampToPlane(card, plane); }
      const path = file.path;
      card.addEventListener("pointerdown", () => this.focus(path), true);
      card.addEventListener("focusin", () => this.focus(path), true);
      // `detach` closes the panel: the card goes with its leaf.
      const detach = leaf.detach.bind(leaf);
      leaf.detach = () => { if (!this.close(leaf, detach)) detach(); };
      this.stats.opened++;
      this.remember();
      this.host.opened?.(file);
      this.host.changed?.();
    } else {
      p.card.removeClass("is-collapsed");
      // Opened before by a path that mounted nothing beneath it (a remembered
      // panel restored at load): mounted now -- the browser's slate had come
      // back alone, with no browser under it (G-300).
      if (opts.mount && !p.cleanup) { const pp = p; const undo = await opts.mount(p.card); if (undo) pp.cleanup = undo; }
      // Asked for again: decorated again (a panel restored at load, before the
      // slate decorations were hooked, drew its title as plain text -- G-300).
      this.host.changed?.();
    }
    this.focus(file.path);
    if (opts.line !== undefined && opts.line >= 0) {
      const v: any = p.leaf.view;
      try { v?.editor?.setCursor({ line: opts.line, ch: 0 }); v?.editor?.scrollIntoView({ from: { line: opts.line, ch: 0 }, to: { line: opts.line, ch: 0 } }, true); }
      catch { /* a cursor is a convenience */ }
    }
    return p.leaf;
  }

  /** An empty panel for a note opened into it later (`leaf.openFile`): the
   *  checks' drop-in for `getLeaf("tab")`, so a probe lives on the plane. */
  leaf(): any {
    // A REAL leaf, outside the workspace tree: its first `openFile` mounts it
    // as that note's panel on the plane; afterwards it is that panel's leaf
    // (its view, its detach, setActiveLeaf on it) like any other.
    if (this.plantOwnView || !this.host.plane()) { this.stats.own_view++; return this.app.workspace.getLeaf("tab"); }
    const Leaf = (this.app.workspace as any).activeLeaf?.constructor ?? (this.app.workspace.getMostRecentLeaf() as any)?.constructor;
    const leaf: any = new Leaf(this.app);
    leaf.__openFile = leaf.openFile;
    const setViewState0 = leaf.setViewState;
    const mounted = () => { leaf.openFile = leaf.__openFile; leaf.setViewState = setViewState0; };
    leaf.openFile = async (file: TFile, st?: any) => {
      mounted();
      await this.open(file, { leaf, state: st });
    };
    // A note opened by view state (`{ type: "markdown", state: { file } }`)
    // mounts it the same way -- P-M3 opens its probe so, and the leaf sat
    // detached, off the plane and out of the DOM.
    leaf.setViewState = async (vs: any, ...rest: any[]) => {
      const f = vs && vs.type === "markdown" && vs.state && vs.state.file ? this.app.vault.getAbstractFileByPath(String(vs.state.file)) : null;
      if (!(f instanceof TFile)) return setViewState0.call(leaf, vs, ...rest);
      mounted();
      await this.open(f, { leaf, state: { state: vs.state } });
    };
    return leaf;
  }

  /** Close a panel back into its node (the note stays). */
  close(leaf: any, detach?: () => void, remember = true): boolean {
    const p = this.panels.find((x) => x.leaf === leaf);
    if (!p) return false;
    // Off the list first: the leaf's own (patched) detach comes back here.
    this.panels = this.panels.filter((x) => x !== p);
    p.undrag();
    try { p.cleanup?.(); } catch { /* gone */ }
    try { (detach || p.leaf.detach.bind(p.leaf))(); } catch { /* gone */ }
    p.card.remove();
    this.stats.closed++;
    if (remember) this.remember();
    this.host.changed?.();
    return true;
  }

  closePath(path: string): boolean {
    const p = this.panelOf(path);
    return p ? this.close(p.leaf) : false;
  }

  /** The delete tool: the panel goes and its note to Obsidian's trash. The
   *  cockpit is the craft's root and is never deleted. */
  async remove(path: string): Promise<boolean> {
    if (path === COCKPIT_PATH) return false;
    // The editor's own save first, then the panel shut: a save still pending
    // when the note went wrote it back (33 probe notes outlived the checks
    // that deleted them).
    const p = this.panelOf(path);
    try { await p?.leaf.view?.save?.(); } catch { /* nothing to save */ }
    this.closePath(path);
    await new Promise((r) => window.setTimeout(r, 150));
    const f = this.app.vault.getAbstractFileByPath(path);
    if (!(f instanceof TFile)) return false;
    await this.app.vault.trash(f, false);           // the vault's .trash: recoverable
    // Its remembered place goes with it: a later note of the same name started
    // where a test had dragged this one, against the plane's corner (G-298).
    try { window.localStorage.removeItem("domvec-plane-card:" + path); } catch { /* a convenience */ }
    this.stats.deleted++;
    this.host.changed?.();
    return true;
  }

  /** The delete tool by file (the checks' cleanup goes through it, item 66). */
  async trash(file: TFile | string): Promise<boolean> {
    return this.remove(typeof file === "string" ? file : file.path);
  }

  /** The sooner / later fans open now: note -> { dir, the notes it opened }. */
  fans = new Map<string, { dir: number; paths: string[] }>();
  fanStats = { opened: 0, closed: 0, last: [] as string[] };
  /** Planted (item 90): a fan ignores creation order -- sooner and later alike. */
  plantFanUnordered = false;
  /** The ego's cells made before (`dir` -1) or after (+1) this one, by their
   *  creation time, opened as minimized nodes on an arc beside its card; the
   *  same tool again folds the fan away (item 90). */
  async fan(path: string, dir: -1 | 1, n = 5): Promise<string[]> {
    const key = path + "|" + dir;
    const open = this.fans.get(key);
    if (open) {
      for (const q of open.paths) this.closePath(q);
      this.fans.delete(key); this.fanStats.closed++;
      return [];
    }
    const me = this.app.vault.getAbstractFileByPath(path);
    const plane = this.host.plane(), p = this.panelOf(path);
    if (!(me instanceof TFile) || !plane || !p) return [];
    const t0 = me.stat.ctime;
    // Cells only: the cockpit and the browsers' cockpits are instruments,
    // not cells (a browser's slate fanned open would lose its browser).
    const pool = (this.host.egoNotes?.() || []).filter((q) => q !== path && q !== COCKPIT_PATH && !q.startsWith("domvec/browser"))
      .map((q) => this.app.vault.getAbstractFileByPath(q)).filter((f): f is TFile => f instanceof TFile)
      .filter((f) => this.plantFanUnordered || (dir < 0 ? f.stat.ctime < t0 : f.stat.ctime > t0))
      .sort((a, b) => Math.abs(a.stat.ctime - t0) - Math.abs(b.stat.ctime - t0)).slice(0, n);
    const cr = p.card.getBoundingClientRect(), pr = plane.getBoundingClientRect();
    const cx = (dir < 0 ? cr.left : cr.right) - pr.left, cy = cr.top - pr.top + 24;
    const opened: string[] = [];
    for (let i = 0; i < pool.length; i++) {
      const f = pool[i];
      const was = !!this.panelOf(f.path);
      await this.open(f);
      const q = this.panelOf(f.path);
      if (!q) continue;
      if (!q.card.hasClass("is-collapsed")) this.toggleMinimized(f.path);
      const a = (-0.6 + (1.2 * i) / Math.max(1, pool.length - 1)) * (pool.length > 1 ? 1 : 0);
      const r = 120 + 30 * i;
      q.card.style.left = `${Math.max(0, cx + dir * r * Math.cos(a) - (dir < 0 ? 70 : 0))}px`;
      q.card.style.top = `${Math.max(0, cy + r * Math.sin(a))}px`;
      clampToPlane(q.card, plane);
      if (!was) opened.push(f.path);
    }
    this.fans.set(key, { dir, paths: opened });
    this.fanStats.opened++; this.fanStats.last = pool.map((f) => f.path);
    return pool.map((f) => f.path);
  }

  /** Minimized: the card is its header node alone (items 54-55). */
  toggleMinimized(path: string): boolean {
    const p = this.panelOf(path);
    if (!p) return false;
    const now = !p.card.hasClass("is-collapsed");
    p.card.toggleClass("is-collapsed", now);
    if (now) this.stats.minimized++; else this.stats.restored++;
    const plane = this.host.plane();
    if (plane) clampToPlane(p.card, plane);
    return now;
  }

  /** The header node's gestures: right-click minimizes, a double right-click deletes. */
  private hook(p: PlanePanel): void {
    let rightAt = 0;
    const onRight = (e: MouseEvent) => {
      const t = e.target as HTMLElement;
      const onHead = !!t?.closest?.(".domvec-plane-head-node, .domvec-var-title, .domvec-slate-circle-dot");
      if (!onHead) return;
      const now = performance.now();
      if (now - rightAt < 450) {
        e.preventDefault(); e.stopPropagation();
        rightAt = 0;
        // The first right-click minimized it; the second deletes.
        void this.remove(p.path);
        return;
      }
      rightAt = now;
      // A slate's own right-click on its title collapses it (the slate gesture,
      // G-278, left to run); its card follows. Any other note's header
      // minimizes the card.
      if (p.head) { e.preventDefault(); e.stopPropagation(); this.toggleMinimized(p.path); }
    };
    p.card.addEventListener("contextmenu", onRight, true);
    // A slate: the card is minimized exactly when its slate is collapsed.
    if (!p.head) {
      const sync = () => p.card.toggleClass("is-collapsed", !!p.leaf.containerEl.querySelector(".domvec-slate-circle"));
      const mo = new MutationObserver(sync);
      mo.observe(p.leaf.containerEl, { childList: true, subtree: true });
      const undrag = p.undrag;
      p.undrag = () => { mo.disconnect(); undrag(); };
    }
  }

  /** The view of a note on the plane, if one is open there. */
  viewOf(path: string): MarkdownView | null {
    const p = this.panelOf(path);
    return p && p.leaf.view instanceof MarkdownView ? p.leaf.view : null;
  }

  unload(): void {
    // Unloading is not the reader closing them: the list is kept for the reload.
    for (const p of [...this.panels]) this.close(p.leaf, undefined, false);
    this.toolsEl?.remove();
    this.toolsEl = null;
  }
}
