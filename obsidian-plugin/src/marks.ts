/**
 * The reader marks what the model is given -- `P-N9` and `P-N10`.
 *
 * "exposing the chunk scanning and selection highlighting for markdown
 * rendering in the alternative panel by the user to annotate the context fed
 * to our small language model" (Addendum II). `NOTEBOOK_PANEL_DESIGN` §5 reads
 * it as: a selection in the RENDERED view (reading mode -- the reader selects
 * content, not markers and fences), held as a set of TRIE ADDRESSES rather
 * than a string, and those addresses are the chat's context in place of the
 * rewind.
 *
 * An address is the chunk's `(xpath, part)` under the note's `vault://` url --
 * what `/chunk_preview` (the chunker the store uses, `P-N8`) says the selected
 * lines belong to; its cid is the store's own, `sha1(url|xpath|part)`. The
 * lines are not kept: they are re-resolved from the note's CURRENT text when
 * a block is painted or a prompt is sent, so an edit above a mark does not
 * move it onto someone else's text.
 *
 * Selecting inside chunks that are all marked already unmarks them -- the
 * same gesture both ways, no button needed; the chat's bar has a clear.
 */
import type { App, MarkdownView, TFile } from "obsidian";
import type { Sidecar } from "./sidecar";

/** An address, and the hash of the content it held when marked: the trie's
 *  own two keys (CLAUDE.md 5b). Vault xpaths are ordinal -- a section added
 *  above turns `section[3]` into `section[4]` -- so the content finds a mark
 *  that MOVED, and the address one whose own text was edited. */
export interface Mark { xpath: string; part: number; hash?: string }
export interface Resolved extends Mark { cid: string; url: string; from: number; to: number; markdown: string }

const keyOf = (m: Mark) => m.xpath + "#" + m.part;

async function sha16(s: string): Promise<string> {
  const d = await crypto.subtle.digest("SHA-1", new TextEncoder().encode(s));
  return Array.from(new Uint8Array(d)).map((b) => b.toString(16).padStart(2, "0")).join("").slice(0, 16);
}

export class NoteMarks {
  /** note path -> its marked addresses. Kept in the plugin's data. */
  byNote: Record<string, Mark[]> = {};
  /** The last spans resolved per note, for painting synchronously. */
  private spans = new Map<string, Resolved[]>();
  stats = { marked: 0, unmarked: 0, sent: 0, realigned: 0, last: null as any };
  /** Planted (P-N9): a selection marks nothing. */
  plantNoMarks = false;
  /** Planted (P-N9): a mark is its ordinal address alone, no content hash. */
  plantAddressOnly = false;

  constructor(private app: App, private sidecar: Sidecar, private save: () => Promise<void>,
              private onChange: (path: string) => void) {}

  urlOf(path: string): string { return "vault://" + this.app.vault.getName() + "/" + path; }
  count(path: string): number { return (this.byNote[path] || []).length; }

  /** A note's text as an open view of it holds it -- a tab or a panel on the
   *  plane -- else the file's: the file lags the editor by its autosave, and a
   *  section added a moment before put rendered lines and file lines out of
   *  step (P-N9 on the plane picked another chunk). */
  private async textOf(file: TFile, fromFile = false): Promise<string> {
    if (fromFile) return this.app.vault.read(file);
    const plane: any[] = (window as any).__domvecPlane?.leaves?.() || [];
    for (const leaf of [...this.app.workspace.getLeavesOfType("markdown"), ...plane]) {
      const v: any = leaf.view;
      if (v?.file?.path === file.path && typeof v.getViewData === "function") return String(v.getViewData());
    }
    return this.app.vault.cachedRead(file);
  }

  /** Resolve a note's marks against its current text: lines, markdown, cid.
   *  `fromFile` when the FILE just changed (`modify`): a write from outside the
   *  editor lands in the file before the view reloads it, and resolving
   *  against the view's old text put a mark on the lines its chunk HAD -- a
   *  section inserted above moved the highlight onto the block above (P-N9). */
  async resolve(file: TFile, fromFile = false): Promise<Resolved[]> {
    const marks = this.byNote[file.path] || [];
    if (!marks.length) { this.spans.delete(file.path); return []; }
    const text = await this.textOf(file, fromFile);
    const pv = await this.sidecar.chunkPreview(text, file.path, this.app.vault.getName());
    const lines = text.split("\n"), url = this.urlOf(file.path);
    const chunks = (pv && pv.chunks) || [];
    const mdOf = (c: { start_line: number; end_line: number }) => lines.slice(c.start_line, c.end_line + 1).join("\n");
    const byHash = new Map<string, any>(), byAddr = new Map<string, any>();
    for (const c of chunks) { byHash.set(await sha16(mdOf(c)), c); byAddr.set(keyOf(c), c); }
    const out: Resolved[] = [], seen = new Set<string>();
    for (const m of marks) {
      const c = (m.hash && !this.plantAddressOnly && byHash.get(m.hash)) || byAddr.get(keyOf(m));
      if (!c || seen.has(keyOf(c))) continue;
      seen.add(keyOf(c));
      m.xpath = c.xpath; m.part = c.part;          // the mark follows its chunk
      m.hash = await sha16(mdOf(c));
      out.push({ xpath: c.xpath, part: c.part, hash: m.hash, from: c.start_line, to: c.end_line,
                 cid: await sha16(url + "|" + c.xpath + "|" + c.part), url, markdown: mdOf(c) });
    }
    this.spans.set(file.path, out);
    return out;
  }

  /** The rendered blocks of a reading view: Obsidian's sections, with the
   *  source lines each draws (`start`/`end` are positions, `.line` 0-based). */
  private sections(view: MarkdownView): { el: HTMLElement; lineStart: number; lineEnd: number }[] {
    const raw = ((view as any).previewMode?.renderer?.sections || [])
      .filter((s: any) => s && s.el)
      .map((s: any) => ({ el: s.el, lineStart: s.start?.line ?? s.lineStart, lineEnd: s.end?.line ?? s.lineEnd }))
      .filter((s: any) => Number.isFinite(s.lineStart) && Number.isFinite(s.lineEnd));
    // The renderer's line numbers can lag an edit (a section inserted above
    // shifted them, and a selection marked the block above -- P-N9 on the
    // plane): each section's first rendered words must be on its first line;
    // where they are not, the section is moved to the nearest line that holds
    // them, its span kept.
    const data = typeof (view as any).getViewData === "function" ? String((view as any).getViewData()) : "";
    if (!data) return raw;
    const lines = data.split("\n");
    const norm = (t: string) => t.replace(/[#>*_`\[\]()-]/g, " ").replace(/\s+/g, " ").trim().toLowerCase();
    return raw.map((s: any) => {
      const words = norm((s.el.textContent || "").split("\n").find((l: string) => l.trim()) || "").slice(0, 32);
      if (!words || norm(lines[s.lineStart] || "").includes(words)) return s;
      let best = -1;
      for (let d = 1; d < lines.length && best < 0; d++) {
        for (const i of [s.lineStart - d, s.lineStart + d]) if (i >= 0 && i < lines.length && norm(lines[i]).includes(words)) { best = i; break; }
      }
      if (best < 0) return s;
      const shift = best - s.lineStart;
      this.stats.realigned = (this.stats.realigned || 0) + 1;
      return { el: s.el, lineStart: s.lineStart + shift, lineEnd: s.lineEnd + shift };
    });
  }

  /** A selection in the reading view, marked (or unmarked) as addresses. */
  async markSelection(view: MarkdownView): Promise<Mark[]> {
    const file = view.file;
    const sel = window.getSelection();
    if (!file || !sel || sel.isCollapsed || !sel.rangeCount || this.plantNoMarks) return [];
    const range = sel.getRangeAt(0);
    const hit = this.sections(view).filter((s) => range.intersectsNode(s.el));
    if (!hit.length) return [];
    const a = Math.min(...hit.map((s) => s.lineStart)), b = Math.max(...hit.map((s) => s.lineEnd));
    const text = await this.textOf(file);
    const pv = await this.sidecar.chunkPreview(text, file.path, this.app.vault.getName());
    const lines = text.split("\n");
    const picked: Mark[] = [];
    for (const c of ((pv && pv.chunks) || []).filter((c) => c.start_line <= b && c.end_line >= a))
      picked.push({ xpath: c.xpath, part: c.part, hash: await sha16(lines.slice(c.start_line, c.end_line + 1).join("\n")) });
    if (!picked.length) return [];
    const have = new Map((this.byNote[file.path] || []).map((m) => [keyOf(m), m]));
    const allMarked = picked.every((m) => have.has(keyOf(m)));
    for (const m of picked) { if (allMarked) have.delete(keyOf(m)); else have.set(keyOf(m), m); }
    if (allMarked) this.stats.unmarked += picked.length; else this.stats.marked += picked.length;
    this.byNote[file.path] = [...have.values()];
    if (!this.byNote[file.path].length) delete this.byNote[file.path];
    this.stats.last = { path: file.path, lines: [a, b], picked: picked.length, unmarked: allMarked };
    sel.removeAllRanges();
    await this.resolve(file);
    this.paint(view);
    await this.save();
    this.onChange(file.path);
    return picked;
  }

  /** Highlight the rendered blocks that fall in a marked chunk. */
  paint(view: MarkdownView): number {
    const spans = view.file ? this.spans.get(view.file.path) || [] : [];
    let n = 0;
    for (const s of this.sections(view)) {
      const on = spans.some((r) => s.lineStart <= r.to && s.lineEnd >= r.from);
      s.el.toggleClass("domvec-marked", on);
      if (on) n++;
    }
    return n;
  }

  /** One rendered block, as Obsidian post-processes it (re-renders keep the mark). */
  paintBlock(el: HTMLElement, path: string, info: { lineStart: number; lineEnd: number } | null): void {
    const spans = this.spans.get(path);
    if (!spans || !info) return;
    el.toggleClass("domvec-marked", spans.some((r) => info.lineStart <= r.to && info.lineEnd >= r.from));
  }

  async clear(path: string): Promise<void> {
    delete this.byNote[path];
    this.spans.delete(path);
    const plane: any[] = (window as any).__domvecPlane?.leaves?.() || [];
    for (const leaf of [...this.app.workspace.getLeavesOfType("markdown"), ...plane]) {
      const v = leaf.view as MarkdownView;
      if (v.file?.path === path) this.paint(v);
    }
    await this.save();
    this.onChange(path);
  }
}
