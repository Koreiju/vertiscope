/**
 * Edits re-run (PLUGIN_GOAL 194: "we do away with things like calling in the
 * terminal because we're measuring the changes instantly"). A pause after an
 * edit inside a python cell runs THAT cell by the run button's own path, and
 * the dataflow (G-380) re-runs its readers -- no Run press, no terminal.
 *
 * In trie terms: the note is a vault:// page; each run writes its output
 * block into it, as a pressed Run does. The cockpit is skipped: it applies
 * its cell's values as they are typed (G-418).
 */
import type { App, TFile } from "obsidian";
import { cellSource, findFences } from "./fences";
import type { RunRequest } from "./runbutton";

const PY = /^(python|py|python3)$/;

export class AutoRun {
  stats = { scheduled: 0, ran: 0, skipped: 0, last: "" };
  /** Planted: edits never run -- the reader must press Run. */
  plantOff = false;
  delayMs = 900;
  private timers = new Map<string, number>();
  private busy = new Set<string>();

  constructor(private app: App, private run: (req: RunRequest) => Promise<any>, private skip: (path: string) => boolean) {}

  onEdit(editor: any, file: TFile | null): void {
    if (!file || !editor || this.plantOff || this.skip(file.path)) return;
    const at = editor.getCursor().line;
    const fence = findFences(editor.getValue()).find((f) => f.openLine < at && at < f.closeLine && PY.test(f.lang));
    if (!fence) return;
    const key = file.path + "#" + fence.openLine;
    window.clearTimeout(this.timers.get(key));
    this.stats.scheduled++;
    this.timers.set(key, window.setTimeout(() => void this.fire(editor, file, fence.openLine, key), this.delayMs));
  }

  private async fire(editor: any, file: TFile, openLine: number, key: string): Promise<void> {
    this.timers.delete(key);
    if (this.busy.has(key)) { this.stats.skipped++; return; }
    // Found again as the note is NOW: typing may have moved it.
    const f = findFences(editor.getValue()).find((x) => x.openLine === openLine && PY.test(x.lang));
    if (!f) { this.stats.skipped++; return; }
    this.busy.add(key);
    try {
      await this.run({ lang: f.lang, code: cellSource(f.body), line: f.openLine, path: file.path, refs: f.refs });
      this.stats.ran++; this.stats.last = key;
    } finally { this.busy.delete(key); }
  }
}

/**
 * Edges BETWEEN notes (2026-11-25: "I also doubt we have any completeness on
 * our dependency graph"). A compiled link is a cell `b = Vault.read("/b.md")`
 * (G-420), which the per-note dataflow (G-380) can only list as an outside
 * ref. This keeps the reverse index -- each note to the notes whose cells read
 * it -- and when a note changes, re-runs exactly those reading cells, so an
 * edit in b reaches a. Planted `plantNoCross`: nothing re-runs across notes.
 *
 * In trie terms: an edge is vault://a#cell n -> vault://b, read from a's text;
 * a change to page b re-writes each reading cell's output block in page a.
 */
const READ = /Vault\.read\(\s*["']([^"'\n]+)["']/g;
const SKIP = /^(build|\.trash|domvec\/chunks|\.obsidian)\//;

export class CrossRun {
  stats = { indexed: 0, edges: 0, reran: 0, last: "" };
  plantOff = false;
  delayMs = 900;
  /** target path -> reader paths. */
  readers = new Map<string, Set<string>>();
  private reads = new Map<string, Set<string>>();
  private timers = new Map<string, number>();
  private running = new Set<string>();

  constructor(private app: App, private run: (req: RunRequest) => Promise<any>) {}

  static targetOf(reader: string, ref: string): string {
    const p = ref.startsWith("/") ? ref.slice(1) : (reader.includes("/") ? reader.replace(/\/[^/]*$/, "/") : "") + ref;
    return p.endsWith(".md") ? p : p + ".md";
  }

  private reindex(path: string, text: string): void {
    for (const t of this.reads.get(path) || []) this.readers.get(t)?.delete(path);
    const ts = new Set<string>();
    for (const m of text.matchAll(READ)) ts.add(CrossRun.targetOf(path, m[1]));
    if (ts.size) this.reads.set(path, ts); else this.reads.delete(path);
    for (const t of ts) { if (!this.readers.has(t)) this.readers.set(t, new Set()); this.readers.get(t)!.add(path); }
    this.stats.edges = [...this.readers.values()].reduce((n, s) => n + s.size, 0);
  }

  async build(): Promise<void> {
    for (const f of this.app.vault.getMarkdownFiles()) {
      if (SKIP.test(f.path)) continue;
      const t = await this.app.vault.cachedRead(f);
      if (t.includes("Vault.read(")) this.reindex(f.path, t);
      this.stats.indexed++;
    }
  }

  /** A note was written: re-index it, then re-run the cells that read it. */
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
        await this.run({ lang: c.lang, code: cellSource(c.body), line: c.openLine, path: reader, refs: c.refs });
        this.stats.reran++; this.stats.last = reader + "#" + c.openLine + " <- " + target;
      }
    } finally { window.setTimeout(() => this.running.delete(reader), 1500); }
  }
}


/**
 * G-413 (187, 166, 167 c, T-10; spec 13h): a base tool's VIEW changing re-runs
 * its READERS. A cell reads a tool when its code reads the tool's state --
 * `WebBrowser.url`, `.title`, `.chunks(`, `.controls(` for the browser cell.
 * When that view changes (the browser navigates: `domvec-tool-view` on the
 * window), every such cell is re-run, debounced, so what it printed follows
 * what the tool shows. Planted `plantOff`: the readers keep their old output.
 *
 * In trie terms: the tool's view is a page address; a reader cell's output is
 * re-derived from the new address through the same run path as a press.
 */
export const TOOL_READS: Record<string, RegExp> = {
  browser: /\bWebBrowser\s*\.\s*(url|title|chunks|controls)\b/,
  // G-412: the chat's turns. A turn written re-runs the cells reading them.
  chat: /\bChat\s*\.\s*messages\b/,
  // G-413: the terminal pane's last command and output.
  terminal: /\bTerminal\s*\.\s*last\b/,
};

export class ToolRun {
  stats = { indexed: 0, readers: 0, views: 0, reran: 0, last: "" };
  plantOff = false;
  delayMs = 900;
  /** tool -> reader note paths. */
  readers = new Map<string, Set<string>>();
  private timer = new Map<string, number>();
  private running = new Set<string>();
  /** `isOpen`: a reader re-runs only while it is drawn -- in a tab or on the
   *  plane. A note nobody is looking at (a design doc quoting `WebBrowser.url`
   *  as an example, seen 2026-11-25) is never executed by a navigation. */
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
      if (t.includes("WebBrowser") || t.includes("Chat.") || t.includes("Terminal.")) this.reindex(f.path, t);
      this.stats.indexed++;
    }
  }

  async onModify(file: TFile): Promise<void> {
    if (SKIP.test(file.path) || file.extension !== "md") return;
    this.reindex(file.path, await this.app.vault.cachedRead(file));
  }

  /** The tool's view changed: its readers re-run, once per settled change. */
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
      if (tool === "chat" && detail && reader !== detail) continue;   // a chat's turn re-runs its own note's readers
      this.running.add(reader);
      try {
        for (const c of findFences(await this.app.vault.read(f)).filter((c) => PY.test(c.lang) && re.test(c.body))) {
          await this.run({ lang: c.lang, code: cellSource(c.body), line: c.openLine, path: reader, refs: c.refs });
          this.stats.reran++; this.stats.last = reader + "#" + c.openLine + " <- " + tool + " " + detail;
        }
      } finally { this.running.delete(reader); }
    }
  }
}
