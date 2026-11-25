/**
 * The editor drawing the dataflow's problems (G-380's last open part: "Not
 * yet: the editor drawing the problems"). A run whose note has a name defined
 * twice or a cycle is refused re-running (dataflowrun.ts); the cells in that
 * problem are now MARKED where they are -- a red rule on each fence's opening
 * line and the problem's message after it -- until a later run of the note
 * comes back clean. Planted `__domvecPlantNoProblemMarks`: nothing is drawn.
 *
 * In trie terms: nothing is written to the page; the marks are a view over
 * vault://note#cell n, keyed by line and mapped through edits.
 */
import { StateEffect, StateField, type Extension } from "@codemirror/state";
import { Decoration, EditorView, WidgetType, type DecorationSet } from "@codemirror/view";

export interface ProblemMark { line: number; message: string }
export const setProblems = StateEffect.define<ProblemMark[]>();

class Msg extends WidgetType {
  constructor(private text: string) { super(); }
  eq(o: Msg) { return o.text === this.text; }
  toDOM() { const s = document.createElement("span"); s.className = "domvec-df-problem-msg"; s.textContent = "  ⚠ " + this.text; return s; }
}

export const problemField = StateField.define<DecorationSet>({
  create: () => Decoration.none,
  update(deco, tr) {
    deco = deco.map(tr.changes);
    for (const e of tr.effects) {
      if (!e.is(setProblems)) continue;
      const doc = tr.state.doc, ranges: any[] = [];
      for (const m of [...e.value].sort((a, b) => a.line - b.line)) {
        if (m.line < 0 || m.line >= doc.lines) continue;
        const l = doc.line(m.line + 1);
        ranges.push(Decoration.line({ class: "domvec-df-problem", attributes: { title: m.message } }).range(l.from));
        ranges.push(Decoration.widget({ widget: new Msg(m.message), side: 1 }).range(l.to));
      }
      deco = Decoration.set(ranges, true);
    }
    return deco;
  },
  provide: (f) => EditorView.decorations.from(f),
});

export const problemExtension: Extension = [problemField];

/** Mark (or, with [], clear) the problems in every open editor of `path`. */
export function markProblems(views: any[], path: string, marks: ProblemMark[]): number {
  if ((window as any).__domvecPlantNoProblemMarks) marks = [];
  let n = 0;
  for (const v of views) {
    if (v?.file?.path !== path) continue;
    const cm: EditorView | undefined = v.editor?.cm;
    if (!cm) continue;
    cm.dispatch({ effects: setProblems.of(marks) });
    n++;
  }
  return n;
}
