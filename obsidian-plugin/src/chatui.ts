/**
 * ONE chat interface, three hosts (PLUGIN_GOAL 182; G-394).
 *
 * "our chat interfaces should be much more well formatted along the general
 * chat interface style with a clear input box, type-rendered outputs with
 * ```language" -- and "the different artifacts at their grains on input and
 * output are still ... building block style unique instantiations".
 *
 * A conversation is ONE note. Its turns are `## You` and `## <model>`
 * headings, so every turn, paragraph and code block has an address in the
 * note's own tree (the vault:// page the sidecar addresses like any page):
 * nothing about a block lives outside the note. The interface draws those
 * turns as a chat -- a speaker row, prose rendered as markdown, each fenced
 * block under a header naming its language -- above a clear input box.
 *
 * Every block is a typed piece the reader can take out (182, "Select +
 * drag"): press and HOLD a block -- or lines selected inside a code block --
 * and drag it off the conversation (a plain click or click-drag stays the
 * editor's: a cursor, a selection), and it becomes its own panel on the plane,
 * its frontmatter naming the address it came from. The pulled note is a
 * vault note, so retrieval and the dependency graph see it like any other.
 *
 * The host supplies only what differs: where the context comes from (the
 * magnetized panels, the pinned web chunks, the rewound cells) and where a
 * pulled piece lands.
 */
import { Component, MarkdownRenderer, type App, type TFile } from "obsidian";

import { parseConversation, blocksOf, addressOf, turnText, rangeOf, YOU, type ChatBlock, type ChatTurn, type BlockKind, type Piece } from "./chatparse";
export { parseConversation, blocksOf, addressOf, turnText, rangeOf, YOU };
export type { ChatBlock, ChatTurn, BlockKind, Piece };
const NL = "\n";
const FENCE = "`".repeat(3);

export interface ChatHost {
  /** The model's display name (L-1: the chat role of the one model table). */
  model(): string;
  /** This host's context for a prompt: magnetized panels, pins, rewound cells. */
  context(prompt: string): Promise<string[]>;
  stream(prompt: string, context: string[], onToken: (t: string) => void): Promise<string>;
  /** A piece dragged off the conversation, dropped at a screen point. */
  pullOut?(piece: Piece, at: { x: number; y: number }): Promise<string | void>;
}

export class ChatUI {
  readonly el: HTMLElement;
  log: HTMLElement;
  input: HTMLTextAreaElement;
  private send: HTMLElement;
  private comp = new Component();
  busy = false;
  stats = { sends: 0, tokens: 0, pulled: 0, rendered_blocks: 0, last_error: "" };
  /** Planted (G-394): blocks are drawn but carry no address, so nothing can be pulled out. */
  static plantNoPieces = false;
  /** Planted (182): the block carries no fence line -- its tools run "a cell
   *  somewhere", and a block the model repeated cannot be told apart. */
  static plantNoLine = false;

  constructor(private app: App, private file: TFile, private host: ChatHost, parent: HTMLElement) {
    this.comp.load();
    this.el = parent.createDiv({ cls: "domvec-chatui" });
    this.log = this.el.createDiv({ cls: "domvec-chatui-log" });
    const box = this.el.createDiv({ cls: "domvec-chatui-inputbox" });
    this.input = box.createEl("textarea", { cls: "domvec-chatui-input", attr: { placeholder: "Send a message…", rows: "1" } });
    this.send = box.createDiv({ cls: "domvec-chatui-send", attr: { "aria-label": "Send", title: "Send (Enter)" } });
    this.send.setText("➤");
    // Keys typed here are text, never the camera's (G-334), and never Obsidian's.
    this.input.addEventListener("keydown", (e) => {
      e.stopPropagation();
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void this.ask(); }
    });
    this.input.addEventListener("input", () => this.grow());
    for (const el of [this.input, this.send, this.log]) el.addEventListener("mousedown", (e) => e.stopPropagation());
    this.send.onclick = () => { void this.ask(); };
    void this.render();
  }

  destroy(): void { this.comp.unload(); this.el.remove(); }

  private grow(): void {
    this.input.style.height = "auto";
    this.input.style.height = Math.min(160, this.input.scrollHeight) + "px";
  }

  async text(): Promise<string> { return this.app.vault.read(this.file); }

  /** Draw the conversation from the note -- the note is the only state. */
  async render(streaming?: { prompt: string; reply: string }): Promise<void> {
    const parsed = parseConversation(await this.text());
    const turns = parsed.turns.slice();
    if (streaming) {
      turns.push({ who: "you", label: "You", body: streaming.prompt, blocks: blocksOf(streaming.prompt) });
      turns.push({ who: "model", label: this.host.model(), body: streaming.reply, blocks: blocksOf(streaming.reply) });
    }
    if (!streaming && parsed.draft && !this.input.value && !turns.length) { this.input.value = parsed.draft; this.grow(); }
    const atEnd = this.log.scrollHeight - this.log.scrollTop - this.log.clientHeight < 40;
    this.log.empty();
    if (!turns.length) this.log.createDiv({ cls: "domvec-chatui-empty", text: "Ask " + this.host.model() + " anything. Panels magnetized to this one are its context." });
    let n = 0;
    for (let t = 0; t < turns.length; t++) {
      const turn = turns[t];
      const tEl = this.log.createDiv({ cls: "domvec-chatui-turn is-" + turn.who });
      const who = tEl.createDiv({ cls: "domvec-chatui-who" });
      who.createSpan({ cls: "domvec-chatui-avatar", text: turn.who === "you" ? "◯" : "✺" });
      who.createSpan({ cls: "domvec-chatui-name", text: turn.who === "you" ? "You" : turn.label });
      for (let b = 0; b < turn.blocks.length; b++) {
        await this.drawBlock(tEl, turn.blocks[b], t, b);
        n++;
      }
    }
    this.stats.rendered_blocks = n;
    if (atEnd || streaming) this.log.scrollTop = this.log.scrollHeight;
  }

  private async drawBlock(parent: HTMLElement, blk: ChatBlock, t: number, b: number): Promise<void> {
    const el = parent.createDiv({ cls: "domvec-chatui-block is-" + blk.kind });
    if (!ChatUI.plantNoPieces) {
      el.dataset.address = addressOf(this.file.path, t, b);
      el.dataset.kind = blk.kind;
      el.dataset.lang = blk.lang;
    }
    // The fence's line in the note: the run / terminal / open / unnest tools
    // the shared post-processor draws act on THIS cell (182).
    if (!ChatUI.plantNoLine) el.dataset.line = String(blk.line);
    if (blk.kind === "code") {
      const head = el.createDiv({ cls: "domvec-chatui-codehead" });
      head.createSpan({ cls: "domvec-chatui-lang", text: blk.lang });
      const copy = head.createSpan({ cls: "domvec-chatui-copy", text: "copy" });
      copy.onclick = (e) => { e.stopPropagation(); void navigator.clipboard.writeText(blk.text); copy.setText("copied"); };
      const body = el.createDiv({ cls: "domvec-chatui-codebody" });
      await MarkdownRenderer.render(this.app, FENCE + blk.lang + NL + blk.text + NL + FENCE, body, this.file.path, this.comp);
    } else {
      await MarkdownRenderer.render(this.app, blk.text, el, this.file.path, this.comp);
    }
    if (ChatUI.plantNoPieces) return;
    this.holdToPull(el, () => this.pieceFrom(el, blk, t, b));
  }

  /** Press-and-HOLD picks a piece up (182: "pulling ... shouldn't block
   *  basic clicks for a text cursor ... Click and hold with a debounce would
   *  be the difference"). A click, or a press that MOVES before `HOLD_MS`,
   *  is the browser's own -- a cursor, a selection -- and nothing here
   *  touches it. Held still past the debounce, the block arms; the drag then
   *  carries it, and a release outside the conversation pulls it out there.
   *  The selection is read at the PRESS, so selected lines are what is held.
   *  Planted `plantNoDebounce`: a press picks up at once, as `draggable` did
   *  -- a click-drag selects nothing. */
  static HOLD_MS = 350;
  static plantNoDebounce = false;
  holdStats = { armed: 0, cancelled_by_move: 0, clicks: 0 };
  private holdToPull(el: HTMLElement, piece: () => Piece): void {
    el.addEventListener("pointerdown", (e: PointerEvent) => {
      // A tool on the block (run, terminal, open, unnest) is a button, never a pull.
      if (e.button !== 0 || (e.target as HTMLElement)?.closest?.("button, a, input, textarea")) return;
      const x0 = e.clientX, y0 = e.clientY;
      const held = piece();               // the selection as it is at the press
      let armed = false, ghost: HTMLElement | null = null;
      const arm = () => {
        armed = true; this.holdStats.armed++;
        el.addClass("is-armed");
        document.body.addClass("domvec-chatui-pulling");
        window.getSelection()?.removeAllRanges();
        ghost = document.body.createDiv({ cls: "domvec-chatui-ghost", text: held.text.split("\n").slice(0, 4).join("\n") });
        ghost.style.left = x0 + 8 + "px"; ghost.style.top = y0 + 8 + "px";
      };
      const timer = ChatUI.plantNoDebounce ? (arm(), 0) : window.setTimeout(arm, ChatUI.HOLD_MS);
      const move = (m: PointerEvent) => {
        if (!armed) {
          if (Math.hypot(m.clientX - x0, m.clientY - y0) > 4) { window.clearTimeout(timer); this.holdStats.cancelled_by_move++; done(); }
          return;
        }
        m.preventDefault();
        if (ghost) { ghost.style.left = m.clientX + 8 + "px"; ghost.style.top = m.clientY + 8 + "px"; }
      };
      const up = (u: PointerEvent) => {
        window.clearTimeout(timer);
        if (!armed) { this.holdStats.clicks++; done(); return; }
        const r = this.el.getBoundingClientRect();
        const inside = u.clientX >= r.left && u.clientX <= r.right && u.clientY >= r.top && u.clientY <= r.bottom;
        done();
        if (!inside) void this.pull(held, { x: u.clientX, y: u.clientY });
      };
      const done = () => {
        window.removeEventListener("pointermove", move, true);
        window.removeEventListener("pointerup", up, true);
        el.removeClass("is-armed");
        document.body.removeClass("domvec-chatui-pulling");
        ghost?.remove(); ghost = null;
      };
      window.addEventListener("pointermove", move, true);
      window.addEventListener("pointerup", up, true);
    });
  }

  /** The block, or the lines of it the reader has SELECTED (a code block's
   *  line range, 182's screenshot). */
  pieceFrom(el: HTMLElement, blk: ChatBlock, t: number, b: number): Piece {
    const sel = window.getSelection();
    const s = sel && !sel.isCollapsed ? sel.toString() : "";
    if (blk.kind === "code" && s.trim() && el.contains(sel!.anchorNode) && blk.text.includes(s.trim())) {
      const lines = rangeOf(blk.text, s);
      if (lines) {
        const all = blk.text.split(/\r?\n/);
        return { address: addressOf(this.file.path, t, b, lines), kind: "code", lang: blk.lang,
                 text: all.slice(lines[0] - 1, lines[1]).join(NL), lines };
      }
    }
    return { address: addressOf(this.file.path, t, b), kind: blk.kind, lang: blk.lang, text: blk.text };
  }

  async pull(piece: Piece, at: { x: number; y: number }): Promise<string | void> {
    if (!this.host.pullOut) return;
    const made = await this.host.pullOut(piece, at);
    if (made) this.stats.pulled++;
    return made;
  }

  /** Send the input box's text: the turn and the reply go INTO the note. */
  async ask(prompt?: string): Promise<string> {
    const p = (prompt ?? this.input.value).trim();
    if (!p || this.busy) return "";
    this.busy = true; this.el.addClass("is-busy");
    this.input.value = ""; this.grow();
    let reply = "", timer = 0;
    try {
      const ctx = await this.host.context(p);
      const paint = () => { timer = 0; void this.render({ prompt: p, reply }); };
      void this.render({ prompt: p, reply: "" });
      reply = await this.host.stream(p, ctx, (tok) => {
        reply += tok; this.stats.tokens++;
        if (!timer) timer = window.setTimeout(paint, 120);
      });
      if (timer) window.clearTimeout(timer);
      await this.append(p, reply);
      this.stats.sends++;
    } catch (err) {
      this.stats.last_error = String((err as any)?.message || err);
      await this.append(p, "*(no reply: " + this.stats.last_error + ")*");
    } finally {
      this.busy = false; this.el.removeClass("is-busy");
      await this.render();
    }
    return reply;
  }

  private async append(prompt: string, reply: string): Promise<void> {
    const old = await this.text();
    const { draft } = parseConversation(old);
    // An old chat note's body was its prompt: it is now the first turn's, not loose text.
    const base = draft ? old.slice(0, old.lastIndexOf(draft)) + old.slice(old.lastIndexOf(draft) + draft.length) : old;
    await this.app.vault.modify(this.file, base.replace(/\s+$/, "") + NL + turnText("You", prompt) + turnText(this.host.model(), reply.trim()));
  }
}

