/** The chat interface's pure half (G-394): a conversation note -> turns ->
 *  typed blocks -> addresses. No Obsidian import, so it is unit-tested. */

const NL = "\n";
const FENCE = "`".repeat(3);

export type BlockKind = "prose" | "code";
/** `line`: a code block's opening-fence line in the WHOLE note (0-based) --
 *  the cell's identity to the kernel, as in any note (182: the same tools
 *  wherever a code artifact is found); -1 for prose. */
export interface ChatBlock { kind: BlockKind; lang: string; text: string; line: number }
export interface ChatTurn { who: "you" | "model"; label: string; body: string; blocks: ChatBlock[] }
export interface Piece { address: string; kind: BlockKind; lang: string; text: string; lines?: [number, number] }

/** The heading a reader's turn starts with. */
export const YOU = "## You";

/** A conversation note -> its turns. Text before the first turn heading is
 *  NOT a turn: an old chat note's body (a prompt written before the
 *  interface) comes back as `draft`, for the input box. */
export function parseConversation(text: string): { turns: ChatTurn[]; draft: string } {
  const body = text.replace(/^---[\s\S]*?\n---\s*\n?/, "");
  const lines = body.split(/\r?\n/);
  // The body's first line, as a line of the whole note.
  const skip = text.slice(0, text.length - body.length).split(/\r?\n/).length - 1;
  const turns: ChatTurn[] = [];
  const pre: string[] = [];
  let cur: ChatTurn | null = null, buf: string[] = [], inFence = false, from = 0;
  const close = () => {
    if (!cur) return;
    // Leading blank lines dropped from the body still count toward its lines.
    let lead = 0; while (lead < buf.length && !buf[lead].trim()) lead++;
    cur.body = buf.join(NL).replace(/^\s+|\s+$/g, "");
    cur.blocks = blocksOf(cur.body, from + lead);
    turns.push(cur);
  };
  for (let i = 0; i < lines.length; i++) {
    const l = lines[i];
    if (l.startsWith(FENCE)) inFence = !inFence;
    const m = !inFence && /^## (.+?)\s*$/.exec(l);
    if (m) {
      close();
      const label = m[1];
      cur = { who: label === "You" ? "you" : "model", label, body: "", blocks: [] };
      buf = [];
      from = skip + i + 1;
      continue;
    }
    (cur ? buf : pre).push(l);
  }
  close();
  return { turns, draft: pre.join(NL).trim() };
}

/** A turn's body -> its blocks: each fenced block one `code` block (its
 *  language from the fence), each paragraph between them one `prose` block. */
export function blocksOf(body: string, offset = -1): ChatBlock[] {
  const out: ChatBlock[] = [];
  const lines = body.split(/\r?\n/);
  let prose: string[] = [], code: string[] | null = null, lang = "", open = -1;
  const flushProse = () => {
    for (const para of prose.join(NL).split(/\n\s*\n/)) if (para.trim()) out.push({ kind: "prose", lang: "", text: para.trim(), line: -1 });
    prose = [];
  };
  for (let i = 0; i < lines.length; i++) {
    const l = lines[i];
    if (code === null && l.startsWith(FENCE)) { flushProse(); code = []; lang = l.slice(3).trim().split(/\s/)[0] || "text"; open = offset < 0 ? -1 : offset + i; continue; }
    if (code !== null && l.startsWith(FENCE)) { out.push({ kind: "code", lang, text: code.join(NL), line: open }); code = null; continue; }
    (code ?? prose).push(l);
  }
  if (code !== null) out.push({ kind: "code", lang, text: code.join(NL), line: open });   // a reply still streaming
  flushProse();
  return out;
}

/** The address of a block, inside the conversation note: turn, block, and
 *  for a pulled line range its 1-based lines. */
export function addressOf(note: string, turn: number, block: number, lines?: [number, number]): string {
  return `vault://${note}#turn${turn + 1}/block${block + 1}` + (lines ? `/L${lines[0]}-${lines[1]}` : "");
}

/** The text a model turn is appended with. */
export function turnText(who: string, body: string): string {
  return `${NL}## ${who}${NL}${NL}${body}${NL}`;
}

/** A selection inside a code block -> its 1-based line range, or null. */
export function rangeOf(code: string, selected: string): [number, number] | null {
  const s = selected.replace(/\r/g, "").replace(/^\n+|\n+$/g, "");
  const at = code.indexOf(s);
  if (at < 0 || !s) return null;
  const first = code.slice(0, at).split("\n").length;
  return [first, first + s.split("\n").length - 1];
}
