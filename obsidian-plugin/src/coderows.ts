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
import { type App } from "obsidian";
import { cellSource, findFences } from "./fences";
import type { PlaneDesk } from "./planepanels";

export interface RowsHost { app: App; desk: PlaneDesk; settings: { sidecar: string } }

const NL = String.fromCharCode(10);

export class CodeRows {
  stats = { mounted: 0, drawn: 0, edits: 0, refused: 0, last: null as any };
  /** Planted: edits are drawn but never written back. */
  plantNoWrite = false;
  private seen = new Map<string, string>();       // path -> the cell source last drawn

  constructor(private host: RowsHost) {}

  /** The card's first python cell: its source and its body's line span in the editor. */
  private cellOf(path: string): { ed: any; code: string; from: number; to: number } | null {
    const v = this.host.desk.viewOf(path);
    if (!v || !v.editor) return null;
    const f = findFences(v.editor.getValue()).find((x) => /^py(thon3?)?$/.test(x.lang));
    if (!f) return null;
    return { ed: v.editor, code: cellSource(f.body), from: f.openLine + 1, to: f.closeLine };
  }

  private async post(body: any): Promise<any> {
    const base = this.host.settings.sidecar.replace(/\/+$/, "");
    const r = await fetch(base + "/code_rows", { method: "POST", headers: { "Content-Type": "application/json", "X-Domvec-Client": "obsidian-plugin" },
                                                 body: JSON.stringify(body) });
    return r.json();
  }

  /** Every plane card with a python cell gets its rows strip, kept in step with the text. */
  async sweep(): Promise<void> {
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
    for (const p of this.host.desk.panels) {
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
      this.draw(strip, p.path, got.rows || []);
    }
  }

  private draw(strip: HTMLElement, path: string, rows: any[]): void {
    // A field being edited keeps its focus: never redrawn under the reader.
    if (strip.contains(document.activeElement)) return;
    strip.empty();
    this.stats.drawn++;
    const field = (row: HTMLElement, cls: string, value: string, op: string, name: string, editable: boolean) => {
      const el = row.createEl("input", { cls: "domvec-rows-" + cls, attr: { value, placeholder: cls, spellcheck: "false" } }) as HTMLInputElement;
      el.dataset.row = name; el.dataset.op = op;
      el.readOnly = !editable;
      el.size = Math.max(2, Math.min(28, value.length + 1));
      if (editable) el.addEventListener("change", () => { void this.edit(path, op, name, el.value); });
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
  async edit(path: string, op: string, name: string, value: string): Promise<boolean> {
    const c = this.cellOf(path);
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
    // The body's lines replaced in the editor (the fence lines kept).
    const now = this.cellOf(path)!;
    const body = String(got.source).replace(/\n+$/, "");
    now.ed.replaceRange(body + NL, { line: now.from, ch: 0 }, { line: now.to, ch: 0 });
    this.stats.edits++;
    this.stats.last = { path, op, name, value };
    return true;
  }
}
