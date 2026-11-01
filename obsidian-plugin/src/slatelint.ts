/**
 * The markdown cell's trees, checked as the Python module they are
 * (PLUGIN_GOAL 62, 63': "treat our specialized code-node markdown
 * integrations more like as a standard python module ... so things like
 * triple-repeating "results" would likely throw a syntax error").
 *
 * The errors are the sidecar's (`domvec/slate_module.py`, one owner of the
 * semantics): a name bound twice in a namespace, a name defined as itself, a
 * circular definition, a reference to nothing. Drawn where they are, as an
 * editor draws a linter's: a wavy underline, the error as its title. Asked
 * half a second after the text settles, and only of a note that holds a tree.
 */
import { StateEffect, StateField, type Extension, RangeSetBuilder } from "@codemirror/state";
import { Decoration, type DecorationSet, EditorView, ViewPlugin, type ViewUpdate } from "@codemirror/view";
import { editorInfoField } from "obsidian";
import type { Sidecar } from "./sidecar";

export interface SlateDiagnostic { line: number; from: number; to: number; kind: string; message: string }

const setDiags = StateEffect.define<SlateDiagnostic[]>();

export const slateLintStats = { asked: 0, drawn: 0, last: [] as SlateDiagnostic[], path: "" };

const diagField = StateField.define<DecorationSet>({
  create: () => Decoration.none,
  update(deco, tr) {
    deco = deco.map(tr.changes);
    for (const e of tr.effects) {
      if (!e.is(setDiags)) continue;
      const b = new RangeSetBuilder<Decoration>();
      const doc = tr.state.doc;
      const ds = e.value.slice().sort((a, z) => a.line - z.line || a.from - z.from);
      for (const d of ds) {
        if (d.line + 1 > doc.lines) continue;
        const ln = doc.line(d.line + 1);
        const a = Math.min(ln.from + d.from, ln.to), z = Math.max(a + 1, Math.min(ln.from + d.to, ln.to));
        if (z <= a) continue;
        b.add(a, z, Decoration.mark({ class: "domvec-slate-error", attributes: { title: d.kind + ": " + d.message, "data-kind": d.kind } }));
      }
      deco = b.finish();
      slateLintStats.drawn = ds.length;
    }
    return deco;
  },
  provide: (f) => EditorView.decorations.from(f),
});

/** Has a tree worth asking about: a slate note, or an unindented line followed by a tab-indented one. */
function hasTrees(text: string): boolean {
  return /^---\r?\n(?:.*\r?\n)*?domvec:\s*slate\s*\r?\n/.test(text) || /^\S.*\n\t\S/m.test(text);
}

export function slateLint(sidecar: () => Sidecar | null): Extension {
  const plugin = ViewPlugin.fromClass(class {
    private timer = 0;
    private seq = 0;
    constructor(private view: EditorView) { this.schedule(0); }
    update(u: ViewUpdate) { if (u.docChanged) this.schedule(500); }
    destroy() { window.clearTimeout(this.timer); }
    private schedule(ms: number) {
      window.clearTimeout(this.timer);
      this.timer = window.setTimeout(() => void this.run(), ms);
    }
    private async run() {
      const sc = sidecar();
      if (!sc || (window as any).__domvecPlantNoSlateLint) return;
      const text = this.view.state.doc.toString();
      if (!hasTrees(text)) {
        if (slateLintStats.drawn) this.view.dispatch({ effects: setDiags.of([]) });
        return;
      }
      const seq = ++this.seq;
      slateLintStats.asked++;
      const got = await sc.slateCheck(text);
      if (seq !== this.seq || !got || !Array.isArray(got.diagnostics)) return;
      if (this.view.state.doc.toString() !== text) return;             // stale: the next run answers
      slateLintStats.last = got.diagnostics;
      try { slateLintStats.path = this.view.state.field(editorInfoField)?.file?.path || ""; } catch { /* not an Obsidian editor */ }
      this.view.dispatch({ effects: setDiags.of(got.diagnostics) });
    }
  });
  return [diagField, plugin];
}
