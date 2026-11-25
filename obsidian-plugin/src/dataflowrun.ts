/**
 * Marimo-style reactive runs (G-380; PLUGIN_GOAL 167 f, "marimo style").
 *
 * After a python cell runs cleanly, the cells that read the names it defines
 * are stale. The sidecar reads that from the note's own text (`POST
 * /dataflow`, `domvec/dataflow.py` `rerun_plan`: defs and refs read
 * statically, one definition per name, cycles refused) and this re-runs them
 * in run order, by the run button's own path -- each lit, its output written
 * under it. A re-run does not start another: the plan already holds every
 * transitive reader. A cell in a problem (a name defined twice, a cycle) runs,
 * but nothing is re-run around it; the problem is said instead.
 *
 * In trie terms: the note is a `vault://` page; each re-run writes its output
 * block into that page, and the store follows the note as for any run.
 */
import { TFile, type App } from "obsidian";
import { cellSource, findFences } from "./fences";
import type { RunRequest } from "./runbutton";

export interface DataflowHost {
  app: App;
  settings: { sidecar: string };
  onRunFence(req: RunRequest): Promise<any>;
}

export class DataflowRun {
  stats = { plans: 0, reran: 0, refused: 0, failed: 0, last: null as any };
  /** Planted: a run never re-runs its readers -- they stay stale. */
  plantNoRerun = false;
  private active = new Set<string>();

  /** `noteText`: the note's text as the reader sees it (the editor's when open). */
  constructor(private host: DataflowHost, private noteText: (path: string) => Promise<string>,
              /** Draw (or clear) the problems in the note's open editors (dfproblems.ts). */
              private mark: (path: string, marks: { line: number; message: string }[]) => void = () => undefined) {}

  /** Called after a cell's run; the line for its notice, or "". */
  async after(req: RunRequest, reply: any): Promise<string> {
    const note = req.path;
    if (!note || this.plantNoRerun || this.active.has(note)) return "";
    if (!reply || !reply.ok || !/^(python|py|python3)$/.test(String(req.lang || "").toLowerCase())) return "";
    const markdown = await this.noteText(note);
    let plan: any;
    try {
      const base = this.host.settings.sidecar.replace(/\/+$/, "");
      const r = await fetch(base + "/dataflow", { method: "POST", headers: { "Content-Type": "application/json", "X-Domvec-Client": "obsidian-plugin" },
                                                  body: JSON.stringify({ markdown, line: req.line }) });
      plan = await r.json();
    } catch (e) { return ""; }
    this.stats.plans++;
    if (plan.problems && plan.problems.length) {
      this.mark(note, plan.problems.flatMap((p: any) => (p.open_lines || []).map((line: number) => ({ line, message: p.message || p.kind }))));
      this.stats.refused++;
      this.stats.last = { note, problems: plan.problems };
      return "not re-run: " + plan.problems.map((p: any) => p.message || p.kind).join("; ");
    }
    this.mark(note, []);
    const todo: any[] = plan.rerun || [];
    if (!todo.length) { this.stats.last = { note, line: req.line, rerun: [] }; return ""; }
    const ran: number[] = [];
    this.active.add(note);
    try {
      for (const t of todo) {
        // Found again by its source in the note as it is NOW: a re-run before
        // it may have written an output block above it and moved its line.
        const code = cellSource(t.source);
        const now = findFences(await this.noteText(note)).filter((x) => x.lang.startsWith("py") && cellSource(x.body) === code);
        const f = now.find((x) => x.openLine === t.open_line) || (now.length === 1 ? now[0] : null);
        if (!f) { this.stats.failed++; break; }
        const r = await this.host.onRunFence({ path: note, lang: "python", code, line: f.openLine, refs: f.refs });
        if (!r || !r.ok) { this.stats.failed++; break; }
        ran.push(t.open_line);
        this.stats.reran++;
      }
    } finally { this.active.delete(note); }
    this.stats.last = { note, line: req.line, rerun: todo.map((t) => t.open_line), ran, ms: plan.ms };
    return `re-ran ${ran.length} of ${todo.length} reading ${(plan.defs || []).join(", ")}`;
  }
}

/** The note's text: the editor's when it is open, else the file's. */
export async function noteTextOf(app: App, path: string, views: () => any[]): Promise<string> {
  const v = views().find((x) => x?.file?.path === path && x.editor);
  if (v) return v.editor.getValue();
  const f = app.vault.getAbstractFileByPath(path);
  return f instanceof TFile ? app.vault.cachedRead(f) : "";
}
