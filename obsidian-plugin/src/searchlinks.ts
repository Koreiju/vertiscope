/**
 * The search as ONE node with its inputs and outputs as hard links
 * (PLUGIN_GOAL 164, G-372 step 3; `docs/SEARCH_GRAPH_DESIGN.md`, Revision).
 *
 * The reader: "A high-level retrieval mechanism that integrates cleanly with
 * its input and output artifacts, in that all its inputs and outputs are
 * shown as hard links". The node is the retrieval cell (the "search" bar of
 * item 163). Its OUTPUTS are the results it shows: a line from the cell to
 * the node that draws each one in the 3D view. Its INPUTS are the artifacts
 * it reads: the slate its query is bound to (the cockpit, `ego.md`) when that
 * slate is open on the plane, and the browser cell when the query was sent
 * to the web. Live search only (item 164): the lines are the current
 * results' and go when the search is cleared.
 *
 * Trie framing: read only. Every out-link ends at a node whose id is a cid
 * or a page url -- an address -- and carries it (`data-cid`).
 *
 * Drawn in an SVG layer over the canvas, redrawn every frame while a search
 * is live, because the camera keeps moving after the simulation settles and
 * a line fixed at draw time would point where the node used to be.
 */

export interface SearchLinkInput { key: string; el: Element }
export interface SearchLinkOutput { cid: string; rank: number; x: number; y: number; z: number }

export interface SearchLinkSource {
  /** The canvas the 3D view draws into: the layer's frame of reference. */
  canvas(): HTMLElement | null;
  /** The retrieval cell -- the search node -- or null when none is shown. */
  cell(): HTMLElement | null;
  /** The shown results' drawn nodes, best first. */
  outputs(): SearchLinkOutput[];
  /** The artifacts the search reads that are on screen. */
  inputs(): SearchLinkInput[];
  /** World to canvas pixels. */
  toScreen(x: number, y: number, z: number): { x: number; y: number } | null;
}

export class SearchLinks {
  /** Planted: the search shows its results and draws no link. */
  plantNoLinks = false;
  stats = { frames: 0, out: 0, in: 0, offscreen: 0, cleared: 0, last_cids: [] as string[] };
  private svg: SVGSVGElement | null = null;
  private frame = 0;
  private live = false;

  constructor(private src: SearchLinkSource) {}

  /** A search is showing results: draw its links until `stop`. */
  start(): void {
    this.live = true;
    if (this.frame) return;
    const step = () => {
      if (!this.live) { this.frame = 0; return; }
      try { this.draw(); } catch { /* one bad frame must not end the loop */ }
      this.frame = window.requestAnimationFrame(step);
    };
    this.frame = window.requestAnimationFrame(step);
  }

  /** The search was cleared: its links go with it. */
  stop(): void {
    this.live = false;
    if (this.frame) window.cancelAnimationFrame(this.frame);
    this.frame = 0;
    this.svg?.remove();
    this.svg = null;
    this.stats.out = 0; this.stats.in = 0; this.stats.last_cids = [];
    this.stats.cleared++;
  }

  /** One frame: every link re-anchored to where its ends are now. */
  draw(): void {
    const canvas = this.src.canvas(), cell = this.src.cell();
    if (!canvas || !cell || this.plantNoLinks) {
      this.svg?.remove(); this.svg = null;
      this.stats.out = 0; this.stats.in = 0;
      return;
    }
    const NS = "http://www.w3.org/2000/svg";
    if (!this.svg || !canvas.contains(this.svg)) {
      this.svg = document.createElementNS(NS, "svg") as SVGSVGElement;
      this.svg.classList.add("domvec-search-links");
      canvas.appendChild(this.svg);
    }
    const svg = this.svg;
    const cv = canvas.getBoundingClientRect();
    svg.setAttribute("width", String(cv.width)); svg.setAttribute("height", String(cv.height));
    const cr = cell.getBoundingClientRect();
    // The node's port: the middle of the cell's top edge, where its results
    // leave it; inputs arrive at the same port from above.
    const port = { x: cr.left + cr.width / 2 - cv.left, y: cr.top - cv.top };

    const want: { key: string; x1: number; y1: number; x2: number; y2: number; cls: string; cid?: string; rank?: number }[] = [];
    let off = 0;
    for (const o of this.src.outputs()) {
      const at = this.src.toScreen(o.x, o.y, o.z);
      if (!at || !Number.isFinite(at.x) || !Number.isFinite(at.y)) { off++; continue; }
      if (at.x < 0 || at.y < 0 || at.x > cv.width || at.y > cv.height) { off++; continue; }
      want.push({ key: "out:" + o.cid, x1: port.x, y1: port.y, x2: at.x, y2: at.y, cls: "is-out", cid: o.cid, rank: o.rank });
    }
    for (const i of this.src.inputs()) {
      const r = i.el.getBoundingClientRect();
      if (!r.width || !r.height) continue;
      // From the input card's edge nearest the port.
      const cx = Math.max(r.left, Math.min(port.x + cv.left, r.right)) - cv.left;
      const cy = Math.max(r.top, Math.min(port.y + cv.top, r.bottom)) - cv.top;
      want.push({ key: "in:" + i.key, x1: cx, y1: cy, x2: port.x, y2: port.y, cls: "is-in" });
    }

    const keep = new Set(want.map((w) => w.key));
    for (const l of Array.from(svg.querySelectorAll("line"))) if (!keep.has((l as any).dataset.key)) l.remove();
    const byKey = new Map<string, SVGLineElement>();
    for (const l of Array.from(svg.querySelectorAll("line"))) byKey.set((l as any).dataset.key, l as SVGLineElement);
    for (const w of want) {
      let l = byKey.get(w.key);
      if (!l) {
        l = document.createElementNS(NS, "line") as SVGLineElement;
        (l as any).dataset.key = w.key;
        l.classList.add(w.cls);
        if (w.cid) (l as any).dataset.cid = w.cid;
        svg.appendChild(l);
      }
      if (w.rank !== undefined) (l as any).dataset.rank = String(w.rank);
      l.setAttribute("x1", w.x1.toFixed(1)); l.setAttribute("y1", w.y1.toFixed(1));
      l.setAttribute("x2", w.x2.toFixed(1)); l.setAttribute("y2", w.y2.toFixed(1));
    }
    this.stats.frames++;
    this.stats.out = want.filter((w) => w.cls === "is-out").length;
    this.stats.in = want.length - this.stats.out;
    this.stats.offscreen = off;
    this.stats.last_cids = want.filter((w) => w.cid).map((w) => w.cid!) ;
  }
}
