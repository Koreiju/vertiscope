/**
 * The notebook chat -- `L-2`..`L-9`, and `G-44`'s notebook half (PLUGIN_GOAL,
 * "The minimal embedded chat"). The model is L-1's, through the same
 * `POST /chat` the browser cell uses, so a cell is sent to a conversation at
 * most once (keyed by its content: a cell whose output changed is new).
 *
 * "an embedded tool within the jupyter notebook panels; at the bottom of the
 * cell that has been selected" -- the panel sits at the selected cell's foot;
 * "a *hovering one* that follows the user's scrolls" -- it is clamped to the
 * view while the cell scrolls out of it; "does not apply a new re-wind ...
 * until the user has selected/interacted with a new cell" -- the rewind's
 * range is fixed when the cursor lands on a cell, never on scroll; "injected
 * into the user prompt as the effective contextual history" -- the rewound
 * cells go ahead of the prompt; "the user prompt decides how many" -- `@N`;
 * "within a safety factor of the maximum token limit" -- `SAFETY` of the
 * model's window.
 *
 * Reading of the verbatim, mine: the rewind's RANGE is fixed on landing and
 * its TEXT read when the prompt is sent, so an edit to the selected cell is
 * in the "current state" the verbatim asks for; and the conversation is shown
 * at the cell, not written into the note (writing to notebooks is deferred by
 * name, `L-11`).
 */
import { Component, MarkdownRenderer, MarkdownView, type App, type TFile } from "obsidian";
import type { Sidecar } from "./sidecar";
import type { NoteMarks } from "./marks";
import { cellAt, cellsOf, parseRewind, rewind, type Cell } from "./rewind";

/** The model's window (`domvec/chat.py`: n_ctx 8192) and the share one rewind may take. */
export const N_CTX = 8192;
export const SAFETY = 0.35;
/** The band below the scroll window the collapsed chat rests in (P-M5). */
export const DOCK_PX = 40;

export interface NotebookTurn { prompt: string; cells: number; source: string; sent: number; dropped: number; chars: number; reply: string; ms: number }

export class NotebookChat {
  readonly el: HTMLElement;
  private log: HTMLElement;
  private input: HTMLTextAreaElement;
  private label: HTMLElement;
  private clearMarks: HTMLElement;
  /** The cell the rewind ends at, fixed when the cursor landed on it. */
  landed: { index: number; from: number; hash: string } | null = null;
  /** Rewinds applied: one per landing on a new cell, none per scroll. */
  rewinds = 0;
  turns: NotebookTurn[] = [];
  busy = false;
  lastError = "";
  /** The last rewind sent, for the harness. */
  lastRewind: { cells: number; chars: number; budget: number; cut: boolean; limit: number | null } | null = null;
  /** Planted (L-6): a new rewind on every scroll, as a scroll-follower would. */
  plantRewindOnScroll = false;
  /** Planted (L-9): no budget -- the whole note above the cell. */
  plantNoBudget = false;
  /** Planted (P-N10): the reader's marks are ignored, the rewind sent instead. */
  plantIgnoreMarks = false;
  /** Planted (P-M5): no band -- the strip clamps over the note's last lines. */
  plantNoDock = false;
  /** Placed in the band below the scroll window, not at a cell's foot. */
  docked = false;
  /** What the last turn was given: "marks" or "rewind". */
  lastSource = "";
  private scrollEl: HTMLElement | null = null;
  private onScroll = () => this.place();

  constructor(private app: App, private owner: Component, private view: MarkdownView, private sidecar: Sidecar,
              private marks: NoteMarks | null = null) {
    this.el = view.contentEl.createDiv({ cls: "domvec-nbchat" });
    const bar = this.el.createDiv({ cls: "domvec-chat-bar" });
    this.label = bar.createSpan({ cls: "domvec-chat-label" });
    this.clearMarks = bar.createEl("button", { text: "clear marks", cls: "domvec-chat-reset" });
    this.clearMarks.onclick = () => { if (this.view.file) void this.marks?.clear(this.view.file.path); };
    const reset = bar.createEl("button", { text: "new chat", cls: "domvec-chat-reset" });
    reset.onclick = () => void this.reset();
    this.log = this.el.createDiv({ cls: "domvec-chat-log markdown-rendered" });
    this.input = this.el.createEl("textarea", { cls: "domvec-chat-input" });
    this.input.placeholder = "Ask about the cells above -- @3 for the last 3 -- Enter sends";
    this.input.rows = 2;
    this.input.addEventListener("keydown", (e: KeyboardEvent) => {
      e.stopPropagation();
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        const q = this.input.value;
        if (q.trim()) { this.input.value = ""; void this.send(q); }
      }
    });
    this.el.addEventListener("mouseenter", () => this.open(true));
    this.el.addEventListener("mouseleave", () => { if (document.activeElement !== this.input && !this.busy) this.open(false); });
    this.attachScroll();
    this.refresh();
  }

  get session(): string { return "note:" + (this.view.file?.path || "untitled"); }
  get isOpen(): boolean { return this.el.hasClass("is-open"); }
  open(on: boolean): void { this.el.toggleClass("is-open", on); this.place(); }

  private cm(): any { return (this.view.editor as any)?.cm; }

  private attachScroll(): void {
    const sd: HTMLElement | null = this.cm()?.scrollDOM || null;
    if (sd === this.scrollEl) return;
    this.scrollEl?.removeEventListener("scroll", this.onScroll);
    this.scrollEl = sd;
    sd?.addEventListener("scroll", () => {
      this.onScroll();
      if (this.plantRewindOnScroll) this.land(true);
    }, { passive: true });
  }

  private text(): string { return this.view.editor?.getValue() ?? ""; }

  /** The cursor moved: a NEW cell is a new rewind; the same cell is not. */
  land(force = false): void {
    this.attachScroll();
    const ed = this.view.editor;
    if (!ed) return;
    const cells = cellsOf(this.text());
    if (!cells.length && !this.marked()) { this.landed = null; this.el.hide(); this.dock(false); return; }
    this.el.show();
    this.dock(true);
    if (!cells.length) { this.landed = null; this.refresh(); return; }
    // "last-most viewable cell within current selection": the selection's END.
    const line = Math.max(ed.getCursor("from").line, ed.getCursor("to").line);
    const index = cellAt(cells, line);
    const c = cells[index];
    if (force || !this.landed || this.landed.index !== index || this.landed.from !== c.from) {
      this.landed = { index, from: c.from, hash: c.hash };
      this.rewinds++;
    }
    this.refresh();
  }

  /** Shown: the scroll window gives up a band at its foot (P-M5). */
  private dock(on: boolean): void {
    this.view.contentEl.toggleClass("domvec-chat-dock", on && !this.plantNoDock);
  }

  /**
   * At the foot of the selected cell while that foot is in view (L-2);
   * otherwise -- the cell scrolled away, the reading view, a marked note with
   * no cells -- in the band BELOW the scroll window's boundary (P-M5: "the
   * hovering chat is always below the boundary of the scrollable markdown
   * window"), so it never lies over text. Open, it grows upward over the
   * view, which is what hovering it asks for.
   */
  place(): void {
    const host = this.view.contentEl.getBoundingClientRect();
    const h = this.el.offsetHeight || 28;
    const band = this.view.contentEl.hasClass("domvec-chat-dock") ? DOCK_PX : 0;
    const docked = host.height - h - (this.isOpen ? 6 : Math.max(6, (band - h) / 2));
    let top = docked;
    const cm = this.cm();
    const cells = this.landed ? cellsOf(this.text()) : [];
    const c = this.landed ? cells[Math.min(this.landed.index, cells.length - 1)] : null;
    if (cm && c && this.view.getMode() === "source") {
      try {
        const pos = cm.state.doc.line(Math.min(c.to + 1, cm.state.doc.lines)).to;
        const at = cm.coordsAtPos(pos);
        // The foot only while the strip would sit inside the scroll window.
        if (at && at.bottom + 4 - host.top + h <= host.height - band) top = Math.max(8, at.bottom + 4 - host.top);
      } catch { /* the line is not laid out: docked */ }
    }
    this.docked = top === docked;
    this.el.style.top = `${Math.round(top)}px`;
  }

  /** The rewind that would be sent now: the landed range, its current text. */
  pendingRewind(limit: number | null) {
    const cells = cellsOf(this.text());
    if (!this.landed || !cells.length) return null;
    const end = Math.min(this.landed.index, cells.length - 1);
    if (this.plantNoBudget) {
      const all = cells.slice(0, end + 1);
      return { cells: all, chars: all.reduce((a, c) => a + c.text.length, 0), budget: Infinity, cut: false };
    }
    return rewind(cells, end, { nCtx: N_CTX, safety: SAFETY, limit });
  }

  /** How many addresses the reader marked in this note (P-N10). */
  marked(): number { return this.view.file && this.marks ? this.marks.count(this.view.file.path) : 0; }

  markdown(): string {
    const out: string[] = [];
    for (const t of this.turns) {
      out.push(`> **You** -- ${t.source === "marks" ? `${t.cells} marked chunk${t.cells === 1 ? "" : "s"}` : `rewound ${t.cells} cell${t.cells === 1 ? "" : "s"}`}, ${t.sent} new to the chat\n> ${t.prompt.replace(/\n/g, "\n> ")}`);
      out.push(t.reply || "*(no reply)*");
    }
    if (this.busy) out.push("*thinking...*");
    if (this.lastError) out.push(`*${this.lastError}*`);
    return out.join("\n\n");
  }

  refresh(): void {
    const r = this.pendingRewind(null), m = this.marked();
    this.label.setText(`chat${this.turns.length ? ` · ${this.turns.length}` : ""}`
      + (m ? ` · context: ${m} marked` : r ? ` · rewinds ${r.cells.length} cell${r.cells.length === 1 ? "" : "s"}` : ""));
    this.clearMarks.toggle(m > 0);
    this.log.empty();
    void MarkdownRenderer.render(this.app, this.markdown() || "*Ask about this cell and the ones above it.*",
      this.log, this.view.file?.path || "", this.owner).then(() => { this.log.scrollTop = this.log.scrollHeight; this.place(); });
  }

  async send(raw: string): Promise<NotebookTurn | null> {
    if (this.busy) return null;
    if (!this.landed) this.land();
    const { limit, prompt } = parseRewind(raw);
    const path = this.view.file?.path || "";
    let context: { cid: string; url: string; markdown: string; head: string }[];
    let given: number;
    // The reader's marks, when there are any, ARE the context (P-N10): their
    // addresses resolved against the note's current text, in note order.
    const marked = this.view.file && this.marks && this.marked() && !this.plantIgnoreMarks
      ? (await this.marks.resolve(this.view.file)).sort((a, b) => a.from - b.from) : [];
    if (marked.length) {
      context = marked.map((m) => ({ cid: m.cid, url: m.url + "#" + m.xpath, markdown: m.markdown,
        head: `marked, lines ${m.from + 1}-${m.to + 1}` }));
      given = marked.length;
      this.lastSource = "marks";
      if (this.marks) this.marks.stats.sent += marked.length;
    } else {
      const r = this.pendingRewind(limit);
      if (!r) { this.lastError = "no cell selected"; this.refresh(); return null; }
      this.lastRewind = { cells: r.cells.length, chars: r.chars, budget: r.budget, cut: r.cut, limit };
      context = r.cells.map((c: Cell) => ({ cid: "cell:" + c.hash, url: `vault://${path}#L${c.from + 1}`,
        markdown: c.text, head: `${c.kind} cell, line ${c.from + 1}` }));
      given = r.cells.length;
      this.lastSource = "rewind";
    }
    this.busy = true; this.lastError = ""; this.open(true); this.refresh();
    try {
      const got = await this.sidecar.chat(this.session, prompt || raw, context);
      if (!got || got.error || !got.turn) {
        this.lastError = `the chat did not answer${got && got.error ? `: ${String(got.error).slice(0, 120)}` : ""}`;
        return null;
      }
      const t = got.turn;
      const turn: NotebookTurn = { prompt: prompt || raw, cells: given, source: this.lastSource, sent: t.context.length,
        dropped: t.resent_dropped.length, chars: t.delta_chars, reply: t.reply, ms: t.ms };
      this.turns.push(turn);
      return turn;
    } finally {
      this.busy = false;
      this.refresh();
    }
  }

  async reset(): Promise<void> {
    await this.sidecar.chat(this.session, "", [], true);
    this.turns = []; this.lastError = "";
    this.refresh();
  }

  destroy(): void {
    this.scrollEl?.removeEventListener("scroll", this.onScroll);
    this.dock(false);
    this.el.remove();
  }
}

/** One chat per open note view that holds a code cell (a notebook). */
export class NotebookChats {
  readonly byView = new Map<MarkdownView, NotebookChat>();
  /** The reader's marks (P-N10), set by the plugin. */
  marks: NoteMarks | null = null;
  constructor(private app: App, private owner: Component, private sidecar: Sidecar) {}

  /** The chat of the active note, made when it is a notebook. */
  forActive(): NotebookChat | null {
    const view = this.app.workspace.getActiveViewOfType(MarkdownView);
    return view ? this.forView(view) : null;
  }

  /** A view's chat: a notebook's, or any note's the reader has marked. */
  forView(view: MarkdownView): NotebookChat | null {
    if (!view.file) return null;
    let chat = this.byView.get(view);
    const isNotebook = /^\s*(`{3,}|~{3,})/m.test(view.editor?.getValue() ?? "")
      || !!(this.marks && this.marks.count(view.file.path));
    if (!isNotebook) { if (chat) { chat.destroy(); this.byView.delete(view); } return null; }
    if (!chat || !chat.el.isConnected) {
      chat = new NotebookChat(this.app, this.owner, view, this.sidecar, this.marks);
      this.byView.set(view, chat);
    }
    return chat;
  }

  /** The cursor moved in some editor. */
  onCursor(): void { this.forActive()?.land(); }

  forFile(file: TFile): NotebookChat | null {
    for (const [v, c] of this.byView) if (v.file === file) return c;
    return null;
  }

  destroy(): void { for (const c of this.byView.values()) c.destroy(); this.byView.clear(); }
}
