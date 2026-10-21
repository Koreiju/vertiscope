import { canonAddr, isListAbove, isProseItem } from "./address.ts";
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
  /** Each line's element address, so a panel can show the lines under the
   *  element the reader hovers rather than the whole chunk. */
  addrs?: string[];
  /** When this content arrived (an apply counter): the newest content at an
   *  address is what the page draws there now. */
  seq?: number;
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

  /**
   * The lines of a chunk under the element the reader hovers: the smallest
   * ancestor of that element holding at least `min` of the chunk's lines --
   * a tile, not the whole scroller section its in-page chunk is (archive.org,
   * 2026-10-17: five tiles opened one 40-line container). All lines when the
   * element is not inside the chunk.
   */
  linesUnder(id: string, element: string, min = 3): string[] | null {
    const h = this.retained.get(id) || (() => { const m = /#(\d+)(?:\.\d+)?$/.exec(id || ""); const x = m ? this.chunks.get(Number(m[1])) : undefined; return x && x.id === id ? x : undefined; })();
    if (!h || !h.text) return null;
    if (!element || !h.addrs || h.addrs.length !== h.text.length) return h.text;
    const ca = h.addrs.map(canonAddr);
    let at = canonAddr(element);
    while (at && at.length > 1) {
      const pick = h.text.filter((_t, i) => ca[i] === at || ca[i].startsWith(at + "/"));
      if (pick.length >= Math.min(min, h.text.length)) return pick;
      const cut = at.lastIndexOf("/");
      if (cut <= 0) break;
      at = at.slice(0, cut);
    }
    return h.text;
  }

  /**
   * The lines the page holds UNDER an element, from whichever live chunks
   * hold them: the smallest ancestor of `element` with at least `min` lines
   * under it, capped at `max` (past it, a container). The sensor's hovered
   * in-page chunk often does not hold the tile at all -- a scroller section
   * several tiles share, or a neighbour -- so looking only inside it opened
   * other tiles (archive.org, 2026-10-17: 1 of 6 tiles right).
   */
  linesForElement(element: string, min = 3, max = 60): string[] | null {
    if (!element) return null;
    const all: { a: string; t: string }[] = [];
    for (const h of this.chunks.values()) {
      if (!h.text || !h.addrs || h.addrs.length !== h.text.length) continue;
      h.addrs.forEach((a, i) => all.push({ a: canonAddr(a), t: h.text![i] }));
    }
    let at = canonAddr(element);
    while (at && at.length > 1) {
      const pick = all.filter((x) => x.a === at || x.a.startsWith(at + "/")).map((x) => x.t);
      if (pick.length > max) return null;
      if (pick.length >= min) return pick;
      const cut = at.lastIndexOf("/");
      if (cut <= 0) break;
      at = at.slice(0, cut);
    }
    return null;
  }

  /**
   * The live chunk holding an element's UNIT -- its nearest ancestor with at
   * least `min` lines under it on the page -- and that unit's address. The
   * sensor's hovered in-page chunk is often not it (a section several tiles
   * share, or a neighbour): its own lines walked up past the tile and opened
   * another tile (archive.org homepage, 2026-10-17).
   */
  chunkForElement(element: string, min = 3, max = 60, preferSid = -1): { id: string; at: string } | null {
    if (!element) return null;
    // One row per ADDRESS: where two live chunks hold the same address (a
    // merged run not yet re-cut, and the tile's own new chunk), the one the
    // sensor names for this hover wins, then the NEWEST -- the page draws one
    // thing there. Most-lines-wins picked a stale run: archive.org's search
    // list rewrites a tile in place and its old run kept the old title
    // (2026-10-18, PLUGIN_GOAL 149). Planted: `plantMostLines`.
    const best = new Map<string, { id: string; a: string; rank: number[] }>();
    for (const [sid, h] of this.chunks) {
      if (!h.addrs) continue;
      const rank = (ForceTree.plantMostLines || (globalThis as any).__vertiscopePlantPick) ? [0, 0] : [sid === preferSid ? 1 : 0, h.seq || 0];
      for (const a0 of h.addrs) {
        const a = canonAddr(a0), had = best.get(a);
        if (!had || rank[0] > had.rank[0] || (rank[0] === had.rank[0] && rank[1] > had.rank[1])) best.set(a, { id: h.id, a, rank });
      }
    }
    const rows = (ForceTree.plantMostLines || (globalThis as any).__vertiscopePlantPick)
      ? [...this.chunks.values()].flatMap((h) => (h.addrs || []).map((a) => ({ id: h.id, a: canonAddr(a) })))
      : [...best.values()];
    const all = rows.map((r) => r.a);
    let at = canonAddr(element);
    while (at && at.length > 1) {
      const under: { id: string; a: string }[] = rows.filter((r) => r.a === at || r.a.startsWith(at + "/"));
      if (under.length > max) return null;
      const pickChunk = () => {
        const by = new Map<string, number>();
        for (const r of under) by.set(r.id, (by.get(r.id) || 0) + 1);
        return [...by.entries()].sort((x, y) => y[1] - x[1])[0][0];
      };
      if (under.length >= min) {
        // A SUB-COMPONENT is not the unit; its item is (G-251): on up while
        // the level above is not a list, holds no more than `max`, and adds
        // no other chunk's lines -- a bandcamp track row's image and title
        // were two units, each a part of the row (2026-10-18). Planted
        // `plantSubUnit`.
        if (!ForceTree.plantSubUnit && !(globalThis as any).__vertiscopePlantSubUnit) {
          // Levels that add no line are passed through, not taken; a link
          // ends the climb below it (it is the whole of what it wraps).
          const mine = new Set(under.map((r) => r.id));
          let cur = at;
          for (;;) {
            const c = cur.lastIndexOf("/"), up = c > 0 ? cur.slice(0, c) : "";
            if (!up || /\/a(\[\d+\])?$/.test(up) || isListAbove(up, all)) break;
            const u2 = rows.filter((r) => r.a === up || r.a.startsWith(up + "/"));
            if (u2.length > max || u2.some((r) => !mine.has(r.id))) break;
            cur = up;
            if (u2.length > under.length) { at = up; under.splice(0, under.length, ...u2); }
          }
        }
        // An ITEM of a list that fits is not the unit -- the list is, however
        // many lines the item has: inline code and links make a short bullet
        // three lines, and it opened alone (fastapi's README, 2026-10-18:
        // "Receives HTTP requests in the paths `/` and `/items/{item_id}`"
        // one panel per bullet). Planted `plantItemAlways`.
        const cut0 = at.lastIndexOf("/"), up0 = cut0 > 0 ? at.slice(0, cut0) : "";
        if (up0 && !ForceTree.plantItemAlways && isListAbove(up0, all) && isProseItem(at, all)
            && rows.filter((r) => r.a === up0 || r.a.startsWith(up0 + "/")).length <= max) { at = up0; continue; }
        return { id: pickChunk(), at };
      }
      // A level holding a CODE BLOCK is a whole unit -- the block with its
      // toolbar -- however few lines it has (G-233): one line is the code.
      if (under.some((r) => /\/pre(\[\d+\])?$/.test(r.a)) && !ForceTree.plantCodeAsText) return { id: pickChunk(), at };
      const cut = at.lastIndexOf("/");
      if (cut <= 0) break;
      const up = at.slice(0, cut);
      // Below a list, the item is the unit, however few of its lines streamed;
      // and an item with NONE yet has no unit -- climbing on reads the other
      // items (a whole section of neighbours, 2026-10-18). Planted:
      // `plantClimbPastList`.
      // ...unless the whole list fits in one unit: a prose list of bullets is
      // ONE panel, not one per bullet (github README, 2026-10-18, PLUGIN_GOAL
      // 173). The item rule is for lists too big to be a unit -- archive.org's
      // grid. Planted `plantItemAlways`: the item, whatever the list's size.
      const listFits = () => rows.filter((r) => r.a === up || r.a.startsWith(up + "/")).length <= max;
      if (isListAbove(up, all) && (ForceTree.plantItemAlways || !listFits())) {
        if (under.length) return { id: pickChunk(), at };
        if (!(ForceTree.plantClimbPastList || (globalThis as any).__vertiscopePlantPick)) return null;
      }
      at = up;
    }
    return null;
  }


  /** A chunk's line addresses by node id (live or retained), or null. */
  addrsOf(id: string): string[] | null {
    const r = this.retained.get(id);
    if (r) return r.addrs || null;
    const m = /#(\d+)(?:\.\d+)?$/.exec(id || "");
    const h = m ? this.chunks.get(Number(m[1])) : undefined;
    return h && h.id === id && h.addrs ? h.addrs : null;
  }

  /** A live chunk's line texts by its node id, or null (gone, or a branch). */
  linesOf(id: string): string[] | null {
    const r = this.retained.get(id);
    if (r) return r.text || null;
    const m = /#(\d+)(?:\.\d+)?$/.exec(id || "");
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
  /** A sensor id's node: generation 0 is `#sid`, a reused element's later
   *  contents `#sid.g` -- each distinct content its own node (G-216). */
  nodeId(sensorId: number): string {
    const g = this.gen.get(sensorId) || 0;
    return g ? `f:${this.url}#${sensorId}.${g}` : `f:${this.url}#${sensorId}`;
  }
  private gen = new Map<number, number>();

  /**
   * **The page is every unique chunk seen, not the last DOM** (G-216,
   * 2026-10-17: "track the full set of unique chunks"; "archive still not
   * registering correctly"). archive.org's result list recycles itself as it
   * scrolls -- in 15 s, 698 chunks removed and 544 rewritten in place -- so a
   * tile scrolled past vanished from the graph and a reused element
   * overwrote the tile it had held. Bluesky's feed does the same ("nodes
   * scanned temporarily are disappearing"). A chunk the page removes is
   * RETAINED: its node stays, re-hung from the page root (its place in the
   * DOM is gone). A reused element's new content is a new node and the old
   * content is retained. Retained content seen again elsewhere is dropped, so
   * each content keeps one node. Planted: `plantDropRemoved`, as before.
   */
  static plantDropRemoved = false;
  /** Planted: every version of a re-cut element retained (the 40-line copies). */
  static plantKeepVersions = false;
  /** Planted: the generation advances only on an in-place rewrite (a removed-then-reused id collides with its kept version). */
  static plantGenOnRewriteOnly = false;
  /** Planted: the unit's chunk is the one with the most lines there (stale runs win). */
  static plantMostLines = false;
  /** Planted: an item with no lines yet climbs past its list (opens the neighbours). */
  static plantClimbPastList = false;
  /** Planted: below any list the item is the unit (bullets one panel each). */
  static plantItemAlways = false;
  /** Planted (G-251): a unit stops at its first level with `min` lines -- a part of its item. */
  static plantSubUnit = false;
  private applySeq = 0;
  private retained = new Map<string, Held>();
  private retainedByText = new Map<string, string>();
  retainStats = { retained: 0, recycled: 0, revived: 0 };
  retainedCount(): number { return this.retained.size; }
  private retain(h: Held, delta: ForceNodeDelta): void {
    this.retained.set(h.id, h);
    // The element's NEXT content is a new node: a kept version and a live
    // one never share an id. Bumped only on an in-place rewrite before, so a
    // REMOVED element whose sensor id came back took the kept version's id,
    // and every lookup (kept first) served the old tile -- archive.org's
    // "Archive Team: US Government" opened "Medical Heritage Library"
    // (2026-10-17, PLUGIN_GOAL 149). Planted: `plantGenOnRewriteOnly`.
    if (!ForceTree.plantGenOnRewriteOnly && !(globalThis as any).__vertiscopePlantGen) {
      const m = /#(\d+)(?:\.\d+)?$/.exec(h.id);
      if (m) { const sid = Number(m[1]); this.gen.set(sid, (this.gen.get(sid) || 0) + 1); }
    }
    const key = (h.text || []).join("\n");
    if (key) this.retainedByText.set(key, h.id);
    const page = ForceTree.pageId(this.url);
    if (h.parent !== page) { h.parent = page; delta.reparented.push({ id: h.id, parent: page }); }
    this.retainStats.retained++;
  }

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

  /**
   * A drain line as panel markdown: a line an `<img>` draws is its picture,
   * `![](src)` -- streamed as the bare url, a grey chunk's panel showed the
   * address as text and no image (Bluesky, 2026-10-17: "embedded media is
   * missing. the nodes are registered, but the content is missing").
   */
  private lineText(l: any): string {
    const t = String((l && l[1]) || "");
    const path = l && l[2];
    if (!t || !Array.isArray(path) || ForceTree.plantImgAsText) return t;
    let last = "";
    for (let i = 0; i + 1 < path.length; i += 2) {
      const tag = this.seg(path[i]);
      if (tag === "#text" || tag === SHADOW) continue;
      last = tag;
    }
    if ((last === "img" || last === "image") && /^(https?:|data:image|\/)/.test(t)) return `![](${t})`;
    // A code block (G-233): fenced, so a panel draws it as code.
    if (last === "pre" && !ForceTree.plantCodeAsText) return "```\n" + t + "\n```";
    // A control's existence marker (`@control` -> its element name) drawn as
    // a control, not as the bare word "button" (G-233).
    const acc = typeof l[3] === "number" && l[3] >= 0 ? this.seg(l[3]) : "";
    // The stored markdown's lo-fi forms: a button `( · )`, a field `[ ]`.
    if (acc === "@control") return t === "button" ? "( · )" : "[ ]";
    // A link's destination is the page's address for it, never a tail of it:
    // `/docs/transformers/v5.20.1/...#transformers.Pipeline` reads as
    // `https://huggingface.co/docs/...` (2026-10-18: "please ensure to
    // resolve hyperlink tails to their domains"). Resolved against the base
    // the page declared (`baseFor`), as the stored panels already are.
    // Planted `plantRelativeLinks`.
    if (!ForceTree.plantRelativeLinks && (acc === "href" || last === "a" || last === "area")
        && /^(\/|\.\.?\/|\?|#)/.test(t) && !/\s/.test(t)) {
      try { return new URL(t, ForceTree.baseOf(this.url)).href; } catch { return t; }
    }
    return t;
  }
  static plantCodeAsText = false;
  /** The base a page's relative links resolve against; the browser cell
   *  sets it to the base each page declared (`snapshot.baseFor`). */
  static baseOf: (url: string) => string = (u) => u;
  /** Planted: a link's destination drawn as the page wrote it (a tail). */
  static plantRelativeLinks = false;
  static plantImgAsText = false;

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
      moved.push(h.address);
      if (ForceTree.plantDropRemoved) delta.removed.push(h.id);
      else this.retain(h, delta);
    }
    const fresh: number[] = [...adopted];
    for (const c of payload?.chunks || []) {
      const sid = Number(c.id);
      const { address, title } = this.address(c.lines || []);
      let had = this.chunks.get(sid);
      const digest = Number(c.digest) || 0;
      const text = (c.lines || []).map((l: any) => this.lineText(l));
      const addrs = (c.lines || []).map((l: any) => "/" + this.steps(l && l[2]).join("/"));
      // A reused element now holding DIFFERENT content: the old content is
      // retained under its own node; the new content is a new node.
      // ...and only when the old content is mostly GONE: a container that
      // grew (archive.org's scroller section, re-cut on every tile) is a
      // superset of its old self, and keeping each version left dozens of
      // near-identical 40-line nodes (2026-10-17). Planted: every version.
      const lost = (old: string[]) => { const now = new Set(text); const o = old.filter((l) => l.trim());
        return !o.length || o.filter((l) => !now.has(l)).length >= 0.5 * o.length; };
      if (had && had.digest !== digest && !ForceTree.plantDropRemoved
          && (had.text || []).join("\n") !== text.join("\n") && (ForceTree.plantKeepVersions || lost(had.text || []))) {
        this.retain(had, delta);
        if (ForceTree.plantGenOnRewriteOnly || (globalThis as any).__vertiscopePlantGen) this.gen.set(sid, (this.gen.get(sid) || 0) + 1);
        this.retainStats.recycled++;
        had = undefined;
      }
      // Content retained earlier and live again: one node per content.
      const tkey = text.join("\n");
      const back = tkey ? this.retainedByText.get(tkey) : undefined;
      if (back && !had) {
        this.retained.delete(back); this.retainedByText.delete(tkey);
        delta.removed.push(back);
        this.retainStats.revived++;
      }
      const held: Held = { id: this.nodeId(sid), address, title,
                           lines: (c.lines || []).length, parent: had ? had.parent : "",
                           digest, text, addrs, seq: had && had.digest === digest ? had.seq : ++this.applySeq };
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

// Reachable by the live probes, to plant its static switches (G-233).
(globalThis as any).__vertiscopeForceTree = ForceTree;
