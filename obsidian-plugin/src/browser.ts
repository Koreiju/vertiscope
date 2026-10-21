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

import { mergePayloads, removesCarried } from "./mergepayloads";
export { mergePayloads };
import { addressTarget } from "./address";
import { isolate } from "./isolate";
import { ForceTree, type ForceNodeDelta } from "./forcetree";
import { PipelineBox } from "./pipelinebox";
import { profiler } from "./profile";
import { Component, ItemView, MarkdownRenderer, Menu, WorkspaceLeaf, requestUrl } from "obsidian";
import { baseFor, putBase, putFavicon, putPictures } from "./snapshot";
// A streamed link's destination resolves against the base its page declared.
ForceTree.baseOf = baseFor;
import { Snapshot, dropSnapshot, getSnapshot, putSnapshot, renderSnapshot, snapshotScript, xpathsOfLines } from "./snapshot";

import { LayoutNode } from "./graph";
import { Sidecar } from "./sidecar";
import { GATE_SMALL_LINES, GateVerdict, pageGate } from "./gate";
import { CentralDiff, EnactResult, SearchHit } from "./types";
import { ActRecord, ActResult, PanelAction, addressTable, chainFor, parseAddressKey } from "./panelact";

export const BROWSER_VIEW = "vertiscope-browser-view";

/**
 * The session every browser cell shares.
 *
 * `persist:` makes it survive a restart. Without the prefix Electron gives an
 * in-memory session, and a reader would be logged out of every site each time
 * the pane was closed -- which would also mean the sensor scanned a different
 * page than the one the reader browsed.
 */
const PARTITION = "persist:vertiscope";

/**
 * Where the sensor's drain handle lives on the page's `window`.
 *
 * Fixed rather than randomised, unlike the Selenium path, which picks a fresh
 * name per scan so a page cannot learn to look for it. Here the reader is
 * driving their own browser at a page they chose, and a stable name is what
 * lets a second scan of the same page reuse the fold instead of rebuilding
 * it -- which is the whole point of an O(delta) sensor.
 */
const HANDLE = "__vertiscopeSensor";

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
const SIGNAL = "\u0001vertiscope:" + Math.random().toString(36).slice(2, 10) + ":";

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
  /** Times this capture was tried and got no reply (re-queued, never dropped). */
  attempts?: number;
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
  getDisplayText(): string { return "vertiscope browser"; }
  getIcon(): string { return "globe"; }

  async onOpen(): Promise<void> {
    const root = this.contentEl;
    root.empty();
    root.addClass("vertiscope-browser");

    const bar = root.createDiv({ cls: "vertiscope-browser-bar" });
    const back = bar.createEl("button", { text: "←" });
    const fwd = bar.createEl("button", { text: "→" });
    const reload = bar.createEl("button", { text: "⟳" });
    this.address = bar.createEl("input", { cls: "vertiscope-browser-url" });
    this.address.type = "text";
    this.address.placeholder = "url";
    const scan = bar.createEl("button", { text: "scan" });
    this.liveButton = bar.createEl("button", { text: "live ●" });
    // `G-60`: save each page as presented, for offline use -- a toggle, as asked.
    this.saveOfflineButton = bar.createEl("button");
    this.paintSaveOffline();
    this.saveOfflineButton.onclick = () => { void this.toggleSaveOffline(); };
    // `G-62`: the page with no connection -- saved as presented, or rebuilt
    // from the scan trace. Pressed again, back to the live page.
    const offlineBtn = bar.createEl("button", { text: "offline" });
    // Item 89: the outlines shown or not -- by ALPHA only (a class on the wrap,
    // opacity 0 on the boxes). Hover, the 3D flight, panels, pins and the
    // stream behave the same either way. Planted (plantBoxesStopHover): off
    // also stops the hover, which is what "the same" forbids.
    this.boxesButton = bar.createEl("button");
    this.boxesButton.onclick = () => { void this.toggleBoxes(); };
    offlineBtn.onclick = () => {
      if (this.offlineFor) { const u = this.offlineFor; this.offlineFor = ""; this.go(u); }
      else void this.openOffline(this.webview?.getURL() || "");
    };

    // The overlay, above the page and never inside it (`G-41`). This is
    // Obsidian's own DOM drawn over the webview, not script written into the
    // document -- the distinction the constraint exists for.
    const search = root.createDiv({ cls: "vertiscope-browser-search" });
    this.queryInput = search.createEl("input", { cls: "vertiscope-query" });
    this.queryInput.type = "text";
    this.queryInput.placeholder = "search the corpus";
    this.scopeButton = search.createEl("button", { text: "everywhere" });
    this.scopeButton.onclick = () => this.setScope(this.rankScope
      ? "" : (this.webview ? this.webview.getURL() : ""));
    const clear = search.createEl("button", { text: "×" });
    clear.onclick = () => { this.queryInput.value = ""; this.showResults([]); };

    this.split = root.createDiv({ cls: "vertiscope-browser-split" });
    this.browserWrap = this.split.createDiv({ cls: "vertiscope-browser-page" });
    this.overlay = this.browserWrap.createDiv({ cls: "vertiscope-overlay" });
    this.results = this.overlay.createDiv({ cls: "vertiscope-overlay-list" });
    this.overlay.hide();
    this.markdownWrap = this.split.createDiv({ cls: "vertiscope-browser-md" });
    this.markdownWrap.hide();
    this.markdownWrap.createDiv({ cls: "vertiscope-browser-empty" }).setText(
      "Double right-click a chunk in the browser to pin it here.");

    this.status = root.createDiv({ cls: "vertiscope-browser-status" });

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
    // Every read of the sensor runs in an isolated world of the page, out of
    // the page's sight and past its console wrappers (`isolate.ts`). The plant
    // `main-world` restores the old routing for a check's planted arm.
    isolate(view, () => this.plant.has("main-world"));
    this.webview = view;
    // The field the reader is typing in keeps the keyboard while the cell
    // navigates or presses "More results" for a search (2026-10-11: "i type a
    // number and am instantly kicked out"): a webview takes focus when it
    // loads or takes input, so a field the reader was in is given it back --
    // only when the cell's OWN action took it, never a click of the reader's.
    this.registerDomEvent(document, "focusin", (e: FocusEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && t !== view && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable)) this.readerField = t;
    });
    view.addEventListener("focus", () => this.giveBackFocus());
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
                                     (cid, url, stored) => {
                                       // Only a hover ON THE PAGE SHOWN: while a new document
                                       // loads, the session is still the old page, and a hover
                                       // from the new page's sensor was looked up in the old
                                       // page's tree -- a TMDB hover opened an archive.org
                                       // chunk (2026-10-17, "very serious url and chunk
                                       // degradation"). Planted: `cross-page-hover`.
                                       const shown = this.currentPage();
                                       if (cid && url && shown && docKey(url) !== docKey(shown) && !this.plant.has("cross-page-hover")) {
                                         this.hoverStats.cross_page_refused++;
                                         this.lastHovered = null;
                                         this.onHover("", "", "");
                                         return;
                                       }
                                       this.lastHovered = cid ? { cid, url, stored: stored || "" } : null;
                                       this.onHover(cid, url, stored);
                                     });
      this.pipebox.urlOf = (u: string) => this.sessionAliases.get(u) || u;
      this.pipebox.shownUrl = () => this.shownUrl();
      // Hover-first (`G-80`): the pointer is over something the store does
      // not hold yet, so drain now instead of on the next tick.
      this.pipebox.onUnresolved = () => { if (!this.draining) void this.tick(); };
      // The outline's unit is the STORED chunk once the store knows the page.
      this.pipebox.storedFor = (cid, url) => this.storedCidFor(cid, url);
      this.pipebox.setPins(this.pinList());
      this.paintBoxes();
    } catch (err) {
      console.error("vertiscope: the pipeline box failed to build", err);
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
        this.pageMovedAt = Date.now();
        this.pushedDrains++;
        if (!this.draining) void this.tick();
        else this.drainAgain = true;
      } else if (body === "scroll") {
        this.pageMovedAt = Date.now();
        this.pageScrolledAt = Date.now();
        // Every box moved and nothing mutated: the overlay re-measures what
        // it shows (pins, the streaming diff boxes) from the page's new place.
        this.pipebox?.pageScrolled();
      } else if (body.startsWith("hover ")) {
        // Planted by D-40's check: the old path, hover found by the poll.
        if (this.plant.has("poll-hover")) return;
        // The reader's pointer moving over the page is the reader using the app
        // (unless a check or a stress run is going: their synthetic moves are
        // not the reader).
        // ...but only if the PAGE did not just move: on a feed or a carousel
        // the element under a still pointer keeps changing, the sensor
        // reports a hover each time, and the idle turn never ran ("rotating
        // xyzhsv stalls out after some time", 2026-10-17). A page that
        // scrolled or mutated in the last 400 ms moved itself. Planted:
        // `hover-always-reader`.
        const by: Record<string, number> = ((window as any).__vertiscopeReaderBy = (window as any).__vertiscopeReaderBy || {});
        const pageMoved = Date.now() - this.pageMovedAt < 400 && !this.plant.has("hover-always-reader");
        if (pageMoved) by["hover-page-moved"] = (by["hover-page-moved"] || 0) + 1;
        else if (!(window as any).__vertiscope?.verify?.state?.()?.running && !(window as any).__vertiscopeStressing) {
          (window as any).__vertiscopeReaderAt = Date.now();
          by["hover"] = (by["hover"] || 0) + 1;
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
    // The session follows the DOCUMENT the moment it commits, not when it
    // finishes loading: in between, the new page's sensor already pushed
    // hovers, and they were read against the old page (2026-10-17, a TMDB
    // hover opened an archive.org chunk while TMDB loaded for 15 s).
    // The url the cell shows, kept from the webview's own commits (see
    // `shownUrl`). Registered first, so every handler below reads the new one.
    view.addEventListener("did-navigate", (e: any) => { if (e && e.isMainFrame !== false) this.noteShown(String(e.url || "")); });
    view.addEventListener("did-navigate-in-page", (e: any) => { if (e && e.isMainFrame) this.noteShown(String(e.url || "")); });
    view.addEventListener("did-navigate", (e: any) => {
      if (!e || e.isMainFrame === false || this.plant.has("session-at-load")) return;
      const u = String(e.url || "");
      if (/^https?:/.test(u)) void this.pageChanged(u, true);
    });
    // The main frame's status: `did-navigate` does not carry it on a webview,
    // `did-frame-navigate` does (G-249 -- a 502 is not the page).
    view.addEventListener("did-frame-navigate", (e: any) => {
      if (e && e.isMainFrame) this.docStatus = { seq: this.docSeq, status: Number(e.httpResponseCode) || 0 };
    });
    view.addEventListener("did-start-navigation", (e: any) => {
      if (e && e.isMainFrame && !e.isInPlace && !e.isSameDocument) {
        this.domReady = false; this.loadFailedUrl = "";
        // A new DOCUMENT: no url of the old one stands for this session.
        this.sessionAliases.clear(); this.pendingInPage = "";
        this.docSeq++;
        profiler().visitStart(String(e.url || ""));
        // Leaving the offline form for a LIVE page ends offline (G-62). Only
        // the button cleared it, so any other navigation left the cell
        // "offline" for good: every hover panel was then docked, pinned and
        // never expired (2026-10-11, G-125's check -- offlineFor named a
        // fixture page two runs gone). The offline form itself is a file:
        // url and keeps it. Planted: only the button clears it.
        if (this.offlineFor && /^https?:/.test(String(e.url || "")) && !this.plantStickyOffline) this.offlineFor = "";
      }
    });
    view.addEventListener("did-stop-loading", () => {
      if (this.saveOfflineOn()) this.scheduleOfflineSave();
      this.address.value = view.getURL();
      try {
        const u = view.getURL();
        if (/^https?:/.test(u)) (this.app as any).saveLocalStorage?.("vertiscope-browser-last", u);
      } catch { /* not attached */ }
      this.say(view.getTitle() || view.getURL());
      // A PDF is read as a document, not folded as a viewer (G-248).
      void this.maybePdf();
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
    // A server REDIRECT moves the visit to its target's address (bandcamp:
    // `radio?show=1010` -> `/radio/1010`); its stages are marked there.
    view.addEventListener("did-redirect-navigation", (e: any) => {
      if (e && e.isMainFrame) profiler().visitAlias(String(e.url || ""));
    });
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
        profiler().visitAlias(String(view.getURL()));
        // Not decided HERE (G-216, 2026-10-17). archive.org's search list
        // rewrites its own url as it scrolls (`&page=2` ... `&page=7`); taken
        // as seven pages, the same growing list was captured seven times, a
        // settle queued per "left" page, and the capture backlog reached 80.
        // A route change in an app (YouTube, Bluesky) is ALSO an in-page
        // navigation, so the url cannot tell them apart -- the content can:
        // the first drain under the new url says whether the page's chunks
        // stayed (the same document, still growing) or went (a new page).
        if (this.session && !this.plant.has("inpage-is-new-page")) this.pendingInPage = String(view.getURL());
        else void this.pageChanged(view.getURL(), true);
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
      // The chunk under the pointer, to the graph at once: in right-click
      // mode its panel opens (G-215, 2026-10-17: "panel fly to and right
      // click on hovers doesn't function on the toggle" -- only a 3D node's
      // right-click was wired). The menu and the double right-click pin are
      // unchanged.
      if (this.lastHovered && !this.plant.has("no-browser-right")) {
        const h = this.lastHovered;
        this.onRightChunk(h.cid, h.url, h.stored || this.storedCidFor(h.cid, h.url));
      }
      window.clearTimeout(this.menuTimer);
      this.menuTimer = window.setTimeout(() => this.contextMenu(p, x, y),
                                         BrowserView.DOUBLE_RIGHT_MS);
    });

    view.addEventListener("did-fail-load", (e: any) => {
      // -3 is ABORTED, which is what a redirect away from a page reports.
      // Showing it as a failure would make every redirect look broken.
      if (e.errorCode !== -3) this.say(`did not load: ${e.errorDescription}`);
      if (e.errorCode !== -3 && e.isMainFrame !== false) this.loadFailedUrl = String(e.validatedURL || "");
      // No connection: the page opens from what the store holds (`G-62`).
      if ((BrowserView.NO_CONNECTION.has(e.errorCode) || (this.plantRefusedIsOffline && e.errorCode === -102)) && e.isMainFrame !== false
          && /^https?:/.test(String(e.validatedURL || ""))) {
        void this.openOffline(String(e.validatedURL));
      }
    });

    back.onclick = () => { if (view.canGoBack()) view.goBack(); };
    fwd.onclick = () => { if (view.canGoForward()) view.goForward(); };
    reload.onclick = () => view.reload();
    this.address.addEventListener("keydown", (e: KeyboardEvent) => {
      if (e.key !== "Enter") return;
      // Words search DuckDuckGo; a place is gone to (G-202, `address.ts`).
      const to = this.plant.has("address-literal") ? { url: this.address.value, search: false }
        : addressTarget(this.address.value);
      if (to.search) this.addressStats.searched++; else this.addressStats.went++;
      if (to.url) this.go(to.url);
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
      const last = String((this.app as any).loadLocalStorage?.("vertiscope-browser-last") || "");
      if (last && /^https?:/.test(last) && !/[?&](d3[5-7]|g9[34]|d36)=/.test(last)) {
        window.setTimeout(() => this.go(last), 300);
      }
    } catch { /* storage unavailable: start blank */ }
  }

  async onClose(): Promise<void> {
    // The capture pump stops with the view. It kept sending its queue -- and
    // retrying refusals for up to 15 minutes -- after a plugin reload, beside
    // the new view's pump: two sensors' drains for one url interleaved on the
    // sidecar's session, each mismatch dropped the session, and both were
    // refused in a loop, several a second (2026-10-18). The new view's sensor
    // sends the shown page whole; what the old queue held is counted, not
    // sent. Planted `pump-after-close`: as before.
    if (!this.plant.has("pump-after-close")) {
      this.closed = true;
      this.abandonedOnClose = this.captureQueue.filter((c) => !c.settle).length;
      this.captureQueue = this.captureQueue.filter((c) => c.settle);
    }
    // Timers this view started outside `registerInterval` stop with it (a
    // closed view's code otherwise kept firing after a plugin reload).
    window.clearInterval(this.placeTimer); this.placeTimer = 0 as any;
    window.clearTimeout(this.offlineTimer); this.offlineTimer = 0;
    this.pipebox?.destroy();
    this.pipebox = null;
    // Settle whatever page was being captured. Per-drain writes are deltas;
    // a pane closed mid-page would leave the store holding the last delta
    // rather than the finished trie.
    if (this.session) {
      const leaving = this.session;
      this.session = "";
      void this.sidecar.capture(leaving, { settle: true })
        .then((r) => this.noteDiff(r && !r.error ? r.diff : null));
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
    await leaf.setViewState({ type: "vertiscope-browser-view", active: true });
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
    // Planted `no-settle` (G-221): a stored, unchanged chunk streams again as
    // new -- going back to a page repeated its whole scan in the 3D view.
    if (!map || map.url !== url || this.plant.has("no-settle")) return [];
    return Object.entries(covers).filter(([, cid]) => map.stored.has(cid)).map(([id]) => id);
  }

  /**
   * The STORED chunk under a pushed hover (`f:<url>#<sensor id>`), through
   * the same chunk map the diff's covers use -- so the 3D view can fly to and
   * open the chunk the reader is pointing at, wherever it sits in the diff.
   * "" when the map does not know it yet.
   */
  /** Like `storedCidFor`, and whether the cover is the chunk ITSELF or only
   *  a stored ancestor (the nearest-ancestor walk). */
  storedCoverFor(cid: string, url: string): { cid: string; exact: boolean } {
    this.lastCoverExact = false;
    const got = this.storedCidFor(cid, url);
    return { cid: got, exact: this.lastCoverExact };
  }
  private lastCoverExact = false;
  storedCidFor(cid: string, url: string): string {
    const m = /^f:(.*)#(\d+)(?:\.\d+)?$/.exec(cid || "");
    if (!m) return "";
    // A force id names its page: resolved only within THAT page, never
    // through another page's tree or map (the cross-page hover, 2026-10-17).
    if (docKey(m[1]) !== docKey(url) && !this.plant.has("cross-page-hover")) return "";
    const tree = this.forceTrees.get(url) || this.forceTrees.get(m[1]);
    if (!tree) return "";
    const id = tree.nodeId(Number(m[2]));
    const held = tree.held().filter((h: any) => h.id === id);
    if (!held.length) return "";
    const exact = this.coversFor(url, held)[id];
    if (exact) this.lastCoverExact = true;
    if (exact || this.plantNoAncestorHover) return exact || "";
    // For a HOVER, the stored chunk that draws the element may be anchored
    // ABOVE the page's own (finer) chunk -- a cast card in a stored grid.
    // `coversFor` refuses ancestors on purpose (a new paragraph inside a
    // stored section is the diff), so every hover on an already stored page
    // resolved to nothing and the camera stopped flying (2026-10-10: "Fly to
    // hovered degradation spotted as well when navigated to a new website").
    // The map's own nearest-ancestor walk, the one `/resolve` does.
    const map = this.pipebox?.map;
    if (!map || docKey(map.url) !== docKey(url)) return "";
    // Within THREE steps of the hovered element. Further up, a stored
    // ancestor is a container standing for a whole region -- archive.org's
    // tile resolved to the home page's root container (its search header)
    // and the search page's tiles to its hidden feedback survey (2026-10-17).
    // A card in a stored grid is a step or two up. Planted: any depth.
    const steps = this.plant.has("ancestor-any-depth") ? 40 : 4;
    const chain: string[] = [];
    let a = held[0].address;
    while (a && chain.length < steps) { chain.push(a); const cut = a.lastIndexOf("/"); if (cut <= 0) break; a = a.slice(0, cut); }
    const hit = map.lookup(chain);
    return hit ? hit.cid : "";
  }
  /** Planted: hovers resolve only where `coversFor` does (the dead fly-to). */
  plantNoAncestorHover = false;

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
  /** Told by the plugin: the central diff of a capture or a settle -- every
   *  view applies this one record (added / retired / renamed / known). */
  onDiff: (diff: CentralDiff) => void = () => {};
  /** Diffs this cell has applied, for the harness. */
  diffsApplied = { seen: 0, retired: 0, renamed: 0, pins_rekeyed: 0, pins_reresolved: 0, pins_lost: 0 };

  /**
   * Apply one central diff (`_page_diff`) to what THIS cell holds, then hand
   * the same record to every other view. The chunk map drops retired cids and
   * re-keys renamed ones; a pin keyed by a renamed cid follows it (a shift
   * moved the chunk's address, not its content), so its outline, its markdown
   * card and its billboard stay on the same content. A pin on a chunk that
   * was retired WITHOUT a successor is left as the reader set it: the reader
   * lets it go, the diff does not take a pin away.
   *
   * **But it is re-anchored by its ADDRESS** (G-82, 2026-10-17). A pin is
   * the reader pointing at `url : xpath`; the chunk id is only which chunk
   * drew that address when they pointed. A capture that re-cuts the page
   * retires the id with no same-markdown successor, and the pin kept a cid
   * the store no longer had: the graph's `/place` found nothing and the
   * second of two pins opened no billboard (`561404dd`: "no such chunk").
   * The pin's address is resolved again and the pin moves to the chunk that
   * draws it now. Nothing draws it any more: left as the reader set it.
   * Planted (`no-pin-reresolve`): the old behaviour.
   */
  private noteDiff(diff: CentralDiff | null | undefined): void {
    if (!diff || typeof diff !== "object" || !Array.isArray(diff.retired)) return;
    this.diffsApplied.seen++;
    const map = this.pipebox?.map;
    if (map && map.url === diff.url) {
      const got = map.applyDiff(diff);
      this.diffsApplied.retired += got.dropped;
      this.diffsApplied.renamed += got.renamed;
    }
    const renamed = diff.renamed || {};
    const moved = [...this.pinned.keys()].filter((c) => renamed[c] && !this.pinned.has(renamed[c]));
    if (moved.length) {
      this.pinned = new Map([...this.pinned].map(([cid, rec]): [string, PinRecord] =>
        renamed[cid] && moved.includes(cid)
          ? [renamed[cid], { ...rec, cid: renamed[cid] }] : [cid, rec]));
      this.pipebox?.setPins(this.pinList());
      void this.renderSide();
      for (const old of moved) {
        this.onUnpin(old);
        this.onPin(renamed[old]);
      }
      this.diffsApplied.pins_rekeyed += moved.length;
    }
    const gone = new Set(diff.retired);
    const lost = [...this.pinned.keys()].filter((c) => gone.has(c) && !renamed[c]);
    if (lost.length && !this.plant.has("no-pin-reresolve")) void this.reanchorPins(lost);
    try { this.onDiff(diff); } catch (e) { console.error("vertiscope: onDiff failed", e); }
  }

  /** Pins whose chunk was retired, moved to whatever draws their address now. */
  /** old cid -> the cid its pin moved to, for a check holding the old one. */
  reanchored = new Map<string, string>();
  async reanchorPins(lost: string[]): Promise<void> {
    let changed = false;
    for (const old of lost) {
      const rec = this.pinned.get(old);
      if (!rec) continue;
      const read = await this.readPin(rec.url, rec.matched);
      if ("error" in read || !read.cid || read.cid === old) { this.diffsApplied.pins_lost++; continue; }
      if (!this.pinned.has(old)) continue;        // let go while this was asking
      // Same slot in the stack: the reader's order is theirs.
      // The page's own rendering of the chunk, as a fresh pin takes it (D-36).
      await this.takeSnapshot(read).catch(() => undefined);
      this.pinned = new Map([...this.pinned].map(([cid, r]): [string, PinRecord] =>
        cid === old ? [read.cid, read] : [cid, r]));
      this.onUnpin(old);
      this.onPin(read.cid);
      this.reanchored.set(old, read.cid);
      this.diffsApplied.pins_reresolved++;
      changed = true;
    }
    if (changed) {
      this.pipebox?.setPins(this.pinList());
      void this.renderSide();
    }
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
    here = this.currentPage();
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
  /** The page form re-read WITH the store's address table, so its controls
   *  are live (the fast path from the chunk map carries no addresses). */
  async snapshotAddressed(cid: string, lines: any[]): Promise<boolean> {
    let here = "";
    here = this.currentPage();
    if (!here || !lines || !lines.length) return false;
    await this.takeSnapshot({ cid, url: here, matched: "", markdown: "", head: "",
                              xpaths: xpathsOfLines(lines), addrs: addressTable(lines) });
    return !!getSnapshot(cid);
  }

  // ---- saved page forms (PLUGIN_GOAL 51) ---------------------------------
  //
  // "I should also never see the notification that something that we have
  // already chunked and tracked is inaccessible ... we still can render the
  // originally scanned chunk before the shadow scripts removed the
  // informations" (2026-10-10). Every stored chunk of the open page has its
  // page form taken while its elements are on the page and SAVED (the blob
  // beside the store, mapped as `Chunk.snap`), a few at a time and never
  // while the page scrolls; a chunk a capture rewrites is taken again.
  private savedForms = new Set<string>();
  /** When the sensor last drained into the cell (performance.now). */
  lastDrainAt = 0;
  private savedFormsUrl = "";
  private saverTimer = 0;
  saverStats = { taken: 0, saved: 0, failed: 0, batches: 0, last_ms: 0, url: "", media: 0, media_refused: 0, media_failed: 0 };
  /** Pictures waiting to be saved, and every one already asked for. */
  private mediaQueue = new Set<string>();
  private mediaSaved = new Set<string>();
  /** Planted: page forms saved without their pictures (they render only online). */
  plantNoMedia = false;
  /** Streamed chunks placed before the store: the hook and its record. */
  onProjected: (url: string, got: any) => void = () => {};
  transientStats = { asked: 0, placed: 0, last_ms: 0 };
  /** Planted: streamed chunks wait grey for the store, as before. */
  plantNoTransient = false;
  /** Planted: no page form is ever saved (the banner's world). */
  plantNoSaver = false;

  scheduleFormSaver(delay = 1200): void {
    if (this.saverTimer || this.plantNoSaver) return;
    this.saverTimer = window.setTimeout(() => { this.saverTimer = 0; void this.saveFormsSlice(); }, delay);
  }

  /** A capture rewrote these: their saved forms are taken again. */
  formsDirty(cids: string[]): void {
    for (const c of cids) this.savedForms.delete(c);
    this.scheduleFormSaver();
  }

  private async saveFormsSlice(): Promise<void> {
    const map = this.pipebox?.map;
    const wv = this.webview;
    if (!map || !wv || this.plantNoSaver) return;
    let here = "";
    here = this.currentPage();
    if (!here || !map.url || docKey(map.url) !== docKey(here)) return;
    if (this.savedFormsUrl !== map.url) { this.savedForms.clear(); this.savedFormsUrl = map.url; }
    // Only while the page is STILL. The clone runs in the page's own thread,
    // the one the sensor drains from: eight chunks a slice held the page 14.7
    // s of 40 while the reader browsed archive.org and streamed updates
    // lagged behind it (2026-10-10: "Significant render lag on streamed
    // updates"). Two a slice, never within 2 s of a scroll, a hover or a drain.
    const now = performance.now();
    const busy = Math.max(this.pipebox?.lastScrollAt || 0, this.pipebox?.hover?.at || 0, this.lastDrainAt || 0);
    if (now - busy < 2000) { this.scheduleFormSaver(2500); return; }
    const todo = map.cids().filter((c) => !this.savedForms.has(c)).slice(0, 2);
    if (!todo.length) return;
    const t0 = performance.now();
    const items: { cid: string; snap: any }[] = [];
    for (const cid of todo) {
      this.savedForms.add(cid);
      const xs = map.xpaths(cid);
      if (!xs.length) continue;
      try {
        const snap = await wv.executeJavaScript(snapshotScript(xs, {}));
        if (snap && snap.html) { items.push({ cid, snap }); putSnapshot(cid, snap as Snapshot); this.saverStats.taken++; }
      } catch { this.saverStats.failed++; }
    }
    // The pictures these forms draw, queued to be saved too ("Even media").
    for (const it of items) {
      String(it.snap.html || "").replace(/<(?:img|video|audio|source)\b[^>]*?\bsrc=["'](https?:\/\/[^"']+)["']/gi,
        (_m: string, u: string) => { if (!this.mediaSaved.has(u)) this.mediaQueue.add(u); return ""; });
    }
    if (items.length) {
      const got: any = await this.sidecar.saveSnapshots(items);
      if (got && !got.error) this.saverStats.saved += got.mapped || 0;
      else { this.saverStats.failed += items.length; for (const it of items) this.savedForms.delete(it.cid); }
      this.saverStats.batches++;
    }
    // Up to four pictures a slice, fetched as the page loaded them (Obsidian's
    // own request, not the page's -- nothing is written into the page).
    if (!this.plantNoMedia) {
      for (const u of [...this.mediaQueue].slice(0, 4)) {
        this.mediaQueue.delete(u);
        this.mediaSaved.add(u);
        try {
          const r = await requestUrl({ url: u, throw: false });
          const ct = String((r.headers && (r.headers["content-type"] || r.headers["Content-Type"])) || "");
          if (r.status >= 200 && r.status < 300 && r.arrayBuffer && r.arrayBuffer.byteLength) {
            const got: any = await this.sidecar.saveMedia(u, r.arrayBuffer, ct);
            if (got && got.saved) this.saverStats.media++; else this.saverStats.media_refused++;
          } else this.saverStats.media_failed++;
        } catch { this.saverStats.media_failed++; }
      }
    }
    this.saverStats.last_ms = Math.round(performance.now() - t0);
    this.saverStats.url = map.url;
    if (map.cids().some((c) => !this.savedForms.has(c)) || this.mediaQueue.size) this.scheduleFormSaver(2500);
  }

  /** Fast-path snapshots re-taken with their controls addressed (G-183). */
  snapAddressed = 0;
  private addrsFor = new Map<string, { addrs: any; at: number }>();
  async snapshotChunk(cid: string, url: string, again = false): Promise<boolean> {
    // `again`: re-read the live page even when a snapshot is held -- an open
    // panel after a diff, or a panel just opened (2026-10-06: the held one was
    // served forever, and the page form showed a stale grey mask).
    if (!cid) return false;
    if (!again && getSnapshot(cid)) return true;
    let here = "";
    here = this.currentPage();
    if (!here || docKey(here) !== docKey(url || "")) return false;
    // FAST: the chunk's elements from the browser's own chunk map -- no
    // sidecar round trip, which queued behind the capture's writes (panel
    // first paint p90 1.8 s while a page was being captured, 2026-10-07).
    const map = this.pipebox?.map;
    const local = map && docKey(map.url) === docKey(here) ? map.xpaths(cid) : [];
    if (local.length) {
      const known = this.addrsFor.get(cid);
      const addrsNow = known && performance.now() - known.at < 60000 ? known.addrs : null;
      await this.takeSnapshot({ cid, url: here, matched: "", markdown: "", head: "",
                                xpaths: local, addrs: addrsNow || {} } as any);
      // The map KNOWS this chunk's elements: if the page drew nothing for
      // them, the store's copy of the same addresses finds nothing either.
      // Falling through cost a 137 ms sidecar fetch and a second in-page
      // clone per panel, twice per panel (2026-10-11: first paint 222-763 ms,
      // "Overlay panel showing in the 3D GUI is now extremely slow").
      //
      // But the map holds xpaths, not ADDRESSES: painted from it, nothing in
      // the panel is tagged with its trie address, so every control is cloned
      // DISABLED -- IMDb's search box could not be typed into (2026-10-12:
      // "I can't enter things in the search bar but I should be able to
      // through the patricia trie"). Where the snapshot holds a control, the
      // addresses follow in the background and the panel is drawn again,
      // live; a panel with none pays nothing.
      const first = getSnapshot(cid);
      if (!addrsNow && first && /<(input|textarea|select|button)\b/i.test(first.html) && !this.plant.has("fast-unaddressed")) {
        void this.sidecar.chunk(cid).then(async (payload: any) => {
          const lines = (payload && payload.lines) || [];
          if (!lines.length) return;
          let now = "";
          now = this.currentPage();
          if (docKey(now) !== docKey(here)) return;
          const addrs = addressTable(lines);
          // Kept a minute, so the redraw this asks for paints addressed at
          // once instead of fetching again (and asking again, forever).
          this.addrsFor.set(cid, { addrs, at: performance.now() });
          await this.takeSnapshot({ cid, url: here, matched: "", markdown: "", head: "",
                                    xpaths: local, addrs } as any);
          this.snapAddressed++;
          this.onDirty([cid]);
        }).catch(() => { /* the unaddressed panel stays */ });
      }
      return !!first;
    }
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

  /**
   * The live sensor's chunking policy. `merge` gathers small siblings into
   * runs up to the budget, and `semantic` keeps a block a reader thinks of as
   * one thing whole: a forum row or a field list is ONE in-page unit, as the
   * store keeps it (2026-10-10: "This should be all one chunk, but it is
   * erroneously split up into subchunks for the same card"; "per-field chunk
   * degradation on overlay"). On since the sweep stopped untracking merged
   * runs (G-142). Planted `no-merge`: one unit per element, as before.
   */
  sensorVariants(): string {
    const v: string[] = [];
    if (!this.plant.has("no-merge")) v.push("merge: true", "semantic: true");
    if (this.plant.has("no-late-roots")) v.push("nolateroots: true");
    // G-233's planted arm: a <pre> cut into its highlighting spans, as before.
    if (this.plant.has("codespans")) v.push("codespans: true");
    // G-197's planted arm: an SVG's `xmlns:xlink` taken as a picture, as before.
    if (this.plant.has("xmlnsurl")) v.push("xmlnsurl: true");
    return "{" + v.join(", ") + "}";
  }

  /** The markdown side: one card per pinned chunk, natively rendered. */
  private async renderSide(): Promise<void> {
    this.markdownWrap.empty();
    if (!this.pinned.size) {
      this.markdownWrap.createDiv({ cls: "vertiscope-browser-empty" }).setText(
        "Double right-click a chunk in the browser to pin it here.");
      return;
    }
    for (const pin of this.pinned.values()) {
      const card = this.markdownWrap.createDiv({ cls: "vertiscope-pin-card" });
      card.dataset.cid = pin.cid;
      // The card is the pin's handle in the slate: clicking it brings the
      // chunk's billboard back in the 3D view, expanded (2026-09-26).
      card.onclick = (e: MouseEvent) => {
        if ((e.target as HTMLElement)?.closest?.(".vertiscope-pin-close, a")) return;
        this.onPin(pin.cid);
      };
      const head = card.createDiv({ cls: "vertiscope-browser-mdhead" });
      // The site, not the xpath: the address is kept as the tooltip.
      let host = "";
      try { host = new URL(pin.url).host; } catch { /* not a url */ }
      head.createSpan({ text: host || pin.head }).setAttr("title", pin.head);
      const close = head.createSpan({ cls: "vertiscope-pin-close", text: "\u00d7" });
      close.setAttr("aria-label", "unpin");
      close.onclick = () => this.unpin(pin.cid);
      const body = card.createDiv({ cls: "vertiscope-browser-mdbody" });
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
        const more = card.createEl("details", { cls: "vertiscope-pin-md" });
        more.createEl("summary", { text: "markdown" });
        const md = more.createDiv({ cls: "vertiscope-browser-mdbody" });
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

  /** When the page last scrolled or mutated itself (its pushed signals). */
  private pageMovedAt = 0;
  /** When the page last scrolled (its pushed "scroll"). */
  private pageScrolledAt = 0;
  /** Documents loaded in this cell, and which one the session belongs to. */
  private docSeq = 0;
  /** The main frame's HTTP status, for the document it belongs to (G-249). */
  private docStatus = { seq: -1, status: 0 };
  /** The document's gate verdict, decided on its first drain (G-249). */
  private gate: { seq: number; v: GateVerdict } = { seq: -1, v: { why: "", kind: "" } };
  /** The document that is a PDF (its viewer's DOM is not the page), by docSeq. */
  private pdfDoc = -1;
  /** PDFs read and chunked (G-248). Planted `no-pdf`: a PDF is left to the viewer, as before. */
  pdfStats = { seen: 0, sent: 0, chunks: 0, pages: 0, last: "", error: "", ms: 0, read_ms: 0, bytes: 0, store_ms: 0 };
  /** Drains and documents kept out of the store as page STATES (G-249). */
  gateStats = { drains: 0, docs: 0, last: "", lastSeq: -1, at: 0 };
  private sessionDocSeq = -1;
  /** The PAGE the cell shows: its url, or the session it is an alias of --
   *  archive.org's list rewrites its url as it scrolls, and every check of
   *  "is this page open" compared the raw url (`&page=7`) with the session's
   *  and refused: snapshots, the page form, the form saver (2026-10-17). */
  /**
   * **The url the cell shows, without asking the main process.** `getURL()`
   * on a webview is a SYNCHRONOUS round trip to Electron's main process, and
   * the graph asked it on every force tick (`calm` -> `browsingUrl`), the
   * hover path on every push and the box on every paint: 1.0 s of 40 on the
   * Julia forum in `invokeSync`, and while the main process was busy relaying
   * the page's traffic each ask blocked the frame -- long tasks of 140-370 ms
   * that held a hover's outline (D-40: ours p95 347 ms, 2026-10-19). The url
   * changes only when the page commits a navigation, and the webview says so
   * (`did-navigate`, `did-navigate-in-page`); it is kept from those, and read
   * again at most once a second in case one was missed. Planted `sync-url`:
   * asked every time, as before.
   */
  shownUrl(): string {
    const now = performance.now();
    if (this.plant.has("sync-url") || now - this.shownAt > 1000) {
      try { this.shown = this.webview?.getURL() || ""; } catch { return this.shown; }
      this.shownAt = now;
      this.shownAsks++;
    }
    return this.shown;
  }
  private shown = "";
  private shownAt = -Infinity;
  /** Synchronous asks made (the harness reads it). */
  shownAsks = 0;
  private noteShown(u: string): void { if (u) { this.shown = u; this.shownAt = performance.now(); } }
  currentPage(): string {
    let u = "";
    try { u = this.shownUrl(); } catch { return ""; }
    if (u && u === this.pendingInPage && this.session) return this.session;   // undecided: still the session's
    return this.sessionAliases.get(u) || u;
  }
  hoverStats = { cross_page_refused: 0 };
  /** An in-page navigation waiting for its first drain to say what it is (G-216). */
  private pendingInPage = "";
  /** Urls the page took without leaving its document -> the session's url. */
  private sessionAliases = new Map<string, string>();
  inPageStats = { same_doc: 0, new_page: 0, adopted: 0 };
  /** The tree that last decoded each document's stream (by `docSeq`). */
  private docTrees = new Map<number, ForceTree>();
  /** What the address bar sent where (G-202). */
  addressStats = { searched: 0, went: 0 };
  /** Navigate. Bare hosts get https, because a reader types `arxiv.org`. */
  go(where: string): void {
    if (!this.webview || !where.trim()) return;
    const url = /^[a-z]+:/i.test(where) ? where : `https://${where}`;
    this.address.value = url;
    this.webview.loadURL(url);
    this.layoutSide();
  }

  // ---- PLUGIN_GOAL 85: the web half of a search ---------------------------

  /**
   * A query searched on DuckDuckGo, in THIS cell, so the results page is
   * captured like any page and streams into the store and the 3D view as a
   * diff. The cell scrolls to the end and presses "More results" in a loop
   * that is EXHAUSTIVE (item 105): it ends only when a round adds no results
   * (no delta) or the button is gone, and `stopped` says which. Real pointer
   * input at the button's place on the page, the way the reader's mouse
   * arrives (nothing is written into the document; scrolling moves the
   * viewport). A newer query cancels an older one. Bot checks are never
   * answered: a page with no results and no button just ends the run.
   */
  webSearchStats = { asked: 0, rounds: 0, clicked: 0, results: 0, last: "", ms: 0, stopped: "", deltas: [] as number[] };
  private webSeq = 0;
  /** Planted (item 85): the web half never runs. */
  plantNoWebSearch = false;
  /** The field the reader last typed in, and when the cell last acted itself. */
  private readerField: HTMLElement | null = null;
  private selfActedAt = -1e9;
  focusStats = { restored: 0, stolen: 0 };
  /** Planted: the cell keeps the focus it took. */
  plantKeepFocus = false;
  private selfAct(): void {
    this.selfActedAt = performance.now();
    for (const ms of [30, 250, 800]) window.setTimeout(() => this.giveBackFocus(), ms);
  }
  private giveBackFocus(): void {
    const view = this.webview;
    if (!view || document.activeElement !== view) return;
    if (performance.now() - this.selfActedAt > 1500) return;    // the reader's own click
    const f = this.readerField;
    if (!f || !f.isConnected) return;
    this.focusStats.stolen++;
    if (this.plantKeepFocus) return;
    f.focus({ preventScroll: true });
    if (document.activeElement === f) this.focusStats.restored++;
  }
  /** Planted (item 105): the old fixed count -- three rounds, then stop. */
  plantFixedRounds = 0;
  /** How long a round waits for its results to arrive before calling it no delta. */
  webDeltaWaitMs = 4000;
  async searchWeb(query: string): Promise<any> {
    const wv = this.webview;
    if (!wv || !query.trim() || this.plantNoWebSearch) return null;
    const seq = ++this.webSeq;
    const t0 = performance.now();
    const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
    const url = "https://duckduckgo.com/?q=" + encodeURIComponent(query.trim()) + "&ia=web";
    this.webSearchStats.asked++;
    this.webSearchStats.last = query.trim();
    this.webSearchStats.stopped = "";
    this.webSearchStats.deltas = [];
    this.webSearchStats.rounds = 0;
    this.webSearchStats.ms = 0;
    this.selfAct();
    this.go(url);
    for (let i = 0; i < 80; i++) {
      await sleep(150);
      if (seq !== this.webSeq) return null;
      if (i % 4 === 0) this.selfAct();          // a load in flight may take the keyboard late
      try { if (!wv.isLoading() && /duckduckgo\.com/.test(wv.getURL())) { this.selfAct(); break; } } catch { /* not attached */ }
    }
    const wc = (window as any).require("@electron/remote").webContents.fromId(wv.getWebContentsId());
    const count = async () => Number(await wv.executeJavaScript(
      "document.querySelectorAll('article[data-testid=\"result\"], li[data-layout=\"organic\"]').length").catch(() => 0)) || 0;
    // Until the page stops growing or offers no more: no round count (item 105).
    // The results arrive some time after the press, so a round waits for the
    // count to move -- up to `webDeltaWaitMs` -- before it calls the round empty.
    const grew = async (from: number) => {
      for (let w = 0; w < this.webDeltaWaitMs; w += 250) {
        await sleep(250);
        if (seq !== this.webSeq) return -1;
        const n = await count();
        if (n > from) { await sleep(300); return await count(); }
      }
      return from;
    };
    await sleep(900);
    let have = await count();
    for (;;) {
      if (seq !== this.webSeq) return null;
      if (this.plantFixedRounds && this.webSearchStats.rounds >= this.plantFixedRounds) {
        this.webSearchStats.stopped = "fixed rounds (planted)";
        break;
      }
      // To the end of the list: the viewport moves, the page does not change.
      // A page that loads more on scroll alone grows here.
      await wv.executeJavaScript("window.scrollTo(0, document.documentElement.scrollHeight); 1").catch(() => 0);
      await sleep(700);
      // The button's place on the page, read; then pressed by pointer input.
      const at = await wv.executeJavaScript(`(function(){
        var b = document.getElementById('more-results') || Array.prototype.slice.call(document.querySelectorAll('button, a'))
          .filter(function(x){ return /^\\s*more results\\s*$/i.test(x.textContent || ''); })[0];
        if (!b) return null;
        b.scrollIntoView({ block: 'center' });
        var r = b.getBoundingClientRect();
        return r.width > 0 ? [Math.round(r.left + r.width / 2), Math.round(r.top + r.height / 2)] : null;
      })()`).catch(() => null);
      this.webSearchStats.rounds++;
      if (!at) {
        // No button: the list may still have grown from the scroll itself.
        const after = await grew(have);
        if (after < 0) return null;
        this.webSearchStats.deltas.push(after - have);
        if (after > have) { have = after; continue; }
        this.webSearchStats.stopped = "no more-results button";
        break;
      }
      await sleep(250);
      this.selfAct();
      wc.sendInputEvent({ type: "mouseMove", x: at[0], y: at[1] });
      wc.sendInputEvent({ type: "mouseDown", x: at[0], y: at[1], button: "left", clickCount: 1 });
      wc.sendInputEvent({ type: "mouseUp", x: at[0], y: at[1], button: "left", clickCount: 1 });
      this.webSearchStats.clicked++;
      const after = await grew(have);
      if (after < 0) return null;
      this.webSearchStats.deltas.push(after - have);
      this.webSearchStats.results = after;
      if (after <= have) { this.webSearchStats.stopped = "no delta"; break; }
      have = after;
    }
    await sleep(800);
    this.webSearchStats.results = await count();
    this.webSearchStats.ms = Math.round(performance.now() - t0);
    return { ...this.webSearchStats, url: wv.getURL() };
  }

  /** Restrict the ranking to one shadow DOM, or release it (`G-70`). */
  //: Told the plugin, which tells the projector (`G-38`). Brokered, like
  //  every other cross-pane signal here: neither pane may require the other.
  onHover: (cid: string, url: string, stored?: string) => void = () => {};
  /** For a hovered grey chunk: the chunk that holds the element's unit, and
   *  the unit (`chunkForElement`), or null. */
  greyUnitFor(cid: string): { id: string; at: string } | null {
    const h = this.pipebox?.hover;
    if (!h || h.cid !== cid || !h.xpath || this.plant.has("grey-unit-by-hover-chunk")) return null;
    const m = /^f:(.*)#\d+(?:\.\d+)?$/.exec(cid);
    const tree = m ? this.forceTrees.get(m[1]) : null;
    // The sensor's own hovered chunk is preferred where it holds the unit.
    const sid = Number((/#(\d+)(?:\.\d+)?$/.exec(cid) || [])[1]);
    return tree ? tree.chunkForElement(String(h.xpath), 3, 60, Number.isFinite(sid) ? sid : -1) : null;
  }
  /** The element the reader's pointer is on, for the hovered grey chunk `cid`. */
  hoverElementOf(cid: string): string {
    const h = this.pipebox?.hover;
    return h && h.cid === cid ? String(h.xpath || "") : "";
  }
  /** Told on a right-click over the page with the chunk last hovered (G-215). */
  onRightChunk: (cid: string, url: string, stored: string) => void = () => {};
  private lastHovered: { cid: string; url: string; stored: string } | null = null;

  /** A grey (streamed, not yet stored) chunk's markdown, from its drain
   *  (PLUGIN_GOAL 125): the panel shows it at once, marked provisional. */
  forcePayload(key: string): any | null {
    // `cid|element`: the lines of chunk `cid` under the hovered element --
    // a tile, not the whole in-page container several tiles share
    // (archive.org, 2026-10-17: "hovering over vhs vault inbox does not
    // display the correct shadow chunk"). Planted: the whole chunk.
    const bar = String(key || "").indexOf("|");
    const id = bar >= 0 ? key.slice(0, bar) : key;
    const el = bar >= 0 && !this.plant.has("whole-grey-chunk") ? key.slice(bar + 1) : "";
    const m = /^f:(.*)#\d+(?:\.\d+)?$/.exec(id || "");
    if (!m || this.plant.has("no-force-panel")) return null;
    const tree = this.forceTrees.get(m[1]);
    const text = tree ? (el ? (tree.linesForElement(el) || tree.linesUnder(id, el)) : tree.linesOf(id)) : null;
    if (!text || !text.length) return null;
    // Each line keyed like a stored line (`url|xpath`), so one rule finds the
    // hovered element's unit in either (`unitOf`).
    const addrs = !el && tree ? tree.addrsOf(id) : null;
    return { cid: key, url: m[1], provisional: true,
             lines: text.map((t, i) => ({ text: t, key: addrs && addrs[i] ? `${m[1]}|${addrs[i]}` : "" })) };
  }
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
      const row = this.results.createDiv({ cls: "vertiscope-hit" });
      const head = row.createDiv({ cls: "vertiscope-hit-head" });
      head.createSpan({ cls: "vertiscope-hit-rank", text: String(i + 1) });
      head.createSpan({ cls: "vertiscope-hit-url", text: hit.url });
      if ((hit.members ?? 1) > 1) {
        head.createSpan({ cls: "vertiscope-hit-tag",
                          text: `${hit.members} merged` });
      }
      head.createSpan({ cls: "vertiscope-hit-tag",
                        text: `${hit.tokens ?? 0} tok` });
      // Which factor fired, not the product. The product of three small
      // numbers reads as zero and says nothing about why this ranked.
      head.createSpan({
        cls: "vertiscope-hit-score",
        text: `lex ${(hit.lexical ?? 0).toFixed(2)} · ` +
              `sem ${(hit.semantic ?? 0).toFixed(2)}`,
      });
      row.createDiv({ cls: "vertiscope-hit-preview", text: hit.preview });
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
      })(${JSON.stringify(chainFor(plan.kind, plan.xpath, rec.value, !!rec.enter))})`);
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
        here = this.currentPage();
        if (!here) break;
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
            {budget: 0, debounce: 80, variants: ${this.sensorVariants()}, known: [], signal: ${JSON.stringify(SIGNAL)},
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
    const url = this.currentPage();
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
    const url = this.currentPage();
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
  private async pageChanged(url: string, force = false): Promise<void> {
    // The same document under another url is not a page change (G-216); an
    // in-page navigation not yet decided waits for its first drain.
    url = this.sessionAliases.get(url) || url;
    if (url && url === this.pendingInPage) return;
    if (!force && this.session && url && url !== this.session && this.docSeq === this.sessionDocSeq
        && !this.plant.has("inpage-is-new-page")) return;
    if (!url || url === "about:blank") {
      // Leaving for a blank page is still LEAVING: the page left behind is
      // settled and collapses like any other (G-91 -- it used to return here
      // first, and the page stayed expanded for good).
      const left = this.session;
      this.session = "";
      if (left) {
        if (this.plant.has("drop-on-leave")) this.onLeaving(left);    // kept until settled (item 130)
        await this.settleQueued(left);
        if (this.session !== left) this.onLeft(left);
      }
      return;
    }
    if (url === this.session || (this.session && docKey(url) === docKey(this.session))) return;
    const leaving = this.session;
    this.session = url;
    this.sessionDocSeq = this.docSeq;      // the document this session reads (G-216)
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
      (map.constructor as any).plantNoCache = this.plant.has("no-map-cache");    // G-221's planted arm
      // The page's projected chunks come WITH its map (S-1): drawn the moment
      // the reader lands, from the projector's memory, not through the
      // placement queue behind the page's first capture.
      // The page's base url, for the markdown form's relative destinations.
      try { void this.webview?.executeJavaScript("document.baseURI").then((b: any) => putBase(url, String(b || ""))).catch(() => undefined); }
      catch { /* not attached */ }
      // RETRIED while the answer is missing (2026-10-11: "invisible panels
      // spotted in the chunk node view" -- Comparison_of_web_browsers sat with
      // an EMPTY map for its whole visit: the one landing load failed while
      // the app was frozen, the page was already stored so no capture came to
      // patch it, and every hover resolved to nothing). Only while the map is
      // still empty: a capture that patched it meanwhile is newer than a
      // reload would be. Planted: one attempt, as before.
      const loadMap = async (): Promise<boolean> => {
        for (const wait of this.plant.has("map-once") ? [0] : [0, 1500, 4000, 10000, 25000]) {
          if (wait) await new Promise((r) => window.setTimeout(r, wait));
          if (map.url !== url && wait) return false;
          if (wait && map.cids().length) return true;
          if (await map.load(this.sidecar, url)) return true;
          if (map.url !== url) return false;
          this.mapRetries++;
        }
        return false;
      };
      void loadMap().then(() => {
        if (map.url !== url || this.session !== url) return;
        this.scheduleFormSaver();
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
    // The page left behind KEEPS its grey nodes until its settle has stored
    // them and they fold into its page node (`onLeft` below). Dropped here,
    // at the moment of leaving, a fast reader lost every page's diff before
    // it was stored or drawn (2026-10-17, PLUGIN_GOAL 130: "persist rendering
    // on grey nodes streamed as diffs a few seconds ago on one page while the
    // same thing happens on successive pages"). It replaces the drop made for
    // B-tree's 401 nodes hanging through a long settle. Planted:
    // `drop-on-leave`, as before.
    if (leaving && this.plant.has("drop-on-leave")) this.onLeaving(leaving);
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
    // Undecided in-page url: drained as the session's until a pushed drain
    // decides (G-216) -- never a fresh tree for a url that may be an alias.
    const here = this.shownUrl();
    const url = here === this.pendingInPage && this.session ? this.session : (this.sessionAliases.get(here) || here);
    // Drained once the DOCUMENT is ready, loading or not: YouTube and IMDb
    // never stop "loading" (streaming requests), and waiting for them to meant
    // 0 and 2 drains in 16 s -- the heavy live pages were barely scanned
    // (G-101, 2026-09-27).
    if (!url || url === "about:blank" || (wv.isLoading() && !this.domReady)) return;
    // An offline view is a local file, not a page: nothing in it is captured.
    if (!/^https?:/.test(url)) return;
    if (url !== this.session && docKey(url) !== docKey(this.session) && url !== this.pendingInPage) {
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
        let url = String(p.url || this.shownUrl() || "");
        if (!url || url === "about:blank") continue;
        // An in-page url change, decided by this drain (see did-navigate-in-page):
        // at least half the session's live chunks removed -> a new page;
        // otherwise the same document under another url.
        url = this.sessionAliases.get(url) || url;
        // Same DOCUMENT (no new one has loaded since the session began) under
        // another url: decided by this drain, whichever of it and the
        // navigation event arrived first.
        if (url !== this.session && this.session && this.docSeq === this.sessionDocSeq
            && docKey(url) !== docKey(this.session) && !this.plant.has("inpage-is-new-page")) {
          const tree = this.forceTrees.get(this.session);
          const live = tree ? tree.held().length : 0;
          const removed = (p.removed || []).length;
          if (this.pendingInPage === url) this.pendingInPage = "";
          // A url rewritten WHILE THE PAGE SCROLLS is the page keeping its
          // place in a list, never a new page: archive.org's list is
          // virtualized and drops off-screen items as it scrolls, so half
          // the live chunks went with every rewrite and three of four were
          // taken for new pages (2026-10-17). Without a scroll, the content
          // decides, as an app's route change requires.
          const scrolling = Date.now() - this.pageScrolledAt < 1500 && !this.plant.has("inpage-ignore-scroll");
          if (scrolling || removed < 0.5 * live || live === 0) {
            this.sessionAliases.set(url, this.session); this.inPageStats.same_doc++;
            url = this.session;
          } else {
            this.inPageStats.new_page++;
            this.sessionDocSeq = -1;                 // let the switch below happen
          }
        }
        if (url !== String(p.url || "")) p.url = url;
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
    // A page STATE -- an error response, a bot check -- is not the page
    // (G-249): it is not streamed, not outlined, not stored, so the url's
    // trie stays what it was and the real page's drains continue its stream
    // when it arrives (G-247: a DDoS-Guard check stored as the url's three
    // lines made the page come back as all new). Planted `store-gates`.
    // A PDF's viewer is not the page: its text arrives through `/pdf`.
    if (this.pdfDoc === this.docSeq && !this.plant.has("no-pdf")) {
      prof.fact(trace, "why", "pdf viewer");
      prof.finish(trace, "nothing_placed");
      return;
    }
    const gate = this.gateOf(payload, title);
    if (gate.why) {
      this.gateStats.drains++;
      if (this.gateStats.lastSeq !== this.docSeq) { this.gateStats.docs++; this.gateStats.lastSeq = this.docSeq; }
      this.gateStats.last = gate.why; this.gateStats.at = Date.now();
      this.say(`page state · ${gate.why} · not stored; the stream resumes on the page itself`);
      this.capturedAt.set(url, performance.now());     // nothing to wait for
      prof.fact(trace, "gated", gate.why);
      prof.finish(trace, "nothing_placed");
      return;
    }
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
      if (!tree) {
        tree = new ForceTree(url); this.forceTrees.set(url, tree);
        // A page that began inside a running document continues its stream
        // (G-216): the document's dictionary and live chunks, adopted.
        const prev = this.docTrees.get(this.docSeq);
        if (prev && !this.plant.has("no-adopt")) { tree.adopt(prev); this.inPageStats.adopted++; }
      }
      this.docTrees.set(this.docSeq, tree);
      if (this.docTrees.size > 8) this.docTrees.delete(this.docTrees.keys().next().value as number);
      const delta = tree.apply(payload);
      this.lastDrainAt = performance.now();
      if (delta) drainIds = delta.added.map((a) => a.id);
      // Placed through the fit NOW, not after the store (PLUGIN_GOAL 48):
      // the drain's new chunks, by their own text, in the delta only.
      if (delta && !this.plantNoTransient) {
        const want = new Set(delta.added.filter((a) => !a.branch && a.parent).map((a) => a.id));
        const items = (payload.chunks || []).map((c: any) => ({
          id: tree!.nodeId(Number(c.id)),
          text: (c.lines || []).map((l: any) => String((l && l[1]) || "")).join("\n"),
        })).filter((it: any) => want.has(it.id) && it.text.trim().length > 8).slice(0, 300);
        if (items.length) {
          const asked = performance.now();
          void this.sidecar.project(url, items).then((got: any) => {
            if (!got || !got.pos) return;
            this.transientStats.asked += items.length;
            this.transientStats.placed += Object.keys(got.pos).length;
            this.transientStats.last_ms = Math.round(performance.now() - asked);
            this.onProjected(url, got);
          });
        }
      }
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
    // Merged at ENQUEUE into the page's last queued job (not a settle, which
    // stays a barrier): the queue holds at most one job per page between
    // settles however fast the page mutates or however long the store is
    // held -- a 195 s checkpoint grew it to 62-135 jobs (archive.org,
    // 2026-10-17). Nothing is dropped: the merge replays the drains in order.
    // Planted `no-enqueue-merge`: a job per drain.
    let into = -1;
    for (let i = this.captureQueue.length - 1; i >= 0; i--) {
      if (this.captureQueue[i].url === url) { into = this.captureQueue[i].settle ? -1 : i; break; }
    }
    // Never merged across a REMOVAL of what the queued job still carries:
    // merged, the two cancel and the store never sees that content -- a
    // tile shown and recycled between two captures (G-216: the page is
    // every chunk it showed). Queued after it instead.
    if (into >= 0 && removesCarried(payload, this.captureQueue[into].payload)) into = -1;
    if (into >= 0 && !this.plant.has("no-enqueue-merge")) {
      const j = this.captureQueue[into];
      this.captureQueue[into] = { ...j, payload: mergePayloads([j.payload, payload]),
                                  drainIds: [...(j.drainIds || []), ...(drainIds || [])],
                                  merged: [...(j.merged || []), trace].filter(Boolean), title: title || j.title };
      this.mergedCaptures++;
      this.enqueueMerged++;
    } else {
      this.captureQueue.push({ url, payload, trace, drainIds, queuedAt: performance.now(),
                               title });
    }
    void this.pumpCaptures();
    // Planted by D-35's check: the old behaviour, the drain loop held
    // across the whole capture.
    if (this.plant.has("serial-capture")) {
      while (this.capturing || this.captureQueue.length) {
        await new Promise((r) => window.setTimeout(r, 50));
      }
    }
  }

  /** Landing map loads that failed and were asked again. */
  mapRetries = 0;

  // ---- offline (`G-59`..`G-62`) ---------------------------------------------

  /** Chromium's net errors that mean "no connection", not "no such page". */
  // Not -102 (CONNECTION_REFUSED): a server that refused is up-network and
  // down itself, and a closed local fixture server put the cell into its
  // offline form for good (2026-10-11). Planted: -102 counts again.
  static NO_CONNECTION = new Set([-106, -105, -109, -118, -21, -137, -130]);
  plantRefusedIsOffline = false;
  /** The url whose offline form the cell is showing, "" when live. */
  offlineFor = "";
  /** Planted: a navigation to a live page leaves the cell offline (only the button ends it). */
  plantStickyOffline = false;
  offlineStats = { saved: 0, save_failed: 0, opened_saved: 0, opened_infilled: 0, opened_traced: 0, nothing: 0, last: null as any };
  private saveOfflineButton: HTMLButtonElement | null = null;
  private offlineSavedThisVisit = new Set<string>();
  private offlineTimer = 0;
  private loadFailedUrl = "";
  private openingOffline = "";

  private plugin(): any { return (this.app as any).plugins.getPlugin("vertiscope-bridge"); }
  private saveOfflineOn(): boolean { return !!this.plugin()?.settings?.saveOffline; }
  private boxesButton: HTMLButtonElement | null = null;
  /** Planted (item 89): turning the boxes off also stops the hover. */
  plantBoxesStopHover = false;
  boxesShown(): boolean { return this.plugin()?.settings?.showBoxes !== false; }
  paintBoxes(): void {
    const on = this.boxesShown();
    if (this.boxesButton) this.boxesButton.setText(on ? "boxes ●" : "boxes ○");
    this.browserWrap?.toggleClass("vertiscope-boxes-off", !on);
    if (this.pipebox) this.pipebox.paused = !on && this.plantBoxesStopHover;
  }
  async toggleBoxes(on?: boolean): Promise<void> {
    const p = this.plugin();
    if (!p) return;
    p.settings.showBoxes = on ?? !this.boxesShown();
    await p.saveSettings();
    this.paintBoxes();
  }
  private paintSaveOffline(): void {
    if (this.saveOfflineButton) this.saveOfflineButton.setText(this.saveOfflineOn() ? "save offline ●" : "save offline ○");
  }
  private async toggleSaveOffline(): Promise<void> {
    const p = this.plugin();
    if (!p) return;
    p.settings.saveOffline = !p.settings.saveOffline;
    await p.saveSettings();
    this.paintSaveOffline();
    if (p.settings.saveOffline) this.scheduleOfflineSave(500);
  }

  /** Once a page has stopped loading and the reader has let it settle. */
  private scheduleOfflineSave(ms = 5000): void {
    window.clearTimeout(this.offlineTimer);
    this.offlineTimer = window.setTimeout(() => { void this.saveOfflinePage(); }, ms);
  }

  /**
   * The page as the cell PRESENTS it (`G-60`): Chromium's MHTML serialisation
   * of the live document -- its scripts already run, every resource inline --
   * and its visible text, for the infill test. Read from the page, never
   * written into it.
   */
  async saveOfflinePage(force = false): Promise<any> {
    const wv = this.webview;
    if (!wv || (!force && !this.saveOfflineOn())) return null;
    const url = wv.getURL();
    if (!/^https?:/.test(url) || this.offlineFor) return null;
    if (!force && this.offlineSavedThisVisit.has(url)) return null;
    // Never Chromium's error page: a failed load saved "no internet" as the
    // page (Axolotl, 744 bytes, 2026-10-11).
    if (this.loadFailedUrl === url) return null;
    this.offlineSavedThisVisit.add(url);
    try {
      const req = (window as any).require;
      const os = req("os"), path = req("path"), fsp = req("fs/promises");
      const dir = path.join(os.tmpdir(), "vertiscope-offline");
      await fsp.mkdir(dir, { recursive: true });
      const file = path.join(dir, "save-" + Date.now() + ".mhtml");
      const wc = req("@electron/remote").webContents.fromId(wv.getWebContentsId());
      await wc.savePage(file, "MHTML");
      const bytes: Buffer = await fsp.readFile(file);
      await fsp.rm(file, { force: true });
      // textContent, not innerText: the saved page holds hidden content too (a
      // collapsed navbox), and the infill test asks what the SAVED page holds.
      const text = String(await wv.executeJavaScript("document.body ? document.body.textContent : ''") || "");
      if (text.trim().length < 200) { this.offlineStats.save_failed++; this.offlineStats.last = { url, skipped: "almost no text" }; return null; }
      const got = await this.sidecar.saveOfflinePage(url, bytes.toString("base64"), text);
      if (got && got.saved) this.offlineStats.saved++; else this.offlineStats.save_failed++;
      this.offlineStats.last = { url, bytes: bytes.length, at: Date.now(), reply: got };
      return got;
    } catch (e) {
      this.offlineStats.save_failed++;
      this.offlineStats.last = { url, error: String(e).slice(0, 200) };
      return null;
    }
  }

  /**
   * The page with no connection (`G-62`): the saved page when it holds what
   * the scan traced, otherwise the page rebuilt from the trace (`G-61`'s
   * infill) -- written to a local file, because Chromium opens MHTML only
   * from one, and because with no network nothing else is reachable.
   */
  async openOffline(url: string): Promise<any> {
    const wv = this.webview;
    if (!wv || !/^https?:/.test(url)) return null;
    // One at a time: a failed navigation reports more than once.
    if (this.openingOffline === url) return null;
    this.openingOffline = url;
    try { return await this.openOfflineOnce(url); } finally { this.openingOffline = ""; }
  }

  private async openOfflineOnce(url: string): Promise<any> {
    const wv = this.webview!;
    const t0 = performance.now();
    const info: any = await this.sidecar.offlineInfo(url);
    if (!info || !info.opens) { this.offlineStats.nothing++; this.say("nothing kept for this page offline"); return info; }
    const data = await this.sidecar.offlineForm(url, info.opens);
    if (!data) { this.offlineStats.nothing++; return info; }
    const req = (window as any).require;
    const os = req("os"), path = req("path"), fsp = req("fs/promises");
    const dir = path.join(os.tmpdir(), "vertiscope-offline");
    await fsp.mkdir(dir, { recursive: true });
    const file = path.join(dir, "open-" + Date.now() + (info.opens === "traced" ? ".html" : ".mhtml"));
    await fsp.writeFile(file, Buffer.from(data));
    this.offlineFor = url;
    if (info.opens === "saved") this.offlineStats.opened_saved++;
    else if (info.opens === "infilled") this.offlineStats.opened_infilled++;
    else this.offlineStats.opened_traced++;
    wv.loadURL("file:///" + file.replace(/\\/g, "/"));
    this.say(info.opens === "saved" ? "offline · the page as it was saved"
           : info.opens === "infilled" ? "offline · the page as it was saved, infilled from the scan trace"
                                    : `offline · rebuilt from the scan trace (${info.chunks} chunks)`);
    this.offlineStats.last = { opened: url, form: info.opens, ms: Math.round(performance.now() - t0) };
    return info;
  }
  /** Times the sidecar asked the sensor to send everything again. */
  resyncs = 0;

  /**
   * The sidecar restarted under this page and cannot decode the sensor's
   * next delta (its dictionary went with the old process): the sensor sends
   * its whole dictionary and every chunk on the next drain (`resync` in
   * sensor.js). A drain is asked for at once, so the store is whole again
   * without the reader reloading anything.
   */
  private async resyncSensor(): Promise<void> {
    const wv = this.webview;
    if (!wv) return;
    try {
      await wv.executeJavaScript(`(function(){var h=window[${JSON.stringify(HANDLE)}];return h&&h.resync?h.resync():0;})()`);
      this.resyncs++;
      window.setTimeout(() => { if (!this.draining) void this.tick(); else this.drainAgain = true; }, 50);
    } catch { /* the page went away; its next sensor starts whole */ }
  }

  /** Drains that rode along in another drain's capture (merged ingest). */
  mergedCaptures = 0;

  /** Captures waiting to be sent, in drain order per url. */
  private captureQueue: CaptureJob[] = [];
  /** A capture (or settle) is in flight. */
  capturing = false;
  /** Queued captures, for the harness and the corner box. */
  get captureBacklog(): number { return this.captureQueue.length; }
  /** Drains folded into an already-queued job of their page (G-217). */
  enqueueMerged = 0;
  /** Captures re-queued after no reply or a retryable refusal. */
  captureRetries = 0;
  /** The view closed: its pump sends nothing more but settles. */
  private closed = false;
  /** Drains a closed view held unsent (reported, not retried). */
  abandonedOnClose = 0;
  /** Refusals ("dictionary incomplete") for a page no longer shown: counted,
   *  not answered with a rescan of the page that IS shown. */
  refusedLeft = 0;

  /**
   * The sidecar refused a capture of `url` -- its session does not hold the
   * dictionary the payload extends. Only the sensor of the page SHOWN can
   * resend its dictionary, so only a refusal for that document resyncs it.
   * A late drain of a page already left (its session settled and closed)
   * resynced whatever page was on screen instead: a full drain of every
   * chunk, captured again, for each such refusal -- 2026-10-18, after
   * archive.org visits the sidecar logged a refusal every few seconds and
   * the shown page rescanned each time (PLUGIN_GOAL 150/152). Planted
   * `resync-any-refusal`: as before.
   */
  private onRefused(url: string): void {
    const doc = (u: string) => this.sessionAliases.get(u) || u;
    if (this.plant.has("resync-any-refusal") || doc(url) === this.currentPage()) { void this.resyncSensor(); return; }
    this.refusedLeft++;
  }

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
      while (this.captureQueue.length && !(this.closed && !this.captureQueue[0].settle)) {
        // OLDEST first (2026-10-17, PLUGIN_GOAL 155: "scans are slow to
        // register older chunks. Perhaps priority on the oldest pushed diff
        // updates"): the current page went first, and a page scrolled past or
        // left waited behind every drain of the page on screen. A page's later
        // drains still ride with its oldest (merged below), so the current
        // page is one job, not one per drain. Planted `current-page-first`.
        let k = this.plant.has("current-page-first") ? this.captureQueue.findIndex((c) => c.url === this.session) : 0;
        if (k < 0) k = 0;
        // A LEFT page's settle waits behind the page on screen (2026-10-18):
        // oldest-first put bandcamp's settle -- its complete trie, 5-12 s on
        // a store rewriting ~200 moved addresses -- ahead of the next page's
        // first capture, and that page's chunks sat grey 30-75 s ("a lot of
        // diff scans not yet at least projected after vectorization"). The
        // settle is the left page's bookkeeping: nothing drawn waits on it.
        // Its DRAINS keep their age order. Planted `settle-in-age-order`.
        if (this.captureQueue[k] && this.captureQueue[k].settle && this.captureQueue[k].url !== this.session
            && !this.plant.has("settle-in-age-order")) {
          const cur = this.captureQueue.findIndex((c) => !c.settle && c.url === this.session);
          if (cur >= 0) k = cur;
        }
        let job = this.captureQueue.splice(k, 1)[0];
        // Every later drain of the same page queued meanwhile rides along --
        // up to a settle of that page, which stays a barrier.
        if (!job.settle && !this.plant.has("serial-ingest")) {
          const ride: CaptureJob[] = [];
          // No cap: however long the store stalls (a checkpoint held it 195 s,
          // 2026-10-17), a page's queued drains merge into ONE capture of its
          // latest state, so the backlog is a job per page, never per drain.
          // Planted `ride-cap-40`: the old cap.
          const cap = this.plant.has("ride-cap-40") ? 40 : Infinity;
          for (let i = k; i < this.captureQueue.length && ride.length < cap; ) {
            const c = this.captureQueue[i];
            if (c.url !== job.url) { i++; continue; }
            if (c.settle) break;
            if (removesCarried(c.payload, mergePayloads([job, ...ride].map((j) => j.payload)))) break;
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
          try {
            const settled = await this.sidecar.capture(job.url, { settle: true });
            // The settle's diff: what the page's complete trie dropped from
            // the store that the per-drain deltas never retired.
            this.noteDiff(settled && !settled.error ? settled.diff : null);
          } catch { /* reported by the next */ }
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

  /**
   * The gate verdict for the current document (G-249). Its status and title
   * every drain; its LINES only on its first drain, which is the whole fold
   * -- a later drain is a delta, and a few lines of one say nothing about
   * the page. A document once gated stays gated.
   */
  private gateOf(payload: any, title: string): GateVerdict {
    if (this.plant.has("store-gates")) return { why: "", kind: "" };
    if (this.gate.seq === this.docSeq && this.gate.v.why) return this.gate.v;
    const status = this.docStatus.seq === this.docSeq ? this.docStatus.status : 0;
    const lines: string[] = [];
    if (this.gate.seq !== this.docSeq && payload && payload.chunks) {
      outer: for (const c of payload.chunks) for (const l of (c.lines || [])) {
        lines.push(String((l && l[1]) || ""));
        if (lines.length > GATE_SMALL_LINES) break outer;
      }
    }
    const v = pageGate(status, title, lines);
    this.gate = { seq: this.docSeq, v };
    return v;
  }

  /**
   * A PDF the reader reached is downloaded and chunked like a page (G-248,
   * PLUGIN_GOAL 177: "there isnt a download process for pdfs and subsequent
   * chunking for us and there really should be"). The bytes are read BY THE
   * PAGE from its own document -- the browser's own copy, usually its cache --
   * so nothing new is asked of the host; the sidecar keeps the file and lays
   * its text out as pages, headings and paragraphs (`vertiscope/pdf.py`), which
   * the recursive chunker, the vectoriser and the graph take like any page.
   */
  private async maybePdf(): Promise<void> {
    const wv: any = this.webview;
    if (!wv || this.plant.has("no-pdf")) return;
    const seq = this.docSeq;
    let kind = "";
    try { kind = String(await wv.executeJavaScript("document.contentType") || ""); } catch { return; }
    if (kind !== "application/pdf" || this.pdfDoc === seq) return;
    this.pdfDoc = seq;
    const url = String(wv.getURL());
    this.pdfStats.seen++;
    this.say(`pdf · reading ${url.split("/").pop()}`);
    const t0 = performance.now();
    let b64 = "";
    try {
      b64 = String(await wv.executeJavaScript(`fetch(location.href).then((r) => r.arrayBuffer()).then((b) => {
        if (b.byteLength > 80 * 1024 * 1024) return "";
        const u = new Uint8Array(b); let s = "";
        for (let i = 0; i < u.length; i += 0x8000) s += String.fromCharCode.apply(null, u.subarray(i, i + 0x8000));
        return btoa(s); })`) || "");
    } catch (e) { this.pdfStats.error = String(e).slice(0, 120); }
    this.pdfStats.read_ms = Math.round(performance.now() - t0);
    this.pdfStats.bytes = Math.round(b64.length * 3 / 4);
    if (!b64 || this.docSeq !== seq) { if (!b64) this.say("pdf · could not read the document"); return; }
    const ts = performance.now();
    const got: any = await this.sidecar.pdf(url, b64);
    this.pdfStats.store_ms = Math.round(performance.now() - ts);
    this.pdfStats.ms = Math.round(performance.now() - t0);
    if (!got || got.error) { this.pdfStats.error = String(got?.error || "no reply"); this.say(`pdf · ${this.pdfStats.error}`); return; }
    this.pdfStats.sent++; this.pdfStats.chunks += Number(got.chunks || 0); this.pdfStats.pages += Number(got.pages || 0);
    this.pdfStats.last = String(got.url || url); this.pdfStats.error = "";
    this.say(`pdf · ${got.pages} pages · ${got.chunks} chunks · kept as ${got.kept}`);
    // Drawn as the page's chunks are: the placement queue waits for vectors.
    if (this.docSeq === seq) void this.placeWholePage(String(got.url || url));
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
        if (reply && (reply as any).resync && !this.plant.has("no-resync")) { this.onRefused(url); return; }
        // No reply (the sidecar restarting, busy, down) or a refusal asking
        // for a retry: the capture goes BACK to the front of the queue, never
        // dropped (2026-10-17: "persist chunk streams no matter how fast") --
        // a failed capture was simply returned from, and its drains lost.
        // Kept trying for up to 15 minutes, backing off to 5 s.
        const unreachable = !reply || !!(reply as any).unreachable;
        if ((unreachable || (reply as any).retry) && !this.plant.has("drop-failed-capture") && !this.closed) {
          job.attempts = (job.attempts || 0) + 1;
          // While the sidecar does not answer at all (down, restarting, its
          // store being rebuilt) the stream waits however long that takes;
          // only a sidecar that answers and keeps refusing gets 15 minutes.
          if (unreachable || performance.now() - (job.queuedAt || performance.now()) < 15 * 60 * 1000) {
            this.captureRetries++;
            await new Promise((r) => window.setTimeout(r, Math.min(5000, 400 * job.attempts!)));
            this.captureQueue.unshift(job);
            return;
          }
        }
        this.say(`capture: ${reply ? reply.error : "no reply"}`);
        return;
      }
      // The chunks this drain rewrote, and the elements they draw.
      if (this.pipebox && this.pipebox.map.url === url) {
        this.pipebox.map.patch((reply as any).map_delta);
      }
      // The ONE diff of this capture (retired / renamed / known), applied to
      // the chunk map and the pins here and handed to every graph view --
      // before the placed nodes below are absorbed, so a renamed chunk's new
      // node can start where the old one stood.
      this.noteDiff(reply.diff);
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
        this.formsDirty(cids);
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
        if (reply && (reply as any).resync && !this.plant.has("no-resync")) { this.onRefused(url); return; }
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
    this.noteDiff(done.diff);
    this.say(`scanned · ${done.addresses} addresses · ${done.chunks} chunks ` +
             `· ${total} rewrites over ${passes + 1} passes ` +
             `· ${(elapsedMs / 1000).toFixed(1)}s` +
             (this.lastScan.settled ? " · settled" : " · capped"));
  }

  private say(text: string): void {
    this.status.setText(text);
  }
}
