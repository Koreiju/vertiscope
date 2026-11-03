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
  /** The cell's `{ref}` inputs from its fence line (G-279). */
  readonly refs?: string[];
  /** The rollout's sample of the first `{ref}` (G-283). */
  readonly sample?: number;
}

export interface RunHost {
  /** Async, and the return is not awaited by the caller: a click must not
   *  block the editor while a cell runs. */
  onRunFence(req: RunRequest): void | Promise<void>;
  /** `P-N3`: the same cell to a command terminal in its OWN pane (§4a). The
   *  kernel runs in place; "both at once" is pressing both -- two panes. */
  onTerminalFence?(req: RunRequest): void | Promise<void>;
  /** G-283: play / pause the cell over the samples of its first `{ref}`. */
  onRolloutFence?(req: RunRequest): void | Promise<void>;
  /** G-234: the cell in the code artifact panel, as a module opens there. */
  onOpenFence?(req: RunRequest): void | Promise<void>;
  /** G-329: the cell unnested into a black-box panel on the plane. */
  onUnnestFence?(req: RunRequest): void | Promise<void>;
}

/** `⧉ open` beside run (G-234). */
function openButton(doc: Document, onClick: () => void): HTMLButtonElement {
  const btn = doc.createElement("button");
  btn.className = "domvec-open-fence";
  btn.type = "button";
  btn.setAttribute("aria-label", "Open this cell in the code artifact panel");
  btn.textContent = "⧉ open";
  btn.addEventListener("mousedown", (e) => e.preventDefault());
  btn.addEventListener("click", (e) => { e.preventDefault(); e.stopPropagation(); onClick(); });
  return btn;
}

/** `⊞ unnest` beside open (G-329): the cell as a black box, its imports unnesting down to their base modules. */
function unnestButton(doc: Document, onClick: () => void): HTMLButtonElement {
  const btn = doc.createElement("button");
  btn.className = "domvec-open-fence domvec-unnest-fence";
  btn.type = "button";
  btn.setAttribute("aria-label", "Unnest this cell: its imports and definitions as black boxes");
  btn.textContent = "⊞ unnest";
  btn.addEventListener("mousedown", (e) => e.preventDefault());
  btn.addEventListener("click", (e) => { e.preventDefault(); e.stopPropagation(); onClick(); });
  return btn;
}

/** The rollout's play beside run (G-283), on a cell with a `{ref}` to iterate. */
function playButton(doc: Document, onClick: () => void): HTMLButtonElement {
  const btn = doc.createElement("button");
  btn.className = "domvec-play-fence";
  btn.type = "button";
  btn.setAttribute("aria-label", "Run this block once per sample of its first ref");
  btn.textContent = "\u25b6\u25b6 play";
  btn.addEventListener("mousedown", (e) => e.preventDefault());
  btn.addEventListener("click", (e) => { e.preventDefault(); e.stopPropagation(); onClick(); });
  return btn;
}

/** The terminal button beside the run button (`P-N3`). Planted
 *  `__domvecPlantNoTermFence`: not drawn. */
function termButton(doc: Document, onClick: () => void): HTMLButtonElement | null {
  if ((window as any).__domvecPlantNoTermFence) return null;
  const btn = doc.createElement("button");
  btn.className = "domvec-term-fence";
  btn.type = "button";
  btn.setAttribute("aria-label", "Open this block in a terminal pane");
  btn.textContent = "⌨ terminal";
  btn.addEventListener("click", (ev) => { ev.preventDefault(); ev.stopPropagation(); onClick(); });
  return btn;
}

/** The shared button, so the two paths cannot drift in label or class. */
function runButton(doc: Document, onClick: () => void): HTMLButtonElement {
  const btn = doc.createElement("button");
  btn.className = "domvec-run-fence";
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
      if (!pre || pre.querySelector(":scope > .domvec-run-fence")) return;

      // Obsidian marks the language as `language-python` on the <code>. Reading
      // the class is the only route here: the post-processor is handed rendered
      // DOM and the fence's info string is gone with the source.
      const cls = Array.from(code.classList)
        .find((c) => c.startsWith("language-")) || "";
      const lang = cls.slice("language-".length).toLowerCase();
      if (!isRunnable(lang)) return;

      pre.classList.add("domvec-has-run");
      // The fence line's `{ref}` inputs (G-279): reading view renders no info
      // string, so they are read from the section's source line.
      const info = ctx.getSectionInfo(pre);
      const fenceLine = info ? (info.text.split("\n")[info.lineStart] || "") : "";
      const refs = [...fenceLine.replace(/^\s*(`{3,}|~{3,})\s*\S*/, "").matchAll(/\{([^{}]+)\}/g)]
        .map((m) => m[1].trim()).filter(Boolean);
      const req = (): RunRequest => ({
        refs,
        lang,
        code: cellSource(code.textContent || ""),
        // Reading view knows the section, not the line. `getSectionInfo` gives
        // the real line when it can; -1 says "unknown" rather than guessing 0,
        // which would make every unknown cell collide on the first one.
        line: ctx.getSectionInfo(pre)?.lineStart ?? -1,
        path: ctx.sourcePath || "",
      });
      pre.appendChild(runButton(el.ownerDocument, () => host.onRunFence(req())));
      const term = host.onTerminalFence ? termButton(el.ownerDocument, () => host.onTerminalFence!(req())) : null;
      if (term) pre.appendChild(term);
      if (host.onOpenFence) pre.appendChild(openButton(el.ownerDocument, () => host.onOpenFence!(req())));
      if (host.onUnnestFence) pre.appendChild(unnestButton(el.ownerDocument, () => host.onUnnestFence!(req())));
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
    wrap.className = "domvec-run-fence-wrap";
    const req = (): RunRequest => ({
      lang: this.fence.lang,
      code: cellSource(this.fence.body),
      line: this.fence.openLine,
      path: this.path(),
      refs: this.fence.refs,
    });
    wrap.appendChild(runButton(view.dom.ownerDocument, () => this.host.onRunFence(req())));
    const term = this.host.onTerminalFence
      ? termButton(view.dom.ownerDocument, () => this.host.onTerminalFence!(req())) : null;
    if (term) wrap.appendChild(term);
    if (this.host.onOpenFence) wrap.appendChild(openButton(view.dom.ownerDocument, () => this.host.onOpenFence!(req())));
    if (this.host.onUnnestFence) wrap.appendChild(unnestButton(view.dom.ownerDocument, () => this.host.onUnnestFence!(req())));
    if (this.host.onRolloutFence && (this.fence.refs || []).length) {
      wrap.appendChild(playButton(view.dom.ownerDocument, () => this.host.onRolloutFence!(req())));
    }
    return wrap;
  }

  /** The editor must not treat a click on the button as a click into the text. */
  ignoreEvent(): boolean { return true; }
}

function buildDecorations(view: EditorView, host: RunHost,
                          path: (view: EditorView) => string): DecorationSet {
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
      widget: new RunWidget(fence, host, () => path(view)),
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
                                      path: (view: EditorView) => string): Extension {
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
