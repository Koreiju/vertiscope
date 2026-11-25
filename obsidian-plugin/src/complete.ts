/**
 * Natural-language-first prototyping (G-238; Addendum XI (167): "docstrings
 * and code-type wireframes first, then each component completed, informed by
 * graph RAG over the code-diff graph, the docstrings and the web KG").
 *
 * A python cell that is a WIREFRAME -- a `def` with a docstring and a `...`
 * (or `pass`) body -- gets a `✎ complete` control. Pressing it retrieves from
 * the store with the docstring (the one index holds code:// chunks, vault
 * notes and the web: the code's docstrings and the web KG alike), hands the
 * hits and the wireframe to the local model, and writes the completed
 * function back over the cell -- signature and docstring as the reader wrote
 * them. Planted `__domvecPlantNoComplete`: the cell is left as it was.
 *
 * In trie terms: reads the trie through /search; writes one cell of
 * vault://note (the same fence, its body replaced).
 */
import { TFile, type App } from "obsidian";
import { findFences } from "./fences";

const NL = String.fromCharCode(10);
const TQ = String.fromCharCode(96).repeat(3);

export function isWireframe(code: string): boolean {
  return /^\s*def\s+\w+\s*\(.*\)\s*(->\s*[^:]+)?:\s*$/m.test(code)
    && /("""|''')/.test(code)
    && /^\s+(\.\.\.|pass)\s*$/m.test(code);
}

function docstringOf(code: string): string {
  const m = code.match(/("""|''')([\s\S]*?)\1/);
  return m ? m[2].trim() : code;
}

/** The first python block of a reply, or the reply if it is bare code. */
export function codeOf(reply: string): string {
  const m = reply.match(new RegExp(TQ + "(?:python|py)?[ \\t]*\\r?\\n([\\s\\S]*?)" + TQ));
  return (m ? m[1] : reply).replace(/\s+$/, "");
}

export const completeStats = { asked: 0, written: 0, refused: 0, last: null as any };
(window as any).__domvecCompleteStats = completeStats;

export async function completeCell(app: App, deps: {
  search: (q: string) => Promise<{ url: string; preview: string }[]>;
  stream: (prompt: string, ctx: string[], on: (t: string) => void) => Promise<string>;
  viewOf: (path: string) => any;
}, path: string, line: number, code: string): Promise<boolean> {
  if ((window as any).__domvecPlantNoComplete || !isWireframe(code)) { completeStats.refused++; return false; }
  completeStats.asked++;
  const hits = (await deps.search(docstringOf(code)).catch(() => [])).slice(0, 4);
  // The hits go INTO the prompt as reference, the instruction last: sent as
  // chat context they came first and the model answered about them instead.
  const ref = hits.length ? "Reference from the store (use only if relevant):" + NL + hits.map((h) => "- " + h.url + ": " + h.preview.replace(/\s+/g, " ").slice(0, 300)).join(NL) + NL + NL : "";
  const prompt = ref + TQ + "python" + NL + code + NL + TQ + NL + NL
    + "Complete the Python function above: replace its `...` body with working code. Keep its signature and docstring exactly. "
    + "Reply with ONE " + TQ + "python block holding the whole function and nothing else.";
  const reply = await deps.stream(prompt, [], () => undefined);
  const body = codeOf(reply);
  const sig = (code.match(/^\s*def\s+(\w+)/m) || [])[1];
  if (!sig || !new RegExp("def\\s+" + sig + "\\b").test(body) || isWireframe(body)) {
    completeStats.refused++; completeStats.last = { path, line, reply: reply.slice(0, 300) }; return false;
  }
  const f = app.vault.getAbstractFileByPath(path);
  if (!(f instanceof TFile)) return false;
  // The editor only in source mode (EditorCalls.append's rule): a reading
  // view's editor is not saved, and the write was lost.
  const v0 = deps.viewOf(path), v = v0 && v0.getMode?.() === "source" ? v0 : null;
  const text: string = v?.editor ? v.editor.getValue() : await app.vault.read(f);
  const fence = findFences(text).find((x) => x.openLine === line);
  if (!fence) return false;
  const lines = text.split(NL);
  const next = [...lines.slice(0, fence.openLine + 1), ...body.split(NL), ...lines.slice(fence.closeLine)].join(NL);
  if (v?.editor) v.editor.setValue(next); else await app.vault.modify(f, next);
  completeStats.written++; completeStats.last = { path, line, hits: hits.length, body: body.slice(0, 300) };
  return true;
}
