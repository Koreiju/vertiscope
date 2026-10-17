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
  added: { id: string; parent: string; title: string; lines: number; again?: boolean; branch?: boolean }[];
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
  /** Every branch of the page's trie now: id -> its parent and title, so the
   *  graph can draw a chunk's missing ancestors instead of hanging it on the
   *  page (a branch announced while the page was folded was never drawn). */
  branches?: Record<string, { parent: string; title: string }>;
}

interface Held {
  id: string; address: string; title: string; lines: number; parent: string; digest: number;
  /** The chunk's line texts as the drain delivered them: a grey node shows
   *  its markdown at once, before any store or vector (PLUGIN_GOAL 125). */
  text?: string[];
}

const SHADOW = "#shadow-root";

export class ForceTree {
  readonly url: string;
  private dict: string[] = [];
  private chunks = new Map<number, Held>();
  private started = false;
  /** The patricia trie's BRANCHING points among the held chunks' addresses
   *  (address -> its node id and parent): the interior the stream hangs on. */
  private branches = new Map<string, { id: string; parent: string }>();
  /** Planted by G-116's check: no branches -- every chunk under the page (the star). */
  static plantFlat = false;

  branchId(address: string): string { return `f:${this.url}@${address}`; }

  /**
   * Continue a DOCUMENT's stream under a new page (G-216/G-217). The
   * sensor's dictionary and chunk ids belong to the document, not to the
   * page the store files them under: a fresh tree for a page that began
   * inside a running document could decode none of its drains ("mid-stream:
   * cannot decode yet") and the stream was dropped -- archive.org's search
   * list, 0 chunks held after a url rewrite (2026-10-17). The new tree takes
   * the document's dictionary and its live chunks, which are still on the
   * page, and reports them as added on its first drain.
   */
  adopt(from: ForceTree): void {
    this.dict = [...from.dict];
    for (const [sid, h] of from.chunks) this.chunks.set(sid, { ...h, id: this.nodeId(sid), parent: "" });
    this.adoptPending = true;
  }
  private adoptPending = false;

  /** A live chunk's line texts by its node id, or null (gone, or a branch). */
  linesOf(id: string): string[] | null {
    const m = /#(\d+)$/.exec(id || "");
    const h = m ? this.chunks.get(Number(m[1])) : undefined;
    return h && h.id === id && h.text ? h.text : null;
  }

  /**
   * The patricia trie over the held chunks' addresses (2026-10-06: "The
   * lagging chunks initialized into a perfect sphere and not really the
   * 'diff' over the patricia trie at all ... The diff should be sort of like
   * a trickling effect over the emerging diff on the active and open tree").
   * A chunk's parent was the nearest chunk ENCLOSING it, and sibling regions
   * rarely enclose each other: 33/33 streamed nodes hung on the page node.
   * Here the interior is drawn too: a prefix where held addresses DIVERGE
   * (two or more distinct next steps) is a branch node; every chunk and
   * branch hangs from its nearest proper-prefix node, chunk or branch, else
   * the page. Compressed (only branching prefixes), so it is the patricia
   * trie's own shape. Returns address -> parent id for chunks and branches.
   */
  private skeleton(): { parentOfChunk: Map<number, string>; branches: Map<string, string> } {
    const page = ForceTree.pageId(this.url);
    const parentOfChunk = new Map<number, string>();
    const branches = new Map<string, string>();
    if (ForceTree.plantFlat) {
      for (const [sid, h] of this.chunks) parentOfChunk.set(sid, this.parentOf(h.address, sid));
      return { parentOfChunk, branches };
    }
    // Next-step continuations under every prefix, and chunk addresses.
    const nexts = new Map<string, Set<string>>();
    const chunkAt = new Map<string, number>();
    for (const [sid, h] of this.chunks) {
      if (!chunkAt.has(h.address)) chunkAt.set(h.address, sid);
      const steps = h.address.split("/").filter(Boolean);
      for (let k = 1; k < steps.length; k++) {
        const pre = "/" + steps.slice(0, k).join("/");
        (nexts.get(pre) || nexts.set(pre, new Set()).get(pre)!).add(steps[k]);
      }
    }
    const nodeAt = new Map<string, string>();          // address -> node id
    for (const [pre, set] of nexts) {
      if (set.size >= 2 && !chunkAt.has(pre) && pre !== "/html") nodeAt.set(pre, this.branchId(pre));
    }
    for (const [addr, sid] of chunkAt) nodeAt.set(addr, this.nodeId(sid));
    const up = (addr: string): string => {
      const steps = addr.split("/").filter(Boolean);
      for (let k = steps.length - 1; k >= 1; k--) {
        const pre = "/" + steps.slice(0, k).join("/");
        const id = nodeAt.get(pre);
        if (id) return id;
      }
      return page;
    };
    for (const [pre, id] of nodeAt) if (id.indexOf("@") >= 0) branches.set(pre, up(pre));
    for (const [sid, h] of this.chunks) {
      const own = chunkAt.get(h.address);
      // A second chunk at the same address hangs beside the first, from
      // the same parent (never from its twin).
      parentOfChunk.set(sid, own !== undefined && own !== sid ? up(h.address) : up(h.address));
    }
    return { parentOfChunk, branches };
  }

  constructor(url: string) { this.url = url; }

  static pageId(url: string): string { return `f:${url}`; }
  nodeId(sensorId: number): string { return `f:${this.url}#${sensorId}`; }

  get size(): number { return this.chunks.size; }

  /** A held chunk's address by its sensor id. */
  addressOf(sensorId: number): string | null {
    return this.chunks.get(sensorId)?.address ?? null;
  }

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
    // Adopted from the document's previous page: drawn as new here.
    const adopted: number[] = [];
    if (this.adoptPending) {
      this.adoptPending = false;
      for (const [sid, h] of this.chunks) { adopted.push(sid); moved.push(h.address); }
    }
    for (const rid of payload?.removed || []) {
      const h = this.chunks.get(Number(rid));
      if (!h) continue;
      this.chunks.delete(Number(rid));
      delta.removed.push(h.id);
      moved.push(h.address);
    }
    const fresh: number[] = [...adopted];
    for (const c of payload?.chunks || []) {
      const sid = Number(c.id);
      const { address, title } = this.address(c.lines || []);
      const had = this.chunks.get(sid);
      const digest = Number(c.digest) || 0;
      const held: Held = { id: this.nodeId(sid), address, title,
                           lines: (c.lines || []).length, parent: had ? had.parent : "",
                           digest, text: (c.lines || []).map((l: any) => String((l && l[1]) || "")) };
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
    // The trie's skeleton, recomputed when an address came or went: branch
    // nodes added and dropped, every parent that changed reparented.
    const sk = (moved.length || fresh.length) ? this.skeleton() : null;
    if (sk) {
      // Branches that left (no longer a divergence), deepest first.
      for (const [addr, b] of [...this.branches]) {
        if (!sk.branches.has(addr)) { this.branches.delete(addr); delta.removed.push(b.id); }
      }
      // Branches that arrived, shallowest first so a parent precedes its child.
      const arrived = [...sk.branches.keys()].filter((a) => !this.branches.has(a))
        .sort((a, b) => a.split("/").length - b.split("/").length);
      for (const addr of arrived) {
        const parent = sk.branches.get(addr)!;
        const id = this.branchId(addr);
        this.branches.set(addr, { id, parent });
        const last = addr.split("/").filter(Boolean).slice(-2).join("/");
        delta.added.push({ id, parent, title: last, lines: 0, branch: true });
      }
      for (const [addr, b] of this.branches) {
        const p = sk.branches.get(addr)!;
        if (p !== b.parent && !arrived.includes(addr)) { b.parent = p; delta.reparented.push({ id: b.id, parent: p }); }
      }
    }
    const freshIds = new Set(fresh);
    for (const sid of fresh) {
      const h = this.chunks.get(sid);
      if (!h) continue;                      // adopted, then removed by this drain
      h.parent = sk ? (sk.parentOfChunk.get(sid) || ForceTree.pageId(this.url)) : this.parentOf(h.address, sid);
      delta.added.push({ id: h.id, parent: h.parent, title: h.title, lines: h.lines });
      delta.addresses.push(h.address);
    }
    if (sk) {
      for (const [sid, h] of this.chunks) {
        if (freshIds.has(sid)) continue;
        const p = sk.parentOfChunk.get(sid) || ForceTree.pageId(this.url);
        if (p !== h.parent) { h.parent = p; delta.reparented.push({ id: h.id, parent: p }); }
      }
    }
    delta.branches = {};
    for (const [addr, b] of this.branches) {
      delta.branches[b.id] = { parent: b.parent, title: addr.split("/").filter(Boolean).slice(-2).join("/") };
    }
    delta.size = this.chunks.size;
    delta.ms = performance.now() - t0;
    return delta;
  }
}
