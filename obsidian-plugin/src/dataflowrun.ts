/**
 * Marimo-style intra-note AND cross-notebook reactive DAG compilation (`G-380`,
 * `G-451`; PLUGIN_GOAL 167 f, 201 d).
 *
 * In trie terms: each notebook is a `vault://<vault>/<note>` page whose fenced
 * cells (`#cell <n>`) define and reference Python globals. `POST /dataflow`
 * builds the topological DAG across all active notebooks so:
 * 1. Before cell `C` runs (`upstreamFor`), any upstream cells in OTHER notebooks
 *    whose definitions `C` references are evaluated first and injected into `C`'s
 *    kernel (`sidecar.py` `_post_kernel`).
 * 2. After cell `C` runs (`after`), every downstream cell (in `C`'s note and in
 *    other open/graph notebooks) that references `C`'s definitions re-runs in
 *    topological order.
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
  stats = { plans: 0, reran: 0, cross_reran: 0, upstream_compiled: 0, refused: 0, failed: 0, last: null as any };
  /** Planted (`G-380`): a run never re-runs its readers -- they stay stale. */
  plantNoRerun = false;
  /** Planted (`G-451`): cross-notebook upstream & downstream DAG disabled. */
  plantNoCrossDag = false;
  private active = new Set<string>();
  private inCrossBatch = false;

  constructor(
    private host: DataflowHost,
    private noteText: (path: string) => Promise<string>,
    private mark: (path: string, marks: { line: number; message: string }[]) => void = () => undefined,
    private allNotes?: (focusNote: string) => Promise<Record<string, string>>,
  ) {}

  /** Compute upstream cells across notebooks that must compile before `(note, line)` runs (`G-451`). */
  async upstreamFor(note: string, line: number): Promise<any[]> {
    if (!note || this.plantNoCrossDag || !this.allNotes) return [];
    try {
      const notes = await this.allNotes(note);
      if (Object.keys(notes).length <= 1) return [];
      const base = this.host.settings.sidecar.replace(/\/+$/, "");
      const r = await fetch(base + "/dataflow", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Domvec-Client": "obsidian-plugin" },
        body: JSON.stringify({ notes, note, line }),
      });
      if (!r.ok) return [];
      const plan = await r.json();
      const up = (plan.upstream || []).filter((u: any) => u.note !== note);
      if (up.length) this.stats.upstream_compiled += up.length;
      return plan.upstream || [];
    } catch {
      return [];
    }
  }

  /** Called after a cell's run; returns a short status note or `""`. */
  async after(req: RunRequest, reply: any): Promise<string> {
    const note = req.path;
    if (!note || this.plantNoRerun || this.active.has(note) || this.inCrossBatch) return "";
    if (!reply || !reply.ok || !/^(python|py|python3)$/i.test(String(req.lang || "").toLowerCase())) return "";
    const markdown = await this.noteText(note);
    const base = this.host.settings.sidecar.replace(/\/+$/, "");
    let plan: any;
    try {
      const r = await fetch(base + "/dataflow", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Domvec-Client": "obsidian-plugin" },
        body: JSON.stringify({ markdown, line: req.line }),
      });
      plan = await r.json();
    } catch {
      return "";
    }
    this.stats.plans++;
    if (plan.problems && plan.problems.length) {
      this.mark(note, plan.problems.flatMap((p: any) => (p.open_lines || []).map((line: number) => ({ line, message: p.message || p.kind }))));
      this.stats.refused++;
      this.stats.last = { note, problems: plan.problems };
      return "not re-run: " + plan.problems.map((p: any) => p.message || p.kind).join("; ");
    }
    this.mark(note, []);

    // Collect cross-notebook downstream cells if `allNotes` is wired (`G-451`).
    let crossTodo: any[] = [];
    if (!this.plantNoCrossDag && this.allNotes) {
      try {
        const notes = await this.allNotes(note);
        notes[note] = markdown;
        if (Object.keys(notes).length > 1) {
          const cr = await fetch(base + "/dataflow", {
            method: "POST",
            headers: { "Content-Type": "application/json", "X-Domvec-Client": "obsidian-plugin" },
            body: JSON.stringify({ notes, note, line: req.line }),
          });
          if (cr.ok) {
            const cPlan = await cr.json();
            crossTodo = (cPlan.downstream || []).filter((d: any) => d.note && d.note !== note);
          }
        }
      } catch { /* ignore */ }
    }

    const todo: any[] = plan.rerun || [];
    if (!todo.length && !crossTodo.length) {
      this.stats.last = { note, line: req.line, rerun: [], cross: [] };
      return "";
    }
    const ran: number[] = [];
    const crossRan: string[] = [];
    this.active.add(note);
    this.inCrossBatch = true;
    try {
      for (const t of todo) {
        const code = cellSource(t.source);
        const now = findFences(await this.noteText(note)).filter((x) => x.lang.toLowerCase().startsWith("py") && cellSource(x.body) === code);
        const f = now.find((x) => x.openLine === t.open_line) || (now.length === 1 ? now[0] : null);
        if (!f) { this.stats.failed++; break; }
        const r = await this.host.onRunFence({ path: note, lang: "python", code, line: f.openLine, refs: f.refs, quiet: true } as any);
        if (!r || !r.ok) { this.stats.failed++; break; }
        ran.push(t.open_line);
        this.stats.reran++;
      }
      for (const ct of crossTodo) {
        const tNote = String(ct.note);
        const code = cellSource(ct.source);
        const now = findFences(await this.noteText(tNote)).filter((x) => x.lang.toLowerCase().startsWith("py") && cellSource(x.body) === code);
        const f = now.find((x) => x.openLine === ct.open_line) || (now.length === 1 ? now[0] : null);
        if (!f) continue;
        const r = await this.host.onRunFence({ path: tNote, lang: "python", code, line: f.openLine, refs: f.refs, quiet: true } as any);
        if (r && r.ok) {
          crossRan.push(`${tNote}#${f.openLine}`);
          this.stats.reran++;
          this.stats.cross_reran++;
        }
      }
    } finally {
      this.active.delete(note);
      this.inCrossBatch = false;
    }
    this.stats.last = { note, line: req.line, rerun: todo.map((t) => t.open_line), ran, cross: crossRan, ms: plan.ms };
    return `re-ran ${ran.length + crossRan.length} reading ${(plan.defs || []).join(", ")}`;
  }
}

export async function noteTextOf(app: App, path: string, views: () => any[]): Promise<string> {
  const v = views().find((x) => x?.file?.path === path && x.editor);
  if (v) return v.editor.getValue();
  const f = app.vault.getAbstractFileByPath(path);
  return f instanceof TFile ? app.vault.cachedRead(f) : "";
}
