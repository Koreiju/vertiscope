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

import { PipelineBox } from "./pipelinebox";
import { profiler } from "./profile";
import { Component, ItemView, MarkdownRenderer, WorkspaceLeaf } from "obsidian";

import { LayoutNode } from "./graph";
import { Sidecar } from "./sidecar";
import { SearchHit } from "./types";

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

/** Which face of the panel is showing. */
type Face = "browser" | "markdown";

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
  private face: Face = "browser";
  private address!: HTMLInputElement;
  private status!: HTMLElement;
  private browserWrap!: HTMLElement;
  private markdownWrap!: HTMLElement;
  private toggle!: HTMLElement;

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
    this.toggle = bar.createEl("button", { text: "markdown" });

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

    this.browserWrap = root.createDiv({ cls: "domvec-browser-page" });
    this.overlay = this.browserWrap.createDiv({ cls: "domvec-overlay" });
    this.results = this.overlay.createDiv({ cls: "domvec-overlay-list" });
    this.overlay.hide();
    this.markdownWrap = root.createDiv({ cls: "domvec-browser-md" });
    this.markdownWrap.hide();
    this.markdownWrap.createDiv({ cls: "domvec-browser-empty" }).setText(
      "Right-click a chunk in the browser to bring its full markdown here.");

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
    this.pipebox = new PipelineBox(this.browserWrap, this.sidecar,
                                   () => this.webview,
                                   (cid, url) => this.onHover(cid, url));

    view.addEventListener("did-start-loading", () => this.say("loading…"));
    view.addEventListener("did-stop-loading", () => {
      this.address.value = view.getURL();
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
      if (e && e.isMainFrame) {
        this.address.value = view.getURL();
        void this.pageChanged(view.getURL());
      }
    });
    // Right-click ports the chunk's full markdown to the other face
    // (`G-39`). The event is the WEBVIEW's, raised in the host -- nothing is
    // listening inside the page, and nothing is written into it. The one
    // read it does take is `elementFromPoint` at the cursor, on demand.
    view.addEventListener("context-menu", (e: any) => {
      const p = e && e.params;
      if (!p) return;
      void this.portMarkdown(Number(p.x) || 0, Number(p.y) || 0);
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
    this.toggle.onclick = () => this.show(
      this.face === "browser" ? "markdown" : "browser");
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

  /** Show one face; the other keeps its state rather than being rebuilt. */
  private show(face: Face): void {
    this.face = face;
    const browsing = face === "browser";
    this.browserWrap.toggle(browsing);
    this.markdownWrap.toggle(!browsing);
    this.toggle.setText(browsing ? "markdown" : "browser");
  }

  /** Navigate. Bare hosts get https, because a reader types `arxiv.org`. */
  go(where: string): void {
    if (!this.webview || !where.trim()) return;
    const url = /^[a-z]+:/i.test(where) ? where : `https://${where}`;
    this.address.value = url;
    this.webview.loadURL(url);
    this.show("browser");
  }

  /** Restrict the ranking to one shadow DOM, or release it (`G-70`). */
  //: Told the plugin, which tells the projector (`G-38`). Brokered, like
  //  every other cross-pane signal here: neither pane may require the other.
  onHover: (cid: string, url: string) => void = () => {};
  /** The pipeline overlay; see `pipelinebox.ts`. */
  pipebox: PipelineBox | null = null;

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
  async reveal(url: string, xpath = ""): Promise<void> {
    if (!url) return;
    await this.goToHit({ cid: "", url, xpath } as SearchHit);
  }

  private async goToHit(hit: SearchHit): Promise<void> {
    const wv = this.webview;
    if (!wv) return;
    if (wv.getURL() !== hit.url) {
      this.go(hit.url);
      for (let i = 0; i < 40; i++) {
        await new Promise((r) => setTimeout(r, 400));
        if (!wv.isLoading()) break;
      }
    }
    if (!hit.xpath) return;
    try {
      const found = await wv.executeJavaScript(`(function () {
        var r = document.evaluate(${JSON.stringify(hit.xpath)}, document,
          null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);
        var n = r.singleNodeValue;
        if (!n) return false;
        if (n.nodeType === 3) n = n.parentElement;
        if (!n) return false;
        n.scrollIntoView({block: "center"});
        return true;
      })()`);
      this.say(found ? `at ${hit.xpath}`
                     : `the page no longer has ${hit.xpath}`);
    } catch (e) {
      this.say(`could not reach it: ${String(e).slice(0, 80)}`);
    }
  }

  /**
   * What is under the cursor -> its chunk -> the markdown face (`G-39`).
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

    const got = await this.sidecar.resolve(url, xpath);
    if (!got || !got.lines) {
      this.say(`no chunk draws ${xpath.slice(-48)}`);
      return;
    }
    let markdown = (got.lines as { text: string }[])
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
          // Absolute, protocol-relative and in-page anchors are left alone.
          if (/^[a-z][a-z0-9+.-]*:/i.test(target)
              || target.startsWith("//") || target.startsWith("#")) {
            return whole;
          }
          try {
            return head + new URL(target, base).href;
          } catch {
            return whole;
          }
        });
    }
    this.markdownWrap.empty();
    const head = this.markdownWrap.createDiv({ cls: "domvec-browser-mdhead" });
    head.setText(got.ancestors_walked
      ? `${got.matched_xpath} · ${got.ancestors_walked} above what you clicked`
      : String(got.matched_xpath || xpath));
    const body = this.markdownWrap.createDiv({ cls: "domvec-browser-mdbody" });
    // The NATIVE renderer, not a code block: `G-37` asks for the same
    // content as an Obsidian markdown panel, rendering the full markdown.
    await MarkdownRenderer.render(this.app, markdown, body, "",
                                  this as unknown as Component);
    // The projector rings the same chunk (`G-38`, as far as it goes). One
    // gesture, both surfaces: the reader points once and the map says where
    // that is.
    this.onHover(String(got.cid || ""), String(got.url || url || ""));
    this.show("markdown");
    this.say(`${got.cid} · ${markdown.split("\n").length} lines`);
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
    if (!url || url === "about:blank") { this.session = ""; return; }
    if (url === this.session) return;
    const leaving = this.session;
    this.session = url;
    if (leaving) {
      await this.sidecar.capture(leaving, { settle: true });
    }
    if (this.live) this.say(`live · ${url}`);
    void this.placeWholePage(url);
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
      for (const [traceId, list] of byTrace) this.onChunks(list, edges, traceId);
    } finally {
      this.placing = false;
    }
  }

  private async tick(): Promise<void> {
    if (!this.live || this.draining || !this.webview) return;
    const wv = this.webview;
    const url = wv.getURL();
    if (!url || url === "about:blank" || wv.isLoading()) return;
    if (url !== this.session) {
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
      const payload = await wv.executeJavaScript(`(function () {
        if (!window[${JSON.stringify(HANDLE)}]) {
          var h = (${BrowserView.sensorSource})(
            {budget: 0, debounce: 80, variants: {}, known: []});
          Object.defineProperty(window, ${JSON.stringify(HANDLE)},
            {value: h, enumerable: false, configurable: false});
        }
        return window[${JSON.stringify(HANDLE)}].drain();
      })()`);

      // Nothing changed. Not posted: an empty delta costs a round trip, a
      // decode and a store write to say "no", and a reader idling on a static
      // page would pay it once a second forever.
      prof.stage(trace, "drain", performance.now() - drainStart);
      // The guest's own fold time for this drain, from its own clock. It is
      // INSIDE `drain`, and the difference is the executeJavaScript bridge.
      const repair = payload && payload.stats ? payload.stats.repairMs : undefined;
      if (typeof repair === "number") {
        prof.stage(trace, "fold", repair - (this.lastRepairMs ?? 0));
        this.lastRepairMs = repair;
      }
      if (!payload || !(payload.chunks || []).length) {
        prof.fact(trace, "why", "empty drain");
        prof.finish(trace, "nothing_placed");
        return;
      }
      prof.fact(trace, "chunks_in_drain", (payload.chunks || []).length);

      // One round trip: fold, store, and place, because per drain they are
      // one question. The second call carried a list of cids the server had
      // just computed and was handing straight back.
      const captureStart = performance.now();
      const reply = await this.sidecar.capture(
        url, { payload, place: true, trace: trace.id, title: wv.getTitle() || "" });
      const captureMs = performance.now() - captureStart;
      prof.stage(trace, "capture", captureMs);
      if (reply) prof.sidecar(trace, reply.phases, reply.ms, captureMs);
      if (!reply || reply.error) {
        this.say(`capture: ${reply ? reply.error : "no reply"}`);
        return;
      }
      const cids = (reply.dirty_cids || []) as string[];
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
        this.onChunks(nodes,
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
    } catch (e) {
      // The realm goes away on navigation and the handle with it. That is
      // ordinary, not an error: the next tick reboots into the new document.
      this.say(`live · ${String(e).slice(0, 80)}`);
    } finally {
      this.draining = false;
    }
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
