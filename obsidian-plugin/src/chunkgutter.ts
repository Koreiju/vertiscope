/**
 * Where the chunker cut, drawn in the editor's gutter.
 *
 * `P-N8`, and `NOTEBOOK_PANEL_DESIGN` §5 is explicit that it is not decoration:
 * *"it is the only way a reader can tell why retrieval returned half a section,
 * and at a 256-token window the cuts are frequent enough to matter."*
 *
 * **Computed from the text on screen, not read back from the store.** §5 said
 * "read straight from the trie", and that is right for a note nobody is editing
 * and wrong for the one in front of you: a stored boundary is stale from the
 * first keystroke, and a mark confidently in the wrong place answers "why did my
 * section split" with last week's answer. The sidecar's `/chunk_preview` runs
 * the SAME pipeline indexing does -- `tag_note`, `from_tags`, `render_trie` --
 * with the store write left out, so the marks agree with what indexing would
 * produce by construction.
 *
 * A CM6 gutter rather than line decorations: a boundary belongs beside the text
 * and not in it. Marking the lines themselves would compete with Obsidian's own
 * syntax highlighting for the same pixels, and a reader would have to learn
 * which colour meant what.
 */

import { Extension, RangeSetBuilder, StateEffect, StateField } from "@codemirror/state";
import { EditorView, GutterMarker, gutter } from "@codemirror/view";

/** One chunk's extent, as the sidecar reported it. */
export interface ChunkSpan {
  index: number;
  start_line: number;      // 0-based, inclusive
  end_line: number;        // 0-based, inclusive
  tokens: number;
  window: number;
  over_window: boolean;
}

/** Replaces the known spans for this editor. */
export const setChunkSpans = StateEffect.define<ChunkSpan[]>();

const spansField = StateField.define<ChunkSpan[]>({
  create: () => [],
  update(spans, tr) {
    for (const e of tr.effects) if (e.is(setChunkSpans)) return e.value;
    return spans;
  },
});

class BoundaryMarker extends GutterMarker {
  constructor(private readonly span: ChunkSpan,
              private readonly where: "start" | "middle" | "end") { super(); }

  eq(other: BoundaryMarker) {
    return other.span.index === this.span.index && other.where === this.where;
  }

  toDOM() {
    const el = document.createElement("div");
    el.className = `vertiscope-chunk-mark vertiscope-chunk-${this.where}` +
                   (this.span.over_window ? " vertiscope-chunk-over" : "");
    // The count on the FIRST line only. Repeating it down the span would say
    // the same true thing forty times and make the gutter unreadable, which is
    // the failure mode of every gutter that tries to say more than one thing.
    el.textContent = this.where === "start" ? String(this.span.tokens) : "";
    el.title = `chunk ${this.span.index}: lines ` +
               `${this.span.start_line + 1}–${this.span.end_line + 1}, ` +
               `${this.span.tokens} of ${this.span.window} tokens` +
               (this.span.over_window ? " — OVER the window" : "");
    return el;
  }
}

/**
 * The gutter extension.
 *
 * Rebuilt only when the SPANS change, not on every document change: the spans
 * come from a round trip to the sidecar, so on a keystroke they are stale by
 * definition and redrawing them would make the marks jitter against text that
 * has already moved. The caller re-requests, and the marks move when the answer
 * arrives.
 */
export function chunkGutter(): Extension {
  return [
    spansField,
    gutter({
      class: "vertiscope-chunk-gutter",
      markers(view: EditorView) {
        const spans = view.state.field(spansField, false) ?? [];
        if (!spans.length) return RangeSetBuilder.prototype.finish.call(
          new RangeSetBuilder());
        const builder = new RangeSetBuilder<GutterMarker>();
        const total = view.state.doc.lines;
        for (const span of spans) {
          for (let n = span.start_line; n <= span.end_line; n++) {
            // CM lines are 1-based, and the sidecar counts from 0. Off by one
            // here would put every mark one line high, which reads as a
            // chunker that cuts in the wrong place rather than as an index bug.
            const lineNo = n + 1;
            if (lineNo < 1 || lineNo > total) continue;
            const line = view.state.doc.line(lineNo);
            const where = n === span.start_line ? "start"
                        : n === span.end_line ? "end" : "middle";
            builder.add(line.from, line.from, new BoundaryMarker(span, where));
          }
        }
        return builder.finish();
      },
    }),
  ];
}
