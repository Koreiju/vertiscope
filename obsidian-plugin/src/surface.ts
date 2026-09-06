/**
 * One chunk, rendered as something a reader can look at and press.
 *
 * `MarkdownRenderChild` rather than a bare element so the fetch, the
 * listeners and the plugin's registry are released when the note section goes
 * away -- a surface whose fetch resolves into a detached element is the usual
 * way a code-block processor leaks.
 */

import { MarkdownRenderChild } from "obsidian";

import { ChunkLine, ChunkPayload, DomvecSettings, EnactResult }
  from "./types";

/** `![alt](src)` as the distiller draws media. */
const MEDIA = /^!\[([^\]]*)\]\(([^)\s]*)\)/;
/** `[words](target)` as it draws a link. */
const LINK = /^\[([^\]]*)\]\(([^)\s]*)\)/;

export interface SurfaceHost {
  settings: DomvecSettings;
  fetchChunk(cid: string): Promise<ChunkPayload | null>;
  /** Whether the SERVER will drive the live page. Not a plugin setting. */
  canEnact(): boolean;
  enact(address: string, action?: string,
        text?: string): Promise<EnactResult | null>;
}

export class ChunkSurface extends MarkdownRenderChild {
  private interactive: boolean;
  private payload: ChunkPayload | null = null;
  private readout: HTMLElement | null = null;

  constructor(
    containerEl: HTMLElement,
    private cid: string,
    private host: SurfaceHost,
  ) {
    super(containerEl);
    this.interactive = host.settings.interactiveByDefault;
  }

  async onload() {
    this.payload = await this.host.fetchChunk(this.cid);
    this.draw();
  }

  toggle() {
    this.interactive = !this.interactive;
    this.draw();
  }

  // -- drawing ---------------------------------------------------------------

  private draw() {
    const root = this.containerEl;
    root.empty();
    this.readout = null;
    root.addClass("domvec-surface");

    this.drawBar(root.createDiv({ cls: "domvec-bar" }));

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

  /**
   * The distilled HTML, as elements, with its addresses wired.
   *
   * This is the form markdown cannot be. A `<button>` here exists because the
   * trie says the element at that xpath is a control -- not because a regex
   * matched `( Add to basket )` in a rendering. The markup arrives already
   * escaped and whitelisted from `htmlform.py`; what this method adds is the
   * two things only the client can decide: whether media may be fetched, and
   * whether a control may actually fire.
   *
   * `innerHTML` is deliberate and is the reason the Python side is written
   * the way it is. Obsidian hands a code-block processor an UNSANITISED
   * element, so nothing downstream will catch a `<script>` that got this far;
   * the whitelist and the escaping upstream are the whole defence, and they
   * are tested against the parsed tree rather than against the string.
   */
  private drawDistilledHtml(body: HTMLElement, markup: string) {
    const holder = body.createDiv({ cls: "domvec-html" });
    holder.innerHTML = markup;

    if (!this.host.settings.loadRemoteMedia) {
      // Stripped rather than hidden. A hidden `<img src>` has already been
      // fetched, which is the exact thing the setting exists to prevent: it
      // tells the host the page was read again, from a new address.
      holder.querySelectorAll("img[src]").forEach((node) => {
        const img = node as HTMLImageElement;
        const box = document.createElement("div");
        box.className = "dv-noimg";
        box.textContent = "▣";
        box.title = img.getAttribute("src") || "";
        img.replaceWith(box);
      });
    }

    const live = this.host.canEnact();
    holder.querySelectorAll("[data-domvec-address]").forEach((node) => {
      const el = node as HTMLElement;
      const key = el.getAttribute("data-domvec-address") || "";
      if (!key) return;
      const control = el.matches("button, input, a, fieldset")
        || el.querySelector("button, input") !== null;
      if (!control) return;
      // Enabled only when the SERVER says it will drive the page. The
      // elements arrive disabled from Python, which is the safe direction to
      // be wrong in -- a surface drawn before `/health` answers offers
      // nothing that 403s.
      if (live) {
        el.querySelectorAll("[disabled]").forEach(
          (d) => d.removeAttribute("disabled"));
        el.removeAttribute("disabled");
        el.addClass("domvec-live");
      }
      el.addEventListener("click", (event) => {
        // Always prevented. An `<a href>` in here points at the live web and
        // clicking it should press the element through the sensor, not
        // navigate the vault's own webview to a scraped url.
        event.preventDefault();
        event.stopPropagation();
        if (live) this.pressAddress(key, this.labelOf(el));
        else this.say(`${this.classOf(el)}  ${key}`);
      });
    });
  }

  private labelOf(el: HTMLElement): string {
    return (el.textContent || "").trim().slice(0, 60);
  }

  private classOf(el: HTMLElement): string {
    const cls = (el.getAttribute("class") || "").split(/\s+/)
      .find((c) => c.startsWith("dv-"));
    return cls ? cls.slice(3) : el.tagName.toLowerCase();
  }

  private async pressAddress(key: string, label: string) {
    this.say(`pressing ${label || key.slice(0, 40)}…`);
    const result = await this.host.enact(key, "press");
    if (!result) {
      this.say("no answer from the sidecar");
      return;
    }
    if (result.error) {
      // A refusal is not a failure, and the surface must not blur the two:
      // the never-press set turning something down is the system working.
      this.say((result.refused ? "refused: " : "error: ") + result.error);
      return;
    }
    this.say(`${result.did || "done"} — ${result.detail || ""} ` +
             `${result.url ? "→ " + result.url : ""}`.trim());
  }

  private drawBar(bar: HTMLElement) {
    bar.createSpan({ cls: "domvec-cid", text: this.cid.slice(0, 8) });
    if (this.payload) {
      bar.createSpan({ cls: "domvec-url", text: this.payload.url });
      // How full the context window this chunk was cut against actually is.
      // The window was 1200 CHARACTERS and the chunks it made held a median
      // of 165 tokens -- 8% of a real one -- and nothing in the vault said
      // so, because the number was never shown anywhere a reader looks.
      const size = this.payload.tokens;
      const window = this.payload.window;
      if (size) {
        bar.createSpan({
          cls: "domvec-size",
          text: window
            ? `${size} tok · ${Math.round((100 * size) / window)}% of ${window}`
            : `${size} tok`,
        });
      }
    } else {
      // Said plainly. An unreachable sidecar and a chunk with nothing in it
      // render identically otherwise, and that ambiguity hides a dead
      // pipeline for as long as nobody happens to check.
      bar.createSpan({
        cls: "domvec-offline",
        text: "offline — sidecar unreachable",
      });
    }
    const button = bar.createEl("button", {
      cls: "domvec-toggle",
      text: this.interactive ? "markdown" : "interactive HTML",
    });
    button.onclick = () => this.toggle();
  }

  private drawInteractive(body: HTMLElement) {
    // The distilled HTML when the sidecar sent it. The line-by-line
    // reconstruction below is the fallback for a sidecar too old to send it,
    // and for it alone: rebuilding a button from `( Add to basket )` is a
    // guess about a rendering, where the HTML form is what the trie said.
    const markup = this.payload!.html;
    if (markup && markup.trim()) {
      this.drawDistilledHtml(body, markup);
      return;
    }
    for (const line of this.payload!.lines) {
      if (!line.text.trim()) continue;
      const row = body.createDiv({ cls: "domvec-line" });
      if (this.drawMedia(row, line)) continue;
      if (line.control) {
        this.drawControl(row, line);
        continue;
      }
      row.createSpan({ cls: "domvec-text", text: this.words(line.text) });
    }
  }

  /**
   * An image or a player, as a billboard rather than as its markup.
   *
   * The distiller already knows what the media IS -- it draws `![alt](src)`
   * with the page's own alt text, never the file name -- so the billboard has
   * a caption without guessing. Whether the picture itself loads is the
   * reader's choice: see `loadRemoteMedia`, which is off by default because
   * fetching a page's assets from a vault tells those hosts the page was read
   * again.
   */
  private drawMedia(row: HTMLElement, line: ChunkLine): boolean {
    const match = MEDIA.exec(line.text.trim());
    const isMedia = match !== null ||
      line.cls === "image" || line.cls === "media";
    if (!isMedia) return false;

    const alt = (match ? match[1] : "").trim();
    const src = this.absolute((match ? match[2] : "") || line.target || "");
    const card = row.createDiv({ cls: "domvec-billboard" });

    if (src && this.host.settings.loadRemoteMedia) {
      const img = card.createEl("img", { cls: "domvec-media" });
      img.src = src;
      img.alt = alt || "image";
      // A broken asset must not leave a silent gap where a picture was.
      img.onerror = () => {
        img.remove();
        this.drawMediaPlaceholder(card, alt, src, "did not load");
      };
    } else {
      this.drawMediaPlaceholder(card, alt, src,
        src ? "media off" : "no source");
    }

    const caption = card.createDiv({ cls: "domvec-caption" });
    caption.createSpan({ text: alt || line.cls });
    if (src) {
      const open = caption.createEl("button", {
        cls: "domvec-act domvec-open", text: "open",
      });
      open.onclick = () => window.open(src, "_blank");
    }
    if (line.key) card.setAttr("aria-label", line.key);
    return true;
  }

  private drawMediaPlaceholder(card: HTMLElement, alt: string,
                               src: string, why: string) {
    const box = card.createDiv({ cls: "domvec-media-off" });
    box.createSpan({ cls: "domvec-media-icon", text: "▣" });
    box.createSpan({ text: alt || "image" });
    box.createSpan({ cls: "domvec-media-why", text: `— ${why}` });
    if (src) box.setAttr("title", src);
  }

  private drawControl(row: HTMLElement, line: ChunkLine) {
    const live = this.host.canEnact();
    const el = row.createEl("button", {
      cls: `domvec-act domvec-${line.cls}` + (live ? " domvec-live" : ""),
      text: this.words(line.text) || line.cls,
    });
    // Whether a click ACTS is the server's decision, read from `/health`, not
    // a plugin setting. A plugin setting is this side asserting something
    // about itself, and this side is a page renderer inside an app the user
    // installs plugins into.
    //
    // With the gate shut the click still reports the address it WOULD act on,
    // which is what the surface did before there was a write path at all.
    el.onclick = () => (live ? this.press(line) : this.announce(line));
    el.setAttr("aria-label", line.control_key || line.key);
    if (live) el.setAttr("title", "presses this in the live browser");
  }

  /**
   * Press it for real, and say what came back.
   *
   * The address sent is `control_key` when there is one: the affordance's own
   * address, not the address the LINE happens to be stored under. An anchor's
   * `interactive.links` address is suppressed by the render, so the line
   * carries a `urls.*` or `text.visible` address instead, and enacting on
   * that would name the wrong thing.
   */
  private async press(line: ChunkLine) {
    const key = line.control_key || line.key;
    if (!key) return;
    this.say("pressing…");
    const result = await this.host.enact(key, "press");
    if (!result) {
      this.say("no answer from the sidecar");
      return;
    }
    if (result.error) {
      // A refusal is not a failure, and the surface must not blur the two:
      // the never-press set turning something down is the system working.
      this.say((result.refused ? "refused: " : "error: ") + result.error);
      return;
    }
    this.say(`${result.did || "done"} — ${result.detail || ""} ` +
             `${result.url ? "→ " + result.url : ""}`.trim());
  }

  private say(text: string) {
    if (!this.readout) {
      this.readout = this.containerEl.createDiv({ cls: "domvec-readout" });
    }
    this.readout.setText(text);
  }

  private drawMarkdown(body: HTMLElement) {
    const pre = body.createEl("pre", { cls: "domvec-md" });
    pre.createEl("code", {
      text: this.payload!.lines.map((l) => l.text).join("\n"),
    });
  }

  // -- helpers ---------------------------------------------------------------

  /**
   * The words a reader sees, with the render's own marks taken back off.
   *
   * The distiller draws a control with marks that SAY it is a control --
   * `( Add to basket )`, `[ ] Search books`, `=== form ===` -- and the surface
   * re-adds its own affordance by drawing a real button. Leaving the marks in
   * the label prints them twice: a form's button read `=== form ===` in the
   * running app, and a button would have read `( Add to basket )`.
   *
   * The REPL's `Document.from_chunks` strips the same marks for the same
   * reason, and its comment records the trap that matters here: the heading
   * marker comes off FIRST, because a control inside a heading renders as
   * `##### ( Products )` and every test below, each of which looks at a
   * LEADING mark, otherwise stops firing.
   */
  private words(text: string): string {
    let out = text.trim();

    const heading = /^#{1,6}\s+/.exec(out);
    if (heading) out = out.slice(heading[0].length).trim();

    const link = LINK.exec(out);
    if (link) return link[1].trim();

    const form = /^===\s*(.*?)\s*===$/.exec(out);
    if (form) return form[1].trim();

    const button = /^\(\s*(.*?)\s*\)$/.exec(out);
    if (button) return button[1].trim();

    const field = /^\[[ xX]?\]\s*(.*)$/.exec(out);
    if (field) return field[1].trim();

    return out;
  }

  /** A page-relative src resolved against the chunk's own url. */
  private absolute(src: string): string {
    if (!src) return "";
    try {
      return new URL(src, this.payload?.url || undefined).toString();
    } catch {
      return "";
    }
  }

  private announce(line: ChunkLine) {
    const key = line.control_key || line.key;
    this.say(`${line.cls}  ${key}` +
             (line.target ? `  → ${line.target}` : ""));
  }
}
