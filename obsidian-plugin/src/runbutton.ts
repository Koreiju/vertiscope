/**
 * The run button, in both of Obsidian's rendering paths.
 *
 * Step 2 of `docs/NOTEBOOK_PANEL_DESIGN.md` §6, and its "done when" is
 * deliberately two-sided: *a button appears per fence, in reading AND live
 * preview*. Those are separate renderers and a plugin has to satisfy each on
 * its own terms:
 *
 * * **Reading view** builds real DOM from the markdown, so a
 *   `MarkdownPostProcessor` gets an element and can append a button to it.
 * * **Live preview** is CodeMirror 6. The `pre > code` of reading view does not
 *   exist; the fence is editor lines with decorations on them. So the button has
 *   to be a CM6 widget decoration, from a `ViewPlugin`.
 *
 * Only the fence-finding is shared (`fences.ts`), which is the only part that
 * *can* be.
 *
 * **The button does not execute anything yet.** Step 3 is the kernel. It calls
 * `host.onRunFence`, and until that has a kernel behind it the host says so out
 * loud — a button that silently does nothing is the phantom affordance the PRD
 * scores against, and a button that lies about being wired is worse.
 */

import { MarkdownPostProcessorContext } from "obsidian";
import { Extension, RangeSetBuilder } from "@codemirror/state";
import {
  Decoration, DecorationSet, EditorView, ViewPlugin, ViewUpdate, WidgetType,
} from "@codemirror/view";

import { Fence, cellSource, findFences, isRunnable } from "./fences";

/** What a run request carries. Enough for step 3 to execute without re-parsing. */
export interface RunRequest {
  readonly lang: string;
  readonly code: string;
  /** 0-based opening-fence line, which is the cell's identity in the note. */
  readonly line: number;
  /** Vault path of the note, when the renderer knew it. */
  readonly path: string;
}

export interface RunHost {
  /** Async, and the return is not awaited by the caller: a click must not
   *  block the editor while a cell runs. */
  onRunFence(req: RunRequest): void | Promise<void>;
}

/** The shared button, so the two paths cannot drift in label or class. */
function runButton(doc: Document, onClick: () => void): HTMLButtonElement {
  const btn = doc.createElement("button");
  btn.className = "vertiscope-run-fence";
  btn.type = "button";
  btn.setAttribute("aria-label", "Run this block");
  btn.textContent = "▶ run";
  btn.addEventListener("click", (ev) => {
    // The fence sits inside the editor in live preview, where a bare click
    // would also move the cursor into the code and, in reading view, would
    // start a text selection. Neither is what pressing a button means.
    ev.preventDefault();
    ev.stopPropagation();
    onClick();
  });
  return btn;
}

// --- reading view -----------------------------------------------------------

/**
 * Add a button to every runnable fence in rendered markdown.
 *
 * Registered as a general post-processor rather than a code-block processor:
 * `registerMarkdownCodeBlockProcessor(lang, …)` claims the fence and REPLACES
 * its rendering, which would cost the syntax highlighting Obsidian already
 * does, and would need registering once per language. A post-processor leaves
 * the block alone and adds to it.
 */
export function readingViewRunButtons(host: RunHost) {
  return (el: HTMLElement, ctx: MarkdownPostProcessorContext): void => {
    el.querySelectorAll("pre > code").forEach((code) => {
      const pre = code.parentElement;
      if (!pre || pre.querySelector(":scope > .vertiscope-run-fence")) return;

      // Obsidian marks the language as `language-python` on the <code>. Reading
      // the class is the only route here: the post-processor is handed rendered
      // DOM and the fence's info string is gone with the source.
      const cls = Array.from(code.classList)
        .find((c) => c.startsWith("language-")) || "";
      const lang = cls.slice("language-".length).toLowerCase();
      if (!isRunnable(lang)) return;

      pre.classList.add("vertiscope-has-run");
      pre.appendChild(runButton(el.ownerDocument, () => host.onRunFence({
        lang,
        code: cellSource(code.textContent || ""),
        // Reading view knows the section, not the line. `getSectionInfo` gives
        // the real line when it can; -1 says "unknown" rather than guessing 0,
        // which would make every unknown cell collide on the first one.
        line: ctx.getSectionInfo(pre)?.lineStart ?? -1,
        path: ctx.sourcePath || "",
      })));
    });
  };
}

// --- live preview (CodeMirror 6) --------------------------------------------

class RunWidget extends WidgetType {
  constructor(
    private readonly fence: Fence,
    private readonly host: RunHost,
    private readonly path: () => string,
  ) { super(); }

  /**
   * Two widgets are interchangeable when they would draw and act the same.
   *
   * Without this, every keystroke rebuilds every widget in the viewport: the
   * DOM is replaced, and a click landing during the rebuild hits a detached
   * button. The body is part of the comparison because it is what the button
   * would RUN — two fences identical but for their code are not the same
   * widget, and reusing one for the other would run the wrong cell.
   */
  eq(other: RunWidget): boolean {
    return other.fence.openLine === this.fence.openLine
      && other.fence.lang === this.fence.lang
      && cellSource(other.fence.body) === cellSource(this.fence.body);
  }

  toDOM(view: EditorView): HTMLElement {
    const wrap = view.dom.ownerDocument.createElement("span");
    wrap.className = "vertiscope-run-fence-wrap";
    wrap.appendChild(runButton(view.dom.ownerDocument, () => this.host.onRunFence({
      lang: this.fence.lang,
      code: cellSource(this.fence.body),
      line: this.fence.openLine,
      path: this.path(),
    })));
    return wrap;
  }

  /** The editor must not treat a click on the button as a click into the text. */
  ignoreEvent(): boolean { return true; }
}

function buildDecorations(view: EditorView, host: RunHost,
                          path: () => string): DecorationSet {
  const builder = new RangeSetBuilder<Decoration>();
  const doc = view.state.doc;
  // The whole document, not only the viewport. A fence's OPENING line can be
  // scrolled out of view while its body is on screen, and scanning only
  // visible ranges would both miss that button and mis-pair fences whose
  // partner is off-screen — the open/close pairing is a property of the
  // document, not of the viewport.
  for (const fence of findFences(doc.toString())) {
    if (!isRunnable(fence.lang)) continue;
    // At the END of the opening fence line: a widget at the line start would
    // sit before the ``` and push the fence marker sideways.
    const line = doc.line(fence.openLine + 1);   // CM lines are 1-based
    builder.add(line.to, line.to, Decoration.widget({
      widget: new RunWidget(fence, host, path),
      side: 1,
    }));
  }
  return builder.finish();
}

/**
 * The live-preview extension.
 *
 * Rebuilt on `docChanged` only. A viewport change cannot add or remove a fence,
 * and rebuilding on scroll would replace every button while the reader is
 * reaching for one.
 */
export function livePreviewRunButtons(host: RunHost,
                                      path: () => string): Extension {
  return ViewPlugin.fromClass(
    class {
      decorations: DecorationSet;
      constructor(view: EditorView) {
        this.decorations = buildDecorations(view, host, path);
      }
      update(update: ViewUpdate) {
        if (update.docChanged) {
          this.decorations = buildDecorations(update.view, host, path);
        }
      }
    },
    { decorations: (v) => v.decorations },
  );
}
