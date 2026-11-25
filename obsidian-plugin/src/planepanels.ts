import { decorateCard } from "./slots";
import { acceptTabDrops, toTabs } from "./tabdrag";
import { TERMINAL_VIEW } from "./terminal";
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
import { chunkNoteState, clampToPlane, makeDraggable, type PlaceStats } from "./planecard";
import { edgeResizable } from "./edgeresize";
import { isSlate, COCKPIT_PATH } from "./cockpit";
import { ChatUI, type Piece } from "./chatui";
import { EgoCanvas } from "./egocanvas";

export interface PlaneHost {
  /** The plane over the 3D view, when a graph is open. */
  plane(): HTMLElement | null;
  /** A panel opened or closed: the craft redraws its stuck rings. */
  changed?(): void;
  /** A card was dragged to a new place: the ego's 2D plane follows it (158). */
  moved?(path: string): void;
  /** A note just shown in a panel (the plugin's notebook bookkeeping). */
  opened?(file: TFile): void;
  /** The retrieval bar's code nodes by name (PLUGIN_GOAL 133). */
  codeNodes?(q: string): Promise<any[]>;
  /** G-388: mined trie-path pattern TYPES matching the query; one picked
   *  opens as its own node on the plane (`openType`). */
  typeNodes?(q: string): Promise<any[]>;
  openType?(pattern: string): void;
  /** G-205: the browse card -- the retrieval artifact's view -- with a query. */
  openBrowse?(query: string, scope?: string): void;
  /** The `+ browser` tool: the browser cell as a panel (item 71). */
  openBrowser?(): void;
  /** A click (no drag) on a panel's header node: its halo (item 81). */
  headerClick?(path: string): void;
  /** PLUGIN_GOAL 150: the panel goes back INTO 3D -- closed, the camera flown to its craft node. */
  intoCraft?(path: string): boolean;
  /** The chat cell's model, streamed (PLUGIN_GOAL 134). */
  chatStream?(prompt: string, context: string[], onToken: (t: string) => void): Promise<string>;
  /** Pull-apart: a pulled cell's card dropped at (x, y) goes back into the panel there. */
  pullInto?(from: string, x: number, y: number): Promise<boolean>;
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
const TERMINAL_TEXT = ["---", "domvec: terminal", "---", "", "A PowerShell cell: snap it to other cells; its place sets its order.", ""].join(String.fromCharCode(10));
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
   *  the cockpit's card is remembered the same way). Collapsed node artifacts
   *  are never remembered as open panels: the Craft IS their node form. */
  private remember(): void {
    try {
      const openPaths = this.panels.filter((p) => !p.card.hasClass("is-collapsed")).map((p) => p.path);
      window.localStorage.setItem(OPEN_KEY, JSON.stringify(openPaths));
    } catch { /* a convenience */ }
  }
  private uncollapseStoredFold(path: string): boolean {
    try {
      const k = "domvec.slate.folds:" + path;
      const raw = window.localStorage.getItem(k);
      if (!raw) return false;
      const st = JSON.parse(raw);
      if (st && st.collapsed) {
        st.collapsed = false;
        window.localStorage.setItem(k, JSON.stringify(st));
        return true;
      }
    } catch { /* a convenience */ }
    return false;
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
    for (const rawPath of Array.isArray(paths) ? paths : []) {
      const path = String(rawPath);
      // A panel that was collapsed to its deprecated circle node before restart
      // lives in the Craft as a node now; do not restore it as a circle artifact.
      if (this.uncollapseStoredFold(path)) continue;
      const f = this.app.vault.getAbstractFileByPath(path);
      if (f instanceof TFile) await this.open(f);
    }
    this.remember();
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
    this.hookFlip(plane);
    this.startMemoryLinks();
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
  retrieveStats = { queries: 0, node_hits: 0, type_hits: 0, picked: 0, last_kind: "" };
  /** Planted: the bar waits for every lookup before showing anything. */
  plantRetrieveWaits = false;
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
      // PLUGIN_GOAL 142: "Powershell terminals should also be added to the set
      // of cells that can be magnetized both vertically and laterally."
      { label: "terminal cell", kind: "cell", act: () => { void this.create("notebook", { text: TERMINAL_TEXT }); } },
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
      // G-205: any query can be BROWSED -- the retrieval artifact, on its own
      // card, ranked at web scope (the card's picker widens or narrows it).
      if (q.length >= 2 && this.host.openBrowse) {
        const raw = input.value.trim();
        hits.unshift({ label: raw, kind: "browse", act: () => { this.host.openBrowse!(raw, "web"); } });
      }
      // What needs no lookup is shown AT ONCE: the code nodes and the mined
      // types follow when they come (mining reads every address row, ~5 s
      // cold -- run 82: the bar showed nothing at all until it finished).
      if (!this.plantRetrieveWaits) show(hits);
      let nodes: any[] = [];
      if (q.length >= 2 && this.host.codeNodes) nodes = await this.host.codeNodes(q).catch(() => []);
      let types: any[] = [];
      if (q.length >= 2 && this.host.typeNodes) types = await this.host.typeNodes(q).catch(() => []);
      if (my !== seq) return;
      this.retrieveStats.node_hits = nodes.length;
      const BT = String.fromCharCode(96).repeat(3), NL = String.fromCharCode(10);
      for (const n of nodes) hits.push({ label: `${n.qname || n.name}`, kind: String(n.kind || "node"), act: () => {
        void this.create("notebook", { text: [`${n.kind} [${n.qname || n.name}](${n.url}${n.line ? "#L" + n.line : ""})`, "", BT + "python", `# ${n.qname || n.name}`, BT, ""].join(NL) });
      } });
      // G-388: a mined type is a node kind of its own -- an aggregate of trie
      // paths across pages -- listed with what it aggregates.
      this.retrieveStats.type_hits = types.length;
      for (const t of types) hits.push({ label: `${t.pattern}  (${t.instances} on ${t.pages} pages)`, kind: "type",
        act: () => { this.host.openType?.(t.pattern); } });
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
    // A new note's frontmatter is not cached yet: a terminal is known by its text.
    if (text === TERMINAL_TEXT) return this.open(f, { mount: (c) => this.terminalMount(c) });
    if (/^---\r?\ndomvec: chat\r?\n/.test(text)) return this.open(f, { mount: (c) => this.chatMount(c, f) });
    return this.open(f);
  }

  /** A note as a panel on the plane: the card it already has, or a new one. */
  async open(file: TFile, opts: { line?: number; leaf?: any; state?: any;
                                  at?: { x: number; y: number } | null;
                                  mount?: (card: HTMLElement) => Promise<(() => void) | void> } = {}): Promise<any> {
    const plane = this.host.plane();
    if (this.plantOwnView || !plane) {
      // Off the plane: the note in a tab of its own (the planted arm, or no 3D view open).
      this.stats.own_view++;
      const leaf = this.app.workspace.getLeaf("tab");
      await leaf.openFile(file, { state: { mode: "source", source: false } } as any);
      return leaf;
    }
    if (!((window as any).__domvec?.verify?.state?.()?.running)) {
      this.uncollapseStoredFold(file.path);
    }
    let p = this.panelOf(file.path);
    if (!p) {
      const Leaf = (this.app.workspace as any).activeLeaf?.constructor ?? (this.app.workspace.getMostRecentLeaf() as any)?.constructor;
      if (!Leaf && !opts.leaf) return null;
      const card = plane.createDiv({ cls: "domvec-plane-card domvec-panel-card" });
      card.dataset.path = file.path;
      decorateCard(card, file.path);   // the card: slot (G-240): +chat and any other decoration
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
        // A chat note drawn as the chat interface (G-394) asks from its own input box.
        const paintAsk = () => { askEl.style.display = isChat() && !card.classList.contains("is-chat") ? "" : "none"; };
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
      // A failed open leaves no card behind (2026-11-08: an untracked, empty
      // collapsed card stayed on the plane as a second "ego" circle).
      try {
        await (leaf.__openFile || leaf.openFile).call(leaf, file, opts.state || chunkNoteState(file.path));
      } catch (err) {
        try { leaf.detach?.(); } catch { /* gone */ }
        card.remove();
        this.stats.failed_open = (this.stats.failed_open || 0) + 1;
        throw err;
      }
      const fpath = file.path;
      // Alt+click on the node is the containment gesture (G-327), not the halo.
      // Only a panel with an explicit header bar (`head`) triggers `headerClick`
      // on click; a slate's `.domvec-var-title` is line 1 of its text editor.
      const undrag = makeDraggable(card, plane, "domvec-plane-card:" + file.path, this.place,
        () => { if (performance.now() - this.altAt < 800 || !head) return; this.host.headerClick?.(fpath); },
        (x, y) => this.wireDrop(fpath, x, y),
        () => this.host.moved?.(fpath), () => this.host.moved?.(fpath));
      if (opts.at && Number.isFinite(opts.at.x) && Number.isFinite(opts.at.y)) {
        card.style.right = "auto";
        card.style.left = `${Math.round(opts.at.x + 18)}px`;
        card.style.top = `${Math.round(opts.at.y - 24)}px`;
      }
      clampToPlane(card, plane);
      // Any edge or corner resizes it, found by hovering (159); a resize is the
      // READER sizing it, as the corner's was (G-326).
      const unedge = edgeResizable(card, { onEnd: () => { const q = this.panelOf(fpath); if (q) { q.manual = true; this.foldStats.manual++; } } });
      p = { path: file.path, card, leaf, head, undrag: () => { unedge(); undrag(); } };
      // The panel is the note's as soon as the note shows; anything mounted
      // beneath it (the browser under its cockpit) arrives after -- a browser
      // booting for seconds once hid the panel itself (G-300).
      this.panels.push(p);
      window.dispatchEvent(new CustomEvent("domvec-plane-changed"));   // G-400: 3D draws what the plane does not
      this.linksOn();                              // links between panels (G-398) whenever there are panels
      this.hook(p);
      const mount = opts.mount || (this.isTerminal(file) ? (c: HTMLElement) => this.terminalMount(c, Leaf)
                                   : this.isChatNote(file) ? (c: HTMLElement) => this.chatMount(c, file) : undefined);
      if (mount) { const pp = p; const undo = await mount(card); if (undo) pp.cleanup = undo; clampToPlane(card, plane); }
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
      // INTO 3D (150): a double-click on a collapsed panel's node (its circle or
      // header node) closes it back into its craft node, the camera flown there.
      card.addEventListener("dblclick", (e: MouseEvent) => {
        const t = e.target as HTMLElement;
        const onCircle = !!t?.closest?.(".domvec-slate-circle, .domvec-slate-circle-dot");
        if (t?.closest?.(".domvec-plane-card") !== card || (!card.hasClass("is-collapsed") && !onCircle)) return;
        if (!this.host.intoCraft?.(path)) return;
        e.preventDefault(); e.stopPropagation();
        this.intoStats.sent++;
        this.panelOf(path)?.leaf.detach();
      }, true);
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
      if (opts.at && Number.isFinite(opts.at.x) && Number.isFinite(opts.at.y)) {
        p.card.style.right = "auto";
        p.card.style.left = `${Math.round(opts.at.x + 18)}px`;
        p.card.style.top = `${Math.round(opts.at.y - 24)}px`;
        clampToPlane(p.card, plane);
      }
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
    window.dispatchEvent(new CustomEvent("domvec-plane-changed"));   // G-400: 3D draws what the plane does not
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
    // T-4 (PLUGIN_GOAL 142/145): a `{ref}` naming another cell is a COMPILED
    // reference -- a hard link as much as a note link ("hard links happen when
    // one type of cell ... references another cell in any possible way").
    // Planted `plantRefsNotLinks`: note links only, as before.
    if (!this.plantRefsNotLinks) {
      for (const t of this.refTargets(path)) out.add(t);
      for (const p of this.panels) if (p.path !== path && this.refTargets(p.path).has(path)) out.add(p.path);
    }
    out.delete(path);
    return out;
  }
  plantRefsNotLinks = false;
  /** note path -> the open panels its `{name}` references resolve to (by
   *  basename, spaces as underscores, case-folded). Re-read on edit. */
  private refCache = new Map<string, { at: number; names: Set<string> }>();
  refTargets(path: string): Set<string> {
    const f = this.app.vault.getAbstractFileByPath(path);
    if (!(f instanceof TFile)) return new Set();
    // The NAMES a note's braces reference are cached per version of the note;
    // they are resolved against the panels open NOW (a panel opened after the
    // read was never linked -- seen 2026-11-22). Names may hold spaces (N.7):
    // `{notebook 3}` is a reference as much as `{search.results}`.
    let hit = this.refCache.get(path);
    if (!hit || hit.at !== f.stat.mtime) {
      const names = new Set<string>();
      hit = { at: f.stat.mtime, names };
      this.refCache.set(path, hit);
      void this.app.vault.cachedRead(f).then((t) => {
        for (const m of t.matchAll(/\{([^{}\n]+)\}/g)) names.add(m[1].split(".")[0].split("#")[0].trim());
        // A code cell reading another note is a compiled link (194; O-7):
        // `x = Vault.read("folder/note.md")` names that note.
        for (const m of t.matchAll(/Vault\.read\(\s*["']([^"'\n]+)["']/g)) names.add(m[1].replace(/^.*\//, "").replace(/\.md$/, "").trim());
      });
    }
    const key = (n: string) => n.toLowerCase().replace(/[\s_]+/g, "_");
    const byName = new Map(this.panels.map((p) => [key(p.path.slice(p.path.lastIndexOf("/") + 1).replace(/\.md$/, "")), p.path]));
    const to = new Set<string>();
    for (const n of hit.names) { const q = byName.get(key(n)); if (q && q !== path) to.add(q); }
    return to;
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
  chatStats: any = { asks: 0, tokens: 0, context_cells: 0, last_ms: 0, first_token_ms: 0, linked: 0 };
  isTerminal(file: TFile): boolean {
    const fm = this.app.metadataCache.getFileCache(file)?.frontmatter;
    if (fm) return String(fm.domvec || "") === "terminal";
    return false;
  }
  terminalStats = { mounted: 0 };

  /** A conversation note (`domvec: chat`), drawn as the ONE chat interface
   *  (PLUGIN_GOAL 182, G-394): its turns from the note, a clear input box,
   *  its context the panels magnetized to it (134), a piece pulled out of
   *  it landing as its own panel where it is dropped. */
  isChatNote(file: TFile): boolean {
    return String(this.app.metadataCache.getFileCache(file)?.frontmatter?.domvec || "") === "chat";
  }
  chats = new Map<string, ChatUI>();
  /** The ego canvas (183; spec §12c, G-401): the ego slate's component fields. */
  canvas = new EgoCanvas({
    app: this.app,
    members: () => {
      const g: any = this.app.workspace.getLeavesOfType("domvec-graph-view")[0]?.view;
      return [...new Set<string>((g?.craft?.nodes || []).filter((n: any) => n.kind === "note" && n.path).map((n: any) => n.path))];
    },
  });
  /** Planted (G-404): a card dropped on a card writes a wiki link (136 forbids it). */
  plantCardLinks = false;
  /** The ego canvas IS the ego slate (54 "one ego"; spec §12c): its component
   *  fields brought up to date, the cockpit opened at the plane's centre (183). */
  async openCanvas(): Promise<any> {
    this.linksOn();
    await this.canvas.sync();
    const cp: any = (this.app as any).plugins?.getPlugin?.("domvec-bridge")?.cockpit;
    const v = await cp?.open?.();
    const card: HTMLElement | null = cp?.card || null, plane = this.host.plane();
    if (card && plane) {
      const w = Math.min(560, Math.round(plane.clientWidth * 0.62));
      card.style.width = w + "px"; card.style.right = "auto";
      card.style.left = Math.round((plane.clientWidth - w) / 2) + "px";
      card.style.top = Math.max(8, Math.round(plane.clientHeight * 0.08)) + "px";
    }
    return v;
  }
  /** L-1: the chat role of the one model table (`models.ROLES["chat"]`). */
  static CHAT_MODEL = "Nous Hermes 2 Mistral DPO";
  private async chatMount(card: HTMLElement, file: TFile): Promise<() => void> {
    card.addClass("is-chat");
    const ui = new ChatUI(this.app, file, {
      model: () => String(this.app.metadataCache.getFileCache(file)?.frontmatter?.model || PlaneDesk.CHAT_MODEL),
      context: () => this.chatContext(file.path),
      stream: (p, ctx, on) => this.host.chatStream ? this.host.chatStream(p, ctx, on) : Promise.reject(new Error("no sidecar chat")),
      pullOut: (piece, at) => this.pullPiece(file.path, piece, at),
    }, card);
    this.chats.set(file.path, ui);
    const ref = this.app.vault.on("modify", (f) => { if (f.path === file.path && !ui.busy) void ui.render(); });
    return () => { this.app.vault.offref(ref); ui.destroy(); this.chats.delete(file.path); };
  }

  /** The context of a chat at `path`: the panels magnetized to it, in
   *  compilation order, then the rest -- truncated to a budget (134, 142). */
  async chatContext(path: string): Promise<string[]> {
    const strip = (t: string) => t.replace(/^---[\s\S]*?---\s*/, "").trim();
    const ctx: string[] = [];
    let budget = 6000;
    const order = this.compileOrder(path).filter((q) => q !== path);
    const rest = this.magnetized(path).filter((q) => !order.includes(q));
    this.chatStats.order = order.slice();
    for (const q of [...order, ...rest]) {
      const g = this.app.vault.getAbstractFileByPath(q) as TFile | null;
      if (!g || budget <= 0) continue;
      const t = strip(await this.app.vault.read(g)).slice(0, budget);
      if (t) { ctx.push(t); budget -= t.length; }
    }
    this.chatStats.asks++; this.chatStats.context_cells = ctx.length;
    return ctx;
  }

  /** A piece pulled out of a conversation (182): its own note, typed by
   *  what it is (a code block a code cell, prose a markdown panel), its
   *  frontmatter naming the address it came from, opened where it was
   *  dropped. Being a vault note it is retrieved and linked like any other. */
  pullStats = { pulled: 0, last: null as any };
  async pullPiece(from: string, piece: Piece, at: { x: number; y: number }): Promise<string> {
    const NL = String.fromCharCode(10), BT = String.fromCharCode(96).repeat(3);
    const dir = from.includes("/") ? from.slice(0, from.lastIndexOf("/")) : PLANE_FOLDER;
    const base = from.slice(from.lastIndexOf("/") + 1).replace(/\.md$/, "");
    const tag = piece.address.slice(piece.address.indexOf("#") + 1).replace(/\//g, " ");
    let path = "";
    for (let i = 1; ; i++) { path = `${dir}/${base} ${tag}${i > 1 ? " " + i : ""}.md`; if (!this.app.vault.getAbstractFileByPath(path)) break; }
    const body = piece.kind === "code" ? [BT + piece.lang, piece.text, BT] : [piece.text];
    const text = ["---", "domvec: " + (piece.kind === "code" ? "code-output" : "piece"), "from: " + JSON.stringify(piece.address), "---", "", ...body, ""].join(NL);
    await this.create("notebook", { path, text });
    const c = this.panelOf(path)?.card, plane = this.host.plane();
    if (c && plane) {
      const r = plane.getBoundingClientRect();
      c.style.right = "auto";
      c.style.left = `${Math.round(at.x - r.left)}px`;
      c.style.top = `${Math.round(at.y - r.top)}px`;
      clampToPlane(c, plane);
    }
    this.pullStats.pulled++; this.pullStats.last = { path, address: piece.address, kind: piece.kind, lines: piece.lines || null };
    return path;
  }
  /** A terminal cell: its note on top (what it is for), a live PowerShell
   *  session beneath, in the same card -- so it snaps like any cell. */
  private async terminalMount(card: HTMLElement, Leaf?: any): Promise<() => void> {
    Leaf = Leaf || (this.app.workspace as any).activeLeaf?.constructor || (this.app.workspace.getMostRecentLeaf() as any)?.constructor;
    const tl = new Leaf(this.app);
    tl.containerEl.addClass("domvec-plane-terminal");
    card.appendChild(tl.containerEl);
    await tl.setViewState({ type: TERMINAL_VIEW, active: false });
    this.terminalStats.mounted++;
    return () => { try { tl.detach(); } catch { /* gone with the card */ } };
  }

  /**
   * COMPILATION ORDER (PLUGIN_GOAL 142, ruling T-11): "Magnetization means a
   * temporary link for compilation serialization (up to down, left to
   * right)". The magnet-connected group of `path` (magnets only, never
   * links), read row-major: rows by top edge (cards whose tops lie within
   * half the shorter card's height share a row), left to right within a row.
   * Planted `plantMagnetBfsOrder`: the order the magnets were walked in.
   */
  plantMagnetBfsOrder = false;
  compileOrder(path: string): string[] {
    const sides = ["magnetLeft", "magnetRight", "magnetTop", "magnetBottom"];
    const seen = new Set<string>([path]), bfs = [path], queue = [path];
    while (queue.length) {
      const at = queue.shift()!;
      const mine = this.panelOf(at)?.card;
      const next = new Set<string>();
      if (mine) for (const k of sides) { const v = (mine.dataset as any)[k]; if (v) next.add(v); }
      for (const p of this.panels) for (const k of sides) if ((p.card.dataset as any)[k] === at) next.add(p.path);
      for (const n of next) if (!seen.has(n) && this.panelOf(n)) { seen.add(n); bfs.push(n); queue.push(n); }
    }
    if (this.plantMagnetBfsOrder) return bfs;
    const box = (q: string) => { const c = this.panelOf(q)!.card; return { t: c.offsetTop, l: c.offsetLeft, h: c.offsetHeight }; };
    const items = bfs.map((q) => ({ q, ...box(q) })).sort((a, b) => a.t - b.t);
    const rows: typeof items[] = [];
    for (const it of items) {
      const row = rows[rows.length - 1];
      if (row && Math.abs(it.t - row[0].t) < 0.5 * Math.min(it.h, row[0].h)) row.push(it); else rows.push([it]);
    }
    return rows.flatMap((r) => r.sort((a, b) => a.l - b.l).map((x) => x.q));
  }

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
    const order = this.compileOrder(path).filter((q) => q !== path);
    const rest = this.magnetized(path).filter((q) => !order.includes(q));
    this.chatStats.order = order.slice();
    for (const q of [...order, ...rest]) {
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
    await this.spawnCodeCells(rp, reply);
    return reply;
  }

  /**
   * Each fenced code block of a chat reply becomes its OWN code cell, snapped
   * under the reply (PLUGIN_GOAL 135(c): "SLM model outputs of code artifacts
   * should automatically render and register within the chat context as their
   * own pickable/pullable magnetic nodes"). They are magnetized, so they are
   * the chat's context too, and can be pulled away like any cell. Planted
   * `plantNoCodeCells`: the code stays inside the reply only.
   */
  plantNoCodeCells = false;
  codeCellStats = { spawned: 0 };
  async spawnCodeCells(replyPath: string, reply: string): Promise<string[]> {
    if (this.plantNoCodeCells) return [];
    const NL = String.fromCharCode(10), BT = String.fromCharCode(96).repeat(3);
    const re = new RegExp(BT + "([\\w+-]*)" + NL + "([\\s\\S]*?)" + BT, "g");
    const made: string[] = [];
    const dir = replyPath.includes("/") ? replyPath.slice(0, replyPath.lastIndexOf("/")) : "";
    const base = replyPath.slice(replyPath.lastIndexOf("/") + 1).replace(/\.md$/, "");
    let m: RegExpExecArray | null, i = 0, above = replyPath;
    while ((m = re.exec(reply))) {
      const lang = m[1] || "python", code = m[2].replace(/\s+$/, "");
      if (!code.trim()) continue;
      i++;
      const path = `${dir ? dir + "/" : ""}${base} code ${i}.md`;
      if (this.app.vault.getAbstractFileByPath(path)) continue;
      await this.create("notebook", { path, text: ["---", "domvec: code-output", "from: " + replyPath, "---", "", BT + lang, code, BT, ""].join(NL) });
      const c = this.panelOf(path)?.card, a = this.panelOf(above)?.card;
      if (c && a) {
        c.style.right = "auto"; c.style.left = a.style.left || `${a.offsetLeft}px`;
        c.style.top = `${a.offsetTop + a.offsetHeight}px`;
        c.dataset.magnetTop = above;
      }
      above = path; made.push(path); this.codeCellStats.spawned++;
    }
    return made;
  }

  /**
   * PLUGIN_GOAL 135(b): "a single gesture allows the user to flip between the
   * two representations depending on where they are localized". A double-click
   * on the plane's empty ground flips the panels around that spot from panel
   * form to graph form -- each folds to its node, and the links between them
   * (note links either way, and magnets) are drawn as undirected edges -- and
   * the same gesture flips them back. Planted `plantFlipNoLinks`: nodes, no edges.
   */
  flipped: { members: string[]; svg: SVGSVGElement; timer: number } | null = null;
  flipStats = { flips: 0, back: 0, last: null as any };
  plantFlipNoLinks = false;
  static FLIP_RADIUS = 700;
  private flipHooked = new WeakSet<HTMLElement>();
  private flipUnhook: (() => void)[] = [];
  private hookFlip(plane: HTMLElement): void {

    // The plane is click-through (pointer-events: none): its empty ground is
    // the 3D canvas beneath, so the gesture is heard there -- on the bare
    // canvas only, never on a panel, a tool or a billboard.
    const ground = plane.parentElement || plane;
    // One listener per GROUND: the plane is rebuilt under the same canvas,
    // and two listeners flipped and flipped back on one double-click.
    if (this.flipHooked.has(ground)) return;
    this.flipHooked.add(ground);
    const onDbl = (e: MouseEvent) => {
      if ((e as any).__domvecFlip) return;
      const t = e.target as HTMLElement;
      if (!(t?.classList?.contains("domvec-plane") || t?.tagName === "CANVAS")) return;
      // Double-clicking a Craft node or 3D world node on the canvas belongs to
      // that node (open/close panel or fly to linked node), not a ground flip.
      const gv: any = (this.app as any).workspace?.getLeavesOfType?.("domvec-graph-view")?.[0]?.view;
      if (gv?.craft?.nodeAt?.(e.clientX, e.clientY) || gv?.nodeAtScreen?.(e.clientX, e.clientY)) return;
      (e as any).__domvecFlip = true;
      e.preventDefault(); e.stopPropagation();
      const now = this.host.plane(); if (!now) return;
      const r = now.getBoundingClientRect();
      this.flip(e.clientX - r.left, e.clientY - r.top);
    };
    ground.addEventListener("dblclick", onDbl);
    this.flipUnhook.push(() => ground.removeEventListener("dblclick", onDbl));
  }
  /**
   * WIRING in graph form (UR N.4; RESERVOIR_DESIGN 8b "left-drag wiring in
   * graph form"): a node dragged onto another node writes a reference from
   * the first note to the second -- a hard link, because one cell now
   * references another (PLUGIN_GOAL 142) -- and springs back. The flip's
   * edges are recomputed, so the new link is drawn at once. Only while
   * flipped, and only between two of its nodes. Planted `plantNoWiring`.
   */
  plantNoWiring = false;
  wireStats = { wired: 0, refused: 0, last: null as any };
  wireDrop(from: string, x: number, y: number): boolean {
    // Off the plane onto a tab bar: the card becomes a tab (2026-11-25, tabdrag.ts).
    const pc = this.panelOf(from);
    if (pc && toTabs(this.app, pc.card, from, x, y)) { this.closePath(from); return true; }
    // A record placed EXTERNAL (G-403) dropped back on the slate that holds its
    // field: the card closes and the field is revealed again, internal.
    for (const [key, ref] of this.externals) {
      const [host, rec] = key.split("|");
      if (rec !== from || !this.revealIn) continue;
      const c = this.panelOf(host)?.card.getBoundingClientRect();
      if (c && x >= c.left && x <= c.right && y >= c.top && y <= c.bottom) {
        this.externals.delete(key); this.closePath(from); void this.revealIn(host, ref); this.drawLinks();
        return true;
      }
    }
    // A pulled cell's card (pullapart.ts) dropped on a panel goes back in.
    const ff = this.app.vault.getAbstractFileByPath(from);
    if (ff instanceof TFile && String(this.app.metadataCache.getFileCache(ff)?.frontmatter?.domvec || "") === "cell" && this.host.pullInto) {
      const hit = this.panels.some((q) => { if (q.path === from) return false; const c = q.card.getBoundingClientRect(); return x >= c.left && x <= c.right && y >= c.top && y <= c.bottom; });
      if (hit) { void this.host.pullInto(from, x, y); return true; }
    }
    // A card dropped on another card is PLACEMENT, never a link (136: "magnetizing
    // new panels together doesn't create new links between panels. That comes
    // from the compilation aspect"; G-404). Links come only from compilation
    // (`{ref}`s, def/use). Wiring survives only inside the retired, planted
    // flip form it always belonged to. Planted `plantCardLinks`: a card dropped
    // on a card writes a wiki link (G-399's slice, which wrote `[[browser]]` x3
    // into the canvas note when the canvas was moved).
    const f = this.flipped;
    if (!f && !this.plantCardLinks) { this.wireStats.refused = (this.wireStats.refused || 0) + 1; return false; }
    const members = f ? f.members : this.panels.filter((q) => !q.card.hasClass("is-collapsed")).map((q) => q.path);
    if (this.plantNoWiring || !members.includes(from)) return false;
    const to = members.find((m) => {
      if (m === from) return false;
      const c = this.panelOf(m)?.card.getBoundingClientRect();
      return !!c && x >= c.left - 8 && x <= c.right + 8 && y >= c.top - 8 && y <= c.bottom + 8;
    });
    if (!to) return false;
    const src = this.app.vault.getAbstractFileByPath(from), dst = this.app.vault.getAbstractFileByPath(to);
    if (!(src instanceof TFile) || !(dst instanceof TFile)) return false;
    const link = this.app.fileManager.generateMarkdownLink(dst, src.path);
    void this.app.vault.process(src, (t) => t.replace(/\s*$/, "") + String.fromCharCode(10, 10) + link + String.fromCharCode(10)).then(() => {
      // Re-drawn once the link is resolved: flip back and forth over the same members.
      // Once Obsidian has RESOLVED the new link (polled, up to 4 s): a fixed
      // 700 ms redrew before it, and the new edge was not drawn.
      let tries = 0;
      const wait = () => { if (!this.linkedTo(from).has(to) && ++tries < 40) { window.setTimeout(wait, 100); return; } redraw(); };
      const redraw = () => { const keep = this.flipped; if (!keep) { this.drawLinks(); return; } const pr = this.host.plane()?.getBoundingClientRect(); if (!pr) return;
        const c = this.panelOf(from)?.card.getBoundingClientRect(); if (!c) return;
        this.flip(0, 0); this.flip(c.left - pr.left + c.width / 2, c.top - pr.top + c.height / 2); };
      wait();
    });
    this.wireStats.wired++; this.wireStats.last = { from, to };
    return true;
  }

  /** Flip the panels within reach of (x, y) in plane coordinates; again flips back. */
  /** RETIRED by PLUGIN_GOAL 183 (G-399): there is no graph form in 2D -- the
   *  links between panels are always drawn (G-398). A flip already open is
   *  closed; a new one is refused. Planted `plantFlipForm`: as before. */
  plantFlipForm = false;
  flip(x: number, y: number): string[] {
    const plane = this.host.plane();
    if (!plane) return [];
    if (!this.flipped && !this.plantFlipForm) { (this.flipStats as any).refused = ((this.flipStats as any).refused || 0) + 1; return []; }
    if (this.flipped) {
      const f = this.flipped; this.flipped = null;
      window.clearInterval(f.timer); f.svg.remove();
      for (const m of f.members) { const q = this.panelOf(m); if (q && q.card.hasClass("is-collapsed")) this.toggleMinimized(m); }
      this.flipStats.back++; this.flipStats.last = { back: f.members };
      return [];
    }
    const pr = plane.getBoundingClientRect();
    const centre = (q: PlanePanel) => { const c = q.card.getBoundingClientRect(); return { x: c.left - pr.left + c.width / 2, y: c.top - pr.top + c.height / 2 }; };
    const members = this.panels.filter((q) => {
      if (q.card.hasClass("is-collapsed")) return false;
      const c = q.card.getBoundingClientRect();
      // Near the spot: its nearest point within reach.
      const nx = Math.max(c.left - pr.left, Math.min(x, c.right - pr.left)), ny = Math.max(c.top - pr.top, Math.min(y, c.bottom - pr.top));
      return Math.hypot(nx - x, ny - y) <= PlaneDesk.FLIP_RADIUS;
    }).map((q) => q.path);
    for (const m of members) this.toggleMinimized(m);
    const NS = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(NS, "svg") as SVGSVGElement;
    svg.classList.add("domvec-flip-edges");
    plane.appendChild(svg);
    const pairs: [string, string][] = [];
    if (!this.plantFlipNoLinks) {
      for (let i = 0; i < members.length; i++) {
        const a = members[i], la = this.linkedTo(a), ma = new Set(this.magnetized(a));
        for (let j = i + 1; j < members.length; j++) { const b = members[j]; if (la.has(b) || ma.has(b)) pairs.push([a, b]); }
      }
    }
    const draw = () => {
      svg.setAttribute("width", String(plane.scrollWidth)); svg.setAttribute("height", String(plane.scrollHeight));
      while (svg.firstChild) svg.firstChild.remove();
      for (const [a, b] of pairs) {
        const qa = this.panelOf(a), qb = this.panelOf(b);
        if (!qa || !qb) continue;
        const ca = centre(qa), cb = centre(qb);
        const l = document.createElementNS(NS, "line");
        l.setAttribute("x1", String(ca.x + plane.scrollLeft)); l.setAttribute("y1", String(ca.y + plane.scrollTop));
        l.setAttribute("x2", String(cb.x + plane.scrollLeft)); l.setAttribute("y2", String(cb.y + plane.scrollTop));
        l.dataset.a = a; l.dataset.b = b;
        svg.appendChild(l);
      }
    };
    draw();
    const timer = window.setInterval(draw, 200);
    this.flipped = { members, svg, timer };
    this.flipStats.flips++; this.flipStats.last = { at: [Math.round(x), Math.round(y)], members, edges: pairs.length };
    return members;
  }

  /**
   * LINKS BETWEEN PANELS (183, G-398): every pair of open cards whose notes
   * link to each other (either way -- a wiki link, an embed, the ego canvas's
   * own `[[...]]` lines) is joined by a line on the plane, border to border,
   * kept in step as cards move. A graph of panels, not of circles: the line
   * is the only graph mark on the plane. Planted `plantNoPlaneLinks`: none.
   */
  plantNoPlaneLinks = false;
  /** Planted (G-404): the plane's lines follow wiki links as well (T-4 forbids it). */
  plantWikiLines = false;
  /** G-403: resolved-external placements, "host|record" -> the {ref} name. Their line is solid. */
  externals = new Map<string, string>();
  /** Set by the plugin: reveal `ref` in `host`'s slate again (G-403's way back). */
  revealIn: ((host: string, ref: string) => Promise<any>) | null = null;
  linkStats = { edges: 0, pairs: [] as string[][] };
  private linkSvg: SVGSVGElement | null = null;
  private linkTimer = 0;
  linksOn(): void {
    if (this.linkTimer) return;
    this.linkTimer = window.setInterval(() => this.drawLinks(), 250);
  }
  linksOff(): void { window.clearInterval(this.linkTimer); this.linkTimer = 0; this.linkSvg?.remove(); this.linkSvg = null; }
  drawLinks(): void {
    const plane = this.host.plane();
    if (!plane) return;
    // The plane takes notes dragged from tabs or the file list (tabdrag.ts).
    acceptTabDrops(this.app, plane, (f, at) => this.open(f, { at }));
    const NS = "http://www.w3.org/2000/svg";
    if (!this.linkSvg || !plane.contains(this.linkSvg)) {
      this.linkSvg?.remove();
      this.linkSvg = document.createElementNS(NS, "svg") as SVGSVGElement;
      this.linkSvg.classList.add("domvec-plane-links");
      plane.prepend(this.linkSvg);                 // behind every card
    }
    const svg = this.linkSvg;
    while (svg.firstChild) svg.firstChild.remove();
    const pairs: string[][] = [];
    if (!this.plantNoPlaneLinks) {
      const open = this.panels.filter((q) => !q.card.hasClass("is-collapsed") && q.card.isConnected);
      for (let i = 0; i < open.length; i++) {
        // Lines come from COMPILATION only (136, 142; spec §12d, G-404): a
        // `{ref}` naming the other record. A plain wiki link is a plain link
        // (T-4) and draws nothing. Planted `plantWikiLines`: wiki links too.
        const rel = (q: string) => this.plantWikiLines ? this.linkedTo(q) : this.refTargets(q);
        const la = rel(open[i].path);
        for (let j = i + 1; j < open.length; j++) {
          if (la.has(open[j].path) || rel(open[j].path).has(open[i].path)) pairs.push([open[i].path, open[j].path]);
        }
      }
    }
    const pr = plane.getBoundingClientRect();
    svg.setAttribute("width", String(plane.scrollWidth)); svg.setAttribute("height", String(plane.scrollHeight));
    // The point where the segment between two centres leaves a card's box.
    const exit = (r: DOMRect, tx: number, ty: number) => {
      const cx = r.left + r.width / 2, cy = r.top + r.height / 2, dx = tx - cx, dy = ty - cy;
      const k = Math.min(Math.abs(dx) > 1e-6 ? (r.width / 2) / Math.abs(dx) : Infinity, Math.abs(dy) > 1e-6 ? (r.height / 2) / Math.abs(dy) : Infinity, 1);
      return { x: cx + dx * k - pr.left + plane.scrollLeft, y: cy + dy * k - pr.top + plane.scrollTop };
    };
    for (const [a, b] of pairs) {
      const ra = this.panelOf(a)!.card.getBoundingClientRect(), rb = this.panelOf(b)!.card.getBoundingClientRect();
      const pa = exit(ra, rb.left + rb.width / 2, rb.top + rb.height / 2), pb = exit(rb, ra.left + ra.width / 2, ra.top + ra.height / 2);
      const l = document.createElementNS(NS, "line");
      l.setAttribute("x1", String(pa.x)); l.setAttribute("y1", String(pa.y));
      l.setAttribute("x2", String(pb.x)); l.setAttribute("y2", String(pb.y));
      l.dataset.a = a; l.dataset.b = b;
      if (this.externals.has(a + "|" + b) || this.externals.has(b + "|" + a)) l.classList.add("is-external");
      svg.appendChild(l);
    }
    this.linkStats.edges = pairs.length; this.linkStats.pairs = pairs;
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
      // Its OWN header only: a card inside this one has its own (seen
      // 2026-11-22: a right-click on an inner title minimized the outer card).
      if (!onHead || t.closest(".domvec-plane-card") !== p.card) return;
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
      if (!t?.closest?.(".domvec-plane-head-node, .domvec-var-title, .domvec-slate-circle-dot") || t.closest(".domvec-plane-card") !== p.card) return;
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

  // ---- PLUGIN_GOAL 135(c)(d), 136: memory links on the plane -------------
  //
  // "magnetizing new panels together doesn't create new links between panels.
  // That comes from the compilation aspect and function-object undirected
  // bidirectional forward-inverse calls on the computation graph as the
  // reservoir of memory-linked artifacts" (136); "Solid computational links
  // can be turned 'on' and 'off' with a gesture (perhaps a right click on a
  // clearly clickable solid undirected link) that is either semi translucent
  // or solid" (135d); a chat's code outputs "with solid links" (135c).
  //
  // So a link between two plane panels is drawn ONLY from the computation
  // graph: a recorded run whose input is another panel's note (`/signal`,
  // the forward call and its inverse lookup), and a code-output cell's
  // `from:` its reply. Snapping (magnets) is placement and never a link. A
  // right-click on a link toggles it solid / translucent, and the state is
  // KEPT across reloads by the pair's key. Planted `plantNoMemoryLinks`.
  plantNoMemoryLinks = false;
  memoryStats = { pairs: 0, from_signal: 0, from_output: 0, toggles: 0, drawn: 0 };
  private memSvg: SVGSVGElement | null = null;
  private memTimer = 0;
  private memSignal: { note: string; path: string }[] = [];
  private memSignalAt = -1e9;
  static MEM_KEY = "domvec-memory-links";
  private memState(): Record<string, boolean> {
    try { return JSON.parse(window.localStorage.getItem(PlaneDesk.MEM_KEY) || "{}"); } catch { return {}; }
  }
  private memSave(st: Record<string, boolean>): void {
    try { window.localStorage.setItem(PlaneDesk.MEM_KEY, JSON.stringify(st)); } catch { /* a convenience */ }
  }
  static pairKey(a: string, b: string): string { return a < b ? a + "|" + b : b + "|" + a; }
  /** The panel pairs the computation graph links, among the panels open now. */
  memoryPairs(): [string, string][] {
    const open = new Set(this.panels.map((p) => p.path));
    const out = new Map<string, [string, string]>();
    let sig = 0, outp = 0;
    for (const e of this.memSignal) {
      if (e.note !== e.path && open.has(e.note) && open.has(e.path)) { out.set(PlaneDesk.pairKey(e.note, e.path), [e.note, e.path]); sig++; }
    }
    for (const p of this.panels) {
      const f = this.app.vault.getAbstractFileByPath(p.path);
      const fm: any = f instanceof TFile ? this.app.metadataCache.getFileCache(f)?.frontmatter : null;
      const from = fm && typeof fm.from === "string" ? fm.from : "";
      if (from && open.has(from)) { out.set(PlaneDesk.pairKey(p.path, from), [p.path, from]); outp++; }
    }
    this.memoryStats.from_signal = sig; this.memoryStats.from_output = outp; this.memoryStats.pairs = out.size;
    return [...out.values()];
  }
  /** Refresh the recorded runs (forward calls) from the store, at most every 10 s. */
  async memRefreshSignal(force = false): Promise<void> {
    if (!force && performance.now() - this.memSignalAt < 10000) return;
    this.memSignalAt = performance.now();
    const P: any = (this.app as any).plugins?.plugins?.["domvec-bridge"];
    let got: any = null;
    try { got = await P?.sidecar?.signal?.(2000); } catch { got = null; }
    const edges: any[] = (got && got.edges) || [];
    this.memSignal = edges.map((e: any) => {
      const u = String(e.url || "");
      const path = u.startsWith("vault://") ? decodeURIComponent(u.replace(/^vault:\/\/[^/]*\//, "")) : "";
      return { note: String(e.note || ""), path };
    }).filter((e) => e.note && e.path);
  }
  memDraw(): void {
    const plane = this.host.plane();
    if (!plane) return;
    if (this.plantNoMemoryLinks) { this.memSvg?.remove(); this.memSvg = null; this.memoryStats.drawn = 0; return; }
    const NS = "http://www.w3.org/2000/svg";
    if (!this.memSvg || !plane.contains(this.memSvg)) {
      this.memSvg = document.createElementNS(NS, "svg") as SVGSVGElement;
      this.memSvg.classList.add("domvec-memory-links");
      plane.appendChild(this.memSvg);
    }
    const svg = this.memSvg;
    svg.setAttribute("width", String(plane.scrollWidth)); svg.setAttribute("height", String(plane.scrollHeight));
    const pr = plane.getBoundingClientRect(), st = this.memState();
    const pairs = this.memoryPairs();
    const want = new Set(pairs.map(([a, b]) => PlaneDesk.pairKey(a, b)));
    for (const l of Array.from(svg.querySelectorAll("line"))) if (!want.has((l as any).dataset.key)) l.remove();
    for (const [a, b] of pairs) {
      const key = PlaneDesk.pairKey(a, b);
      const pa = this.panelOf(a), pb = this.panelOf(b);
      if (!pa || !pb) continue;
      const ra = pa.card.getBoundingClientRect(), rb = pb.card.getBoundingClientRect();
      const ca = { x: ra.left + ra.width / 2, y: ra.top + ra.height / 2 }, cb = { x: rb.left + rb.width / 2, y: rb.top + rb.height / 2 };
      // Edge to edge: from each card's border toward the other's centre.
      const clip = (c: any, r: DOMRect, to: any) => {
        const dx = to.x - c.x, dy = to.y - c.y;
        const t = Math.min(Math.abs((r.width / 2) / (dx || 1e-9)), Math.abs((r.height / 2) / (dy || 1e-9)), 1);
        return { x: c.x + dx * t - pr.left + plane.scrollLeft, y: c.y + dy * t - pr.top + plane.scrollTop };
      };
      const p1 = clip(ca, ra, cb), p2 = clip(cb, rb, ca);
      let line = Array.from(svg.querySelectorAll("line")).find((l) => (l as any).dataset.key === key) as SVGLineElement | undefined;
      if (!line) {
        line = document.createElementNS(NS, "line") as SVGLineElement;
        (line as any).dataset.key = key; (line as any).dataset.a = a; (line as any).dataset.b = b;
        line.addEventListener("contextmenu", (e) => {
          e.preventDefault(); e.stopPropagation();
          const s2 = this.memState(); s2[key] = s2[key] === false; this.memSave(s2);
          this.memoryStats.toggles++; this.memDraw();
        });
        svg.appendChild(line);
      }
      const on = st[key] !== false;
      line.setAttribute("x1", String(p1.x)); line.setAttribute("y1", String(p1.y));
      line.setAttribute("x2", String(p2.x)); line.setAttribute("y2", String(p2.y));
      line.setAttribute("stroke-opacity", on ? "0.95" : "0.25");
      (line as any).dataset.on = String(on);
    }
    this.memoryStats.drawn = svg.querySelectorAll("line").length;
  }
  /** PLUGIN_GOAL 150: a card showing a slate's graph form is at least the
   *  graph's size, so the whole graph is grabbable (its overflow fell through
   *  to the 3D canvas: card 180x120 under a 425x284 graph). Planted
   *  `plantGraphOverflow`. */
  plantGraphOverflow = false;
  intoStats = { sent: 0 };
  fitGraphCards(): void {
    const cpCard: HTMLElement | null = (this.app as any).plugins?.plugins?.["domvec-bridge"]?.cockpit?.card || null;
    const cards = this.panels.map((p) => p.card).concat(cpCard && cpCard.isConnected ? [cpCard] : []);
    for (const card of cards) {
      const g = card.querySelector(".domvec-slate-graph") as HTMLElement | null;
      if (!g || this.plantGraphOverflow) { if (card.dataset.graphFit) { card.style.minWidth = ""; card.style.minHeight = ""; delete card.dataset.graphFit; } continue; }
      const gr = g.getBoundingClientRect(), cr = card.getBoundingClientRect();
      const w = Math.ceil(gr.right - cr.left + 8), h = Math.ceil(gr.bottom - cr.top + 8);
      if (w > cr.width || h > cr.height) { card.style.minWidth = `${Math.max(w, cr.width)}px`; card.style.minHeight = `${Math.max(h, cr.height)}px`; card.dataset.graphFit = "1"; }
    }
  }
  /** Start drawing memory links on the plane (once the plane exists). */
  startMemoryLinks(): void {
    if (this.memTimer) return;
    const tick = () => { this.fitGraphCards(); void this.memRefreshSignal().then(() => this.memDraw()); };
    tick();
    this.memTimer = window.setInterval(tick, 400);
  }

  unload(): void {
    if (this.memTimer) { window.clearInterval(this.memTimer); this.memTimer = 0; } this.memSvg?.remove(); this.memSvg = null;
    for (const u of this.flipUnhook) u(); this.flipUnhook = [];
    if (this.flipped) { window.clearInterval(this.flipped.timer); this.flipped.svg.remove(); this.flipped = null; }
    // Unloading is not the reader closing them: the list is kept for the reload.
    for (const p of [...this.panels]) this.close(p.leaf, undefined, false);
    this.toolsEl?.remove();
    this.toolsEl = null;
  }
}
