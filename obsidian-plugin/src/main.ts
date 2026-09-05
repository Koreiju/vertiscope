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
 * the native graph work for free, and the 3D view (next) owns its own scene.
 */

import {
  MarkdownPostProcessorContext,
  MarkdownRenderChild,
  Plugin,
  PluginSettingTab,
  Setting,
  App,
} from "obsidian";

interface DomvecSettings {
  /** Where the Python sidecar answers. Empty disables every lookup. */
  sidecar: string;
  /** Start in the interactive surface rather than the distilled markdown. */
  interactiveByDefault: boolean;
}

const DEFAULTS: DomvecSettings = {
  sidecar: "http://127.0.0.1:8787",
  interactiveByDefault: true,
};

/** One line of a chunk, as the sidecar reports it. */
interface ChunkLine {
  text: string;
  /** `url:xpath:taxonomy:content` -- the patricia trie address. */
  key: string;
  /** One of the eighteen render classes: link, button, field, text, ... */
  cls: string;
  /** True when the address is an affordance rather than prose. */
  control: boolean;
  /** Resolved href/src, when the address carries one. */
  target?: string;
}

interface ChunkPayload {
  cid: string;
  url: string;
  xpath: string;
  lines: ChunkLine[];
}

export default class DomvecPlugin extends Plugin {
  settings: DomvecSettings = DEFAULTS;
  /** Every mounted surface, so the toggle command can reach them all. */
  private surfaces = new Set<ChunkSurface>();

  async onload() {
    this.settings = Object.assign({}, DEFAULTS, await this.loadData());

    this.registerMarkdownCodeBlockProcessor(
      "domvec",
      (source, el, ctx) => this.renderChunk(source, el, ctx),
    );

    this.addCommand({
      id: "domvec-toggle-surface",
      name: "Toggle distilled markdown / interactive surface",
      // No default hotkey: Obsidian asks users not to claim one, and a
      // conflict is silent -- the command simply stops firing.
      callback: () => this.surfaces.forEach((s) => s.toggle()),
    });

    this.addSettingTab(new DomvecSettingTab(this.app, this));
  }

  onunload() {
    this.surfaces.clear();
  }

  async saveSettings() {
    await this.saveData(this.settings);
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

  /** Ask the sidecar for a chunk. Null means "render what the note has". */
  async fetchChunk(cid: string): Promise<ChunkPayload | null> {
    const base = this.settings.sidecar.trim().replace(/\/+$/, "");
    if (!base) return null;
    try {
      const res = await fetch(`${base}/chunk/${encodeURIComponent(cid)}`);
      if (!res.ok) return null;
      return (await res.json()) as ChunkPayload;
    } catch {
      // Offline is a supported mode, not a failure: the vault is meant to
      // work with no sidecar and no network. The surface says so and falls
      // back to the note's own prose.
      return null;
    }
  }
}

function parseCid(source: string): string | null {
  const m = /^\s*cid:\s*([A-Za-z0-9]+)\s*$/m.exec(source);
  return m ? m[1] : null;
}

/**
 * The rendered surface for one chunk.
 *
 * MarkdownRenderChild rather than a bare element so the fetch, the listeners
 * and the plugin's registry are all released when the section goes away.
 */
class ChunkSurface extends MarkdownRenderChild {
  private interactive: boolean;
  private payload: ChunkPayload | null = null;

  constructor(
    containerEl: HTMLElement,
    private cid: string,
    private plugin: DomvecPlugin,
  ) {
    super(containerEl);
    this.interactive = plugin.settings.interactiveByDefault;
  }

  async onload() {
    this.payload = await this.plugin.fetchChunk(this.cid);
    this.draw();
  }

  toggle() {
    this.interactive = !this.interactive;
    this.draw();
  }

  private draw() {
    const root = this.containerEl;
    root.empty();
    root.addClass("domvec-surface");

    const bar = root.createDiv({ cls: "domvec-bar" });
    bar.createSpan({ cls: "domvec-cid", text: this.cid.slice(0, 8) });
    if (this.payload) {
      bar.createSpan({ cls: "domvec-url", text: this.payload.url });
    } else {
      // Said plainly rather than left to look like an empty chunk. An
      // unreachable sidecar and a chunk with no content render identically
      // otherwise, and that ambiguity is how a dead pipeline goes unnoticed.
      bar.createSpan({
        cls: "domvec-offline",
        text: "offline - sidecar unreachable",
      });
    }
    const button = bar.createEl("button", {
      cls: "domvec-toggle",
      text: this.interactive ? "markdown" : "interactive",
    });
    button.onclick = () => this.toggle();

    const body = root.createDiv({ cls: "domvec-body" });
    if (!this.payload) {
      body.createDiv({
        cls: "domvec-hint",
        text: "The distilled markdown above this block is the offline reading.",
      });
      return;
    }
    if (this.interactive) this.drawInteractive(body);
    else this.drawMarkdown(body);
  }

  /** Controls as controls; prose as prose. */
  private drawInteractive(body: HTMLElement) {
    for (const line of this.payload!.lines) {
      const row = body.createDiv({ cls: "domvec-line" });
      if (!line.control) {
        row.createSpan({ cls: "domvec-text", text: line.text });
        continue;
      }
      const el = row.createEl("button", {
        cls: `domvec-act domvec-${line.cls}`,
        text: line.text || line.cls,
      });
      // Read-only by default: the click reports the address it would act on
      // rather than acting. Driving the real page is the Selenium port, and
      // it must be an explicit choice, never a side effect of opening a note.
      el.onclick = () => this.announce(line);
      el.setAttr("aria-label", line.key);
    }
  }

  private drawMarkdown(body: HTMLElement) {
    const pre = body.createEl("pre", { cls: "domvec-md" });
    pre.createEl("code", {
      text: this.payload!.lines.map((l) => l.text).join("\n"),
    });
  }

  private announce(line: ChunkLine) {
    const out = this.containerEl.querySelector(".domvec-readout")
      ?? this.containerEl.createDiv({ cls: "domvec-readout" });
    out.setText(
      `${line.cls}  ${line.key}` + (line.target ? `  -> ${line.target}` : ""),
    );
  }
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
  }
}
