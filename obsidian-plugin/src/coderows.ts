/**
 * A code card's typed rows, drawn on its plane card as fields (G-378;
 * PLUGIN_GOAL 167 c, mortegon M.2-M.5).
 *
 * A notebook card's python cell reads as rows -- `name : Type = value` -- and
 * each part is a field the reader edits in place: no verb to type (CLAUDE.md
 * constraint 2). An edit goes to the sidecar (`POST /code_rows`), which writes
 * it back into the cell's source with LibCST (`domvec/code_rows.py`: comments
 * and formatting kept, a rename following the cell's reads); the returned
 * source replaces the cell's body through the card's EDITOR, whose own save
 * persists it (a file write would race the autosave, as `storeOutput` found).
 *
 * A class row unfolds into its fields, a function row into its parameters,
 * shown read-only beneath it: the editable rows are the module's own.
 *
 * In trie terms: the card is a `vault://` page and the cell a fence in it;
 * a row is the binding's place in that fence, and an edit is a write to the
 * page's text, re-indexed as any edit is.
 */
import { TFile, type App } from "obsidian";
import { cellSource, findFences } from "./fences";
import type { PlaneDesk } from "./planepanels";

export interface RowsHost { app: App; desk: PlaneDesk; settings: { sidecar: string } }

/** Where a block's rows write back: a note and its fence's opening line
 *  (182, "generalized in their interfaces no matter whether or not they are
 *  within a markdown panel or their own panel" -- one target for both). */
export interface FenceTarget { path: string; line: number }

const NL = String.fromCharCode(10);

export class CodeRows {
  stats = { mounted: 0, drawn: 0, edits: 0, refused: 0, last: null as any };
  /** Planted: edits are drawn but never written back. */
  plantNoWrite = false;
  private seen = new Map<string, string>();       // path -> the cell source last drawn
  /** Planted (182): rows only on a code card of its own -- a python block in
   *  a markdown panel or a chat turn gets the tools but not its rows. */
  plantCardOnly = false;
  blockStats = { mounted: 0, drawn: 0 };
  private bySource = new Map<string, any>();

  /** A python block's rows UNDER the block, wherever it is drawn (a markdown
   *  panel's reading view, a chat turn): the same rows, the same fields, the
   *  same write-back as a code card's (182). */
  async mountUnder(pre: HTMLElement, target: FenceTarget, code: string): Promise<void> {
    if (this.plantCardOnly || target.line < 0 || !code.trim()) return;
    let strip = pre.nextElementSibling as HTMLElement | null;
    if (!strip || !strip.classList.contains("domvec-rows")) {
      strip = pre.ownerDocument.createElement("div");
      strip.className = "domvec-rows is-block";
      pre.after(strip);
      this.blockStats.mounted++;
    }
    this.style();
    // Rows are a function of the block's source alone: a re-render (a chat
    // repaints on every note change) does not ask again.
    let got = this.bySource.get(code);
    if (!got) {
      got = await this.post({ source: code }).catch(() => null);
      if (got && !got.error) { this.bySource.set(code, got); if (this.bySource.size > 200) this.bySource.delete(this.bySource.keys().next().value as string); }
    }
    if (!got || got.error || !(got.rows || []).length) { strip.remove(); return; }
    this.blockStats.drawn++;
    this.draw(strip, target, got.rows || []);
  }

  /** The fence at `target` -- in the note's open editor when it has one (an
   *  editor's autosave would undo a file write), else in the file. */
  private async fenceAt(target: FenceTarget): Promise<{ text: string; code: string; from: number; to: number; ed: any } | null> {
    const v = this.host.desk.viewOf(target.path) as any;
    const f = this.host.app.vault.getAbstractFileByPath(target.path);
    const text = v?.editor ? v.editor.getValue() : f instanceof TFile ? await this.host.app.vault.read(f) : "";
    const fence = findFences(text).find((x) => x.openLine === target.line);
    if (!fence) return null;
    return { text, code: cellSource(fence.body), from: fence.openLine + 1, to: fence.closeLine, ed: v?.editor || null };
  }

  constructor(private host: RowsHost) {}

  /** The card's first python cell: its source and its body's line span in the editor. */
  private cellOf(path: string): { ed: any; code: string; from: number; to: number; line: number } | null {
    const v = this.host.desk.viewOf(path);
    if (!v || !v.editor) return null;
    const f = findFences(v.editor.getValue()).find((x) => /^py(thon3?)?$/.test(x.lang));
    if (!f) return null;
    return { ed: v.editor, code: cellSource(f.body), from: f.openLine + 1, to: f.closeLine, line: f.openLine };
  }

  private style(): void { this.styleOnce(); }

  private async post(body: any): Promise<any> {
    const base = this.host.settings.sidecar.replace(/\/+$/, "");
    const r = await fetch(base + "/code_rows", { method: "POST", headers: { "Content-Type": "application/json", "X-Domvec-Client": "obsidian-plugin" },
                                                 body: JSON.stringify(body) });
    return r.json();
  }

  /** Every plane card with a python cell gets its rows strip, kept in step with the text. */
  async sweep(): Promise<void> {
    this.style();
    for (const p of this.host.desk.panels) {
      // A chat card's blocks carry their OWN rows, under each block (182).
      if (p.card.classList.contains("is-chat")) { p.card.querySelector(":scope > .domvec-rows")?.remove(); continue; }
      const c = this.cellOf(p.path);
      let strip = p.card.querySelector(":scope > .domvec-rows") as HTMLElement | null;
      if (!c || !c.code.trim()) { strip?.remove(); this.seen.delete(p.path); continue; }
      if (!strip) { strip = p.card.createDiv({ cls: "domvec-rows" }); this.stats.mounted++; }
      if (this.seen.get(p.path) === c.code) continue;
      this.seen.set(p.path, c.code);
      const got = await this.post({ source: c.code }).catch(() => null);
      // No rows to draw (a cell mid-edit that does not parse, or a sidecar
      // without the route): no strip, rather than an error under every card.
      if (!got || got.error) { strip.remove(); this.stats.last = { path: p.path, unread: got ? got.error : "no answer" }; continue; }
      this.draw(strip, { path: p.path, line: c.line }, got.rows || []);
    }
  }

  private styleOnce(): void {
    if (!document.getElementById("domvec-rows-style")) {
      const st = document.head.createEl("style", { attr: { id: "domvec-rows-style" } });
      st.textContent = [
        ".domvec-rows{display:flex;flex-direction:column;gap:2px;padding:4px 8px;border-top:1px solid var(--background-modifier-border);font-family:var(--font-monospace);font-size:11px}",
        ".domvec-rows-row{display:flex;align-items:center;gap:4px}",
        ".domvec-rows-row input{background:transparent;border:none;border-bottom:1px dotted var(--background-modifier-border);color:var(--text-normal);font:inherit;padding:0 2px;height:16px}",
        ".domvec-rows-row input:read-only{color:var(--text-muted);border-bottom-color:transparent}",
        ".domvec-rows-row input:focus{border-bottom:1px solid var(--interactive-accent);outline:none}",
        ".domvec-rows-name{font-weight:600}.domvec-rows-sep{color:var(--text-faint)}.domvec-rows-type{color:var(--text-accent)}",
        ".domvec-rows-row.is-inner{opacity:.8}",
      ].join(NL);
    }
  }

  private draw(strip: HTMLElement, target: FenceTarget, rows: any[]): void {
    // A field being edited keeps its focus: never redrawn under the reader.
    if (strip.contains(document.activeElement)) return;
    strip.empty();
    this.stats.drawn++;
    const field = (row: HTMLElement, cls: string, value: string, op: string, name: string, editable: boolean) => {
      const el = row.createEl("input", { cls: "domvec-rows-" + cls, attr: { value, placeholder: cls, spellcheck: "false" } }) as HTMLInputElement;
      el.dataset.row = name; el.dataset.op = op;
      el.readOnly = !editable;
      el.size = Math.max(2, Math.min(28, value.length + 1));
      if (editable) el.addEventListener("change", () => { void this.edit(target, op, name, el.value); });
      el.addEventListener("mousedown", (e) => e.stopPropagation());   // a field is the editor's, never a pull (182)
      el.addEventListener("keydown", (e) => { if (e.key === "Enter") el.blur(); e.stopPropagation(); });
      return el;
    };
    const line = (r: any, depth: number) => {
      const row = strip.createDiv({ cls: "domvec-rows-row" + (depth ? " is-inner" : "") });
      row.style.paddingLeft = (depth * 14) + "px";
      const editable = depth === 0 && r.kind === "value";
      field(row, "name", r.name, "rename", r.name, depth === 0);
      row.createSpan({ cls: "domvec-rows-sep", text: ":" });
      field(row, "type", r.type || "", "type", r.name, editable);
      row.createSpan({ cls: "domvec-rows-sep", text: "=" });
      field(row, "value", r.kind === "value" || r.kind === "param" ? (r.value || "") : r.kind, "value", r.name, editable);
      for (const c of r.children || []) line(c, depth + 1);
    };
    for (const r of rows) line(r, 0);
  }

  /** One field's edit, written back into the cell. */
  async edit(target: FenceTarget | string, op: string, name: string, value: string): Promise<boolean> {
    if (typeof target === "string") { const cc = this.cellOf(target); if (!cc) return false; target = { path: target, line: cc.line }; }
    const path = target.path;
    const c = await this.fenceAt(target);
    if (!c) return false;
    const e = op === "rename" ? { op, name, to: value } : op === "type" ? { op, name, type: value } : { op, name, value };
    const got = await this.post({ source: c.code, edit: e }).catch((x) => ({ error: String(x) }));
    if (!got || got.error) {
      this.stats.refused++;
      this.stats.last = { path, op, name, refused: got ? got.error : "no answer" };
      this.seen.delete(path);                      // redraw the row as the source still has it
      return false;
    }
    if (this.plantNoWrite) { this.stats.last = { path, op, name, planted: true }; return false; }
    // The body's lines replaced -- in the editor when the note has one
    // (the fence lines kept), else in the file.
    const now = (await this.fenceAt(target))!;
    const body = String(got.source).replace(/\n+$/, "");
    if (now.ed) now.ed.replaceRange(body + NL, { line: now.from, ch: 0 }, { line: now.to, ch: 0 });
    else {
      const f = this.host.app.vault.getAbstractFileByPath(path) as TFile;
      await this.host.app.vault.process(f, (t) => { const L = t.split(NL); L.splice(now.from, now.to - now.from, ...body.split(NL)); return L.join(NL); });
    }
    this.stats.edits++;
    this.stats.last = { path, op, name, value };
    return true;
  }
}
