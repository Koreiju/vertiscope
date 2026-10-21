/**
 * A cell's output, stored in the note itself.
 *
 * Step 4 of `NOTEBOOK_PANEL_DESIGN` §6. §1 chose this shape over an `.ipynb`
 * sidecar and the reason is the whole architecture: output written into the `.md`
 * IS markdown the trie already holds, so `P-N5`/`P-N6` — notebooks chunked and
 * diff-updated like webpages — come free rather than needing a second ingest
 * path. A sidecar file would be two sources of truth for one document.
 *
 * The on-disk shape, immediately after the cell's closing fence:
 *
 *     ```python
 *     print(6 * 7)
 *     ```
 *     <!-- nb-output hash=<sha256> count=3 status=ok -->
 *     ````text
 *     42
 *     ````
 *     <!-- /nb-output -->
 *
 * **The markers are HTML comments, and that is load-bearing.** Verified in the
 * running app rather than assumed: Obsidian hides them in reading view while
 * rendering everything between them, so the note shows its output and not its
 * bookkeeping, and any other markdown renderer — GitHub, a PDF export — does the
 * same. That is what lets the output be ordinary note content and metadata at
 * once.
 *
 * **`hash` is the exact source, not a content-blind digest.** `CLAUDE.md` 5b:
 * `subtree_hash` folds in a normalised token multiset and answers "is this the
 * same content?"; `exact_hash` folds in the exact value and answers "does this
 * draw the same?". An output is a projection and prints values verbatim, so it
 * must key on the exact spelling — a cell whose string literal changed is a
 * different cell, and a content-blind hash would serve the old output for it.
 * `fences.cellSource` is that exact spelling, which is why both rendering paths
 * had to be made to agree on it in step 2.
 */

/** Opens a stored output. Attributes are `key=value`, space separated. */
const OPEN = /^\s*<!--\s*nb-output\s+([^>]*?)\s*-->\s*$/;
/** Closes it. */
const CLOSE = /^\s*<!--\s*\/nb-output\s*-->\s*$/;

export interface OutputBlock {
  /** 0-based line of the opening marker. */
  readonly openLine: number;
  /** 0-based line of the closing marker. */
  readonly closeLine: number;
  readonly attrs: Record<string, string>;
}

/** Parse `hash=abc count=2 status=ok` into a record. */
function parseAttrs(raw: string): Record<string, string> {
  const attrs: Record<string, string> = {};
  for (const part of raw.split(/\s+/)) {
    if (!part) continue;
    const eq = part.indexOf("=");
    if (eq <= 0) continue;
    attrs[part.slice(0, eq)] = part.slice(eq + 1).replace(/^"|"$/g, "");
  }
  return attrs;
}

/**
 * The output block that belongs to a cell closing at `afterLine`, if any.
 *
 * Found POSITIONALLY — the next non-blank line after the cell's closing fence —
 * rather than by an id stored in both places. Two reasons: an output belongs
 * immediately after its cell, which is where a reader expects to see it, and an
 * id in the marker would have to survive the reader copying a cell, at which
 * point two cells would claim one output. Position cannot be duplicated.
 */
export function outputAfter(lines: string[], afterLine: number): OutputBlock | null {
  let i = afterLine + 1;
  while (i < lines.length && lines[i].trim() === "") i++;
  if (i >= lines.length) return null;
  const open = OPEN.exec(lines[i]);
  if (!open) return null;
  for (let j = i + 1; j < lines.length; j++) {
    if (CLOSE.test(lines[j])) {
      return { openLine: i, closeLine: j, attrs: parseAttrs(open[1]) };
    }
  }
  // An opener with no closer is a truncated write or a hand-edit. Treated as
  // absent rather than as extending to the end of the note: claiming every line
  // below it would mean the next write deleted the rest of the document.
  return null;
}

/** The SHA-256 of a cell's exact source, as hex. */
export async function hashCell(source: string): Promise<string> {
  const bytes = new TextEncoder().encode(source);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0")).join("");
}

/**
 * A fence long enough to hold `body` verbatim.
 *
 * CommonMark closes a fence with at least as many backticks as opened it, so a
 * body containing ``` needs a longer one. Without this, a cell that printed a
 * markdown snippet would end its own output block early and the rest of the
 * output would land in the note as live markdown.
 */
function fenceFor(body: string): string {
  let longest = 0;
  for (const run of body.match(/`+/g) || []) longest = Math.max(longest, run.length);
  return "`".repeat(Math.max(4, longest + 1));
}

export interface CellResult {
  ok?: boolean;
  stdout?: string;
  stderr?: string;
  value?: string | null;
  error?: string;
  count?: number;
}

/**
 * What a cell's result looks like in the note.
 *
 * Everything the cell produced, in the order a reader expects it: what it
 * printed, what it complained about, then what it evaluated to. An empty result
 * is still written, as `status=ok` with no body, because the ABSENCE of an
 * output block means "never run" and a reader needs to tell that from "ran, said
 * nothing".
 */
export function renderOutput(result: CellResult, hash: string): string[] {
  const parts: string[] = [];
  if (result.stdout && result.stdout.trim()) parts.push(result.stdout.replace(/\n+$/, ""));
  if (result.stderr && result.stderr.trim()) parts.push(result.stderr.replace(/\n+$/, ""));
  if (result.error) parts.push(result.error.replace(/\n+$/, ""));
  else if (result.value) parts.push(result.value);

  const status = result.error ? "error" : "ok";
  // `format` is written even though it is always `text` today, because it is
  // the field that lets a richer format arrive without migrating every note
  // already on disk. §1's comparison cites HTML tables and plots; those are a
  // later step, and a reader of the file should be able to see that this block
  // is not claiming to be one.
  //
  // `text` is also the right DEFAULT rather than a placeholder: stdout is
  // preformatted by nature. A cell printing aligned columns must not have them
  // reflowed, and markdown would do exactly that.
  const attrs = [`hash=${hash}`, `count=${result.count ?? 0}`,
                 `status=${status}`, "format=text"];
  const head = `<!-- nb-output ${attrs.join(" ")} -->`;
  if (!parts.length) return [head, "<!-- /nb-output -->"];

  const body = parts.join("\n");
  const fence = fenceFor(body);
  return [head, `${fence}text`, ...body.split("\n"), fence, "<!-- /nb-output -->"];
}

/**
 * Put `block` after the cell closing at `closeLine`, replacing any block there.
 *
 * Returns the whole new document. Whole-document rather than a ranged edit
 * because the caller hands this to `Vault.process`, which is read-modify-write
 * under one lock — the only way to avoid losing a keystroke the reader typed
 * while the cell was running.
 */
export function withOutput(text: string, closeLine: number,
                           block: string[]): string {
  const lines = text.split("\n");
  const existing = outputAfter(lines, closeLine);
  if (existing) {
    lines.splice(existing.openLine, existing.closeLine - existing.openLine + 1,
                 ...block);
  } else {
    lines.splice(closeLine + 1, 0, ...block);
  }
  return lines.join("\n");
}

/**
 * Whether a stored output was produced by this source.
 *
 * `false` for a missing block too, which reads oddly until you ask what the
 * caller does with it: it marks an output as not-for-this-code, and an output
 * that does not exist is not for this code either.
 */
export function isStale(block: OutputBlock | null, hash: string): boolean {
  return !block || block.attrs.hash !== hash;
}
