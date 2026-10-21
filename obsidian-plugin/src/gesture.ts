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
const BEFORE_OPEN = /(^|[^!])\[([^[\]\n]{3,})\]\($/;
const BEFORE_CLOSED = /(^|[^!])\[([^[\]\n]{3,})\]\(\)$/;

export function gestureIn(line: string, ch: number): { ch: number; query: string } | null {
  const before = line.slice(0, ch);
  const after = line.slice(ch);
  let m = BEFORE_OPEN.exec(before);
  if (m && after.startsWith(")")) return { ch, query: m[2].trim() };
  m = BEFORE_CLOSED.exec(before);
  if (m) return { ch: ch - 1, query: m[2].trim() };
  return null;
}
