/**
 * Pure fence-adaptive cursor, multi-cell mapping, and editing helpers (`G-447`,
 * PLUGIN_GOAL 200 e).
 *
 * Keeps every VS Code editing operation strictly inside the body lines of a
 * runnable fenced code block (`vault://<vault>/<note>#cell <k>`), returning
 * `null` on fence delimiter lines and in markdown prose so prose editing, list
 * indentation, and `[]()` retrieval gestures remain completely untouched.
 */

import { findFences, isRunnable, type Fence } from "./fences";

export interface FenceCursorContext {
  /** The active fence containing `pos`. */
  readonly fence: Fence;
  /** True when `fence` has an explicit closing fence line in `text`. */
  readonly closed: boolean;
  /** 0-based document line of `pos`. */
  readonly docLine0: number;
  /** 1-based line inside `fence.body`. */
  readonly cellLine: number;
  /** 0-based column on `docLine0`. */
  readonly col: number;
  /** True when `fence.lang` is Python (`python`, `py`, `python3`). */
  readonly isPython: boolean;
  /** All Python fences in the document, in document order. */
  readonly pyFences: Fence[];
  /** Bodies of all Python fences in the document. */
  readonly pyCells: string[];
  /** Index of `fence` in `pyFences` (-1 when non-Python). */
  readonly pyCellIndex: number;
}

export function isPythonLang(lang: string): boolean {
  const l = String(lang || "").toLowerCase();
  return l === "python" || l === "py" || l === "python3";
}

function isFenceClosed(lines: string[], fence: Fence): boolean {
  if (fence.closeLine <= fence.openLine || fence.closeLine >= lines.length) return false;
  const openMatch = /^(\s*)(`{3,}|~{3,})/.exec(lines[fence.openLine] || "");
  if (!openMatch) return false;
  const closeLineText = lines[fence.closeLine] || "";
  const closeMatch = /^(\s*)(`{3,}|~{3,})\s*$/.exec(closeLineText);
  return !!closeMatch && closeMatch[2][0] === openMatch[2][0] && closeMatch[2].length >= openMatch[2].length;
}

/** Resolve a character offset `pos` in markdown `text` to its runnable fence body context, or `null`. */
export function fenceContextAtText(text: string, pos: number): FenceCursorContext | null {
  if (pos < 0 || pos > text.length) return null;
  const lines = text.split("\n");
  // Map offset `pos` to `(docLine0, col)`.
  let rem = pos, docLine0 = 0;
  for (let i = 0; i < lines.length; i++) {
    const len = lines[i].length;
    if (rem <= len || i === lines.length - 1) {
      docLine0 = i;
      break;
    }
    rem -= len + 1;
  }
  const col = Math.max(0, Math.min(rem, lines[docLine0]?.length ?? 0));
  const allFences = findFences(text);
  const pyFences = allFences.filter((f) => isPythonLang(f.lang));
  for (const fence of allFences) {
    if (!isRunnable(fence.lang)) continue;
    const closed = isFenceClosed(lines, fence);
    const lastBodyLine = closed ? fence.closeLine - 1 : fence.closeLine;
    if (docLine0 >= fence.openLine + 1 && docLine0 <= lastBodyLine) {
      const isPython = isPythonLang(fence.lang);
      const pyCellIndex = isPython ? pyFences.indexOf(fence) : -1;
      return {
        fence,
        closed,
        docLine0,
        cellLine: docLine0 - fence.openLine,
        col,
        isPython,
        pyFences,
        pyCells: pyFences.map((pf) => pf.body),
        pyCellIndex,
      };
    }
  }
  return null;
}

/** Comment prefix for a runnable fence language. */
export function commentPrefixForLang(lang: string): string {
  const l = String(lang || "").toLowerCase();
  if (l === "javascript" || l === "js" || l === "node" || l === "typescript" || l === "ts") return "//";
  if (l === "sql" || l === "duckdb") return "--";
  return "#";
}

/** Toggle line comments over `lines` using `prefix` (`#` or `//`). */
export function toggleLinesComment(lines: string[], prefix: string): string[] {
  const nonEmpty = lines.filter((l) => l.trim().length > 0);
  if (!nonEmpty.length) return lines.map((l) => prefix + " " + l);
  const esc = prefix.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const commentedRe = new RegExp(`^(\\s*)${esc}\\s?`);
  const allCommented = nonEmpty.every((l) => commentedRe.test(l));
  if (allCommented) {
    return lines.map((l) => (l.trim().length ? l.replace(commentedRe, "$1") : l));
  }
  const minIndent = Math.min(...nonEmpty.map((l) => (l.match(/^\s*/)?.[0].length ?? 0)));
  return lines.map((l) => {
    if (!l.trim().length) return l;
    return l.slice(0, minIndent) + prefix + " " + l.slice(minIndent);
  });
}

/** Compute next line indentation after pressing Enter at `col` on `lineText`. */
export function nextLineIndent(lineText: string, col: number, lang: string): string {
  const before = lineText.slice(0, col);
  const baseIndent = before.match(/^[ \t]*/)?.[0] ?? "";
  const trimmed = before.replace(/#.*$/, "").trim();
  if (isPythonLang(lang)) {
    if (trimmed.endsWith(":")) return baseIndent + "    ";
    if (/^(return|pass|raise|break|continue)\b/.test(trimmed) && baseIndent.length >= 4) {
      return baseIndent.slice(0, baseIndent.length - 4);
    }
  } else if (/[{(\[]\s*$/.test(trimmed)) {
    return baseIndent + "    ";
  }
  return baseIndent;
}

const PY_KEYWORDS_AND_BUILTINS = new Set([
  "False", "None", "True", "and", "as", "assert", "async", "await", "break", "class",
  "continue", "def", "del", "elif", "else", "except", "finally", "for", "from", "global",
  "if", "import", "in", "is", "lambda", "nonlocal", "not", "or", "pass", "raise", "return",
  "try", "while", "with", "yield", "abs", "all", "any", "bool", "bytes", "callable", "chr",
  "dict", "dir", "divmod", "enumerate", "eval", "exec", "Exception", "filter", "float",
  "format", "frozenset", "getattr", "globals", "hasattr", "hash", "hex", "id", "input",
  "int", "isinstance", "issubclass", "iter", "len", "list", "locals", "map", "max", "min",
  "next", "object", "oct", "open", "ord", "pow", "print", "property", "range", "repr",
  "reversed", "round", "set", "setattr", "slice", "sorted", "staticmethod", "str", "sum",
  "super", "tuple", "type", "vars", "zip", "Database", "WebBrowser", "Vault", "Agent",
  "Chat", "Terminal", "Search", "search", "similar", "chunk", "page_form", "resolve",
  "focus", "unfold", "pages", "ego", "attach", "view", "types", "check", "create", "link",
  "invoke", "commit", "review",
]);

/** Fast static extraction of top-level Python `defs` and external `refs` across a note's fences (`G-448`, `G-451`). */
export function extractNotePyDefsRefs(markdownText: string): {
  defs: Set<string>;
  refs: Set<string>;
  perCell: { openLine: number; defs: Set<string>; refs: Set<string> }[];
} {
  const allDefs = new Set<string>();
  const allReads = new Set<string>();
  const perCell: { openLine: number; defs: Set<string>; refs: Set<string> }[] = [];
  for (const f of findFences(markdownText || "")) {
    if (!isPythonLang(f.lang)) continue;
    const cDefs = new Set<string>();
    const cReads = new Set<string>();
    const stripped = f.body
      .replace(/"""[\s\S]*?"""|'''[\s\S]*?'''/g, '""')
      .replace(/"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'/g, '""')
      .replace(/#.*$/gm, "");
    for (const ln of stripped.split(/\r?\n/)) {
      if (!ln.trim() || /^\s/.test(ln)) continue;
      let m: RegExpExecArray | null;
      if ((m = /^(?:async\s+)?def\s+([A-Za-z_]\w*)\s*\(/.exec(ln))) cDefs.add(m[1]);
      else if ((m = /^class\s+([A-Za-z_]\w*)\b/.exec(ln))) cDefs.add(m[1]);
      else if ((m = /^import\s+(.+)$/.exec(ln))) {
        for (const part of m[1].split(",")) {
          const asM = /^\s*([\w.]+)(?:\s+as\s+([A-Za-z_]\w*))?/.exec(part);
          if (asM) cDefs.add(asM[2] || asM[1].split(".")[0]);
        }
      } else if ((m = /^from\s+[\w.]+\s+import\s+(.+)$/.exec(ln))) {
        for (const part of m[1].replace(/[()]/g, "").split(",")) {
          const asM = /^\s*([A-Za-z_]\w*)(?:\s+as\s+([A-Za-z_]\w*))?/.exec(part);
          if (asM && asM[1] !== "*") cDefs.add(asM[2] || asM[1]);
        }
      } else if ((m = /^([A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)\s*(?::[^=]+)?=(?!=)/.exec(ln))) {
        for (const v of m[1].split(",")) {
          const nm = v.trim();
          if (nm && !nm.startsWith("_")) cDefs.add(nm);
        }
      }
    }
    // Collect non-attribute identifier reads `(?<!\.)\b[A-Za-z_]\w*\b`
    for (const tokMatch of stripped.matchAll(/(?<![.\w])([A-Za-z_]\w*)\b/g)) {
      const id = tokMatch[1];
      if (!id.startsWith("_") && !PY_KEYWORDS_AND_BUILTINS.has(id) && !cDefs.has(id)) {
        cReads.add(id);
      }
    }
    for (const d of cDefs) if (!d.startsWith("_")) allDefs.add(d);
    for (const r of cReads) allReads.add(r);
    perCell.push({ openLine: f.openLine, defs: cDefs, refs: cReads });
  }
  const extRefs = new Set<string>();
  for (const r of allReads) if (!allDefs.has(r)) extRefs.add(r);
  return { defs: allDefs, refs: extRefs, perCell };
}
