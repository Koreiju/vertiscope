/**
 * A chunk panel as a MAIN Obsidian pane, for when there is no connection
 * (`G-59`: *"seeing still the billboarded panel that we currently have as a
 * more 'main' panel within obsidian rather than in the UMAP projector"*).
 *
 * Online a chunk opens as a billboard in the 3D view beside the live page.
 * Offline there is no live page to stand beside, so the same panel -- the same
 * element, its page and markdown forms, its controls -- is docked here and
 * takes the pane. Nothing is re-rendered: the graph view moves its billboard
 * element in (`GraphView.dockPanel`), so the two cannot disagree.
 */
import { ItemView, WorkspaceLeaf } from "obsidian";

export const PANEL_VIEW = "vertiscope-panel-view";

export class PanelView extends ItemView {
  /** The chunk whose panel is docked, for the tab title and the harness. */
  cid = "";

  constructor(leaf: WorkspaceLeaf) {
    super(leaf);
  }

  getViewType(): string { return PANEL_VIEW; }
  getDisplayText(): string { return this.cid ? `chunk ${this.cid.slice(0, 8)} (offline)` : "vertiscope chunk (offline)"; }
  getIcon(): string { return "file-text"; }

  async onOpen(): Promise<void> {
    this.contentEl.addClass("vertiscope-panel-pane");
  }

  /** Take the panel element: one panel at a time, the latest. */
  dock(el: HTMLElement, cid: string): void {
    this.contentEl.empty();
    el.addClass("vertiscope-bb-docked");
    el.style.left = "";
    el.style.top = "";
    this.contentEl.appendChild(el);
    this.cid = cid;
    (this.leaf as any).updateHeader?.();
  }
}
