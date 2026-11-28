/**
 * Fence-exit reactive evaluation & cross-notebook variable reactivity (`G-419`
 * amended by `G-449`, `G-426`, `G-451`, `G-453`; PLUGIN_GOAL 194, 201 b/d/f).
 *
 * In trie terms:
 * - Each note is a `vault://<vault>/<note>` page whose fenced ` ```python ` and
 *   ` ```tool ` blocks are addressed cells (`#cell <k>`).
 * - Editing inside a ` ``` ` fence marks that cell dirty without running broken
 *   mid-typing code; only once the cursor EXITS `[openLine, closeLine]` (or the
 *   editor blurs) does the cell evaluate and write its output block into the note.
 * - Cross-notebook `defs -> refs` (`extractNotePyDefsRefs`) and `Vault.read`
 *   edges re-run dependent open notebooks in topological order when upstream
 *   definitions change.
 */
import type { App, TFile } from "obsidian";
import { extractNotePyDefsRefs } from "./fencecode";
import { cellSource, findFences, type Fence } from "./fences";
import type { RunRequest } from "./runbutton";

const PY = /^(python|py|python3)$/i;
const TOOL = /^tool$/i;

interface DirtyCell {
  file: TFile;
  openLine: number;
  lang: string;
  code: string;
}

export class AutoRun {
  stats = { scheduled: 0, ran: 0, skipped: 0, mid_fence_held: 0, tool_exits: 0, last: "" };
  /** Planted (`G-419` / `G-449`): edits never run automatically. */
  plantOff = false;
  /** Planted (`G-449`): old behaviour -- fires on timer WHILE cursor is still inside the fence! */
  plantRunInsideFence = false;
  delayMs = 900;
  onToolFenceExit: ((file: TFile, fence: Fence) => Promise<any>) | null = null;
  private timers = new Map<string, number>();
  private busy = new Set<string>();
  private dirty = new Map<string, DirtyCell>();

  constructor(private app: App, private run: (req: RunRequest) => Promise<any>, private skip: (path: string) => boolean) {}

  onEdit(editor: any, file: TFile | null): void {
    if (!file || !editor || this.plantOff || this.skip(file.path)) return;
    const at = editor.getCursor().line;
    const val = editor.getValue();
    const fence = findFences(val).find((f) => f.openLine <= at && at <= f.closeLine && (PY.test(f.lang) || TOOL.test(f.lang)));
    if (!fence) {
      // Edit occurred outside fences: if this file had any dirty fence, flush it now.
      void this.flushOutside(editor, file);
      return;
    }
    const key = file.path + "#" + fence.openLine;
    this.dirty.set(key, {
      file,
      openLine: fence.openLine,
      lang: fence.lang,
      code: cellSource(fence.body),
    });
    this.stats.scheduled++;
    if (this.plantRunInsideFence && PY.test(fence.lang)) {
      window.clearTimeout(this.timers.get(key));
      this.timers.set(key, window.setTimeout(() => void this.fire(editor, file, fence.openLine, key), this.delayMs));
      return;
    }
    this.stats.mid_fence_held++;
  }

  /** Called when the cursor moves or editor blurs: runs any dirty fence the cursor has left (`G-449`, `G-453`). */
  async flushOutside(editor: any, file: TFile | null, blurred = false): Promise<void> {
    if (this.plantOff || !this.dirty.size) return;
    const curLine = (!blurred && editor && typeof editor.getCursor === "function") ? editor.getCursor().line : -1;
    const curText = editor && typeof editor.getValue === "function" ? editor.getValue() : "";
    const curFences = curText ? findFences(curText) : [];

    for (const [key, item] of [...this.dirty.entries()]) {
      if (file && item.file.path !== file.path) continue;
      if (this.skip(item.file.path)) { this.dirty.delete(key); continue; }
      const liveFence = curFences.find((x) => x.openLine === item.openLine && (PY.test(x.lang) || TOOL.test(x.lang)))
        || curFences.find((x) => cellSource(x.body) === item.code && x.lang.toLowerCase() === item.lang.toLowerCase());
      if (!blurred && liveFence && curLine >= liveFence.openLine && curLine <= liveFence.closeLine) {
        // Cursor is still inside this fence window: keep waiting!
        continue;
      }
      if (this.busy.has(key)) {
        // Previous run still finishing: keep dirty and retry shortly so the edit is never lost.
        window.setTimeout(() => void this.flushOutside(editor, file, blurred), 200);
        continue;
      }
      this.dirty.delete(key);
      if (!liveFence) { this.stats.skipped++; continue; }
      if (TOOL.test(liveFence.lang)) {
        if (this.onToolFenceExit) {
          this.stats.tool_exits++;
          this.stats.last = key;
          await this.onToolFenceExit(item.file, liveFence);
        }
        continue;
      }
      await this.fire(editor, item.file, liveFence.openLine, key);
    }
  }

  private async fire(editor: any, file: TFile, openLine: number, key: string): Promise<void> {
    this.timers.delete(key);
    if (this.busy.has(key)) { this.stats.skipped++; return; }
    const text = editor && typeof editor.getValue === "function" ? editor.getValue() : await this.app.vault.cachedRead(file);
    const f = findFences(text).find((x) => x.openLine === openLine && PY.test(x.lang));
    if (!f || !cellSource(f.body).trim()) { this.stats.skipped++; return; }
    this.busy.add(key);
    try {
      await this.run({ lang: f.lang, code: cellSource(f.body), line: f.openLine, path: file.path, refs: f.refs, quiet: true } as any);
      this.stats.ran++; this.stats.last = key;
    } finally { this.busy.delete(key); }
  }
}

const READ = /Vault\.read\(\s*["']([^"'\n]+)["']/g;
const SKIP = /^(build|\.trash|domvec\/chunks|\.obsidian|docs)\//;

export class CrossRun {
  stats = { indexed: 0, edges: 0, var_edges: 0, reran: 0, last: "" };
  plantOff = false;
  delayMs = 900;
  /** target path -> reader paths (`Vault.read`). */
  readers = new Map<string, Set<string>>();
  private reads = new Map<string, Set<string>>();
  /** note path -> `{defs, refs}` for direct cross-notebook variable DAG (`G-451`). */
  pyGraph = new Map<string, { defs: Set<string>; refs: Set<string> }>();
  private timers = new Map<string, number>();
  private running = new Set<string>();

  constructor(
    private app: App,
    private run: (req: RunRequest) => Promise<any>,
    private isActiveNote: (path: string) => boolean = (p) => p.startsWith("domvec/graph/"),
  ) {}

  static targetOf(reader: string, ref: string): string {
    const p = ref.startsWith("/") ? ref.slice(1) : (reader.includes("/") ? reader.replace(/\/[^/]*$/, "/") : "") + ref;
    return p.endsWith(".md") ? p : p + ".md";
  }

  reindex(path: string, text: string): void {
    for (const t of this.reads.get(path) || []) this.readers.get(t)?.delete(path);
    const ts = new Set<string>();
    for (const m of text.matchAll(READ)) ts.add(CrossRun.targetOf(path, m[1]));
    if (ts.size) this.reads.set(path, ts); else this.reads.delete(path);
    for (const t of ts) { if (!this.readers.has(t)) this.readers.set(t, new Set()); this.readers.get(t)!.add(path); }
    this.stats.edges = [...this.readers.values()].reduce((n, s) => n + s.size, 0);

    if (text.includes("```")) {
      const py = extractNotePyDefsRefs(text);
      if (py.defs.size || py.refs.size) this.pyGraph.set(path, { defs: py.defs, refs: py.refs });
      else this.pyGraph.delete(path);
    } else {
      this.pyGraph.delete(path);
    }
    let varEdges = 0;
    for (const [a, pa] of this.pyGraph.entries()) {
      for (const [b, pb] of this.pyGraph.entries()) {
        if (a !== b && [...pa.defs].some((d) => pb.refs.has(d))) varEdges++;
      }
    }
    this.stats.var_edges = varEdges;
  }

  /** External variable definitions from other indexed notebooks (`G-450`, `G-451`). */
  externalDefsFor(notePath: string): { name: string; note: string }[] {
    const out: { name: string; note: string }[] = [];
    const seen = new Set<string>();
    const localDefs = this.pyGraph.get(notePath)?.defs || new Set<string>();
    for (const [p, g] of this.pyGraph.entries()) {
      if (p === notePath || !this.isActiveNote(p)) continue;
      for (const d of g.defs) {
        if (!localDefs.has(d) && !seen.has(d)) {
          seen.add(d);
          out.push({ name: d, note: p });
        }
      }
    }
    return out;
  }

  async build(): Promise<void> {
    for (const f of this.app.vault.getMarkdownFiles()) {
      if (SKIP.test(f.path)) continue;
      const t = await this.app.vault.cachedRead(f);
      if (t.includes("Vault.read(") || (this.isActiveNote(f.path) && t.includes("```"))) {
        this.reindex(f.path, t);
      }
      this.stats.indexed++;
    }
  }

  /** A note was written: re-index it, then re-run cells in notes that `Vault.read` it. */
  async onModify(file: TFile): Promise<void> {
    if (SKIP.test(file.path) || file.extension !== "md") return;
    this.reindex(file.path, await this.app.vault.cachedRead(file));
    if (this.plantOff || this.running.has(file.path)) return;
    for (const reader of this.readers.get(file.path) || []) {
      if (reader === file.path) continue;
      window.clearTimeout(this.timers.get(reader));
      this.timers.set(reader, window.setTimeout(() => void this.rerun(reader, file.path), this.delayMs));
    }
  }

  private async rerun(reader: string, target: string): Promise<void> {
    this.timers.delete(reader);
    const f = this.app.vault.getAbstractFileByPath(reader) as TFile | null;
    if (!f || this.running.has(reader)) return;
    const cells = findFences(await this.app.vault.read(f)).filter((c) => PY.test(c.lang)
      && [...c.body.matchAll(READ)].some((m) => CrossRun.targetOf(reader, m[1]) === target));
    this.running.add(reader);
    try {
      for (const c of cells) {
        this.stats.reran++;
        this.stats.last = reader + "#" + c.openLine + " <- " + target;
        await this.run({ lang: c.lang, code: cellSource(c.body), line: c.openLine, path: reader, refs: c.refs, quiet: true } as any);
      }
    } finally { window.setTimeout(() => this.running.delete(reader), 1500); }
  }
}

export const TOOL_READS: Record<string, RegExp> = {
  browser: /\bWebBrowser\s*\.\s*(url|title|chunks|controls)\b/,
  chat: /\bChat\s*\.\s*messages\b/,
  terminal: /\bTerminal\s*\.\s*last\b/,
  search: /\bSearch\s*\.\s*last\b/,
};

export class ToolRun {
  stats = { indexed: 0, readers: 0, views: 0, reran: 0, last: "" };
  plantOff = false;
  delayMs = 900;
  readers = new Map<string, Set<string>>();
  private timer = new Map<string, number>();
  private running = new Set<string>();
  constructor(private app: App, private run: (req: RunRequest) => Promise<any>, private isOpen: (path: string) => boolean = () => true) {}

  reindex(path: string, text: string): void {
    if (/^docs\//.test(path)) return;
    for (const [tool, re] of Object.entries(TOOL_READS)) {
      if (!this.readers.has(tool)) this.readers.set(tool, new Set());
      const reads = findFences(text).some((c) => PY.test(c.lang) && re.test(c.body));
      if (reads) this.readers.get(tool)!.add(path); else this.readers.get(tool)!.delete(path);
    }
    this.stats.readers = [...this.readers.values()].reduce((n, s) => n + s.size, 0);
  }

  async build(): Promise<void> {
    for (const f of this.app.vault.getMarkdownFiles()) {
      if (SKIP.test(f.path)) continue;
      const t = await this.app.vault.cachedRead(f);
      if (t.includes("WebBrowser") || t.includes("Chat.") || t.includes("Terminal.") || t.includes("Search.")) this.reindex(f.path, t);
      this.stats.indexed++;
    }
  }

  async onModify(file: TFile): Promise<void> {
    if (SKIP.test(file.path) || file.extension !== "md") return;
    this.reindex(file.path, await this.app.vault.cachedRead(file));
  }

  onView(tool: string, detail = ""): void {
    this.stats.views++;
    if (this.plantOff) return;
    window.clearTimeout(this.timer.get(tool));
    this.timer.set(tool, window.setTimeout(() => void this.rerunAll(tool, detail), this.delayMs));
  }

  private async rerunAll(tool: string, detail: string): Promise<void> {
    const re = TOOL_READS[tool];
    for (const reader of [...(this.readers.get(tool) || [])]) {
      const f = this.app.vault.getAbstractFileByPath(reader) as TFile | null;
      if (!f || this.running.has(reader) || !this.isOpen(reader)) continue;
      if (tool === "chat" && detail && reader !== detail) continue;
      this.running.add(reader);
      try {
        for (const c of findFences(await this.app.vault.read(f)).filter((c) => PY.test(c.lang) && re.test(c.body))) {
          await this.run({ lang: c.lang, code: cellSource(c.body), line: c.openLine, path: reader, refs: c.refs, quiet: true } as any);
          this.stats.reran++; this.stats.last = reader + "#" + c.openLine + " <- " + tool + " " + detail;
        }
      } finally { this.running.delete(reader); }
    }
  }
}
