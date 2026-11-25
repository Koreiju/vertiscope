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
import { defsOf, isWireframe, orderDefs, type WDef } from "./wiredefs";
export { defsOf, isWireframe, orderDefs };

const NL = String.fromCharCode(10);
const TQ = String.fromCharCode(96).repeat(3);

function docstringOf(code: string): string {
  const m = code.match(/("""|''')([\s\S]*?)\1/);
  return m ? m[2].trim() : code;
}

/** The first python block of a reply, or the reply if it is bare code. */
export function codeOf(reply: string): string {
  const m = reply.match(new RegExp(TQ + "(?:python|py)?[ \\t]*\\r?\\n([\\s\\S]*?)" + TQ));
  return (m ? m[1] : reply).replace(/\s+$/, "");
}

export const completeStats = { asked: 0, written: 0, refused: 0, components: [] as string[], last: null as any };
if (typeof window !== "undefined") (window as any).__domvecCompleteStats = completeStats;

type Deps = {
  search: (q: string) => Promise<{ url: string; preview: string }[]>;
  stream: (prompt: string, ctx: string[], on: (t: string) => void) => Promise<string>;
  viewOf: (path: string) => any;
};

/** One component: the completed `def name` from the model, or null. */
async function completeOne(deps: Deps, cell: string, d: WDef, done: string[]): Promise<string | null> {
  const hits = (await deps.search(d.doc || docstringOf(d.text)).catch(() => [])).slice(0, 4);
  // The hits go INTO the prompt as reference, the instruction last: sent as
  // chat context they came first and the model answered about them instead.
  const ref = hits.length ? "Reference from the store (use only if relevant):" + NL + hits.map((h) => "- " + h.url + ": " + h.preview.replace(/\s+/g, " ").slice(0, 300)).join(NL) + NL + NL : "";
  const prior = done.length ? "Already written (call these, do not rewrite them):" + NL + TQ + "python" + NL + done.join(NL + NL) + NL + TQ + NL + NL : "";
  const others = cell !== d.text ? "The module it belongs to:" + NL + TQ + "python" + NL + cell + NL + TQ + NL + NL : "";
  const prompt = ref + prior + others + TQ + "python" + NL + d.text + NL + TQ + NL + NL
    + "Complete the Python function `" + d.name + "` above: replace its `...` body with working code. Keep its signature and docstring exactly. "
    + "Reply with ONE " + TQ + "python block holding the whole function " + d.name + " and nothing else.";
  const reply = await deps.stream(prompt, [], () => undefined);
  const got = defsOf(codeOf(reply)).find((x) => x.name === d.name);
  if (!got || got.wire) { completeStats.last = { name: d.name, reply: reply.slice(0, 300) }; return null; }
  return got.text;
}

/** Complete every wireframe of the cell, in order (G-238: "then each component
 *  completed"); each completed component is handed to the next. The cell is
 *  written once, with what was completed, even if a later component failed. */
export async function completeCell(app: App, deps: Deps, path: string, line: number, code: string): Promise<boolean> {
  if ((window as any).__domvecPlantNoComplete || !isWireframe(code)) { completeStats.refused++; return false; }
  completeStats.asked++;
  // Planted `__domvecPlantCompleteUnordered`: source order, no prior components handed on.
  const plantU = !!(window as any).__domvecPlantCompleteUnordered;
  const order = plantU ? defsOf(code).filter((x) => x.wire) : orderDefs(defsOf(code));
  let cur = code; const done: string[] = [], names: string[] = [];
  for (const w of order) {
    const d = defsOf(cur).find((x) => x.name === w.name && x.wire);
    if (!d) continue;
    const body = await completeOne(deps, cur, d, plantU ? [] : done);
    if (!body) { completeStats.refused++; break; }
    const ls = cur.split(NL);
    cur = [...ls.slice(0, d.from), ...body.split(NL), ...ls.slice(d.to)].join(NL);
    done.push(body); names.push(d.name);
  }
  if (!names.length) return false;
  const f = app.vault.getAbstractFileByPath(path);
  if (!(f instanceof TFile)) return false;
  // The editor only in source mode (EditorCalls.append's rule): a reading
  // view's editor is not saved, and the write was lost.
  const v0 = deps.viewOf(path), v = v0 && v0.getMode?.() === "source" ? v0 : null;
  const text: string = v?.editor ? v.editor.getValue() : await app.vault.read(f);
  const fence = findFences(text).find((x) => x.openLine === line);
  if (!fence) return false;
  const lines = text.split(NL);
  const next = [...lines.slice(0, fence.openLine + 1), ...cur.replace(/\s+$/, "").split(NL), ...lines.slice(fence.closeLine)].join(NL);
  if (v?.editor) v.editor.setValue(next); else await app.vault.modify(f, next);
  completeStats.written++; completeStats.components = names; completeStats.last = { path, line, order: names };
  return true;
}
