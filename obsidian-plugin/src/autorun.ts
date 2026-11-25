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
