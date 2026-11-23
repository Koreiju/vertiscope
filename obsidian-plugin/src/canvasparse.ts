/** The ego canvas's pure half (G-396): its note -> sections; a section -> its line. */

export const CANVAS_PATH = "domvec/ego canvas.md";
const NL = "\n";

export interface Section { path: string; embedded: boolean; line: number }

/** The canvas note's body -> its sections, in order. A line that is neither
 *  an embed nor a link is the reader's own text and is kept, never a section. */
export function sectionsOf(text: string): Section[] {
  const out: Section[] = [];
  const lines = text.split(/\r?\n/);
  let inFm = lines[0] === "---";
  for (let i = inFm ? 1 : 0; i < lines.length; i++) {
    if (inFm) { if (lines[i] === "---") inFm = false; continue; }
    const m = /^\s*(!?)\[\[([^\]|#]+)(?:[#|][^\]]*)?\]\]\s*$/.exec(lines[i]);
    if (m) out.push({ path: m[2].trim().replace(/\.md$/, "") + ".md", embedded: m[1] === "!", line: i });
  }
  return out;
}

/** A section's line, contained (`![[x]]`) or pulled out (`[[x]]`). */
export function lineFor(path: string, embedded: boolean): string {
  return (embedded ? "!" : "") + "[[" + path.replace(/\.md$/, "") + "]]";
}

