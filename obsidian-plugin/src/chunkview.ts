/**
 * One chunk, on its own, in its own pane.
 *
 * Clicking a node in the 3D graph used to open the NOTE the chunk was
 * exported into, which is a page of a vault: frontmatter, the distilled
 * markdown, a fence, and whatever the reader has since written around it.
 * A node stands for a chunk, so clicking it should show that chunk and
 * nothing else -- as its structured markdown, or as the interactive HTML,
 * because those are the two forms a chunk has.
 *
 * The pane holds a `ChunkSurface`, the same component a `vertiscope` fence in a
 * note holds. One surface, two places it can be mounted: a chunk must not
 * look like one thing inside a note and another in the graph's pane.
 *
 * `addChild` rather than a bare construction, so the surface's fetch and
 * listeners are released when the pane closes. `ItemView` is a `Component`
 * and this is what it is for.
 */

import { ItemView, WorkspaceLeaf } from "obsidian";

import { ChunkSurface, SurfaceHost } from "./surface";

export const CHUNK_VIEW = "vertiscope-chunk-view";

export class ChunkView extends ItemView {
  private cid = "";
  private surface: ChunkSurface | null = null;

  constructor(leaf: WorkspaceLeaf, private host: SurfaceHost,
              private openNote: (cid: string) => void) {
    super(leaf);
  }

  getViewType() { return CHUNK_VIEW; }
  getIcon() { return "file-text"; }

  getDisplayText() {
    return this.cid ? `chunk ${this.cid.slice(0, 8)}` : "vertiscope chunk";
  }

  /** Show a different chunk in the pane that is already open. */
  async show(cid: string) {
    if (cid === this.cid && this.surface) return;
    this.cid = cid;
    await this.render();
    // The tab header is NOT refreshed here. `WorkspaceLeaf.updateHeader` is
    // the call that would do it and it is not in the public API -- the one
    // community plugin that reaches into the graph view's internals warns in
    // its own README that this is how settings get lost. The cid is on the
    // surface's own bar, which is a supported place to put it and is where a
    // reader is already looking.
  }

  /**
   * Re-read this chunk when a capture has just rewritten it (`S-12`).
   *
   * **In trie terms**: a capture writes the dirty chunks to the trie, and an
   * open panel is a reader of one address in it. It read that address once,
   * when it was opened, and nothing told it to read again -- so a write to
   * the very address it is displaying never reached it. Measured: a click
   * that appended a list item landed in the store and in a panel opened
   * afterwards (539 chars, token present) while the panel that was already
   * open sat unchanged at 448 characters.
   *
   * `show` cannot be what fixes this: it takes a cid and returns early when
   * the cid has not changed, which is correct for its own job -- re-rendering
   * on every graph click would throw away the reader's scroll position. What
   * changed here is the CONTENT at an unchanged cid, so the re-read is a
   * separate entry point with a separate trigger.
   */
  async refreshIf(cids: Iterable<string>): Promise<void> {
    if (!this.cid) return;
    for (const cid of cids) {
      if (cid === this.cid) {
        await this.render();
        return;
      }
    }
  }

  async onOpen() {
    await this.render();
  }

  private async render() {
    const root = this.containerEl.children[1] as HTMLElement;
    root.empty();
    root.addClass("vertiscope-chunk-pane");

    if (this.surface) {
      this.removeChild(this.surface);
      this.surface = null;
    }
    if (!this.cid) {
      root.createDiv({
        cls: "vertiscope-hint",
        text: "Pick a node in the 3D graph to read its chunk here.",
      });
      return;
    }

    const bar = root.createDiv({ cls: "vertiscope-chunk-bar" });
    const note = bar.createEl("button", { text: "open the note" });
    note.onclick = () => this.openNote(this.cid);

    const holder = root.createDiv();
    const surface = new ChunkSurface(holder, this.cid, this.host);
    this.addChild(surface);
    this.surface = surface;
  }
}
