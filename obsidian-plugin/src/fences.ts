/**
 * Where the code fences are — one rule, read by both views.
 *
 * Step 2 of `docs/NOTEBOOK_PANEL_DESIGN.md` §6: a run button per fence, in
 * reading view AND live preview. Those are two different rendering paths in
 * Obsidian and neither can serve the other, so the only thing that can be
 * shared is the answer to "where does a fence start and end".
 *
 * **This mirrors `vertiscope/vault.py`'s `_FENCE`, deliberately and by hand.**
 * The Python side parses a note into trie addresses; this side decorates the
 * same note in the editor. If the two disagreed about what a fence is, a button
 * would appear over something the trie addressed as prose, or a code block
 * would get an address and no button. So the regex below is the same rule:
 *
 *     _FENCE = re.compile(r"^(\s*)(`{3,}|~{3,})\s*(\S*)")
 *
 * and the closing rule is the same too — same fence character, at least as
 * long — which is what lets a fence contain a shorter fence. Two spellings of
 * one rule is a known defect class in this project; it is accepted here because
 * one side is Python in a backend and the other is TypeScript in a renderer,
 * and the alternative is shipping a parser over the wire to decorate a
 * textarea. The mitigation is that both are stated in one place each, and this
 * comment names the other.
 *
 * Why not `syntaxTree` from `@codemirror/language`, which is the usual answer:
 * that package is not among obsidian's peer dependencies and is absent from
 * node_modules, so using it means adding a CM6 package of our own — the exact
 * thing `esbuild.config.mjs` externalises CM6 to avoid. A text scan needs no
 * dependency and agrees with the backend by construction.
 */

/** A fence opener: indent, three-or-more backticks or tildes, an info string. */
const FENCE = /^(\s*)(`{3,}|~{3,})\s*(\S*)/;

export interface Fence {
  /** 0-based line index of the opening fence. */
  readonly openLine: number;
  /** 0-based line index of the closing fence, or the last line when unclosed. */
  readonly closeLine: number;
  /** The info string — `python`, `bash`, `` — lowercased. */
  readonly lang: string;
  /** The fence's content, without either fence line. */
  readonly body: string;
}

/**
 * Every fence in `text`, in document order.
 *
 * An unclosed fence still yields a Fence, running to the end of the document.
 * That is deliberate: a reader who has just typed ``` and is about to type the
 * code should see the button appear, not see it withheld until they close the
 * block. The backend treats an unclosed fence the same way.
 */
export function findFences(text: string): Fence[] {
  const lines = text.split("\n");
  const out: Fence[] = [];
  let i = 0;
  while (i < lines.length) {
    const open = FENCE.exec(lines[i]);
    if (!open) { i++; continue; }
    const marker = open[2];
    let j = i + 1;
    while (j < lines.length) {
      const close = FENCE.exec(lines[j]);
      if (close && close[2][0] === marker[0] && close[2].length >= marker.length) {
        break;
      }
      j++;
    }
    out.push({
      openLine: i,
      closeLine: Math.min(j, lines.length - 1),
      lang: (open[3] || "").toLowerCase(),
      body: lines.slice(i + 1, j).join("\n"),
    });
    i = j + 1;
  }
  return out;
}

/**
 * Languages a run button is offered for.
 *
 * An allow-list, not a deny-list, and the reason is what a button MEANS: it
 * says "this can be executed here". Offering one on a ```json block or on the
 * plugin's own ```vertiscope surface promises something that cannot happen, and a
 * control that does nothing is worse than an absent one — `PLUGIN_PRD` scores
 * exactly that as a phantom affordance.
 *
 * `vertiscope` is excluded by name for a second reason: that fence already renders
 * an interactive chunk surface, and a run button on it would sit inside
 * someone else's widget.
 */
const RUNNABLE = new Set([
  "python", "py", "python3",
  "bash", "sh", "shell", "zsh",
  "powershell", "pwsh", "ps1",
  "javascript", "js", "node",
  "typescript", "ts",
  "r", "julia", "ruby", "rb",
  "sql", "duckdb",
]);

export function isRunnable(lang: string): boolean {
  return RUNNABLE.has(lang.toLowerCase());
}

/**
 * One spelling of a cell's source, whichever renderer found it.
 *
 * The two paths disagree by a newline and it is not cosmetic. Reading view
 * reads `code.textContent`, which HTML serialisation ends with a newline before
 * the closing tag; the live-preview scanner joins the body lines and does not.
 * Measured: the same cell came back `"x = 1\nprint(x)\n"` through one path and
 * `"x = 1\nprint(x)"` through the other.
 *
 * Step 3 keys a cell's stored output on a digest of its source — `exact_hash`
 * semantics, per `NOTEBOOK_PANEL_DESIGN` §4, because a projection prints values
 * verbatim. Two digests for one cell means switching between reading view and
 * live preview silently invalidates the output and re-runs the cell. So the
 * normalisation belongs here, once, rather than in whichever path is noticed
 * second.
 *
 * Trailing blank lines go; interior blank lines and leading indentation stay,
 * because in Python both change what the code MEANS.
 */
export function cellSource(raw: string): string {
  return raw.replace(/\r\n/g, "\n").replace(/\n+$/, "");
}
