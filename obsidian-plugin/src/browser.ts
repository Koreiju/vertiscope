/**
 * The browser cell: a real Electron browser, in a panel, beside its markdown.
 *
 * `G-36`..`G-42`. One component with two hosts -- this standalone pane, and
 * later a cell inside the notebook -- with the same functionality in both,
 * the standalone being the expanded view.
 *
 * **`<webview>`, not `BrowserView` or `WebContentsView`, and the reason is
 * layout.** All three are available here (measured in the running app:
 * Electron 39.8.3, Chrome 142, `webviewTag` on, `@electron/remote` reachable,
 * both view classes present). The other two are OS-level surfaces positioned
 * in window coordinates: they float *above* the DOM and have to be
 * repositioned by hand on every resize, split, tab change and scroll. `G-36`
 * asks for a browser that resizes within the notebook and with the panel
 * around it, and a `<webview>` is an element -- it flows, it splits, it
 * scrolls, and Obsidian's own layout moves it without being told.
 *
 * **Nothing is written into the page** (`G-41`, and constraint 7). The
 * highlight and the retrieval overlay are drawn in Obsidian's DOM, above the
 * webview, never as script injected into the document. The webview's own
 * `webContents` carries a CDP debugger, which is how the sensor will read the
 * page (`G-47`) -- reading, not writing.
 *
 * **One session.** A single `partition` across every browser cell, so that
 * clicking a node in the projector navigates the browser the reader already
 * has, cookies and scroll position and all, rather than opening a fresh one
 * that has never seen the site (`G-40`).
 */

import { ForceTree, type ForceNodeDelta } from "./forcetree";
import { PipelineBox } from "./pipelinebox";
import { profiler } from "./profile";
import { Component, ItemView, MarkdownRenderer, Menu, WorkspaceLeaf } from "obsidian";
import { putFavicon, putPictures } from "./snapshot";
import { Snapshot, dropSnapshot, getSnapshot, putSnapshot, renderSnapshot, snapshotScript, xpathsOfLines } from "./snapshot";

import { LayoutNode } from "./graph";
import { Sidecar } from "./sidecar";
import { EnactResult, SearchHit } from "./types";
import { ActRecord, ActResult, PanelAction, addressTable, chainFor, parseAddressKey } from "./panelact";

export const BROWSER_VIEW = "domvec-browser-view";

/**
 * The session every browser cell shares.
 *
 * `persist:` makes it survive a restart. Without the prefix Electron gives an
 * in-memory session, and a reader would be logged out of every site each time
 * the pane was closed -- which would also mean the sensor scanned a different
 * page than the one the reader browsed.
 */
const PARTITION = "persist:domvec";

/**
 * Where the sensor's drain handle lives on the page's `window`.
 *
 * Fixed rather than randomised, unlike the Selenium path, which picks a fresh
 * name per scan so a page cannot learn to look for it. Here the reader is
 * driving their own browser at a page they chose, and a stable name is what
 * lets a second scan of the same page reuse the fold instead of rebuilding
 * it -- which is the whole point of an O(delta) sensor.
 */
const HANDLE = "__domvecSensor";

/** How many times to scroll and drain again. The Selenium path sweeps a page
 *  the same way: a document that loads on scroll has not finished being
 *  itself when it first paints. */
const SCROLLS = 6;

/** How far one scroll step moves, as a fraction of the viewport (`S-8`).
 *
 *  Finer than the 0.9 it replaces. A lazy loader keyed on an element nearing
 *  the fold fires once per step, so a coarse jump can carry a trigger past
 *  the viewport before anything is asked for -- the pass then drains a page
 *  that has not started loading yet, and reads as settled.
 *
 *  **Tuned, like the pause, and for a measured reason.** A flat 0.5 turned
 *  one page into 15 passes against the old cadence's 8, and since every
 *  pass costs a drain and a capture round trip the scan came out SLOWER
 *  (7.9s against 6.2s) for exactly the same 26 addresses. Fine steps are
 *  worth their cost only where the page is actually producing, so the step
 *  grows while drains come back empty and collapses back the moment one
 *  does not. The row asks for fine-grained AND time-efficient, and a fixed
 *  step can only be one of them. */
const SCROLL_STEP = 0.5;
const SCROLL_STEP_MAX = 1.6;

/** The tuned pause between a scroll and the drain that follows it.
 *
 *  **Tuned per visit rather than fixed, which is the whole of `S-8`.** The
 *  700ms constant was a guess every page paid: a static page waited 4.9
 *  seconds to be told six times that nothing had changed, and a page that
 *  loads slowly was drained before it had loaded. The loop multiplies the
 *  pause up while drains keep producing dirty chunks and down while they
 *  come back empty, which is the page's own update rate measured rather
 *  than assumed.
 *
 *  In trie terms nothing about WHAT is written changes -- each drain still
 *  carries one delta into the trie. What is tuned is WHEN the next delta is
 *  asked for, and when to stop asking. */
const PAUSE_START_MS = 400;
const PAUSE_MIN_MS = 120;
const PAUSE_MAX_MS = 1500;

/** Consecutive empty drains AT THE BOTTOM before a page is called settled.
 *
 *  Two, not one: a single empty drain is also what a page in the middle of
 *  a fetch looks like. */
const QUIET_PASSES = 2;

/** Hard stops, so a page that never settles still terminates. A ticker or
 *  a carousel rewrites forever and would otherwise scroll for as long as
 *  the reader allowed. */
const MAX_PASSES = 40;
const MAX_SCAN_MS = 25000;

/** Long enough for a lazy loader to have run, short enough that a reader
 *  watching the pane does not think it has hung. */
const PAUSE_MS = 700;

/**
 * How often the live sensor drains while the reader browses.
 *
 * The sensor debounces its own fold at 80ms and a drain returns only what
 * changed since the last one, so this is not a sampling rate for the page --
 * it is how often the picture catches up. Just over a second is slow enough
 * that a page settling after load is drained two or three times rather than
 * thirty, and fast enough that a reader scrolling sees nodes appear while
 * they are still looking at what produced them.
 */
const LIVE_MS = 1200;

/** How many results one window of the ranking carries (`G-69`). */
const PAGE_SIZE = 12;


/** Elements that sit inside a line of text (mirrors `markdown._INLINE_TAGS`). */
const INLINE_TAGS = new Set([
  "a", "abbr", "b", "bdi", "bdo", "br", "cite", "code", "data", "del", "dfn",
  "em", "i", "img", "ins", "kbd", "mark", "math", "q", "s", "samp", "small",
  "span", "strong", "sub", "sup", "time", "u", "var", "wbr",
]);

/** What a pinned chunk holds: read from the store, never from the page. */
interface PinRecord {
  cid: string; url: string; matched: string; markdown: string; head: string;
  /** The elements the chunk's lines draw, for the page-faithful snapshot (D-36). */
  xpaths?: string[];
  /** The trie's address for each of those elements, so the snapshot can carry it (G-111). */
  addrs?: Record<string, [string, number]>;
}

/**
 * The prefix the sensor's pushed signals carry on the page's console: a
 * control character, and a nonce per plugin load. The page can write to its
 * own console, and a fixed prefix would let it forge a drain into the store;
 * the nonce lives only in the sensor's closure.
 */
const SIGNAL = "\u0001domvec:" + Math.random().toString(36).slice(2, 10) + ":";

/** A url's DOCUMENT: the same page with or without a #fragment. */
function docKey(u: string): string {
  return String(u || "").split("#")[0];
}

/** One queued capture: a drain's payload, or the settle of a page left. */
interface CaptureJob {
  url: string;
  payload?: any;
  trace?: any;
  drainIds?: string[];
  title?: string;
  settle?: boolean;
  done?: () => void;
  /** When it was queued (performance.now), for the backlog it waited in. */
  queuedAt?: number;
  /** Traces of the drains merged into this one capture. */
  merged?: any[];
}

/**
 * Consecutive drains of one page as ONE capture (2026-09-28: "I'm also
 * surprised that the database ingests leave out so many diffed chunks for
 * *so long*"). Captures ran one per drain, one at a time -- 0.9 s p50 on a
 * small store, 5-6 s on the reader's -- while a scroll drains several times a
 * second, so the queue grew for as long as the reader scrolled and a diff
 * waited behind every drain before it. A sensor payload is incremental, so
 * drains merge in order: the dictionary, shapes and moves concatenated (the
 * last `stats.dictSize` is the running total, which is what the sidecar's
 * restart check compares); each chunk at its LATEST emission; a chunk emitted
 * and then removed dropped; the host's own fields (boxes, pictures) left out.
 */
export function mergePayloads(ps: any[]): any {
  if (ps.length === 1) return ps[0];
  const last = ps[ps.length - 1];
  const out: any = { ...last, dict: [], shapes: [], moves: [], removed: [], chunks: [] };
  const byId = new Map<string, any>();
  for (const p of ps) {
    for (const d of p.dict || []) out.dict.push(d);
    for (const x of p.shapes || []) out.shapes.push(x);
    for (const m of p.moves || []) out.moves.push(m);
    for (const r of p.removed || []) out.removed.push(r);
    for (const c of p.chunks || []) { byId.delete(String(c.id)); byId.set(String(c.id), c); }
  }
  const removed = new Set(out.removed.map(String));
  out.chunks = [...byId.values()].filter((c) => !removed.has(String(c.id)));
  delete out.boxes; delete out.pictures; delete out.inpage;
  return out;
}

export class BrowserView extends ItemView {
  /** Fetched once per app run and shared: it is one file on disk and it does
   *  not change under a running plugin. */
  private static sensorSource = "";
  /** The sensor's `repairMs` is cumulative; this is the last value
   *  seen, so each drain's `fold` stage is its own share. */
  private lastRepairMs: number | undefined;
  /**
   * Chunks stored but not yet placeable, waiting on the embedder -- and the
   * trace each came from, so the profile's end-to-end includes the wait.
   * Keyed by cid; a later drain that re-dirties a chunk replaces its entry.
   */
  private pendingPlace = new Map<string, { trace: string; since: number }>();
  private placeTimer = 0;
  private placing = false;
  private webview: any = null;
  private address!: HTMLInputElement;
  private status!: HTMLElement;
  private browserWrap!: HTMLElement;
  private markdownWrap!: HTMLElement;
  /** The page and the markdown side, side by side (`G-78`). */
  private split!: HTMLElement;
  /** Right-clicked chunks, newest first. Each is outlined on the page, shown
   *  on the markdown side and open as a billboard in the graph -- one
   *  selection, three surfaces, closed together. */
  private pinned = new Map<string, PinRecord>();

  /** True while a drain is in flight, so a slow one cannot be lapped. */
  private draining = false;
  /** Live capture on? The reader's switch, and it starts on. */
  private live = true;
  /** What the last `scan` cost and how it paced itself (`S-8`). Public so a
   *  live check can read the pacing rather than re-deriving it: a check that
   *  reimplements what it measures can be wrong in either direction. */
  lastScan: {
    passes: number; elapsedMs: number; rewrites: number; addresses: number;
    pauses: number[]; steps: number[]; settled: boolean;
    meanPauseMs: number; mode: string;
  } = { passes: 0, elapsedMs: 0, rewrites: 0, addresses: 0,
        pauses: [], steps: [], settled: false, meanPauseMs: 0, mode: "" };
  /** The url the current capture session belongs to. A navigation ends one
   *  session and begins another, and the old one has to be settled first or
   *  its last delta never becomes a complete write. */
  private session = "";
  private liveButton!: HTMLElement;

  // --- the retrieval overlay (`G-42`, `G-63`, `G-69`, `G-70`) ------------
  private overlay!: HTMLElement;
  private results!: HTMLElement;
  private scopeButton!: HTMLElement;
  private queryInput!: HTMLInputElement;
  /** Which shadow DOM the ranking is restricted to, or "" for the corpus.
   *  Named `rankScope` because `ItemView` already has a `scope`, and it is a
   *  keymap. */
  private rankScope = "";
  //: `G-38` asks for HOVER and this is a RIGHT-CLICK, which is a real gap
  //  and not a shortcut. Measured, before settling for it:
  //
  //    * the host never sees the cursor. A `mousemove` listener on the
  //      `<webview>` element caught 0 events while the pointer crossed it;
  //      the guest swallows them.
  //    * `Overlay.setInspectMode` attaches and paints -- `Overlay.highlightNode`
  //      was seen to shade a product card, drawn by Chromium with nothing
  //      added to the document -- but it reported no node for synthetic
  //      input, on hover OR click: three `Input.dispatchMouseEvent` moves
  //      and a full press/release yielded only `DOM.setChildNodes`.
  //
  //  So the only way to the literal requirement is a `mousemove` listener
  //  inside the page, and constraint 7 forbids writing into the page. That
  //  is the user's call to make, not this file's. What is built is the
  //  correspondence itself, on the gesture that does work.
  private hits: SearchHit[] = [];
  /** How deep the reader has scrolled the ranking. `G-69`: the cutoff is a
   *  decision they make by stopping, so this only ever grows. */
  private offset = 0;
  private more = false;
  private fetching = false;
  private debounce = 0;

  constructor(leaf: WorkspaceLeaf, private sidecar: Sidecar,
              private onChunks: (nodes: LayoutNode[],
                                 edges?: { source: string; target: string }[],
                                 trace?: string)
                => void = () => {},
              //: What the reader has scrolled to, for the projector to
              //: open the page to (`G-55`, `G-56`).
              private onHits: (url: string, cids: string[]) => void =
                () => {}) {
    super(leaf);
  }

  getViewType(): string { return BROWSER_VIEW; }
  getDisplayText(): string { return "domvec browser"; }
  getIcon(): string { return "globe"; }

  async onOpen(): Promise<void> {
    const root = this.contentEl;
    root.empty();
    root.addClass("domvec-browser");

    const bar = root.createDiv({ cls: "domvec-browser-bar" });
    const back = bar.createEl("button", { text: "←" });
    const fwd = bar.createEl("button", { text: "→" });
    const reload = bar.createEl("button", { text: "⟳" });
    this.address = bar.createEl("input", { cls: "domvec-browser-url" });
    this.address.type = "text";
    this.address.placeholder = "url";
    const scan = bar.createEl("button", { text: "scan" });
    this.liveButton = bar.createEl("button", { text: "live ●" });

    // The overlay, above the page and never inside it (`G-41`). This is
    // Obsidian's own DOM drawn over the webview, not script written into the
    // document -- the distinction the constraint exists for.
    const search = root.createDiv({ cls: "domvec-browser-search" });
    this.queryInput = search.createEl("input", { cls: "domvec-query" });
    this.queryInput.type = "text";
    this.queryInput.placeholder = "search the corpus";
    this.scopeButton = search.createEl("button", { text: "everywhere" });
    this.scopeButton.onclick = () => this.setScope(this.rankScope
      ? "" : (this.webview ? this.webview.getURL() : ""));
    const clear = search.createEl("button", { text: "×" });
    clear.onclick = () => { this.queryInput.value = ""; this.showResults([]); };

    this.split = root.createDiv({ cls: "domvec-browser-split" });
    this.browserWrap = this.split.createDiv({ cls: "domvec-browser-page" });
    this.overlay = this.browserWrap.createDiv({ cls: "domvec-overlay" });
    this.results = this.overlay.createDiv({ cls: "domvec-overlay-list" });
    this.overlay.hide();
    this.markdownWrap = this.split.createDiv({ cls: "domvec-browser-md" });
    this.markdownWrap.hide();
    this.markdownWrap.createDiv({ cls: "domvec-browser-empty" }).setText(
      "Double right-click a chunk in the browser to pin it here.");

    this.status = root.createDiv({ cls: "domvec-browser-status" });

    // Built with `createElement` rather than `createEl`: Obsidian's helper
    // types against HTMLElementTagNameMap, and `webview` is not in it.
    const view = document.createElement("webview") as any;
    view.setAttribute("partition", PARTITION);
    // `allowpopups` stays OFF. A page that opens a window would put a browser
    // outside the panel, outside the session, and outside anything the
    // projector knows about.
    view.setAttribute("src", "about:blank");
    view.style.width = "100%";
    view.style.height = "100%";
    this.browserWrap.appendChild(view);
    this.webview = view;
    // The pipeline, over the page being browsed: a box in the cell's corner
    // and the hovered chunk's outline. Both live in the CELL, never in the
    // page (`G-41`). Hover rings the projector through the same `onHover`
    // the right-click path uses, read at call time because the plugin
    // assigns it after construction.
    this.pipebox?.destroy();
    // Guarded: the box failing to build must not take the rest of the cell
    // with it. It did once -- a throw here skipped every listener registered
    // below it (right-click, navigation, the live tick) with no error shown.
    try {
      this.pipebox = new PipelineBox(this.browserWrap, this.sidecar,
                                     () => this.webview,
                                     (cid, url) => this.onHover(cid, url));
      // Hover-first (`G-80`): the pointer is over something the store does
      // not hold yet, so drain now instead of on the next tick.
      this.pipebox.onUnresolved = () => { if (!this.draining) void this.tick(); };
      this.pipebox.setPins(this.pinList());
    } catch (err) {
      console.error("domvec: the pipeline box failed to build", err);
      this.pipeboxError = String((err as any)?.stack || err).slice(0, 400);
      this.pipebox = null;
    }

    view.addEventListener("did-start-loading", () => this.say("loading…"));
    // The sensor's PUSHED signals (2026-09-27): "dirty" -- chunks are ready,
    // drain now instead of on the next 1.2 s tick; "hover <id> <box>" -- the
    // pointer is over this chunk, outline it now instead of on the next poll.
    view.addEventListener("console-message", (e: any) => {
      const m = String((e && e.message) || "");
      if (!m.startsWith(SIGNAL)) return;
      const body = m.slice(SIGNAL.length);
      if (body.startsWith("drain ")) {
        // The drain itself, sent from the task that folded it.
        let payload: any = null;
        try { payload = JSON.parse(body.slice(6)); } catch { return; }
        this.pushedPayloads++;
        void this.onPushedDrain(payload);
      } else if (body === "dirty") {
        this.pushedDrains++;
        if (!this.draining) void this.tick();
        else this.drainAgain = true;
      } else if (body.startsWith("hover ")) {
        // Planted by D-40's check: the old path, hover found by the poll.
        if (this.plant.has("poll-hover")) return;
        // The reader's pointer moving over the page is the reader using the app
        // (unless a check or a stress run is going: their synthetic moves are
        // not the reader).
        if (!(window as any).__domvec?.verify?.state?.()?.running && !(window as any).__domvecStressing) {
          (window as any).__domvecReaderAt = Date.now();
        }
        this.pipebox?.pushedHover(body.slice(6), this.session || "");
      }
    });
    // The page's own icon, as the webview reports it for the tab (G-81).
    view.addEventListener("page-favicon-updated", (e: any) => {
      const list = (e && e.favicons) || [];
      try { if (list.length) putFavicon(view.getURL(), String(list[0])); } catch { /* not attached */ }
    });
    // The document is ready to read once dom-ready fires, whatever the network
    // is still doing; a new main-frame navigation (not an in-page one) resets it.
    view.addEventListener("dom-ready", () => { this.domReady = true; });
    view.addEventListener("did-start-navigation", (e: any) => {
      if (e && e.isMainFrame && !e.isInPlace && !e.isSameDocument) this.domReady = false;
    });
    view.addEventListener("did-stop-loading", () => {
      this.address.value = view.getURL();
      try {
        const u = view.getURL();
        if (/^https?:/.test(u)) (this.app as any).saveLocalStorage?.("domvec-browser-last", u);
      } catch { /* not attached */ }
      this.say(view.getTitle() || view.getURL());
      // A load finishing is when a page becomes worth reading. Booting here
      // rather than on `did-navigate` means the sensor folds a document that
      // exists, instead of one still being parsed.
      void this.pageChanged(view.getURL());
    });
    // An in-page navigation -- a route change in a single-page app -- leaves
    // the document and the sensor's handle intact but makes the address a
    // lie. The sensor reports the page's own url in every payload for this
    // reason; the SESSION still has to move, or the new route's chunks are
    // filed under the old one.
    view.addEventListener("did-navigate-in-page", (e: any) => {
      // A #fragment is the SAME document: following an anchor link started
      // a new page ("Radix_tree#PATR" stored beside "Radix_tree", 2026-09-27).
      const sameDoc = (a: string, c: string) => a.split("#")[0] === c.split("#")[0];
      if (e && e.isMainFrame && this.session && sameDoc(String(e.url || view.getURL()), this.session)) {
        this.address.value = view.getURL();
        return;
      }
      if (e && e.isMainFrame) {
        this.address.value = view.getURL();
        void this.pageChanged(view.getURL());
      }
    });
    // Right-click pins the chunk under the cursor: its markdown beside the
    // page (`G-39`, `G-78`). The event is the WEBVIEW's, raised in the host -- nothing is
    // listening inside the page, and nothing is written into it. The one
    // read it does take is `elementFromPoint` at the cursor, on demand.
    view.addEventListener("context-menu", (e: any) => {
      const p = e && e.params;
      if (!p) return;
      // The event reports the point in the OBSIDIAN WINDOW's coordinates,
      // not the page's: a right-click at (200, 200) in the page arrived as
      // (1088, 368) with the cell in the right half of the window. Handed to
      // the page's `elementFromPoint` as-is, every point landed outside the
      // 808 px guest -- "nothing under the cursor" on every right-click
      // whenever the cell was not at the window's left edge (2026-09-26).
      const r = view.getBoundingClientRect();
      const x = (Number(p.x) || 0) - r.left;
      const y = (Number(p.y) || 0) - r.top;
      // A DOUBLE right-click pins; a single one is the browser's own menu
      // (2026-09-26: "double-right-click with a certain debounce would
      // actually be better for pinning ... keeps regular right click
      // interactions for the electron browser"). The menu waits out the
      // debounce, so a second click inside it pins instead of opening it.
      const now = performance.now();
      const prev = this.lastRight;
      if (now - prev.at < BrowserView.DOUBLE_RIGHT_MS
          && Math.hypot(x - prev.x, y - prev.y) < 16) {
        window.clearTimeout(this.menuTimer);
        this.lastRight = { at: 0, x: 0, y: 0 };
        this.lastGesture = "pin";
        void this.portMarkdown(x, y);
        return;
      }
      this.lastRight = { at: now, x, y };
      window.clearTimeout(this.menuTimer);
      this.menuTimer = window.setTimeout(() => this.contextMenu(p, x, y),
                                         BrowserView.DOUBLE_RIGHT_MS);
    });

    view.addEventListener("did-fail-load", (e: any) => {
      // -3 is ABORTED, which is what a redirect away from a page reports.
      // Showing it as a failure would make every redirect look broken.
      if (e.errorCode !== -3) this.say(`did not load: ${e.errorDescription}`);
    });

    back.onclick = () => { if (view.canGoBack()) view.goBack(); };
    fwd.onclick = () => { if (view.canGoForward()) view.goForward(); };
    reload.onclick = () => view.reload();
    this.address.addEventListener("keydown", (e: KeyboardEvent) => {
      if (e.key === "Enter") this.go(this.address.value);
    });
    scan.onclick = () => this.scan();

    // Debounced, because a ranking runs over the corpus and a keystroke is
    // not a question. 250ms is long enough that typing a word costs one
    // query and short enough that the list feels attached to the keyboard.
    this.queryInput.addEventListener("input", () => {
      window.clearTimeout(this.debounce);
      this.debounce = window.setTimeout(() => { void this.runQuery(); }, 250);
    });
    // Continuous scrolling, not a page of top-k (`G-69`). The ranking is a
    // total order and the reader ends it by stopping, so nearing the bottom
    // asks for more rather than offering a "next" button.
    this.results.addEventListener("scroll", () => {
      const box = this.results;
      if (box.scrollTop + box.clientHeight > box.scrollHeight - 120) {
        void this.runQuery(true);
      }
    });
    this.liveButton.onclick = () => this.setLive(!this.live);

    // One timer for the life of the pane, registered so Obsidian stops it
    // when the view closes. A timer per navigation would leak one per page a
    // reader visits, and they would all still be draining.
    this.registerInterval(window.setInterval(() => { void this.tick(); },
                                             LIVE_MS));

    this.say("ready");
    // Back where the reader was (2026-09-27: after a window reload the cell
    // came back on about:blank, and "nothing showing in the obsidian
    // browser" was the report). The last page is remembered per vault.
    try {
      const last = String((this.app as any).loadLocalStorage?.("domvec-browser-last") || "");
      if (last && /^https?:/.test(last) && !/[?&](d3[5-7]|g9[34]|d36)=/.test(last)) {
        window.setTimeout(() => this.go(last), 300);
      }
    } catch { /* storage unavailable: start blank */ }
  }

  async onClose(): Promise<void> {
    this.pipebox?.destroy();
    this.pipebox = null;
    // Settle whatever page was being captured. Per-drain writes are deltas;
    // a pane closed mid-page would leave the store holding the last delta
    // rather than the finished trie.
    if (this.session) {
      const leaving = this.session;
      this.session = "";
      void this.sidecar.capture(leaving, { settle: true });
    }
    // The element goes with the DOM; the browsing SESSION is deliberately
    // left alone, since it is shared and persistent by design.
    this.webview = null;
  }

  /**
   * Lay the cell out: the PAGE, always, and the markdown side beside it
   * whenever a chunk is pinned (`G-82`).
   *
   * There is no second face any more. Addendum IV's "switchable second
   * view" -- the markdown alone, full width, behind a toggle -- was replaced
   * by Addendum VII's follow-up: the browser stays the main surface and
   * pinned chunks are side panels. A face that hid the page also hid every
   * outline on it, which is what the pins exist to show.
   */
  private layoutSide(): void {
    const side = this.pinned.size > 0;
    this.browserWrap.show();
    this.markdownWrap.toggle(side);
    this.markdownWrap.toggleClass("is-side", side);
  }

  /** The pins, newest first, for the corner box's outlines. */
  private pinList() {
    return [...this.pinned.values()].map((p) => ({
      cid: p.cid, matched: p.matched, url: p.url }));
  }

  /** Two right-clicks closer together than this pin; one alone opens the menu. */
  static DOUBLE_RIGHT_MS = 350;
  private lastRight = { at: 0, x: 0, y: 0 };
  private menuTimer = 0;
  /** What the last right-click gesture did -- "menu" or "pin" -- for the harness. */
  lastGesture = "";
  /** The items of the last context menu shown, for the harness. */
  lastMenu: string[] = [];

  /**
   * The browser's own context menu, for a single right-click: what a reader
   * expects from a browser at that point -- the link, the image, the
   * selection -- plus navigation and the pin, with its shortcut named.
   * `p` is the webview's context-menu params (window coordinates).
   */
  private contextMenu(p: any, x: number, y: number): void {
    const menu = new Menu();
    const items: string[] = [];
    const add = (title: string, icon: string, run: () => void) => {
      items.push(title);
      menu.addItem((i) => i.setTitle(title).setIcon(icon).onClick(run));
    };
    const copy = (text: string) => { void navigator.clipboard.writeText(text); };
    if (p.linkURL) {
      add("Open link in new tab", "external-link", () => void this.openInNewTab(p.linkURL));
      add("Open link here", "arrow-right", () => this.go(p.linkURL));
      add("Copy link address", "link", () => copy(p.linkURL));
    }
    if (p.mediaType === "image" && p.srcURL) {
      add("Open image in new tab", "image", () => void this.openInNewTab(p.srcURL));
      add("Copy image address", "copy", () => copy(p.srcURL));
    }
    if (p.selectionText) add("Copy", "copy", () => copy(p.selectionText));
    if (p.isEditable) add("Paste", "clipboard-paste", () => this.webview?.paste());
    menu.addSeparator();
    const wv = this.webview;
    if (wv?.canGoBack()) add("Back", "arrow-left", () => wv.goBack());
    if (wv?.canGoForward()) add("Forward", "arrow-right", () => wv.goForward());
    add("Reload", "rotate-cw", () => wv?.reload());
    menu.addSeparator();
    add("Pin this chunk (double right-click)", "pin", () => void this.portMarkdown(x, y));
    this.lastMenu = items;
    this.lastGesture = "menu";
    menu.showAtPosition({ x: Number(p.x) || 0, y: Number(p.y) || 0 });
  }

  /** A new browser cell in its own tab, on `url`. */
  private async openInNewTab(url: string): Promise<void> {
    const leaf = this.app.workspace.getLeaf("tab");
    await leaf.setViewState({ type: "domvec-browser-view", active: true });
    const v: any = leaf.view;
    for (let i = 0; i < 20 && !(v && v.webview); i++) await new Promise((r) => setTimeout(r, 100));
    if (v && typeof v.go === "function") v.go(url);
  }

  /** Told by the plugin: a drain's delta, decoded here, for the force tree
   *  (`G-89`) -- before the capture's round trip. */
  onDrain: (delta: ForceNodeDelta) => void = () => {};
  /** One chunk tree per page, fed by that page's drains. */
  private forceTrees = new Map<string, ForceTree>();

  /** Told by the plugin: force nodes a capture processed and the store did
   *  not keep -- never pending. */
  onUnstored: (url: string, ids: string[]) => void = () => {};
  /** Force ids a capture has shown the store does not keep. */
  private unstoredIds = new Set<string>();
  /** The same knowledge by page and ADDRESS: a sensor instance renumbers its
   *  chunks on every landing, so id-keyed memory forgot page furniture each
   *  visit and it flashed as the diff again (G-91: 22 boxes on a stored page). */
  private unstoredAt = new Map<string, Set<string>>();

  /** Addresses on `url` a capture has shown the store does not keep. */
  private unstoredOn(url: string): Set<string> {
    let s = this.unstoredAt.get(url);
    if (!s) { s = new Set(); this.unstoredAt.set(url, s); }
    return s;
  }
  /** Told by the plugin: the reader is leaving this page (not yet settled). */
  onLeaving: (url: string) => void = () => {};
  /** Told by the plugin: the reader left this page and it is settled. */
  onLeft: (url: string) => void = () => {};
  /** Told by the plugin: force nodes whose content a stored chunk now covers. */
  onCovers: (url: string, covers: Record<string, string>, settled: string[]) => void = () => {};

  /**
   * Which stored chunk draws each address, from the renderer's chunk map
   * (`chunkmap.ts`) -- the chunk anchored at the address, beneath it, or at
   * its nearest ancestor. A force node is the PENDING diff only while this
   * finds nothing the projector has drawn (`G-89`): on a page the store
   * already holds, the first drain names every chunk, and all but the diff
   * are covered.
   */
  /** Of `covers`, the ids whose chunk the store held when the page was
   *  landed on -- already transformed, so never pending. */
  private settledOf(url: string, covers: Record<string, string>): string[] {
    const map = this.pipebox?.map;
    if (!map || map.url !== url) return [];
    return Object.entries(covers).filter(([, cid]) => map.stored.has(cid)).map(([id]) => id);
  }

  private coversFor(url: string, items: { id: string; address: string }[]): Record<string, string> {
    const map = this.pipebox?.map;
    const out: Record<string, string> = {};
    if (!map || map.url !== url) return out;
    for (const it of items) {
      // The address itself, or a stored chunk anchored BENEATH it -- never an
      // ancestor: a new paragraph inside a stored section is not covered by
      // the section, it is the diff.
      // ... or at the nearest BLOCK ancestor, walking up through inline
      // elements only: a bold word or a link inside a stored paragraph has
      // no anchor of its own (its text is joined into the paragraph's line),
      // and Trie drew 133 such fragments as pending over its projected
      // chunks. A new paragraph is a block, so it still stops here.
      const chain = [it.address];
      let a = it.address;
      while (true) {
        const cut = a.lastIndexOf("/");
        const tag = a.slice(cut + 1).split("[")[0].toLowerCase();
        if (cut <= 0 || !INLINE_TAGS.has(tag)) break;
        a = a.slice(0, cut);
        chain.push(a);
      }
      const hit = map.lookup(chain);
      if (hit) out[it.id] = hit.cid;
    }
    return out;
  }
  /** Told by the plugin: a capture rewrote these chunks. */
  onDirty: (cids: string[]) => void = () => {};
  /** Told by the plugin: a pinned chunk opened in the graph. */
  onPin: (cid: string) => void = () => {};
  /** Told by the plugin: a pinned chunk was let go. */
  onUnpin: (cid: string) => void = () => {};

  /** Let a pinned chunk go: its outline, its markdown and its billboard. */
  unpin(cid: string): void {
    if (!this.pinned.delete(cid)) return;
    this.pipebox?.setPins(this.pinList());
    void this.renderSide();
    this.onUnpin(cid);
    this.layoutSide();
  }

  /**
   * Keep what was just pinned where the reader can see it (`G-78`).
   *
   * The first pin opens the side panel, which narrows the page, and the
   * reflow can carry the pinned element out of the viewport: measured on the
   * Radix tree page, a paragraph pinned at y 60+ sat at y -242 a second
   * later, so its outline -- the thing the pin exists to show -- had nowhere
   * to be drawn. After the layout settles, an element that left the view is
   * brought back to its middle. Scrolling is a reader's action on the page,
   * not a write into it.
   */
  private async keepInView(xpath: string): Promise<void> {
    const wv = this.webview;
    if (!wv || !xpath) return;
    await new Promise((r) => setTimeout(r, 120));
    await wv.executeJavaScript(
      "(function(x){var n=document.evaluate(x,document,null," +
      "XPathResult.FIRST_ORDERED_NODE_TYPE,null).singleNodeValue;" +
      "if(n&&n.nodeType===3)n=n.parentElement;if(!n)return false;" +
      "var b=n.getBoundingClientRect();" +
      "if(b.bottom>0&&b.top<innerHeight)return false;" +
      "n.scrollIntoView({block:'center',behavior:'instant'});return true;})(" +
      JSON.stringify(xpath) + ")").catch(() => false);
  }

  /** Which chunks are pinned -- for the harness. */
  pinnedState() {
    return [...this.pinned.values()].map((p) => ({
      cid: p.cid, url: p.url, matched: p.matched,
      lines: p.markdown.split("\n").length }));
  }

  /** Last snapshot outcome, for the harness: what was read and how much. */
  lastSnapshot: { cid: string; ok: boolean; elements: number; found: number; asked: number; ms: number; why?: string } | null = null;

  /**
   * Read the chunk's own elements from the live page (D-36) -- only when the
   * page open in the cell is the chunk's page. True if a snapshot was taken
   * and differs from the one held.
   */
  private async takeSnapshot(read: PinRecord): Promise<boolean> {
    const wv = this.webview;
    const t0 = performance.now();
    const asked = (read.xpaths || []).length;
    const note = (ok: boolean, why: string, s: any = null) => {
      this.lastSnapshot = { cid: read.cid, ok, elements: s ? s.elements : 0, found: s ? s.found : 0,
                            asked, ms: Math.round(performance.now() - t0), why: why || undefined };
    };
    if (!wv || !asked) { note(false, "no page or no xpaths"); return false; }
    let here = "";
    try { here = wv.getURL(); } catch { /* not attached */ }
    if (here !== read.url) { note(false, "page not open"); return false; }
    if (this.plant.has("distilled-panels")) {
      dropSnapshot(read.cid);
      note(false, "planted: distilled only");
      return false;
    }
    try {
      const snap = await wv.executeJavaScript(snapshotScript(read.xpaths || [], read.addrs || {}));
      if (!snap || !snap.html) { note(false, "nothing found"); return false; }
      const before = getSnapshot(read.cid);
      putSnapshot(read.cid, snap as Snapshot);
      note(true, "", snap);
      return !before || before.html !== snap.html;
    } catch (e) {
      note(false, String(e).slice(0, 80));
      return false;
    }
  }

  /** The largest rendered picture per drained chunk (force id -> src). */
  private drainPics = new Map<string, string>();
  /** Told when stored chunks get their most relevant picture. Set by the plugin. */
  onPictures: (byCid: Record<string, string>) => void = () => {};

  /** Drains the sensor asked for (pushed), for the harness. */
  pushedDrains = 0;
  /** Drains that arrived as payloads on the console channel (D-40). */
  pushedPayloads = 0;
  /** A push arrived mid-drain: drain again as soon as this one ends. */
  private drainAgain = false;

  /** The current document has fired dom-ready (drains may run while loading). */
  private domReady = false;

  /**
   * A snapshot of `cid` for the 3D billboard (2026-09-27: "the 3D gui is not
   * reflecting the same structure of panel as in the clipboard"): taken now,
   * from the live page, when the chunk's page is the one open in the cell.
   * False when it cannot be (another page is open, or nothing is found).
   */
  async snapshotChunk(cid: string, url: string): Promise<boolean> {
    if (!cid || getSnapshot(cid)) return !!getSnapshot(cid);
    let here = "";
    try { here = this.webview?.getURL() || ""; } catch { /* not attached */ }
    if (!here || docKey(here) !== docKey(url || "")) return false;
    const payload: any = await this.sidecar.chunk(cid).catch(() => null);
    const lines = (payload && payload.lines) || [];
    if (!lines.length) return false;
    await this.takeSnapshot({ cid, url: here, matched: "", markdown: "", head: "",
                              xpaths: xpathsOfLines(lines), addrs: addressTable(lines) });
    return !!getSnapshot(cid);
  }

  /**
   * Start capture over (the plugin's sidecar changed under the cell): the
   * session and the force trees are dropped, so the next load starts a new
   * capture session with a fresh sensor -- a sensor's dictionary belongs to
   * the sidecar it was talking to.
   */
  restartCapture(): void {
    this.session = "";
    this.forceTrees.clear();
    this.unstoredIds.clear();
    this.unstoredAt.clear();
    this.captureQueue = [];
    this.pipebox?.clearStreaming();
  }

  /** Named defects a check can plant through the plugin (non-vacuity arms). */
  plant = new Set<string>();

  /** The markdown side: one card per pinned chunk, natively rendered. */
  private async renderSide(): Promise<void> {
    this.markdownWrap.empty();
    if (!this.pinned.size) {
      this.markdownWrap.createDiv({ cls: "domvec-browser-empty" }).setText(
        "Double right-click a chunk in the browser to pin it here.");
      return;
    }
    for (const pin of this.pinned.values()) {
      const card = this.markdownWrap.createDiv({ cls: "domvec-pin-card" });
      card.dataset.cid = pin.cid;
      // The card is the pin's handle in the slate: clicking it brings the
      // chunk's billboard back in the 3D view, expanded (2026-09-26).
      card.onclick = (e: MouseEvent) => {
        if ((e.target as HTMLElement)?.closest?.(".domvec-pin-close, a")) return;
        this.onPin(pin.cid);
      };
      const head = card.createDiv({ cls: "domvec-browser-mdhead" });
      // The site, not the xpath: the address is kept as the tooltip.
      let host = "";
      try { host = new URL(pin.url).host; } catch { /* not a url */ }
      head.createSpan({ text: host || pin.head }).setAttr("title", pin.head);
      const close = head.createSpan({ cls: "domvec-pin-close", text: "\u00d7" });
      close.setAttr("aria-label", "unpin");
      close.onclick = () => this.unpin(pin.cid);
      const body = card.createDiv({ cls: "domvec-browser-mdbody" });
      // The chunk as the BROWSER draws it (D-36), when the page gave one; the
      // distilled markdown one click away -- and alone when the page is not
      // open to read from.
      const snap = getSnapshot(pin.cid);
      if (snap) {
        body.addClass("has-snapshot");
        renderSnapshot(body, snap, {
          maxHeight: 640, onLink: (h) => this.go(h), cid: pin.cid,
          onAct: (rec) => this.actOnChunk(pin.cid, rec),
        });
        const more = card.createEl("details", { cls: "domvec-pin-md" });
        more.createEl("summary", { text: "markdown" });
        const md = more.createDiv({ cls: "domvec-browser-mdbody" });
        await MarkdownRenderer.render(this.app, pin.markdown, md, "",
                                      this as unknown as Component);
        continue;
      }
      // The NATIVE renderer (`G-37`): the same content as an Obsidian
      // markdown panel, rendering the full markdown.
      await MarkdownRenderer.render(this.app, pin.markdown, body, "",
                                    this as unknown as Component);
    }
  }

  /** Navigate. Bare hosts get https, because a reader types `arxiv.org`. */
  go(where: string): void {
    if (!this.webview || !where.trim()) return;
    const url = /^[a-z]+:/i.test(where) ? where : `https://${where}`;
    this.address.value = url;
    this.webview.loadURL(url);
    this.layoutSide();
  }

  /** Restrict the ranking to one shadow DOM, or release it (`G-70`). */
  //: Told the plugin, which tells the projector (`G-38`). Brokered, like
  //  every other cross-pane signal here: neither pane may require the other.
  onHover: (cid: string, url: string) => void = () => {};
  /** The pipeline overlay; see `pipelinebox.ts`. */
  pipebox: PipelineBox | null = null;
  /** Why the overlay did not build, if it did not -- read by the harness. */
  pipeboxError = "";

  setScope(url: string): void {
    this.rankScope = url || "";
    this.scopeButton.setText(this.rankScope ? "this page" : "everywhere");
    this.scopeButton.title = this.rankScope || "ranked over the whole corpus";
    void this.runQuery();
  }

  /**
   * Ask for the next window of the ranking (`G-69`).
   *
   * `more === true` asks for the slice after what is already shown; anything
   * else starts again from the top. Guarded against re-entry, because the
   * scroll handler fires on every frame of a flick and each one would
   * otherwise launch a ranking.
   */
  private async runQuery(more = false): Promise<void> {
    const query = this.queryInput.value.trim();
    if (!query) { this.showResults([]); return; }
    if (this.fetching) return;
    if (more && !this.more) return;
    this.fetching = true;
    try {
      const offset = more ? this.offset : 0;
      const got = await this.sidecar.search(query, {
        k: PAGE_SIZE, offset, url: this.rankScope || undefined });
      if (!got) { this.say("no sidecar"); return; }
      this.more = !!got.more;
      this.offset = offset + got.hits.length;
      this.showResults(more ? this.hits.concat(got.hits) : got.hits);
      // Tell the projector what the reader has reached. Only when the
      // ranking is scoped to a page: opening every page a corpus-wide
      // ranking touched is the 12,820-node picture again, arrived at from
      // the other direction.
      if (this.rankScope) {
        this.onHits(this.rankScope, this.hits.map((h) => h.cid));
      }
      this.say(`${this.hits.length} of the ranking` +
               (this.rankScope ? " · this page" : "") +
               ` · ${got.tokens} tok`);
    } finally {
      this.fetching = false;
    }
  }

  /** Draw the ranking. */
  private showResults(hits: SearchHit[]): void {
    this.hits = hits;
    this.results.empty();
    this.overlay.toggle(hits.length > 0);
    hits.forEach((hit, i) => {
      const row = this.results.createDiv({ cls: "domvec-hit" });
      const head = row.createDiv({ cls: "domvec-hit-head" });
      head.createSpan({ cls: "domvec-hit-rank", text: String(i + 1) });
      head.createSpan({ cls: "domvec-hit-url", text: hit.url });
      if ((hit.members ?? 1) > 1) {
        head.createSpan({ cls: "domvec-hit-tag",
                          text: `${hit.members} merged` });
      }
      head.createSpan({ cls: "domvec-hit-tag",
                        text: `${hit.tokens ?? 0} tok` });
      // Which factor fired, not the product. The product of three small
      // numbers reads as zero and says nothing about why this ranked.
      head.createSpan({
        cls: "domvec-hit-score",
        text: `lex ${(hit.lexical ?? 0).toFixed(2)} · ` +
              `sem ${(hit.semantic ?? 0).toFixed(2)}`,
      });
      row.createDiv({ cls: "domvec-hit-preview", text: hit.preview });
      row.onclick = () => { void this.goToHit(hit); };
    });
  }

  /**
   * Take the browser to a result (`G-42`).
   *
   * Navigate if it is elsewhere, then bring the chunk into view. The scroll
   * is done by evaluating the chunk's xpath and calling `scrollIntoView` --
   * a READ of the document and a movement of the viewport, not a write into
   * it. Nothing about the page changes; what changes is which part of it the
   * reader is looking at, which is what they asked for.
   */
  /**
   * Show an address, from wherever the ask came from (`G-40`, `G-58`).
   *
   * Clicking a node in the projector drives the browser to that chunk: the
   * SAME session the reader was already in, scrolled to the place, rather
   * than a second rendering of the page beside the first. That is the whole
   * of §O.5 -- three representations collapsing into one -- and the
   * machinery for it was already here and private, reachable only from the
   * overlay's own result rows.
   */
  async reveal(url: string, xpath = ""): Promise<boolean | null> {
    if (!url) return null;
    return (await this.arrive(url, xpath)).found;
  }

  private async goToHit(hit: SearchHit): Promise<void> {
    await this.arrive(hit.url, hit.xpath || "");
  }

  /**
   * Take the cell to `url`, and the element at `xpath` into view, and say what
   * happened: whether it had to navigate, and whether the xpath resolved
   * (`found`: null when no xpath was asked for or the page could not be
   * reached). The one road both a retrieval click (`G-42`) and a panel gesture
   * (`G-111`) take before anything else is done to the page.
   *
   * The xpath is resolved with the document's own `evaluate`, which cannot
   * spell a `#shadow-root` step: for an element inside a shadow tree `found`
   * is false here while the sensor (which walks the composed tree) can still
   * reach it -- so a caller about to ACT reads `found` as a report, not a veto.
   */
  private async arrive(url: string, xpath: string):
      Promise<{ navigated: boolean; found: boolean | null }> {
    const wv = this.webview;
    if (!wv) return { navigated: false, found: null };
    let navigated = false;
    if (docKey(wv.getURL()) !== docKey(url)) {
      navigated = true;
      this.go(url);
      for (let i = 0; i < 40; i++) {
        await new Promise((r) => setTimeout(r, 400));
        if (!wv.isLoading()) break;
      }
    }
    if (!xpath) return { navigated, found: null };
    try {
      const found = await wv.executeJavaScript(`(function () {
        var r = document.evaluate(${JSON.stringify(xpath)}, document,
          null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);
        var n = r.singleNodeValue;
        if (!n) return false;
        if (n.nodeType === 3) n = n.parentElement;
        if (!n) return false;
        n.scrollIntoView({block: "center"});
        return true;
      })()`);
      this.say(found ? `at ${xpath}`
                     : `the page no longer has ${xpath}`);
      return { navigated, found: !!found };
    } catch (e) {
      this.say(`could not reach it: ${String(e).slice(0, 80)}`);
      return { navigated, found: null };
    }
  }

  /**
   * Carry a panel's gesture out on the LIVE page (`G-111`).
   *
   * The chunk panel is a view of trie addresses, and a control in it is the
   * page's control seen through its address. Pressing it:
   *
   *   1. asks the sidecar to adjudicate the address (`--enact` flag, the trie
   *      holds it, the refusal set) -- the url and xpath used below are the
   *      STORED ones it hands back, not the panel's;
   *   2. brings the cell to the page (navigating if it is elsewhere) and
   *      scrolls the element into view, reporting whether the xpath resolved;
   *   3. performs the action in the page through the sensor's `perform`
   *      (click, type, choose), which refuses the never-press set again
   *      against what the element says now.
   *
   * Nothing else is written: no listener, no global, no attribute. The page's
   * own handlers run on the event, the sensor sees the mutation and drains it
   * like any other, and the panel re-reads -- it keeps no state of its own.
   * The events are synthetic (`isTrusted: false`), so a site that checks it
   * will not respond.
   */
  async actOn(rec: ActRecord): Promise<ActResult> {
    if (this.plant.has("act-noop")) {
      return { ok: false, stage: "planted", error: "planted: actOn does nothing" };
    }
    const wv = this.webview;
    if (!wv) return { ok: false, stage: "navigate", error: "no browser cell" };
    const plan = await this.sidecar.enactPlan(rec.key, rec.action, rec.value);
    if (!plan) return { ok: false, stage: "plan", error: "no answer from the sidecar" };
    if (plan.error || !plan.ok || !plan.url || !plan.xpath || !plan.kind) {
      return { ok: false, stage: "plan", refused: !!plan.refused,
               error: plan.error || plan.detail || "the sidecar did not adjudicate it" };
    }
    const at = await this.arrive(plan.url, plan.xpath);
    if (at.navigated) {
      for (let i = 0; i < 40 && !this.domReady; i++) await new Promise((r) => setTimeout(r, 250));
    }
    if (!(await this.ensureSensor())) {
      return { ok: false, stage: "sensor", navigated: at.navigated, scrolled: at.found ?? undefined,
               error: "the sensor is not in the page" };
    }
    let out: any = null;
    try {
      out = await wv.executeJavaScript(`(function (c) {
        var h = window[${JSON.stringify(HANDLE)}];
        if (!h || !h.perform) return { nosensor: true };
        if (!h.xpathTicks) return { stale: true };
        return h.perform(c);
      })(${JSON.stringify(chainFor(plan.kind, plan.xpath, rec.value))})`);
    } catch (e) {
      return { ok: false, stage: "perform", navigated: at.navigated, scrolled: at.found ?? undefined,
               error: `the page went away mid-gesture: ${String(e).slice(0, 80)}` };
    }
    const base = { navigated: at.navigated, scrolled: at.found ?? undefined };
    if (!out || out.nosensor || out.stale) {
      return { ok: false, stage: "sensor", ...base,
               error: out && out.stale ? "this page's sensor predates panel gestures: reload the page"
                                       : "the sensor is not in the page" };
    }
    const failed: [string, string][] = out.failed || [];
    if (failed.length) {
      const refused = failed.some((f) => f[1] === "refused");
      return { ok: false, stage: "perform", refused, ...base, url: out.url, done: out.done, failed,
               error: refused ? "refused in the page: the never-press set names this element"
                              : failed.map((f) => `${f[0]}: ${f[1]}`).join("; ") };
    }
    this.say(`${rec.action} · ${plan.label || plan.xpath}`);
    return { ok: true, stage: "done", ...base, url: out.url, done: out.done,
             did: `${rec.action}${plan.label ? " " + plan.label.slice(0, 40) : ""}` };
  }

  /**
   * A gesture on a chunk's panel, and then the panel re-read from the page.
   * The page's reaction may be asynchronous, so the chunk is re-read a few
   * times until its rendering changes; the panels redraw from that.
   */
  async actOnChunk(cid: string, rec: ActRecord): Promise<ActResult> {
    const before = getSnapshot(cid)?.html || "";
    const res = await this.actOn(rec);
    if (!res.ok) return res;
    const wv = this.webview;
    if (!wv) return res;
    let read: PinRecord | null = null;
    try {
      const p: any = await this.sidecar.chunk(cid);
      const lines = (p && p.lines) || [];
      if (lines.length) {
        read = { cid, url: "", matched: "", markdown: "", head: "",
                 xpaths: xpathsOfLines(lines), addrs: addressTable(lines) };
      }
    } catch { /* keep what is shown */ }
    if (!read) {
      const again = await this.readPin(rec.url, rec.xpath);
      if (!("error" in again)) read = { ...again, cid };
    }
    if (read) {
      for (let i = 0; i < 6; i++) {
        await new Promise((r) => setTimeout(r, 250));
        let here = "";
        try { here = wv.getURL(); } catch { break; }
        await this.takeSnapshot({ ...read, url: here });
        if ((getSnapshot(cid)?.html || "") !== before) break;
      }
    }
    // After this call's own result has been shown, so the redraw's readout
    // reads what happened rather than "pressing".
    window.setTimeout(() => {
      if (this.pinned.has(cid)) void this.renderSide();
      this.onDirty([cid]);
    }, 0);
    return res;
  }

  /**
   * An address held by a surface (the distilled form's controls) acted on in
   * the same cell, by the same road (`G-111`). The legacy `/enact` drives a
   * separate headless Firefox the reader never sees.
   */
  async actOnAddress(key: string, action = "press", text?: string): Promise<EnactResult | null> {
    const at = parseAddressKey(key);
    if (!at) return { error: "unparseable address" };
    const act: PanelAction = action === "type" || action === "choose" || action === "toggle"
      ? action : "press";
    const r = await this.actOn({ key, url: at.url, xpath: at.xpath, action: act, value: text });
    return r.ok ? { ok: true, did: r.did, detail: r.navigated ? "navigated to the page first" : "in the page",
                    url: r.url, address: key }
                : { error: r.error, refused: r.refused, address: key };
  }

  /** The sensor in the page, booted if absent -- the actuator `perform` lives on it. */
  private async ensureSensor(): Promise<boolean> {
    const wv = this.webview;
    if (!wv) return false;
    if (!BrowserView.sensorSource) {
      const got = await this.sidecar.sensor();
      if (!got || !got.source) return false;
      BrowserView.sensorSource = got.source;
    }
    try {
      return !!(await wv.executeJavaScript(
        `(function () { ${this.sensorBoot()} return !!window[${JSON.stringify(HANDLE)}]; })()`));
    } catch { return false; }
  }

  /** The install-if-absent statement the drain and an act share. */
  private sensorBoot(): string {
    return `if (!window[${JSON.stringify(HANDLE)}]) {
          var h = (${BrowserView.sensorSource})(
            {budget: 0, debounce: 80, variants: {}, known: [], signal: ${JSON.stringify(SIGNAL)},
             push: ${!this.plant.has("pull-drain")}});
          Object.defineProperty(window, ${JSON.stringify(HANDLE)},
            {value: h, enumerable: false, configurable: false});
        }`;
  }

  /**
   * What is under the cursor -> its chunk -> pinned beside the page (`G-39`).
   *
   * Three steps, and the middle one is the interesting one. The xpath is
   * built in the page with the SAME convention the trie uses -- the index is
   * omitted for the first sibling of its tag and present for the rest, so
   * `li/a` and `li[10]/a` are different addresses and `li[1]/a` is not an
   * address at all. Getting that wrong resolves nothing, silently.
   *
   * Then the sidecar walks UP from there, because a reader points at a span
   * inside a paragraph inside a section and only one of those is a thing the
   * trie holds. `ancestors_walked` says how far it went, so "this is not
   * quite what you clicked" is visible rather than implied.
   */
  private async portMarkdown(x: number, y: number): Promise<void> {
    const wv = this.webview;
    if (!wv) return;
    const url = wv.getURL();
    let xpath = "";
    try {
      xpath = await wv.executeJavaScript(
        "(function(){var el=document.elementFromPoint(" + x + "," + y + ");" +
        "if(!el) return '';var parts=[];" +
        "while(el && el.nodeType===1 && el.tagName){" +
        "var tag=el.tagName.toLowerCase(),i=1,sib=el.previousElementSibling;" +
        "while(sib){if(sib.tagName===el.tagName)i++;sib=sib.previousElementSibling;}" +
        "parts.unshift(i>1?tag+'['+i+']':tag);el=el.parentElement;}" +
        "return '/'+parts.join('/');})()");
    } catch (err) {
      this.say(`could not read the page: ${String(err).slice(0, 70)}`);
      return;
    }
    if (!xpath) { this.say("nothing under the cursor"); return; }
    await this.pinXpath(xpath);
  }

  /**
   * Pin the chunk that draws `xpath` (`G-78`): what a right-click does once
   * it knows which element was under the cursor. Public so the harness can
   * pin by address -- an MCP tool asks for exactly what a reader's
   * right-click would have produced.
   */
  /**
   * What a pin holds for the chunk drawing `xpath` on `url`: read from the
   * store, with relative targets resolved against the page. Shared by the
   * right-click and by `refreshPins`, so a pinned chunk re-read after a
   * capture is the same thing a fresh pin would have been.
   */
  private async readPin(url: string, xpath: string): Promise<PinRecord | { error: string }> {
    const got = await this.sidecar.resolve(url, xpath);
    if (!got || !got.lines) return { error: `no chunk draws ${xpath}` };
    // A form's own line is its `action` url, which the page never draws
    // (D-36): left out of the side card, as the billboard leaves it out.
    let markdown = (got.lines as { text: string; cls?: string; key?: string }[])
      .filter((l) => !(l.cls === "group" && /\|action(%7C|\|)/.test(String(l.key || ""))
                       && /^\s*(\/|\?|https?:)/.test(String(l.text || ""))))
      .map((l) => l.text).join("\n");
    // Relative targets are resolved against the PAGE, not the vault.
    //
    // The distiller keeps a link as the document wrote it, which is usually
    // relative -- so media/cache/2c/da/....jpg rendered here asked Obsidian
    // for a VAULT file of that name and got "could not be found". The chunk
    // knows the url it came from, which is exactly the base a browser would
    // have used to fetch it.
    const base = String(got.url || url || "");
    if (base) {
      markdown = markdown.replace(
        /(!?\[[^\]]*\]\()([^)\s]+)/g,
        (whole: string, head: string, target: string) => {
          // Absolute urls and in-page anchors are left alone. A
          // PROTOCOL-relative one is not: left as `//host/...` Obsidian took
          // it against its own `app://` origin, and DuckDuckGo's favicons
          // read "could not be found" in the side card (D-36).
          if (/^[a-z][a-z0-9+.-]*:/i.test(target) || target.startsWith("#")) {
            return whole;
          }
          try {
            return head + new URL(target, base).href;
          } catch {
            return whole;
          }
        });
    }
    const cid = String(got.cid || "");
    const matched = String(got.matched_xpath || xpath);
    return {
      cid, url: String(got.url || url || ""), matched, markdown,
      xpaths: xpathsOfLines(got.lines as { key?: string }[]),
      addrs: addressTable(got.lines as { key?: string; control_key?: string; control?: boolean }[]),
      head: got.ancestors_walked
        ? `${matched} · ${got.ancestors_walked} above what you clicked`
        : matched,
    };
  }

  /**
   * A capture rewrote `cids`: re-read every PINNED one among them, so the
   * markdown beside the page never shows what the page used to say (`S-12`).
   *
   * The side panel held the markdown read at pin time, and nothing re-read
   * it: after a page added an item, the pinned chunk's billboard showed it
   * and its side panel did not (364 characters before and after, 2026-09-26),
   * while unpinning and pinning again showed it at once. O(delta): only the
   * pins a capture names are read, one resolve each.
   */
  async refreshPins(cids: string[]): Promise<number> {
    const touched = [...this.pinned.values()].filter((p) => cids.includes(p.cid));
    let changed = 0;
    for (const pin of touched) {
      const read = await this.readPin(pin.url, pin.matched);
      if ("error" in read || read.cid !== pin.cid) continue;
      // The page's own rendering is re-read too: it can change while the
      // distilled markdown does not (a restyle, a picture arriving).
      const snapped = await this.takeSnapshot(read);
      if (read.markdown === pin.markdown && !snapped) continue;
      this.pinned.set(pin.cid, { ...read, head: pin.head });
      changed++;
    }
    if (changed) await this.renderSide();
    return changed;
  }

  async pinXpath(xpath: string): Promise<{ cid: string } | { error: string }> {
    const wv = this.webview;
    if (!wv) return { error: "no browser" };
    const url = wv.getURL();
    const read = await this.readPin(url, xpath);
    if ("error" in read) {
      this.say(`no chunk draws ${xpath.slice(-48)}`);
      return read;
    }
    const { cid, markdown } = read;
    // The chunk as the browser draws it, read BEFORE either panel opens, so
    // the card and the billboard both show the page's rendering (D-36).
    await this.takeSnapshot(read);
    // **Pinned, not swapped in (`G-78`).** Right-click used to replace the
    // page with the markdown, which left nothing to highlight. Now the chunk
    // is pinned: outlined on the page at its box, rendered on the markdown
    // side beside it, and opened as a billboard in the graph -- and it stays
    // until it is let go from either side.
    this.pinned.delete(cid);                     // re-pinning moves it to the top
    this.pinned = new Map([[cid, read], ...this.pinned]);
    this.pipebox?.setPins(this.pinList());
    await this.renderSide();
    this.layoutSide();
    void this.keepInView(read.matched);
    // The projector rings the same chunk (`G-38`) and opens its billboard.
    this.onHover(cid, read.url);
    this.onPin(cid);
    this.say(`${cid} · ${markdown.split("\n").length} lines · pinned`);
    return { cid };
  }

  /** Turn live capture on or off, and say which it is. */
  private setLive(on: boolean): void {
    this.live = on;
    this.liveButton.setText(on ? "live ●" : "live ○");
    this.say(on ? "live capture on" : "live capture off");
  }

  /**
   * The page changed under the sensor.
   *
   * The previous session is SETTLED before the new one starts. Per-drain
   * writes are deltas and never retire a chunk that re-partitioning replaced,
   * so a page left without settling keeps whatever its last delta happened to
   * leave in the store -- which is a page half-rewritten by the one after it.
   */
  private async pageChanged(url: string): Promise<void> {
    if (!url || url === "about:blank") {
      // Leaving for a blank page is still LEAVING: the page left behind is
      // settled and collapses like any other (G-91 -- it used to return here
      // first, and the page stayed expanded for good).
      const left = this.session;
      this.session = "";
      if (left) {
        this.onLeaving(left);
        await this.settleQueued(left);
        if (this.session !== left) this.onLeft(left);
      }
      return;
    }
    if (url === this.session || (this.session && docKey(url) === docKey(this.session))) return;
    const leaving = this.session;
    this.session = url;
    // Sensor ids are per document: nothing streaming on the page left behind.
    this.pipebox?.clearStreaming();
    this.pipebox?.resetPush();
    // The overlay's map of this page (DESIGN_VII §3), loaded on landing and
    // patched from every capture reply after -- FIRST, before the page left
    // behind is settled. It waited behind that settle capture, which is
    // seconds under load, and until it came every hover and every force
    // node on the new page was checked against the OLD page's map (P-B2
    // read map_follows false 600 ms after an address-bar navigation).
    if (this.pipebox && url && url !== "about:blank") {
      const map = this.pipebox.map;
      // The page's projected chunks come WITH its map (S-1): drawn the moment
      // the reader lands, from the projector's memory, not through the
      // placement queue behind the page's first capture.
      void map.load(this.sidecar, url).then(() => {
        if (map.url !== url || this.session !== url) return;
        if (map.nodes.length) this.onChunks(map.nodes, [], "");
        // A drain that beat the map here was checked against nothing, and
        // drew the page's stored chunks as pending (Trie: 133 force nodes
        // over 84 projected ones). Now that the map is in, check again.
        const tree = this.forceTrees.get(url);
        if (tree) {
          const covers = this.coversFor(url, tree.held());
          if (Object.keys(covers).length) this.onCovers(url, covers, this.settledOf(url, covers));
        }
      });
    }
    // Anything the projector has not placed yet goes on the queue -- BEFORE
    // the page left behind is settled, not after: the next page's 3D used to
    // wait behind that settle, 6 s after a large page (S-3).
    void this.placeWholePage(url);
    // The page left behind: its pending diff is not the reader's any more --
    // drawn now it would hang in the graph until the settle is done (B-tree's
    // 401 force nodes did, for the length of a long settle).
    if (leaving) this.onLeaving(leaving);
    if (leaving) {
      // The page left behind settles AFTER the new page's first capture
      // (D-35). A settle re-ingests the whole page under the store's lock;
      // sent first, it held the lock for seconds while the page the reader is
      // looking at waited to be stored, mapped and placed.
      await this.firstCapture(url, 4000);
      await this.settleQueued(leaving);
      // Settled: its last diff is stored and on its way through the
      // transform, so its chunk nodes fold back into its page node (S-6).
      if (this.session !== leaving) this.onLeft(leaving);
    }
    if (this.live) this.say(`live · ${url}`);
  }

  /**
   * Send EVERY chunk the store holds for this page to the projector.
   *
   * **Why a drain is not enough.** A drain places what it changed. A page
   * the store already holds barely changes when revisited, so after a
   * reload the reader could be looking at a fully captured, fully embedded
   * page with none of it in the graph -- measured, "0/688 in graph" on a
   * page whose 676 chunks all had vectors. The chain the reader is owed is
   * every chunk, not every changed one.
   *
   * Through the placement queue, which already does the rest: batches,
   * waits for any chunk still being embedded, and hands each result to the
   * graph, which ignores what it already has. Traced, so the profile shows
   * the cost of landing on a page as its own entry.
   */
  /**
   * Chunk nodes are drawn for the page being BROWSED only (and its page
   * node always). A placement or capture result that arrives after the reader
   * left its page used to re-add that page's chunks just after they had been
   * collapsed into its node (G-91: the left page never stayed collapsed).
   */
  private forPage(nodes: LayoutNode[]): LayoutNode[] {
    return nodes.filter((n: any) => n.level === "page" || !n.url || n.url === this.session);
  }

  /** When each url's first capture of this visit came back (D-35). */
  private capturedAt = new Map<string, number>();
  /** The settle of the page left, deferred behind the next page's first capture. */
  private async firstCapture(url: string, limitMs: number): Promise<void> {
    const since = performance.now();
    this.capturedAt.delete(url);
    while (performance.now() - since < limitMs) {
      if (this.capturedAt.has(url) || this.session !== url) return;
      await new Promise((r) => window.setTimeout(r, 100));
    }
  }

  private async placeWholePage(url: string): Promise<void> {
    if (!url || url === "about:blank") return;
    const cids = await this.sidecar.pageCids(url).catch(() => [] as string[]);
    if (!cids.length || this.session !== url) return;
    const trace = profiler().begin("land", url);
    profiler().fact(trace, "page_chunks", cids.length);
    this.enqueuePlacement(cids, trace.id);
  }

  /**
   * One turn of the live loop: fold what changed, store it, place it.
   *
   * Guarded rather than queued. A drain that has not come back is a page
   * still being folded, and starting a second one would hand the sidecar two
   * deltas whose order it cannot recover -- the decoder's dictionary is
   * append-only, so out-of-order drains do not merely arrive late, they
   * arrive unreadable.
   */
  /**
   * Hold chunks that are stored but not yet placeable, and keep asking.
   *
   * On its own timer rather than the drain's, because the two are
   * independent: a drain happens when the page mutates, a chunk becomes
   * placeable when the encoder finishes, and tying the second to the first
   * meant a static page's last chunks were never drawn.
   */
  private enqueuePlacement(cids: string[], traceId: string) {
    const now = performance.now();
    for (const cid of cids) this.pendingPlace.set(cid, { trace: traceId, since: now });
    if (!this.placeTimer) {
      this.placeTimer = window.setInterval(() => void this.drainPlacement(), 250);
    }
  }

  private async drainPlacement(): Promise<void> {
    if (this.placing) return;
    if (!this.pendingPlace.size) {
      window.clearInterval(this.placeTimer);
      this.placeTimer = 0;
      return;
    }
    this.placing = true;
    const prof = profiler();
    try {
      // Give up on anything that has waited a long time: a chunk whose
      // vector never comes would otherwise keep this loop alive forever.
      const now = performance.now();
      for (const [cid, v] of this.pendingPlace) {
        if (now - v.since > 60000) {
          this.pendingPlace.delete(cid);
          const t = prof.get(v.trace);
          if (t) { prof.fact(t, "why", "vector never arrived"); prof.finish(t, "not_seen"); }
        }
      }
      const cids = [...this.pendingPlace.keys()];
      if (!cids.length) return;
      const got: any = await this.sidecar.place(cids);
      const nodes = ((got && got.nodes) || []) as LayoutNode[];
      if (!nodes.length) return;
      // Group what landed by the trace that asked for it, so each drain's
      // end-to-end closes on ITS chunks appearing.
      const byTrace = new Map<string, LayoutNode[]>();
      // Nodes nobody queued -- the page hub `place` sends with its chunks --
      // travel with the first batch. Dropping them dropped every page->root
      // edge with them: on a page new to the graph the hub did not exist
      // yet, so `addEdges` discarded 57 of 79 edges and the trie hung loose.
      const unasked: LayoutNode[] = [];
      for (const n of nodes) {
        const entry = this.pendingPlace.get(n.cid);
        if (!entry) { unasked.push(n); continue; }
        this.pendingPlace.delete(n.cid);
        const t = prof.get(entry.trace);
        if (t) prof.stage(t, "vector_wait", now - entry.since);
        const list = byTrace.get(entry.trace) || [];
        list.push(n);
        byTrace.set(entry.trace, list);
      }
      const edges = ((got && got.edges) || []) as { source: string; target: string }[];
      const first = byTrace.keys().next();
      if (!first.done && unasked.length) byTrace.get(first.value)!.unshift(...unasked);
      for (const [traceId, list] of byTrace) this.onChunks(this.forPage(list), edges, traceId);
    } finally {
      this.placing = false;
    }
  }

  private async tick(): Promise<void> {
    if (!this.live || this.draining || !this.webview) return;
    const wv = this.webview;
    const url = wv.getURL();
    // Drained once the DOCUMENT is ready, loading or not: YouTube and IMDb
    // never stop "loading" (streaming requests), and waiting for them to meant
    // 0 and 2 drains in 16 s -- the heavy live pages were barely scanned
    // (G-101, 2026-09-27).
    if (!url || url === "about:blank" || (wv.isLoading() && !this.domReady)) return;
    if (url !== this.session && docKey(url) !== docKey(this.session)) {
      this.lastRepairMs = undefined;
      await this.pageChanged(url);
      return;
    }

    this.draining = true;
    // One trace per drain, closed by the graph when a node from it is seen
    // on screen -- or by one of the early returns below, each of which is
    // a real outcome worth counting rather than a trace to lose.
    const prof = profiler();
    const trace = prof.begin("live", url);
    try {
      if (!BrowserView.sensorSource) {
        const got = await this.sidecar.sensor();
        if (!got || !got.source) return;
        BrowserView.sensorSource = got.source;
      }
      const drainStart = performance.now();
      let drainBack = 0;
      const payload = await wv.executeJavaScript(`(function () {
        ${this.sensorBoot()}
        var h = window[${JSON.stringify(HANDLE)}];
        // One place for the drain, its boxes and pictures; pushed when this
        // host's signal is the handle's, and then only {pushed: v} comes back.
        if (h.flush) return h.flush(${JSON.stringify(SIGNAL)});
        var t0 = performance.now();
        var p = h.drain();
        var t1 = performance.now(), t2 = t1, t3 = t1;
        // The diff's boxes, in the SAME crossing (G-90): read by the
        // sensor's box peripheral after the fold, never inside it.
        if (p && p.chunks && p.chunks.length && h.boxes) {
          p.boxes = h.boxes(p.chunks.map(function (c) { return c.id; }));
          t2 = performance.now();
          // And each chunk's largest RENDERED picture, in the same crossing.
          if (h.pictures) p.pictures = h.pictures(p.chunks.map(function (c) { return c.id; }));
          t3 = performance.now();
        }
        // Where the crossing's time goes, on the guest's clock; the rest of
        // \`drain\` is serialisation and the bridge.
        if (p) p.inpage = {drain: t1 - t0, boxes: t2 - t1, pictures: t3 - t2};
        return p;
      })()`);

      drainBack = performance.now();
      // Pushed: it arrives (or has arrived) on the console channel, in order.
      if (payload && payload.pushed) { prof.drop(trace); return; }
      await this.absorbDrain(payload, url, trace, drainStart, drainBack, wv.getTitle() || "");
    } catch (e) {
      // The realm goes away on navigation and the handle with it. That is
      // ordinary, not an error: the next tick reboots into the new document.
      this.say(`live · ${String(e).slice(0, 80)}`);
    } finally {
      this.draining = false;
      if (this.drainAgain) { this.drainAgain = false; window.setTimeout(() => void this.tick(), 0); }
    }
  }

  /**
   * A drain the sensor PUSHED (2026-09-27): sent from the task that folded
   * it, so it never queues behind the page's long tasks the way a pulled
   * drain did. Absorbed in arrival order -- one channel, so page order.
   */
  private pushQueue: { payload: any; at: number }[] = [];
  private pumpingPush = false;
  private async onPushedDrain(payload: any): Promise<void> {
    this.pushQueue.push({ payload, at: performance.now() });
    if (this.pumpingPush) return;
    this.pumpingPush = true;
    try {
      while (this.pushQueue.length) {
        const { payload: p, at } = this.pushQueue.shift()!;
        const wv = this.webview;
        if (!wv || !this.live) continue;
        const url = String(p.url || wv.getURL() || "");
        if (!url || url === "about:blank") continue;
        if (url !== this.session && docKey(url) !== docKey(this.session)) {
          this.lastRepairMs = undefined;
          // Sets the session at once; the settle it starts runs behind.
          void this.pageChanged(url);
        }
        const prof = profiler();
        const trace = prof.begin("live", url);
        const inpage = p.inpage || {};
        const transit = typeof p.sentAt === "number" ? Math.max(0, Date.now() - p.sentAt) : 0;
        prof.stage(trace, "push_transit", transit);
        const inPage = (inpage.drain || 0) + (inpage.boxes || 0) + (inpage.pictures || 0);
        // How long it sat in the host's queue before being absorbed (G-90).
        prof.stage(trace, "pump_wait", performance.now() - at);
        await this.absorbDrain(p, url, trace, at - inPage - transit, at, wv.getTitle() || "");
      }
    } catch (e) {
      this.say(`live · ${String(e).slice(0, 80)}`);
    } finally {
      this.pumpingPush = false;
    }
  }

  /**
   * One drain into the GUI, pulled or pushed: the force tree, the overlay's
   * outlines, the 3D stream, and the store's capture queued behind them.
   */
  private async absorbDrain(payload: any, url: string, trace: any, drainStart: number,
                            drainBack: number, title: string): Promise<void> {
    const prof = profiler();
    // The host's wall clock at arrival: a page that logs its own mutations
    // can time the stream against ITS clock (D-40), not the sensor's.
    prof.fact(trace, "host_epoch", Date.now());
    // Which of the page's chunks this drain carried (the sensor's own ids, as
    // `at()` answers them), so a check can tie a mutation it saw to the drain
    // that brought it rather than to whichever drain came next.
    if (payload && payload.chunks) prof.fact(trace, "chunk_ids", payload.chunks.map((c: any) => Number(c.id)).slice(0, 400));
    if (payload && payload.dirtyAt) prof.stage(trace, "mutation_to_host", Math.max(0, Date.now() - payload.dirtyAt));
    // The force ids this drain emitted: what its capture is answerable for.
    let drainIds: string[] = [];
    // Nothing changed. Not posted: an empty delta costs a round trip, a
    // decode and a store write to say "no", and a reader idling on a static
    // page would pay it once a second forever.
    prof.stage(trace, "drain", performance.now() - drainStart);
    // The guest's own fold time for this drain, from its own clock. It is
    // INSIDE `drain`, and the difference is the executeJavaScript bridge.
    if (payload && payload.inpage) {
      prof.stage(trace, "drain.call", payload.inpage.drain);
      prof.stage(trace, "drain.boxes", payload.inpage.boxes);
      prof.stage(trace, "drain.pictures", payload.inpage.pictures);
    }
    const repair = payload && payload.stats ? payload.stats.repairMs : undefined;
    if (typeof repair === "number") {
      // Cumulative per handle; a new handle (a new realm) starts from zero.
      const prev = this.lastRepairMs ?? 0;
      prof.stage(trace, "fold", repair >= prev ? repair - prev : repair);
      this.lastRepairMs = repair;
    }
    // The force tree first (`G-89`): straight from the drain, before the
    // capture's round trip, so the graph shows the scan at once.
    if (payload && ((payload.chunks || []).length || (payload.removed || []).length)) {
      let tree = this.forceTrees.get(url);
      if (!tree) { tree = new ForceTree(url); this.forceTrees.set(url, tree); }
      const delta = tree.apply(payload);
      if (delta) drainIds = delta.added.map((a) => a.id);
      if (payload.pictures) {
        (payload.chunks || []).forEach((c: any, i: number) => {
          const pic = payload.pictures[i];
          if (pic && pic[0]) this.drainPics.set(tree!.nodeId(Number(c.id)), String(pic[0]));
        });
        while (this.drainPics.size > 5000) this.drainPics.delete(this.drainPics.keys().next().value as string);
      }
      // The diff outlined FIRST (`G-90`) -- boxes came back with the drain,
      // so this is placement only -- and only the TRUE diff (H-1): a chunk
      // the store already holds unchanged is not news, and landing on a
      // stored page used to flash its whole first drain.
      if (delta && payload.boxes && payload.boxes.length) {
        const tc = performance.now();
        const addedIds = new Set(delta.added.map((a) => a.id));
        delta.covers = this.coversFor(url, tree.held().filter((h) => addedIds.has(h.id)));
        prof.stage(trace, "absorb.covers", performance.now() - tc);
        const again = new Set(delta.added.filter((a) => a.again).map((a) => a.id));
        // WHY each chunk of the drain was or was not outlined, as facts on
        // the trace (2026-09-27: "overlays for completely new diff updates
        // ... have not been observed for several minutes" -- and the trace
        // could not say whether a drain was stored content, furniture known
        // never to be stored, off screen, or dropped).
        const why = { flashed: 0, covered: 0, unstored: 0, offscreen: 0, nobox: 0 };
        const vh = (this.webview as any)?.clientHeight || 0;
        const boxes = (payload.chunks || []).map((c: any, i: number) => {
          const id = tree.nodeId(Number(c.id));
          // Not flashed: covered and unchanged, or known never to be stored.
          if (this.unstoredIds.has(id) && !again.has(id)) { why.unstored++; return null; }
          const addr = tree.addressOf(Number(c.id));
          if (addr && this.unstoredOn(url).has(addr) && !again.has(id)) { why.unstored++; return null; }
          if (delta.covers[id] && !again.has(id)) { why.covered++; return null; }
          const r = payload.boxes[i];
          if (!r) { why.nobox++; return null; }
          if (r[1] + r[3] < 0 || (vh && r[1] > vh) || (r[2] <= 0 && r[3] <= 0)) why.offscreen++;
          else why.flashed++;
          return r;
        });
        prof.fact(trace, "flash", why);
        prof.stage(trace, "absorb.flash_prep", performance.now() - tc);
        if (boxes.some(Boolean)) {
          this.pipebox?.flashBoxes(boxes, drainBack, trace.id,
                                   (payload.chunks || []).map((c: any) => Number(c.id)));
        }
      }
      if (delta && (delta.added.length || delta.removed.length || delta.reparented.length)) {
        if (!payload.boxes) delta.covers = this.coversFor(url, tree.held().filter(
          (h) => delta.added.some((a) => a.id === h.id)));
        delta.settled = this.settledOf(url, delta.covers);
        // Known never to be stored on this page: not the diff either.
        const known = this.unstoredOn(url);
        for (const h of tree.held()) {
          if (known.has(h.address) && !delta.covers[h.id]
              && delta.added.some((a) => a.id === h.id && !a.again)) delta.settled.push(h.id);
        }
        delta.t0 = drainBack;
        delta.trace = trace.id;
        prof.stage(trace, "force_tree", delta.ms);
        // Both outputs of this drain, from the same instant (`G-90`): the
        // diff outlined on the page, and its nodes in the 3D graph.
        if (delta.addresses.length && !(payload && payload.boxes)) {
          this.pipebox?.flashDiff(delta.addresses, drainBack, trace.id);
        }
        // The 3D update AFTER the frame that paints the overlay (G-90): run in
        // the same task it held the main thread, and while the graph was
        // large the boxes waited for it -- 545 ms p50 to paint, against
        // 5-9 ms when the graph was small. rAF, then a task: the paint
        // happens between them.
        window.requestAnimationFrame(() => window.setTimeout(() => this.onDrain(delta), 0));
      }
    }
    if (!payload || !(payload.chunks || []).length) {
      this.capturedAt.set(url, performance.now());
      prof.fact(trace, "why", "empty drain");
      prof.finish(trace, "nothing_placed");
      return;
    }
    prof.fact(trace, "chunks_in_drain", (payload.chunks || []).length);

    // The store comes AFTER the GUI (Addendum IX, D-35): the capture is
    // queued, and this drain is done -- the next tick drains, outlines and
    // draws again whether or not the store has answered. It used to hold
    // `draining` across the whole round trip, and a new page's first
    // capture (the whole page, 5-7 s to store) froze the overlay and the
    // 3D stream for exactly that long after every navigation.
    this.captureQueue.push({ url, payload, trace, drainIds, queuedAt: performance.now(),
                             title });
    void this.pumpCaptures();
    // Planted by D-35's check: the old behaviour, the drain loop held
    // across the whole capture.
    if (this.plant.has("serial-capture")) {
      while (this.capturing || this.captureQueue.length) {
        await new Promise((r) => window.setTimeout(r, 50));
      }
    }
  }

  /** Drains that rode along in another drain's capture (merged ingest). */
  mergedCaptures = 0;

  /** Captures waiting to be sent, in drain order per url. */
  private captureQueue: CaptureJob[] = [];
  /** A capture (or settle) is in flight. */
  capturing = false;
  /** Queued captures, for the harness and the corner box. */
  get captureBacklog(): number { return this.captureQueue.length; }

  /**
   * Send queued captures one at a time. The CURRENT page's go first; any
   * other url's (the page left behind: its last drains, then its settle)
   * keep their own order and wait. Order within one url is kept because the
   * sidecar's decoder dictionary is append-only; across urls there is no
   * shared state to order.
   */
  private async pumpCaptures(): Promise<void> {
    if (this.capturing) return;
    this.capturing = true;
    try {
      while (this.captureQueue.length) {
        let k = this.captureQueue.findIndex((c) => c.url === this.session);
        if (k < 0) k = 0;
        let job = this.captureQueue.splice(k, 1)[0];
        // Every later drain of the same page queued meanwhile rides along --
        // up to a settle of that page, which stays a barrier.
        if (!job.settle && !this.plant.has("serial-ingest")) {
          const ride: CaptureJob[] = [];
          for (let i = k; i < this.captureQueue.length && ride.length < 40; ) {
            const c = this.captureQueue[i];
            if (c.url !== job.url) { i++; continue; }
            if (c.settle) break;
            ride.push(this.captureQueue.splice(i, 1)[0]);
          }
          if (ride.length) {
            const all = [job, ...ride];
            job = { ...job, payload: mergePayloads(all.map((j) => j.payload)),
                    drainIds: all.flatMap((j) => j.drainIds || []),
                    merged: ride.map((j) => j.trace).filter(Boolean) };
            this.mergedCaptures += ride.length;
          }
        }
        if (job.settle) {
          try { await this.sidecar.capture(job.url, { settle: true }); } catch { /* reported by the next */ }
          job.done && job.done();
          continue;
        }
        try {
          await this.captureOne(job);
        } catch (e) {
          this.say(`live · ${String(e).slice(0, 80)}`);
        }
      }
    } finally {
      this.capturing = false;
    }
  }

  /** Settle a page through the queue, after every capture of it already queued. */
  private settleQueued(url: string): Promise<void> {
    return new Promise((resolve) => {
      this.captureQueue.push({ url, settle: true, done: resolve });
      void this.pumpCaptures();
    });
  }

  private async captureOne(job: CaptureJob): Promise<void> {
    const { url, payload, trace, drainIds } = job;
    const prof = profiler();
    // How long this drain's diff waited for the store to take it.
    if (job.queuedAt) prof.stage(trace, "capture_queue_wait", performance.now() - job.queuedAt);
    for (const t of job.merged || []) prof.fact(t, "merged_into", trace?.id || "");
    const wv = { getTitle: () => job.title || "" };

      // One round trip: fold, store, and place, because per drain they are
      // one question. The second call carried a list of cids the server had
      // just computed and was handing straight back.
      const captureStart = performance.now();
      const reply = await this.sidecar.capture(
        url, { payload, place: true, trace: trace.id, title: wv.getTitle() || "" });
      const captureMs = performance.now() - captureStart;
      this.capturedAt.set(url, performance.now());
      prof.stage(trace, "capture", captureMs);
      if (reply) prof.sidecar(trace, reply.phases, reply.ms, captureMs);
      if (!reply || reply.error) {
        this.say(`capture: ${reply ? reply.error : "no reply"}`);
        return;
      }
      // The chunks this drain rewrote, and the elements they draw.
      if (this.pipebox && this.pipebox.map.url === url) {
        this.pipebox.map.patch((reply as any).map_delta);
      }
      const cids = (reply.dirty_cids || []) as string[];
      // The map now knows what this capture stored: re-check what is still
      // drawn as pending on this page. What the capture processed and the
      // store still holds no chunk for -- page furniture, content the
      // projection does not render -- is not waiting on anything: it is not
      // pending, and goes (it lingered for the 20 s timeout, and flashed as
      // the diff on every landing).
      {
        const tree = this.forceTrees.get(url);
        if (tree) {
          const held = tree.held();
          const covers = this.coversFor(url, held);
          // A rewritten chunk the capture neither placed nor queued for a
          // vector is not drawable on its own (a merge-group member, a
          // duplicate -- drawn through its lead): what it covers is settled,
          // or it waited for a node that never comes (G-89 C7: 3 left).
          const placedNow = new Set(((reply as any).nodes || []).map((n: any) => n.cid));
          const waitingNow = new Set(((reply as any).unplaced || []) as string[]);
          const undrawable = new Set(((reply as any).dirty_cids || [] as string[])
            .filter((c: string) => !placedNow.has(c) && !waitingNow.has(c)));
          const settledNow = this.settledOf(url, covers)
            .concat(Object.entries(covers).filter(([, c]) => undrawable.has(c)).map(([id]) => id));
          if (Object.keys(covers).length) this.onCovers(url, covers, settledNow);
          // The stored chunks now known for drained ones carry their pictures.
          const picked: Record<string, string> = {};
          for (const [fid, cid] of Object.entries(covers)) {
            const src = this.drainPics.get(fid);
            if (src && cid) picked[cid as string] = src;
          }
          if (Object.keys(picked).length) { putPictures(picked); this.onPictures(picked); }
          // Saved: their outlines on the page go too (after their dwell) --
          // the same moment their translucent nodes collapse in 3D (D-37).
          if (this.pipebox && url === this.session) {
            const sid = (id: string) => Number(id.slice(id.lastIndexOf("#") + 1));
            this.pipebox.savedStreaming(Object.keys(covers).map(sid).filter((n) => !isNaN(n)));
          }
          const captured = new Set(drainIds);
          const unstored = held.filter((h) => captured.has(h.id) && !covers[h.id]).map((h) => h.id);
          if (unstored.length) this.onUnstored(url, unstored);
          const at = this.unstoredOn(url);
          for (const h of held) {
            if (!covers[h.id]) { this.unstoredIds.add(h.id); at.add(h.address); } else at.delete(h.address);
          }
        }
      }
      // Every form of a chunk that is open follows the capture that rewrote
      // it -- the pinned markdown here, the billboard in the graph -- keyed
      // on what the capture DIRTIED, not on what it newly placed: a chunk
      // already drawn is rewritten without being placed again.
      if (cids.length) {
        void this.refreshPins(cids);
        this.onDirty(cids);
      }
      if (!cids.length) {
        this.say(`live · ${reply.addresses} addresses`);
        prof.fact(trace, "why", "nothing dirty");
        prof.finish(trace, "nothing_placed");
        return;
      }
      const nodes = (reply.nodes as LayoutNode[]) || [];
      prof.fact(trace, "dirty", cids.length);
      prof.fact(trace, "placed", nodes.length);
      prof.fact(trace, "unplaced", (reply.unplaced || []).length);
      // Anything stored but not yet placeable goes on the placement queue,
      // which asks again on its own timer until the encoder has caught up.
      // Before this, those chunks waited for the next DRAIN -- and a page
      // that had finished loading never drained again, so they never
      // appeared at all.
      const unplacedCids = (reply.unplaced || []) as string[];
      if (unplacedCids.length) this.enqueuePlacement(unplacedCids, trace.id);
      if (!nodes.length) {
        // The trace stays open: `enqueuePlacement` will close it when the
        // queue places these, so end-to-end includes the encoder's time.
        prof.fact(trace, "why", "awaiting vectors");
        prof.fact(trace, "queued_for_placement", unplacedCids.length);
        if (!unplacedCids.length) prof.finish(trace, "nothing_placed");
      }
      // **With the edges.** `place_into` computes the containment among
      // what it placed and this dropped them, so every live-captured
      // chunk drew as a loose dot: 793 chunk nodes, 16 with an edge.
      if (nodes.length) {
        this.onChunks(this.forPage(nodes),
          (reply.edges as { source: string; target: string }[]) || [],
          trace.id);
      }
      // "Unplaced" has two causes and they are not the same news: a chunk
      // seconds old has no vector yet and will get one, while a workspace
      // with no fit has nowhere to put anything and will not until it is
      // asked for a layout. Reporting both as "awaiting a vector" sent me
      // looking for a broken embedder that was working perfectly.
      const waiting = reply.unplaced ? reply.unplaced.length : 0;
      this.say(`live · ${cids.length} chunks · ${nodes.length} placed` +
               (reply.why ? ` · ${reply.why}`
                : waiting ? ` · ${waiting} awaiting a vector` : "") +
               (reply.place_error ? ` · ${reply.place_error}` : "") +
               (reply.stale ? " · fit is stale, refit" : "") +
               ` · ${reply.ms} ms`);
  }

  /**
   * Scan the page the reader is looking at (`G-47`).
   *
   * The same sensor the Selenium path runs, fetched from the sidecar rather
   * than bundled -- a copy compiled in here would be a second sensor, and
   * every comparison between a browser-cell capture and a corpus scan would
   * then be measuring the drift between them instead of the page.
   *
   * It READS. The sensor walks the composed tree, including shadow roots,
   * and hands back one serialisation; nothing is written into the document
   * (constraint 7). The handle it installs is a property on `window`, which
   * is the same thing the Selenium path does and the one concession -- the
   * alternative is re-walking the page from scratch on every drain.
   */
  /**
   * ``fixed`` reproduces the cadence this replaced: `SCROLLS` + 1 passes at
   * `PAUSE_MS`, stepping 0.9 of a viewport, no early stop.
   *
   * **It exists so that `S-8` has something to be measured against.** A
   * tuned scan that is merely fast is not an improvement -- it is only an
   * improvement if it captures no less. Keeping the old schedule callable
   * makes that an A/B on one page in one session rather than a comparison
   * between two numbers recorded on different days by different code.
   */
  async scan(opts: { fixed?: boolean } = {}): Promise<void> {
    const wv = this.webview;
    if (!wv) return;
    const url = wv.getURL();
    if (!url || url === "about:blank") { this.say("nothing to scan"); return; }

    if (!BrowserView.sensorSource) {
      this.say("fetching the sensor…");
      const got = await this.sidecar.sensor();
      if (!got || !got.source) { this.say("no sensor from the sidecar"); return; }
      BrowserView.sensorSource = got.source;
    }

    // Boot once per page, then drain. The handle is checked rather than
    // re-installed, because re-booting would throw away the fold and make
    // every pass a full read -- which is the opposite of what the sensor is.
    this.say("folding the page…");
    let booted = false;
    try {
      booted = await wv.executeJavaScript(`(function () {
        if (window[${JSON.stringify(HANDLE)}]) return true;
        var h = (${BrowserView.sensorSource})(
          {budget: 0, debounce: 80, variants: {}, known: []});
        Object.defineProperty(window, ${JSON.stringify(HANDLE)},
          {value: h, enumerable: false, configurable: false});
        return typeof h.drain === "function";
      })()`);
    } catch (e) {
      this.say(`the sensor did not run: ${String(e).slice(0, 120)}`);
      return;
    }
    if (!booted) { this.say("the sensor installed no drain handle"); return; }

    // Several passes, scrolling between them, because a page that loads on
    // scroll has not finished being itself when it first paints. Scrolling
    // is what the Selenium path does too; it is the reader's own browser, so
    // it is their scroll position that moves and then comes back.
    //
    // **Live-tuned rather than counted out (`S-8`).** The loop runs until
    // the page has been seen to the bottom AND the trie has stopped
    // changing, with the pause between a scroll and its drain following the
    // page's own update rate. Six fixed passes at 700ms was both too much
    // for a static page and too little for a slow one.
    const startedAt = Date.now();
    const where0 = await wv.executeJavaScript("window.scrollY");
    let total = 0, addresses = 0;
    let pause = PAUSE_START_MS;
    let quiet = 0, passes = 0, atBottom = false;
    const pauses: number[] = [];
    const steps: number[] = [];

    const cap = opts.fixed ? SCROLLS + 1 : MAX_PASSES;
    let step = opts.fixed ? 0.9 : SCROLL_STEP;
    if (opts.fixed) pause = PAUSE_MS;

    for (passes = 0; passes < cap; passes++) {
      if (passes) {
        atBottom = await wv.executeJavaScript(
          "(function(){var before=window.scrollY;" +
          "window.scrollBy(0, window.innerHeight * " + step + ");" +
          "return window.scrollY <= before + 1;})()");
        pauses.push(pause);
        steps.push(Math.round(step * 100) / 100);
        await new Promise((r) => setTimeout(r, pause));
      }
      let payload: any = null;
      try {
        payload = await wv.executeJavaScript(
          `window[${JSON.stringify(HANDLE)}].drain()`);
      } catch (e) {
        this.say(`drain ${passes} failed: ${String(e).slice(0, 100)}`);
        return;
      }
      const reply = await this.sidecar.capture(
        url, { payload, title: this.webview?.getTitle() || "" });
      if (!reply || reply.error) {
        this.say(`capture failed: ${reply ? reply.error : "no reply"}`);
        return;
      }
      const dirty = reply.dirty || 0;
      total += dirty;
      addresses = Math.max(addresses, reply.addresses || 0);

      // The tuning itself. Productive drains mean the page is still
      // arriving and the next one should wait longer; empty ones mean it is
      // ahead of us and the next can come sooner.
      if (!opts.fixed) {
        pause = dirty
          ? Math.min(Math.round(pause * 1.4), PAUSE_MAX_MS)
          : Math.max(Math.round(pause * 0.6), PAUSE_MIN_MS);
        // Cover ground fast where nothing is arriving, slow down the
        // instant something does.
        step = dirty
          ? SCROLL_STEP
          : Math.min(step * 1.5, SCROLL_STEP_MAX);
      }
      quiet = dirty ? 0 : quiet + 1;

      this.say(`pass ${passes}: ${reply.addresses} addresses, ` +
               `${dirty} rewritten, ${reply.ms} ms, next in ${pause} ms`);

      // Settled: seen to the bottom, and the trie has stopped changing.
      // The fixed arm counts its passes out regardless, which is the
      // behaviour being compared against.
      if (!opts.fixed && atBottom && quiet >= QUIET_PASSES) break;
      if (Date.now() - startedAt > MAX_SCAN_MS) break;
    }

    // Put the reader back where they were. The comment above has always
    // said their scroll position "comes back"; nothing was bringing it.
    await wv.executeJavaScript(
      "window.scrollTo(0, " + (Number(where0) || 0) + "); true");

    const elapsedMs = Date.now() - startedAt;
    this.lastScan = {
      passes: passes + 1, elapsedMs, rewrites: total, addresses,
      pauses, steps, settled: atBottom && quiet >= QUIET_PASSES,
      mode: opts.fixed ? "fixed" : "tuned",
      meanPauseMs: pauses.length
        ? Math.round(pauses.reduce((a, b) => a + b, 0) / pauses.length) : 0,
    };

    // One complete write from the settled trie. The per-drain writes are
    // deltas and never retire a chunk that re-partitioning replaced.
    const done = await this.sidecar.capture(url, {
      settle: true, title: wv.getTitle() || "" });
    if (!done || done.error) {
      this.say(`settle failed: ${done ? done.error : "no reply"}`);
      return;
    }
    this.say(`scanned · ${done.addresses} addresses · ${done.chunks} chunks ` +
             `· ${total} rewrites over ${passes + 1} passes ` +
             `· ${(elapsedMs / 1000).toFixed(1)}s` +
             (this.lastScan.settled ? " · settled" : " · capped"));
  }

  private say(text: string): void {
    this.status.setText(text);
  }
}
