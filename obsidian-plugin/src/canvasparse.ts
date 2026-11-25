/**
 * The ego canvas's pure half (spec §12c, G-401): the ego slate's COMPONENT
 * fields -- `\tname\t{ref}` lines whose one `{ref}` names a note.
 *
 * The canvas is not a note of its own (item 54, "one ego"): it is the ego
 * slate `domvec/ego.md`, whose rank-1 fields are the cockpit's (`view`,
 * `throttle`, `search`, ...) AND one field per component of the tool space
 * (158), in compile order (142). A component field's brace is drawn in one of
 * mortegon's three states (UR O.1a) -- hidden, revealed inline, or resolved to
 * a panel -- and that state is FOLD state: the line itself never changes.
 */

export const EGO_PATH = "domvec/ego.md";
/** The 183 slice's separate canvas note; read once to seed the order, then retired. */
export const OLD_CANVAS_PATH = "domvec/ego canvas.md";
const NL = "\n";

export interface Field { name: string; ref: string; line: number }

/** The rank-1 fields of the slate's tree whose value is exactly one `{ref}`
 *  for which `isNote(ref)` holds -- a cockpit field like `keys {keys}` or
 *  `plan {search.results}` names no note and is not a component. */
export function componentFieldsOf(text: string, isNote: (ref: string) => boolean): Field[] {
  const out: Field[] = [];
  const lines = text.split(/\r?\n/);
  let i = 0;
  if (lines[0] === "---") { i = 1; while (i < lines.length && lines[i] !== "---") i++; i++; }
  for (; i < lines.length; i++) {
    const m = /^\t([^\t]+)\t\{([^{}]+)\}\s*$/.exec(lines[i]);
    if (m && isNote(m[2].trim())) out.push({ name: m[1].trim(), ref: m[2].trim(), line: i });
  }
  return out;
}

/** A component's field line: its name, and the brace that references it. */
export function fieldLine(name: string): string {
  return "\t" + name + "\t{" + name + "}";
}

/** The old canvas note's sections, in order (`![[x]]` or `[[x]]`), as paths. */
export function oldSectionsOf(text: string): string[] {
  const out: string[] = [];
  for (const l of text.split(/\r?\n/)) {
    const m = /^\s*!?\[\[([^\]|#]+)(?:[#|][^\]]*)?\]\]\s*$/.exec(l);
    if (m) out.push(m[1].trim().replace(/\.md$/, "") + ".md");
  }
  return out;
}

/** The slate text with component lines appended to the end of its tree. */
export function withFields(text: string, names: string[]): string {
  if (!names.length) return text;
  return text.replace(/\s*$/, "") + NL + names.map(fieldLine).join(NL) + NL;
}
