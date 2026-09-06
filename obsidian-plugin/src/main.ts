/**
 * domvec bridge -- distilled web chunks as live surfaces inside notes.
 *
 * The design turns on one property of Obsidian: a code-block processor is
 * handed a real HTMLElement inside a real note, and the DOM a plugin builds
 * there is NOT put through the sanitiser that strips scripts and handlers
 * from raw HTML in markdown. So a note can be an ordinary `.md` file -- which
 * is what the graph view reads -- and still carry a surface you can click.
 *
 * That is why the note is split the way it is. The prose above the fence
 * holds the wikilinks, because Obsidian parses links only there; the fence
 * holds nothing but a cid, because everything else is looked up from the
 * store and a second copy in the note would drift from it.
 *
 * The native graph view has no plugin API -- the one community plugin that
 * extends it patches undocumented internals and warns that settings can be
 * lost. So this plugin does not touch it. Real wikilinks in real notes make
 * the native graph work for free.
 */

import {
  App,
  MarkdownPostProcessorContext,
  Notice,
  Plugin,
  WorkspaceLeaf,
  PluginSettingTab,
  Setting,
} from "obsidian";

import { GRAPH_VIEW, GraphView } from "./graph";
import { RetrievalSuggest } from "./retrieval";
import { Sidecar } from "./sidecar";
import { ChunkSurface, SurfaceHost } from "./surface";
import { ChunkPayload, DEFAULTS, DomvecSettings } from "./types";

export default class DomvecPlugin extends Plugin implements SurfaceHost {
  settings: DomvecSettings = DEFAULTS;
  sidecar!: Sidecar;
  /** Every mounted surface, so the toggle command can reach them all. */
  private surfaces = new Set<ChunkSurface>();

  async onload() {
    this.settings = Object.assign({}, DEFAULTS, await this.loadData());
    this.sidecar = new Sidecar(() => this.settings.sidecar);

    this.registerMarkdownCodeBlockProcessor(
      "domvec",
      (source, el, ctx) => this.renderChunk(source, el, ctx),
    );

    this.registerEditorSuggest(
      new RetrievalSuggest(this.app, this.sidecar, () => this.settings),
    );

    this.addCommand({
      id: "domvec-toggle-surface",
      name: "Toggle distilled markdown / interactive surface",
      // No default hotkey: Obsidian asks plugins not to claim one, and a
      // conflict is silent -- the command simply stops firing.
      callback: () => this.surfaces.forEach((s) => s.toggle()),
    });

    this.addCommand({
      id: "domvec-toggle-media",
      name: "Toggle loading remote media",
      callback: async () => {
        this.settings.loadRemoteMedia = !this.settings.loadRemoteMedia;
        await this.saveSettings();
        this.surfaces.forEach((s) => s.toggle());
        this.surfaces.forEach((s) => s.toggle());   // redraw, same mode
        new Notice(`domvec: remote media ${
          this.settings.loadRemoteMedia ? "on" : "off"}`);
      },
    });

    this.addCommand({
      id: "domvec-check-sidecar",
      name: "Check sidecar connection",
      callback: async () => {
        const ok = await this.sidecar.alive();
        new Notice(ok
          ? `domvec: sidecar answering at ${this.settings.sidecar}`
          : `domvec: no sidecar at ${this.settings.sidecar || "(unset)"} — ` +
            "notes still read offline");
      },
    });

    this.registerView(
      GRAPH_VIEW,
      (leaf: WorkspaceLeaf) =>
        new GraphView(leaf, this.sidecar, (cid) => this.revealChunk(cid)),
    );
    this.addRibbonIcon("git-fork", "domvec 3D graph", () => this.openGraph());
    this.addCommand({
      id: "domvec-open-graph",
      name: "Open the 3D graph",
      callback: () => this.openGraph(),
    });

    this.addSettingTab(new DomvecSettingTab(this.app, this));
  }

  onunload() {
    this.surfaces.clear();
    // The view's own `onClose` releases the WebGL context; detaching leaves
    // is Obsidian's job and doing it here is explicitly discouraged, because
    // it destroys layout the user arranged.
  }

  private async openGraph() {
    const existing = this.app.workspace.getLeavesOfType(GRAPH_VIEW);
    if (existing.length) {
      this.app.workspace.revealLeaf(existing[0]);
      return;
    }
    const leaf = this.app.workspace.getLeaf("tab");
    await leaf.setViewState({ type: GRAPH_VIEW, active: true });
    this.app.workspace.revealLeaf(leaf);
  }

  /**
   * Open the note a graph node stands for.
   *
   * Matched on the `cid` in frontmatter rather than on the file name, because
   * the exporter names notes for their first words and two chunks can start
   * the same way. The cid is the identity everything else is keyed on.
   */
  private async revealChunk(cid: string) {
    const file = this.app.vault.getMarkdownFiles().find((f) => {
      const cache = this.app.metadataCache.getFileCache(f);
      return cache?.frontmatter?.cid === cid;
    });
    if (!file) {
      new Notice(`domvec: no exported note for ${cid.slice(0, 8)}`);
      return;
    }
    await this.app.workspace.getLeaf(false).openFile(file);
  }

  async saveSettings() {
    await this.saveData(this.settings);
  }

  fetchChunk(cid: string): Promise<ChunkPayload | null> {
    return this.sidecar.chunk(cid);
  }

  private renderChunk(
    source: string,
    el: HTMLElement,
    ctx: MarkdownPostProcessorContext,
  ) {
    const cid = parseCid(source);
    if (!cid) {
      el.createEl("div", {
        cls: "domvec-error",
        text: "domvec: this block carries no cid",
      });
      return;
    }
    const surface = new ChunkSurface(el, cid, this);
    // addChild ties the surface to the element's life: when the user edits
    // the note and this section is replaced, onunload runs. Without it an
    // aborted fetch resolves into a detached element.
    ctx.addChild(surface);
    this.surfaces.add(surface);
    surface.register(() => this.surfaces.delete(surface));
  }
}

function parseCid(source: string): string | null {
  const m = /^\s*cid:\s*([A-Za-z0-9]+)\s*$/m.exec(source);
  return m ? m[1] : null;
}

class DomvecSettingTab extends PluginSettingTab {
  constructor(app: App, private plugin: DomvecPlugin) {
    super(app, plugin);
  }

  display() {
    const { containerEl } = this;
    containerEl.empty();

    new Setting(containerEl)
      .setName("Sidecar address")
      .setDesc(
        "Where the domvec Python sidecar answers. Leave empty to work purely " +
          "from the exported notes, with no process and no network.",
      )
      .addText((t) =>
        t
          .setPlaceholder(DEFAULTS.sidecar)
          .setValue(this.plugin.settings.sidecar)
          .onChange(async (v) => {
            this.plugin.settings.sidecar = v;
            await this.plugin.saveSettings();
          }),
      );

    new Setting(containerEl)
      .setName("Open as interactive surface")
      .setDesc("Otherwise a chunk opens as its distilled markdown.")
      .addToggle((t) =>
        t
          .setValue(this.plugin.settings.interactiveByDefault)
          .onChange(async (v) => {
            this.plugin.settings.interactiveByDefault = v;
            await this.plugin.saveSettings();
          }),
      );

    new Setting(containerEl)
      .setName("Load remote media")
      .setDesc(
        "Off by default, and that is a privacy setting rather than a " +
          "performance one: fetching a page's images from your vault tells " +
          "those hosts the page was read again, at a new time, from a new " +
          "address. With it off, media shows as a captioned placeholder.",
      )
      .addToggle((t) =>
        t
          .setValue(this.plugin.settings.loadRemoteMedia)
          .onChange(async (v) => {
            this.plugin.settings.loadRemoteMedia = v;
            await this.plugin.saveSettings();
          }),
      );

    new Setting(containerEl)
      .setName("Retrieval results")
      .setDesc("How many passages the `/` gesture offers.")
      .addSlider((s) =>
        s
          .setLimits(3, 20, 1)
          .setDynamicTooltip()
          .setValue(this.plugin.settings.retrievalLimit)
          .onChange(async (v) => {
            this.plugin.settings.retrievalLimit = v;
            await this.plugin.saveSettings();
          }),
      );
  }
}
