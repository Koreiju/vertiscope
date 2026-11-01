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
import { MarkdownRenderChild, type App } from "obsidian";
import { BROWSER_VIEW } from "./browser";

export const BROWSER_FENCE = "browser";

/** Every notebook browser cell rendered now, for the harness. */
export const notebookBrowsers = new Set<NotebookBrowserCell>();

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
    this.mounts++;
    this.containerEl.appendChild(this.leaf.containerEl);
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
