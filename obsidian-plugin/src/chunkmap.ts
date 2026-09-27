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

import type { Sidecar } from "./sidecar";

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

  /** Replace the map with the store's for `url`: one call, on landing. */
  async load(sidecar: Sidecar, url: string): Promise<boolean> {
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
    const got: any = await sidecar.pageMap(url).catch(() => null);
    if (this.url !== url) return false;          // the reader moved on
    if (!got || !got.chunks) return false;
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
    for (const [cid, xpaths] of Object.entries(delta)) {
      for (const old of this.byCid.get(cid) || []) {
        if (this.byXpath.get(old) === cid) this.byXpath.delete(old);
      }
      if (!xpaths || !xpaths.length) { this.byCid.delete(cid); continue; }
      this.byCid.set(cid, xpaths.slice());
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
          if (!held || !this.byCid.has(held) || this.fresh) this.byPrefix.set(up, cid);
          cut = up.lastIndexOf("/");
        }
      }
    }
  }

  /**
   * The chunk drawing the hovered element: the nearest mapped entry of its
   * ancestor chain, leaf first. Returns how many levels it walked, as
   * `/resolve` reports `ancestors_walked`.
   */
  lookup(chain: string[]): { cid: string; matched: string; walked: number } | null {
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
