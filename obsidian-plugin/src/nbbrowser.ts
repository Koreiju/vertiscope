/**
 * The browser cell INSIDE a notebook -- `G-36`'s second host.
 *
 * "the webbrowser notebook cells should be actual electron browser cells,
 * resizable within the notebook, as well as allowing it to resize along with
 * the rest of the notebook within its panel window" -- and "the completeness
 * of functionalities are the same" as the standalone cell.
 *
 * So this is not a second browser. A ```` ```browser ```` fence (its first
 * line the url) is rendered as the SAME `BrowserView` the standalone pane is,
 * in a workspace leaf of its own that is not in the workspace's tree (the way
 * hover popovers host a view): the same sensor, overlay, right-click markdown
 * face, chat and captures to the store and the 3D view. The leaf's container
 * sits in a frame the reader drags to resize (height); its width is the
 * note's, so it resizes with the notebook's pane. A webview flows with the DOM
 * (why `<webview>` was chosen, `G-36`), so the page's viewport follows both.
 * The leaf is detached when Obsidian unloads the rendered block.
 */
import { MarkdownRenderChild, setIcon, type App } from "obsidian";
import { BROWSER_VIEW } from "./browser";

export const BROWSER_FENCE = "browser";

/** Every notebook browser cell rendered now, for the harness. */
export const notebookBrowsers = new Set<NotebookBrowserCell>();

/**
 * D-54 (PLUGIN_GOAL 167 e, 173 c "Both"): a notebook browser cell is a regular
 * browser to Obsidian's leaf lookup -- registered IN PLACE. Its leaf cannot
 * join the workspace's tree (it lives inside a note), so the lookup is taught
 * it: `getLeavesOfType(BROWSER_VIEW)` answers the tree's browser leaves AND
 * every mounted cell's, and `iterateAllLeaves` visits them too. Everything
 * that finds a browser that way -- the browser in use, a reveal, a kernel's
 * `WebBrowser.go`, the 2 s report of what is shown -- reaches the cell where
 * it sits. Undone by the returned function. Planted `__domvecPlantNbUnregistered`:
 * the lookup is the tree's only.
 */
export function registerNotebookLeaves(app: App): () => void {
  const ws: any = app.workspace;
  const byType = ws.getLeavesOfType.bind(ws), every = ws.iterateAllLeaves.bind(ws);
  const cells = () => (window as any).__domvecPlantNbUnregistered ? [] : [...notebookBrowsers].map((c) => c.leaf).filter(Boolean);
  ws.getLeavesOfType = (type: string) => {
    const tree = byType(type);
    return type === BROWSER_VIEW ? [...tree, ...cells().filter((l) => !tree.includes(l))] : tree;
  };
  ws.iterateAllLeaves = (cb: (leaf: any) => any) => { every(cb); for (const l of cells()) cb(l); };
  return () => { ws.getLeavesOfType = byType; ws.iterateAllLeaves = every; };
}

export class NotebookBrowserCell extends MarkdownRenderChild {
  leaf: any = null;
  constructor(private app: App, containerEl: HTMLElement, readonly url: string, readonly sourcePath: string) {
    super(containerEl);
  }

  get view(): any { return this.leaf?.view ?? null; }

  private sizes: ResizeObserver | null = null;
  /** Times the browser was mounted / put away as the frame showed or hid. */
  mounts = 0;
  unmounts = 0;
  /** D-54: tabs opened from this cell. */
  poppedOut = 0;

  /**
   * D-54 (173 c): the cell's page in a regular workspace tab -- a new browser
   * leaf in the tree, sent to the url the cell shows NOW (not the fence's
   * first one). The cell stays in the note.
   */
  async popOut(): Promise<any> {
    let url = this.url;
    try { const v = this.view; url = (typeof v?.shownUrl === "function" ? v.shownUrl() : v?.webview?.getURL()) || url; } catch { /* not loaded */ }
    const leaf = this.app.workspace.getLeaf("tab");
    // The page as the tab's OWN state (137(18), `BrowserView.setState`): a new
    // tab otherwise restores the reader's last shared page on its own clock,
    // and that restore landed after a `go` and replaced it (D-54, run 21).
    await leaf.setViewState({ type: BROWSER_VIEW, active: true, state: { url } });
    const v: any = leaf.view;
    for (let i = 0; i < 100; i++) {
      try { v.webview?.getURL(); break; } catch { await new Promise((r) => setTimeout(r, 100)); }
    }
    let now = ""; try { now = v.webview?.getURL() || ""; } catch { /* not ready */ }
    if (now.split("#")[0] !== url.split("#")[0]) { try { v.go(url); } catch { /* the tab went away */ } }
    this.app.workspace.setActiveLeaf(leaf, { focus: true });
    this.poppedOut++;
    return leaf;
  }

  /**
   * Lazy, and only while SEEN. Obsidian keeps a note's live-preview editor
   * alive behind its reading view, so a fence is rendered twice; a browser
   * in each would be two webviews and two sensors on one page. The browser
   * is mounted while its frame is laid out and put away when it is hidden.
   */
  onload(): void {
    notebookBrowsers.add(this);
    this.sizes = new ResizeObserver(() => {
      const shown = this.containerEl.offsetWidth > 0 && this.containerEl.offsetHeight > 0;
      if (shown && !this.leaf) void this.mount();
      else if (!shown && this.leaf) this.unmount();
    });
    this.sizes.observe(this.containerEl);
  }

  private async mount(): Promise<void> {
    const Leaf = (this.app.workspace as any).activeLeaf?.constructor
      ?? this.app.workspace.getLeavesOfType("markdown")[0]?.constructor;
    if (!Leaf) { this.containerEl.setText("(no workspace leaf to host the browser cell)"); return; }
    this.leaf = new Leaf(this.app);
    // Before its view opens: the view reads `hosted` as it restores (D-54).
    this.leaf.__domvecHosted = true;
    this.mounts++;
    this.containerEl.appendChild(this.leaf.containerEl);
    // The pop-out (D-54): one control on the frame's corner, a field to press
    // rather than a verb to type.
    if (!this.containerEl.querySelector(":scope > .domvec-nb-popout")) {
      const b = this.containerEl.createEl("button", { cls: "domvec-nb-popout clickable-icon", attr: { "aria-label": "Open this page in a tab" } });
      setIcon(b, "external-link");
      b.style.cssText = "position:absolute;top:2px;right:2px;z-index:5;padding:2px;height:22px;width:22px";
      b.onclick = (e) => { e.preventDefault(); e.stopPropagation(); void this.popOut(); };
    }
    await this.leaf.setViewState({ type: BROWSER_VIEW, active: false });
    const v = this.view;
    if (!v || !this.url || typeof v.go !== "function") return;
    // A webview takes no `loadURL` until it is attached and dom-ready; before
    // then the call throws, and `getURL` with it -- which is the gate.
    for (let i = 0; i < 100 && this.leaf; i++) {
      try { v.webview?.getURL(); break; } catch { await new Promise((r) => setTimeout(r, 100)); }
    }
    if (this.leaf && this.view === v) { try { v.go(this.url); } catch { /* the cell went away */ } }
  }

  private unmount(): void {
    try { this.leaf?.detach(); } catch { /* already gone */ }
    this.leaf?.containerEl?.remove();
    this.leaf = null;
    this.unmounts++;
  }

  onunload(): void {
    notebookBrowsers.delete(this);
    this.sizes?.disconnect();
    if (this.leaf) this.unmount();
  }
}

/** The fence processor: one browser cell per ```browser block. Planted
 *  `__domvecPlantNoNotebookBrowser`: the url stays a plain code block. */
export function browserFence(app: App) {
  return (source: string, el: HTMLElement, ctx: { sourcePath: string; addChild: (c: MarkdownRenderChild) => void }) => {
    const url = (source.trim().split(/\r?\n/)[0] || "about:blank").trim();
    if ((window as any).__domvecPlantNoNotebookBrowser) { el.createEl("pre", { text: source }); return; }
    const frame = el.createDiv({ cls: "domvec-nb-browser" });
    frame.setAttr("data-url", url);
    ctx.addChild(new NotebookBrowserCell(app, frame, url, ctx.sourcePath));
  };
}
