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

import { CHUNK_VIEW, ChunkView } from "./chunkview";
import {
  RunHost, RunRequest, livePreviewRunButtons, readingViewRunButtons,
} from "./runbutton";
import { GRAPH_VIEW, GraphView } from "./graph";
import { RetrievalSuggest } from "./retrieval";
import { Sidecar } from "./sidecar";
import { ChunkSurface, SurfaceHost } from "./surface";
import { ChunkPayload, DEFAULTS, DomvecSettings, EnactResult }
  from "./types";
import { VaultLinks } from "./vaultlinks";

export default class DomvecPlugin extends Plugin implements SurfaceHost, RunHost {
  settings: DomvecSettings = DEFAULTS;
  sidecar!: Sidecar;
  links!: VaultLinks;
  /**
   * What the SERVER last said it allows. Refreshed on load and by the
   * connection check; never assumed, and never set from a plugin setting.
   */
  private serverEnact = false;
  /** Every mounted surface, so the toggle command can reach them all. */
  private surfaces = new Set<ChunkSurface>();

  async onload() {
    this.settings = Object.assign({}, DEFAULTS, await this.loadData());
    this.sidecar = new Sidecar(() => this.settings.sidecar);
    this.links = new VaultLinks(this.app, this.sidecar);

    this.registerMarkdownCodeBlockProcessor(
      "domvec",
      (source, el, ctx) => this.renderChunk(source, el, ctx),
    );

    this.registerEditorSuggest(
      new RetrievalSuggest(this.app, this.sidecar, () => this.settings,
                           this.links),
    );

    // A run button per fence, in BOTH rendering paths. They are separate
    // renderers in Obsidian and neither covers the other: reading view builds
    // DOM a post-processor can append to, live preview is CodeMirror and needs
    // a widget decoration. See `runbutton.ts`.
    this.registerMarkdownPostProcessor(readingViewRunButtons(this));
    this.registerEditorExtension(
      livePreviewRunButtons(this, () => this.app.workspace.getActiveFile()?.path ?? ""),
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
        const health = await this.sidecar.health();
        this.serverEnact = !!(health && health.enact);
        new Notice(health
          ? `domvec: sidecar at ${this.settings.sidecar} — ` +
            `${health.pages} pages, ` +
            (health.enact ? "CAN drive the live page" : "read-only")
          : `domvec: no sidecar at ${this.settings.sidecar || "(unset)"} — ` +
            "notes still read offline");
      },
    });

    this.registerView(
      GRAPH_VIEW,
      (leaf: WorkspaceLeaf) =>
        new GraphView(leaf, this.sidecar, (cid) => this.openChunk(cid),
                      () => this.settings.loadRemoteMedia),
    );
    this.registerView(
      CHUNK_VIEW,
      (leaf: WorkspaceLeaf) =>
        new ChunkView(leaf, this, (cid) => this.revealChunk(cid)),
    );
    this.addRibbonIcon("git-fork", "domvec 3D graph", () => this.openGraph());
    this.addCommand({
      id: "domvec-open-graph",
      name: "Open the 3D graph",
      callback: () => this.openGraph(),
    });

    // Ask the server what it allows, once, at load. A surface drawn before
    // the answer arrives is read-only, which is the safe direction to be
    // wrong in.
    this.sidecar.health().then((h) => { this.serverEnact = !!(h && h.enact); });

    this.addSettingTab(new DomvecSettingTab(this.app, this));
  }

  /**
   * A fence's run button was pressed: run it in the note's kernel.
   *
   * The NOTE is sent, not the cell, because the note is the isolation boundary
   * (`NOTEBOOK_PANEL_DESIGN` §4): variables are shared between cells of one note
   * and isolated across notes. Without a path there is no boundary to name, so
   * this refuses rather than letting the server default one — a defaulted note
   * would put every cell in the vault into one namespace, which surfaces as a
   * mysterious collision between unrelated notes.
   *
   * Step 4 writes the result into the note as an output block. Until then it is
   * a Notice, which is honest about being transient rather than looking like
   * persistence that failed.
   */
  async onRunFence(req: RunRequest): Promise<void> {
    const note = req.path || this.app.workspace.getActiveFile()?.path || "";
    if (!note) {
      new Notice("domvec: cannot run a cell outside a note — " +
                 "the note is the kernel's isolation boundary", 6000);
      return;
    }

    const running = new Notice(`domvec: running ${req.lang}…`, 0);
    let reply;
    try {
      reply = await this.sidecar.runCell(note, req.code, req.lang);
    } finally {
      running.hide();
    }

    if (!reply) {
      new Notice(`domvec: no sidecar at ${this.settings.sidecar || "(unset)"} ` +
                 "— cannot run cells", 6000);
      return;
    }
    if (reply.error && reply.ok === undefined) {
      // The server refused rather than the cell failing: 403 when the kernel is
      // off, 400 when the request was wrong. Both carry a `detail` that says
      // what to do, and showing it is the difference between "off" and "broken".
      new Notice(`domvec: ${reply.error}` +
                 (reply.detail ? ` — ${reply.detail}` : ""), 9000);
      return;
    }

    // Whenever the namespace is not the one the previous cell left, say so. A
    // silently-empty variable reads as a bug in the reader's own code.
    const notes: string[] = [];
    if (reply.kernel) notes.push(reply.kernel);
    if (reply.evicted) notes.push(`retired ${reply.evicted}'s kernel`);

    if (!reply.ok) {
      const last = (reply.error || "").trim().split("\n").pop() || "failed";
      new Notice(`domvec [${reply.count ?? "?"}] ${last}` +
                 (notes.length ? ` (${notes.join("; ")})` : ""), 9000);
      return;
    }
    const shown = [reply.stdout, reply.stderr, reply.value ?? ""]
      .filter((s) => s && s.trim()).join("\n").trim();
    new Notice(`domvec [${reply.count ?? "?"}] ` +
               (shown || "ok, no output") +
               (notes.length ? `\n(${notes.join("; ")})` : ""), 8000);
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
   * Show the chunk a graph node stands for -- and only that chunk.
   *
   * A node stands for a chunk, so clicking it shows the chunk, as its
   * structured markdown or as the interactive HTML. It used to open the
   * NOTE, which is a page of a vault: frontmatter, the distilled markdown, a
   * fence, and whatever the reader has since written around it. The note is
   * still one button away, in the pane's own bar.
   *
   * One pane, reused. Opening a tab per click buries the graph you are
   * clicking in within a few nodes.
   */
  private async openChunk(cid: string) {
    const existing = this.app.workspace.getLeavesOfType(CHUNK_VIEW);
    const leaf = existing.length
      ? existing[0]
      : this.app.workspace.getLeaf("split", "vertical");
    if (!existing.length) {
      await leaf.setViewState({ type: CHUNK_VIEW, active: true });
    }
    const view = leaf.view as ChunkView;
    await view.show(cid);
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

  canEnact(): boolean {
    return this.serverEnact;
  }

  enact(address: string, action = "press",
        text?: string): Promise<EnactResult | null> {
    return this.sidecar.enact(address, action, text);
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
