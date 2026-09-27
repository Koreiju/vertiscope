/**
 * The page's chunk tree, built in the RENDERER from the drain itself (`G-89`).
 *
 * 2026-09-26: the first scans draw *"with a full force-directed layout"*,
 * *"straight from the electron's recursive mutationobserver shadow DOM
 * chunking basically prior to vectorization and projection/fitting over
 * UMAP"* -- and force-directed is *"a first and primary representation"*.
 *
 * So this reads nothing but the payload the sensor's `drain()` hands the
 * browser cell: no sidecar round trip, no store, no embedding. Each sensor
 * chunk arrives with its lines, and each line with its interned path; the
 * chunk's ADDRESS is the longest common element path of its lines, and its
 * PARENT is the nearest other chunk whose address encloses it -- else the
 * page. One parent per node, so the tree is the patricia tree's shape, not a
 * graph. A drain updates it by its delta: the chunks it emitted are upserted,
 * the ids it names removed are dropped, and only nodes whose parent could
 * have changed (those under an address that came or went) are re-parented.
 *
 * Decoding mirrors `Sensing._xpath` for the transport the cell asks for
 * (`variants: {}`: interned segments, nothing else), and stops being
 * trusted -- `decoded: false` -- the moment a payload reports anything else.
 */

export interface ForceNodeDelta {
  url: string;
  /** Nodes that are new: the page's own on the first drain, then chunks.
   *  `again` marks a chunk the tree already held whose content changed --
   *  pending once more, since its new content has not been transformed. */
  added: { id: string; parent: string; title: string; lines: number; again?: boolean }[];
  /** Node ids gone. */
  removed: string[];
  /** Existing nodes whose parent changed (a chunk arrived or left above them). */
  reparented: { id: string; parent: string }[];
  /** Chunks the tree holds for this page after the drain. */
  size: number;
  /** ms spent here, for the phase contract's per-drain budget. */
  ms: number;
  /** The element addresses of the chunks this drain added or rewrote --
   *  what the browser outlines as the diff (`G-90`). */
  addresses: string[];
  /** `performance.now()` when the drain came back from the page: the one
   *  instant both the overlay and the 3D graph are timed from (`G-90`). */
  t0: number;
  /** The drain's profile trace, so both timings land on it. */
  trace: string;
  /** Node id -> the stored chunk that already draws its content, from the
   *  browser's chunk map; absent when nothing stored covers it yet. */
  covers: Record<string, string>;
  /** Node ids whose covering chunk the store held before this visit. */
  settled: string[];
}

interface Held {
  id: string; address: string; title: string; lines: number; parent: string; digest: number;
}

const SHADOW = "#shadow-root";

export class ForceTree {
  readonly url: string;
  private dict: string[] = [];
  private chunks = new Map<number, Held>();
  private started = false;

  constructor(url: string) { this.url = url; }

  static pageId(url: string): string { return `f:${url}`; }
  nodeId(sensorId: number): string { return `f:${this.url}#${sensorId}`; }

  get size(): number { return this.chunks.size; }

  /** Every chunk held: its node id and address -- for coverage checks. */
  held(): { id: string; address: string }[] {
    return [...this.chunks.values()].map((h) => ({ id: h.id, address: h.address }));
  }

  private seg(x: any): string {
    if (typeof x === "string") return x;
    return typeof x === "number" && x >= 0 && x < this.dict.length ? this.dict[x] : "?";
  }

  /** [tagId, ord, tagId, ord, ...] -> the element steps, text steps dropped. */
  private steps(path: any): string[] {
    const out = ["html"];
    if (!Array.isArray(path)) return out;
    for (let i = 0; i + 1 < path.length; i += 2) {
      const tag = this.seg(path[i]);
      const ord = Number(path[i + 1]) || 1;
      if (tag === "#text") break;             // a line's own text node
      if (tag === SHADOW) { out.push(SHADOW); continue; }
      out.push(ord > 1 ? `${tag}[${ord}]` : tag);
    }
    return out;
  }

  /** The chunk's address: the longest common element path of its lines. */
  private address(lines: any[]): { address: string; title: string } {
    let common: string[] | null = null;
    let title = "";
    for (const line of lines || []) {
      if (!Array.isArray(line)) continue;
      if (!title && typeof line[1] === "string") title = line[1].trim().slice(0, 60);
      const s = this.steps(line[2]);
      if (!common) { common = s; continue; }
      let k = 0;
      while (k < common.length && k < s.length && common[k] === s[k]) k++;
      common = common.slice(0, k);
    }
    return { address: "/" + (common || ["html"]).join("/"), title };
  }

  /** The nearest held chunk whose address strictly encloses `address`. */
  private parentOf(address: string, self: number): string {
    let best: Held | null = null;
    for (const [sid, h] of this.chunks) {
      if (sid === self) continue;
      if (address.startsWith(h.address + "/")
          && (!best || h.address.length > best.address.length)) best = h;
    }
    return best ? best.id : ForceTree.pageId(this.url);
  }

  /** Fold one drain in. `null` when the payload is a transport this cannot read. */
  apply(payload: any): ForceNodeDelta | null {
    const t0 = performance.now();
    // What RAN, as the payload reports it -- never what was asked for.
    const flags = (payload && payload.stats && payload.stats.variants) || {};
    if (flags.shape || flags.pathdelta || flags.packed || flags.idanchor) return null;
    // A sensor that restarted (a reload of the same url) starts its
    // dictionary over; every id held here would then name the wrong segment.
    const size = payload?.stats?.dictSize;
    const incoming = (payload?.dict || []).length;
    if (typeof size === "number" && size !== this.dict.length + incoming) {
      const gone = [...this.chunks.values()].map((h) => h.id);
      this.dict = [];
      this.chunks.clear();
      if (size !== incoming) return null;    // mid-stream: cannot decode yet
      const got = this.apply(payload);
      if (got) got.removed.unshift(...gone);
      return got;
    }
    for (const d of payload?.dict || []) this.dict.push(String(d));
    const delta: ForceNodeDelta = { url: this.url, added: [], removed: [], reparented: [],
                                    size: 0, ms: 0, addresses: [], t0: 0, trace: "", covers: {}, settled: [] };
    if (!this.started) {
      this.started = true;
      delta.added.push({ id: ForceTree.pageId(this.url), parent: "", title: this.url, lines: 0 });
    }
    const moved: string[] = [];              // addresses that came or went
    for (const rid of payload?.removed || []) {
      const h = this.chunks.get(Number(rid));
      if (!h) continue;
      this.chunks.delete(Number(rid));
      delta.removed.push(h.id);
      moved.push(h.address);
    }
    const fresh: number[] = [];
    for (const c of payload?.chunks || []) {
      const sid = Number(c.id);
      const { address, title } = this.address(c.lines || []);
      const had = this.chunks.get(sid);
      const digest = Number(c.digest) || 0;
      const held: Held = { id: this.nodeId(sid), address, title,
                           lines: (c.lines || []).length, parent: had ? had.parent : "",
                           digest };
      this.chunks.set(sid, held);
      if (!had) { fresh.push(sid); moved.push(address); }
      else {
        if (had.address !== address) moved.push(had.address, address);
        if (had.digest !== digest) {
          delta.added.push({ id: held.id, parent: held.parent, title, lines: held.lines, again: true });
          delta.addresses.push(address);
        }
      }
    }
    for (const sid of fresh) {
      const h = this.chunks.get(sid)!;
      h.parent = this.parentOf(h.address, sid);
      delta.added.push({ id: h.id, parent: h.parent, title: h.title, lines: h.lines });
      delta.addresses.push(h.address);
    }
    // Only a node under an address that came or went can have a new parent.
    if (moved.length) {
      const freshIds = new Set(fresh);
      for (const [sid, h] of this.chunks) {
        if (freshIds.has(sid)) continue;
        if (!moved.some((a) => h.address.startsWith(a + "/") || h.address === a)) continue;
        const p = this.parentOf(h.address, sid);
        if (p !== h.parent) { h.parent = p; delta.reparented.push({ id: h.id, parent: p }); }
      }
    }
    delta.size = this.chunks.size;
    delta.ms = performance.now() - t0;
    return delta;
  }
}
