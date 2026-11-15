/**
 * A chunk's name as a reader names it (PLUGIN_GOAL 159: the hover tooltip
 * read "[[Only include results for this site](?q=okapi%20giraffe..." --
 * "we could likely add at least some headers or local semantic keyword
 * anchors ... A simple text preview or header would work best"). The same
 * rule as the sidecar's `md_title` (domvec/obsidian/sidecar.py): the first
 * line with words in it -- a link's TEXT, never its url, no image, no bare
 * url, no hex id -- with the markdown taken off. "" when no line has words.
 */
export function mdTitle(md: string, limit = 80): string {
  for (const line of String(md || "").split(/\r?\n/)) {
    let t = line.replace(/!\[[^\]]*\]\([^)]*\)/g, " ");
    t = t.replace(/\[+\(?\s*([^[\]]*?)\s*\)?\]+\(+[^)]*\)+/g, "$1");
    t = t.replace(/https?:\/\/\S+/g, " ");
    t = t.replace(/\b[0-9a-fA-F]{8,}\b/g, " ");
    t = t.replace(/<[^>]+>|`|\*\*|__|[[\]]|^\s*(#+|[-*+>]|\d+\.)\s*/g, " ");
    t = t.replace(/\s+/g, " ").replace(/^[\s|-]+|[\s|-]+$/g, "");
    if (/[\p{L}]{2,}/u.test(t)) return t.length <= limit ? t : t.slice(0, limit - 1).trimEnd() + "…";
  }
  return "";
}

/** Text made safe to place inside HTML (the library's tooltip is HTML). */
export function escapeHtml(s: string): string {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c] as string));
}
