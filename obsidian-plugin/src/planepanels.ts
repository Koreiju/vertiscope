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
  /** The retrieval bar's code nodes by name (PLUGIN_GOAL 133). */
  codeNodes?(q: string): Promise<any[]>;
  /** The `+ browser` tool: the browser cell as a panel (item 71). */
  openBrowser?(): void;
  /** A click (no drag) on a panel's header node: its halo (item 81). */
  headerClick?(path: string): void;
  /** The chat cell's model, streamed (PLUGIN_GOAL 134). */
  chatStream?(prompt: string, context: string[], onToken: (t: string) => void): Promise<string>;
  /** The soft-link field's query: the halo laid out for it (item 90). */
  haloQuery?(path: string, query: string): void;
  /** The ego's notes (the craft's), for the sooner / later fans (item 90). */
  egoNotes?(): string[];
}

export interface PlanePanel { path: string; card: HTMLElement; leaf: any; head: HTMLElement | null; undrag: () => void; cleanup?: () => void;
  /** G-326: the reader sized it by hand -- the fold no longer sizes it. */
  manual?: boolean; fitH?: number; foldedToNode?: boolean }

/** Where new notes made by the tools go. */
export const PLANE_FOLDER = "domvec/graph";
const OPEN_KEY = "domvec-plane-panels";

// No heading: the header node IS the note's name (item 54, drawn once).
const NOTEBOOK_TEXT = (_name: string) => "```python\n\n```\n";
const RESPONSE_HEAD = ["---", "domvec: response", "---", ""].join(String.fromCharCode(10));
const SLATE_TEXT = (name: string) => `---\ndomvec: slate\n---\n${name}\n\tvalue\t\n`;

export class PlaneDesk {
  panels: PlanePanel[] = [];
  stats: Record<string, number> = { created: 0, opened: 0, closed: 0, deleted: 0, minimized: 0, restored: 0, own_view: 0, zoomed: 0 };
  place: PlaceStats = { drags: 0, clamped: 0 };
  /** Planted (item 66): panels open in a workspace tab, off the plane. */
  plantOwnView = false;
  /** Planted (133): the soft-link field back on panel headers. */
  plantSoftLinkField = false;
  /** Planted (133): Ctrl+= / Ctrl+- leave the panel alone. */
  plantNoPanelZoom = false;
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
    // Cards a previous load of the plugin left on the plane (the plane
    // outlives a reload): not this desk's, so each reload stacked another
    // copy of every remembered panel. Planted `__domvecPlantKeepOrphans`.
    const plane = this.host.plane();
    if (plane && !(window as any).__domvecPlantKeepOrphans) {
      const mine = new Set(this.panels.map((p) => p.card));
      for (const old of Array.from(plane.querySelectorAll(".domvec-panel-card")) as HTMLElement[]) if (!mine.has(old)) old.remove();
    }
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
    if (!this.plantToolButtons) { this.buildRetrievalBar(el); this.toolsEl = el; void this.restore(); return el; }
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

  /** Planted (133): the three create buttons, as before the retrieval bar. */
  plantToolButtons = false;
  plantNoChatEntry = false;
  retrieveStats = { queries: 0, node_hits: 0, picked: 0, last_kind: "" };
  /**
   * The RETRIEVAL BAR (PLUGIN_GOAL 133: "Instead of buttons for creating only
   * three different notebook-level cells ... a retrieval bar for the different
   * typed nodes from our code-side artifacts ... code cell, markdown cell and
   * browser cell within a retrieval space that includes the generalities"):
   * one field; its results are the three general cells, then every typed node
   * of the code property graph whose name matches, each with its kind. A node
   * picked opens as a cell holding its reference.
   */
  private buildRetrievalBar(el: HTMLElement): void {
    const input = el.createEl("input", { cls: "domvec-plane-retrieve", attr: { placeholder: "cell or node…" } });
    const list = el.createDiv({ cls: "domvec-plane-retrieve-list" });
    input.onmousedown = (e) => e.stopPropagation();
    type Hit = { label: string; kind: string; act: () => void };
    const general: Hit[] = [
      { label: "code cell", kind: "cell", act: () => { void this.create("notebook"); } },
      { label: "markdown cell", kind: "cell", act: () => { void this.create("slate"); } },
      { label: "browser cell", kind: "cell", act: () => { this.host.openBrowser?.(); } },
      // A CHAT cell (PLUGIN_GOAL 134: "a basic mistral 2 DPO chat model cell as
      // one of the primary jupyter level notebook cells"): its note carries
      // `domvec: chat`, so its head shows `ask`. Planted `plantNoChatEntry`.
      ...(this.plantNoChatEntry ? [] : [{ label: "chat cell", kind: "cell", act: () => {
        void this.create("notebook", { text: ["---", "domvec: chat", "---", "", "Ask here; snap cells to my edges for context.", ""].join(String.fromCharCode(10)) });
      } }]),
    ];
    let seq = 0;
    const show = (hits: Hit[]) => {
      list.empty();
      for (const h of hits) {
        const row = list.createDiv({ cls: "domvec-plane-retrieve-hit" });
        row.createSpan({ cls: "domvec-plane-retrieve-kind", text: h.kind });
        row.createSpan({ text: " " + h.label });
        row.onmousedown = (e) => { e.preventDefault(); e.stopPropagation(); this.retrieveStats.picked++; this.retrieveStats.last_kind = h.kind; list.empty(); input.value = ""; h.act(); };
      }
    };
    const run = async () => {
      const q = input.value.trim().toLowerCase(), my = ++seq;
      this.retrieveStats.queries++;
      const hits = general.filter((g) => !q || g.label.includes(q));
      let nodes: any[] = [];
      if (q.length >= 2 && this.host.codeNodes) nodes = await this.host.codeNodes(q).catch(() => []);
      if (my !== seq) return;
      this.retrieveStats.node_hits = nodes.length;
      const BT = String.fromCharCode(96).repeat(3), NL = String.fromCharCode(10);
      for (const n of nodes) hits.push({ label: `${n.qname || n.name}`, kind: String(n.kind || "node"), act: () => {
        void this.create("notebook", { text: [`${n.kind} [${n.qname || n.name}](${n.url}${n.line ? "#L" + n.line : ""})`, "", BT + "python", `# ${n.qname || n.name}`, BT, ""].join(NL) });
      } });
      show(hits);
    };
    input.oninput = () => { void run(); };
    input.onfocus = () => { void run(); };
    input.onblur = () => window.setTimeout(() => list.empty(), 150);
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
        // PLUGIN_GOAL 133: "soft links" is subsumed by "similar" (the field
        // is gone; planted `plantSoftLinkField` puts it back); minimize and
        // exit, which notebook panels did not have.
        if (this.plantSoftLinkField) {
          const field = head.createEl("input", { cls: "domvec-plane-softlink", attr: { placeholder: "soft links…" } });
          field.onmousedown = (e) => e.stopPropagation();
          field.onkeydown = (e) => { if (e.key === "Enter" && field.value.trim()) { e.preventDefault(); this.host.haloQuery?.(file.path, field.value); } };
        }
        // A CHAT cell's ask (PLUGIN_GOAL 134). Decided again when the note's
        // metadata lands: a note just created has none yet.
        tool("ask ▸", "is-ask", () => { void this.askChat(file.path); });
        const askEl = head.querySelector(".is-ask") as HTMLElement;
        const isChat = () => String(this.app.metadataCache.getFileCache(file)?.frontmatter?.domvec || "") === "chat";
        const paintAsk = () => { askEl.style.display = isChat() ? "" : "none"; };
        paintAsk();
        const ref = this.app.metadataCache.on("changed", (f: TFile) => { if (f.path === file.path) paintAsk(); });
        window.setTimeout(paintAsk, 600);
        card.addEventListener("domvec-closed", () => this.app.metadataCache.offref(ref));
        tool("–", "is-minimize", () => { this.toggleMinimized(file.path); });
        tool("×", "is-exit", () => { const q = this.panelOf(file.path); if (q) q.leaf.detach(); });
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
      // Alt+click on the node is the containment gesture (G-327), not the halo.
      const undrag = makeDraggable(card, plane, "domvec-plane-card:" + file.path, this.place,
        () => { if (performance.now() - this.altAt < 800) return; this.host.headerClick?.(fpath); });
      clampToPlane(card, plane);
      p = { path: file.path, card, leaf, head, undrag };
      // The panel is the note's as soon as the note shows; anything mounted
      // beneath it (the browser under its cockpit) arrives after -- a browser
      // booting for seconds once hid the panel itself (G-300).
      this.panels.push(p);
      this.hook(p);
      if (opts.mount) { const pp = p; const undo = await opts.mount(card); if (undo) pp.cleanup = undo; clampToPlane(card, plane); }
      const path = file.path;
      // Ctrl+= / Ctrl+- (and Ctrl+0) resize THIS panel (PLUGIN_GOAL 133),
      // captured before Obsidian's own zoom of the whole app.
      card.addEventListener("keydown", (e: KeyboardEvent) => {
        if (!(e.ctrlKey || e.metaKey) || this.plantNoPanelZoom) return;
        const k = e.key;
        if (k !== "=" && k !== "+" && k !== "-" && k !== "0") return;
        e.preventDefault(); e.stopPropagation();
        const now = Number(card.dataset.zoom || "1");
        const next = k === "0" ? 1 : Math.min(3, Math.max(0.4, Math.round((now * (k === "-" ? 1 / 1.1 : 1.1)) * 100) / 100));
        card.dataset.zoom = String(next);
        (card.style as any).zoom = String(next);
        this.stats.zoomed = (this.stats.zoomed || 0) + 1;
      }, true);
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

  /**
   * **Panel and node are one fold parameter** (PLUGIN_GOAL 110, G-326): a
   * panel is as tall as the fields it SHOWS -- folding a heading or a slate
   * field shrinks it, unfolding grows it, up to the plane (beyond that it
   * scrolls: the rest is occluded) -- and folded back to its root field, one
   * line showing, it IS its node. A reader's own resize takes the size over.
   * Planted `plantFixedSize`: the card's fixed CSS size whatever is folded.
   */
  plantFixedSize = false;
  foldStats = { fits: 0, to_node: 0, from_node: 0, manual: 0 };
  /** What a panel shows: its visible lines and folds, its content's natural height. */
  foldOf(path: string): { lines: number; folds: number; content: number; height: number; node: boolean; manual: boolean } | null {
    const p = this.panelOf(path);
    if (!p) return null;
    const el = p.leaf.containerEl as HTMLElement;
    const v: any = p.leaf.view;
    const preview = typeof v?.getMode === "function" && v.getMode() === "preview";
    let lines = 0, folds = 0, content = 0;
    // The NATURAL height: from the top of what is drawn to the bottom of its
    // last block -- never a sizer's scroll height, which CodeMirror holds at
    // least as tall as its container, so a card sized to it grew without end
    // (G-326, run 42-43: a six-line note read 728 px, the plane's limit).
    const bottomOf = (root: HTMLElement | null, kids: HTMLElement[]) => {
      if (!root || !kids.length) return 0;
      const top = root.getBoundingClientRect().top;
      return Math.max(...kids.map((k) => k.getBoundingClientRect().bottom - top));
    };
    if (preview) {
      const sizer = el.querySelector(".markdown-reading-view .markdown-preview-sizer") as HTMLElement | null;
      const kids = sizer ? Array.from(sizer.querySelectorAll(":scope > div:not(.mod-footer)")) as HTMLElement[] : [];
      content = bottomOf(sizer, kids);
      lines = kids.filter((k) => !k.classList.contains("mod-header")).length;
      folds = el.querySelectorAll(".markdown-reading-view .is-collapsed").length;
    } else {
      const cm = el.querySelector(".cm-content") as HTMLElement | null;
      const ls = cm ? Array.from(cm.querySelectorAll(":scope > *")) as HTMLElement[] : [];
      lines = ls.filter((l) => l.classList.contains("cm-line") && (l.textContent || "").trim().length > 0).length;
      folds = cm ? cm.querySelectorAll(".cm-foldPlaceholder").length : 0;
      // The inline title and properties sit above the content in the same scroller.
      const scroller = el.querySelector(".cm-scroller") as HTMLElement | null;
      content = bottomOf(scroller, ls) + 8;
    }
    return { lines, folds, content, height: p.card.offsetHeight, node: p.card.hasClass("is-collapsed"), manual: !!p.manual };
  }
  /** Size one panel to what it shows; fold it into its node when only its root shows. */
  fit(path: string): void {
    const p = this.panelOf(path);
    const plane = this.host.plane();
    if (!p || !plane || this.plantFixedSize || p.manual || !p.card.hasClass("domvec-panel-card") || p.card.hasClass("domvec-browser-card")) return;
    const f = this.foldOf(path);
    if (!f) return;
    // Folded back to the root: one line, something folded -- the panel is its node.
    if (!f.node && f.folds > 0 && f.lines <= 1) {
      p.card.addClass("is-collapsed"); p.foldedToNode = true; this.foldStats.to_node++;
      clampToPlane(p.card, plane);
      return;
    }
    if (f.node) return;
    const head = (p.head?.offsetHeight || 0) + 18;
    const max = Math.max(160, plane.clientHeight * 0.85);
    const h = Math.round(Math.min(max, Math.max(120, head + f.content + 12)));
    if (Math.abs(h - (p.fitH ?? -1)) <= 2 && Math.abs(p.card.offsetHeight - h) <= 2) return;
    p.fitH = h;
    p.card.style.height = h + "px";
    this.foldStats.fits++;
    clampToPlane(p.card, plane);
  }
  fitAll(): void { for (const p of this.panels) this.fit(p.path); if (this.groups.size) this.followGroups(); }

  /**
   * **The containment gesture** (PLUGIN_GOAL 111, G-327): Alt+click on a
   * panel's node gathers the COLLAPSED panel nodes linked to it -- a link
   * either way between the notes -- under it, in a container drawn round
   * them; they follow it while contained, and the same gesture puts them
   * back where they were. Planted `plantContainNoLinks`: every collapsed node
   * is gathered, linked or not.
   */
  plantContainNoLinks = false;
  groups = new Map<string, { members: string[]; was: Map<string, { left: string; top: string }>; el: HTMLElement }>();
  containStats = { gathered: 0, released: 0, last: null as any };
  private altAt = 0;
  /** The notes linked to this one, either way (the metadata cache's resolved links). */
  linkedTo(path: string): Set<string> {
    const out = new Set<string>();
    const rl: Record<string, Record<string, number>> = (this.app.metadataCache as any).resolvedLinks || {};
    for (const t of Object.keys(rl[path] || {})) out.add(t);
    for (const [src, targets] of Object.entries(rl)) if (targets && targets[path]) out.add(src);
    out.delete(path);
    return out;
  }
  contain(path: string): string[] {
    const p = this.panelOf(path);
    const plane = this.host.plane();
    if (!p || !plane) return [];
    const had = this.groups.get(path);
    if (had) {
      for (const m of had.members) {
        const q = this.panelOf(m), w = had.was.get(m);
        if (q && w) { q.card.style.left = w.left; q.card.style.top = w.top; q.card.removeClass("is-contained"); }
      }
      had.el.remove();
      this.groups.delete(path);
      this.containStats.released++;
      this.containStats.last = { path, released: had.members };
      return [];
    }
    const linked = this.linkedTo(path);
    const inOther = new Set([...this.groups.values()].flatMap((g) => g.members));
    const members = this.panels.filter((q) => q.path !== path && q.card.hasClass("is-collapsed") && !inOther.has(q.path)
      && !this.groups.has(q.path) && (this.plantContainNoLinks || linked.has(q.path))).map((q) => q.path);
    const was = new Map<string, { left: string; top: string }>();
    for (const m of members) { const q = this.panelOf(m)!; was.set(m, { left: q.card.style.left, top: q.card.style.top }); q.card.addClass("is-contained"); }
    const el = plane.createDiv({ cls: "domvec-plane-group" });
    el.createSpan({ cls: "domvec-plane-group-label", text: path.split("/").pop()!.replace(/\.md$/, "") + " contains " + members.length });
    this.groups.set(path, { members, was, el });
    this.containStats.gathered++;
    this.containStats.last = { path, members, linked: linked.size };
    this.followGroups();
    return members;
  }
  /** Each group's members laid out under its node, and its container drawn round them. */
  followGroups(): void {
    const plane = this.host.plane();
    if (!plane) return;
    const pr = plane.getBoundingClientRect();
    for (const [path, g] of this.groups) {
      const p = this.panelOf(path);
      if (!p) { g.el.remove(); this.groups.delete(path); continue; }
      const cr = p.card.getBoundingClientRect();
      const x0 = cr.left - pr.left, y0 = cr.bottom - pr.top + 14;
      let right = cr.right - pr.left, bottom = cr.bottom - pr.top;
      g.members.forEach((m, i) => {
        const q = this.panelOf(m);
        if (!q) return;
        const x = x0 + (i % 4) * 76, y = y0 + Math.floor(i / 4) * 70;
        q.card.style.left = x + "px"; q.card.style.top = y + "px"; q.card.style.right = "auto";
        right = Math.max(right, x + q.card.offsetWidth); bottom = Math.max(bottom, y + q.card.offsetHeight);
      });
      const pad = 10;
      g.el.style.left = (x0 - pad) + "px"; g.el.style.top = (cr.top - pr.top - pad) + "px";
      g.el.style.width = (right - x0 + 2 * pad) + "px"; g.el.style.height = (bottom - (cr.top - pr.top) + 2 * pad) + "px";
    }
  }

  /** Minimized: the card is its header node alone (items 54-55). */
  chatStats = { asks: 0, tokens: 0, context_cells: 0, last_ms: 0, first_token_ms: 0, linked: 0 };
  /** The cells magnetized around `path`, recursively -- its context (PLUGIN_GOAL 134). */
  magnetized(path: string): string[] {
    const seen = new Set<string>([path]), order: string[] = [];
    const sides = ["magnetLeft", "magnetRight", "magnetTop", "magnetBottom"];
    const cards = () => this.panels.map((p) => p.card);
    const queue = [path];
    while (queue.length) {
      const at = queue.shift()!;
      const mine = this.panelOf(at)?.card;
      const next = new Set<string>();
      if (mine) for (const k of sides) { const v = (mine.dataset as any)[k]; if (v) next.add(v); }
      for (const c of cards()) for (const k of sides) if ((c.dataset as any)[k] === at && c.dataset.path) next.add(c.dataset.path);
      for (const n of next) if (!seen.has(n)) { seen.add(n); order.push(n); queue.push(n); }
    }
    // The magnet RESPECTS HARD LINKS (PLUGIN_GOAL 134: "the block-magnet
    // element also respects hard links ... even for laterals"): every note a
    // magnetized cell -- or the chat cell itself -- links to is context too,
    // followed recursively (two hops; the budget truncates). Planted
    // `__domvecPlantMagnetNoLinks`: the magnets alone, as before.
    if (!(window as any).__domvecPlantMagnetNoLinks) {
      const resolved: Record<string, Record<string, number>> = (this.app.metadataCache as any).resolvedLinks || {};
      let frontier = [path, ...order];
      for (let hop = 0; hop < 2 && frontier.length; hop++) {
        const nextF: string[] = [];
        for (const at of frontier) for (const to of Object.keys(resolved[at] || {})) {
          if (seen.has(to) || !to.endsWith(".md")) continue;
          seen.add(to); order.push(to); nextF.push(to); this.chatStats.linked++;
        }
        frontier = nextF;
      }
    }
    return order;
  }
  /** A chat cell asked (PLUGIN_GOAL 134): its text the prompt, the cells
   *  magnetized around it (recursively, truncated) the ONLY context; the reply
   *  a separate response cell snapped beneath it, written token by token. */
  async askChat(path: string): Promise<string> {
    const f = this.app.vault.getAbstractFileByPath(path) as TFile | null;
    const p = this.panelOf(path);
    if (!f || !p || !this.host.chatStream) return "";
    const strip = (t: string) => t.replace(/^---[\s\S]*?---\s*/, "").trim();
    const prompt = strip(await this.app.vault.read(f));
    const ctx: string[] = [];
    let budget = 6000;
    for (const q of this.magnetized(path)) {
      const g = this.app.vault.getAbstractFileByPath(q) as TFile | null;
      if (!g || budget <= 0) continue;
      const t = strip(await this.app.vault.read(g)).slice(0, budget);
      if (t) { ctx.push(t); budget -= t.length; }
    }
    this.chatStats.asks++; this.chatStats.context_cells = ctx.length;
    const dir = path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "";
    let rp = "";
    for (let i = 1; ; i++) { rp = `${dir ? dir + "/" : ""}${f.basename} reply ${i}.md`; if (!this.app.vault.getAbstractFileByPath(rp)) break; }
    await this.create("notebook", { path: rp, text: RESPONSE_HEAD });
    const rc = this.panelOf(rp)?.card, pc = p.card;
    if (rc) {
      rc.style.right = "auto"; rc.style.left = pc.style.left || `${pc.offsetLeft}px`;
      rc.style.top = `${pc.offsetTop + pc.offsetHeight}px`;
      rc.dataset.magnetTop = path;
    }
    const rf = this.app.vault.getAbstractFileByPath(rp) as TFile;
    const editor: any = (this.panelOf(rp)?.leaf?.view as any)?.editor;
    const t0 = performance.now(); let first = 0, n = 0;
    const reply = await this.host.chatStream(prompt, ctx, (tok) => {
      n++; if (!first) first = performance.now() - t0;
      if (editor) { const end = editor.offsetToPos(editor.getValue().length); editor.replaceRange(tok, end); }
    });
    if (!editor) await this.app.vault.modify(rf, RESPONSE_HEAD + reply);
    this.chatStats.tokens += n; this.chatStats.last_ms = Math.round(performance.now() - t0); this.chatStats.first_token_ms = Math.round(first);
    return reply;
  }

  toggleMinimized(path: string): boolean {
    const p = this.panelOf(path);
    if (!p) return false;
    const now = !p.card.hasClass("is-collapsed");
    // Restored from a node it was FOLDED into: unfolded, or the fold would
    // fold it straight back (G-326).
    if (!now && p.foldedToNode) {
      try { (p.leaf.view as any)?.editor?.exec?.("unfoldAll"); } catch { /* nothing folded */ }
      p.foldedToNode = false; this.foldStats.from_node++;
    }
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
    // Alt+click on the node: contain its linked collapsed nodes (G-327).
    p.card.addEventListener("click", (e: MouseEvent) => {
      if (!e.altKey) return;
      const t = e.target as HTMLElement;
      if (!t?.closest?.(".domvec-plane-head-node, .domvec-var-title, .domvec-slate-circle-dot")) return;
      e.preventDefault(); e.stopPropagation();
      this.altAt = performance.now();
      this.contain(p.path);
    }, true);
    p.card.addEventListener("pointerdown", (e: PointerEvent) => { if (e.altKey) this.altAt = performance.now(); }, true);
    // The resize corner pressed and the size changed: the READER sized it (G-326).
    p.card.addEventListener("pointerdown", (e: PointerEvent) => {
      const r = p.card.getBoundingClientRect();
      if (e.clientX < r.right - 18 || e.clientY < r.bottom - 18) return;
      const h0 = p.card.offsetHeight, w0 = p.card.offsetWidth;
      const up = () => {
        window.removeEventListener("pointerup", up, true);
        if (Math.abs(p.card.offsetHeight - h0) > 3 || Math.abs(p.card.offsetWidth - w0) > 3) { p.manual = true; this.foldStats.manual++; }
      };
      window.addEventListener("pointerup", up, true);
    }, true);
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
