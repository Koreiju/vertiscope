/**
 * Which chunk draws which element of the page being browsed -- held HERE, in
 * the renderer, so the overlay never waits on the store (DESIGN_VII §3).
 *
 * **Why it exists.** Hover used to ask the sidecar (`/resolve`) on every new
 * element. That is one store query per ancestor level, behind a store that
 * serialises every statement: measured on the Radix tree page, 28 ms at the
 * median and **5,626 ms** at worst, while a landing capture held the store.
 * The overlay is the pipeline's fastest output and was waiting on its
 * slowest part.
 *
 * **What it holds.** The page's `Anchors`: each markdown line's own element
 * address, mapped to the 256-token chunk that draws it -- the unit hover and
 * pin show (decided 2026-09-26: *"make hover-pin the 256 limit"*). Loaded in
 * one call when the browser lands on a page, then patched from each capture
 * reply, which names the chunks that drain rewrote and their addresses --
 * O(delta), and no extra round trip.
 *
 * **Same answer as `/resolve`.** A hover resolves to the chunk anchored at the
 * nearest ancestor-or-self of the hovered element, exactly the walk the
 * sidecar does, but in memory.
 */

import { canonAddr } from "./address.ts";
import type { Sidecar } from "./sidecar";
import type { CentralDiff } from "./types";

export class ChunkMap {
  url = "";
  loadedAt = 0;
  /** element xpath -> the chunk whose line draws it */
  private byXpath = new Map<string, string>();
  /**
   * Every ANCESTOR path of an anchored address -> a chunk anchored beneath it.
   *
   * `/resolve` matches an element when an address IS it or lies BENEATH it
   * (`starts_with(xpath + "/")`), and many addresses are text nodes: a
   * heading's line is anchored at `.../h2/text()[1]`, never at the `<h2>`
   * the pointer is over. Matching exact paths only, the map missed 3 of 6
   * hovered headings on the Radix tree page that the store resolved.
   */
  private byPrefix = new Map<string, string>();
  /** chunk -> every element its lines draw, for the outline's extent */
  private byCid = new Map<string, string[]>();
  /** The page's chunks where the projector already has them, served with
   *  the map on landing (S-1): drawn at once, not through the queue. */
  nodes: any[] = [];
  /** Chunks the store held when the page was landed on: already through the
   *  transform, so never the pending diff (whether or not drawn as a node --
   *  a merge-group member is drawn through its lead). */
  stored = new Set<string>();

  get size(): number { return this.byXpath.size; }
  get chunks(): number { return this.byCid.size; }
  /** Every stored chunk this page's map draws. */
  cids(): string[] { return [...this.byCid.keys()]; }

  /**
   * The maps of the last pages left, by url (G-221, PLUGIN_GOAL 150: "going
   * back to previous pages repeats a scan entirely without efficient diff
   * updates"). Going back used to start from an EMPTY map until the store's
   * answer came: the new document's first drains arrived before it, nothing
   * could say they were already stored, and the page streamed again as new
   * (79 grey nodes on one revisit). Restored synchronously on landing, then
   * refreshed from the store as before. Planted `plantNoCache`.
   */
  private static cache = new Map<string, { byXpath: Map<string, string>; byPrefix: Map<string, string>;
    byCid: Map<string, string[]>; nodes: any[]; stored: Set<string>; at: number }>();
  static CACHE_PAGES = 8;
  static plantNoCache = false;
  cacheStats = { hits: 0, misses: 0 };

  private remember(): void {
    if (!this.url || !this.loadedAt) return;
    ChunkMap.cache.delete(this.url);
    ChunkMap.cache.set(this.url, { byXpath: new Map(this.byXpath), byPrefix: new Map(this.byPrefix),
      byCid: new Map(this.byCid), nodes: this.nodes.slice(), stored: new Set(this.stored), at: this.loadedAt });
    while (ChunkMap.cache.size > ChunkMap.CACHE_PAGES) ChunkMap.cache.delete(ChunkMap.cache.keys().next().value as string);
  }

  /** Replace the map with the store's for `url`: one call, on landing. */
  async load(sidecar: Sidecar, url: string): Promise<boolean> {
    if (this.url !== url) this.remember();
    // The map is THIS page's from the moment the page is landed on, even
    // when the store has nothing for it yet. It used to keep the previous
    // page's map on a page the store did not hold -- and since a capture
    // only patches the map for its own url, a new page's map stayed empty
    // for as long as it was open: no hover outline, no coverage for the
    // force tree's pending diff (2026-09-26).
    this.url = url;
    this.byXpath.clear();
    this.byPrefix.clear();
    this.byCid.clear();
    this.nodes = [];
    this.stored = new Set();
    const hit = ChunkMap.plantNoCache ? undefined : ChunkMap.cache.get(url);
    if (hit) {
      this.byXpath = new Map(hit.byXpath); this.byPrefix = new Map(hit.byPrefix); this.byCid = new Map(hit.byCid);
      this.nodes = hit.nodes.slice(); this.stored = new Set(hit.stored); this.loadedAt = hit.at;
      this.cacheStats.hits++;
    } else this.cacheStats.misses++;
    const got: any = await sidecar.pageMap(url).catch(() => null);
    if (this.url !== url) return false;          // the reader moved on
    if (!got || !got.chunks) return !!hit;
    this.byXpath.clear(); this.byPrefix.clear(); this.byCid.clear();
    this.apply(got.chunks);
    this.stored = new Set(Object.keys(got.chunks));
    this.nodes = Array.isArray(got.nodes) ? got.nodes : [];
    this.loadedAt = Date.now();
    return true;
  }

  /** True while applying a capture's delta (not the landing load): newer
   *  chunks then take ancestor paths from older ones. */
  private fresh = false;

  /** Patch from a capture reply: each named chunk's addresses, replaced. */
  patch(delta: Record<string, string[]> | null | undefined): void {
    this.fresh = true;
    try { this.apply(delta); } finally { this.fresh = false; }
  }

  apply(delta: Record<string, string[]> | null | undefined): void {
    if (!delta) return;
    for (const [cid, raw] of Object.entries(delta)) {
      // One spelling for every address held here (`canonAddr`).
      const xpaths = (raw || []).map(canonAddr);
      for (const old of this.byCid.get(cid) || []) {
        if (this.byXpath.get(old) === cid) this.byXpath.delete(old);
      }
      if (!xpaths || !xpaths.length) { this.byCid.delete(cid); continue; }
      this.byCid.set(cid, xpaths.slice());
      // The chunk's ROOT: the longest element path all its addresses share.
      // A newer chunk takes over paths at or below it -- never the ancestors
      // above, or one chunk claims the page (a capture with a stale sensor
      // dictionary wrote a chunk rooted at /html/*[..'?'][1], and with
      // "newest wins" everywhere every hover on the page resolved to it).
      let root = xpaths[0] || "";
      for (const x of xpaths) {
        let k = 0;
        while (k < root.length && k < x.length && root[k] === x[k]) k++;
        root = root.slice(0, k);
      }
      root = root.slice(0, root.lastIndexOf("/") + 1 || root.length);
      for (const x of xpaths) {
        // A re-partition names NEW chunks for addresses an older chunk held,
        // and never names the old one (it is retired, not rewritten). The
        // newer chunk takes the address from it, or hover kept resolving to
        // the retired chunk and outlining its partial extent (G-79 drew 2 of
        // 4 same-chunk pairs as one box after the chunker changed).
        const prev = this.byXpath.get(x);
        if (prev && prev !== cid) {
          const left = (this.byCid.get(prev) || []).filter((y) => y !== x);
          if (left.length) this.byCid.set(prev, left); else this.byCid.delete(prev);
        }
        this.byXpath.set(x, cid);
        // Each ancestor path, so an element resolves to a chunk anchored
        // beneath it. On a live page the LATEST chunk to claim a path under
        // it wins -- the earlier rule (first seen keeps it) held retired
        // chunks' prefixes forever.
        let cut = x.lastIndexOf("/");
        while (cut > 0) {
          const up = x.slice(0, cut);
          const held = this.byPrefix.get(up);
          const below = up.length + 1 >= root.length && (up + "/").startsWith(root);
          if (!held || !this.byCid.has(held) || (this.fresh && below)) this.byPrefix.set(up, cid);
          cut = up.lastIndexOf("/");
        }
      }
    }
  }

  /**
   * The central diff's retirements and renames, applied to this map.
   *
   * The store's patricia trie dropped `retired` cids and gave `renamed`
   * content a new cid; this map is a projection of the same trie keyed on the
   * same cid, so it makes the same two moves rather than keep a chunk the
   * store no longer has (which hover would keep resolving to). Run AFTER
   * `patch`: the capture's `map_delta` already names a renamed chunk's new
   * addresses, and a retired cid's entries are dropped only where it still
   * owns them (a newer chunk that took the address keeps it). O(delta): only
   * the retired chunks' own addresses and their ancestor paths are visited.
   */
  applyDiff(diff: CentralDiff | null | undefined): { dropped: number; renamed: number } {
    const out = { dropped: 0, renamed: 0 };
    if (!diff || diff.url !== this.url) return out;
    const renamed = diff.renamed || {};
    const goneNow = new Set<string>();
    for (const old of diff.retired || []) {
      const to = renamed[old];
      const xs = this.byCid.get(old) || [];
      if (to && !this.byCid.has(to) && xs.length) {
        // The new cid has no addresses of its own yet: it inherits the old
        // chunk's (same content, shifted index).
        this.byCid.set(to, xs.slice());
        for (const x of xs) {
          if (this.byXpath.get(x) === old) this.byXpath.set(x, to);
          let cut = x.lastIndexOf("/");
          while (cut > 0) {
            const up = x.slice(0, cut);
            if (this.byPrefix.get(up) === old) this.byPrefix.set(up, to);
            cut = up.lastIndexOf("/");
          }
        }
        this.byCid.delete(old);
        if (this.stored.delete(old)) this.stored.add(to);
        out.renamed++;
        continue;
      }
      for (const x of xs) {
        if (this.byXpath.get(x) === old) this.byXpath.delete(x);
        let cut = x.lastIndexOf("/");
        while (cut > 0) {
          const up = x.slice(0, cut);
          if (this.byPrefix.get(up) === old) this.byPrefix.delete(up);
          cut = up.lastIndexOf("/");
        }
      }
      if (this.byCid.delete(old)) out.dropped++;
      this.stored.delete(old);
      goneNow.add(old);
    }
    if (goneNow.size) this.nodes = this.nodes.filter((n: any) => !goneNow.has(n?.cid));
    return out;
  }

  /**
   * The chunk drawing the hovered element: the nearest mapped entry of its
   * ancestor chain, leaf first. Returns how many levels it walked, as
   * `/resolve` reports `ancestors_walked`.
   */
  lookup(chain: string[]): { cid: string; matched: string; walked: number } | null {
    chain = chain.map(canonAddr);
    for (let i = 0; i < chain.length; i++) {
      // The element itself anchored, else something anchored beneath it --
      // the two cases `/resolve` accepts, in its order.
      const cid = this.byXpath.get(chain[i]) || this.byPrefix.get(chain[i]);
      if (cid) return { cid, matched: chain[i], walked: i };
    }
    return null;
  }

  /** Every element a chunk's lines draw. */
  xpaths(cid: string): string[] {
    return this.byCid.get(cid) || [];
  }
}
