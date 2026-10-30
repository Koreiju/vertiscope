/**
 * The notebook chat's REWIND -- `L-2`..`L-9` (PLUGIN_GOAL, "The minimal
 * embedded chat"). Pure: a note's text in, cells and rewinds out.
 *
 * "the context window for the small language model then starts at this
 * 'last-most viewable cell within current selection/focus' as the terminal
 * point and re-winds backwards within the notebook in its *current state*
 * (including terminal or kernel output display ...)"; "the user prompt
 * decides how many remaining chunks of tokens to rewind backwards for";
 * "the token limit for our re-winds are within a safety factor of the
 * maximum token limit for an input prompt".
 *
 * A CELL is what a notebook reader means by one: a fenced code block with
 * the output block the kernel wrote under it (`<!-- nb-output -->`, so the
 * output rewinds WITH its code, as the verbatim's "current state"), or a
 * markdown block -- a heading with the paragraphs under it up to the next
 * blank-line break, or a paragraph. Each cell carries a hash of its text, so
 * a cell a session has already been sent is recognised and not sent again,
 * and a cell whose output changed is a new cell.
 */

export interface Cell {
  /** First and last line, 0-based, inclusive. */
  from: number;
  to: number;
  kind: "code" | "markdown";
  /** The cell's text as the note holds it now, output included. */
  text: string;
  hash: string;
}

const FENCE = /^\s*(`{3,}|~{3,})/;
const OUT_OPEN = /^\s*<!--\s*nb-output\b/;
const OUT_CLOSE = /^\s*<!--\s*\/nb-output\s*-->/;

/** A small, stable string hash (FNV-1a, 32-bit, hex). */
export function hashOf(s: string): string {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 0x01000193) >>> 0; }
  return h.toString(16).padStart(8, "0");
}

/** The note's cells, in order. Front matter is not a cell. */
export function cellsOf(text: string): Cell[] {
  const lines = text.split("\n");
  const cells: Cell[] = [];
  let i = 0;
  if (lines[0] && /^---\s*$/.test(lines[0])) {
    for (i = 1; i < lines.length && !/^---\s*$/.test(lines[i]); i++);
    i++;
  }
  const push = (from: number, to: number, kind: Cell["kind"]) => {
    const body = lines.slice(from, to + 1).join("\n");
    if (!body.trim()) return;
    cells.push({ from, to, kind, text: body, hash: hashOf(kind + "\n" + body) });
  };
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }
    const f = FENCE.exec(line);
    if (f) {
      const mark = f[1];
      let j = i + 1;
      while (j < lines.length && !(lines[j].trim().startsWith(mark[0].repeat(mark.length)) && lines[j].trim().replace(/[`~]/g, "") === "")) j++;
      let end = Math.min(j, lines.length - 1);
      // The kernel's output belongs to the code above it.
      let k = end + 1;
      while (k < lines.length && !lines[k].trim()) k++;
      if (k < lines.length && OUT_OPEN.test(lines[k])) {
        let m = k;
        while (m < lines.length && !OUT_CLOSE.test(lines[m])) m++;
        end = Math.min(m, lines.length - 1);
      }
      push(i, end, "code");
      i = end + 1;
      continue;
    }
    if (OUT_OPEN.test(line)) {                       // an output with no code above: its own cell
      let m = i;
      while (m < lines.length && !OUT_CLOSE.test(lines[m])) m++;
      push(i, Math.min(m, lines.length - 1), "code");
      i = m + 1;
      continue;
    }
    // A markdown block: to the next blank line, fence or heading.
    let j = i + 1;
    while (j < lines.length && lines[j].trim() && !FENCE.test(lines[j]) && !OUT_OPEN.test(lines[j])
           && !/^#{1,6}\s/.test(lines[j])) j++;
    push(i, j - 1, "markdown");
    i = j;
  }
  return cells;
}

/** The cell holding `line`, or the nearest one above it (a blank line between cells). */
export function cellAt(cells: Cell[], line: number): number {
  let at = -1;
  for (let k = 0; k < cells.length; k++) {
    if (cells[k].from <= line) at = k;
    if (cells[k].from > line) break;
  }
  return at < 0 && cells.length ? 0 : at;
}

/** Roughly four characters a token, the encoder's average on English. */
export const CHARS_PER_TOKEN = 4;

export interface RewindOpts {
  /** The model's context window, in tokens. */
  nCtx: number;
  /** The share of it one rewind may take -- the verbatim's safety factor. */
  safety: number;
  /** At most this many cells (the prompt's own count), or all that fit. */
  limit?: number | null;
}

/** Cells from `end` backwards, oldest first, within the budget. The terminal
 *  cell is always included (cut to the budget if it alone exceeds it). */
export function rewind(cells: Cell[], end: number, o: RewindOpts): { cells: Cell[]; chars: number; budget: number; cut: boolean } {
  const budget = Math.floor(o.nCtx * o.safety) * CHARS_PER_TOKEN;
  const out: Cell[] = [];
  let chars = 0, cut = false;
  for (let k = end; k >= 0; k--) {
    if (o.limit != null && out.length >= o.limit) break;
    const c = cells[k];
    if (chars + c.text.length > budget) {
      if (!out.length) { out.push({ ...c, text: c.text.slice(c.text.length - budget) }); chars = budget; cut = true; }
      break;
    }
    out.push(c);
    chars += c.text.length;
  }
  return { cells: out.reverse(), chars, budget, cut };
}

/** "@3 why does this fail?" -- the prompt asks for the last 3 cells. The
 *  number is taken out of the prompt; none means as many as fit. */
export function parseRewind(prompt: string): { limit: number | null; prompt: string } {
  const m = /(^|\s)@(\d{1,3})(?=\s|$)/.exec(prompt);
  if (!m) return { limit: null, prompt: prompt.trim() };
  const rest = (prompt.slice(0, m.index) + " " + prompt.slice(m.index + m[0].length)).replace(/\s+/g, " ").trim();
  return { limit: Math.max(1, Number(m[2])), prompt: rest };
}
