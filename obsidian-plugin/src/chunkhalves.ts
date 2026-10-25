/**
 * A chunk note's two halves, one shown at a time (`P-W2`, `P-W8`; `D-3`).
 *
 * The verbatim: the obsidian panels "are retrofitted to show their *base and
 * original* markdown editors with their interactive html cards". On a chunk
 * note (`domvec: chunk` in its frontmatter) the card is the `domvec` fence and
 * the markdown editor is the note's OWN body -- the native, editable editor,
 * where the `[]()` gesture is typed. The fence's markdown / shadow-DOM switch
 * chooses the half: shadow DOM draws the card and hides the body; markdown
 * folds the card to its bar and the body is the editor.
 *
 * What it replaced: a read-only render of the chunk's markdown INSIDE the
 * fence, over a body folded into a collapsed callout -- the defect, because
 * neither of those is the editor the goal names.
 *
 * Live preview hides the body with a block REPLACE decoration from a state
 * field, not with CSS: CodeMirror measures its lines, and lines hidden behind
 * its back desync the height map it scrolls by. Block decorations cannot come
 * from a view plugin, hence the field. Reading view is plain sections, hidden
 * by class (`styles.css`, `.domvec-half-card`).
 */

import { Extension, RangeSetBuilder, StateEffect, StateField, Text } from "@codemirror/state";
import { Decoration, DecorationSet, EditorView, WidgetType } from "@codemirror/view";

/** True: the card is the half on show, so the body is hidden. */
export const setBodyHidden = StateEffect.define<boolean>();

/** The body's extent: from the line after the `domvec` fence closes to the
 *  end of the note, as [from, to] offsets; null when there is no body. */
export function bodyRange(doc: Text): [number, number] | null {
  let open = -1;
  for (let i = 1; i <= doc.lines; i++) {
    const text = doc.line(i).text.trim();
    if (open < 0) {
      if (text.startsWith("```domvec")) open = i;
    } else if (text.startsWith("```")) {
      if (i >= doc.lines) return null;
      // Blank lines straight after the fence belong to neither half.
      let first = i + 1;
      while (first <= doc.lines && !doc.line(first).text.trim()) first++;
      if (first > doc.lines) return null;
      return [doc.line(first).from, doc.length];
    }
  }
  return null;
}

class HiddenHalf extends WidgetType {
  eq() { return true; }
  toDOM() {
    const el = document.createElement("div");
    el.className = "domvec-half-hidden";
    el.textContent = "markdown half -- switch to “markdown” above to edit";
    return el;
  }
  ignoreEvent() { return false; }
}

interface Halves { hidden: boolean; deco: DecorationSet; }

function decorate(doc: Text, hidden: boolean): DecorationSet {
  const range = hidden ? bodyRange(doc) : null;
  if (!range) return Decoration.none;
  const b = new RangeSetBuilder<Decoration>();
  b.add(range[0], range[1], Decoration.replace({ block: true, widget: new HiddenHalf() }));
  return b.finish();
}

const halvesField = StateField.define<Halves>({
  create: () => ({ hidden: false, deco: Decoration.none }),
  update(v, tr) {
    let hidden = v.hidden;
    for (const e of tr.effects) if (e.is(setBodyHidden)) hidden = e.value;
    if (hidden === v.hidden && !tr.docChanged) return v;
    return { hidden, deco: decorate(tr.state.doc, hidden) };
  },
  provide: (f) => EditorView.decorations.from(f, (v) => v.deco),
});

export function chunkHalves(): Extension {
  return halvesField;
}

/** For checks: whether this editor is hiding a chunk note's body now. */
export function bodyHidden(view: EditorView): boolean {
  const v = view.state.field(halvesField, false);
  return !!(v && v.hidden && v.deco.size > 0);
}
