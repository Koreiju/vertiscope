/**
 * vertiscope bridge -- distilled web chunks as live surfaces inside notes.
 *
 * The design turns on one property of Obsidian: a code-block processor is
 * handed a real HTMLElement inside a real note, and the DOM a plugin builds
 * there is NOT put through the sanitiser that strips scripts and handlers
 * from raw HTML in markdown. So a note can be an ordinary `.md` file -- which
 * is what the graph view reads -- and still carry a surface you can click.
 *
 * That is why the note is split the way it is. The prose above the fence
 * holds the wikilinks, because Obsidian parses links only there; the fence
 * holds nothing but a cid, because everything else is looked up from the
 * store and a second copy in the note would drift from it.
 *
 * The native graph view has no plugin API -- the one community plugin that
 * extends it patches undocumented internals and warns that settings can be
 * lost. So this plugin does not touch it. Real wikilinks in real notes make
 * the native graph work for free.
 */

import { UBLOCK_SHIM } from "./ublockshim";
import { profiler } from "./profile";
import {
  App,
  MarkdownPostProcessorContext,
  MarkdownView,
  Notice,
  Plugin,
  TFile,
  WorkspaceLeaf,
  PluginSettingTab,
  Setting,
} from "obsidian";

import { installHarness } from "./harness";
import { TERMINAL_VIEW, TerminalView } from "./terminal";
import {
  RunHost, RunRequest, livePreviewRunButtons, readingViewRunButtons,
} from "./runbutton";
import { cellSource, findFences } from "./fences";
import { ChunkSpan, chunkGutter, setChunkSpans } from "./chunkgutter";
import { hashCell, renderOutput, withOutput } from "./outputs";
import { BROWSER_VIEW, BrowserView } from "./browser";
import type { ActRecord } from "./panelact";
import { GRAPH_VIEW, GraphView } from "./graph";
import { RetrievalSuggest } from "./retrieval";
import { GestureHost, linkGesture } from "./linkgesture";
import { Sidecar } from "./sidecar";
import { ChunkSurface, SurfaceHost } from "./surface";
import { ChunkPayload, DEFAULTS, VertiscopeSettings, EnactResult, KernelReply }
  from "./types";
import { VaultLinks } from "./vaultlinks";
import { PANEL_VIEW, PanelView } from "./panelview";

export default class VertiscopePlugin extends Plugin implements SurfaceHost, RunHost {
  settings: VertiscopeSettings = DEFAULTS;

  /**
   * **uBlock Origin in the browser cell** (G-201, 2026-10-17: "please add
   * uBlock origin to our browser immediately"). The official 1.75.0 chromium
   * build, unpacked under this plugin's `extensions/`, loaded into the
   * browser cell's OWN session (`persist:vertiscope`) -- never Obsidian's -- once
   * per app run, without file access. Electron implements only part of the
   * extension API, so what it actually blocks is measured, not assumed
   * (`window.__vertiscopeAdblock`). Off with the `adblock` setting.
   */
  async loadAdblock(): Promise<void> {
    const st: any = ((window as any).__vertiscopeAdblock = { wanted: !!this.settings.adblock, loaded: false });
    if (!this.settings.adblock) return;
    try {
      const remote = (require("electron") as any).remote;
      const ses = remote?.session?.fromPartition("persist:vertiscope");
      const exts = ses?.extensions || ses;
      if (!exts?.loadExtension) { st.error = "this Electron has no session.loadExtension"; return; }
      const have = (exts.getAllExtensions?.() || []).find((e: any) => /uBlock/i.test(e.name || ""));
      if (have) { Object.assign(st, { loaded: true, name: have.name, version: have.version, already: true }); return; }
      const base = (this.app.vault.adapter as any).getBasePath?.() || "";
      const dir = `${base}/${this.manifest.dir}/extensions/ublock0-1.75.0/uBlock0.chromium`;
      // The compatibility shim, first in the background page (`ublockshim.ts`):
      // written whenever missing, so a fresh unpack works too.
      try {
        const fs = require("fs") as typeof import("fs");
        const shimPath = `${dir}/js/vertiscope-electron-shim.js`;
        if (!fs.existsSync(shimPath) || fs.readFileSync(shimPath, "utf8") !== UBLOCK_SHIM) fs.writeFileSync(shimPath, UBLOCK_SHIM, "utf8");
        const bgPath = `${dir}/background.html`;
        const bg = fs.readFileSync(bgPath, "utf8");
        if (!bg.includes("vertiscope-electron-shim.js")) {
          fs.writeFileSync(bgPath, bg.replace("<body>", '<body>' + String.fromCharCode(10) + '<script src="js/vertiscope-electron-shim.js"></script>'), "utf8");
        }
        st.shim = true;
      } catch (e) { st.shim_error = String(e).slice(0, 200); }
      const ext = await exts.loadExtension(dir, { allowFileAccess: false });
      Object.assign(st, { loaded: true, name: ext?.name, version: ext?.version, id: ext?.id });
    } catch (e) {
      st.error = String(e).slice(0, 300);
    }
  }
  sidecar!: Sidecar;
  links!: VaultLinks;
  /** The `[]()` gesture's host: its counters and its planted arm (`R-1`..`R-4`). */
  gesture!: GestureHost;
  /**
   * What the SERVER last said it allows. Refreshed on load and by the
   * connection check; never assumed, and never set from a plugin setting.
   */
  private serverEnact = false;
  /** Every mounted surface, so the toggle command can reach them all. */
  private surfaces = new Set<ChunkSurface>();

  async onload() {

    // **The harness: one wrapper over the UI layer (`D-24`).**
    //
    // `__vertiscope.ui()` is the interface as a data structure in SCREEN
    // pixels; `__vertiscope.trace` captures every sidecar call at the fetch
    // boundary; `__vertiscope.act()` runs a gesture through the application's
    // own paths and returns the UI before, the UI after, and the backend
    // work it caused. The checks used to read JavaScript properties, which
    // is how three of them passed while the pane showed a clump.
    installHarness(this.app, () => this.settings.sidecar);

    // When the READER last used THIS app (2026-09-28: "Idle's never going to
    // finish" -- the machine-wide idle clock counted every keystroke in every
    // window, so an in-app run waited an hour for a reader typing elsewhere).
    // Keys, clicks, wheel and pointer in the Obsidian window; pointer moves in
    // the browser cell arrive as the sensor's pushed hovers (browser.ts).
    // Each stamp says what made it (`__vertiscopeReaderBy`): the idle turn
    // "stalls out after some time" (2026-10-17) when something that is not
    // the reader keeps stamping, and the tally is how that is found.
    const by: Record<string, number> = ((window as any).__vertiscopeReaderBy = (window as any).__vertiscopeReaderBy || {});
    for (const ev of ["keydown", "pointerdown", "wheel", "pointermove"] as const) {
      this.registerDomEvent(window, ev, () => { (window as any).__vertiscopeReaderAt = Date.now(); by[ev] = (by[ev] || 0) + 1; },
                            { capture: true, passive: true } as any);
    }

    this.settings = Object.assign({}, DEFAULTS, await this.loadData());
    void this.loadAdblock();
    // A test workspace outlives a plugin reload (`session.ts`): put it back,
    // and badge it in the status bar for as long as it lasts.
    const sw: any = (window as any).__vertiscope?.session?.switcher;
    if (sw) {
      sw.badge = this.addStatusBarItem();
      await sw.resume();
      sw.paint();
    }
    this.sidecar = new Sidecar(() => this.settings.sidecar);
    // Once a minute while the reader has been idle five minutes: the sidecar
    // may compact its store now, the only moment nobody waits on it (2026-10-18:
    // 1.6 -> 8.8 GB uncompacted, captures 3-10 s -> 15-26 s). Never while the
    // reader is here. Planted `__vertiscopePlantNoMaintenance`.
    this.registerInterval(window.setInterval(() => {
      const idle = Date.now() - ((window as any).__vertiscopeReaderAt || 0);
      if (idle >= 300000 && !(globalThis as any).__vertiscopePlantNoMaintenance) void this.sidecar.maintenance(idle);
    }, 60000));
    this.links = new VaultLinks(this.app, this.sidecar);
    const links = this.links;
    this.gesture = {
      sidecar: this.sidecar,
      stats: { opened: 0, pages: 0, infilled: 0, last: null },
      plantOverlay: false,
      onOpen: () => { void links.refresh(); },
      destination: (hit) => {
        // A vault note links by its path in the vault; a page with an
        // exported note links to that note (a markdown panel link, as the
        // verbatim asks); anything else by its own address.
        if (hit.url.startsWith("vault://")) return encodeURI(decodeURIComponent(hit.url.replace(/^vault:\/\/[^/]*\//, "")));
        const note = links.noteFor(hit.url);
        return note ? encodeURI(note + ".md") : hit.url;
      },
    };

    // A load that never finished (2026-10-12: an enable that hung) leaves its
    // registrations behind with no unload to remove them; the next onload
    // then threw at the first one and registered NOTHING -- every reload
    // after ran the stale views' old code. Its view types are cleared first;
    // a code-block processor cannot be cleared from here, so a stale one is
    // left handling fences rather than aborting this load.
    const reg: any = (this.app as any).viewRegistry;
    for (const t of [GRAPH_VIEW, BROWSER_VIEW, PANEL_VIEW, TERMINAL_VIEW]) {
      try { if (reg?.viewByType?.[t]) reg.unregisterView(t); } catch { /* not ours to fail on */ }
    }
    try {
      this.registerMarkdownCodeBlockProcessor(
        "vertiscope",
        (source, el, ctx) => this.renderChunk(source, el, ctx),
      );
    } catch (e) {
      console.warn("vertiscope: a stale `vertiscope` fence processor is still registered; keeping it", e);
    }

    this.registerEditorSuggest(
      new RetrievalSuggest(this.app, this.sidecar, () => this.settings,
                           this.links),
    );

    // A run button per fence, in BOTH rendering paths. They are separate
    // renderers in Obsidian and neither covers the other: reading view builds
    // DOM a post-processor can append to, live preview is CodeMirror and needs
    // a widget decoration. See `runbutton.ts`.
    // Where the chunker cut, in the editor's gutter (`P-N8`).
    // The `[]()` gesture (`R-1`..`R-4`): results in a block under the line,
    // a click infills the link between the parentheses.
    this.registerEditorExtension(linkGesture(this.gesture));
    this.registerEditorExtension(chunkGutter());
    this.registerEvent(this.app.workspace.on("active-leaf-change",
                                             () => this.refreshChunkMarks()));
    this.registerEvent(this.app.workspace.on("editor-change",
                                             () => this.scheduleChunkMarks()));

    // A note's kernel is keyed by its PATH, so deleting or renaming the note
    // leaves a running interpreter nothing can reach -- it would sit until the
    // LRU evicted it. The same leak the terminal had until a closed pane began
    // releasing its shell; fixed the same way, at the moment the key stops
    // being valid.
    this.registerEvent(this.app.vault.on("delete", (f) => {
      if (f.path.endsWith(".md")) void this.sidecar.restartKernel(f.path);
    }));
    this.registerEvent(this.app.vault.on("rename", (f, oldPath) => {
      // The OLD path, not the new one: the kernel is filed under where the note
      // used to be, and the note under its new name has no kernel yet.
      if (oldPath.endsWith(".md")) void this.sidecar.restartKernel(oldPath);
    }));

    this.registerMarkdownPostProcessor(readingViewRunButtons(this));
    this.registerEditorExtension(
      livePreviewRunButtons(this, () => this.app.workspace.getActiveFile()?.path ?? ""),
    );

    this.addCommand({
      id: "vertiscope-session-empty",
      name: "Start an empty test workspace",
      callback: () => { void (window as any).__vertiscope?.session?.empty(); },
    });
    this.addCommand({
      id: "vertiscope-session-restart",
      name: "Restart the test workspace's sidecar",
      callback: () => { void (window as any).__vertiscope?.session?.restart(); },
    });
    this.addCommand({
      id: "vertiscope-session-reader",
      name: "Return to my workspace",
      callback: () => { void (window as any).__vertiscope?.session?.reader(); },
    });
    this.addCommand({
      id: "vertiscope-toggle-surface",
      name: "Toggle distilled markdown / interactive surface",
      // No default hotkey: Obsidian asks plugins not to claim one, and a
      // conflict is silent -- the command simply stops firing.
      callback: () => this.surfaces.forEach((s) => s.toggle()),
    });

    this.addCommand({
      id: "vertiscope-toggle-media",
      name: "Toggle loading remote media",
      callback: async () => {
        this.settings.loadRemoteMedia = !this.settings.loadRemoteMedia;
        await this.saveSettings();
        this.surfaces.forEach((s) => s.toggle());
        this.surfaces.forEach((s) => s.toggle());   // redraw, same mode
        new Notice(`vertiscope: remote media ${
          this.settings.loadRemoteMedia ? "on" : "off"}`);
      },
    });

    this.addCommand({
      id: "vertiscope-check-sidecar",
      name: "Check sidecar connection",
      callback: async () => {
        const health = await this.sidecar.health();
        this.serverEnact = !!(health && health.enact);
        new Notice(health
          ? `vertiscope: sidecar at ${this.settings.sidecar} — ` +
            `${health.pages} pages, ` +
            (health.enact ? "CAN drive the live page" : "read-only")
          : `vertiscope: no sidecar at ${this.settings.sidecar || "(unset)"} — ` +
            "notes still read offline");
      },
    });

    this.registerView(
      GRAPH_VIEW,
      (leaf: WorkspaceLeaf) => {
        const view = new GraphView(
          leaf, this.sidecar, this,
          () => this.settings.loadRemoteMedia);
        // Clicking a page in the projector narrows the browser's ranking to
        // it, and right-clicking releases that (`G-70`). Brokered here for
        // the same reason capture is: neither pane may require the other.
        view.onScope = (url: string) => {
          for (const l of this.app.workspace.getLeavesOfType(BROWSER_VIEW)) {
            const browser = l.view as BrowserView;
            if (browser && typeof browser.setScope === "function") {
              browser.setScope(url);
            }
          }
        };
        // And the browser goes where the reader clicked (`G-40`, `G-58`):
        // same session, scrolled to the chunk, rather than a second
        // rendering of the page beside the first. Brokered for the same
        // reason -- a projector with no browser open must still work.
        // A query from the 3D search field also searches the web in the
        // browser cell (PLUGIN_GOAL 85), when the setting allows it.
        view.onWebSearch = (query: string) => {
          if (!this.settings.webSearch) return;
          const l = this.app.workspace.getLeavesOfType(BROWSER_VIEW)[0];
          const browser = l?.view as BrowserView | undefined;
          if (browser && typeof browser.searchWeb === "function") void browser.searchWeb(query);
        };
        view.onReveal = (url: string, xpath: string) => {
          for (const l of this.app.workspace.getLeavesOfType(BROWSER_VIEW)) {
            const browser = l.view as BrowserView;
            if (browser && typeof browser.reveal === "function") {
              void browser.reveal(url, xpath);
            }
          }
        };
        // Closing a billboard the browser pinned lets the browser drop the
        // pin and its markdown too (`G-78`): one selection, three surfaces.
        view.browsingUrl = () => {
          const l = this.app.workspace.getLeavesOfType(BROWSER_VIEW)[0];
          const b: any = l?.view;
          try { return (typeof b?.shownUrl === "function" ? b.shownUrl() : b?.webview?.getURL()) || ""; } catch { return ""; }
        };
        // A control in a billboard's chunk snapshot is the page's control seen
        // through its trie address: pressing it acts on the live page in the
        // cell (`G-111`). Looked up at the moment of the gesture, so a graph
        // opened before the browser still reaches it.
        view.onAct = async (cid: string, rec: ActRecord) => {
          const cell = this.browserCell();
          return cell ? cell.actOnChunk(cid, rec) : null;
        };
        view.onBillboardClosed = (cid: string) => {
          for (const l of this.app.workspace.getLeavesOfType(BROWSER_VIEW)) {
            const browser = l.view as BrowserView;
            if (browser && typeof browser.unpin === "function") browser.unpin(cid);
          }
        };
        return view;
      },
    );
    // The terminal is a SEPARATE PANE, per NOTEBOOK_PANEL_DESIGN §4a: the
    // in-panel switch selects a kernel run, and shell work lives out here.
    this.registerView(
      TERMINAL_VIEW,
      (leaf: WorkspaceLeaf) => new TerminalView(leaf, this.sidecar),
    );
    this.addCommand({
      id: "vertiscope-open-terminal",
      name: "Open a command terminal",
      callback: () => this.openTerminal(),
    });

    // The browser cell (`G-36`). A pane now; the same component becomes a
    // notebook cell, with the standalone being the expanded view.
    this.registerView(PANEL_VIEW, (leaf: WorkspaceLeaf) => new PanelView(leaf));
    this.registerView(
      BROWSER_VIEW,
      (leaf: WorkspaceLeaf) => {
        const browser = new BrowserView(
        leaf, this.sidecar,
        // Live capture reaches the projector through the plugin rather than
        // by one view holding the other: a graph pane that is closed, or has
        // not been opened yet, must not stop the browser cell from scanning.
        // And to the PANELS, not only the projector (`S-12`). The row asks
        // that one capture reach the graph and the open and closed panel
        // sets uniformly; a panel opened after the change reads the store
        // fresh and could hardly be wrong, and that is exactly what hid the
        // one that was already open being stale.
        (nodes, edges, trace) => {
          this.eachGraph((view) => view.absorb(nodes, edges, trace));
        },
        // And so does the ranking (`G-55`, `G-56`): what the reader has
        // scrolled to is what the projector opens the page to.
        (url, cids) => this.eachGraph((view) => void view.showHits(url, cids)));
        // Hovering a chunk in the browser rings its node in the projector
        // (`G-38`). Brokered like everything else across the two panes.
        browser.onRightChunk = (cid: string, url: string, stored: string) =>
          this.eachGraph((view) => view.rightPanel(cid, url, stored));
        browser.onHover = (cid: string, url: string, stored?: string) =>
          this.eachGraph((view) => {
            if (stored) { view.highlightChunk(cid, url, stored); return; }
            // A stored ANCESTOR covers the hovered chunk only roughly -- the
            // tile not yet stored resolved to archive.org's whole search-page
            // container (a hidden feedback survey, 2026-10-17). The grey node
            // with the chunk's exact streamed content wins when it is drawn;
            // the ancestor is the fallback. Planted: `ancestor-over-grey`.
            const cover = browser.storedCoverFor(cid, url);
            const grey = !cover.exact && !browser.plant.has("ancestor-over-grey") && view.hasNode(cid);
            view.highlightChunk(cid, url, grey ? "" : cover.cid);
          });
        // Right-click pins a chunk: its billboard opens in the graph and
        // stays while the browser's markdown side holds it (`G-78`).
        // A capture rewrote chunks: their open billboards redraw. The
        // browser re-reads its own pins; this carries the other form.
        // Every drain's delta goes to the force tree (`G-89`) the moment it
        // is decoded -- before the capture's round trip.
        browser.onDrain = (delta) => this.eachGraph((view) => view.forceDelta(delta));
        browser.onUnstored = (url: string, ids: string[]) =>
          this.eachGraph((view) => view.dropForceIds(ids));
        browser.onLeaving = (url: string) =>
          this.eachGraph((view) => view.dropForce(url));
        browser.onLeft = (url: string) =>
          this.eachGraph((view) => view.collapsePage(url));
        browser.onCovers = (url, covers, settled) =>
          this.eachGraph((view) => view.coverForce(url, covers, settled));
        // The central diff (retired / renamed / known), once per capture and
        // per settle: every graph view applies this one record.
        browser.onDiff = (diff) =>
          this.eachGraph((view) => view.applyDiff(diff));
        browser.onDirty = (cids: string[]) =>
          this.eachGraph((view) => view.refreshBillboards(cids));
        browser.onPin = (cid: string) =>
          this.eachGraph((view) => {
            view.onNavigate = (href: string) => browser.go(href);
            // A pin whose chunk the store no longer holds (retired by a
            // capture before any diff could say so) places nothing: the
            // browser re-anchors it by its address (G-82, 2026-10-17).
            void view.pinChunk(cid).then((ok) => {
              if (!ok && !browser.plant.has("no-pin-reresolve")) {
                void browser.reanchorPins([cid]);
              }
            });
          });
        browser.onPictures = (byCid: Record<string, string>) =>
          this.eachGraph((view) => view.setPictures(byCid));
        // Any billboard opened in 3D can ask for its chunk's page snapshot.
        this.eachGraph((view) => {
          view.snapshotFor = (cid: string, url: string, again?: boolean) => browser.snapshotChunk(cid, url, !!again);
          view.onNavigate = (href: string) => browser.go(href);
          view.forcePayloadFor = (id: string) => browser.forcePayload(id);
          view.hoverElementOf = (cid: string) => browser.hoverElementOf(cid);
          view.greyUnitFor = (cid: string) => browser.greyUnitFor(cid);
        });
        browser.onProjected = (url: string, got: any) =>
          this.eachGraph((view) => view.applyProjected(url, got));
        browser.onUnpin = (cid: string) =>
          this.eachGraph((view) => view.unpinChunk(cid));
        return browser;
      },
    );
    this.addCommand({
      id: "vertiscope-open-browser",
      name: "Open the browser cell",
      callback: () => this.openBrowser(),
    });

    // (The profile pane and its status-bar readout are gone (`G-76`): the
    // pipeline's statistics live in the browser cell's corner box, where the
    // page they describe is, and where the MCP tools read and toggle them.)
    // A layout saved while those panes existed still names them; close
    // those leaves rather than leave "plugin view missing" tabs behind.
    this.app.workspace.onLayoutReady(() => {
      for (const gone of ["vertiscope-profile-view", "vertiscope-chunk-view"]) {
        this.app.workspace.detachLeavesOfType(gone);
      }
    });

    this.addRibbonIcon("git-fork", "vertiscope 3D graph", () => this.openGraph());
    this.addCommand({
      id: "vertiscope-open-graph",
      name: "Open the 3D graph",
      callback: () => this.openGraph(),
    });

    // Ask the server what it allows, once, at load. A surface drawn before
    // the answer arrives is read-only, which is the safe direction to be
    // wrong in.
    this.sidecar.health().then((h) => { this.serverEnact = !!(h && h.enact); });

    this.addSettingTab(new VertiscopeSettingTab(this.app, this));
  }

  /** Pending chunk-mark refresh, so typing does not ask once per keystroke. */
  private chunkTimer: number | null = null;

  /**
   * Ask again, but not on every keystroke.
   *
   * The boundaries are a round trip and a full re-chunk of the note, and while
   * a reader is typing the answer is stale before it arrives. Debounced to the
   * pause between words rather than throttled: a throttle would answer DURING
   * the typing, which is exactly when the answer is worth least.
   */
  private scheduleChunkMarks() {
    if (this.chunkTimer !== null) window.clearTimeout(this.chunkTimer);
    this.chunkTimer = window.setTimeout(() => {
      this.chunkTimer = null;
      void this.refreshChunkMarks();
    }, 700);
  }

  /** Re-ask the sidecar where this note's chunks fall, and redraw the gutter. */
  private async refreshChunkMarks() {
    const view = this.app.workspace.getActiveViewOfType(MarkdownView);
    // @ts-ignore -- `editor.cm` is the CM6 EditorView; Obsidian does not type it.
    const cm = view?.editor?.cm as { state: unknown; dispatch: Function } | undefined;
    if (!view || !cm) return;
    const preview = await this.sidecar.chunkPreview(
      view.editor.getValue(), view.file?.path ?? "untitled.md");
    if (!preview) return;
    // The editor may have changed under the request -- a reader keeps typing.
    // Dispatching anyway is right: the marks are approximate between
    // keystrokes by nature, and the next debounce corrects them. What would
    // NOT be right is dispatching into a different note, so the path is
    // re-checked.
    const still = this.app.workspace.getActiveViewOfType(MarkdownView);
    if (still?.file?.path !== view.file?.path) return;
    cm.dispatch({ effects: setChunkSpans.of(preview.chunks as ChunkSpan[]) });
  }

  /**
   * A fence's run button was pressed: run it in the note's kernel.
   *
   * The NOTE is sent, not the cell, because the note is the isolation boundary
   * (`NOTEBOOK_PANEL_DESIGN` §4): variables are shared between cells of one note
   * and isolated across notes. Without a path there is no boundary to name, so
   * this refuses rather than letting the server default one — a defaulted note
   * would put every cell in the vault into one namespace, which surfaces as a
   * mysterious collision between unrelated notes.
   *
   * The result is written into the note as an output block (`outputs.ts`) and
   * ALSO shown as a Notice. Both, because they answer different questions: the
   * note is the durable record a later reader and the trie both see, and the
   * Notice is what tells the person who just clicked that anything happened at
   * all — an output block scrolled off screen is indistinguishable from a button
   * that did nothing.
   */
  async onRunFence(req: RunRequest): Promise<void> {
    const note = req.path || this.app.workspace.getActiveFile()?.path || "";
    if (!note) {
      new Notice("vertiscope: cannot run a cell outside a note — " +
                 "the note is the kernel's isolation boundary", 6000);
      return;
    }

    const running = new Notice(`vertiscope: running ${req.lang}…`, 0);
    let reply;
    try {
      reply = await this.sidecar.runCell(note, req.code, req.lang);
    } finally {
      running.hide();
    }

    if (!reply) {
      new Notice(`vertiscope: no sidecar at ${this.settings.sidecar || "(unset)"} ` +
                 "— cannot run cells", 6000);
      return;
    }
    if (reply.error && reply.ok === undefined) {
      // The server refused rather than the cell failing: 403 when the kernel is
      // off, 400 when the request was wrong. Both carry a `detail` that says
      // what to do, and showing it is the difference between "off" and "broken".
      new Notice(`vertiscope: ${reply.error}` +
                 (reply.detail ? ` — ${reply.detail}` : ""), 9000);
      return;
    }

    // Whenever the namespace is not the one the previous cell left, say so. A
    // silently-empty variable reads as a bug in the reader's own code.
    const notes: string[] = [];
    if (reply.kernel) notes.push(reply.kernel);
    if (reply.evicted) notes.push(`retired ${reply.evicted}'s kernel`);

    const stored = await this.storeOutput(note, req, reply);
    if (stored) notes.push(stored);

    const last = (reply.error || "").trim().split("\n").pop();
    const shown = reply.ok
      ? ([reply.stdout, reply.stderr, reply.value ?? ""]
          .filter((s) => s && s.trim()).join("\n").trim() || "ok, no output")
      : (last || "failed");
    new Notice(`vertiscope [${reply.count ?? "?"}] ${shown}` +
               (notes.length ? `\n(${notes.join("; ")})` : ""), 8000);
  }

  /**
   * Write a cell's result into the note, after its closing fence.
   *
   * Returns a note for the Notice when something the reader should hear happened,
   * and `""` when the write was ordinary.
   *
   * The cell is re-found from the file's CURRENT text rather than trusted from
   * the click. A cell can take a minute, and the reader is free to keep typing
   * while it does; `req.line` was true when the button was pressed and may name
   * a different fence by the time the answer arrives. Re-reading and matching on
   * the source is what stops an output landing under the wrong cell.
   */
  private async storeOutput(note: string, req: RunRequest,
                            reply: KernelReply): Promise<string> {
    const file = this.app.vault.getAbstractFileByPath(note);
    if (!(file instanceof TFile)) return "";
    const hash = await hashCell(req.code);
    let outcome = "";
    try {
      // `process` is read-modify-write under one lock. `read` then `modify`
      // would drop whatever the reader typed in between, which for a slow cell
      // is a real window and loses THEIR work rather than ours.
      await this.app.vault.process(file, (text) => {
        const fences = findFences(text);
        // Prefer the fence still at the clicked line; fall back to the only
        // fence with this exact source. If neither is unambiguous, write
        // nothing -- a misplaced output is worse than an absent one, because
        // the reader would trust it.
        let target = fences.find((f) => f.openLine === req.line
                                     && cellSource(f.body) === req.code);
        if (!target) {
          const same = fences.filter((f) => cellSource(f.body) === req.code);
          if (same.length === 1) target = same[0];
        }
        if (!target) {
          outcome = "output not stored: the cell moved or changed";
          return text;
        }
        return withOutput(text, target.closeLine, renderOutput(reply, hash));
      });
    } catch (err) {
      outcome = `output not stored: ${
        err instanceof Error ? err.message : String(err)}`;
    }
    return outcome;
  }

  onunload() {
    this.surfaces.clear();
    // The view's own `onClose` releases the WebGL context; detaching leaves
    // is Obsidian's job and doing it here is explicitly discouraged, because
    // it destroys layout the user arranged.
  }

  /**
   * A terminal pane, and a NEW one each time it is asked for.
   *
   * The graph reuses its leaf because there is one graph; terminals are the
   * opposite -- two of them is the ordinary case (a build in one, git in the
   * other), and each is its own session. Reusing a leaf would make the second
   * request silently steal the first's pane.
   */

  /** Do something to every open projector, if any is open at all. */

  /**
   * Every LOADED graph pane. A pane in a background tab is a deferred stub
   * with none of the view's methods: calling one threw inside the browser's
   * drain -- "view.forceDelta is not a function" -- before the capture was
   * sent, so while the graph sat in a background tab NOTHING was captured
   * (2026-09-27: two purged pages would not re-store). And one pane's
   * failure must not stop the others, or the browser.
   */
  private eachGraph(fn: (view: GraphView) => void): void {
    for (const leaf of this.app.workspace.getLeavesOfType(GRAPH_VIEW)) {
      const view = leaf.view as GraphView;
      if (!view || (leaf as any).isDeferred || !(view instanceof GraphView)) continue;
      try { fn(view); } catch (err) { console.error("vertiscope: a graph pane failed", err); }
    }
  }

  /** Put a browser cell in a pane, reusing one if it is already open. */
  async openBrowser(): Promise<void> {
    const existing = this.app.workspace.getLeavesOfType(BROWSER_VIEW);
    if (existing.length) {
      this.app.workspace.revealLeaf(existing[0]);
      return;
    }
    const leaf = this.app.workspace.getLeaf("split", "vertical");
    await leaf.setViewState({ type: BROWSER_VIEW, active: true });
    this.app.workspace.revealLeaf(leaf);
  }

  private async openTerminal() {
    const leaf = this.app.workspace.getLeaf("split", "horizontal");
    await leaf.setViewState({ type: TERMINAL_VIEW, active: true });
    this.app.workspace.revealLeaf(leaf);
  }

  private async openGraph() {
    const existing = this.app.workspace.getLeavesOfType(GRAPH_VIEW);
    if (existing.length) {
      this.app.workspace.revealLeaf(existing[0]);
      return;
    }
    const leaf = this.app.workspace.getLeaf("tab");
    await leaf.setViewState({ type: GRAPH_VIEW, active: true });
    this.app.workspace.revealLeaf(leaf);
  }


  /**
   * Open the note a graph node stands for.
   *
   * Matched on the `cid` in frontmatter rather than on the file name, because
   * the exporter names notes for their first words and two chunks can start
   * the same way. The cid is the identity everything else is keyed on.
   */
  private async revealChunk(cid: string) {
    const file = this.app.vault.getMarkdownFiles().find((f) => {
      const cache = this.app.metadataCache.getFileCache(f);
      return cache?.frontmatter?.cid === cid;
    });
    if (!file) {
      new Notice(`vertiscope: no exported note for ${cid.slice(0, 8)}`);
      return;
    }
    await this.app.workspace.getLeaf(false).openFile(file);
  }

  async saveSettings() {
    await this.saveData(this.settings);
  }

  fetchChunk(cid: string): Promise<ChunkPayload | null> {
    return this.sidecar.chunk(cid);
  }

  canEnact(): boolean {
    return this.serverEnact;
  }

  /** The open browser cell, if its view is loaded (a background tab is a stub). */
  private browserCell(): BrowserView | null {
    for (const l of this.app.workspace.getLeavesOfType(BROWSER_VIEW)) {
      const b = l.view as BrowserView;
      if (b && typeof b.actOn === "function") return b;
    }
    return null;
  }

  /**
   * A surface's control, pressed: in the browser cell the reader is looking at
   * when there is one (`G-111`), and only otherwise by the sidecar's own
   * headless Firefox, which has been the only thing `/enact` could drive.
   */
  enact(address: string, action = "press",
        text?: string): Promise<EnactResult | null> {
    const cell = this.browserCell();
    if (cell) return cell.actOnAddress(address, action, text);
    return this.sidecar.enact(address, action, text);
  }

  private renderChunk(
    source: string,
    el: HTMLElement,
    ctx: MarkdownPostProcessorContext,
  ) {
    const cid = parseCid(source);
    if (!cid) {
      el.createEl("div", {
        cls: "vertiscope-error",
        text: "vertiscope: this block carries no cid",
      });
      return;
    }
    const surface = new ChunkSurface(el, cid, this);
    // addChild ties the surface to the element's life: when the user edits
    // the note and this section is replaced, onunload runs. Without it an
    // aborted fetch resolves into a detached element.
    ctx.addChild(surface);
    this.surfaces.add(surface);
    surface.register(() => this.surfaces.delete(surface));
  }
}

function parseCid(source: string): string | null {
  const m = /^\s*cid:\s*([A-Za-z0-9]+)\s*$/m.exec(source);
  return m ? m[1] : null;
}

class VertiscopeSettingTab extends PluginSettingTab {
  constructor(app: App, private plugin: VertiscopePlugin) {
    super(app, plugin);
  }

  display() {
    const { containerEl } = this;
    containerEl.empty();

    new Setting(containerEl)
      .setName("Sidecar address")
      .setDesc(
        "Where the vertiscope Python sidecar answers. Leave empty to work purely " +
          "from the exported notes, with no process and no network.",
      )
      .addText((t) =>
        t
          .setPlaceholder(DEFAULTS.sidecar)
          .setValue(this.plugin.settings.sidecar)
          .onChange(async (v) => {
            this.plugin.settings.sidecar = v;
            await this.plugin.saveSettings();
          }),
      );

    new Setting(containerEl)
      .setName("Open as interactive surface")
      .setDesc("Otherwise a chunk opens as its distilled markdown.")
      .addToggle((t) =>
        t
          .setValue(this.plugin.settings.interactiveByDefault)
          .onChange(async (v) => {
            this.plugin.settings.interactiveByDefault = v;
            await this.plugin.saveSettings();
          }),
      );

    new Setting(containerEl)
      .setName("Load remote media")
      .setDesc(
        "Off by default, and that is a privacy setting rather than a " +
          "performance one: fetching a page's images from your vault tells " +
          "those hosts the page was read again, at a new time, from a new " +
          "address. With it off, media shows as a captioned placeholder.",
      )
      .addToggle((t) =>
        t
          .setValue(this.plugin.settings.loadRemoteMedia)
          .onChange(async (v) => {
            this.plugin.settings.loadRemoteMedia = v;
            await this.plugin.saveSettings();
          }),
      );

    new Setting(containerEl)
      .setName("Retrieval results")
      .setDesc("How many passages the `/` gesture offers.")
      .addSlider((s) =>
        s
          .setLimits(3, 20, 1)
          .setDynamicTooltip()
          .setValue(this.plugin.settings.retrievalLimit)
          .onChange(async (v) => {
            this.plugin.settings.retrievalLimit = v;
            await this.plugin.saveSettings();
          }),
      );
  }
}
