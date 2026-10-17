/**
 * What the browser cell's address bar was given: a place to go, or words to
 * search (G-202, 2026-10-17: "please default natural-text inputs to the
 * web-browser url bar as duckduckgo search inputs (no need to scroll)").
 *
 * A place is anything with a scheme (`https:`, `about:`, `file:`), or one
 * token that reads as a host: a dot-separated name with a letter-only last
 * label (`arxiv.org`, `en.wikipedia.org/wiki/Trie`), `localhost`, or an IPv4
 * address, each with an optional port and path. Everything else -- spaces,
 * a bare word, a question -- is a DuckDuckGo search, opened as a page: the
 * results stream into the store like any page, and nothing scrolls or
 * presses "More results" on the reader's behalf.
 */
export function addressTarget(text: string): { url: string; search: boolean } {
  const t = String(text || "").trim();
  if (!t) return { url: "", search: false };
  // A scheme, but not `host:port` (`localhost:8788` is a place, not a scheme).
  if (/^[a-z][a-z0-9+.-]*:(?!\d)/i.test(t) && !/\s/.test(t)) return { url: t, search: false };
  const host = /^(localhost|\d{1,3}(\.\d{1,3}){3}|([a-z0-9-]+\.)+[a-z]{2,})(:\d+)?([/?#]\S*)?$/i;
  // A machine on this one (a dev server, the sidecar) is plain http.
  const local = /^(localhost|\d{1,3}(\.\d{1,3}){3})([:/?#]|$)/i.test(t);
  if (!/\s/.test(t) && host.test(t)) return { url: (local ? "http://" : "https://") + t, search: false };
  return { url: "https://duckduckgo.com/?q=" + encodeURIComponent(t) + "&ia=web", search: true };
}
