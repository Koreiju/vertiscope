/**
 * A code cell with the editor capabilities a reader expects from VS Code
 * (PLUGIN_GOAL 133: "Code cells need to have the full set of vscode
 * capabilities").
 *
 * The extensions are the ones Obsidian's own editor is built from, required at
 * runtime so the cell shares its CodeMirror instance (esbuild marks them
 * external). Read from / written to the trie: completion and go-to-definition
 * ask the sidecar's code property graph (`/code_nodes`), whose nodes are the
 * trie's `code://` addresses, so a picked definition opens at the address the
 * trie holds for it.
 *
 * What a cell gets: line numbers, folding, bracket matching and auto-close,
 * auto-indent, undo history, search and replace, selection-match highlight,
 * Python highlighting, Mod-/ comment toggle, Tab indent, completion from the
 * code graph and the cell's own words, and Mod-click go-to-definition.
 * Planted `__domvecPlantPlainCodeCell`: none of it, a bare editor.
 */
import { Decoration, EditorView, ViewPlugin, keymap, lineNumbers, highlightActiveLine, highlightActiveLineGutter, type DecorationSet, type ViewUpdate } from "@codemirror/view";
import { RangeSetBuilder, type Extension } from "@codemirror/state";

export interface CodeCellHost {
  codeNodes: (q: string) => Promise<any[]>;
  openCode: (url: string) => void;
}

export const codeCellStats = { built: 0, completions_asked: 0, definitions_opened: 0, last_definition: "" };
(window as any).__domvecCodeCell = codeCellStats;

export function codeCellExtensions(host: CodeCellHost): Extension[] {
  if ((window as any).__domvecPlantPlainCodeCell) return [];
  const R: any = require;
  const ac = R("@codemirror/autocomplete"), cmd = R("@codemirror/commands");
  const lang = R("@codemirror/language"), search = R("@codemirror/search");
  const out: Extension[] = [
    lineNumbers(), highlightActiveLineGutter(), highlightActiveLine(),
    lang.foldGutter(), lang.bracketMatching(), lang.indentOnInput(), lang.indentUnit.of("    "),
    ac.closeBrackets(), cmd.history(), search.highlightSelectionMatches(),
    lang.syntaxHighlighting(lang.defaultHighlightStyle, { fallback: true }),
  ];
  // Python highlighting through Obsidian's own CodeMirror 5 python mode, which
  // has the stream interface StreamLanguage wants.
  const cm5: any = (window as any).CodeMirror;
  const mode = cm5?.getMode?.({ indentUnit: 4 }, "python");
  if (mode && mode.name === "python") {
    out.push(lang.StreamLanguage.define({
      name: "python", startState: () => mode.startState(0), token: (s: any, st: any) => mode.token(s, st),
      languageData: { commentTokens: { line: "#" } },
    }));
    // The colours: the stream language's tags come from a second copy of
    // @lezer/highlight, so no highlighter matches them (0 styled spans,
    // measured). The mode is run directly instead, its token names as the
    // `cm-<name>` classes Obsidian's theme already colours.
    if (cm5.StringStream) out.push(cm5Highlight(cm5, mode));
  }
  // Completion: names from the code graph, then words in the cell.
  const fromGraph = async (ctx: any) => {
    const w = ctx.matchBefore(/[\w.]+/);
    if (!w || (w.from === w.to && !ctx.explicit)) return null;
    codeCellStats.completions_asked++;
    const nodes = w.text.length >= 2 ? await host.codeNodes(w.text).catch(() => []) : [];
    const words = new Set<string>();
    for (const m of ctx.state.doc.toString().matchAll(/[A-Za-z_]\w{2,}/g)) words.add(m[0]);
    const opts = [
      ...nodes.map((n: any) => ({ label: String(n.name || n.qname), detail: `${n.kind || "node"} ${n.qname || ""}`, type: n.kind === "class" ? "class" : n.kind === "function" ? "function" : "variable", boost: 2 })),
      ...[...words].filter((x) => x !== w.text).map((x) => ({ label: x, type: "text" })),
    ];
    return { from: w.from + (w.text.lastIndexOf(".") + 1), options: opts, validFor: /^\w*$/ };
  };
  out.push(ac.autocompletion({ override: [fromGraph], activateOnTyping: true }));
  // Go to definition: Mod-click (or F12) on a name opens its node.
  const gotoAt = async (view: EditorView, pos: number): Promise<boolean> => {
    const line = view.state.doc.lineAt(pos), off = pos - line.from;
    let a = off, b = off;
    while (a > 0 && /[\w.]/.test(line.text[a - 1])) a--;
    while (b < line.text.length && /[\w.]/.test(line.text[b])) b++;
    const name = line.text.slice(a, b);
    if (!name) return false;
    const last = name.split(".").pop() || name;
    const nodes = await host.codeNodes(last).catch(() => []);
    const hit = nodes.find((n: any) => n.name === last && /class|function|method/.test(String(n.kind))) || nodes.find((n: any) => n.name === last);
    if (!hit?.url) return false;
    codeCellStats.definitions_opened++; codeCellStats.last_definition = String(hit.qname || hit.name);
    host.openCode(String(hit.url));
    return true;
  };
  out.push(EditorView.domEventHandlers({
    mousedown: (e: MouseEvent, view: EditorView) => {
      if (!(e.ctrlKey || e.metaKey)) return false;
      const pos = view.posAtCoords({ x: e.clientX, y: e.clientY });
      if (pos == null) return false;
      e.preventDefault(); void gotoAt(view, pos); return true;
    },
  }));
  out.push(keymap.of([
    { key: "F12", run: (v: EditorView) => { void gotoAt(v, v.state.selection.main.head); return true; } },
    { key: "Mod-/", run: cmd.toggleComment },
    ...ac.closeBracketsKeymap, ...ac.completionKeymap, ...cmd.historyKeymap,
    ...search.searchKeymap, ...lang.foldKeymap, cmd.indentWithTab, ...cmd.defaultKeymap,
  ]));
  (codeCellStats as any).gotoAt = gotoAt;
  codeCellStats.built++;
  return out;
}

const markCache = new Map<string, Decoration>();
function cm5Highlight(cm5: any, mode: any): Extension {
  const build = (view: EditorView): DecorationSet => {
    const b = new RangeSetBuilder<Decoration>();
    const doc = view.state.doc, last = view.visibleRanges.length ? view.visibleRanges[view.visibleRanges.length - 1].to : doc.length;
    const st = mode.startState(0);
    for (let i = 1; i <= doc.lines; i++) {
      const line = doc.line(i);
      if (line.from > last) break;
      const stream = new cm5.StringStream(line.text, 4);
      if (!line.text.length && mode.blankLine) mode.blankLine(st);
      while (!stream.eol()) {
        const style = mode.token(stream, st);
        if (stream.pos <= stream.start) { stream.pos++; continue; }
        if (style) {
          const cls = String(style).split(" ").map((x: string) => "cm-" + x).join(" ");
          let d = markCache.get(cls);
          if (!d) { d = Decoration.mark({ class: cls }); markCache.set(cls, d); }
          b.add(line.from + stream.start, line.from + stream.pos, d);
        }
        stream.start = stream.pos;
      }
    }
    return b.finish();
  };
  return ViewPlugin.fromClass(class {
    decorations: DecorationSet;
    constructor(view: EditorView) { this.decorations = build(view); }
    update(u: ViewUpdate) { if (u.docChanged || u.viewportChanged) this.decorations = build(u.view); }
  }, { decorations: (v: any) => v.decorations });
}
