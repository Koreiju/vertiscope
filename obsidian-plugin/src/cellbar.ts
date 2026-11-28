/**
 * The structural-cell buttons, at the very bottom of the native markdown
 * (`P-M4`; `NOTEBOOK_PANEL_DESIGN` §2).
 *
 * The verbatim: "The buttons for adding the completely new structural cells
 * are at the very bottom of the obsidian markdown". Not floating per cell, not
 * a toolbar: one strip after the note's last line, in both of Obsidian's
 * renderers, on the native view itself -- there is no new view type (`P-M1`:
 * the original panel survives in its native form, and is grown).
 *
 *   [+ code]          a python fence appended to the note, cursor inside it;
 *                     its run button and kernel are `runbutton.ts`'s
 *   [+ terminal]      a command terminal in a SEPARATE pane (§4a: a shell is a
 *                     stream, not a leaf, and gets no address)
 *   [+ browser cell]  a browser cell IN the note: a ```browser fence, rendered
 *                     as the same component the standalone pane is (G-36)
 *
 * Placed by the plugin into the view's own scroller -- after CodeMirror's
 * content in live preview, before the footer in reading view -- and put back
 * whenever Obsidian rebuilds either (`ensure` is cheap and idempotent).
 */

import { MarkdownView } from "obsidian";

export interface CellBarHost {
  addCodeCell(view: MarkdownView): Promise<void>;
  openTerminal(): unknown;
  openBrowser(): void | Promise<void>;
  addBrowserCell(view: MarkdownView): Promise<void>;
  addChatCell(view: MarkdownView): Promise<void>;
}

const CLS = "domvec-cellbar";

function build(doc: Document, view: MarkdownView, host: CellBarHost): HTMLElement {
  const bar = doc.createElement("div");
  bar.className = CLS;
  bar.setAttribute("contenteditable", "false");
  const add = (label: string, title: string, cls: string, act: () => unknown) => {
    const b = doc.createElement("button");
    b.type = "button";
    b.className = "domvec-cellbar-add " + cls;
    b.textContent = label;
    b.title = title;
    b.addEventListener("mousedown", (e) => e.preventDefault());
    b.addEventListener("click", (e) => { e.preventDefault(); e.stopPropagation(); void act(); });
    bar.appendChild(b);
  };
  add("+ code", "append a code cell to this note", "is-code", () => host.addCodeCell(view));
  add("+ terminal", "open a command terminal in its own pane", "is-terminal", () => host.openTerminal());
  add("+ browser cell", "append a browser cell to this note", "is-browser", () => host.addBrowserCell(view));
  if (!(window as any).__domvecPlantNoCellBarChat) {
    add("+ chat", "append a chat cell to this note", "is-chat", () => host.addChatCell(view));
  }
  return bar;
}

/** Put the strip at the bottom of whichever renderer the view is showing. */
export function ensureCellBar(view: MarkdownView, host: CellBarHost, on: boolean): boolean {
  const root = view.containerEl;
  const placed: HTMLElement[] = [];
  // Live preview / source: after the editor's content, inside its scroller.
  const sizer = root.querySelector(".markdown-source-view .cm-sizer");
  const content = sizer?.querySelector(":scope > .cm-contentContainer");
  // Reading view: the last thing before the footer.
  const preview = root.querySelector(".markdown-reading-view .markdown-preview-sizer");
  const footer = preview?.querySelector(":scope > .mod-footer");
  for (const [parent, before] of [[sizer, content?.nextSibling ?? null], [preview, footer ?? null]] as const) {
    if (!parent) continue;
    let bar = parent.querySelector(":scope > ." + CLS) as HTMLElement | null;
    if (!on) { bar?.remove(); continue; }
    if (!bar) {
      bar = build(root.ownerDocument, view, host);
      parent.insertBefore(bar, before as Node | null);
    }
    placed.push(bar);
  }
  return placed.length > 0;
}
