/**
 * The pipeline, over the browser the reader is using.
 *
 * **Why here and not in a pane.** The profile pane answered "where did the
 * time go" in a place the reader had to go and look, while the thing it
 * described was happening in the browser in front of them. This is a small
 * black box in the bottom-right corner of the browser cell that opens on
 * hover and shows, for THE PAGE BEING BROWSED:
 *
 *   * the chain every chunk is supposed to travel -- stored, embedded, in the
 *     projector, hung from its page -- as counts, so "all of them made it" is
 *     a number the reader can check rather than a claim;
 *   * each chunk against the context window it was cut to;
 *   * the last drain's stages, and what is streaming to the projector now;
 *   * how close the fit is to its next refit (at 2x the chunks it was made
 *     on), and whether this page's anchor is fitted or an estimate;
 *   * the chunk under the pointer: what it is, and whether it has a vector
 *     and a node yet -- with its bounding box outlined on the page.
 *
 * **Nothing is written into the page** (`CLAUDE.md` rule 7, `G-41`). The box
 * and the outline are elements of the browser CELL, layered over the webview
 * in the plugin's own DOM. The guest is only ever READ: the hovered element,
 * its xpath and its bounding rect. The page cannot see any of this.
 */

import { canonAddr } from "./address.ts";
import type { Sidecar } from "./sidecar";
import { profiler } from "./profile";
import { ProfileReadout } from "./profileview";
import { embedded } from "./chunkstructure";
import { ChunkMap } from "./chunkmap";

/** A chunk the reader right-clicked: pinned until the markdown side lets
 *  it go (`G-78`). */
export interface PinnedChunk { cid: string; matched: string; url: string; }

/** The xpath of an element, by the trie's convention (see `portMarkdown`). */
const XPATH_OF = "var parts=[];" +
  "while(el && el.nodeType===1 && el.tagName){" +
  "var tag=el.tagName.toLowerCase(),i=1,sib=el.previousElementSibling;" +
  "while(sib){if(sib.tagName===el.tagName)i++;sib=sib.previousElementSibling;}" +
  "parts.unshift(i>1?tag+'['+i+']':tag);el=el.parentElement;}" +
  "return '/'+parts.join('/');";

/** The sensor's handle on the guest window (as `browser.ts` installs it). */
const SENSOR_HANDLE = "__vertiscopeSensor";

export interface HoverState {
  xpath: string;
  cid: string;
  /** Who answered: the store's chunk map, or the in-page chunking (D-35). */
  source?: "store" | "page";
  matched: string;
  walked: number;
  rect: { x: number; y: number; w: number; h: number } | null;
  lines: number;
  at: number;
  /** The stored chunk the outline stands for, when the store knows the page. */
  stored?: string;
  /** The stored unit came from the hovered element's own address. */
  byAddress?: boolean;
}

/** An address and every ancestor of it, leaf first -- the walk `/resolve` does. */
function addressChain(addr: string): string[] {
  const out: string[] = [];
  let a = addr;
  while (a && out.length < 60) { out.push(a); const cut = a.lastIndexOf("/"); if (cut <= 0) break; a = a.slice(0, cut); }
  return out;
}

/**
 * An in-page read with a deadline. `executeJavaScript` on a page that is still
 * loading can wait until the load finishes; the hover poll holds a busy flag
 * across it, so one stalled read froze the overlay for the whole load --
 * found by a check that hovers right after navigating and saw nothing at all.
 * Past the deadline the read is abandoned and the next poll starts fresh.
 */
function within<T>(p: Promise<T>, ms: number): Promise<T | null> {
  return Promise.race([p.catch(() => null), new Promise<null>((r) => setTimeout(() => r(null), ms))]);
}

export class PipelineBox {
  readonly el: HTMLElement;
  private mini: HTMLElement;
  private full: HTMLElement;
  private outline: HTMLElement;
  /** Boxes outlining the last drain's diff (`G-90`), reused drain to drain. */
  private diffEls: HTMLElement[] = [];
  private diffTimer = 0;
  /** Drain-to-overlay times, ms: the browser half of the `G-90` profile. */
  diffLatencies: number[] = [];
  /** What the last flash outlined, for the harness. */
  lastDiff: { at: number; asked: number; drawn: number; ms: number } | null = null;
  /** Open because someone ASKED -- a click, or the harness on an MCP
   *  tool's behalf (`G-76`). Stays open until asked to close. */
  private userOpen = false;
  /** Open because the pointer is over it: a peek, gone on leave. */
  private peek = false;
  /** What is drawn: asked-open or peeking. Read by the harness. */
  expanded = false;
  /** Everything the box redraws each tick; the profile readout below it is
   *  mounted once and redraws itself. */
  private dyn!: HTMLElement;
  private profileHost!: HTMLElement;
  private readout: ProfileReadout | null = null;
  /** Pinned chunks and the outline each one draws on the page. */
  pins: PinnedChunk[] = [];
  private pinEls = new Map<string, HTMLElement>();
  /** Told when the pointer is over something the store does not hold yet,
   *  so the browser can drain NOW rather than on its next tick (`G-80`). */
  onUnresolved: (xpath: string) => void = () => {};
  private lastUnresolved = "";
  private focused = new Set<string>();
  /** Which chunk draws which element of this page -- in memory, so a hover
   *  never waits on the store (DESIGN_VII §3). */
  map = new ChunkMap();
  /** The last hovers' latencies, pointer-read to outline drawn, in ms. */
  latencies: number[] = [];
  private timer = 0;
  private hoverTimer = 0;
  private status: any = null;
  private statusUrl = "";
  private lastStatusPoll = 0;
  private hoverBusy = false;
  private resolved = new Map<string, { cid: string; matched: string; walked: number; lines: number }>();
  hover: HoverState | null = null;
  /** The checks gesture opened this box; "restore" closes it again. */
  openedForChecks = false;
  /** Hovers answered by each source, for the harness (D-35). */
  hoverSources = { store: 0, page: 0 };
  /** Ignore the store map: the page's own chunking only (diagnostic). */
  pageOnly = false;
  /** Planted: the poll keeps answering after pushes start (the fight). */
  plantPollFights = false;
  /** Planted by D-35's check: the old store-only hover, no in-page answer. */
  plantStoreOnly = false;

  constructor(private wrap: HTMLElement, private sidecar: Sidecar,
              private webview: () => any,
              private onHoverChunk: (cid: string, url: string, stored?: string) => void) {
    this.outline = wrap.createDiv({ cls: "vertiscope-chunk-outline" });
    this.outline.hide();
    this.el = wrap.createDiv({ cls: "vertiscope-pipebox" });
    this.mini = this.el.createDiv({ cls: "vertiscope-pipebox-mini" });
    this.full = this.el.createDiv({ cls: "vertiscope-pipebox-full" });
    this.dyn = this.full.createDiv({ cls: "vertiscope-pipebox-dyn" });
    this.profileHost = this.full.createDiv({ cls: "vertiscope-pipebox-profile" });
    this.full.hide();
    // A click opens or closes it and it STAYS that way (`G-76`); hovering
    // only peeks. The harness calls `setExpanded`, which is the same state a
    // click sets, so what an MCP tool opens a human sees open.
    this.mini.addEventListener("click", () => this.setExpanded(!this.userOpen));
    this.el.addEventListener("mouseenter", () => { this.peek = true; this.draw(); });
    this.el.addEventListener("mouseleave", () => { this.peek = false; this.draw(); });
    this.timer = window.setInterval(() => void this.tick(), 1000);
    // Hover is polled rather than listened for: mouse events over a webview
    // go to the GUEST, and listening there would mean installing a handler
    // in the page. Reading `:hover` five times a second installs nothing.
    // 80 ms: the poll is two small in-page reads and a map lookup now, so a
    // shorter interval costs little and is most of the hover's latency.
    this.hoverTimer = window.setInterval(() => void this.pollHover(), 80);
    this.streamTimer = window.setInterval(() => void this.followStreaming(), 120);
    this.draw();
  }

  destroy() {
    window.clearInterval(this.timer);
    window.clearInterval(this.hoverTimer); window.clearInterval(this.streamTimer);
    this.readout?.destroy();
    this.el.remove();
    this.outline.remove();
    for (const el of this.structEls) el.remove();
    for (const el of this.pinEls.values()) el.remove();
    this.pinEls.clear();
  }

  /** Open or close the readout, and keep it that way. */
  setExpanded(open: boolean) {
    this.userOpen = open;
    this.draw();
  }

  /** The chunks the markdown side holds; each gets an outline (`G-78`). */
  setPins(pins: PinnedChunk[]) {
    this.pins = pins.slice();
    const keep = new Set(pins.map((x) => x.cid));
    for (const [cid, el] of this.pinEls) {
      if (!keep.has(cid)) { el.remove(); this.pinEls.delete(cid); }
    }
    for (const pin of pins) {
      if (!this.pinEls.has(pin.cid)) {
        const el = this.wrap.createDiv({ cls: "vertiscope-chunk-pin" });
        el.hide();
        this.pinEls.set(pin.cid, el);
      }
    }
    void this.placePins();
  }

  /** The page a url belongs to -- the browser's session for an url the page
   *  took without leaving its document (G-216); "0/0 in graph" otherwise. */
  urlOf: (raw: string) => string = (u) => u;
  /** The url the cell shows, kept from its navigations (no synchronous ask). */
  shownUrl: (() => string) | null = null;
  private statusBusy = false;
  /** Planted: a status question every tick, answered or not. */
  plantStatusPileUp = false;
  private url(): string {
    try { return this.urlOf((this.shownUrl ? this.shownUrl() : this.webview()?.getURL()) || ""); } catch { return ""; }
  }

  private visible(): boolean {
    return !document.hidden && this.wrap.isShown() && this.wrap.offsetWidth > 0;
  }

  private async tick() {
    if (!this.visible()) return;
    const url = this.url();
    const now = performance.now();
    // Every 2 s collapsed, every second open; always at once on a new page.
    const every = this.expanded ? 1000 : 2000;
    // ONE question at a time: the tick fires every second whether or not
    // the last answer came back, and against a slow store (0.6-3.9 s an
    // answer) the box kept 8-9 /page_status requests in flight, piling onto
    // a sidecar that then stopped answering (2026-10-19). Planted
    // `plantStatusPileUp`: asked every tick, as before.
    if (url && url !== "about:blank" && (!this.statusBusy || this.plantStatusPileUp) &&
        (url !== this.statusUrl || now - this.lastStatusPoll >= every)) {
      this.lastStatusPoll = now;
      this.statusUrl = url;
      this.statusBusy = true;
      try { this.status = await this.sidecar.pageStatus(url).catch(() => null); }
      finally { this.statusBusy = false; }
    }
    this.draw();
  }

  // ---- hover --------------------------------------------------------------

  private async pollHover() {
    const wv = this.webview();
    if (!wv || this.hoverBusy || !this.visible()) return;
    this.hoverBusy = true;
    try {
      if (this.pins.length) await this.placePins();
      const t0 = performance.now();
      // The hovered element's ancestor chain, leaf first: one in-page read.
      // ...and, in the same crossing, the IN-PAGE chunking's answer: which
      // chunk the sensor draws it in, and that chunk's box (D-35). It needs
      // no store, so the overlay works on a page the store has not seen and
      // in the seconds after a navigation, when the store's map is not in.
      const got: { chain: string[]; at: { id: number; box: number[] | null; depth: number } | null } | null =
        await within(wv.executeJavaScript(
        "(function(){var hs=document.querySelectorAll(':hover');" +
        "if(!hs.length) return null;var el=hs[hs.length-1],leaf=el;var out=[];" +
        "while(el&&el.nodeType===1&&el.tagName){var parts=[],n=el;" +
        "while(n&&n.nodeType===1&&n.tagName){var t=n.tagName.toLowerCase(),k=1,s=n.previousElementSibling;" +
        "while(s){if(s.tagName===n.tagName)k++;s=s.previousElementSibling;}" +
        "parts.unshift(k>1?t+'['+k+']':t);n=n.parentElement;}" +
        "out.push('/'+parts.join('/'));el=el.parentElement;}" +
        "var h=window[" + JSON.stringify(SENSOR_HANDLE) + "];" +
        "return {chain:out,at:(h&&h.at)?h.at(leaf):null};})()"), 400);
      const chain = got ? got.chain : null;
      // Once the sensor PUSHES hovers, they are the hover: the poll neither
      // clears it nor names a chunk of its own. Its empty reads cleared the
      // hover (closing the panel, stopping the camera's follow) and its store
      // lookup could name a different chunk than the sensor's -- the camera
      // retargeted 4 times on one hover and the panel flickered (2026-10-07).
      // The stored chunk is resolved from the pushed one (`storedCidFor`).
      if (this.pushedAt && !this.plantPollFights) return;
      if (!chain || !chain.length) { this.clearHover(); return; }
      const url = this.url();
      // In memory: the same nearest-ancestor walk `/resolve` does in the store.
      const hit = this.pageOnly ? null : (this.map.url === url ? this.map.lookup(chain) : null);
      // Once the sensor pushes, ITS outline is the outline (the overlay comes
      // from the in-page chunking, Addendum IX): the poll only resolves which
      // STORED chunk it is, for the ring and hover-first. Two sources had
      // been trading the outline, and the poll's was 81-130 ms late.
      if (this.pushedAt) {
        // Not over a push that already named its stored unit by address: the
        // poll's chain stops at shadow roots and named the page header for
        // every card of a shadow-DOM list.
        if (hit && (!this.hover || (this.hover.source === "page" && !this.hover.byAddress))) this.onHoverChunk(hit.cid, url);
        return;
      }
      if (!hit && got && got.at && got.at.box && !this.plantStoreOnly) {
        // The store does not know this element yet: outline the chunk the
        // PAGE's own chunking put it in, and ring its force node.
        const b = got.at.box;
        const cid = `f:${url}#${got.at.id}`;
        const changed = !this.hover || this.hover.cid !== cid;
        this.hover = { xpath: chain[0], cid, matched: "", walked: got.at.depth, source: "page",
                       rect: { x: b[0], y: b[1], w: b[2], h: b[3] }, lines: 0, at: performance.now() };
        this.placeOutline();
        const ms = performance.now() - t0;
        this.latencies.push(Math.round(ms * 10) / 10);
        if (this.latencies.length > 100) this.latencies.shift();
        this.hoverSources.page++;
        if (changed) this.onHoverChunk(cid, url);
        if (chain[0] !== this.lastUnresolved) {
          this.lastUnresolved = chain[0];
          this.onUnresolved(chain[0]);
        }
        if (this.expanded) this.draw();
        return;
      }
      if (!hit) {
        // Nothing mapped draws this yet: drain NOW (`G-80`, hover-first).
        // Once per element, so resting the pointer does not drain repeatedly.
        if (chain[0] !== this.lastUnresolved) {
          this.lastUnresolved = chain[0];
          this.onUnresolved(chain[0]);
        }
        this.clearHover();
        return;
      }
      // The CHUNK's extent: the union of every element its lines draw -- not
      // the one element that matched. A heading and its paragraph in one
      // chunk are one box.
      const rect = await this.unionRect(this.map.xpaths(hit.cid));
      const changed = !this.hover || this.hover.cid !== hit.cid;
      this.hoverSources.store++;
      this.hover = { xpath: chain[0], cid: hit.cid, matched: hit.matched, source: "store",
                     walked: hit.walked, rect, lines: this.map.xpaths(hit.cid).length,
                     at: performance.now() };
      this.placeOutline();
      const ms = performance.now() - t0;
      this.latencies.push(Math.round(ms * 10) / 10);
      if (this.latencies.length > 100) this.latencies.shift();
      void this.placeStructure(hit.cid, url);
      if (changed) {
        this.onHoverChunk(hit.cid, url);
        // Hover-first (`G-80`): the chunk under the pointer goes to the front
        // of the encoder's and the projector's queues, and the profile traces
        // how long it takes to be drawn -- its own kind, "hover".
        if (!this.focused.has(hit.cid)) {
          this.focused.add(hit.cid);
          if (this.focused.size > 500) this.focused.clear();
          void this.sidecar.focus([hit.cid]).catch(() => null);
          const prof = profiler();
          const trace = prof.begin("hover", url);
          prof.fact(trace, "cid", hit.cid);
          prof.fact(trace, "ms_outline", Math.round(ms));
          prof.watch(trace, [hit.cid], performance.now());
        }
      }
      if (this.expanded) this.draw();
    } finally {
      this.hoverBusy = false;
    }
  }

  /** The bounding box of several elements, in the page's viewport: one read. */
  private async unionRect(xpaths: string[]):
      Promise<{ x: number; y: number; w: number; h: number } | null> {
    const wv = this.webview();
    if (!wv || !xpaths.length) return null;
    return await within(wv.executeJavaScript(
      // Through the sensor's own resolver where it is loaded: it crosses
      // shadow roots, which document.evaluate cannot.
      "(function(xs){var l=1e9,t=1e9,r=-1e9,b=-1e9,any=false,h=window[" + JSON.stringify(SENSOR_HANDLE) + "];" +
      "for(var i=0;i<xs.length;i++){var n=null;try{n=h&&h.node?h.node(xs[i]):null;}catch(e){}" +
      "if(!n){try{n=document.evaluate(xs[i],document,null,9,null).singleNodeValue;}catch(e){}}" +
      "if(n&&n.nodeType===3)n=n.parentElement;if(!n||!n.getBoundingClientRect)continue;" +
      "var q=n.getBoundingClientRect();if(q.width<=0&&q.height<=0)continue;any=true;" +
      "if(q.left<l)l=q.left;if(q.top<t)t=q.top;if(q.right>r)r=q.right;if(q.bottom>b)b=q.bottom;}" +
      "return any?{x:l,y:t,w:r-l,h:b-t}:null;})(" + JSON.stringify(xpaths.slice(0, 400)) + ")"), 400);
  }

  // ---- the chunk structure around a hover (`P-B7`) -------------------------

  /** Planted: no structure, only the hovered chunk's outline (the shape before P-B7). */
  plantNoStructure = false;
  /** What the structure overlay last drew, for the harness. */
  structure: { stored: string; container: string; siblings: string[]; drawn: number;
               rects: ({ x: number; y: number; w: number; h: number } | null)[]; ms: number } | null = null;
  private structEls: HTMLElement[] = [];
  private structFor = "";

  /**
   * The chunks the hovered one is embedded among (`chunkstructure.ts`: its
   * trie node's parent, and the other chunks under it), outlined faintly on
   * the page's own layout -- one read of the page for all of them, drawn in
   * the cell above the webview, nothing written into the page.
   */
  private async placeStructure(stored: string, url: string, force = false): Promise<void> {
    if (this.plantNoStructure || !stored || this.map.url !== url) { this.clearStructure(); return; }
    if (!force && stored === this.structFor) return;
    this.structFor = stored;
    const t0 = performance.now();
    const got = embedded(stored, this.map.cids(), (c) => this.map.xpaths(c));
    if (!got.siblings.length) { this.clearStructure(true); this.structure = { stored, ...got, drawn: 0, rects: [], ms: 0 }; return; }
    const wv = this.webview();
    if (!wv) return;
    const groups = got.siblings.map((c) => this.map.xpaths(c).slice(0, 60));
    const rects: ({ x: number; y: number; w: number; h: number } | null)[] | null = await within(wv.executeJavaScript(
      "(function(gs){var h=window[" + JSON.stringify(SENSOR_HANDLE) + "];return gs.map(function(xs){" +
      "var l=1e9,t=1e9,r=-1e9,b=-1e9,any=false;for(var i=0;i<xs.length;i++){var n=null;" +
      "try{n=h&&h.node?h.node(xs[i]):null;}catch(e){}" +
      "if(!n){try{n=document.evaluate(xs[i],document,null,9,null).singleNodeValue;}catch(e){}}" +
      "if(n&&n.nodeType===3)n=n.parentElement;if(!n||!n.getBoundingClientRect)continue;" +
      "var q=n.getBoundingClientRect();if(q.width<=0&&q.height<=0)continue;any=true;" +
      "if(q.left<l)l=q.left;if(q.top<t)t=q.top;if(q.right>r)r=q.right;if(q.bottom>b)b=q.bottom;}" +
      "return any?{x:l,y:t,w:r-l,h:b-t}:null;});})(" + JSON.stringify(groups) + ")"), 400);
    // The pointer moved on while the page answered: this is not its structure.
    if (this.structFor !== stored) return;
    const rs = rects || [];
    while (this.structEls.length < rs.length) this.structEls.push(this.wrap.createDiv({ cls: "vertiscope-chunk-struct" }));
    let drawn = 0;
    this.structEls.forEach((el, i) => {
      const r = i < rs.length ? rs[i] : null;
      // Counted as DRAWN only if it is on screen: a sibling below the fold is
      // clipped to nothing by the webview's bounds.
      if (r && r.w > 0 && r.h > 0) { this.placeBox(el, r); if (el.style.display !== "none") drawn++; } else el.hide();
    });
    this.structure = { stored, ...got, drawn, rects: rs, ms: Math.round(performance.now() - t0) };
  }

  private clearStructure(keepFor = false): void {
    for (const el of this.structEls) el.hide();
    if (!keepFor) this.structFor = "";
  }

  private clearHover() {
    if (!this.hover) return;
    this.hover = null;
    this.outline.hide();
    this.clearStructure();
    this.structure = null;
    this.onHoverChunk("", "");
    if (this.expanded) this.draw();
  }

  /** The last flash's own cost: placing the boxes, and the frame they paint in. */
  diffPlaced: number[] = [];

  /**
   * Outline a drain's diff from the boxes that came back WITH the drain
   * (`G-90`): no crossing into the page, placement only. `placed` is the
   * time from the drain returning to the boxes being in position; the
   * latency recorded is to the next frame, when they are painted.
   */
  // ---- streaming outlines (D-37) --------------------------------------------
  //
  // A new chunk stays outlined from the drain that produced it until the
  // store confirms it saved -- the event that collapses its translucent node
  // in 3D (Addendum IX, step 4) -- and for at least `DWELL_MS` once it has
  // been on screen. The outline FOLLOWS it: its box is re-read from the
  // sensor's box peripheral while it streams, so content that loaded below
  // the fold is outlined when the reader scrolls to it. It was a 1.2 s flash
  // of whatever was on screen at the drain, which a reader almost never saw.
  static DWELL_MS = 1500;
  private streamTimer = 0;
  private streamBusy = false;
  /** Sensor chunk id -> when it first showed on screen (0: not yet), saved? */
  streaming = new Map<number, { shownAt: number; saved: boolean; since: number }>();
  /** Outlines drawn by the follower on its last pass, for the harness. */
  streamingShown = 0;
  /** Named defect planted by a check: the old 1.2 s flash, no following. */
  plantFlashOnly = false;

  /** A drain's new chunks start streaming. */
  markStreaming(ids: number[]): void {
    if (this.plantFlashOnly) return;
    const now = performance.now();
    for (const id of ids) {
      const had = this.streaming.get(id);
      if (had) { had.saved = false; had.since = now; } else this.streaming.set(id, { shownAt: 0, saved: false, since: now });
    }
    while (this.streaming.size > 400) this.streaming.delete(this.streaming.keys().next().value as number);
  }

  /** The store confirmed these saved: their outlines go once they have dwelt. */
  savedStreaming(ids: number[]): void {
    for (const id of ids) { const s = this.streaming.get(id); if (s) s.saved = true; }
  }

  /** A new page: nothing on it is streaming yet. */
  clearStreaming(): void {
    this.streaming.clear();
    this.diffEls.forEach((el) => el.hide());
  }

  private async followStreaming(): Promise<void> {
    if (this.streamBusy || !this.streaming.size || !this.visible()) return;
    const wv = this.webview();
    if (!wv) return;
    this.streamBusy = true;
    try {
      const now = performance.now();
      for (const [id, s] of this.streaming) {
        // Gone once saved and seen for the dwell; saved and never scrolled to
        // within 20 s is let go too, or the set would only grow.
        if (s.saved && ((s.shownAt && now - s.shownAt >= PipelineBox.DWELL_MS) || now - s.since > 20000)) {
          this.streaming.delete(id);
        }
      }
      const ids = [...this.streaming.keys()].slice(0, 64);
      if (!ids.length) { this.diffEls.forEach((el) => el.hide()); this.streamingShown = 0; return; }
      const got: any = await within<any>(wv.executeJavaScript(
        "(function(ids){var h=window[" + JSON.stringify(SENSOR_HANDLE) + "];" +
        "return h&&h.boxes?h.boxes(ids):null;})(" + JSON.stringify(ids) + ")"), 300);
      if (!got && this.keepOnMiss) return;
      const rects: (number[] | null)[] = got || [];
      while (this.diffEls.length < ids.length) {
        this.diffEls.push(this.wrap.createDiv({ cls: "vertiscope-diff-box" }));
      }
      let shown = 0;
      const t = performance.now();
      const frame = this.diffEls.length ? this.boxFrame(this.diffEls[0]) : null;
      this.diffEls.forEach((el, i) => {
        const r = i < ids.length ? rects[i] : null;
        if (!r) { el.hide(); return; }
        this.placeBox(el, { x: r[0], y: r[1], w: r[2], h: r[3] }, frame);
        if (el.style.display !== "none") {
          shown++;
          const s = this.streaming.get(ids[i]);
          if (s && !s.shownAt) s.shownAt = t;
        }
      });
      this.streamingShown = shown;
    } finally {
      this.streamBusy = false;
    }
  }

  flashBoxes(boxes: (number[] | null)[], t0: number, traceId: string, ids: number[] = []): void {
    // The drain's new chunks join the streaming set, which keeps them
    // outlined from here on; this call still paints them NOW, from the boxes
    // the drain brought, so the first paint stays in the same frame (G-90).
    if (ids.length) this.markStreaming(ids.filter((_id, i) => !!boxes[i]));
    const rects = boxes.slice(0, 64);
    while (this.diffEls.length < rects.length) {
      this.diffEls.push(this.wrap.createDiv({ cls: "vertiscope-diff-box" }));
    }
    let drawn = 0;
    const frame = this.diffEls.length ? this.boxFrame(this.diffEls[0]) : null;
    this.diffEls.forEach((el, i) => {
      const r = i < rects.length ? rects[i] : null;
      if (r) {
        this.placeBox(el, { x: r[0], y: r[1], w: r[2], h: r[3] }, frame);
        if (el.style.display !== "none") drawn++;
      } else el.hide();
    });
    const placed = performance.now() - t0;
    this.diffPlaced.push(placed);
    if (this.diffPlaced.length > 500) this.diffPlaced.shift();
    window.requestAnimationFrame(() => {
      const ms = performance.now() - t0;
      this.diffLatencies.push(ms);
      if (this.diffLatencies.length > 500) this.diffLatencies.shift();
      this.lastDiff = { at: Date.now(), asked: boxes.length, drawn, ms };
      const t = traceId ? profiler().get(traceId) : undefined;
      if (t) { profiler().stage(t, "drain_to_overlay", ms); profiler().stage(t, "overlay_placed", placed); }
    });
    window.clearTimeout(this.diffTimer);
    if (this.plantFlashOnly || !ids.length) {
      this.diffTimer = window.setTimeout(() => this.diffEls.forEach((el) => el.hide()), 1200);
    }
  }

  /**
   * Outline the chunk set a drain just changed, at once (`G-90`).
   *
   * The in-page chunking has named the chunks that moved; this draws one box
   * per chunk over the page, in one in-page read of their boxes, before the
   * capture has even left for the sidecar -- the browser's half of "fastest
   * to screen". Timed from the instant the drain came back, the same instant
   * the 3D graph's half is timed from, and the boxes fade after a moment so
   * the next diff reads as the next diff.
   */
  async flashDiff(addresses: string[], t0: number, traceId: string): Promise<void> {
    const wv = this.webview();
    if (!wv || !addresses.length) return;
    const xs = addresses.filter((a) => a.indexOf("#shadow-root") < 0).slice(0, 64);
    const rects: any[] = (await within<any>(wv.executeJavaScript(
      "(function(xs){return xs.map(function(x){var n=document.evaluate(x,document," +
      "null,XPathResult.FIRST_ORDERED_NODE_TYPE,null).singleNodeValue;" +
      "if(!n)return null;var b=n.getBoundingClientRect();" +
      "return {x:b.left,y:b.top,w:b.width,h:b.height};});})(" +
      JSON.stringify(xs) + ")"), 400).catch(() => null)) || [];
    while (this.diffEls.length < rects.length) {
      this.diffEls.push(this.wrap.createDiv({ cls: "vertiscope-diff-box" }));
    }
    let drawn = 0;
    this.diffEls.forEach((el, i) => {
      const r = rects[i];
      if (i < rects.length && r) { this.placeBox(el, r); if (el.isShown()) drawn++; }
      else el.hide();
    });
    window.requestAnimationFrame(() => {
      const ms = performance.now() - t0;
      this.diffLatencies.push(ms);
      if (this.diffLatencies.length > 500) this.diffLatencies.shift();
      this.lastDiff = { at: Date.now(), asked: addresses.length, drawn, ms };
      const t = traceId ? profiler().get(traceId) : undefined;
      if (t) profiler().stage(t, "drain_to_overlay", ms);
    });
    window.clearTimeout(this.diffTimer);
    this.diffTimer = window.setTimeout(() => this.diffEls.forEach((el) => el.hide()), 1200);
  }

  /** Each pinned chunk's box, measured in the page and outlined over it. */
  private async placePins() {
    const wv = this.webview();
    if (!wv || !this.pins.length) return;
    // **A pin is outlined on ITS page only** (`G-82`). Its side panel stays
    // when the reader browses on; its outline belongs to the page it was
    // pinned on. The fallback below evaluates the pin's xpath in whatever
    // page is showing, and pages built from one template share addresses:
    // a Radix tree paragraph pinned, then Trie opened, and the outline sat on
    // an unrelated Trie paragraph at the same address (2026-09-26).
    const here = this.url();
    const mine = this.pins.filter((p) => p.url === here);
    for (const pin of this.pins) {
      if (pin.url !== here) this.pinEls.get(pin.cid)?.hide();
    }
    if (!mine.length) return;
    // The pinned chunk's whole extent, as for hover; the matched element
    // alone only when the map does not know the chunk.
    if (this.map.url === here) {
      for (const pin of mine) {
        const el = this.pinEls.get(pin.cid);
        const xs = this.map.xpaths(pin.cid);
        if (el && xs.length) this.placeBox(el, await this.unionRect(xs));
      }
      if (mine.every((p) => this.map.xpaths(p.cid).length)) return;
    }
    const rects: any = await wv.executeJavaScript(
      "(function(xs){return xs.map(function(x){var n=document.evaluate(x,document," +
      "null,XPathResult.FIRST_ORDERED_NODE_TYPE,null).singleNodeValue;" +
      "if(n&&n.nodeType===3)n=n.parentElement;if(!n)return null;" +
      "var b=n.getBoundingClientRect();return {x:b.left,y:b.top,w:b.width,h:b.height};});})(" +
      JSON.stringify(mine.map((x) => x.matched)) + ")").catch(() => null);
    mine.forEach((pin, i) => {
      const el = this.pinEls.get(pin.cid);
      const r = rects && rects[i];
      if (el) this.placeBox(el, r || null);
    });
  }

  /** Put a fixed-position box over a guest-viewport rect, clipped to the
   *  webview and corrected for the containing block (see `pin`). */
  /** The page scrolled (pushed by the sensor): re-measure what is shown, at
   *  most once per frame. */
  private scrollFrame = 0;
  scrolls = 0;
  /** When the page last scrolled (performance.now), for work that must wait for stillness. */
  lastScrollAt = 0;
  pageScrolled(): void {
    this.scrolls++;
    this.lastScrollAt = performance.now();
    // At most every 50 ms, and only when something is outlined: a page that
    // animates its styles sends this every frame (johnwick ~450 a session).
    const now = performance.now();
    if (this.scrollFrame || now - this.lastScrollMeasure < 50) return;
    if (!this.pins.length && !this.streaming.size && !this.structFor) return;
    this.scrollFrame = window.requestAnimationFrame(() => {
      this.scrollFrame = 0;
      this.lastScrollMeasure = performance.now();
      this.keepOnMiss = true;
      const struct = this.structFor && this.hover ? this.placeStructure(this.structFor, this.url(), true) : null;
      void Promise.all([this.placePins(), this.followStreaming(), struct]).finally(() => { this.keepOnMiss = false; });
    });
  }
  private lastScrollMeasure = 0;
  /** A re-measure caused by motion keeps a box where it was when the page
   *  does not answer, instead of hiding it for a frame (the flicker). */
  private keepOnMiss = false;

  /** When a pushed hover last arrived (the poll does not overwrite it). */
  private pushedAt = 0;
  private pushedUrl = "";
  /** A new page: pushes start over (the poll draws until the sensor speaks). */
  resetPush(): void { this.pushedAt = 0; this.pushedUrl = ""; }
  /** Pushed hovers received, and their host-side handling time, for the harness. */
  pushedHovers = 0;
  pushedHandleMs: number[] = [];

  /**
   * The sensor pushed "the pointer is over chunk <id>, box x,y,w,h" (or "-").
   * Drawn at once, from the page's own chunking: no poll to wait for and no
   * crossing to make (2026-09-27: 65-138 ms from pointer move to outline).
   * The store's chunk is still resolved by the poll, for the ring in 3D.
   */
  /** Set only by the browser's planted `plantBoxesStopHover` (item 89). */
  paused = false;
  pushedHover(body: string, url: string): void {
    if (this.paused) return;
    const t0 = performance.now();
    this.pushedHovers++;
    this.pushedAt = t0;
    this.pushedUrl = url;
    if (body === "-" || !body) { this.clearHover(); return; }
    const [id, box, addr] = body.split(" ");
    const b = (box || "").split(",").map(Number);
    if (b.length !== 4 || b.some((x) => !Number.isFinite(x))) return;
    const cid = `f:${url}#${id}`;
    // The STORED chunk this in-page chunk belongs to, when the store knows the
    // page. The page's own chunking cuts finer than the store's -- a forum
    // topic row is five in-page chunks, one per cell, and ONE stored chunk --
    // and the outline drew the cell while the camera flew to, and the panel
    // showed, the whole row (2026-10-10: "This should be all one chunk, but
    // it is erroneously split up into subchunks for the same card"; item 29:
    // the outlined unit is the stored chunk).
    //
    // By the hovered element's OWN address first (the sensor sends it): the
    // store's nearest-ancestor walk, in memory. The page's chunk can be
    // COARSER than the store's -- one in-page chunk for a shadow-DOM list of
    // six stored cards -- and from its id alone every card resolved to the
    // page header (2026-10-11). The id is the fallback.
    let byAddr = this.plantPageUnit || this.plantHoverById || !addr || this.map.url !== url ? null
      : this.map.lookup(addressChain(addr));
    // Within THREE steps of the hovered element: further up, a stored chunk
    // is a container standing for a whole region -- an archive.org tile
    // walked 16 steps to the app's routed page, and its panel showed the
    // search header and a hidden feedback survey (2026-10-17). Planted: any.
    if (byAddr && (byAddr.walked || 0) > 3 && !this.plantAnyDepth) { this.farAncestors++; byAddr = null; }
    const stored = this.plantPageUnit ? "" : (byAddr ? byAddr.cid : this.storedFor(cid, url));
    // ...or the hovered ELEMENT moved: tiles sharing one in-page chunk and one
    // stored chunk were never told apart, and the panel stayed on the first
    // tile (archive.org, 2026-10-17). The graph keeps a panel per UNIT, so a
    // move within one tile renews it rather than reopening.
    const changed = !this.hover || this.hover.cid !== cid || (!!stored && this.hover.stored !== stored)
      || (!this.plantChunkOnlyNotify && !!addr && canonAddr(addr) !== canonAddr(this.hover.xpath || ""));
    // Within one stored unit the outline keeps its place -- if that place
    // holds this element too: a kept live box (see below) belongs to the
    // element it was drawn for.
    const pr = this.hover && this.hover.rect;
    const sameUnit = !!stored && !!this.hover && this.hover.stored === stored && !!pr
      && pr.x < b[0] + b[2] && pr.x + pr.w > b[0] && pr.y < b[1] + b[3] && pr.y + pr.h > b[1];
    const prev = this.hover;
    this.hover = { xpath: addr || "", cid, matched: byAddr ? byAddr.matched : "", walked: byAddr ? byAddr.walked : 0, source: "page",
                   rect: sameUnit && prev ? prev.rect : { x: b[0], y: b[1], w: b[2], h: b[3] },
                   lines: sameUnit && prev ? prev.lines : 0, at: t0, stored: stored || undefined, byAddress: !!byAddr };
    // ONE outline per hover. When the stored unit is known its extent is
    // drawn and nothing before it; the page's own box only if the stored one
    // has not arrived in 40 ms. Drawing the page's box and then the stored
    // unit's a few ms later flashed two sizes on every move (2026-10-11:
    // "overlays flicker on github"). Within one stored unit the outline
    // keeps its place.
    const xs = stored && this.map.url === url ? this.map.xpaths(stored) : [];
    if (!xs.length || sameUnit || this.plantTwoStep) this.placeOutline();
    this.pushedHandleMs.push(performance.now() - t0);
    if (this.pushedHandleMs.length > 200) this.pushedHandleMs.shift();
    if (changed) this.onHoverChunk(cid, url, stored || undefined);
    if (xs.length) {
      let drawn = !!sameUnit || this.plantTwoStep;
      const fallback = drawn ? 0 : window.setTimeout(() => {
        if (this.hover && this.hover.at === t0 && !drawn) { drawn = true; this.placeOutline(); this.twoStepFallbacks++; }
      }, 40);
      void this.unionRect(xs).then((r) => {
        window.clearTimeout(fallback);
        if (!this.hover || this.hover.at !== t0) return;
        // The stored unit's outline must hold what is under the pointer. Its
        // xpaths were recorded when the page was stored; on a page that has
        // moved since (YouTube's feed, archive.org's cards) they resolve to
        // OTHER elements, and the outline was drawn 40+ px from the pointer on
        // 18 of 27 YouTube hovers (2026-10-11). Not touching the page's own
        // live box for the hovered chunk, it is not this hover's outline: the
        // live box is kept. Planted: the stored union, wherever it lands.
        const live = { x: b[0], y: b[1], w: b[2], h: b[3] };
        const meets = !!r && r.x < live.x + live.w && r.x + r.w > live.x && r.y < live.y + live.h && r.y + r.h > live.y;
        if (r && !meets && !this.plantStaleUnion) this.unionFallbacks++;
        else if (r) this.hover = { ...this.hover, rect: r, lines: xs.length };
        drawn = true;
        this.placeOutline();
        if (stored) void this.placeStructure(stored, url);
        this.storedUnitMs.push(performance.now() - t0);
        if (this.storedUnitMs.length > 200) this.storedUnitMs.shift();
      });
    }
  }
  /** Planted: the graph is told only when the hovered CHUNK changes (one panel for every tile). */
  plantChunkOnlyNotify = false;
  /** Planted: a stored ancestor at any depth covers a hover (the 16-step walk). */
  plantAnyDepth = false;
  /** Hovers whose nearest stored ancestor was too far up to stand for them. */
  farAncestors = 0;
  /** Planted: resolve a pushed hover by its in-page chunk id only (before 2026-10-11). */
  plantHoverById = false;
  /** Planted: the page's box first, then the stored unit's (the flicker). */
  plantTwoStep = false;
  /** Hovers whose stored unit took longer than 40 ms (the page's box shown meanwhile). */
  twoStepFallbacks = 0;
  /** Hovers whose stored unit resolved away from the pointer: the live box kept. */
  unionFallbacks = 0;
  /** Planted (G-163): the stored unit's union drawn wherever its xpaths now land. */
  plantStaleUnion = false;

  /** In-page chunk -> the stored chunk it belongs to (set by the browser cell). */
  storedFor: (cid: string, url: string) => string = () => "";
  /** Planted: outline the page's own (finer) chunk, never the stored unit. */
  plantPageUnit = false;
  /** Push -> stored-unit outline, ms, for the harness. */
  storedUnitMs: number[] = [];

  /**
   * The two reads every box's position depends on, taken ONCE per batch: the
   * webview's rect and the boxes' positioned parent's. Placing a box used to
   * write it, read it back and correct it -- a forced layout per box, up to 64
   * per drain: G-90 measured placement p95 31 ms on a 356-chunk drain.
   */
  private boxFrame(el: HTMLElement): { wb: DOMRect; ox: number; oy: number } | null {
    const wv = this.webview();
    if (!wv) return null;
    const wb = wv.getBoundingClientRect();
    // A `position: fixed` box is placed against the VIEWPORT, unless an
    // ancestor forms its containing block (a transform, filter, perspective,
    // contain or will-change). Subtracting the parent's offset regardless
    // drew every diff box up and left of its chunk by the parent's position
    // -- measured 2026-10-06: a box at y=104 over a cell starting at y=168,
    // "the tracked overlay actually slides off the page's bounds".
    if (getComputedStyle(el).position === "fixed") {
      let a = el.parentElement;
      while (a && a !== document.body) {
        const cs = getComputedStyle(a);
        if ((cs.transform && cs.transform !== "none") || (cs.filter && cs.filter !== "none")
            || (cs.perspective && cs.perspective !== "none") || /paint|layout|strict|content/.test(cs.contain || "")
            || /transform|filter|perspective/.test(cs.willChange || "")) {
          const r = a.getBoundingClientRect();
          return { wb, ox: r.left + a.clientLeft, oy: r.top + a.clientTop };
        }
        a = a.parentElement;
      }
      return { wb, ox: 0, oy: 0 };
    }
    const op = (el.offsetParent || el.parentElement) as HTMLElement | null;
    if (!op) return { wb, ox: 0, oy: 0 };
    const pr = op.getBoundingClientRect();
    return { wb, ox: pr.left + op.clientLeft - op.scrollLeft, oy: pr.top + op.clientTop - op.scrollTop };
  }

  private placeBox(el: HTMLElement, r: { x: number; y: number; w: number; h: number } | null,
                   frame?: { wb: DOMRect; ox: number; oy: number } | null) {
    const wv = this.webview();
    if (!r || !wv || r.w <= 0 || r.h <= 0) { el.hide(); return; }
    if (frame) {
      const wb = frame.wb;
      const left = wb.left + Math.max(0, r.x), top = wb.top + Math.max(0, r.y);
      const right = wb.left + Math.min(wb.width, r.x + r.w), bottom = wb.top + Math.min(wb.height, r.y + r.h);
      if (right <= left || bottom <= top) { el.hide(); return; }
      Object.assign(el.style, { left: `${left - frame.ox}px`, top: `${top - frame.oy}px`,
                                width: `${right - left}px`, height: `${bottom - top}px` });
      el.show();
      return;
    }
    const wb = wv.getBoundingClientRect();
    const left = wb.left + Math.max(0, r.x);
    const top = wb.top + Math.max(0, r.y);
    const right = wb.left + Math.min(wb.width, r.x + r.w);
    const bottom = wb.top + Math.min(wb.height, r.y + r.h);
    if (right <= left || bottom <= top) { el.hide(); return; }
    Object.assign(el.style, {
      left: `${left}px`, top: `${top}px`,
      width: `${right - left}px`, height: `${bottom - top}px`,
    });
    el.show();
    const got = el.getBoundingClientRect();
    const dx = got.left - left, dy = got.top - top;
    if (Math.abs(dx) >= 1 || Math.abs(dy) >= 1) {
      el.style.left = `${left - dx}px`;
      el.style.top = `${top - dy}px`;
    }
  }

  /** The outline sits in the CELL over the webview, never in the page. */
  /** Outline placements, for the harness: against `pushedHovers`, how many draws a hover costs. */
  outlinePlacements = 0;
  private placeOutline() {
    this.outlinePlacements++;
    const r = this.hover?.rect;
    const wv = this.webview();
    if (!r || !wv || r.w <= 0 || r.h <= 0) { this.outline.hide(); return; }
    // The webview fills the wrap, so a guest-viewport rect IS a wrap rect,
    // offset by wherever the webview sits inside it.
    // Viewport coordinates throughout: the outline is `position: fixed`, and
    // a guest-viewport rect plus the webview's own on-screen origin IS a
    // window rect -- clipped to the webview so it never draws over the
    // toolbar or a neighbouring pane.
    const wb = wv.getBoundingClientRect();
    const left = wb.left + Math.max(0, r.x);
    const top = wb.top + Math.max(0, r.y);
    const right = wb.left + Math.min(wb.width, r.x + r.w);
    const bottom = wb.top + Math.min(wb.height, r.y + r.h);
    if (right <= left || bottom <= top) { this.outline.hide(); return; }
    Object.assign(this.outline.style, {
      left: `${left}px`, top: `${top}px`,
      width: `${right - left}px`, height: `${bottom - top}px`,
    });
    this.outline.show();
    // Same correction as `pin`: a transformed ancestor, not the viewport, is
    // the containing block, so viewport coordinates land offset by its
    // origin. Measure once, shift by the difference.
    const got = this.outline.getBoundingClientRect();
    const dx = got.left - left, dy = got.top - top;
    if (Math.abs(dx) >= 1 || Math.abs(dy) >= 1) {
      this.outline.style.left = `${left - dx}px`;
      this.outline.style.top = `${top - dy}px`;
    }
  }

  // ---- the projector's side, read from the scene ------------------------

  private inProjector(url: string) {
    const g: any = profiler().graphSource ? profiler().graphSource!() : null;
    if (!g || !url) return null;
    try {
      const nodes = g.graphData().nodes as any[];
      let chunks = 0, hub = false, hovered = false, force = 0, forceAll = 0;
      for (const n of nodes) {
        // The force tree (`G-89`) is drawn from the drains, not the store:
        // counted apart, so "in graph" never mixes the two.
        if (n.force) { forceAll++; if (n.url === url) force++; continue; }
        if (n.url !== url) continue;
        if (n.level === "page") hub = true;
        else chunks++;
        if (this.hover && n.id === this.hover.cid) hovered = true;
      }
      return { chunks, hub, hovered, force, forceAll };
    } catch {
      return null;
    }
  }

  // ---- drawing ----------------------------------------------------------

  /**
   * Pin the box to the bottom-right of the WEBVIEW, wherever it is.
   *
   * Fixed positioning against the webview's own rect rather than an
   * absolute child of the cell: the cell's wrap is not a positioned
   * container, and making it one would re-anchor the search overlay that
   * already lives there -- a change nobody asked for.
   */
  private pin() {
    const wv = this.webview();
    const wb = wv ? wv.getBoundingClientRect() : null;
    if (!wb || wb.width < 40 || wb.height < 40) { this.el.hide(); return; }
    this.el.show();
    this.el.style.maxHeight = `${Math.round(wb.height - 20)}px`;
    // Measured, then corrected. `position: fixed` resolves against the
    // nearest transformed ancestor, not the viewport, and Obsidian's
    // workspace has one: computing `right` from `window.innerWidth` put the
    // box 310 px left of the browser's corner, exactly the width of the
    // sidebar that ancestor does not span. Whatever the containing block is,
    // the difference between where the box landed and where it should be
    // is the correction.
    const wantRight = wb.right - 10, wantBottom = wb.bottom - 10;
    let right = parseFloat(this.el.style.right) || (window.innerWidth - wantRight);
    let bottom = parseFloat(this.el.style.bottom) || (window.innerHeight - wantBottom);
    for (let i = 0; i < 2; i++) {
      this.el.style.right = `${Math.round(right)}px`;
      this.el.style.bottom = `${Math.round(bottom)}px`;
      const got = this.el.getBoundingClientRect();
      const dx = got.right - wantRight, dy = got.bottom - wantBottom;
      if (Math.abs(dx) < 1 && Math.abs(dy) < 1) break;
      right += dx;
      bottom += dy;
    }
  }

  private draw() {
    this.pin();
    const url = this.url();
    const s = this.status && this.status.url === url ? this.status : null;
    const proj = this.inProjector(url);
    const traces = profiler().list().filter((t) => t.url === url);
    const last = traces.slice(-1)[0];
    const lastSeen = [...traces].reverse().find((t) => t.stages && t.stages.end_to_end);
    // Against what the page can DRAW: a duplicate or a merge-group member is
    // never a node (`G-25`, `G-27`), so all-stored is the wrong denominator
    // -- it read "599/688" on a page with every drawable chunk on screen.
    const drawable = s ? (s.drawable ?? s.chunks) : 0;
    const healthy = s && proj && drawable > 0 && proj.chunks >= drawable && proj.hub;

    // ---- collapsed: one line -------------------------------------------
    this.mini.empty();
    const dot = this.mini.createSpan({ cls: "vertiscope-pipebox-dot" });
    dot.addClass(!s ? "is-idle" : healthy ? "is-ok" : "is-warn");
    if (!s || !url || url === "about:blank") {
      this.mini.createSpan({ text: "pipeline idle" });
    } else {
      const parts: string[] = [];
      if (lastSeen) parts.push(fmt(lastSeen.stages.end_to_end));
      parts.push(proj && proj.forceAll
        ? `${proj.force} in the force tree`
        : `${proj ? proj.chunks : "?"}/${drawable} in graph`);
      this.mini.createSpan({ text: parts.join(" · ") });
    }

    this.expanded = this.userOpen || this.peek;
    this.el.toggleClass("is-open", this.userOpen);
    if (!this.expanded) { this.full.hide(); return; }
    this.full.show();
    this.dyn.empty();
    // The stage profile, mounted once and left to redraw itself (`G-76`).
    if (!this.readout) {
      this.readout = new ProfileReadout(this.profileHost, this.sidecar);
      void this.readout.mount();
    }
    // The live checks come first: they do not depend on a page being loaded
    // (`G-75`), and a run is worth seeing on a blank browser too.
    this.drawChecks();
    if (!s) {
      this.dyn.createDiv({ cls: "vertiscope-pipebox-muted",
        text: url && url !== "about:blank" ? "asking the sidecar…" : "no page loaded" });
      return;
    }

    // ---- the chain every chunk travels ------------------------------------
    this.section("This page's chunks");
    const chain = this.dyn.createDiv({ cls: "vertiscope-pipebox-chain" });
    const step = (label: string, n: number | string, of: number, ok: boolean) => {
      const c = chain.createDiv({ cls: `vertiscope-pipebox-step ${ok ? "is-ok" : "is-warn"}` });
      c.createDiv({ cls: "vertiscope-pipebox-n", text: String(n) });
      c.createDiv({ cls: "vertiscope-pipebox-l", text: label });
      if (typeof n === "number" && of) c.title = `${n} of ${of}`;
    };
    step("stored", s.chunks, s.chunks, s.empty_md === 0);
    step("embedded", s.embedded, s.chunks, s.embedded >= s.chunks);
    step("projected", s.projected ?? "?", drawable,
         typeof s.projected === "number" && s.projected >= drawable);
    step("in graph", proj ? proj.chunks : "?", drawable, !!proj && proj.chunks >= drawable);
    step("page hub", proj ? (proj.hub ? "yes" : "no") : "?", 0, !!proj && proj.hub);
    if (s.empty_md) this.line(`${s.empty_md} chunks stored with no markdown`, true);
    if (proj && !proj.hub && proj.chunks > 0) {
      this.line("chunks are in the graph with no page node to hang from", true);
    }
    if (proj && proj.forceAll) {
      this.line(`force tree: ${proj.force} nodes for this page, ${proj.forceAll} in all -- ` +
                "drawn from the drains, before any embedding (G-89)");
    }

    this.line(`window ${s.window} tokens · chunk p50 ${s.tokens_p50}, max ${s.tokens_max}` +
              (s.over_window ? ` · ${s.over_window} OVER the window` : " · none over"),
              s.over_window > 0);

    // ---- fastest to screen: one drain, two outputs (`G-90`) ------------------
    {
      const view: any = profiler().graphView ? profiler().graphView!() : null;
      const scene: number[] = view?.forceStats?.toScene || [];
      const over = this.diffLatencies;
      if (over.length || scene.length) {
        this.section("Drain to screen");
        const q = (xs: number[], p: number) => {
          if (!xs.length) return null;
          const s = xs.slice().sort((a, b) => a - b);
          return s[Math.min(s.length - 1, Math.floor(p * s.length))];
        };
        const placed = this.diffPlaced;
        this.line(`page overlay placed ${fmt(placed[placed.length - 1])} (p95 ${fmt(q(placed, 0.95))}) · ` +
                  `painted ${fmt(over[over.length - 1])} (p95 ${fmt(q(over, 0.95))}, n ${over.length})` +
                  (this.lastDiff ? ` · ${this.lastDiff.drawn}/${this.lastDiff.asked} chunks outlined` : ""));
        this.line(`3D graph ${fmt(scene[scene.length - 1])} (p95 ${fmt(q(scene, 0.95))}, n ${scene.length})` +
                  (view ? ` · ${view.layoutMode}` : ""));
      }
    }

    // ---- the last drain ----------------------------------------------------
    if (last) {
      this.section(`Last drain · ${String(last.facts?.outcome || "?")}` +
                   (last.facts?.why ? ` (${last.facts.why})` : ""));
      const st = last.stages || {};
      const strip = this.dyn.createDiv({ cls: "vertiscope-pipebox-strip" });
      for (const [k, label] of [
        ["fold", "fold"], ["sidecar.absorb", "trie"], ["sidecar.render", "markdown"],
        ["sidecar.store", "store"], ["vector_wait", "embed"], ["sidecar.place", "place"],
        ["visible", "drawn"], ["end_to_end", "total"],
      ] as [string, string][]) {
        if (typeof st[k] !== "number") continue;
        const cell = strip.createDiv({ cls: "vertiscope-pipebox-cell" });
        cell.createDiv({ cls: "vertiscope-pipebox-n", text: fmt(st[k]) });
        cell.createDiv({ cls: "vertiscope-pipebox-l", text: label });
      }
      const f = last.facts || {};
      const flow: string[] = [];
      if (typeof f.chunks_in_drain === "number") flow.push(`${f.chunks_in_drain} chunks folded`);
      if (typeof f.dirty === "number") flow.push(`${f.dirty} changed`);
      if (typeof f.placed === "number") flow.push(`${f.placed} sent to the projector`);
      if (f.queued_for_placement) flow.push(`${f.queued_for_placement} waiting on vectors`);
      if (flow.length) this.line(flow.join(" · "));
    }
    const recent = traces.filter((t) => performance.now() - t.t0 < 30000);
    this.line(`${recent.length} drains in the last 30 s · encoder queue ${s.embed_queue}`);

    // ---- the fit ------------------------------------------------------------
    this.section("Projector fit");
    const pj = s.projector;
    if (pj) {
      // The chunk projector: one fit, a stream into it, a refit at 2x.
      // The epoch is an identity in milliseconds; say when the fit was made.
      const when = new Date(pj.epoch).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
      this.line(`fit of ${when} · UMAP on a sample of ${pj.fit_sample.toLocaleString()} · ` +
                `${pj.projected.toLocaleString()} chunks placed by transform`);
      this.line(`stream: ${pj.placed_total.toLocaleString()} transformed since the fit · ` +
                `queue ${pj.queue}` + (pj.fitting ? " · REFITTING in the background" : ""),
                pj.queue > 256);
    }
    if (s.fitted_chunks) {
      const growth = s.growth || 0;
      const bar = this.dyn.createDiv({ cls: "vertiscope-pipebox-growth" });
      const fill = bar.createDiv({ cls: "vertiscope-pipebox-growthfill" });
      fill.style.width = `${Math.min(100, (growth / 2) * 100)}%`;
      this.line(`${s.chunks_now.toLocaleString()} chunks against ${s.fitted_chunks.toLocaleString()} ` +
                `fitted · ${growth.toFixed(2)}× of the 2× refit` +
                (s.stale ? " · REFIT DUE" : ""), !!s.stale);
      this.line(`this page's anchor: ${s.anchor}` +
                (s.anchor === "estimated" ? " (placed into the fit, refit will fit it)" : ""),
                s.anchor === "none");
    } else {
      // Said as what it is: the projector has no fit yet. The graph is
      // usually open -- it draws the force tree meanwhile.
      this.line(proj && proj.forceAll
        ? "no fit yet — the graph shows the force tree until the projector fits"
        : "no fit yet — the projector fits once enough chunks have vectors", !(proj && proj.forceAll));
    }

    // ---- under the pointer ------------------------------------------------
    this.section("Under the pointer");
    if (!this.hover) {
      this.line("hover a part of the page to follow its chunk", false, true);
    } else {
      const h = this.hover;
      this.line(`${h.cid} · ${h.lines} lines` +
                (h.walked ? ` · ${h.walked} ancestors above what you point at` : ""));
      this.line(`in the projector: ${proj?.hovered ? "yes, ringed" : "not drawn yet"}`,
                !proj?.hovered);
    }
  }

  /**
   * Hardware-in-the-loop checks: the same list `confirm.mjs` runs, executed by
   * the plugin in this window. Whoever started the run -- a reader here, an
   * MCP tool, the terminal client -- its progress and failures show here.
   */
  private drawChecks() {
    const v: any = (window as any).__vertiscope?.verify;
    if (!v) return;
    const st: any = v.state();
    this.section("Checks, run in this app");
    const row = this.dyn.createDiv({ cls: "vertiscope-pipebox-line" });
    if (st.running) {
      row.setText(`running ${st.done}/${st.total} · ${st.current}` +
                  (st.label ? ` · ${st.label}` : ""));
    } else if (st.run) {
      const passed = st.results.filter((r: any) => r.pass).length;
      const secs = Math.round((st.finishedAt - st.startedAt) / 1000);
      const when = new Date(st.finishedAt).toTimeString().slice(0, 5);
      row.setText(`${passed} of ${st.results.length} pass · ${secs} s · ${when}` +
                  (st.label ? ` · ${st.label}` : "") +
                  (st.stoppedBecause ? ` · stopped: ${st.stoppedBecause}` : ""));
      if (passed < st.results.length) row.addClass("is-warn");
    } else {
      row.setText("not run in this session");
      row.addClass("vertiscope-pipebox-muted");
    }
    if (!st.running) {
      const go = row.createEl("button", { text: "run all", cls: "vertiscope-pipebox-run" });
      go.onclick = (e) => { e.stopPropagation(); v.start(); this.draw(); };
      // The same checks on a store this app starts empty and fills itself.
      const fresh = row.createEl("button", { text: "fresh store", cls: "vertiscope-pipebox-run" });
      fresh.title = "start an empty store, fill it by browsing, run every check, switch back";
      fresh.onclick = (e) => { e.stopPropagation(); v.startFresh(); this.draw(); };
    }
    // A fresh-store run's own steps: what it browsed, and that it put the
    // app back afterwards.
    const seed = st.seed || [];
    if (seed.length) {
      const held = seed.filter((r: any) => r.held).length;
      const last = seed[seed.length - 1];
      this.line(`seeded ${held} of ${seed.length} pages · ${last.chunks ?? "?"} chunks`,
                held < seed.length);
      for (const r of seed.filter((x: any) => !x.held)) {
        this.line(`not held: ${String(r.url).slice(0, 60)}`, true);
      }
    }
    if (st.teardown) {
      this.line(`back on ${st.teardown.sidecar} · test sidecar ` +
                (st.teardown.test_sidecar_stopped ? "stopped" : "STILL RUNNING"),
                !st.teardown.test_sidecar_stopped);
    }
    // EVERY verdict, not only the failures: this box is where a run is
    // read (2026-09-26: "you observe the results within the app itself"),
    // so a pass has to be visible as a pass, with how long it took. A
    // failure carries its evidence inline -- a tooltip is invisible to a
    // reader and to anyone reading the box -- trimmed to what fits.
    const list = this.dyn.createDiv({ cls: "vertiscope-pipebox-checks" });
    for (const r of st.results || []) {
      const f = list.createDiv({
        cls: `vertiscope-pipebox-check ${r.pass ? "is-ok" : "is-warn"}` });
      f.dataset.id = r.id;
      f.dataset.pass = r.pass ? "1" : "0";
      f.createSpan({ cls: "vertiscope-pipebox-mark", text: r.pass ? "✓" : "✗" });
      f.createSpan({ cls: "vertiscope-pipebox-id", text: r.id });
      f.createSpan({ text: ` ${r.asks} · ${fmt(r.ms)}` });
      if (!r.pass) {
        f.createDiv({ cls: "vertiscope-pipebox-evidence",
                      text: JSON.stringify(r.evidence ?? null).slice(0, 360) });
      }
    }
    if (st.running && st.current) {
      list.createDiv({ cls: "vertiscope-pipebox-check vertiscope-pipebox-muted",
                       text: `… ${st.current}` });
    }
  }

  private section(title: string) {
    this.dyn.createDiv({ cls: "vertiscope-pipebox-h", text: title });
  }

  private line(text: string, warn = false, muted = false) {
    this.dyn.createDiv({
      cls: `vertiscope-pipebox-line${warn ? " is-warn" : ""}${muted ? " vertiscope-pipebox-muted" : ""}`,
      text,
    });
  }
}

function fmt(ms: number | null | undefined): string {
  if (typeof ms !== "number" || !Number.isFinite(ms)) return "—";
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)} s`;
  if (ms >= 10) return `${Math.round(ms)} ms`;
  return `${ms.toFixed(1)} ms`;
}
