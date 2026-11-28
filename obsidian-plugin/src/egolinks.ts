/**
 * Cell-graph connectivity between `domvec/ego.md` and cell panels (`G-446`,
 * PLUGIN_GOAL 200 b).
 *
 * In trie terms: `vault://<vault>/domvec/ego.md` stores typed ATX sections
 * (`## Code cells`, `## Browser cells`, `## Terminal cells`, `## Chat cells`,
 * `## Markdown cells`), each holding standard internal markdown links
 * `- [title](encodeURI(relPath))` (`main.ts` `destination`, `vault.py` `_LINK`
 * -> `/section[k]/.../a[i]`, `urls.internal`, never wiki links per `G-420`).
 */

export type EgoCellHeading =
  | "Code cells"
  | "Browser cells"
  | "Terminal cells"
  | "Chat cells"
  | "Markdown cells";

const ALL_HEADINGS: readonly EgoCellHeading[] = [
  "Code cells",
  "Browser cells",
  "Terminal cells",
  "Chat cells",
  "Markdown cells",
];

const NL = "\n";

/** Normalize a vault-relative path (`\` -> `/`, strip leading `/`). */
export function normVaultPath(p: string): string {
  return String(p || "").replace(/\\/g, "/").replace(/^\/+/, "").trim();
}

/** Classify a note's text + path into its canonical ego section heading. */
export function classifyCellHeading(path: string, text: string): EgoCellHeading {
  const np = normVaultPath(path).toLowerCase();
  if (np === "domvec/browser.md" || /^domvec\/browser\s+\d+\.md$/.test(np)) return "Browser cells";
  const fmMatch = /^---\r?\n([\s\S]*?)\r?\n---/.exec(text || "");
  const fm = fmMatch ? fmMatch[1] : "";
  if (/^\s*domvec\s*:\s*terminal\s*$/m.test(fm)) return "Terminal cells";
  if (/^\s*domvec\s*:\s*chat\s*$/m.test(fm)) return "Chat cells";
  if (/^\s*(`{3,}|~{3,})\s*browser\b/im.test(text || "")) return "Browser cells";
  if (/^\s*(`{3,}|~{3,})\s*(python|py|python3|bash|sh|shell|powershell|pwsh|ps1|javascript|js|typescript|ts)\b/im.test(text || "")) {
    return "Code cells";
  }
  if (/^\s*(`{3,}|~{3,})\s*chat\b/im.test(text || "")) return "Chat cells";
  return "Markdown cells";
}

/** Extract the display title of a note (opening `# Heading`, else filename stem). */
export function titleOfNote(path: string, text?: string): string {
  if (text) {
    const body = text.replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n?/, "");
    for (const raw of body.split(/\r?\n/)) {
      const t = raw.trim();
      if (!t) continue;
      const m = /^#\s+(.+?)\s*#*$/.exec(t);
      if (m && m[1].trim()) {
        // Strip markdown link wrapper `[Psychic](...)` -> `Psychic` for display consistency.
        const unwrapped = m[1].trim().replace(/\[([^\]]+)\]\([^)]*\)/g, "$1").replace(/[\[\]]/g, "").trim();
        if (unwrapped) return unwrapped;
      }
      break;
    }
  }
  const np = normVaultPath(path);
  const base = np.slice(np.lastIndexOf("/") + 1).replace(/\.md$/i, "");
  return (base || np).replace(/[\[\]]/g, "");
}

/** Migrate deprecated `domvec: slate` notes (`slate_6 \n \t value`, PLUGIN_GOAL 201 a / G-448)
 *  to plain markdown `# <Title>` + fenced cells, preserving any real headings or fences. */
export function migrateDeprecatedSlateText(path: string, text: string): { migrated: boolean; text: string } {
  const np = normVaultPath(path);
  if (!text || np.startsWith("domvec-checks/") || np.toLowerCase() === "domvec/ego.md") {
    return { migrated: false, text };
  }
  const hasSlateFm = /^---\r?\n[\s\S]*?^\s*domvec\s*:\s*slate\s*$/m.test(text);
  const base = np.slice(np.lastIndexOf("/") + 1).replace(/\.md$/i, "");
  const slug = base.replace(/\s+/g, "_");
  const escapedSlug = slug.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const stubRe = new RegExp(`^${escapedSlug}[ \\t]*\\r?\\n\\tvalue[ \\t]*\\r?\\n?`, "im");
  if (!hasSlateFm && !stubRe.test(text)) {
    return { migrated: false, text };
  }
  let body = text.replace(/^---\r?\n([\s\S]*?)\r?\n---\r?\n?/, (_all, fm: string) => {
    const kept = fm.split(/\r?\n/).filter((l) => !/^\s*domvec\s*:\s*slate\s*$/i.test(l) && l.trim().length > 0);
    return kept.length ? `---\n${kept.join("\n")}\n---\n` : "";
  });
  body = body.replace(stubRe, "");
  const trimmed = body.trimStart();
  if (!/^#\s+\S/.test(trimmed)) {
    body = `# ${base}\n\n` + trimmed;
  }
  const clean = body.replace(/\r\n/g, "\n").replace(/\n{3,}/g, "\n\n").trimEnd() + "\n";
  return { migrated: clean !== text, text: clean };
}

/** One standard inline link `[title](encodeURI(path))` to a vault note -- what
 *  every note the plugin writes uses (G-446/G-448: never `[[wiki]]`). */
export function mdLink(path: string, title?: string): string {
  const np = normVaultPath(path);
  const t = (title || titleOfNote(np)).replace(/[\[\]\r\n]+/g, " ").replace(/\s+/g, " ").trim() || titleOfNote(np);
  return `[${t}](${encodeURI(np)})`;
}

/** Standard markdown link bullet `- [title](encodeURI(path))` (`vault.py` `_LINK`). */
export function formatEgoCellBullet(title: string, path: string): string {
  const np = normVaultPath(path);
  const cleanTitle = (title || titleOfNote(np)).replace(/[\[\]\r\n]+/g, " ").trim() || titleOfNote(np);
  return `- [${cleanTitle}](${encodeURI(np)})`;
}

/** Parse every internal `.md` markdown link `[title](target)` in `text`. */
export function parseInternalMdLinks(text: string): { title: string; path: string }[] {
  const out: { title: string; path: string }[] = [];
  const seen = new Set<string>();
  const re = /(?<!!)\[([^\]]*)\]\(([^)\s]+)\)/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text || ""))) {
    const rawTarget = m[2].trim();
    if (/^(https?:|mailto:|code:|data:|javascript:)/i.test(rawTarget)) continue;
    let decoded = rawTarget;
    try { decoded = decodeURIComponent(rawTarget.replace(/^vault:\/\/[^/]+\//i, "")); } catch { /* keep raw */ }
    decoded = normVaultPath(decoded.split("#")[0]);
    if (!decoded || !/\.md$/i.test(decoded) || seen.has(decoded.toLowerCase())) continue;
    seen.add(decoded.toLowerCase());
    out.push({ title: m[1].trim(), path: decoded });
  }
  return out;
}

function isTargetLine(line: string, wantPathLower: string): boolean {
  const m = /^\s*[-*+]\s+\[([^\]]*)\]\(([^)\s]+)\)\s*$/.exec(line);
  if (!m) return false;
  let dec = m[2];
  try { dec = decodeURIComponent(dec.replace(/^vault:\/\/[^/]+\//i, "")); } catch { /* ignore */ }
  return normVaultPath(dec.split("#")[0]).toLowerCase() === wantPathLower;
}

/** Insert or update `- [title](encodeURI(path))` under `## <heading>` in `egoText`.
 *  Preserves `# ego`, prose, the python settings block, and keeps any trailing
 *  ```` ```chat ```` block at the very foot (`G-422`). */
export function upsertEgoCellLink(egoText: string, path: string, title: string, heading: EgoCellHeading): string {
  const np = normVaultPath(path);
  if (!np || np.toLowerCase() === "domvec/ego.md") return egoText;
  const wantLower = np.toLowerCase();
  const bullet = formatEgoCellBullet(title, np);

  // Separate any trailing ```chat ... ``` block so it always remains at the foot.
  let main = (egoText || "").replace(/\r\n/g, NL);
  let tailChat = "";
  const chatMatch = /(\n*```chat[ \t]*\n[\s\S]*?```[ \t]*\s*)$/.exec(main);
  if (chatMatch) {
    tailChat = NL + NL + chatMatch[1].trim() + NL;
    main = main.slice(0, chatMatch.index);
  }

  const headRe = new RegExp(`^##\\s+${heading.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s*$`, "i");
  const curLines = main.split(NL);
  const curH = curLines.findIndex((l) => headRe.test(l.trim()));
  if (curH >= 0) {
    let curEnd = curH + 1;
    let inFence = false;
    while (curEnd < curLines.length) {
      if (/^\s*(`{3,}|~{3,})/.test(curLines[curEnd])) inFence = !inFence;
      if (!inFence && /^#{1,2}\s+/.test(curLines[curEnd])) break;
      curEnd++;
    }
    let replaced = false;
    for (let k = curH + 1; k < curEnd; k++) {
      if (isTargetLine(curLines[k], wantLower)) {
        curLines[k] = bullet;
        replaced = true;
        break;
      }
    }
    if (replaced) {
      // Remove any duplicate occurrences outside this line without reordering sections.
      const deduped = curLines.filter((l, idx) => !isTargetLine(l, wantLower) || idx === curLines.indexOf(bullet, curH + 1));
      main = pruneEmptyManagedHeadings(deduped).join(NL).replace(/\n{3,}/g, NL + NL).replace(/\s+$/, "") + NL;
      return tailChat ? main.replace(/\s+$/, "") + tailChat : main;
    }
  }

  // Otherwise remove any stale bullet for the same path under another heading so a
  // cell that gained a code/browser fence moves cleanly to its current heading.
  main = removePathFromBody(main, wantLower);

  const lines = main.split(NL);
  const hIdx = lines.findIndex((l) => headRe.test(l.trim()));

  if (hIdx >= 0) {
    let endIdx = hIdx + 1;
    let inFence = false;
    while (endIdx < lines.length) {
      if (/^\s*(`{3,}|~{3,})/.test(lines[endIdx])) inFence = !inFence;
      if (!inFence && /^#{1,2}\s+/.test(lines[endIdx])) break;
      endIdx++;
    }
    let insertAt = endIdx;
    while (insertAt > hIdx + 1 && !lines[insertAt - 1].trim()) insertAt--;
    const needBlankAfterHead = insertAt === hIdx + 1;
    const inserted = needBlankAfterHead ? ["", bullet] : [bullet];
    lines.splice(insertAt, 0, ...inserted);
    main = lines.join(NL).replace(/\s+$/, "") + NL;
  } else {
    main = main.replace(/\s+$/, "") + NL + NL + `## ${heading}` + NL + NL + bullet + NL;
  }

  return tailChat ? main.replace(/\s+$/, "") + tailChat : main;
}

function pruneEmptyManagedHeadings(kept: string[]): string[] {
  const out: string[] = [];
  let i = 0;
  while (i < kept.length) {
    const trimmed = kept[i].trim();
    const managed = ALL_HEADINGS.some((h) => trimmed.toLowerCase() === `## ${h.toLowerCase()}`);
    if (managed) {
      let j = i + 1;
      while (j < kept.length && !kept[j].trim()) j++;
      if (j >= kept.length || /^#{1,2}\s+/.test(kept[j].trim())) {
        while (out.length && !out[out.length - 1].trim()) out.pop();
        i = j;
        continue;
      }
    }
    out.push(kept[i]);
    i++;
  }
  return out;
}

function removePathFromBody(body: string, wantLower: string): string {
  const lines = body.split(NL);
  const kept = lines.filter((l) => !isTargetLine(l, wantLower));
  return pruneEmptyManagedHeadings(kept).join(NL).replace(/\n{3,}/g, NL + NL).replace(/\s+$/, "") + NL;
}

/** Remove `path` from `egoText` (and prune empty managed `## <Type> cells` sections). */
export function removeEgoCellLink(egoText: string, path: string): string {
  const np = normVaultPath(path);
  if (!np) return egoText;
  let main = (egoText || "").replace(/\r\n/g, NL);
  let tailChat = "";
  const chatMatch = /(\n*```chat[ \t]*\n[\s\S]*?```[ \t]*\s*)$/.exec(main);
  if (chatMatch) {
    tailChat = NL + NL + chatMatch[1].trim() + NL;
    main = main.slice(0, chatMatch.index);
  }
  const next = removePathFromBody(main, np.toLowerCase());
  return tailChat ? next.replace(/\s+$/, "") + tailChat : next;
}

/** Prune bullets in `egoText` whose target vault path no longer exists (`exists(path) === false`). */
export function pruneMissingEgoCellLinks(egoText: string, exists: (path: string) => boolean): { text: string; removed: string[] } {
  const removed: string[] = [];
  let cur = egoText;
  for (const link of parseInternalMdLinks(egoText)) {
    if (!exists(link.path)) {
      cur = removeEgoCellLink(cur, link.path);
      removed.push(link.path);
    }
  }
  return { text: cur, removed };
}
