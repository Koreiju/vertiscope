/**
 * The browser cell as a panel on the plane, with its own cockpit (PLUGIN_GOAL
 * 71-72, 2026-11-01: "our full web browser panel feature + all functionalities
 * should be translated to its draggable panel/computation graph analogue;
 * includes "cockpit" for browser tools/actions on the panel, as well as the
 * actual web browser rendering the interactive HTML").
 *
 * One card on the plane, two leaves: the BROWSER COCKPIT -- a slate note
 * whose fields ARE the browser's tools, bound both ways as the ego cockpit's
 * are (G-280) -- and the browser itself, the same `BrowserView` the
 * standalone pane and the notebook's browser fence are (G-36). The slate's
 * title, `browser`, is the card's header node (item 54): it drags the card,
 * a right-click on it collapses the browser to that node.
 *
 *   browser
 *   	url	https://...        typed: the browser goes there; navigation writes it back
 *   	back	go                 a click on the value: one page back
 *   	forward	go                 ... forward
 *   	scan	go                 ... the page scanned now
 *   	live	true               a click toggles: the page streamed into the store, or not
 *   	boxes	false              ... the chunk outlines shown, or not
 *   	scope	live               live: the real page; page: the page rebuilt from the
 *   	                           store (offline) -- the scope ladder's upper two rungs
 *   	                           (item 72; `chunk` is the billboard's, RESERVOIR_DESIGN 10.2)
 *
 * The browser's own toolbar stays until the slate covers every action (UR
 * S.4: chrome goes, but not before its replacement is seen to work).
 */
import { App, MarkdownView, TFile } from "obsidian";
import { parseSlate, type SlateLine } from "./slatefold";
import type { PlaneDesk } from "./planepanels";

export const BROWSER_COCKPIT_PATH = "domvec/browser.md";
const T = "\t";
const BROWSER_TEXT = ["---", "domvec: slate", "---", "browser",
  T + "url" + T, T + "back" + T + "go", T + "forward" + T + "go", T + "scan" + T + "go",
  T + "live" + T + "true", T + "boxes" + T + "false", T + "scope" + T + "live", ""].join("\n");

export interface BrowserPanelHost { browserViewType: string; desk: PlaneDesk }

export class BrowserPanel {
  browserLeaf: any = null;
  stats = { opened: 0, went: 0, back: 0, forward: 0, scans: 0, toggles: 0, written: 0, scope: "" as string };
  /** Planted (item 71): the cockpit's fields bind nothing. */
  plantUnbound = false;
  private seenUrl = "";
  private scopeTry = 0;
  private hooked = new WeakSet<HTMLElement>();

  constructor(private app: App, private host: BrowserPanelHost) {}

  /** The slate's view on the plane, if open. */
  slateView(): MarkdownView | null { return this.host.desk.viewOf(BROWSER_COCKPIT_PATH); }
  /** The browser's view inside the card, if mounted. */
  view(): any { return this.browserLeaf?.view || null; }

  /** The browser on the plane: its cockpit note (made on first use) and the
   *  browser beneath it, in one card. */
  async open(url = ""): Promise<any> {
    let f = this.app.vault.getAbstractFileByPath(BROWSER_COCKPIT_PATH);
    if (!(f instanceof TFile)) {
      if (!this.app.vault.getAbstractFileByPath("domvec")) await this.app.vault.createFolder("domvec").catch(() => undefined);
      f = await this.app.vault.create(BROWSER_COCKPIT_PATH, BROWSER_TEXT);
    }
    const desk = this.host.desk;
    const existing = desk.panelOf(BROWSER_COCKPIT_PATH);
    await desk.open(f as TFile, {
      mount: async (card: HTMLElement) => {
        card.addClass("domvec-browser-card");
        const Leaf = (this.app.workspace as any).activeLeaf?.constructor ?? (this.app.workspace.getMostRecentLeaf() as any)?.constructor;
        const leaf = new Leaf(this.app);
        leaf.containerEl.addClass("domvec-browser-panel-leaf");
        card.appendChild(leaf.containerEl);
        await leaf.setViewState({ type: this.host.browserViewType, active: false });
        this.browserLeaf = leaf;
        return () => { try { leaf.detach(); } catch { /* gone */ } if (this.browserLeaf === leaf) this.browserLeaf = null; };
      },
    });
    if (!existing) this.stats.opened++;
    const sv = this.slateView();
    if (sv) this.hook(sv);
    if (url) await this.go(url);
    return this.view();
  }

  /** The browser to a url, once its webview takes one (dom-ready). */
  async go(url: string): Promise<void> {
    const v = this.view();
    if (!v || typeof v.go !== "function") return;
    for (let i = 0; i < 100; i++) {
      try { v.webview?.getURL(); break; } catch { await new Promise((r) => setTimeout(r, 100)); }
    }
    try { v.go(url); this.stats.went++; } catch { /* not ready */ }
  }

  private fields(): SlateLine[] {
    const sv = this.slateView();
    return sv ? parseSlate(sv.editor.getValue()) : [];
  }
  private field(fs: SlateLine[], key: string): SlateLine | undefined {
    return fs.find((f) => f.depth === 1 && f.key === key);
  }
  private write(fl: SlateLine, value: string): void {
    const sv = this.slateView();
    if (!sv || fl.value === value) return;
    sv.editor.replaceRange(value, { line: fl.line, ch: fl.valueFrom }, { line: fl.line, ch: fl.valueFrom + fl.value.length });
    this.stats.written++;
  }

  /** A click on an action's or a toggle's VALUE: the slate is the toolbar. */
  private hook(sv: MarkdownView): void {
    const el = sv.contentEl;
    if (this.hooked.has(el)) return;
    this.hooked.add(el);
    el.addEventListener("mousedown", (e: MouseEvent) => {
      if (e.button !== 0 || this.plantUnbound) return;
      const cm: any = (sv.editor as any).cm;
      const pos = cm?.posAtCoords?.({ x: e.clientX, y: e.clientY });
      if (pos == null) return;
      const ln = cm.state.doc.lineAt(pos);
      const fl = this.fields().find((f) => f.line === ln.number - 1 && f.depth === 1);
      if (!fl) return;
      const ch = pos - ln.from;
      if (!(ch >= fl.valueFrom && ch <= fl.valueFrom + fl.value.length && fl.value.length)) return;
      const v = this.view();
      if (!v) return;
      const val = fl.value.trim();
      let acted = true;
      if (fl.key === "back") { const w = v.webview; if (w?.canGoBack?.()) { w.goBack(); this.stats.back++; } }
      else if (fl.key === "forward") { const w = v.webview; if (w?.canGoForward?.()) { w.goForward(); this.stats.forward++; } }
      else if (fl.key === "scan") { void v.scan?.(); this.stats.scans++; }
      else if (val === "true" || val === "false") { this.write(fl, val === "true" ? "false" : "true"); this.stats.toggles++; }
      else if (fl.key === "scope") { this.write(fl, val === "live" ? "page" : "live"); this.stats.toggles++; }
      else acted = false;
      if (acted) { e.preventDefault(); e.stopPropagation(); }
    }, true);
  }

  /** The text read: an edit in the cockpit drives the browser. */
  onEdit(file: TFile | null): void {
    if (!file || file.path !== BROWSER_COCKPIT_PATH || this.plantUnbound) return;
    const v = this.view();
    if (!v) return;
    const fs = this.fields();
    const url = (this.field(fs, "url")?.value || "").trim();
    const shown = String(v.shownUrl?.() || v.webview?.getURL?.() || "");
    if (url && /^(https?:|file:|about:)/.test(url) && url !== shown && url !== this.seenUrl) { this.seenUrl = url; void this.go(url); }
    const live = (this.field(fs, "live")?.value || "").trim();
    if ((live === "true" || live === "false") && (live === "true") !== !!v.live) v.setLive?.(live === "true");
    const boxes = (this.field(fs, "boxes")?.value || "").trim();
    if ((boxes === "true" || boxes === "false") && (boxes === "true") !== !!v.boxesShown?.()) void v.toggleBoxes?.(boxes === "true");
    const scope = (this.field(fs, "scope")?.value || "").trim();
    if (scope && scope !== this.stats.scope) {
      this.stats.scope = scope;
      // The ladder's upper rungs (item 72): the page rebuilt from the store,
      // or the live page again -- the same address either way.
      if (scope === "page" && !v.offlineFor) void v.openOffline?.(shown);
      else if (scope === "live" && v.offlineFor) { const u = v.offlineFor; v.offlineFor = ""; v.go(u); }
    }
  }

  /** The browser's own state written back: where it is now, what is on. */
  sync(): void {
    if (this.plantUnbound) return;
    const v = this.view(), sv = this.slateView();
    if (!v || !sv) return;
    const fs = this.fields();
    const shown = String(v.offlineFor || v.shownUrl?.() || "");
    // `scope` is a declared state, kept: `page` until the store can rebuild
    // the page (a page just visited may not be stored yet), `live` otherwise.
    const scope = (this.field(fs, "scope")?.value || "").trim();
    const now = performance.now();
    if (scope === "page" && !v.offlineFor && now - this.scopeTry > 3000) {
      this.scopeTry = now;
      const u = String(v.shownUrl?.() || v.webview?.getURL?.() || "");
      if (/^https?:/.test(u)) void v.openOffline?.(u);
    }
    const urlF = this.field(fs, "url");
    if (urlF && shown && shown !== "about:blank" && urlF.value.trim() !== shown && shown !== this.seenUrl) {
      this.seenUrl = shown;
      this.write(urlF, shown);
    }
  }

  close(): void { this.host.desk.closePath(BROWSER_COCKPIT_PATH); }
}
