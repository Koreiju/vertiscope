/**
 * Is this document the page, or a STATE of the page? (G-249, 2026-10-18,
 * PLUGIN_GOAL 176/178: "annas archive re sets from ddos guard", "also
 * getting 502 on annas archive", "ddos guard on annas archive .pk")
 *
 * An error response (a 502) and a bot-check interstitial ("checking your
 * browser") are what the server said INSTEAD of the page. Folded and stored
 * as the url's chunks they replaced the page's real chunks in the trie -- the
 * store's version of the url became the interstitial's three lines -- and
 * when the check passed and the real page loaded, every chunk came back as
 * new: the stream started over. So such a document is a page STATE: drawn
 * in the browser as the site sent it, never stored, never streamed, and the
 * url's trie stays what it was until the real page arrives.
 *
 * Nothing here works around a check. The reader passes it (or it passes by
 * itself); this only refuses to mistake it for the page.
 *
 * Decided from what the host already has -- the main frame's HTTP status
 * and the document's title -- and, for a check that answers 200 with an
 * ordinary-looking title, from the few lines the document holds.
 */

export interface GateVerdict {
  /** Empty: the page itself. Otherwise why it is not. */
  why: string;
  kind: "" | "error" | "check";
}

const OK: GateVerdict = { why: "", kind: "" };

/** Titles bot checks give themselves. Anchored at BOTH ends: a page ABOUT
 *  DDoS-Guard ("DDoS-Guard - Wikipedia") is not one of its checks. */
const CHECK_TITLES = [
  /^ddos-guard$/i,
  /^just a moment\.{0,3}$/i,
  /^attention required!?( \| cloudflare)?$/i,
  /^checking your browser( before accessing.*)?\.{0,3}$/i,
  /^please wait\.{0,3}( \| cloudflare)?$/i,
  /^security check$/i,
  /^verifying (you are|that you are) (a )?human\.{0,3}$/i,
  /^one more step$/i,
  /^ddos protection( by [\w .-]+)?$/i,
  /^access denied$/i,
];
const ERROR_TITLES = [
  /^(4\d\d|5\d\d)\b/,                       // "502 Bad Gateway", "503 Service Unavailable"
  /\b(bad gateway|gateway time-?out|service (temporarily )?unavailable)\b/i,
  /^error (4\d\d|5\d\d)\b/i,
];
/** Lines a check page shows. Only read when the document is SMALL: a real
 *  page that mentions "checking your browser" in an article is not a check. */
const CHECK_LINES = [
  /checking your browser before accessing/i,
  /\bddos-guard\b/i,
  /verify(ing)? (you are|that you are) (a )?human/i,
  /enable javascript and cookies to continue/i,
  /this process is automatic\. your browser will redirect/i,
  /performance (&|and) security by cloudflare/i,
];
/** At most this many lines, for the line test to apply. */
export const GATE_SMALL_LINES = 40;

export function pageGate(status: number, title: string, lines: string[] = []): GateVerdict {
  const t = String(title || "").trim();
  if (CHECK_TITLES.some((re) => re.test(t))) return { why: `bot check ("${t.slice(0, 40)}")`, kind: "check" };
  if (status >= 400) {
    // 403/429/503 are what checks answer with too; the title decided above.
    return { why: `HTTP ${status}`, kind: status === 403 || status === 429 ? "check" : "error" };
  }
  if (ERROR_TITLES.some((re) => re.test(t))) return { why: `error page ("${t.slice(0, 40)}")`, kind: "error" };
  if (lines.length && lines.length <= GATE_SMALL_LINES) {
    const hit = lines.find((l) => CHECK_LINES.some((re) => re.test(l)));
    if (hit) return { why: `bot check ("${hit.trim().slice(0, 40)}")`, kind: "check" };
  }
  return OK;
}
