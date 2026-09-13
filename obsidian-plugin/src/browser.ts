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

import { ItemView, WorkspaceLeaf } from "obsidian";

import { LayoutNode } from "./graph";
import { Sidecar } from "./sidecar";

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

/** Which face of the panel is showing. */
type Face = "browser" | "markdown";

export class BrowserView extends ItemView {
  /** Fetched once per app run and shared: it is one file on disk and it does
   *  not change under a running plugin. */
  private static sensorSource = "";
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
  /** The url the current capture session belongs to. A navigation ends one
   *  session and begins another, and the old one has to be settled first or
   *  its last delta never becomes a complete write. */
  private session = "";
  private liveButton!: HTMLElement;

  constructor(leaf: WorkspaceLeaf, private sidecar: Sidecar,
              private onChunks: (nodes: LayoutNode[]) => void = () => {}) {
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

    this.browserWrap = root.createDiv({ cls: "domvec-browser-page" });
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
    this.liveButton.onclick = () => this.setLive(!this.live);

    // One timer for the life of the pane, registered so Obsidian stops it
    // when the view closes. A timer per navigation would leak one per page a
    // reader visits, and they would all still be draining.
    this.registerInterval(window.setInterval(() => { void this.tick(); },
                                             LIVE_MS));

    this.say("ready");
  }

  async onClose(): Promise<void> {
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
  private async tick(): Promise<void> {
    if (!this.live || this.draining || !this.webview) return;
    const wv = this.webview;
    const url = wv.getURL();
    if (!url || url === "about:blank" || wv.isLoading()) return;
    if (url !== this.session) { await this.pageChanged(url); return; }

    this.draining = true;
    try {
      if (!BrowserView.sensorSource) {
        const got = await this.sidecar.sensor();
        if (!got || !got.source) return;
        BrowserView.sensorSource = got.source;
      }
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
      if (!payload || !(payload.chunks || []).length) return;

      const reply = await this.sidecar.capture(url, { payload });
      if (!reply || reply.error) {
        this.say(`capture: ${reply ? reply.error : "no reply"}`);
        return;
      }
      const cids = (reply.dirty_cids || []) as string[];
      if (!cids.length) {
        this.say(`live · ${reply.addresses} addresses`);
        return;
      }
      const placed = await this.sidecar.place(cids);
      const nodes = (placed && (placed.nodes as LayoutNode[])) || [];
      if (nodes.length) this.onChunks(nodes);
      const waiting = placed && placed.unplaced ? placed.unplaced.length : 0;
      this.say(`live · ${cids.length} chunks · ${nodes.length} placed` +
               (waiting ? ` · ${waiting} awaiting a vector` : "") +
               (placed && placed.stale ? " · fit is stale, refit" : ""));
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
  async scan(): Promise<void> {
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
    let total = 0, addresses = 0;
    for (let pass = 0; pass <= SCROLLS; pass++) {
      if (pass) {
        await wv.executeJavaScript(
          "window.scrollBy(0, window.innerHeight * 0.9); true");
        await new Promise((r) => setTimeout(r, PAUSE_MS));
      }
      let payload: any = null;
      try {
        payload = await wv.executeJavaScript(
          `window[${JSON.stringify(HANDLE)}].drain()`);
      } catch (e) {
        this.say(`drain ${pass} failed: ${String(e).slice(0, 100)}`);
        return;
      }
      const reply = await this.sidecar.capture(url, { payload });
      if (!reply || reply.error) {
        this.say(`capture failed: ${reply ? reply.error : "no reply"}`);
        return;
      }
      total += reply.dirty || 0;
      addresses = Math.max(addresses, reply.addresses || 0);
      this.say(`pass ${pass}: ${reply.addresses} addresses, ` +
               `${reply.dirty} chunks rewritten, ${reply.ms} ms`);
    }

    // One complete write from the settled trie. The per-drain writes are
    // deltas and never retire a chunk that re-partitioning replaced.
    const done = await this.sidecar.capture(url, {
      settle: true, title: wv.getTitle() || "" });
    if (!done || done.error) {
      this.say(`settle failed: ${done ? done.error : "no reply"}`);
      return;
    }
    this.say(`scanned · ${done.addresses} addresses · ${done.chunks} chunks ` +
             `· ${total} rewrites over ${SCROLLS + 1} passes`);
  }

  private say(text: string): void {
    this.status.setText(text);
  }
}
