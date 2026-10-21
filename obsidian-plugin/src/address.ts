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

/**
 * One spelling for an element's address. The store and the stream address a
 * SLOTTED element through its host's shadow root and slot
 * (`.../router-slot/#shadow-root/slot/home-page/...`, the composed path);
 * the page's hover reports its light-DOM path (`.../router-slot/home-page/...`).
 * Compared as-is, neither was a prefix of the other: every archive.org tile
 * missed its own chunk and climbed 16 steps to `router-slot`, opening the
 * page's header or its hidden feedback survey (2026-10-17). The slot step
 * is dropped; the light path is also what a walk through `.shadowRoot`
 * resolves on the page.
 */
export function canonAddr(a: string): string {
  if ((globalThis as any).__vertiscopePlantNoCanon) return String(a || "");   // planted: two spellings, as before
  return String(a || "").replace(/\/#shadow-root\/slot(\[\d+\])?(?=\/|$)/g, "");
}

/**
 * Does the line at `addr` belong to the unit at `at`? Inside it -- or on an
 * ANCHOR that wraps it: a link is the whole of what it wraps, so a unit chosen
 * inside one (archive.org's tile body, below its `<a href=/details/…>`) still
 * carries the href (2026-10-18, PLUGIN_GOAL 171: "empty links on some
 * archive nodes"). Only anchors: an ancestor's loose text is not the unit's.
 * Planted `__vertiscopePlantNoWrapLink`: inside only.
 */
export function inUnit(addr: string, at: string): boolean {
  if (addr === at || addr.startsWith(at + "/")) return true;
  if ((globalThis as any).__vertiscopePlantNoWrapLink) return false;
  return at.startsWith(addr + "/") && /\/a(\[\d+\])?$/.test(addr);
}

/** A payload line's element address: its `key` is `url|xpath|...`. */
export function lineAddr(line: any): string {
  const k = String((line && line.key) || "");
  const parts = k.split("|");
  return parts.length > 1 ? canonAddr(parts[1]) : "";
}

/**
 * The UNIT a hovered element stands in, within one chunk's lines: its nearest
 * ancestor holding at least `min` of them (and no more than `max`, past which
 * it is a container) -- a tile, not the grid. Returns that ancestor's address
 * and its lines, or null when the element is not inside the chunk
 * (archive.org, 2026-10-17: one stored chunk held five tiles and every tile
 * opened the first; "hovering over vhs vault inbox does not display the
 * correct shadow chunk").
 */
export function unitOf(lines: any[], element: string, min = 3, max = 60): { at: string; lines: any[] } | null {
  if (!element || !lines || !lines.length) return null;
  const addrs = lines.map(lineAddr);
  if (!addrs.some(Boolean)) return null;
  let at = canonAddr(element);
  while (at && at.length > 1) {
    const pick: any[] = lines.filter((_l, i) => addrs[i] && inUnit(addrs[i], at));
    if (pick.length > max) return null;
    if (pick.length >= Math.min(min, lines.length)) {
      // A SUB-COMPONENT is not the unit; the item it is part of is (G-251).
      // Three lines are reached inside one bandcamp track row -- its title,
      // "from", "by" -- and the row's image and its title opened two panels
      // (2026-10-18: "hovering over sub-components of the same overall chunk
      // only renders those components"). On up while the level above is not
      // a list, holds no more than `max`, and the chunk is not yet whole.
      // Planted `__vertiscopePlantSubUnit`: the first level with `min`, as before.
      if (!(globalThis as any).__vertiscopePlantSubUnit) {
        // Levels that add no line are passed through, not taken; a LINK
        // ends the climb below it (its href joins by `inUnit`).
        const A = addrs.filter(Boolean) as string[];
        let cur = at;
        while (pick.length < lines.length) {
          const c = cur.lastIndexOf("/"), up = c > 0 ? cur.slice(0, c) : "";
          if (!up || /\/a(\[\d+\])?$/.test(up) || isListAbove(up, A)) break;
          const p2 = lines.filter((_l, i) => addrs[i] && inUnit(addrs[i], up));
          if (p2.length > max) break;
          cur = up;
          if (p2.length > pick.length) { at = up; pick.splice(0, pick.length, ...p2); }
        }
      }
      // An item of a list that FITS is not the unit; the list is (see
      // `ForceTree.chunkForElement`). Planted `__vertiscopePlantItemAlways`.
      const cut0 = at.lastIndexOf("/"), up0 = cut0 > 0 ? at.slice(0, cut0) : "";
      const itemAt = up0 && at.slice(0, at.indexOf("/", up0.length + 1) > 0 ? at.indexOf("/", up0.length + 1) : at.length);
      if (up0 && !(globalThis as any).__vertiscopePlantItemAlways && isListAbove(up0, addrs.filter(Boolean))
          && isProseItem(itemAt, addrs.filter(Boolean) as string[])
          && addrs.filter((a) => a && (a === up0 || a.startsWith(up0 + "/"))).length <= max) { at = up0; continue; }
      return { at, lines: pick };
    }
    // A level holding a code block is a whole unit (G-233).
    if (pick.length && addrs.some((a, i) => pick.includes(lines[i]) && /\/pre(\[\d+\])?$/.test(a))) return { at, lines: pick };
    const cut = at.lastIndexOf("/");
    if (cut <= 0) break;
    const up = at.slice(0, cut);
    // Below a list the item is the unit -- unless the whole list fits in one
    // (a prose list is one panel, PLUGIN_GOAL 173). Planted
    // `__vertiscopePlantItemAlways`.
    const listLines = addrs.filter((a) => a && (a === up || a.startsWith(up + "/"))).length;
    if (pick.length && isListAbove(up, addrs.filter(Boolean))
        && ((globalThis as any).__vertiscopePlantItemAlways || listLines > max)) return { at, lines: pick };
    at = up;
  }
  return null;
}

/**
 * Is `item` a PROSE bullet -- an `li` whose lines are all inline (text, code,
 * links, emphasis) -- rather than a TILE (an `article`, or an item holding
 * images, headings, blocks)? Only a prose bullet joins its whole list as one
 * unit (G-244): archive.org's tiles are a list too, and each stays its own
 * panel (G-220).
 */
const INLINE_STEP = /^(text\(\)|#text|code|a|em|strong|b|i|span|kbd|samp|var|sub|sup|mark|small|abbr|q|cite|br|tt|del|ins|s|u)(\[\d+\])?$/;
export function isProseItem(item: string, under: string[]): boolean {
  const last = item.slice(item.lastIndexOf("/") + 1);
  if (!/^li(\[\d+\])?$/.test(last)) return false;
  for (const a of under) {
    if (a === item) continue;
    if (!a.startsWith(item + "/")) continue;
    for (const step of a.slice(item.length + 1).split("/")) if (step && !INLINE_STEP.test(step)) return false;
  }
  return true;
}

/**
 * Is `parent` a LIST at this point -- do the addresses under it branch into
 * two or more indexed siblings of one kind (`article[19]`, `article[20]`)?
 * A unit search climbing from an item stops below a list: past it, the
 * lines are other items' (a tile whose own lines had not all streamed yet
 * climbed into the grid and showed a neighbour, 2026-10-17).
 */
export function isListAbove(parent: string, addrs: string[]): boolean {
  const kinds = new Map<string, Set<string>>();
  for (const a of addrs) {
    if (!a.startsWith(parent + "/")) continue;
    const step = a.slice(parent.length + 1).split("/")[0];
    const m = /^([^\[]+)\[(\d+)\]$/.exec(step);
    if (!m) continue;
    const set = kinds.get(m[1]) || new Set<string>();
    set.add(m[2]);
    kinds.set(m[1], set);
  }
  for (const set of kinds.values()) if (set.size >= 2) return true;
  return false;
}
