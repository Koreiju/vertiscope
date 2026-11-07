/**
 * The `[]()` gesture's trigger, on one line of text (`R-1`): pure, so it is
 * tested without an editor. `linkgesture.ts` is the editor half.
 *
 * `[query](` before the cursor with `)` right after it -- Obsidian pairs the
 * parenthesis as it is typed -- or `[query]()` just before it. The query is
 * three characters or more: `[a]()` is a link being typed, not a question.
 * An image (`![alt]()`) is not a gesture: its parentheses take a picture.
 * Returns where the link goes (the inside of the `()`) and the query.
 */
// Spaces between `]` and `(` are allowed (2026-11-07: "[ love messages ] ()"
// never fired). Planted `__domvecPlantTightGesture`: they must touch.
const BEFORE_OPEN_TIGHT = /(^|[^!])\[([^[\]\n]{3,})\]\($/;
const BEFORE_CLOSED_TIGHT = /(^|[^!])\[([^[\]\n]{3,})\]\(\)$/;
const BEFORE_OPEN_LOOSE = /(^|[^!])\[([^[\]\n]{3,})\][ \t]*\($/;
const BEFORE_CLOSED_LOOSE = /(^|[^!])\[([^[\]\n]{3,})\][ \t]*\(\)$/;

export function gestureIn(line: string, ch: number): { ch: number; query: string } | null {
  const before = line.slice(0, ch);
  const after = line.slice(ch);
  const tight = typeof window !== "undefined" && (window as any).__domvecPlantTightGesture;
  const BEFORE_OPEN = tight ? BEFORE_OPEN_TIGHT : BEFORE_OPEN_LOOSE;
  const BEFORE_CLOSED = tight ? BEFORE_CLOSED_TIGHT : BEFORE_CLOSED_LOOSE;
  let m = BEFORE_OPEN.exec(before);
  if (m && after.startsWith(")")) return { ch, query: m[2].trim() };
  m = BEFORE_CLOSED.exec(before);
  if (m) return { ch: ch - 1, query: m[2].trim() };
  return null;
}
