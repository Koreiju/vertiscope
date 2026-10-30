/**
 * The browser cell's chat -- `G-43`, `G-44`, `G-45` (PLUGIN_GOAL, O.2).
 *
 * "a hoverable chat panel on the standalone browser window ... that collects
 * the right-click selected *full* markdowns as context efficiently so that the
 * same chunks are *never* re-sent to the context window"; "the right-clicked
 * elements after the most previous response are included in the very next
 * prompt (pre-injected into the markdown obsidian panel, and then injected
 * into the prompt during conversations)"; "Chat outputs would be in a panel
 * below the web-selected markdown ... all in markdown".
 *
 * So there is no context box. The pins ARE the selection: the ones made since
 * the last reply are shown, pre-injected, at the foot of the conversation,
 * and go with the next prompt -- once. The conversation is rendered as
 * markdown below the pinned markdown on the cell's markdown face, and the
 * input is a strip on the browser that opens on hover. The sidecar holds the
 * conversation and refuses a chunk it has already sent (`domvec/chat.py`).
 */
import { Component, MarkdownRenderer, type App } from "obsidian";
import type { Sidecar } from "./sidecar";

export interface ChatPin { cid: string; url: string; markdown: string; head: string }

export interface ChatTurn {
  prompt: string;
  context: { cid: string; url: string; head?: string }[];
  reply: string;
  delta_chars: number;
  resent_dropped: string[];
  ms: number;
}

export class ChatPanel {
  /** The strip on the browser: hover opens it. */
  readonly el: HTMLElement;
  private log: HTMLElement;
  private input: HTMLTextAreaElement;
  private label: HTMLElement;
  /** Chunks this conversation has sent, as the SIDECAR reports them. */
  sent = new Set<string>();
  turns: ChatTurn[] = [];
  busy = false;
  lastError = "";
  readonly session: string;
  /** Planted (G-45): the panel sends every pin every turn -- the sidecar's
   *  at-most-once edge is what then keeps the context window clean. */
  plantSendAllPins = false;
  /** Planted (G-43): the strip never opens on hover. */
  plantNoHover = false;

  constructor(private app: App, private owner: Component, host: HTMLElement, private sidecar: Sidecar,
              private pins: () => ChatPin[], private onChange: () => void) {
    this.session = "cell-" + Math.random().toString(36).slice(2, 10);
    this.el = host.createDiv({ cls: "domvec-chat" });
    const bar = this.el.createDiv({ cls: "domvec-chat-bar" });
    this.label = bar.createSpan({ cls: "domvec-chat-label" });
    const reset = bar.createEl("button", { text: "new chat", cls: "domvec-chat-reset" });
    reset.onclick = () => void this.reset();
    this.log = this.el.createDiv({ cls: "domvec-chat-log markdown-rendered" });
    this.input = this.el.createEl("textarea", { cls: "domvec-chat-input" });
    this.input.placeholder = "Ask about what you pinned -- Enter sends, Shift+Enter for a new line";
    this.input.rows = 2;
    this.input.addEventListener("keydown", (e: KeyboardEvent) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        const q = this.input.value;
        if (q.trim()) { this.input.value = ""; void this.send(q); }
      }
    });
    this.el.addEventListener("mouseenter", () => { if (!this.plantNoHover) this.open(true); });
    this.el.addEventListener("mouseleave", () => {
      if (document.activeElement !== this.input && !this.busy) this.open(false);
    });
    this.input.addEventListener("blur", () => { if (!this.el.matches(":hover") && !this.busy) this.open(false); });
    this.refresh();
  }

  open(on: boolean): void { this.el.toggleClass("is-open", on); }
  get isOpen(): boolean { return this.el.hasClass("is-open"); }

  /** Pins made since the last reply -- the next prompt's context. */
  pending(): ChatPin[] {
    const all = this.pins().slice().reverse();          // oldest first
    return this.plantSendAllPins ? all : all.filter((p) => !this.sent.has(p.cid));
  }

  /** The conversation as markdown: each turn's context and prompt, then the
   *  reply; and the pending pins, pre-injected, at the foot. */
  markdown(): string {
    const out: string[] = [];
    for (const t of this.turns) {
      const ctx = t.context.map((c) => `[${c.head || c.cid}](${c.url})`).join(" · ");
      out.push(`> **You**${ctx ? ` -- with ${ctx}` : ""}\n> ${t.prompt.replace(/\n/g, "\n> ")}`);
      out.push(t.reply || "*(no reply)*");
    }
    const next = this.pending();
    if (next.length) {
      out.push(`*Next prompt includes ${next.length} pinned chunk${next.length > 1 ? "s" : ""}:* `
        + next.map((p) => `[${titleOf(p)}](${p.url})`).join(" · "));
    }
    if (this.busy) out.push("*thinking...*");
    if (this.lastError) out.push(`*${this.lastError}*`);
    return out.join("\n\n");
  }

  /** The conversation below the pinned markdown on the markdown face. */
  async renderInto(el: HTMLElement): Promise<void> {
    if (!this.turns.length && !this.pending().length) return;
    const box = el.createDiv({ cls: "domvec-chat-transcript markdown-rendered" });
    box.createDiv({ cls: "domvec-browser-mdhead" }).setText("chat");
    const body = box.createDiv();
    await MarkdownRenderer.render(this.app, this.markdown(), body, "", this.owner);
  }

  /** Re-render the strip (the pins changed, or a reply came back). */
  refresh(): void {
    const n = this.pending().length;
    this.label.setText(`chat${this.turns.length ? ` · ${this.turns.length} turn${this.turns.length > 1 ? "s" : ""}` : ""}`
      + (n ? ` · ${n} pinned to send` : ""));
    this.log.empty();
    void MarkdownRenderer.render(this.app, this.markdown() || "*Pin chunks with a double right-click, then ask.*",
      this.log, "", this.owner).then(() => { this.log.scrollTop = this.log.scrollHeight; });
  }

  async send(prompt: string): Promise<ChatTurn | null> {
    if (this.busy) return null;
    const context = this.pending().map((p) => ({ cid: p.cid, url: p.url, markdown: p.markdown, head: titleOf(p) }));
    this.busy = true; this.lastError = ""; this.open(true);
    this.refresh();
    try {
      const got = await this.sidecar.chat(this.session, prompt, context);
      if (!got || got.error || !got.turn) {
        this.lastError = `the chat did not answer${got && got.error ? `: ${String(got.error).slice(0, 120)}` : ""}`;
        return null;
      }
      const turn = got.turn as ChatTurn;
      this.turns.push(turn);
      this.sent = new Set<string>(got.sent || []);
      return turn;
    } finally {
      this.busy = false;
      this.refresh();
      this.onChange();
    }
  }

  async reset(): Promise<void> {
    await this.sidecar.chat(this.session, "", [], true);
    this.turns = []; this.sent.clear(); this.lastError = "";
    this.refresh();
    this.onChange();
  }
}

/** A pin named the way a reader names it: its site and its opening words --
 *  never its xpath, which is what the chat first showed (2026-10-30). */
export function titleOf(p: ChatPin): string {
  const words = (p.markdown || "").split("\n").map((l) => l
    .replace(/!\[[^\]]*\]\([^)]*\)/g, "").replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/[#>*_`|\[\]]/g, "").replace(/\s+/g, " ").trim()).find((l) => l.length > 2) || "";
  const short = words.length > 48 ? words.slice(0, 47).replace(/\s+\S*$/, "") + "…" : words;
  return `${hostOf(p.url)} · ${short || p.cid}`;
}

function hostOf(url: string): string {
  try { return new URL(url).host; } catch { return url; }
}
