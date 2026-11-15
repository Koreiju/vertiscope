/**
 * A note's own recursion, unfolded one rank at a time (PLUGIN_GOAL 159).
 *
 * "the navigation on cell hierarchies and unfolding on black box structures
 * still needs to be extended for the general compilation case ... any
 * recursive structures that we have already in our database for code,
 * markdowns, etc, but also including the notebook cells themselves as ego
 * states." A note's recursion is its headings (the trie addresses a heading as
 * the section holding what follows it) and its cells; a cell's is its inputs
 * (the fence's `{ref}`s), its top-level names, its definitions and its output.
 * Each rank names the next as a `{ref}` in Obsidian's own link grammar --
 * `{Note#Heading#Sub}`, `{Note#cell 2}`, `{Note#cell 2#f}` -- so the slate's
 * right-click opens it in place, beneath the line that named it.
 *
 * MIRRORS `domvec/obsidian/refs.py` `outline` BY HAND (the sidecar unfolds a
 * stored page or a note it reads; this unfolds a vault note from its own
 * text). Both are scored against ONE fixture,
 * `tests/fixtures/outline_note.md` -> `outline_expected.json`.
 */

const HEAD = /^(#{1,6})\s+(.+?)\s*#*\s*$/;
const CELL = /^cell\s+(\d+)$/i;
const FENCE = /^(\s*)(`{3,}|~{3,})\s*(\S*)(.*)$/;
const OUT_OPEN = /^\s*<!--\s*nb-output\s+([^>]*?)\s*-->\s*$/;
const OUT_CLOSE = /^\s*<!--\s*\/nb-output\s*-->\s*$/;
const DEF = /^(\s*)(async\s+def|def|class)\s+(\w+)/;
const IMPORT = /^(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))/;
const ASSIGN = /^([A-Za-z_]\w*)\s*(?::[^=]+)?=(?!=)/;
const PY = new Set(["python", "py", "python3", ""]);
const TAB = "\t";

interface Cell { n: number; open: number; close: number; lang: string; body: string[]; refs: string[]; out: string[] | null }
type Head = [number, number, string];

/** A heading as an address segment: what would split or close a ref goes. */
export function cleanHeading(h: string): string {
  return h.replace(/[#{}\[\]|^]/g, " ").replace(/\s+/g, " ").trim();
}
/** Code and output shown, not addressed: a brace would read as a `{ref}`. */
const braces = (t: string) => t.replace(/\{/g, "｛").replace(/\}/g, "｝");
const cap = (out: string[], limit: number) =>
  out.length <= limit ? out : [...out.slice(0, limit - 1), `(+${out.length - limit + 1} more)`];
const indent = (l: string) => l.length - l.trimStart().length;
/** Python's `str.strip()` set is whitespace; JS `trim()` agrees for these. */
const lstripChars = (t: string, chars: string) => { let i = 0; while (i < t.length && chars.includes(t[i])) i++; return t.slice(i); };

function body(text: string): string[] {
  let b = (text || "").replace(/\r/g, "");
  if (b.startsWith("---")) { const e = b.indexOf("\n---", 3); if (e >= 0) b = b.slice(e + 4); }
  return b.split("\n");
}

function scan(lines: string[]): { cells: Cell[]; heads: Head[]; skip: Map<number, Cell | "out"> } {
  const cells: Cell[] = [], heads: Head[] = [], skip = new Map<number, Cell | "out">();
  const n = lines.length;
  let i = 0;
  while (i < n) {
    const f = FENCE.exec(lines[i]);
    if (f) {
      const marker = f[2];
      let j = i + 1;
      while (j < n) {
        const c = FENCE.exec(lines[j]);
        if (c && c[2][0] === marker[0] && c[2].length >= marker.length) break;
        j++;
      }
      const close = Math.min(j, n - 1);
      const cell: Cell = { n: cells.length + 1, open: i, close, lang: (f[3] || "").toLowerCase(), body: lines.slice(i + 1, j), out: null,
                           refs: [...(f[4] || "").matchAll(/\{([^{}]+)\}/g)].map((m) => m[1].trim()).filter(Boolean) };
      for (let k = i; k <= close; k++) skip.set(k, cell);
      cells.push(cell);
      i = close + 1;
      // Its output (`outputs.ts`): the next non-blank line opens a marker with a closer.
      let k = i;
      while (k < n && !lines[k].trim()) k++;
      if (k < n && OUT_OPEN.test(lines[k])) {
        let z = -1;
        for (let q = k + 1; q < n; q++) if (OUT_CLOSE.test(lines[q])) { z = q; break; }
        if (z >= 0) {
          cell.out = lines.slice(k + 1, z);
          for (let q = k; q <= z; q++) skip.set(q, "out");
          i = z + 1;
        }
      }
      continue;
    }
    const h = HEAD.exec(lines[i]);
    if (h && cleanHeading(h[2])) heads.push([i, h[1].length, cleanHeading(h[2])]);
    i++;
  }
  return { cells, heads, skip };
}

function section(lines: string[], heads: Head[], skip: Map<number, Cell | "out">, lo: number, hi: number,
                 base: string, prefix: string, limit: number): string[] {
  const hs = heads.filter((h) => lo <= h[0] && h[0] < hi);
  const level = hs.length ? Math.min(...hs.map((h) => h[1])) : 0;
  const tops = hs.filter((h) => h[1] === level);
  const first = tops.length ? tops[0][0] : hi;
  const leadCap = tops.length ? 3 : limit + 1;
  const out: string[] = [];
  let k = lo;
  while (k < first && out.length < leadCap) {
    const c = skip.get(k);
    if (c && c !== "out") {
      out.push(`cell ${c.n}${c.lang ? " " + c.lang : ""}${TAB}{${base}#cell ${c.n}}`);
      k = c.close + 1;
      continue;
    }
    const t = lines[k].trim();
    if (c === undefined && t && !/^(<!--|\||---)/.test(t)) out.push(lstripChars(t, "#> ").replace(/\t/g, " ").slice(0, 120));
    k++;
  }
  for (const [, , text] of tops) out.push(`${text}${TAB}{${prefix}#${text}}`);
  return cap(out, limit);
}

function cellLines(c: Cell, prefix: string, rest: string[], limit: number): string[] | null {
  let out: string[] = rest.length ? [] : c.refs.map((r) => `input${TAB}{${r}}`);
  let code = c.body.slice();
  const py = PY.has(c.lang);
  for (const name of rest) {
    if (!py) return null;
    const nb = code.filter((l) => l.trim());
    const base = nb.length ? Math.min(...nb.map(indent)) : 0;
    const hit = code.findIndex((l) => { const m = DEF.exec(l); return !!m && m[1].length === base && m[3] === name; });
    if (hit < 0) return null;
    let b: string[] = [];
    for (const l of code.slice(hit + 1)) { if (l.trim() && indent(l) <= base) break; b.push(l); }
    out = ["signature" + TAB + braces(code[hit].trim().replace(/:+$/, "")).slice(0, 120)];
    const k = b.findIndex((l) => l.trim());
    if (k >= 0 && ['"""', "'''"].includes(b[k].trim().slice(0, 3))) {
      const first = b[k].trim();
      const doc = first.slice(3).split(first.slice(0, 3))[0].trim();
      if (doc) out.push("doc" + TAB + braces(doc).slice(0, 120));
      b = [...b.slice(0, k), ...b.slice(k + 1)];
    }
    code = b; prefix = prefix + "#" + name;
  }
  const nb = code.filter((l) => l.trim());
  const base = nb.length ? Math.min(...nb.map(indent)) : 0;
  let rows: string[] = [];
  if (py) {
    for (const l of code) {
      if (!l.trim() || indent(l) !== base) continue;
      const s = l.trim();
      const m = IMPORT.exec(s);
      if (m && !rest.length) { rows.push("import" + TAB + (m[1] || m[2])); continue; }
      const d = DEF.exec(s);
      if (d) { rows.push(`${d[2] === "class" ? "class" : "def"} ${d[3]}${TAB}{${prefix}#${d[3]}}`); continue; }
      // A cell's top-level names are what it hands the cells after it.
      const a = ASSIGN.exec(s);
      if (a && !rest.length) rows.push("var" + TAB + a[1]);
    }
  }
  if (!rows.length) rows = nb.map((l) => braces(l.slice(base).trimEnd().replace(/\t/g, "    ")).slice(0, 120)).slice(0, 6);
  out.push(...rows);
  if (!rest.length && c.out !== null) {
    const shown = c.out.find((l) => l.trim() && !FENCE.test(l))?.trim() || "";
    out.push("output" + TAB + braces(shown).slice(0, 120));
  }
  return cap(out, limit);
}

/** The rank-1 lines of `name` -- `Note`, `Note#Heading#Sub`, `Note#cell N`,
 *  `Note#cell N#def` -- in `text`, Note's own text. null: the address names
 *  nothing in it (a heading or a cell that is not there). */
export function outline(text: string, name: string, limit = 12): string[] | null {
  const lines = body(text);
  const { cells, heads, skip } = scan(lines);
  const [base, ...segs] = (name || "").split("#").map((s) => s.trim());
  let lo = 0, hi = lines.length, prefix = base;
  for (let i = 0; i < segs.length; i++) {
    const m = CELL.exec(segs[i]);
    if (m) {
      const n = parseInt(m[1], 10);
      if (!(n >= 1 && n <= cells.length)) return null;
      return cellLines(cells[n - 1], `${base}#cell ${n}`, segs.slice(i + 1), limit);
    }
    const hs = heads.filter((h) => lo <= h[0] && h[0] < hi);
    const level = hs.length ? Math.min(...hs.map((h) => h[1])) : 0;
    const want = cleanHeading(segs[i]).toLowerCase();
    // The rank below first; then any deeper heading by that name, as an
    // Obsidian link skips levels (`Note#Insert` for `# Building / ## Insert`).
    const hit = hs.find((h) => h[1] === level && h[2].toLowerCase() === want) || hs.find((h) => h[2].toLowerCase() === want);
    if (!hit) return null;
    const end = hs.find((h) => h[0] > hit[0] && h[1] <= hit[1])?.[0] ?? hi;
    lo = hit[0] + 1; hi = end; prefix = prefix + "#" + hit[2];
  }
  return section(lines, heads, skip, lo, hi, base, prefix, limit);
}

// ---- the ego's unfolded boxes, kept in its own note -------------------------
//
// "That way we can track persisting instances of the ego's current setting
// alongside the game state" (PLUGIN_GOAL 159). The cockpit note
// (`domvec/ego.md`) IS the game state -- view, camera, throttle, keys, plan,
// play, search. Which boxes the ego holds open, in which note, is one more
// field of it, so it is read, synced and versioned with the rest instead of
// living in this browser's localStorage alone:
//
//     ego
//         ...
//         unfolded
//             notes/Radix	{Radix#cell 2} {Radix#Building}

/** `unfolded`'s rows: note path (no `.md`) -> the refs revealed in it. */
export function unfoldedOf(text: string): Map<string, string[]> {
  const out = new Map<string, string[]>();
  const lines = (text || "").replace(/\r/g, "").split("\n");
  const at = lines.findIndex((l) => /^\tunfolded\s*$/.test(l));
  if (at < 0) return out;
  for (let i = at + 1; i < lines.length && lines[i].startsWith("\t\t"); i++) {
    const m = /^\t\t(.+?)(?:\t+| {2,})(.*)$/.exec(lines[i]);
    if (!m) continue;
    const names = [...m[2].matchAll(/\{([^{}]+)\}/g)].map((x) => x[1].trim()).filter(Boolean);
    if (names.length) out.set(m[1].trim(), names);
  }
  return out;
}

/** `text` with `unfolded`'s rows for these notes replaced (an empty list
 *  removes the row). The field is made once, after `play` (else before
 *  `search`, else at the end), and only the field's own rows are touched. */
export function withUnfolded(text: string, updates: Map<string, string[]>): string {
  const crlf = /\r\n/.test(text || "");
  const lines = (text || "").replace(/\r/g, "").split("\n");
  let at = lines.findIndex((l) => /^\tunfolded\s*$/.test(l));
  if (at < 0) {
    const play = lines.findIndex((l) => /^\tplay(\t|\s*$)/.test(l));
    const search = lines.findIndex((l) => /^\tsearch\s*$/.test(l));
    at = play >= 0 ? play + 1 : search >= 0 ? search : lines.length;
    if (at === lines.length && lines.length && lines[lines.length - 1] === "") at--;
    lines.splice(at, 0, "\tunfolded");
  }
  let end = at + 1;
  while (end < lines.length && lines[end].startsWith("\t\t")) end++;
  const rows = unfoldedOf(lines.slice(at, end).join("\n"));
  for (const [k, v] of updates) { if (v.length) rows.set(k, v); else rows.delete(k); }
  const next = [...rows].map(([k, v]) => `\t\t${k}\t${v.map((n) => `{${n}}`).join(" ")}`);
  lines.splice(at + 1, end - at - 1, ...next);
  const out = lines.join("\n");
  return crlf ? out.replace(/\n/g, "\r\n") : out;
}
