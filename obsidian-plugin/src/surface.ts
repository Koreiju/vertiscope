/**
 * One chunk, rendered as something a reader can look at and press.
 *
 * `MarkdownRenderChild` rather than a bare element so the fetch, the
 * listeners and the plugin's registry are released when the note section goes
 * away -- a surface whose fetch resolves into a detached element is the usual
 * way a code-block processor leaks.
 */

import { MarkdownRenderChild } from "obsidian";

import { ChunkLine, ChunkPayload, VertiscopeSettings, EnactResult }
  from "./types";

/**
 * The stylesheet that travels INTO the shadow root.
 *
 * It has to live here rather than in `styles.css`: a shadow root is exactly
 * the thing a page-level stylesheet cannot reach. Written against Obsidian's
 * own custom properties, which do inherit across the boundary, so a control
 * drawn in here follows the reader's theme instead of announcing that a
 * plugin drew it.
 *
 * The goal asks for the distilled DOM to render "as interactive obsidian
 * object structures ... as shown by the rendered and interactive fields where
 * properties is" -- the native property rows are the reference, so the field
 * and button rules below borrow their shape: a muted label, a bordered
 * control, an accent when it is live.
 */
const SHADOW_CSS = `
:host { display: block; }
.vertiscope-html > :first-child { margin-top: 0; }
.vertiscope-html > :last-child { margin-bottom: 0; }
.vertiscope-html { line-height: 1.4; font-size: var(--font-ui-small, 13px);
  color: var(--text-normal, #222); }

/* One step per nesting LEVEL of the distilled tree, not per DOM ancestor --
   and _collapse has already dropped every level that held one child, so a
   rule that survives to here stands for a real branch and is worth an indent.

   No vertical margin. A margin on the wrapper compounds with the margin on
   the paragraph inside it, at every level, so a three-deep line paid for four
   gaps to separate it from one neighbour. Spacing belongs to the content, not
   to the container it happens to sit in. */
.dv-n { padding-left: 0.55em; border-left: 1px solid
  var(--background-modifier-border, #ddd); margin: 0; }

/* A picture with words beside it: a result row, a product tile, a profile.
   Drawn as the cohesive thing the page laid out, not as stacked lines. */
/* Row gap ZERO, and that is not a style choice. The figure spans the card
   with grid-row: 1 / span 99, which brings 99 rows into being; a symmetric
   gap then applies between all of them, so 95 empty rows cost 95 gaps.
   Measured in the running app: a card 123px of picture tall rendered 762px,
   and the panel came to 813px for five lines of text. */
.dv-card { display: grid; grid-template-columns: auto 1fr; gap: 0 0.5em;
  align-items: start; padding: 0.3em 0.45em; border-left: none;
  border: 1px solid var(--background-modifier-border, #ddd);
  border-radius: var(--radius-m, 6px);
  background: var(--background-primary-alt, transparent);
  margin: 0.25em 0; }
.dv-card > .dv-fig { grid-row: 1 / span 99; margin: 0; }
.dv-card .dv-img { max-width: 84px; }
/* The first and last things in a card sit against its padding, not on top of
   their own margins as well. */
.dv-card > :first-child { margin-top: 0; }
.dv-card > :last-child { margin-bottom: 0; }

.dv-p { margin: 0.08em 0; }
.dv-h { margin: 0.25em 0 0.08em; line-height: 1.2;
  font-weight: var(--font-semibold, 600); }
h1.dv-h { font-size: 1.35em; } h2.dv-h { font-size: 1.2em; }
h3.dv-h { font-size: 1.1em; } h4.dv-h, h5.dv-h, h6.dv-h { font-size: 1em; }
.dv-ul { margin: 0.08em 0; padding-left: 1em; }
.dv-li { margin: 0.04em 0; }
.dv-a { color: var(--text-accent, #06c); text-decoration: none; }
.dv-a:hover { text-decoration: underline; }
.dv-t { color: inherit; }

/* Controls, shaped like Obsidian's own property fields. Inert until the
   SERVER says it will drive the page -- a button that looks pressable and
   403s is worse than one that says it is only showing you an address. */
.dv-b, .dv-f input {
  font: inherit; color: var(--text-muted, #666);
  background: var(--background-modifier-form-field, #f6f6f6);
  border: 1px solid var(--background-modifier-border, #ddd);
  border-radius: var(--radius-s, 4px); padding: 0.15em 0.55em; }
.dv-b { cursor: default; }
.vertiscope-live { color: var(--text-normal, #111);
  border-color: var(--interactive-accent, #6a6ae0); cursor: pointer; }
.dv-f { display: inline-flex; align-items: center; gap: 0.35em; margin: 0.08em 0; }
.dv-f span { color: var(--text-muted, #666); }
.dv-form { border: 1px dashed var(--background-modifier-border, #ddd);
  border-radius: var(--radius-s, 4px); padding: 0 0.6em 0.35em; margin: 0.3em 0; }
.dv-form legend { color: var(--text-faint, #999); padding: 0 0.3em; }
.dv-select {
  font: inherit; color: var(--text-muted, #666); width: 100%;
  background: var(--background-modifier-form-field, #f6f6f6);
  border: 1px solid var(--background-modifier-border, #ddd);
  border-radius: var(--radius-s, 4px); padding: 0.15em 0; margin: 0.2em 0; }
.dv-opt { padding: 0.1em 0.55em; }
.dv-opt:checked { background: var(--background-modifier-hover, #eee); }

.dv-fig { margin: 0.2em 0; }
.dv-img { max-width: 100%; border-radius: var(--radius-s, 4px); display: block; }
figcaption { color: var(--text-muted, #666); font-size: 0.9em; margin-top: 0.1em; }

/* Never an empty gap: a missing picture and a page that showed none must not
   look the same. */
.dv-noimg { display: inline-flex; align-items: center; justify-content: center;
  min-width: 2.2em; min-height: 2.2em; color: var(--text-faint, #999);
  background: var(--background-secondary, #f2f2f2);
  border: 1px dashed var(--background-modifier-border, #ddd);
  border-radius: var(--radius-s, 4px); }
`;

/** `![alt](src)` as the distiller draws media. */
const MEDIA = /^!\[([^\]]*)\]\(((?:[^()\s]|\((?:[^()\s]|\([^()\s]*\))*\))*)\)/;
/** `[words](target)` as it draws a link. */
const LINK = /^\[([^\]]*)\]\(((?:[^()\s]|\((?:[^()\s]|\([^()\s]*\))*\))*)\)/;

export interface SurfaceHost {
  settings: VertiscopeSettings;
  fetchChunk(cid: string): Promise<ChunkPayload | null>;
  /** Whether the SERVER will drive the live page. Not a plugin setting. */
  canEnact(): boolean;
  enact(address: string, action?: string,
        text?: string): Promise<EnactResult | null>;
}

export class ChunkSurface extends MarkdownRenderChild {
  private interactive: boolean;
  private payload: ChunkPayload | null = null;
  /** Showing the merged group rather than this chunk alone (`G-27`).
   *  Off by default: the chunk a reader asked for is the chunk they get. */
  private showMerged = false;
  private readout: HTMLElement | null = null;

  constructor(
    containerEl: HTMLElement,
    private cid: string,
    private host: SurfaceHost,
    /** Force a form. The graph's billboard is the chunk's SHADOW-DOM form
     *  (`G-77`), whatever the note default is; the markdown form lives on
     *  the browser's markdown side. */
    opts: { interactive?: boolean } = {},
  ) {
    super(containerEl);
    this.interactive = opts.interactive ?? host.settings.interactiveByDefault;
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
    root.addClass("vertiscope-surface");

    this.drawBar(root.createDiv({ cls: "vertiscope-bar" }));

    const body = root.createDiv({ cls: "vertiscope-body" });
    if (!this.payload) {
      body.createDiv({
        cls: "vertiscope-hint",
        text: "The distilled markdown above this block is the offline reading.",
      });
      return;
    }
    const group = this.payload.group;
    if (this.showMerged && group && group.markdown) {
      // The merged reading: the members' markdown assembled in document
      // order. Plain text, with no per-line addresses, and deliberately so --
      // the addresses belong to the individual chunks, and attaching them to
      // an assembled string would invite a click to enact against a line the
      // trie never placed there.
      const merged = body.createDiv({ cls: "vertiscope-merged" });
      merged.createDiv({
        cls: "vertiscope-merged-note",
        text: `${group.members.length} chunks, merged by similarity. `
              + `Retrieval still resolves to each of them separately.`,
      });
      merged.createEl("pre").setText(group.markdown);
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
    const host = body.createDiv({ cls: "vertiscope-html-host" });
    // A shadow root, not a plain div.
    //
    // This markup is a WEB PAGE's structure, and a note is a styled document:
    // dropped into the note's own tree it inherits every markdown rule the
    // theme has -- paragraph spacing, list bullets, link colours, heading
    // scales -- so a distilled page comes out looking like an essay about
    // itself rather than like the page. A shadow root ends that in both
    // directions: the theme cannot reach in, and nothing the page called its
    // classes can reach out.
    //
    // It is also what the Obsidian ecosystem settled on. Of the plugins that
    // render HTML in notes, the ones that take arbitrary markup sandbox it in
    // an iframe -- they have to, since arbitrary markup can carry scripts --
    // and `html-blocks` uses a shadow root per block for exactly the style
    // reason above. Ours is neither arbitrary nor scripted: `htmlform.py`
    // emits a closed tag whitelist with every text node escaped. So the
    // iframe's isolation buys nothing here and costs the two things that
    // matter -- our listeners could no longer reach the elements to wire
    // addresses to them, and Obsidian's own CSS variables would not reach in
    // to make a control look native.
    //
    // Custom properties inherit THROUGH a shadow boundary, which is what lets
    // the sheet below be written in `--text-muted` and friends and still
    // follow the reader's theme.
    const shadow = host.attachShadow({ mode: "open" });
    const sheet = document.createElement("style");
    sheet.textContent = SHADOW_CSS;
    shadow.appendChild(sheet);
    const holder = document.createElement("div");
    holder.className = "vertiscope-html";
    holder.innerHTML = markup;
    shadow.appendChild(holder);

    this.wireDistilled(holder);
  }

  /**
   * Media policy and address wiring, over whatever root holds the markup.
   *
   * Split out from the draw so the shadow root is the only thing that
   * changed: `querySelectorAll` inside a shadow root reaches the elements in
   * it and nothing outside, which is exactly the scope these two passes want.
   */
  private wireDistilled(holder: HTMLElement) {
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
    holder.querySelectorAll("[data-vertiscope-address]").forEach((node) => {
      const el = node as HTMLElement;
      const key = el.getAttribute("data-vertiscope-address") || "";
      if (!key) return;
      const control = el.matches("button, input, a, fieldset, select, option")
        || el.querySelector("button, input, select") !== null;
      if (!control) return;
      // Enabled only when the SERVER says it will drive the page. The
      // elements arrive disabled from Python, which is the safe direction to
      // be wrong in -- a surface drawn before `/health` answers offers
      // nothing that 403s.
      if (live) {
        el.querySelectorAll("[disabled]").forEach(
          (d) => d.removeAttribute("disabled"));
        el.removeAttribute("disabled");
        // An `<option>` carries no `disabled` of its own: the attribute is on
        // the `<select>` around it, which is neither this element nor inside
        // it. Enabling only downward left every option unclickable inside a
        // control that was still off.
        el.closest("select")?.removeAttribute("disabled");
        el.addClass("vertiscope-live");
      }
      // A text field is filled, not pressed (`G-111`): the value the reader
      // enters goes to the page on `change`, and a click only focuses it.
      const field = el.matches(
        "input:not([type=checkbox]):not([type=radio]):not([type=button]):not([type=submit]):not([type=reset]), textarea");
      if (live && field) {
        el.addEventListener("change", () => {
          void this.pressAddress(key, this.labelOf(el), "type", (el as HTMLInputElement).value);
        });
      }
      el.addEventListener("click", (event) => {
        // Always prevented. An `<a href>` in here points at the live web and
        // clicking it should press the element through the sensor, not
        // navigate the vault's own webview to a scraped url.
        event.preventDefault();
        event.stopPropagation();
        if (live && field) return;
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

  private async pressAddress(key: string, label: string, action = "press", text?: string) {
    this.say(`${action === "press" ? "pressing" : action} ${label || key.slice(0, 40)}…`);
    const result = await this.host.enact(key, action, text);
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
    bar.createSpan({ cls: "vertiscope-cid", text: this.cid.slice(0, 8) });
    if (this.payload) {
      bar.createSpan({ cls: "vertiscope-url", text: this.payload.url });
      // How full the context window this chunk was cut against actually is.
      // The window was 1200 CHARACTERS and the chunks it made held a median
      // of 165 tokens -- 8% of a real one -- and nothing in the vault said
      // so, because the number was never shown anywhere a reader looks.
      // A merged chunk says so, and says where in the group this part sits.
      // Without it the pane shows one of eight chunks with no sign the other
      // seven exist, and the 3D graph -- which draws the GROUP -- and this
      // panel would be describing different things under one cid.
      const group = this.payload.group;
      if (group && group.members.length > 1) {
        const merged = bar.createEl("button", {
          cls: "vertiscope-group" + (this.showMerged ? " is-on" : ""),
          text: `${group.position}/${group.members.length} merged · `
                + `${group.tokens} tok`,
        });
        merged.title = this.showMerged
          ? "showing the merged group; press for this chunk alone"
          : "showing this chunk alone; press for the merged group";
        merged.onclick = () => {
          this.showMerged = !this.showMerged;
          this.draw();
        };
      }
      const size = this.payload.tokens;
      const window = this.payload.window;
      if (size) {
        bar.createSpan({
          cls: "vertiscope-size",
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
        cls: "vertiscope-offline",
        text: "offline — sidecar unreachable",
      });
    }
    // A switch showing BOTH states, not a button labelled with the other
    // one. A lone button reading "markdown" is ambiguous in the way that
    // matters -- it can equally mean "you are looking at markdown" and "press
    // to get markdown" -- and the reader cannot tell which form is on screen
    // without recognising it. Two segments with the live one marked answer
    // that without being read.
    const toggle = bar.createDiv({ cls: "vertiscope-switch" });
    const seg = (label: string, on: boolean) => {
      const el = toggle.createEl("button", {
        cls: "vertiscope-seg" + (on ? " is-on" : ""),
        text: label,
      });
      el.setAttr("aria-pressed", String(on));
      el.onclick = () => { if (!on) this.toggle(); };
      return el;
    };
    seg("markdown", !this.interactive);
    seg("shadow DOM", this.interactive);
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
      const row = body.createDiv({ cls: "vertiscope-line" });
      if (this.drawMedia(row, line)) continue;
      if (line.control) {
        this.drawControl(row, line);
        continue;
      }
      row.createSpan({ cls: "vertiscope-text", text: this.words(line.text) });
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
    const card = row.createDiv({ cls: "vertiscope-billboard" });

    if (src && this.host.settings.loadRemoteMedia) {
      const img = card.createEl("img", { cls: "vertiscope-media" });
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

    const caption = card.createDiv({ cls: "vertiscope-caption" });
    caption.createSpan({ text: alt || line.cls });
    if (src) {
      const open = caption.createEl("button", {
        cls: "vertiscope-act vertiscope-open", text: "open",
      });
      open.onclick = () => window.open(src, "_blank");
    }
    if (line.key) card.setAttr("aria-label", line.key);
    return true;
  }

  private drawMediaPlaceholder(card: HTMLElement, alt: string,
                               src: string, why: string) {
    const box = card.createDiv({ cls: "vertiscope-media-off" });
    box.createSpan({ cls: "vertiscope-media-icon", text: "▣" });
    box.createSpan({ text: alt || "image" });
    box.createSpan({ cls: "vertiscope-media-why", text: `— ${why}` });
    if (src) box.setAttr("title", src);
  }

  private drawControl(row: HTMLElement, line: ChunkLine) {
    const live = this.host.canEnact();
    const el = row.createEl("button", {
      cls: `vertiscope-act vertiscope-${line.cls}` + (live ? " vertiscope-live" : ""),
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
      this.readout = this.containerEl.createDiv({ cls: "vertiscope-readout" });
    }
    this.readout.setText(text);
  }

  private drawMarkdown(body: HTMLElement) {
    const pre = body.createEl("pre", { cls: "vertiscope-md" });
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
