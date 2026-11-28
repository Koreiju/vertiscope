/**
 * domvec bridge -- distilled web chunks as live surfaces inside notes.
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

import { mdLink } from "./egolinks";
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
  editorInfoField,
  Modal,
  Menu,
  SuggestModal,
} from "obsidian";

import { installHarness } from "./harness";
import { TERMINAL_VIEW, TerminalView } from "./terminal";
import { CODE_VIEW, CodeView } from "./codeview";
import { BROWSER_FENCE, browserFence, notebookBrowsers, registerNotebookLeaves } from "./nbbrowser";
import {
  RunHost, RunRequest, livePreviewRunButtons, readingViewRunButtons,
} from "./runbutton";
import { cellSource, findFences } from "./fences";
import { ChunkSpan, chunkGutter, setChunkSpans } from "./chunkgutter";
import { EditorView } from "@codemirror/view";
import { bodyHidden, chunkHalves, setBodyHidden } from "./chunkhalves";
import { ensureCellBar } from "./cellbar";
import { hashCell, renderOutput, withOutput } from "./outputs";
import { BROWSER_VIEW, BrowserView } from "./browser";
import type { ActRecord } from "./panelact";
import { GRAPH_VIEW, GraphView } from "./graph";
import { RetrievalSuggest } from "./retrieval";
import { GestureHost, linkGesture } from "./linkgesture";
import { Sidecar } from "./sidecar";
import { ChunkSurface, SurfaceHost } from "./surface";
import { ChunkPayload, DEFAULTS, DomvecSettings, EnactResult, KernelReply }
  from "./types";
import { VaultLinks } from "./vaultlinks";
import { PANEL_VIEW, PanelView } from "./panelview";
import { COCKPIT_PATH, Cockpit } from "./cockpit";
import { PLANE_FOLDER, PlaneDesk } from "./planepanels";
import { BrowseCard } from "./browsecard";
import { EditorCalls } from "./editorcalls";
import { DataflowRun, noteTextOf } from "./dataflowrun";
import { AutoRun, CrossRun, ToolRun } from "./autorun";
import { PullApart } from "./pullapart";
import { agentBlock } from "./agentblock";
import { Slots, registerDecorator, registerCellControl } from "./slots";
import { pullButton, completeButton } from "./runbutton";
import { isWireframe } from "./wiredefs";
import { completeCell } from "./complete";
import { watchTabDrags } from "./tabdrag";
import { drawDefs, nodeDefs, setDefault, setTraitDefault } from "./nodedefs";
import { markProblems, problemExtension } from "./dfproblems";
import { CodeRows } from "./coderows";
import { BrowserPanel } from "./browserpanel";
import { PlaneHalo } from "./planehalo";
import { slateFolds } from "./slatefold";
import { NotebookChats } from "./notebookchat";
import { NoteMarks } from "./marks";
import { ChatCellHost, chatCell, ensureChatFence, extractReplyToolBodies, plusChat, streamPromptIntoNote } from "./chatcell";
import { executeToolFenceOnExit, toolBlockProcessor, toolHistoryExtension, writeToolStepToNote } from "./toolcell";
import { fenceCodeExtensions } from "./codecell";
import { slateLint, slateLintStats } from "./slatelint";
import { EditorView as CmView } from "@codemirror/view";

export default class DomvecPlugin extends Plugin implements SurfaceHost, RunHost {
  settings: DomvecSettings = DEFAULTS;

  /**
   * **uBlock Origin in the browser cell** (G-201, 2026-10-17: "please add
   * uBlock origin to our browser immediately"). The official 1.75.0 chromium
   * build, unpacked under this plugin's `extensions/`, loaded into the
   * browser cell's OWN session (`persist:domvec`) -- never Obsidian's -- once
   * per app run, without file access. Electron implements only part of the
   * extension API, so what it actually blocks is measured, not assumed
   * (`window.__domvecAdblock`). Off with the `adblock` setting.
   */
  async loadAdblock(): Promise<void> {
    const st: any = ((window as any).__domvecAdblock = { wanted: !!this.settings.adblock, loaded: false });
    if (!this.settings.adblock) return;
    try {
      const remote = (require("electron") as any).remote;
      const ses = remote?.session?.fromPartition("persist:domvec");
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
        const shimPath = `${dir}/js/domvec-electron-shim.js`;
        if (!fs.existsSync(shimPath) || fs.readFileSync(shimPath, "utf8") !== UBLOCK_SHIM) fs.writeFileSync(shimPath, UBLOCK_SHIM, "utf8");
        const bgPath = `${dir}/background.html`;
        const bg = fs.readFileSync(bgPath, "utf8");
        if (!bg.includes("domvec-electron-shim.js")) {
          fs.writeFileSync(bgPath, bg.replace("<body>", '<body>' + String.fromCharCode(10) + '<script src="js/domvec-electron-shim.js"></script>'), "utf8");
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
    // The plugin-scope require, for the harness to ask which CodeMirror
    // modules Obsidian hands a plugin (codecell.ts uses the same ones).
    (window as any).__domvecRequire = (m: string) => require(m);
    this.routeLinksToCell();
    this.hookHoverCopy();
    // PLUGIN_GOAL 147: new vaults get the plugin, and a vault with no sidecar
    // of its own starts one on its own fresh workspace.
    window.setTimeout(() => { this.installIntoNewVaults(); }, 5000);
    this.registerInterval(window.setInterval(() => this.installIntoNewVaults(), 15000));
    window.setTimeout(() => { void this.autostartSidecar(); }, 2500);
    // The workspace button names the open workspace (144); the view's header
    // is built before the plugin hands it the menu, so it is labelled here.
    // Every second tick also keeps the sidecar button's dot in step with the
    // running sidecar and reloads an empty graph view as soon as the sidecar answers.
    let barTick = 0;
    this.registerInterval(window.setInterval(() => {
      const name = (this.settings.activeWorkspace || this.workspaceNameOf(this.settings.sidecarLaunch?.workspace) || "workspace") + " ▾";
      for (const leaf of this.app.workspace.getLeavesOfType("domvec-graph-view")) {
        const b = (leaf.view as any).workspaceButton as HTMLElement | null;
        if (b && b.textContent !== name) b.setText(name);
      }
      if (++barTick % 2 === 0) void this.pollSidecarStatus();
    }, 2000));
    // This load's generation (G-175): a view born in an earlier load whose
    // loop is still running reads a newer number and stops itself.
    (window as any).__domvecLoadGen = ((window as any).__domvecLoadGen || 0) + 1;

    // **The harness: one wrapper over the UI layer (`D-24`).**
    //
    // `__domvec.ui()` is the interface as a data structure in SCREEN
    // pixels; `__domvec.trace` captures every sidecar call at the fetch
    // boundary; `__domvec.act()` runs a gesture through the application's
    // own paths and returns the UI before, the UI after, and the backend
    // work it caused. The checks used to read JavaScript properties, which
    // is how three of them passed while the pane showed a clump.
    installHarness(this.app, () => this.settings.sidecar);

    // When the READER last used THIS app (2026-09-28: "Idle's never going to
    // finish" -- the machine-wide idle clock counted every keystroke in every
    // window, so an in-app run waited an hour for a reader typing elsewhere).
    // Keys, clicks, wheel and pointer in the Obsidian window; pointer moves in
    // the browser cell arrive as the sensor's pushed hovers (browser.ts).
    // Each stamp says what made it (`__domvecReaderBy`): the idle turn
    // "stalls out after some time" (2026-10-17) when something that is not
    // the reader keeps stamping, and the tally is how that is found.
    const by: Record<string, number> = ((window as any).__domvecReaderBy = (window as any).__domvecReaderBy || {});
    // Only TRUSTED input is the reader (2026-10-30): a check's own synthetic
    // pointer sweep (G-174's, `isTrusted: false`, one move a frame) stamped
    // the reader as active, the run paused itself for "the reader is using
    // the app", and its sweep never finished -- in a MINIMIZED window. A
    // synthetic event is tallied as `synthetic:<type>`, never as the reader.
    // Planted `__domvecPlantSyntheticReader`: every event stamps, as before.
    for (const ev of ["keydown", "pointerdown", "wheel", "pointermove"] as const) {
      this.registerDomEvent(window, ev, (e: Event) => {
        if (!e.isTrusted && !(window as any).__domvecPlantSyntheticReader) { by["synthetic:" + ev] = (by["synthetic:" + ev] || 0) + 1; return; }
        (window as any).__domvecReaderAt = Date.now(); by[ev] = (by[ev] || 0) + 1;
      }, { capture: true, passive: true } as any);
    }

    this.settings = Object.assign({}, DEFAULTS, await this.loadData());
    await this.syncSidecarUrl();
    void this.loadAdblock();
    // A test workspace outlives a plugin reload (`session.ts`): put it back,
    // and badge it in the status bar for as long as it lasts.
    const sw: any = (window as any).__domvec?.session?.switcher;
    if (sw) {
      sw.badge = this.addStatusBarItem();
      await sw.resume();
      sw.paint();
    }
    this.sidecar = new Sidecar(() => this.settings.sidecar);
    this.autoRun = new AutoRun(this.app, (req) => this.onRunFence(req), (p) => p === "domvec/ego.md" || p.startsWith("domvec-checks/g418"));
    this.autoRun.onToolFenceExit = (file, fence) =>
      executeToolFenceOnExit(
        this.app,
        {
          sidecarBase: () => this.settings.sidecar,
          carryAsk: (a) => this.carryAnyAsk(a, file.path),
        },
        file,
        fence,
      );
    // Edges between notes: a change to a note re-runs the cells that read it (G-426, G-451).
    this.crossRun = new CrossRun(this.app, (req) => this.onRunFence(req));
    this.app.workspace.onLayoutReady(() => {
      void this.crossRun.build();
      void this.desk.migrateDeprecatedSlates();
    });
    // G-413: a base tool's view change re-runs the cells that read it.
    this.toolRun = new ToolRun(this.app, (req) => this.onRunFence(req),
      (p) => !!this.desk.panelOf(p) || this.markdownLeaves().some((l) => (l.view as any)?.file?.path === p));
    this.app.workspace.onLayoutReady(() => void this.toolRun.build());
    this.registerEvent(this.app.vault.on("modify", (f: any) => { if (f instanceof TFile) void this.toolRun.onModify(f); }));
    this.registerEvent(this.app.vault.on("create", (f: any) => { if (f instanceof TFile) void this.toolRun.onModify(f); }));
    const onView = (e: any) => this.toolRun.onView(String(e?.detail?.tool || ""), String(e?.detail?.url || ""));
    window.addEventListener("domvec-tool-view", onView);
    this.register(() => window.removeEventListener("domvec-tool-view", onView));
    this.registerEvent(this.app.vault.on("modify", (f: any) => { if (f instanceof TFile) void this.crossRun.onModify(f); })); this.registerEvent(this.app.vault.on("create", (f: any) => { if (f instanceof TFile) void this.crossRun.onModify(f); }));
    // The kernel's vault facade (P-N4) is rooted at the vault's own folder.
    this.sidecar.vaultRoot = String((this.app.vault.adapter as any).basePath || "");
    // The sidecar told where the vault is (G-277): a `{ref}` to a note reads the
    // note's own text, tabs and lines intact. Again every 30 s, so a restarted
    // sidecar knows it too.
    const tellVault = () => { if (this.sidecar.vaultRoot) void this.sidecar.egoPost("vault_root", { root: this.sidecar.vaultRoot, name: this.app.vault.getName() }); };
    tellVault();
    this.registerInterval(window.setInterval(tellVault, 30000));
    // What the browser in use shows, told to the sidecar every 2 s: a kernel's
    // `WebBrowser.url` reads it (G-279), the kernel never reaching the plugin.
    this.registerInterval(window.setInterval(() => {
      const b: any = this.activeBrowser();
      let url = "";
      try { url = (typeof b?.shownUrl === "function" ? b.shownUrl() : b?.webview?.getURL()) || ""; } catch { /* no webview yet */ }
      if (url) void this.sidecar.egoPost("browser_state", { url, title: (() => { try { return b?.webview?.getTitle?.() || ""; } catch { return ""; } })() });
    }, 2000));
    // Once a minute while the reader has been idle five minutes: the sidecar
    // may compact its store now, the only moment nobody waits on it (2026-10-18:
    // 1.6 -> 8.8 GB uncompacted, captures 3-10 s -> 15-26 s). Never while the
    // reader is here. Planted `__domvecPlantNoMaintenance`.
    this.registerInterval(window.setInterval(() => {
      const idle = Date.now() - ((window as any).__domvecReaderAt || 0);
      // Not while the app is being exercised: a check run or a stress run is
      // not the reader (G-289), so the reader looks idle, and a compaction
      // asked for then restarted the sidecar under the check (2026-10-30, M-10
      // run 52: "the sidecar died"). Planted `__domvecPlantMaintainDuringChecks`.
      const busy = !!((window as any).__domvec?.verify?.state?.()?.running || (window as any).__domvecStressing);
      if (idle >= 300000 && !(globalThis as any).__domvecPlantNoMaintenance
          && (!busy || (globalThis as any).__domvecPlantMaintainDuringChecks)) void this.sidecar.maintenance(idle);
    }, 60000));
    // A supervisor that GAVE UP (every start stalled at the interpreter;
    // `supervisor_gave_up.json` in the workspace) is replaced by a fresh one
    // started from here, outside whatever launched the old one. The stalls
    // themselves were children inheriting the MCP server's stdin pipe
    // (fixed in `supervise._run_child`, 2026-10-25); this stays as the
    // fallback for a supervisor that gives up for any other reason. Only on
    // that marker: a sidecar the reader stopped is left stopped. Planted
    // `__domvecPlantNoRespawn`.
    this.registerInterval(window.setInterval(() => { void this.watchSidecar(); }, 30000));
    this.links = new VaultLinks(this.app, this.sidecar);
    const links = this.links;
    // A note once indexed (it holds retrieval links) is indexed again when it
    // is edited: its links are the store's, and the store follows the note.
    this.registerEvent(this.app.vault.on("modify", (f) => {
      if (f instanceof TFile && f.extension === "md" && (this.settings.indexedNotes || []).includes(f.path)) {
        this.indexNoteSoon(f, "edited");
      } else if (f instanceof TFile && f.extension === "md") {
        void this.indexIfReservoir(f, "reservoir");
      }
    }));
    this.registerEvent(this.app.vault.on("create", (f) => {
      if (f instanceof TFile && f.extension === "md") void this.indexIfReservoir(f, "reservoir");
    }));
    this.addCommand({ id: "domvec-reservoir-index", name: "Index every computation-graph note (the ego reservoir)",
                      callback: () => { void this.indexReservoir(); } });
    this.gesture = {
      sidecar: this.sidecar,
      stats: { opened: 0, pages: 0, infilled: 0, hovers: 0, similars: 0, last: null },
      plantOverlay: false,
      onOpen: () => { void links.refresh(); },
      onInfill: () => { const f = this.app.workspace.getActiveFile(); if (f) this.indexNoteSoon(f, "infill"); },
      onHoverHit: (hit) => {
        const g: any = this.app.workspace.getLeavesOfType(GRAPH_VIEW)[0]?.view;
        if (!g) return;
        if (!hit) { g.focusOn?.(null); g.hoverPanel?.(null); return; }
        g.highlightChunk?.(hit.cid, hit.url, hit.cid);
      },
      onRightHit: (hit) => {
        const g: any = this.app.workspace.getLeavesOfType(GRAPH_VIEW)[0]?.view;
        const n = g?.graph?.graphData?.().nodes?.find((x: any) => String(x.id) === hit.cid);
        if (n && typeof g.openBillboard === "function") void g.openBillboard(n, false, true);
      },
      onWebSearch: (q) => {
        const browser = this.activeBrowser() as BrowserView | undefined;
        if (browser && typeof browser.searchWeb === "function") void browser.searchWeb(q);
      },
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
    for (const t of [GRAPH_VIEW, BROWSER_VIEW, PANEL_VIEW, TERMINAL_VIEW, CODE_VIEW]) {
      try { if (reg?.viewByType?.[t]) reg.unregisterView(t); } catch { /* not ours to fail on */ }
    }
    try {
      this.registerMarkdownCodeBlockProcessor(
        "domvec",
        (source, el, ctx) => this.renderChunk(source, el, ctx),
      );
    } catch (e) {
      console.warn("domvec: a stale `domvec` fence processor is still registered; keeping it", e);
    }
    // The browser cell inside a notebook (G-36's second host, `nbbrowser.ts`).
    // The block features are EXTENSIONS in named slots (G-240, slots.ts):
    // each may be off or fail and the core runs on; none may take a core slot.
    // PLUGIN_GOAL 195 (c) ```tool (G-421); the ```chat input cell (G-422);
    // G-384's ```agent (G-429/G-430).
    this.slots.add({ id: "agent", slot: "codeblock:agent", register: () => this.registerMarkdownCodeBlockProcessor("agent",
      agentBlock(this.app, () => this.settings.sidecar, (f) => this.desk.open(f), (ask) => this.editor.carry(ask))) });
    this.slots.add({ id: "chat", slot: "codeblock:chat", register: () => this.registerMarkdownCodeBlockProcessor("chat",
      chatCell(this.app, (p, c, on, sig, meta) => this.sidecar.chatStream(p, c, on, sig, meta), this.chatHostCtx())) });
    this.slots.add({ id: "tool", slot: "codeblock:tool", register: () => this.registerMarkdownCodeBlockProcessor("tool",
      toolBlockProcessor(this.app, {
        sidecarBase: () => this.settings.sidecar,
        carryAsk: (a) => this.carryAnyAsk(a),
      })) });
    // The +chat cell is a decoration in a `card:` slot (G-240's second kind).
    this.slots.add({ id: "plus-chat", slot: "card:plus-chat", register: () => registerDecorator("plus-chat", (card, path) => plusChat(this.app, card, path)) });
    // The cell controls that are not the core's are a third kind, `cell:` (G-240).
    this.slots.add({ id: "pull-out", slot: "cell:pull-out", register: () => registerCellControl("pull-out", (req, doc) => pullButton(doc, () => this.onPullFence(req() as any))) });
    this.slots.add({ id: "complete", slot: "cell:complete", register: () => registerCellControl("complete", (req, doc) => isWireframe(req().code) ? completeButton(doc, () => this.onCompleteFence(req() as any)) : null) });
    for (const e of ((window as any).__domvecExtraExtensions || []) as any[]) this.slots.add(e);
    this.slots.load();
    this.register(watchTabDrags(this.app));
    // G-403: a slate field held and dropped on the plane opens there, external.
    this.cockpit.desk = () => this.desk;
    this.desk.revealIn = async (host, ref) => { const v = this.desk.viewOf(host); return v ? this.cockpit.toggleReveal(v, ref) : "none"; };
    this.register(this.cockpit.installHold());
    try {
      this.registerMarkdownCodeBlockProcessor(BROWSER_FENCE, browserFence(this.app));
    } catch (e) {
      console.warn("domvec: a stale `browser` fence processor is still registered; keeping it", e);
    }
    (window as any).__domvecNotebookBrowsers = notebookBrowsers;
    // D-54: a notebook browser cell is a browser to the leaf lookup, where it sits.
    this.register(registerNotebookLeaves(this.app));

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
    this.registerEditorExtension(toolHistoryExtension());
    this.registerEditorExtension(chunkGutter()); this.registerEditorExtension(problemExtension);
    // G-447 / G-450 (PLUGIN_GOAL 200 e, 201 c): VS Code-grade completions, signature help,
    // hover docs, go-to-definition, comment toggle, indent, and diagnostics,
    // adaptive strictly to runnable fenced code cells in markdown notes.
    this.registerEditorExtension(fenceCodeExtensions({
      codeNodes: (q) => this.sidecar.codeNodes(q),
      codeIntel: (b) => this.sidecar.codeIntel(b),
      openCode: (u) => { void this.openCode(u); },
      noteOfView: (cm) => {
        const mv = this.markdownLeaves().map((l) => l.view as any).find((v) => v?.editor?.cm === cm);
        return mv?.file?.path || "";
      },
      externalDefs: (n) => this.crossRun.externalDefsFor(n),
    }));
    // A note's trees checked as the Python module they are (PLUGIN_GOAL 62).
    this.registerEditorExtension(slateLint(() => this.sidecar));
    (window as any).__domvecSlateLint = slateLintStats;
    // The notebook chat (L-2..L-9): a panel at the selected cell's foot; the
    // cursor landing on a new cell is a new rewind, a scroll is not.
    this.nbChats = new NotebookChats(this.app, this, this.sidecar);
    this.nbChats.active = () => this.activeView();
    // The reader's prompts are EGO artifacts (G-305, items 74c, 77): each turn
    // written, as it is sent, into `domvec/graph/prompts <note>.md` -- a note
    // the craft counts as the ego's -- linked back to its notebook and OUT to
    // the world through what it was given: each context chunk a link to its
    // page. The reply follows when it comes. Planted `plantPromptsUnkept`.
    this.nbChats.record = async (note, prompt, context) => {
      if (this.plantPromptsUnkept || !note) return null;
      const folder = PLANE_FOLDER;
      if (!this.app.vault.getAbstractFileByPath(folder)) await this.app.vault.createFolder(folder).catch(() => undefined);
      const base = note.split("/").pop()!.replace(/\.md$/, "");
      const path = `${folder}/prompts ${base}.md`;
      const NL = "\n", at = new Date().toISOString().slice(0, 19);
      const links = context.map((c) => {
        const u = String(c.url || "").split("#")[0];
        if (u.startsWith("vault://")) return mdLink(u.replace(/^vault:\/\/[^/]+\//, ""));
        return u.startsWith("http") ? `[${(c.head || u).slice(0, 60)}](${u})` : "";
      }).filter(Boolean);
      const given = links.length ? ` · given ${[...new Set(links)].join(", ")}` : "";
      // CHAT CELLS (PLUGIN_GOAL 159: "chat cells in prompts and responses in
      // Links are standard `[title](encodeURI(path))` (G-446/G-448), never [[wiki]].
      const toNote = mdLink(note), at_ = (n: string) => mdLink(`${folder}/${n}.md`);
      // their own cells, chained after one another with hard links"): each
      // turn is TWO notes of the ego -- the prompt's cell and the reply's --
      // linked prompt -> reply -> next prompt, so the conversation is a chain
      // in the 2D graph (the craft draws a link between ego notes as an edge).
      // The prompts note stays the chat's index. Planted `plantChatOneNote`:
      // the turn lives in the index alone, as before.
      let cells: { prompt: string; reply: string } | null = null;
      if (!this.plantChatOneNote) {
        const prefix = `${base} chat `;
        const nums = this.app.vault.getMarkdownFiles().filter((x) => x.path.startsWith(`${folder}/${prefix}`))
          .map((x) => /chat (\d+) (?:prompt|reply)$/.exec(x.basename)).filter(Boolean).map((m) => Number(m![1]));
        const n = (nums.length ? Math.max(...nums) : 0) + 1, pad = (k: number) => String(k).padStart(3, "0");
        const pName = `${prefix}${pad(n)} prompt`, rName = `${prefix}${pad(n)} reply`;
        const prev = n > 1 ? `${prefix}${pad(n - 1)} reply` : "";
        await this.app.vault.create(`${folder}/${pName}.md`, `# prompt ${n} of ${toNote}` + NL + NL
          + `> ${prompt.replace(/\n/g, NL + "> ")}` + NL + NL
          + (prev ? `after ${at_(prev)}` : "the chat's first turn") + NL + NL
          + `context: ${context.length} item${context.length === 1 ? "" : "s"}${given}` + NL);
        await this.app.vault.create(`${folder}/${rName}.md`, `# reply ${n} of ${toNote}` + NL + NL
          + `answers ${at_(pName)}` + NL + NL + "*(awaiting the reply)*" + NL);
        cells = { prompt: `${folder}/${pName}.md`, reply: `${folder}/${rName}.md` };
        this.chatCellStats.turns++;
        this.chatCellStats.last = { ...cells, after: prev };
      }
      const name = (p: string) => p.split("/").pop()!.replace(/\.md$/, "");
      const entry = `## ${at}` + NL + NL + `> ${prompt.replace(/\n/g, NL + "> ")}` + NL + NL
        + `from ${toNote}` + given + NL + NL
        + (cells ? `${mdLink(cells.prompt)} -> ${mdLink(cells.reply)}` + NL + NL : "")
        + "*(awaiting the reply)*" + NL;
      const f = this.app.vault.getAbstractFileByPath(path);
      if (f instanceof TFile) await this.app.vault.process(f, (t) => t.replace(/\s*$/, "") + NL + NL + entry);
      else await this.app.vault.create(path, `# prompts of ${toNote}` + NL + NL + entry);
      this.promptStats.kept++;
      this.promptStats.last = { path, links: links.length };
      return path + "#" + at + (cells ? "#" + cells.reply + "#" + cells.prompt : "");
    };
    this.nbChats.recordReply = async (at, reply, error, sent) => {
      const [path, stamp, replyCell, promptCell] = at.split("#");
      const AWAIT = "*(awaiting the reply)*";
      const swap = async (p: string, from: string, body: string) => {
        const f = this.app.vault.getAbstractFileByPath(p);
        if (!(f instanceof TFile)) return;
        await this.app.vault.process(f, (t) => {
          const i = from ? t.lastIndexOf(from) : 0;
          const j = i < 0 ? -1 : t.indexOf(AWAIT, i);
          return j < 0 ? t : t.slice(0, j) + body + t.slice(j + AWAIT.length);
        });
      };
      const body = reply ? reply.trim() : `*(no reply: ${error})*`;
      if (replyCell) {
        // The reply in its own cell; the index points at it, not a second copy.
        await swap(replyCell, "", body);
        await swap(path, "## " + stamp, reply ? "*(replied)*" : body);
      } else await swap(path, "## " + stamp, body);
      // What the model was actually GIVEN, on the prompt's own cell (159:
      // "whether or not we have context control correct"): how much was new
      // to the conversation and how much was already in it, not resent.
      if (promptCell && sent) {
        const f = this.app.vault.getAbstractFileByPath(promptCell);
        if (f instanceof TFile) await this.app.vault.process(f, (t) => t.replace(/\s*$/, "") + "\n\n"
          + `sent: ${sent.sent} new to the chat, ${sent.dropped} already in it (not resent), ${sent.chars} characters` + "\n");
      }
    };
    (window as any).__domvecNbChats = this.nbChats;
    // The reader marks what the model is given (P-N9/P-N10, `marks.ts`): a
    // selection in reading view becomes trie addresses, drawn highlighted,
    // and the note's chat sends those in place of the rewind.
    this.marks = new NoteMarks(this.app, this.sidecar,
      async () => { this.settings.marks = this.marks.byNote; await this.saveSettings(); },
      (path) => { const f = this.app.vault.getAbstractFileByPath(path); const c = f instanceof TFile ? this.nbChats?.forFile(f) : null; c?.refresh(); });
    this.marks.byNote = { ...(this.settings.marks || {}) };
    this.nbChats.marks = this.marks;
    (window as any).__domvecMarks = this.marks;
    // The plane's panels and its tools (items 65-66): the checks reach a
    // probe note through these, never through a workspace tab.
    (window as any).__domvecPlane = this.desk;
    (window as any).__domvecBrowseCard = this.browseCard;
    this.browseCard.start();
    this.register(() => this.browseCard.stop());
    this.registerInterval(window.setInterval(() => this.desk.ensureTools(), 1000));
    this.registerInterval(window.setInterval(() => { void this.codeRows.sweep(); }, 1000));
    // G-326: each panel sized to the fields it shows, folded to its node at its root.
    this.registerInterval(window.setInterval(() => this.desk.fitAll(), 400));
    this.registerDomEvent(document, "mouseup", () => {
      const sel = window.getSelection();
      // The view the selection is IN -- a tab or a panel on the plane.
      const view = (sel && sel.anchorNode ? this.markdownLeaves().map((l) => l.view as MarkdownView)
        .find((v) => v?.containerEl?.contains(sel.anchorNode as Node)) : null) || this.activeView();
      if (!view || view.getMode() !== "preview" || !sel || sel.isCollapsed) return;
      const host = (view as any).previewMode?.containerEl as HTMLElement | undefined;
      if (!host || !sel.anchorNode || !host.contains(sel.anchorNode)) return;
      void this.marks.markSelection(view).then((m) => { if (m.length) this.nbChats?.forView(view)?.land(); });
    });
    this.registerMarkdownPostProcessor((el, ctx) => {
      if (!this.marks.count(ctx.sourcePath)) return;
      this.marks.paintBlock(el, ctx.sourcePath, ctx.getSectionInfo(el));
    });
    // A marked note's spans re-resolved when it opens or changes, so the
    // highlight follows its addresses rather than its old line numbers.
    const remark = async (f: TFile | null | undefined, fromFile = false) => {
      if (!f || !this.marks.count(f.path)) return;
      await this.marks.resolve(f, fromFile);
      const paintAll = () => {
        for (const leaf of this.markdownLeaves()) {
          const v = leaf.view as MarkdownView;
          if (v.file?.path === f.path) this.marks.paint(v);
        }
      };
      paintAll();
      // Again once the reading view has re-rendered: its sections' line
      // numbers update after the edit lands, and a paint between the two put
      // the mark on the block above (P-N9, a section inserted above it).
      window.setTimeout(paintAll, 400);
      window.setTimeout(paintAll, 1200);
    };
    this.registerEvent(this.app.workspace.on("file-open", (f) => void remark(f)));
    this.registerEvent(this.app.vault.on("modify", (f) => { if (f instanceof TFile) void remark(f, true); }));
    let nbTimer = 0;
    this.registerEditorExtension(CmView.updateListener.of((u) => {
      if (u.selectionSet || u.focusChanged) {
        const mv = this.markdownLeaves().map((l) => l.view as any).find((v) => v?.editor?.cm === u.view);
        if (mv?.editor && mv?.file) {
          this.autoRun.flushOutside(mv.editor, mv.file, u.focusChanged && !u.view.hasFocus);
        }
      }
      if (!u.selectionSet && !u.docChanged) return;
      window.clearTimeout(nbTimer);
      nbTimer = window.setTimeout(() => this.nbChats?.onCursor(), 120);
    }));
    // The notebook the reader is in: where a prototype cell goes (G-105). Read
    // from the FILE: a note opened into the active tab fires `file-open` and
    // no leaf change, before its editor holds the text. (The first version
    // tested the editor with a `\b` a heredoc had turned into a backspace
    // byte, so no note ever counted.)
    const noteNotebook = (file: TFile | null | undefined) => this.noteNotebook(file);
    this.registerEvent(this.app.workspace.on("active-leaf-change", () => {
      this.nbChats?.onCursor();
      this.wsActiveAt = performance.now();
      void noteNotebook(this.activeView()?.file);
    }));
    this.registerEvent(this.app.workspace.on("file-open", (f) => void noteNotebook(f)));
    // A chunk note's two halves, one at a time (`D-3`): `chunkhalves.ts`.
    this.registerEditorExtension(chunkHalves());
    // The slate's fold state, as decorations (G-278): `slatefold.ts`.
    this.registerEditorExtension(slateFolds());
    for (const ev of ["layout-change", "file-open", "active-leaf-change"] as const) {
      this.registerEvent((this.app.workspace as any).on(ev, () => { this.applyHalves(); this.cockpit.decorate(); }));
    }
    this.registerEvent(this.app.metadataCache.on("changed", () => { this.applyHalves(); this.cockpit.decorate(); }));
    // The cockpit (G-280): the `ego` slate's fields bound both ways to the
    // user agent and the search -- the text read on every edit, the agent's
    // own changes written back a few times a second.
    this.registerEvent(this.app.workspace.on("editor-change", (_e: any, info: any) => {
      this.cockpit.onEdit(info?.file || null);
      this.autoRun.onEdit(_e, info?.file || null);
      if (info?.file?.path) void this.desk.syncHeadTitle(info.file.path);
      for (const b of this.browserPanels) b.onEdit(info?.file || null);
    }));
    this.registerInterval(window.setInterval(() => { this.cockpit.sync(); for (const b of this.browserPanels) b.sync(); }, 250));
    (window as any).__domvecBrowserPanel = this.browserPanel;
    this.browserPanels = [this.browserPanel];
    (window as any).__domvecBrowsers = this;
    (window as any).__domvecActiveBrowser = () => this.activeBrowser();
    (window as any).__domvecHalo = this.halo;
    this.addCommand({ id: "domvec-cockpit", name: "Open the cockpit (ego slate)", callback: () => { void this.cockpit.open(); } });
    // PLUGIN_GOAL 144: workspaces per vault -- a new project starts empty.
    this.addCommand({ id: "domvec-workspace-new", name: "New workspace (empty store, nothing inherited)",
      callback: () => { new WorkspaceNameModal(this.app, (name) => { void this.useWorkspace(name, true); }).open(); } });
    // T-15 (PLUGIN_GOAL 186f): a type from a trie-path pattern, as a code cell on the plane.
    this.addCommand({ id: "domvec-typegen", name: "Type from a trie-path pattern (pydantic, across every stored page)",
      callback: () => { new WorkspaceNameModal(this.app, (pat) => { void this.typeFromPattern(pat); }, "Trie-path pattern, e.g. /html/body/main/article[*]").open(); } });
    this.addCommand({ id: "domvec-idle-drift", name: "Toggle idle drift (camera turns and colours cycle when idle)",
      callback: () => { for (const leaf of this.app.workspace.getLeavesOfType("domvec-graph-view")) { const v: any = leaf.view; v.driftEnabled = !v.driftEnabled; new Notice("domvec idle drift " + (v.driftEnabled ? "on" : "off")); break; } } });
    this.addCommand({ id: "domvec-workspace-switch", name: "Switch workspace",
      callback: () => { new WorkspacePickModal(this.app, this.workspaceList(), this.settings.activeWorkspace || "",
        (name) => { void this.useWorkspace(name, false); }).open(); } });
    // The structural-cell strip at the bottom of every note (`P-M4`); put
    // back whenever Obsidian rebuilds a renderer under it.
    this.registerInterval(window.setInterval(() => this.applyCellBars(), 500));
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
      // Its row in the ego's `unfolded` goes too (PLUGIN_GOAL 159, G-364).
      void this.cockpit?.noteGone(f.path);
      // A deleted note leaves the store (G-291): its pending index is
      // cancelled -- one fired AFTER the delete and put the note back, six
      // check notes on 2026-10-30 -- and its page purged, so its 3D node goes.
      // Planted `__domvecPlantKeepDeleted`.
      if (f.path.endsWith(".md") && !(window as any).__domvecPlantKeepDeleted) {
        window.clearTimeout(this.noteTimers.get(f.path));
        this.noteTimers.delete(f.path);
        this.deletedNotes.add(f.path);
        void this.sidecar.purge("vault://" + this.app.vault.getName() + "/" + f.path);
      }
    }));
    this.registerEvent(this.app.vault.on("rename", (f, oldPath) => {
      // The OLD path, not the new one: the kernel is filed under where the note
      // used to be, and the note under its new name has no kernel yet.
      if (oldPath.endsWith(".md")) void this.sidecar.restartKernel(oldPath);
      void this.cockpit?.noteMoved(oldPath, f.path);
    }));

    this.registerMarkdownPostProcessor(readingViewRunButtons(this));
    this.registerEditorExtension(
      // The note is the EDITOR's own, never the workspace's active file: a
      // panel on the plane is never the active leaf (PLUGIN_GOAL 65), and its
      // run read the active note -- the kernel ran, the output went nowhere.
      livePreviewRunButtons(this, (view) => {
        try { const f = view.state.field(editorInfoField)?.file; if (f) return f.path; } catch { /* not an Obsidian editor */ }
        return this.app.workspace.getActiveFile()?.path ?? "";
      }),
    );

    this.addCommand({
      id: "domvec-unnest-selection",
      name: "Unnest the selection as a black box (G-329)",
      callback: () => { void this.unnestSelection(); },
    });
    this.addCommand({
      id: "domvec-session-empty",
      name: "Start an empty test workspace",
      callback: () => { void (window as any).__domvec?.session?.empty(); },
    });
    this.addCommand({
      id: "domvec-session-restart",
      name: "Restart the test workspace's sidecar",
      callback: () => { void (window as any).__domvec?.session?.restart(); },
    });
    this.addCommand({
      id: "domvec-session-reader",
      name: "Return to my workspace",
      callback: () => { void (window as any).__domvec?.session?.reader(); },
    });
    this.addCommand({
      id: "domvec-toggle-surface",
      name: "Toggle distilled markdown / interactive surface",
      // No default hotkey: Obsidian asks plugins not to claim one, and a
      // conflict is silent -- the command simply stops firing.
      callback: () => this.surfaces.forEach((s) => s.toggle()),
    });

    this.addCommand({
      id: "domvec-toggle-media",
      name: "Toggle loading remote media",
      callback: async () => {
        this.settings.loadRemoteMedia = !this.settings.loadRemoteMedia;
        await this.saveSettings();
        this.surfaces.forEach((s) => s.toggle());
        this.surfaces.forEach((s) => s.toggle());   // redraw, same mode
        new Notice(`domvec: remote media ${
          this.settings.loadRemoteMedia ? "on" : "off"}`);
      },
    });

    this.addCommand({
      id: "domvec-check-sidecar",
      name: "Check sidecar connection",
      callback: async () => {
        await this.sidecarTrigger(false);
      },
    });
    this.addCommand({
      id: "domvec-stop-sidecar",
      name: "Stop sidecar gracefully",
      callback: async () => {
        await this.stopSidecar(false);
      },
    });
    this.addCommand({
      id: "domvec-restart-sidecar",
      name: "Restart sidecar gracefully",
      callback: async () => {
        await this.restartSidecar();
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
          if (!this.settings.webSearch) return false;
          const l = { view: this.activeBrowser() } as any;
          const browser = l?.view as BrowserView | undefined;
          if (!browser || typeof browser.searchWeb !== "function") return false;
          void browser.searchWeb(query);
          return true;
        };
        view.onSidecarTrigger = () => this.sidecarTrigger();
        view.onSidecarMenu = (e, b) => this.sidecarMenu(e, b);
        view.onWorkspaceMenu = (e, b) => this.workspaceMenu(e, b);
        view.onHalo = (path) => { void this.halo.toggle(path); };
        view.workspaceButton?.setText((this.settings.activeWorkspace || this.workspaceNameOf(this.settings.sidecarLaunch?.workspace) || "workspace") + " ▾");
        void this.sidecarTrigger(true).then((t) => view.sidecarButton?.setText(t));
        // ONE browser follows the click -- the one on screen (activeBrowser).
        // Every leaf did until 2026-11-14, so a background tab playing music
        // was navigated away (PLUGIN_GOAL 157).
        view.onReveal = (url: string, xpath: string) => {
          const targets = this.plantRevealAll
            ? this.app.workspace.getLeavesOfType(BROWSER_VIEW).map((l) => l.view as BrowserView)
            : [this.activeBrowser() as BrowserView].filter(Boolean);
          this.revealStats.reveals++;
          this.revealStats.browsers = targets.length;
          this.revealStats.last = url;
          for (const browser of targets) {
            if (browser && typeof browser.reveal === "function") void browser.reveal(url, xpath);
          }
        };
        // Closing a billboard the browser pinned lets the browser drop the
        // pin and its markdown too (`G-78`): one selection, three surfaces.
        view.onPrototype = (cid: string) => this.prototypeToCell(cid);
        view.onOpenCode = (url: string) => this.openCode(url);
        view.onPullToChat = (cid: string) => this.pullToChat(cid);
        view.browsingUrl = () => {
          const l = { view: this.activeBrowser() } as any;
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
    // The code artifact panel (P-C1/P-C2/P-C5): a module's source and its
    // chunks side by side, its own kernel's run surface below.
    this.registerView(CODE_VIEW, (leaf: WorkspaceLeaf) => new CodeView(leaf, this.sidecar));
    this.addCommand({
      id: "domvec-open-code",
      name: "Open the code artifact of the hovered code node",
      callback: () => { const u = (window as any).__domvecLastCodeUrl; if (u) void this.openCode(u); },
    });
    this.addCommand({
      id: "domvec-open-terminal",
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
        (nodes, edges, trace, keep) => {
          this.eachGraph((view) => view.absorb(nodes, edges, trace, keep && keep.size ? { keep } : {}));
        },
        // And so does the ranking (`G-55`, `G-56`): what the reader has
        // scrolled to is what the projector opens the page to.
        (url, cids) => this.eachGraph((view) => void view.showHits(url, cids)));
        // Hovering a chunk in the browser rings its node in the projector
        // (`G-38`). Brokered like everything else across the two panes.
        browser.onRightChunk = (cid: string, url: string, stored: string) => {
          this.eachGraph((view) => view.rightPanel(cid, url, stored));
          // And the CLIPBOARD aggregates it (PLUGIN_GOAL 134h).
          if (stored) void this.clipboardAdd(stored, url);
        };
        // Used = pressed in, or hovered in its page (item 87): the 3D graph
        // follows whichever browser the reader is using.
        browser.containerEl.addEventListener("pointerdown", () => this.touchBrowser(browser), true);
        browser.containerEl.addEventListener("focusin", () => this.touchBrowser(browser), true);
        browser.onHover = (cid: string, url: string, stored?: string) =>
          (this.touchBrowser(browser), this.eachGraph((view) => {
            if (stored) { view.highlightChunk(cid, url, stored); return; }
            // A stored ANCESTOR covers the hovered chunk only roughly -- the
            // tile not yet stored resolved to archive.org's whole search-page
            // container (a hidden feedback survey, 2026-10-17). The grey node
            // with the chunk's exact streamed content wins when it is drawn;
            // the ancestor is the fallback. Planted: `ancestor-over-grey`.
            const cover = browser.storedCoverFor(cid, url);
            const grey = !cover.exact && !browser.plant.has("ancestor-over-grey") && view.hasNode(cid);
            view.highlightChunk(cid, url, grey ? "" : cover.cid);
          }));
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
        browser.onPopup = (popup: string, opener: string, url: string) =>
          this.eachGraph((view) => view.linkPopup(popup, opener, 0, url));
        browser.onPictures = (byCid: Record<string, string>) =>
          this.eachGraph((view) => view.setPictures(byCid));
        // Any billboard opened in 3D can ask for its chunk's page snapshot.
        // **Asked of the browser cell that HOLDS the chunk, not the one built
        // last.** Each cell, as it was built, rewired these to itself, so with
        // three cells open every grey panel asked a cell that had never seen
        // the page: its lines came back empty and the panel was skipped
        // (2026-10-24: "hovering overlays in the browser shows the nodes in
        // the tree form, but the actual panels ... are missing" -- 39 skipped,
        // the reader's cell holding 14 lines for the chunk). Planted
        // `__domvecPlantLastBrowser`: the last-built cell answers, as before.
        // In order: the cell whose pointer is on that chunk, then the cells on
        // screen, then the rest. Grey ids are numbered per cell (`#4` in one
        // is not `#4` in another), and hidden cells left on the same page
        // hold trees for the same url -- the first to answer was not
        // necessarily the cell the reader hovered.
        this.eachGraph((view) => {
          const cells = (cid = ""): any[] => {
            if ((window as any).__domvecPlantLastBrowser) return [browser];
            const all = this.app.workspace.getLeavesOfType(BROWSER_VIEW).map((l) => l.view as any)
              .filter((b) => b && typeof b.forcePayload === "function");
            const base = String(cid).split("|")[0];
            const rank = (b: any) => (base && b.pipebox?.hover?.cid === base ? 0 : (b.containerEl?.offsetWidth || 0) > 0 ? 1 : 2);
            return all.sort((x, y) => rank(x) - rank(y));
          };
          view.snapshotFor = async (cid: string, url: string, again?: boolean) => {
            for (const b of cells(cid)) if (await b.snapshotChunk(cid, url, !!again)) return true;
            return false;
          };
          view.onNavigate = (href: string) => browser.go(href);
          view.forcePayloadFor = (id: string) => {
            for (const b of cells(id)) { const p = b.forcePayload(id); if (p) return p; }
            return null;
          };
          view.hoverElementOf = (cid: string) => {
            for (const b of cells(cid)) { const e = b.hoverElementOf(cid); if (e) return e; }
            return "";
          };
          view.greyUnitFor = (cid: string) => {
            for (const b of cells(cid)) { const g = b.greyUnitFor(cid); if (g) return g; }
            return null;
          };
        });
        browser.onProjected = (url: string, got: any) =>
          this.eachGraph((view) => view.applyProjected(url, got));
        browser.onUnpin = (cid: string) =>
          this.eachGraph((view) => view.unpinChunk(cid));
        return browser;
      },
    );
    this.addCommand({
      id: "domvec-open-browser",
      name: "Open the browser cell",
      callback: () => this.openBrowser(),
    });

    // (The profile pane and its status-bar readout are gone (`G-76`): the
    // pipeline's statistics live in the browser cell's corner box, where the
    // page they describe is, and where the MCP tools read and toggle them.)
    // A layout saved while those panes existed still names them; close
    // those leaves rather than leave "plugin view missing" tabs behind.
    this.app.workspace.onLayoutReady(() => {
      for (const gone of ["domvec-profile-view", "domvec-chunk-view"]) {
        this.app.workspace.detachLeavesOfType(gone);
      }
    });

    this.addRibbonIcon("git-fork", "domvec 3D graph", () => this.openGraph());
    this.addCommand({
      id: "domvec-open-graph",
      name: "Open the 3D graph",
      callback: () => this.openGraph(),
    });

    // Ask the server what it allows, once, at load. A surface drawn before
    // the answer arrives is read-only, which is the safe direction to be
    // wrong in.
    this.sidecar.health().then((h) => { this.serverEnact = !!(h && h.enact); });

    this.addSettingTab(new DomvecSettingTab(this.app, this));
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
    const view = this.activeView();
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
    const still = this.activeView();
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
  /**
   * Panels on the 2D plane (PLUGIN_GOAL 65-66): every note a panel there --
   * Obsidian's own view of it, draggable, minimized to its node -- with the
   * plane's create / delete tools. The craft in 3D rings each one.
   */
  /** G-205: the retrieval artifact's own view -- a card on the plane, not a note. */
  browseCard: BrowseCard = new BrowseCard({
    base: () => String(this.settings.sidecar || "").replace(/\/+$/, ""),
    carry: (a: any) => this.carryToolAsk(a),
    shownUrl: () => { const b: any = this.activeBrowser(); try { return String((typeof b?.shownUrl === "function" ? b.shownUrl() : b?.webview?.getURL()) || ""); } catch { return ""; } },
  });
  openBrowseCard(query = "", scope = "web"): HTMLElement | null {
    const g: any = this.app.workspace.getLeavesOfType(GRAPH_VIEW)[0]?.view;
    const plane = g && typeof g.plane === "function" ? g.plane() : null;
    return plane ? this.browseCard.open(plane, query, scope) : null;
  }
  /** B14 (G-409): a widget edited in place writes that one default into the
   *  note's own cell -- through the open editor when there is one. */
  nodeEdits = { written: 0, reran: 0, last: "" };
  async setNodeDefault(note: string, node: string, port: string, lit: string): Promise<boolean> {
    const f = this.app.vault.getAbstractFileByPath(note);
    if (!(f instanceof TFile)) return false;
    const v = this.markdownLeaves().map((l) => l.view as MarkdownView).find((x) => x?.file?.path === note);
    const text = v?.editor ? v.editor.getValue() : await this.app.vault.read(f);
    const next = port.startsWith("trait:") ? setTraitDefault(text, node, port.slice(6), lit) : setDefault(text, node, port, lit);
    if (next === null || next === text) return false;
    if (v?.editor && v.getMode() === "source") { v.editor.setValue(next); await v.save(); }
    else await this.app.vault.modify(f, next);
    this.nodeEdits.written++; this.nodeEdits.last = `${node}.${port} = ${lit}`;
    // The cell that defines the node runs again, so the kernel holds the new
    // default and the rows are redrawn from it. Planted `__domvecPlantNoEditRerun`.
    if (!(window as any).__domvecPlantNoEditRerun) {
      const def = new RegExp("^[ \\t]*(def|class)[ \\t]+" + node + "\\b", "m");
      const fence = findFences(next).find((c) => /^py/.test(c.lang || "") && def.test(c.body));
      if (fence) { this.nodeEdits.reran++; await this.onRunFence({ lang: fence.lang, code: fence.body, line: fence.openLine, path: note }); }
    }
    return true;
  }

  desk: PlaneDesk = new PlaneDesk(this.app, {
    plane: () => {
      const g: any = this.app.workspace.getLeavesOfType(GRAPH_VIEW)[0]?.view;
      return g && typeof g.plane === "function" ? g.plane() : null;
    },
    changed: () => { const g: any = this.app.workspace.getLeavesOfType(GRAPH_VIEW)[0]?.view; g?.craft?.dirty(); this.cockpit.decorate(); },
    moved: () => { const g: any = this.app.workspace.getLeavesOfType(GRAPH_VIEW)[0]?.view; g?.craft?.replane?.(); },
    // A panel on the plane gets at once what a tab gets from the workspace's
    // layout events, which a leaf outside the tree never fires.
    openBrowser: () => { void this.openBrowserInstance(); },
    headerClick: (path) => { void this.halo.toggle(path); },
    intoCraft: (path) => { const g: any = this.app.workspace.getLeavesOfType(GRAPH_VIEW)[0]?.view; return !!g?.flyToCraft?.(path); },
    chatStream: (prompt: string, ctx: string[], onTok: (t: string) => void, meta?: any) =>
      this.sidecar.chatStream(prompt, ctx, onTok, undefined, meta),
    pins: (path: string) => this.pinsForNote(path),
    pullInto: (from: string, x: number, y: number) => this.pull.into(from, x, y),
    codeNodes: (q: string) => this.sidecar.codeNodes(q),
    typeNodes: (q: string) => this.minedTypes(q),
    openType: (pattern: string) => { void this.typeFromPattern(pattern, this.typeName(pattern)); },
    openBrowse: (q: string, scope?: string) => { this.openBrowseCard(q, scope || "web"); },
    haloQuery: (path, q) => { void this.halo.open(path, q); },
    egoNotes: () => {
      const g: any = this.app.workspace.getLeavesOfType(GRAPH_VIEW)[0]?.view;
      return (g?.craft?.nodes || []).filter((n: any) => n.kind === "note").map((n: any) => n.path);
    },
    opened: (f) => { void this.noteNotebook(f); window.setTimeout(() => { this.applyCellBars(); this.applyHalves(); this.cockpit.decorate(); }, 0); },
  });

  /** Planted (item 99): computation draws no light. */
  plantNoLights = false;
  lightStats = { lit: 0, unlit: 0, now: [] as string[] };
  private lit = new Set<string>();
  light(note: string, on: boolean): void {
    if (this.plantNoLights) return;
    if (on) { this.lit.add(note); this.lightStats.lit++; } else { this.lit.delete(note); this.lightStats.unlit++; }
    this.lightStats.now = [...this.lit];
    this.desk.panelOf(note)?.card.toggleClass("is-computing", on);
    const g: any = this.app.workspace.getLeavesOfType(GRAPH_VIEW)[0]?.view;
    g?.craft?.setLit?.(note, on);
    // A finished run's signal flows on downstream (G-331): the craft's pulse,
    // and each panel it reaches on the plane flashing as it arrives.
    if (!on && g?.craft) {
      // Through the craft as it stands after the run: rebuilt from the open
      // panels' text first, so the readout the run just wrote is a node the
      // signal reaches (bounded: a slow sidecar does not hold the pulse).
      const craft = g.craft;
      void Promise.race([craft.fresh(), new Promise((r) => window.setTimeout(r, 1500))])
        .then(() => this.pulseFrom(craft, note), () => this.pulseFrom(craft, note));
    }
  }
  private pulseFrom(craft: any, note: string): void {
    craft.onPulse = (p: string) => {
      const card = this.desk.panelOf(p)?.card;
      if (!card) return;
      card.addClass("is-pulsed");
      window.setTimeout(() => card.removeClass("is-pulsed"), 450);
    };
    // The run's own panel flashes only when a signal actually leaves it.
    const sent = craft.pulse(note);
    const own = this.desk.panelOf(note)?.card;
    if (sent && own) { own.addClass("is-pulsed"); window.setTimeout(() => own.removeClass("is-pulsed"), 450); }
  }

  /** The halo that slides, on the plane (items 81-84). */
  halo: PlaneHalo = new PlaneHalo({
    app: this.app, desk: this.desk, sidecar: () => this.sidecar,
    plane: () => { const g: any = this.app.workspace.getLeavesOfType(GRAPH_VIEW)[0]?.view; return g && typeof g.plane === "function" ? g.plane() : null; },
  });

  /** Every browser instance on the plane (item 87), the first the default. */
  browserPanels: BrowserPanel[] = [];
  /** A web link clicked inside a domvec panel (a billboard's markdown, a
   *  chunk note, the slate) loads in the BROWSER CELL. Obsidian opens links
   *  with `window.open`, which reached the system browser (2026-11-07: "the
   *  duckduckgo browser opens outside of the plugin"). Elsewhere in Obsidian
   *  links behave as before. Planted `__domvecPlantLinksOut`. */
  linkStats: { to_cell: number; passed: number; code_in?: number } = { to_cell: 0, passed: 0, code_in: 0 };
  private lastPointerIn = false;
  private routeLinksToCell(): void {
    const inPanel = (t: any) => !!(t && t.closest && t.closest(".domvec-bb, .domvec-plane-card, .domvec-browser-md, .domvec-chat, .domvec-cockpit-card, .domvec-code-cell, .domvec-search3d"));
    this.registerDomEvent(document, "mousedown", (e: MouseEvent) => { this.lastPointerIn = inPanel(e.target); }, { capture: true } as any);
    const orig = window.open.bind(window);
    const self = this;
    (window as any).open = function (url?: any, ...rest: any[]) {
      const u = String(url || "");
      // A code:// address is OURS: the module's panel in the app, never the
      // OS (PLUGIN_GOAL 159 screenshot: a notebook's "module repl.model"
      // link raised Windows' "Open external link?" for code://repo/repl/
      // model.py#L1). Planted `__domvecPlantCodeLinksOut`: handed to the OS.
      if (/^code:\/\//i.test(u) && !(window as any).__domvecPlantCodeLinksOut) { void self.openCode(u); self.linkStats.code_in = (self.linkStats.code_in || 0) + 1; return null; }
      if (/^https?:/i.test(u) && self.lastPointerIn && !(window as any).__domvecPlantLinksOut) {
        const b: any = self.activeBrowser();
        if (b && typeof b.go === "function") { b.go(u); self.linkStats.to_cell++; return null; }
      }
      self.linkStats.passed++;
      return orig(url, ...rest);
    };
    this.register(() => { (window as any).open = orig; });
    // An <a href="code://..."> clicked anywhere (reading view, a panel's
    // rendered markdown): the same, before Obsidian's own handler sees it.
    this.registerDomEvent(document, "click", (e: MouseEvent) => {
      const a = (e.target as HTMLElement)?.closest?.("a") as HTMLAnchorElement | null;
      const href = a ? (a.getAttribute("href") || a.dataset.href || "") : "";
      if (!/^code:\/\//i.test(href) || (window as any).__domvecPlantCodeLinksOut) return;
      e.preventDefault(); e.stopPropagation(); e.stopImmediatePropagation();
      void this.openCode(href); this.linkStats.code_in = (this.linkStats.code_in || 0) + 1;
    }, { capture: true } as any);
  }

  /** For the harness: a browser cell on the plane over `path`, its plants set. */
  async openBrowserPanel(path: string, planted = false): Promise<BrowserPanel> {
    const bp = new BrowserPanel(this.app, { browserViewType: BROWSER_VIEW, desk: this.desk }, path);
    bp.plantGoActions = planted; bp.plantNoExit = planted; bp.plantScopeFirstRead = planted;
    this.browserPanels.push(bp);
    await bp.open();
    return bp;
  }

  /** `+ browser`: the default browser if it is not on the plane, else a NEW
   *  instance -- its own cockpit note, its own session. */
  async openBrowserInstance(): Promise<BrowserPanel> {
    if (!this.desk.panelOf(this.browserPanel.path)) { await this.browserPanel.open(); return this.browserPanel; }
    let n = 2;
    while (this.browserPanels.some((b) => b.path === `domvec/browser ${n}.md`) && this.desk.panelOf(`domvec/browser ${n}.md`)) n++;
    const path = `domvec/browser ${n}.md`;
    let bp = this.browserPanels.find((b) => b.path === path);
    if (!bp) { bp = new BrowserPanel(this.app, { browserViewType: BROWSER_VIEW, desk: this.desk }, path); this.browserPanels.push(bp); }
    await bp.open();
    return bp;
  }

  /** The browser the reader is USING (item 87): the one last pressed in or
   *  hovered, of every open browser view -- the standalone pane, the plane's
   *  browsers, a notebook's browser fence. Every 3D feature follows it.
   *  Planted `plantFirstBrowser`: the workspace's first browser, always. */
  plantFirstBrowser = false;
  private browserUsedAt = new Map<any, number>();
  browserStats = { touched: 0, active: "" };
  touchBrowser(v: any): void {
    this.browserUsedAt.set(v, performance.now());
    this.browserStats.touched++;
  }
  activeBrowser(): any {
    const all = this.app.workspace.getLeavesOfType(BROWSER_VIEW).map((l) => l.view as any).filter(Boolean);
    const first = all[0] || null;
    if (this.plantFirstBrowser) return first;
    // A browser ON SCREEN outranks one behind another tab (PLUGIN_GOAL 157:
    // "I had music playing on the other browser tab ... just focus on the
    // browser panel that I was actively having open and was actually showing
    // to the screen"). Among the shown, the last one used; then any.
    const shown = (v: any) => { const el = v?.containerEl; if (!el?.isConnected) return false; const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
    const used = (v: any) => this.browserUsedAt.get(v) ?? -1;
    for (const v of [...this.browserUsedAt.keys()]) if (!v?.containerEl?.isConnected) this.browserUsedAt.delete(v);
    const pick = (vs: any[]) => vs.reduce((b: any, v: any) => (b === null || used(v) > used(b) ? v : b), null);
    const active = this.app.workspace.getActiveViewOfType?.(BrowserView as any) as any;
    if (active && shown(active)) return active;
    return pick(all.filter(shown)) || pick(all) || first;
  }

  /** Planted: a graph click reveals in EVERY browser leaf, as before 2026-11-14. */
  plantRevealAll = false;
  revealStats = { reveals: 0, browsers: 0, last: "" };

  /** The browser cell as a panel on the plane, with its cockpit (item 71). */
  browserPanel: BrowserPanel = new BrowserPanel(this.app, { browserViewType: BROWSER_VIEW, desk: this.desk });

  /** Every markdown leaf showing a note: the workspace's, the plane's panels
   *  and the docked cockpit -- one list, so a run's output, the cell strip and
   *  the marks reach a note wherever it is open. */
  markdownLeaves(): any[] {
    const out: any[] = this.app.workspace.getLeavesOfType("markdown");
    for (const l of this.desk.leaves()) if (!out.includes(l)) out.push(l);
    const c = this.cockpit?.planeLeaf;
    if (c && this.cockpit.card?.isConnected && !out.includes(c)) out.push(c);
    return out;
  }

  /** The note view the reader is in: the plane panel they last touched when
   *  that was after the workspace's last leaf change, else the active tab. */
  private wsActiveAt = 0;
  activeView(): MarkdownView | null {
    const pv = this.desk.focusedView();
    if (pv && this.desk.focusedAt >= this.wsActiveAt) return pv;
    return this.app.workspace.getActiveViewOfType(MarkdownView) || pv;
  }

  /** The notebook the reader is in: where a prototype cell goes (G-105). Read
   *  from the FILE: a note opened into the active tab fires `file-open` and
   *  no leaf change, before its editor holds the text. */
  async noteNotebook(file: TFile | null | undefined): Promise<void> {
    if (!file || file.extension !== "md") return;
    if (/^\s*(`{3,}|~{3,})\s*(python|py)\b/m.test(await this.app.vault.cachedRead(file))) this.lastNotebook = file.path;
  }

  /** The `ego` slate, bound to the agent and the search (G-280). */
  cockpit: Cockpit = new Cockpit(this.app, {
    graph: () => this.app.workspace.getLeavesOfType(GRAPH_VIEW)[0]?.view as any,
    ref: (name: string) => this.sidecar.ref(name),
    webSearch: (q: string) => {
      const browser = this.activeBrowser() as BrowserView | undefined;
      if (!browser || typeof browser.searchWeb !== "function") return false;
      void browser.searchWeb(q);
      // The slate's web branch: the browser cell is an input of the search node (G-372).
      const g: any = this.app.workspace.getLeavesOfType(GRAPH_VIEW)[0]?.view;
      if (g) g.webInputFor = q;
      return true;
    },
  });

  /**
   * The ROLLOUT (G-283; RESERVOIR_DESIGN §4; UR N.9, O.11, E.7): ▶▶ on a cell
   * runs it once per sample of its first `{ref}` -- the sidecar binds that ref
   * to one chunk a run -- so its output block shows ONE current readout and
   * every sample's run is recorded with its own chunk as input, the signal
   * pulsing in 3D per sample. ▶▶ again pauses; the next ▶▶ resumes where it
   * stopped. Planted `__domvecPlantNoRollout`: one run, no samples.
   */
  rollouts = new Map<string, { at: number; playing: boolean; samples: number }>();
  rolloutStats = { plays: 0, samples: 0, finished: 0, paused: 0 };
  rolloutPaceMs = 400;
  async onRolloutFence(req: RunRequest): Promise<void> {
    const note = req.path || this.app.workspace.getActiveFile()?.path || "";
    const key = note + "|" + req.line;
    const r = this.rollouts.get(key) || { at: 0, playing: false, samples: -1 };
    if (r.playing) { r.playing = false; this.rolloutStats.paused++; return; }
    r.playing = true;
    this.rollouts.set(key, r);
    this.rolloutStats.plays++;
    while (r.playing) {
      if ((window as any).__domvecPlantNoRollout) { await this.onRunFence(req); r.playing = false; break; }
      const reply: any = await this.onRunFence({ ...req, sample: r.at });
      const b = (reply && reply.bound && reply.bound[0]) || null;
      if (!b || typeof b.samples !== "number") { r.playing = false; break; }
      r.samples = b.samples;
      if (b.done) { r.playing = false; r.at = 0; this.rolloutStats.finished++; break; }
      this.rolloutStats.samples++;
      r.at++;
      if (r.at >= r.samples) { r.playing = false; r.at = 0; this.rolloutStats.finished++; break; }
      await new Promise((res) => window.setTimeout(res, this.rolloutPaceMs));
    }
  }

  /** The editor's own calls from a cell -- create, link, invoke, commit, review (G-386). */
  editor: EditorCalls = new EditorCalls(this as any);
  /** Marimo-style & cross-notebook DAG re-runs: a cell's readers run after it (`G-380`, `G-451`). */
  dataflow: DataflowRun = new DataflowRun(
    this as any,
    (p: string) => noteTextOf(this.app, p, () => this.markdownLeaves().map((l) => l.view)),
    (p, marks) => { markProblems(this.markdownLeaves().map((l) => l.view), p, marks); },
    async (focusPath: string) => this.collectWorkspaceNotes(focusPath),
  );

  /** Gather computation-graph markdown notes for cross-notebook DAG compilation (`G-451`). */
  async collectWorkspaceNotes(focusPath = ""): Promise<Record<string, string>> {
    const out: Record<string, string> = {};
    const views = this.markdownLeaves().map((l) => l.view as MarkdownView);
    const checkPrefix = focusPath.startsWith("domvec-checks/") ? focusPath.split("/").slice(0, 2).join("/").replace(/\.md$/i, "").split(" ").slice(0, 2).join(" ") : "";
    for (const f of this.app.vault.getMarkdownFiles()) {
      const p = f.path;
      if (p === COCKPIT_PATH || p === "domvec/clipboard.md") continue;
      const inScope = p === focusPath
        || p.startsWith(PLANE_FOLDER + "/")
        || !!this.desk.panelOf(p)
        || views.some((v) => v?.file?.path === p)
        || (checkPrefix && p.startsWith(checkPrefix));
      if (!inScope) continue;
      const openV = views.find((v) => v?.file?.path === p);
      out[p] = openV?.editor ? openV.editor.getValue() : await this.app.vault.cachedRead(f);
    }
    return out;
  }

  chatHostCtx(): ChatCellHost {
    return {
      pins: (path) => this.pinsForNote(path),
      extra: (path) => this.desk.chatContext(path),
      systemPrompt: () => this.cockpit.egoSystemPrompt(),
      markdownViews: () => this.markdownLeaves().map((l) => l.view),
      onToolReply: (path, reply) => this.execReplyTools(path, reply),
    };
  }

  /** Execute ```tool blocks emitted in a chat reply in-place (`G-453`). */
  async execReplyTools(path: string, reply: string): Promise<void> {
    const bodies = extractReplyToolBodies(reply);
    if (!bodies.length) return;
    const base = String(this.settings.sidecar || "").trim().replace(/\/+$/, "");
    if (!base) return;
    const f = this.app.vault.getAbstractFileByPath(path);
    for (const src of bodies) {
      try {
        const res = await fetch(`${base}/tool_cell`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session: `${path}#tool`, source: src }),
        });
        const state = await res.json();
        for (const a of state?.asks || []) await this.carryAnyAsk(a, path);
        if (f instanceof TFile && state?.history_line) {
          await writeToolStepToNote(this.app, f, -1, null, state.history_line);
        }
      } catch { /* sidecar unreachable */ }
    }
  }

  /** Unified ask dispatcher across editor calls, browser, chat, terminal, and toolspaces (`G-452`, `G-453`). */
  async carryAnyAsk(a: any, fromNote = ""): Promise<string> {
    if (!a || typeof a !== "object") return "";
    const said = await this.editor.carry(a);
    if (said) return said;
    if (typeof a.web === "string" && a.web.trim()) {
      this.askStats.web++;
      this.askStats.last = a.web;
      const browser = this.activeBrowser() as BrowserView | undefined;
      if (browser && typeof browser.searchWeb === "function") {
        void browser.searchWeb(a.web);
        return `web: "${a.web}" asked of the browser cell`;
      }
      return `web: no browser cell open for "${a.web}"`;
    }
    if (typeof a.go === "string" && a.go.trim()) {
      this.askStats.go = (this.askStats.go || 0) + 1;
      this.askStats.last = a.go;
      const browser = this.activeBrowser() as BrowserView | undefined;
      if (browser && typeof (browser as any).go === "function" && !this.plantNoBrowserAsk) {
        (browser as any).go(a.go);
        return `go: the browser sent to ${a.go}`;
      }
      return `go: no browser cell open for ${a.go}`;
    }
    if (typeof a.open_note === "string" && a.open_note.trim()) {
      const nf = this.app.vault.getAbstractFileByPath(a.open_note) || this.app.metadataCache.getFirstLinkpathDest(a.open_note, fromNote);
      if (nf instanceof TFile) {
        await this.desk.open(nf);
        return `opened ${nf.path}`;
      }
      return `no note ${a.open_note}`;
    }
    if (typeof a.terminal_run === "string" && a.terminal_run.trim()) {
      await this.sidecar.runCommand(fromNote || "tool-cell", a.terminal_run);
      return `terminal: ${a.terminal_run.slice(0, 48)}`;
    }
    if (a.chat_send && typeof a.chat_send === "object") {
      const targetNote = String(a.chat_send.note || fromNote || "").trim();
      const prompt = String(a.chat_send.prompt || "").trim();
      const sys = typeof a.chat_send.system === "string" ? a.chat_send.system : undefined;
      if (targetNote && prompt) {
        await streamPromptIntoNote(
          this.app,
          targetNote,
          prompt,
          (p, c, on, sig, meta) => this.sidecar.chatStream(p, c, on, sig, meta),
          this.chatHostCtx(),
          sys,
        );
        return `chat: streamed to ${targetNote}`;
      }
    }
    return this.carryToolAsk(a);
  }
  /** A code card's typed rows as fields on its plane card (G-378). */
  codeRows: CodeRows = new CodeRows(this as any);
  /** A cell's asks of the app, carried out (G-288). */
  askStats: { web: number; go?: number; last: string } = { web: 0, last: "" };
  /** Planted (G-279): the kernel's `WebBrowser.go` asks are not carried out. */
  plantNoBrowserAsk = false;

  /** Edits re-run (194): a pause in a python cell runs it and its readers. */
  autoRun!: AutoRun;
  crossRun!: CrossRun;
  toolRun!: ToolRun;
  /** Named extension slots over the core (G-240). */
  slots: Slots = new Slots(() => ((this as any).settings?.disabledExtensions as string[]) || []);
  async onRunFence(req: RunRequest): Promise<any> {
    const note = req.path || this.app.workspace.getActiveFile()?.path || "";
    if (!note) {
      new Notice("domvec: cannot run a cell outside a note — " +
                 "the note is the kernel's isolation boundary", 6000);
      return;
    }

    const isQuiet = !!(req as any).quiet;
    const running = isQuiet ? null : new Notice(`domvec: running ${req.lang}…`, 0);
    let reply;
    // The computation, LIT while it runs (PLUGIN_GOAL 99): the panel's header
    // node on the plane, the craft's node in 3D -- the same moment.
    this.light(note, true);
    try {
      // The cell's `{ref}` inputs (G-279). Planted `__domvecPlantNoRefs`: none sent.
      const refs = (window as any).__domvecPlantNoRefs ? [] : (req.refs || []);
      // The note's own text: its markdown TREES are compiled into the kernel
      // first (PLUGIN_GOAL 62, 63': the extended markdown cell), so a code
      // cell sees the names the markdown binds.
      const nf = this.app.vault.getAbstractFileByPath(note);
      // The EDITOR's text when the note is open (on the plane or in a tab):
      // the file lags the editor by its autosave, and a tree typed a moment
      // before the run was not yet there -- the cell met NameError (G-298).
      const openView = this.markdownLeaves().map((l) => l.view as MarkdownView).find((v) => v?.file?.path === note);
      const markdown = openView?.editor ? openView.editor.getValue()
        : nf instanceof TFile ? await this.app.vault.cachedRead(nf) : "";
      // The note's I/O toggle (item 79): its inputs from the ego or the web.
      const maps = nf instanceof TFile ? String(this.app.metadataCache.getFileCache(nf)?.frontmatter?.maps || "") : "";
      // Cross-notebook upstream cells in topological order (`G-451`).
      const upstream = /^py/i.test(req.lang || "python") ? await this.dataflow.upstreamFor(note, req.line) : [];
      reply = await this.sidecar.runCell(note, req.code, req.lang, refs, req.line, req.sample, markdown, maps, upstream);
    } finally {
      running?.hide();
      this.light(note, false);
    }

    if (!reply) {
      new Notice(`domvec: no sidecar at ${this.settings.sidecar || "(unset)"} ` +
                 "— cannot run cells", 6000);
      return;
    }
    if (reply.error && reply.ok === undefined) {
      // The server refused rather than the cell failing: 403 when the kernel is
      // off, 400 when the request was wrong. Both carry a `detail` that says
      // what to do, and showing it is the difference between "off" and "broken".
      new Notice(`domvec: ${reply.error}` +
                 (reply.detail ? ` — ${reply.detail}` : ""), 9000);
      return;
    }

    // Whenever the namespace is not the one the previous cell left, say so. A
    // silently-empty variable reads as a bug in the reader's own code.
    const notes: string[] = [];
    if (reply.kernel) notes.push(reply.kernel);
    if (reply.evicted) notes.push(`retired ${reply.evicted}'s kernel`);

    const stored = await this.storeOutput(note, req, reply);
    // G-409: the nodes this note now defines, with their ports, at its card's foot.
    if (/^py/.test(req.lang || "python")) {
      void this.sidecar.nodeDefs(note).then((r) => {
        if (!r || !Array.isArray(r.defs)) return;
        nodeDefs[note] = r.defs;
        drawDefs((this as any).desk?.panelOf?.(note)?.card, r.defs, (node, port, lit) => void this.setNodeDefault(note, node, port, lit));
      });
    }
    if (stored) notes.push(stored);
    // The run's signal flow drawn in 3D as it fires (G-292): its recorded
    // inputs -> this cell's note, pulsing.
    if (reply.run) {
      void this.sidecar.runsOf(note).then((got) => {
        const r = got && got.runs && got.runs.find((x: any) => x.rid === reply.run);
        const g = this.app.workspace.getLeavesOfType(GRAPH_VIEW)[0]?.view as any;
        if (r && g && typeof g.signalRun === "function") g.signalRun(note, r.inputs || []);
      });
    }
    // What the cell asked of the app (G-288): `search(..., duckduckgo=True)`
    // asks the BROWSER CELL's web search, the same path as the 3D search
    // button's -- the kernel never fetches the web itself.
    for (const a of (reply.asks || []) as any[]) {
      const said = await this.carryAnyAsk(a, note);
      if (said) notes.push(said);
    }

    // Its readers, re-run (G-380, G-451): the cells (same note + downstream notebooks) that read the names this one defines.
    const reran = await this.dataflow.after({ ...req, path: note }, reply);
    if (reran) notes.push(reran);

    const last = (reply.error || "").trim().split("\n").pop();
    const shown = reply.ok
      ? ([reply.stdout, reply.stderr, reply.value ?? ""]
          .filter((s) => s && s.trim()).join("\n").trim() || "ok, no output")
      : (last || "failed");
    if (!isQuiet) {
      new Notice(`domvec [${reply.count ?? "?"}] ${shown}` +
                 (notes.length ? `\n(${notes.join("; ")})` : ""), 8000);
    }
    return reply;
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
    const place = (text: string): string => {
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
    };
    try {
      // **Into the open editor when there is one.** A note open in an editor
      // has two copies, the file and the editor's text, and a write to the
      // FILE races the editor's autosave: a cell typed and run at once
      // printed 42 and kept nothing, the editor's save of the older text
      // landing after ours (2026-10-25, `+ code`, P-M4) -- and a save forced
      // first did not close it. So the output is an edit in the editor (the
      // changed span only, so the cursor and undo history survive), and the
      // editor's own save persists it. Planted `__domvecPlantFileOutput`.
      const open = (window as any).__domvecPlantFileOutput ? undefined
        : this.markdownLeaves().map((l) => l.view as MarkdownView)
            .find((v) => v?.file?.path === note && v.getMode() === "source");
      if (open) {
        const ed = open.editor;
        const before = ed.getValue();
        const after = place(before);
        if (after !== before) {
          let a = 0;
          while (a < before.length && a < after.length && before[a] === after[a]) a++;
          let b = 0;
          while (b < before.length - a && b < after.length - a
                 && before[before.length - 1 - b] === after[after.length - 1 - b]) b++;
          ed.replaceRange(after.slice(a, after.length - b), ed.offsetToPos(a), ed.offsetToPos(before.length - b));
        }
        return outcome;
      }
      // `process` is read-modify-write under one lock. `read` then `modify`
      // would drop whatever the reader typed in between, which for a slow cell
      // is a real window and loses THEIR work rather than ours.
      await this.app.vault.process(file, place);
    } catch (err) {
      outcome = `output not stored: ${
        err instanceof Error ? err.message : String(err)}`;
    }
    return outcome;
  }

  /** The notebook chats, one per open notebook view (L-2). */
  nbChats: NotebookChats | null = null;
  marks!: NoteMarks;

  onunload() {
    // The craft global names THIS instance's craft or a dead one's: either
    // way it ends here (G-356 read a craft two reloads old while the new
    // view, with no graph, had none).
    (window as any).__domvecCraft = null;
    this.nbChats?.destroy();
    this.cockpit?.unload();
    this.desk?.unload();
    // The plane's browser cells hold leaves made OUTSIDE the workspace (a
    // card's own leaf), which Obsidian never detaches: each reload left the
    // old view ticking against a detached webview, throwing every interval
    // (2026-11-07, found moving the graph tab). Ours to release.
    if (!(window as any).__domvecPlantKeepPanelLeaves) {
      for (const bp of [this.browserPanel, ...(this.browserPanels || [])]) { try { bp?.browserLeaf?.detach(); } catch { /* gone */ } }
    }
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
      try { fn(view); } catch (err) { console.error("domvec: a graph pane failed", err); }
    }
  }

  /** Put a browser cell in a pane, reusing one if it is already open. */
  /** `+ browser cell`: a browser cell IN the note (G-36), on the page the
   *  standalone cell shows, or a search page when there is none. */
  async addBrowserCell(view: MarkdownView): Promise<void> {
    const file = view.file;
    if (!file) return;
    let url = "https://duckduckgo.com/";
    try {
      const b: any = this.activeBrowser();
      const u = b?.webview?.getURL?.();
      if (u && /^https?:/.test(u)) url = u;
    } catch { /* the standalone cell is not attached */ }
    const NL = "\n", F = "```";
    await this.app.vault.process(file, (t) => t.replace(/\s*$/, "") + NL + NL + F + BROWSER_FENCE + NL + url + NL + F + NL);
  }

  async openBrowser(): Promise<void> {
    // The workspace's own browser leaves: a notebook cell is registered with
    // the lookup (D-54) but lives in a note, not in the tree to reveal.
    const existing = this.app.workspace.getLeavesOfType(BROWSER_VIEW).filter((l: any) => !l.__domvecHosted);
    if (existing.length) {
      this.app.workspace.revealLeaf(existing[0]);
      return;
    }
    const leaf = this.app.workspace.getLeaf("split", "vertical");
    await leaf.setViewState({ type: BROWSER_VIEW, active: true });
    this.app.workspace.revealLeaf(leaf);
  }

  /**
   * A chunk panel pulled into the chat of the notebook the reader was last in
   * (P-N7): pinned there, sent with its next prompt at most once.
   */
  pullStats = { pulled: 0, last: null as any };
  async pullToChat(cid: string): Promise<{ path: string; pins: number } | { error: string }> {
    const leaf = this.markdownLeaves().find((l) => (l.view as MarkdownView).file?.path === this.lastNotebook);
    const chat = leaf ? this.nbChats?.forView(leaf.view as MarkdownView) : null;
    if (!chat) { new Notice("domvec: open a notebook to pull a chunk into its chat"); return { error: "no notebook open" }; }
    const p: any = await this.sidecar.chunk(cid);
    if (!p) return { error: "no such chunk" };
    const pins = chat.pin({ cid, url: p.url || "", markdown: (p.lines || []).map((l: any) => l.text || "").join("\n"),
                            head: "pulled in from the 3D view" });
    this.pullStats.pulled++;
    this.pullStats.last = { cid, path: this.lastNotebook, pins };
    return { path: this.lastNotebook, pins };
  }

  /** A code module in its artifact panel, one pane per module. */
  async openCode(url: string): Promise<CodeView | null> {
    for (const leaf of this.app.workspace.getLeavesOfType(CODE_VIEW)) {
      if (leaf.view instanceof CodeView && leaf.view.url === url) { this.app.workspace.revealLeaf(leaf); return leaf.view; }
    }
    const leaf = this.app.workspace.getLeaf("tab");
    await leaf.setViewState({ type: CODE_VIEW, active: true, state: { url } });
    this.app.workspace.revealLeaf(leaf);
    const v = leaf.view;
    if (v instanceof CodeView && v.url !== url) await v.openUrl(url);
    return v instanceof CodeView ? v : null;
  }

  async openTerminal(): Promise<TerminalView | null> {
    const leaf = this.app.workspace.getLeaf("split", "horizontal");
    await leaf.setViewState({ type: TERMINAL_VIEW, active: true });
    this.app.workspace.revealLeaf(leaf);
    return leaf.view instanceof TerminalView ? leaf.view : null;
  }

  /** `P-N3`: a code cell to a command terminal in a NEW pane beside the note
   *  (§4a). The kernel still runs it in place with ▶ run; both at once is two
   *  panes, which needs no layout of its own. */
  terminalStats = { opened: 0, ran: 0 };
  /** G-234: a vault code cell in the code artifact panel -- editable, saved
   *  back into its fence, run in its notebook's own kernel. */
  async onOpenFence(req: RunRequest): Promise<void> {
    if (req.path && req.line >= 0) await this.openCode("cell:" + req.path + "#" + req.line);
  }

  /**
   * **Unnest where the reader selects** (PLUGIN_GOAL 112, G-329): a cell, or
   * the selection in any note -- a dotted name alone read as `import name` --
   * becomes a BLACK-BOX panel on the plane: its imports as `{code://...}`
   * boxes that unnest, field by field (the slate's own recursive reveal), into
   * their library modules and those modules' imports, down to the compiled
   * base modules; its definitions as typed rows. The panel links back to its
   * source note, so the containment gesture (G-327) can gather it there.
   * Planted `plantUnnestFlat`: the rows as plain text, nothing to unnest.
   */
  plantUnnestFlat = false;
  /** Planted (G-305): the reader's prompts are not kept as ego artifacts. */
  plantPromptsUnkept = false;
  promptStats = { kept: 0, last: null as any };
  /** Planted (159 chat cells): a turn lives only in the prompts index, as before. */
  plantChatOneNote = false;
  chatCellStats = { turns: 0, last: null as any };
  unnestStats = { made: 0, last: null as any };
  /** A python block's typed rows under it, wherever it is drawn (182). */
  onRowsFence(pre: HTMLElement, req: RunRequest): Promise<void> {
    return this.codeRows.mountUnder(pre, { path: req.path, line: req.line }, req.code);
  }

  pull: PullApart = new PullApart(this.app, () => this.desk || null);
  async onCompleteFence(req: RunRequest): Promise<void> {
    if (!req.path) return;
    await completeCell(this.app, {
      search: async (q) => ((await this.sidecar.search(q, { k: 4 }))?.hits || []).map((h: any) => ({ url: h.url, preview: h.preview || "" })),
      stream: (p, c, on) => this.sidecar.chatStream(p, c, on),
      viewOf: (p) => this.markdownLeaves().map((l: any) => l.view).find((v: any) => v?.file?.path === p) || this.desk.viewOf(p),
    }, req.path, req.line, req.code);
  }

  async onPullFence(req: RunRequest): Promise<void> {
    if (req.path) await this.pull.out(req.path, req.line);
  }

  async onUnnestFence(req: RunRequest): Promise<void> {
    if (req.path) await this.unnest(req.code, req.path, "cell " + (req.line + 1));
  }
  async unnestSelection(): Promise<string | null> {
    const v = this.activeView();
    if (!v?.file) return null;
    const sel = v.editor?.getSelection?.() || "";
    if (!sel.trim()) return null;
    return this.unnest(sel, v.file.path, "selection");
  }
  async unnest(source: string, from: string, where: string): Promise<string | null> {
    const name = source.trim();
    const src = /^[A-Za-z_][\w.]*$/.test(name) ? "import " + name : source;
    const got = await this.sidecar.unfoldSource("cell://" + from + "#" + where, src);
    if (!got || !got.lines) { new Notice("domvec: nothing to unnest (not python?)"); return null; }
    const NL = "\n";
    const base = from.split("/").pop()!.replace(/\.md$/, "");
    // Underscores inside a ref are escaped: the slate is markdown, and
    // `__init__` drew as "init" in bold (G-332's frame). `/ref` unescapes.
    const rows = got.lines.map((l) => this.plantUnnestFlat ? l.replace(/[{}]/g, "")
      : l.replace(/\{([^}]+)\}/g, (_m: string, r: string) => "{" + r.replace(/_/g, "\\_") + "}"));
    const folder = "domvec/graph";
    if (!this.app.vault.getAbstractFileByPath(folder)) await this.app.vault.createFolder(folder);
    let path = `${folder}/unnest ${base} ${where}.md`.replace(/[\\:*?"<>|#]/g, " ");
    for (let n = 2; this.app.vault.getAbstractFileByPath(path); n++) path = `${folder}/unnest ${base} ${where} ${n}.md`.replace(/[\\:*?"<>|#]/g, " ");
    const text = "---" + NL + "domvec: slate" + NL + "---" + NL + "# unnest " + where + " of " + mdLink(from) + NL + NL + rows.join(NL) + NL;
    const file = await this.app.vault.create(path, text);
    await this.desk.open(file);
    this.unnestStats.made++;
    this.unnestStats.last = { path, from, where, rows: rows.length, boxes: rows.filter((r) => /\{code:\/\//.test(r)).length };
    return path;
  }

  async onTerminalFence(req: RunRequest): Promise<void> {
    const term = await this.openTerminal();
    if (!term) return;
    this.terminalStats.opened++;
    this.terminalStats.ran += await term.runCell(req.lang, req.code);
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
      new Notice(`domvec: no exported note for ${cid.slice(0, 8)}`);
      return;
    }
    await this.app.workspace.getLeaf(false).openFile(file);
  }

  // ---- a supervisor that gave up, replaced -----------------------------------
  // ---- a chunk note's two halves (D-3) --------------------------------------
  //
  // One half on show per NOTE, whichever leaf shows it, and kept across the
  // fence's redraws (live preview rebuilds a widget on every edit near it).
  // Planted `__domvecPlantNoHalves`: a chunk note is treated as any other, so
  // its fence draws the read-only markdown and the body stays on show -- the
  // defect as it was.
  noteHalves = new Map<string, boolean>();
  halvesStats = { applied: 0, leaves: 0 };
  noteHalf = {
    get: (path: string) => this.noteHalves.get(path),
    set: (path: string, card: boolean) => {
      this.noteHalves.set(path, card);
      for (const s of this.surfaces) if (s.note === path) s.showHalf(card);
      this.applyHalves();
    },
  };

  isChunkNote(path: string): boolean {
    if ((window as any).__domvecPlantNoHalves) return false;
    const f = this.app.vault.getAbstractFileByPath(path);
    const fm = f instanceof TFile ? this.app.metadataCache.getFileCache(f)?.frontmatter : null;
    return !!fm && fm.domvec === "chunk";
  }

  applyHalves(): void {
    let leaves = 0;
    for (const leaf of this.markdownLeaves()) {
      const view = leaf.view as MarkdownView;
      const path = view?.file?.path;
      if (!path) continue;
      const chunk = this.isChunkNote(path);
      const card = chunk ? (this.noteHalves.get(path) ?? this.settings.interactiveByDefault) : false;
      view.containerEl.toggleClass("domvec-half-card", chunk && card);
      view.containerEl.toggleClass("domvec-half-md", chunk && !card);
      // @ts-ignore -- `editor.cm` is the CM6 EditorView; Obsidian does not type it.
      const cm = view.editor?.cm as EditorView | undefined;
      if (cm && bodyHidden(cm) !== (chunk && card)) cm.dispatch({ effects: setBodyHidden.of(chunk && card) });
      if (chunk) leaves++;
    }
    this.halvesStats.applied++;
    this.halvesStats.leaves = leaves;
  }

  // ---- structural cells at the bottom of the note (P-M4) ------------------
  //
  // Planted `__domvecPlantNoCellBar`: no strip anywhere.
  cellBarStats = { placed: 0, code_cells: 0, chat_cells: 0 };

  /** Pinned web chunks for a note's chat session: any notebook browser cell in
   *  `path`, a matching plane BrowserPanel, and the active browser (`G-444`). */
  pinsForNote(path: string): { cid: string; url: string; title?: string; markdown: string }[] {
    const seen = new Set<string>();
    const out: { cid: string; url: string; title?: string; markdown: string }[] = [];
    const pushFrom = (bv: any) => {
      if (!bv || typeof bv.pinnedChunks !== "function") return;
      for (const p of bv.pinnedChunks()) {
        if (p && p.cid && !seen.has(p.cid)) { seen.add(p.cid); out.push(p); }
      }
    };
    for (const nb of notebookBrowsers) {
      if (nb.sourcePath === path) pushFrom(nb.view);
    }
    for (const bp of this.browserPanels || []) {
      if (bp.path === path) pushFrom(bp.view());
    }
    pushFrom(this.activeBrowser());
    return out;
  }

  applyCellBars(): void {
    const on = !(window as any).__domvecPlantNoCellBar;
    let placed = 0;
    for (const leaf of this.markdownLeaves()) {
      const view = leaf.view as MarkdownView;
      if (view?.file && ensureCellBar(view, this, on)) placed++;
    }
    this.cellBarStats.placed = placed;
  }

  /** The notebook the reader was last in: a note holding a python cell. */
  lastNotebook = "";
  prototypeStats = { made: 0, last: null as any };

  /**
   * A package chunk as a code prototype in a notebook cell (`G-105`, Addendum
   * IX: "bringing these chunks into code prototypes in jupyter python cells on
   * a notebook"). The chunk's function or class comes from the trie
   * (`/prototype`) and is appended to the notebook the reader was last in --
   * or `Prototypes.md` -- as a python cell headed by a link back to its
   * address, where the cell's own run button runs it in the kernel.
   */
  async prototypeToCell(cid: string): Promise<{ path: string; name: string; code_lines: number } | { error: string }> {
    const p = await this.sidecar.prototype(cid);
    if (!p || p.error) return { error: (p && p.error) || "the sidecar did not answer" };
    if (!p.code) return { error: "no code under " + p.scope };
    const NL = "\n", F = "```";
    const doc = (p.docstring || "").split(NL)[0].trim();
    // Its module's names first (the trie holds the imports as links, not
    // text): the prototype is an editable copy that runs as it did at home.
    const home = p.module
      ? "import importlib as _il; globals().update({k: v for k, v in vars(_il.import_module(" + JSON.stringify(p.module)
        + ")).items() if not k.startswith(\"__\")})  # " + p.module + "'s names" + NL
      : "";
    const block = NL + NL + "### " + (p.name || p.scope) + " -- [" + p.url.replace(/^code:\/\//, "") + " " + p.scope + "](" + p.url + ")" + NL
      + (doc ? NL + "> " + doc + NL : "") + NL + F + "python" + NL + home + p.code.replace(/\s+$/, "") + NL + F + NL;
    let path = this.lastNotebook;
    let file: any = path ? this.app.vault.getAbstractFileByPath(path) : null;
    if (!file) {
      path = "Prototypes.md";
      file = this.app.vault.getAbstractFileByPath(path) || await this.app.vault.create(path, "# Prototypes" + NL);
    }
    await this.app.vault.process(file, (t) => t.replace(/\s*$/, "") + block);
    const out = { path, name: p.name, code_lines: p.code.split(NL).length };
    this.prototypeStats.made++;
    this.prototypeStats.last = out;
    new Notice("prototype " + (p.name || p.scope) + " -> " + path);
    return out;
  }

  /** `+ code`: a python fence at the end of the note, the cursor inside it.
   *  In reading view the note is appended to and switched to editing, so the
   *  new cell is where the reader's next keystroke goes. */
  async addCodeCell(view: MarkdownView): Promise<void> {
    const file = view.file;
    if (!file) return;
    const NL = "\n";
    const FENCE = "```";
    if (view.getMode() !== "source") {
      await this.app.vault.process(file, (t) => t.replace(/\s*$/, "") + NL + NL + FENCE + "python" + NL + NL + FENCE + NL);
      await view.leaf.setViewState({ type: "markdown", state: { file: file.path, mode: "source", source: false } });
    }
    const ed = (view.leaf.view as MarkdownView).editor;
    const text = ed.getValue();
    const trimmed = text.replace(/\s*$/, "");
    if (!trimmed.endsWith(FENCE + "python" + NL + NL + FENCE)) {
      ed.replaceRange(NL + NL + FENCE + "python" + NL + NL + FENCE + NL, ed.offsetToPos(trimmed.length), ed.offsetToPos(text.length));
    }
    const at = ed.getValue().replace(/\s*$/, "").length - (NL + FENCE).length;
    ed.setCursor(ed.offsetToPos(at));
    ed.focus();
    this.cellBarStats.code_cells++;
  }

  /** `+ chat` (`G-443`): standardized chat cell button in `cellbar.ts` across all cells. */
  async addChatCell(view: MarkdownView): Promise<void> {
    const file = view.file;
    if (!file) return;
    if (view.getMode() !== "source") {
      await ensureChatFence(this.app, null, file.path);
      await view.leaf.setViewState({ type: "markdown", state: { file: file.path, mode: "source", source: false } });
    }
    await ensureChatFence(this.app, view.containerEl, file.path);
    this.cellBarStats.chat_cells++;
  }

  // ---- workspaces, per vault (PLUGIN_GOAL 144) ----------------------------
  //
  // A workspace is the sidecar's whole state: the trie store, the fits, the
  // caches, the logs. "New project, fresh, without all the inheritance": a new
  // workspace is an empty folder under THIS vault's `.domvec/workspaces/`, and
  // the sidecar is restarted on it. The list lives in the plugin's data, which
  // Obsidian keeps per vault, so another vault never sees this one's.
  workspaceStats = { switched: 0, created: 0, last: null as any };
  workspaceRoot(): string {
    const req = (window as any).require, path = req("path");
    const base = (this.app.vault.adapter as any).getBasePath?.() || "";
    return path.join(base, ".domvec", "workspaces");
  }
  /** Names known to this vault, the running sidecar's own included. */
  workspaceList(): Record<string, string> {
    const out: Record<string, string> = { ...(this.settings.workspaces || {}) };
    const L = this.settings.sidecarLaunch;
    if (L?.workspace && !Object.values(out).includes(L.workspace)) {
      const req = (window as any).require, path = req("path");
      out[path.basename(L.workspace)] = L.workspace;
    }
    return out;
  }
  // ---- new vaults (PLUGIN_GOAL 147) -----------------------------------------
  //
  // "Opening new vaults should automatically have our plugin installed and
  // sidecar run available." Obsidian has no event for a vault being made, so
  // every running copy watches Obsidian's own vault list and installs into a
  // vault whose `.obsidian` folder is NEWER than the moment this rule first ran
  // (minus two hours, to catch the vault that prompted it). Older vaults are
  // the reader's own and are never touched. Installing = the built files, the
  // id in `community-plugins.json`, and community plugins switched on for that
  // vault (Obsidian keeps that per vault in its local storage).
  autoInstallStats = { scans: 0, installed: [] as string[], skipped_old: 0, errors: 0 };
  installIntoNewVaults(): void {
    const req = (window as any).require;
    let fs: any, path: any;
    try { fs = req("fs"); path = req("path"); } catch { return; }
    this.autoInstallStats.scans++;
    const SINCE = "domvec-autoinstall-since";
    let since = Number(window.localStorage.getItem(SINCE) || 0);
    if (!since) { since = Date.now() - 2 * 3600 * 1000; window.localStorage.setItem(SINCE, String(since)); }
    const appdata = (window as any).process?.env?.APPDATA || "";
    let cfg: any;
    try { cfg = JSON.parse(fs.readFileSync(path.join(appdata, "obsidian", "obsidian.json"), "utf8")); } catch { return; }
    const base = (this.app.vault.adapter as any).getBasePath?.() || "";
    const src = path.join(base, this.app.vault.configDir, "plugins", this.manifest.id);
    for (const [id, v] of Object.entries<any>(cfg.vaults || {})) {
      try {
        const conf = path.join(v.path, ".obsidian");
        const dest = path.join(conf, "plugins", this.manifest.id);
        if (dest === src || !fs.existsSync(conf)) continue;
        const born = fs.statSync(conf).birthtimeMs || fs.statSync(conf).ctimeMs;
        if (born < since) { this.autoInstallStats.skipped_old++; continue; }
        const have = fs.existsSync(path.join(dest, "main.js"));
        const newer = !have || fs.statSync(path.join(src, "main.js")).mtimeMs > fs.statSync(path.join(dest, "main.js")).mtimeMs;
        if (newer) {
          fs.mkdirSync(dest, { recursive: true });
          for (const f of ["main.js", "manifest.json", "styles.css"]) {
            if (fs.existsSync(path.join(src, f))) fs.copyFileSync(path.join(src, f), path.join(dest, f));
          }
        }
        const listF = path.join(conf, "community-plugins.json");
        let list: string[] = [];
        try { list = JSON.parse(fs.readFileSync(listF, "utf8")); } catch { list = []; }
        if (!list.includes(this.manifest.id)) { list.push(this.manifest.id); fs.writeFileSync(listF, JSON.stringify(list, null, 2)); }
        if (window.localStorage.getItem("enable-plugin-" + id) !== "true") window.localStorage.setItem("enable-plugin-" + id, "true");
        if (!have) { this.autoInstallStats.installed.push(v.path); new Notice(`domvec: installed into the new vault ${path.basename(v.path)} -- reopen it to load`, 6000); }
      } catch { this.autoInstallStats.errors++; }
    }
  }
  /** Reconcile `settings.sidecar` with `sidecarLaunch` / `activeWorkspace` so a
   *  stale port in `data.json` (2026-11-17: `sidecar` on 8788 while
   *  `sidecarLaunch` ran `everyone-else-gets-the-office` on 8792) never leaves
   *  the plugin polling the wrong port while its sidecar is already up.
   *  Planted `__domvecPlantStaleSidecarPort`: leaves a mismatched port as-is. */
  async syncSidecarUrl(): Promise<string> {
    if ((window as any).__domvecPlantStaleSidecarPort) return String(this.settings.sidecar || "");
    const sess = (window as any).__domvecSession;
    if (sess && sess.kind === "empty") return String(this.settings.sidecar || "");
    const cur = String(this.settings.sidecar || "").trim().replace(/\/+$/, "");
    if (/:879[01]$/.test(cur)) return cur; // verifier (8790) or test session (8791)
    const L: any = this.settings.sidecarLaunch;
    const activeName = this.settings.activeWorkspace || "";
    const activeDir = (activeName && this.settings.workspaces?.[activeName]) || L?.workspace || "";
    let port = 0;
    if (L && Array.isArray(L.argv) && (!activeDir || !L.workspace || L.workspace === activeDir)) {
      const pi = L.argv.indexOf("--port");
      if (pi >= 0 && pi + 1 < L.argv.length && /^\d+$/.test(String(L.argv[pi + 1]))) {
        port = Number(L.argv[pi + 1]);
      }
    }
    if (!port && activeDir) {
      try {
        const map = JSON.parse(window.localStorage.getItem("domvec-workspace-ports") || "{}");
        if (map && typeof map[activeDir] === "number") port = map[activeDir];
      } catch { /* ignore */ }
    }
    if (port > 0) {
      const want = `http://127.0.0.1:${port}`;
      if (cur !== want) {
        this.settings.sidecar = want;
        await this.saveSettings();
      }
      if (activeDir) this.claimPort(activeDir, port);
      return want;
    }
    return cur;
  }

  /** A vault with no sidecar running: connect to its running sidecar, start its
   *  recorded `sidecarLaunch`, or (for a brand-new vault) create "default". */
  async autostartSidecar(): Promise<void> {
    if ((window as any).__domvecPlantNoAutostart || this.userStoppedSidecar) return;
    await this.syncSidecarUrl();
    const h: any = await this.sidecar.health().catch(() => null);
    if (h && h.ok && h.backend !== "starting" && h.backend !== "dead") {
      this.onSidecarReady(h);
      return;
    }
    if (h && h.backend === "starting") {
      void this.sidecarTrigger(false);
      return;
    }
    if (this.settings.sidecarLaunch && this.settings.sidecarLaunch.python && Array.isArray(this.settings.sidecarLaunch.argv)) {
      await this.sidecarTrigger(false);
      return;
    }
    if (this.settings.sidecarLaunch || this.settings.activeWorkspace) return;
    if (!this.launchTemplate()) return;
    await this.useWorkspace("default", !this.workspaceList()["default"]);
  }

  typegenStats = { asked: 0, made: 0, last: null as any, mined_asks: 0, mined_fetches: 0 };
  /** G-377: what the toolspaces' asks did, by kind, for the harness. */
  toolAskStats: Record<string, number> = {};
  toolAskLast: any = null;
  toolAskLog: any[] = [];
  /**
   * A toolspace call that changes the world (COMPUTATION_GRAPH_EDITOR_SPEC
   * §8), carried out when its cell ends by the method the gesture uses:
   * `focus` the hover's flight, `unfold` the page right-click, `attach` the
   * ego tag, `view` the V key, `pin` the browser's right-click pin, `act` a
   * panel control. Returns the note for the cell's notice, or "".
   */
  /** Planted (G-377): the toolspaces' asks are dropped -- the cell runs, the world does not change. */
  plantNoToolAsks = false;
  /** G-205: the last result `browse(down=...)` opened in the cell. */
  browseLast: { url: string; cid: string; found: boolean | null; at: number } | null = null;
  async carryToolAsk(a: any): Promise<string> {
    if (!a || typeof a !== "object") return "";
    const g: any = this.app.workspace.getLeavesOfType(GRAPH_VIEW)[0]?.view;
    const browser: any = this.activeBrowser();
    const kind = ["focus", "unfold", "attach", "view", "pin", "act", "reveal"].find((k) => a[k] !== undefined);
    if (!kind) return "";
    if (this.plantNoToolAsks) return "";
    this.toolAskStats[kind] = (this.toolAskStats[kind] || 0) + 1;
    let said = "";
    if (kind === "focus") {
      const n = g?.graph?.graphData().nodes.find((x: any) => x.id === a.focus);
      if (n && typeof g.flyTo === "function") { g.flyTo(n); said = `focus: flying to ${String(a.focus).slice(0, 12)}`; }
      else said = `focus: ${String(a.focus).slice(0, 12)} is not drawn`;
    } else if (kind === "unfold") {
      const page = g?.graph?.graphData().nodes.find((x: any) => x.level === "page" && x.url === a.unfold);
      if (!g || !page) said = `unfold: no page node for ${a.unfold}`;
      else {
        g.collapsedByReader?.delete(a.unfold);
        const drawn = g.graph.graphData().nodes.some((x: any) => x.url === a.unfold && x.level !== "page");
        const r = drawn ? { nodes: 0, action: "already open" } : await g.togglePage(page);
        said = `unfold: ${r.action} ${r.nodes}`;
      }
    } else if (kind === "attach") {
      const ok = g && typeof g.tagEgo === "function" ? await g.tagEgo(String(a.attach), true) : false;
      said = ok ? `attach: ${String(a.attach).slice(0, 12)} tagged into the ego` : `attach: not tagged`;
    } else if (kind === "view") {
      if (g?.agent) { g.agent.setMode("ego"); g.agent.setView(a.view); said = `view: ${a.view} person`; }
      else said = "view: no 3D view";
    } else if (kind === "pin") {
      const r = browser && typeof browser.pinXpath === "function" ? await browser.pinXpath(String(a.pin)) : { error: "no browser cell" };
      said = r && r.cid ? `pin: ${String(r.cid).slice(0, 12)} on the plane` : `pin: ${r?.error || "failed"}`;
    } else if (kind === "act") {
      const v = a.act || {};
      const action = v.value === null || v.value === undefined ? "press" : "type";
      // The key is passed as `WebBrowser.controls` gave it: the store holds
      // controls at the markdown level, so reducing it to the four-part leaf
      // was refused as "not in this workspace" (G-377b, run 64).
      const r = browser && typeof browser.actOnAddress === "function" ? await browser.actOnAddress(String(v.address), action, v.value ?? undefined) : { error: "no browser cell" };
      said = r && !(r as any).error ? `act: ${action} done` : `act: ${(r as any)?.error || "failed"}`;
    } else if (kind === "reveal") {
      // G-205 `browse(down=cid)`: the reader's OWN cell (177 b) opens the
      // result's page at its address. Where it goes next streams into the
      // artifact's trace through the 2 s browser_state the plugin already sends.
      const v = a.reveal || {};
      const found = browser && typeof browser.reveal === "function" ? await browser.reveal(String(v.url || ""), String(v.xpath || "")) : undefined;
      said = found === undefined ? "reveal: no browser cell" : `reveal: ${String(v.url || "").slice(0, 60)} ${found ? "at its address" : "(address not found in the document)"}`;
      this.browseLast = { url: String(v.url || ""), cid: String(v.cid || ""), found: found ?? null, at: Date.now() };
    }
    this.toolAskLast = { kind, said, at: Date.now() };
    this.toolAskLog.push(this.toolAskLast); if (this.toolAskLog.length > 20) this.toolAskLog.shift();
    return said;
  }
  /** G-388: the patterns `/typegen?mine=1` found, kept 5 minutes -- mining
   *  reads every address row (5.2 s on 245k), so the retrieval bar must not
   *  pay it per keystroke. One fetch in flight however many ask. */
  private mined: { at: number; types: any[] } | null = null;
  private mining: Promise<any[]> | null = null;
  async minedTypes(q: string, fresh = false): Promise<any[]> {
    this.typegenStats.mined_asks++;
    if (fresh || !this.mined || Date.now() - this.mined.at > 300000) {
      if (!this.mining) {
        this.typegenStats.mined_fetches++;
        const base = String(this.settings.sidecar || "").replace(/\/+$/, "");
        this.mining = fetch(`${base}/typegen?mine=1&limit=200`).then((x) => x.json())
          .then((r) => { const t = Array.isArray(r?.types) ? r.types : []; this.mined = { at: Date.now(), types: t }; return t; })
          .catch(() => []).finally(() => { this.mining = null; });
      }
      await this.mining;
    }
    const s = q.trim().toLowerCase();
    return (this.mined?.types || []).filter((t: any) => !s || "type".startsWith(s) || "types".startsWith(s)
      || String(t.pattern).toLowerCase().includes(s) || (t.fields || []).some((f: string) => f.includes(s))).slice(0, 12);
  }
  /** A class name from a pattern's record root: `.../article[*]` -> `Article`. */
  typeName(pattern: string): string {
    const last = String(pattern).split("/").filter(Boolean).pop() || "item";
    const tag = last.replace(/\[\*\]$/, "").replace(/\W/g, "") || "item";
    return tag.charAt(0).toUpperCase() + tag.slice(1);
  }
  async typeFromPattern(pattern: string, name = "Item"): Promise<any> {
    this.typegenStats.asked++;
    const base = String(this.settings.sidecar || "").replace(/\/+$/, "");
    const r = await fetch(`${base}/typegen?name=${encodeURIComponent(name)}&pattern=${encodeURIComponent(pattern.trim())}`).then((x) => x.json()).catch((e) => ({ error: String(e) }));
    if (!r || r.error) { new Notice("domvec: " + (r?.error || "no answer")); return r; }
    const BT = String.fromCharCode(96).repeat(3), NL = String.fromCharCode(10);
    // G-388: the node shows the type three ways -- its strict model, a table
    // of its fields each linked to the address it was read from (the trie
    // leaf, not only the name made of it), and a type -> fields graph.
    const types: Record<string, string> = r.types || {}, prov: Record<string, string[]> = r.provenance || {};
    const optional = (f: string) => String(r.source).includes(`    ${f}: Optional[`);
    const esc = (x: string) => String(x).replace(/[|\[\]]/g, " ");
    const rows = Object.keys(types).map((f) => {
      const [u, x, acc] = prov[f] || ["", "", ""];
      return `| ${f} | ${types[f]} | ${optional(f) ? "" : "yes"} | ${u ? `[${esc(x.split("/").slice(-3).join("/"))}](${u})` : ""} ${acc ? "`" + esc(acc).split(" ")[0] + "`" : ""} |`;
    });
    // The graph holds the 24 most common fields (the model lists them
    // commonest first); the table holds every one. 159 boxes is not a view.
    const shown = Object.keys(types).slice(0, 24), more = Object.keys(types).length - shown.length;
    const graph = ["graph LR", `  T["${r.class} · ${r.instances} on ${r.pages} pages"]`,
      ...shown.map((f, i) => `  T ${optional(f) ? "-.->" : "-->"} f${i}["${f}: ${types[f]}"]`),
      ...(more > 0 ? [`  T -.-> more["+${more} more fields"]`] : [])];
    await this.desk.create("notebook", { text: ["---", "domvec: type", `pattern: "${String(pattern).replace(/"/g, "")}"`, "---", "",
      `${r.instances} instances on ${r.pages} pages of \`${pattern}\``, "",
      // The graph FIRST: a live-preview card draws only what is on screen,
      // and below a 161-row table the graph was never drawn (G-388, run 55).
      BT + "mermaid", ...graph, BT, "", BT + "python", r.source.trimEnd(), BT, "",
      "| field | type | required | read from |", "| --- | --- | --- | --- |", ...rows, ""].join(NL) });
    this.typegenStats.made++; this.typegenStats.last = { instances: r.instances, pages: r.pages, fields: r.fields };
    return r;
  }
  workspaceNameOf(dir?: string): string {
    if (!dir) return "";
    for (const [n, d] of Object.entries(this.workspaceList())) if (d === dir) return n;
    return (window as any).require("path").basename(dir);
  }
  /** Each workspace serves on its own port, so two vaults (or two projects)
   *  run side by side and never share a store: 8788 for the first one this
   *  machine knew, then the next free number recorded machine-wide. */
  private claimPort(dir: string, port: number): void {
    const KEY = "domvec-workspace-ports";
    let map: Record<string, number> = {};
    try { map = JSON.parse(window.localStorage.getItem(KEY) || "{}"); } catch { map = {}; }
    if (map[dir]) return;                     // it already has its own
    if (Object.values(map).includes(port)) return;   // taken: it gets a new one when next opened
    map[dir] = port;
    try { window.localStorage.setItem(KEY, JSON.stringify(map)); } catch { /* recomputed */ }
  }
  private workspacePort(dir: string): number {
    const KEY = "domvec-workspace-ports";
    let map: Record<string, number> = {};
    try { map = JSON.parse(window.localStorage.getItem(KEY) || "{}"); } catch { map = {}; }
    if (map[dir]) return map[dir];
    const used = new Set(Object.values(map));
    let p = 8788;
    while (used.has(p) || p === 8790 || p === 8791) p++;
    map[dir] = p;
    try { window.localStorage.setItem(KEY, JSON.stringify(map)); } catch { /* recomputed next time */ }
    return p;
  }
  /** A launch to start from: this vault's, else the last one any vault on this
   *  machine recorded (a new vault has none of its own yet). */
  private launchTemplate(): any {
    const own = this.settings.sidecarLaunch;
    if (own && own.python && Array.isArray(own.argv)) return own;
    try { return JSON.parse(window.localStorage.getItem("domvec-sidecar-launch") || "null"); } catch { return null; }
  }
  /** The vault switcher's shape: workspaces with a check on the open one,
   *  then "New workspace...". */
  workspaceMenu(e: MouseEvent, button: HTMLElement): void {
    const menu = new Menu();
    const active = this.settings.activeWorkspace || this.workspaceNameOf(this.settings.sidecarLaunch?.workspace);
    for (const name of Object.keys(this.workspaceList()).sort()) {
      menu.addItem((it) => it.setTitle(name).setChecked(name === active)
        .onClick(() => { if (name !== active) void this.useWorkspace(name, false).then(() => button.setText(name + " ▾")); }));
    }
    menu.addSeparator();
    menu.addItem((it) => it.setTitle("New workspace…").setIcon("plus")
      .onClick(() => new WorkspaceNameModal(this.app, (n) => { void this.useWorkspace(n, true).then(() => button.setText((this.settings.activeWorkspace || n) + " ▾")); }).open()));
    menu.showAtMouseEvent(e);
  }
  async useWorkspace(name: string, create: boolean): Promise<void> {
    name = (name || "").trim().replace(/[^\w.-]+/g, "-");
    if (!name) return;
    const req = (window as any).require;
    const fs = req("fs"), path = req("path"), cp = req("child_process");
    const known = this.workspaceList();
    let dir = known[name];
    if (create) {
      if (dir) { new Notice(`domvec: a workspace named "${name}" already exists in this vault`, 6000); return; }
      dir = path.join(this.workspaceRoot(), name);
      fs.mkdirSync(dir, { recursive: true });
      this.workspaceStats.created++;
    }
    if (!dir) { new Notice(`domvec: no workspace "${name}"`, 5000); return; }
    const L = this.launchTemplate();
    if (!L || !L.python || !Array.isArray(L.argv)) {
      new Notice("domvec: no sidecar launch on record on this machine -- start the sidecar once, then switch", 8000);
      return;
    }
    // Stop only THIS vault's sidecar (its own port); another vault's runs on.
    const oldPort = Number((String(this.settings.sidecar).match(/:(\d+)/) || [])[1]) || 8788;
    // The workspace being LEFT stays in the list, on the port it had: the
    // first switch dropped `corpus123` and gave the new one its port 8788.
    if (L.workspace && L.workspace !== dir) {
      const was = this.workspaceNameOf(L.workspace);
      this.settings.workspaces = { ...(this.settings.workspaces || {}), [was]: L.workspace };
      this.claimPort(L.workspace, oldPort);
    }
    new Notice(`domvec: stopping the sidecar to open workspace "${name}" ...`, 4000);
    await new Promise<void>((done) => {
      const p = cp.spawn(L.python, ["-c", `from domvec.obsidian.controls import stop_sidecar; print(stop_sidecar(port=${oldPort}, force=True))`],
        { cwd: L.cwd || undefined, windowsHide: true });
      p.on("exit", () => done()); p.on("error", () => done());
      window.setTimeout(done, 30000);
    });
    const argv = ["supervise", ...L.argv.filter((a: string) => a !== "supervise" && a !== "serve")];
    const w = argv.indexOf("--workspace");
    if (w >= 0) argv[w + 1] = dir; else argv.push("--workspace", dir);
    const port = this.workspacePort(dir);
    const pi = argv.indexOf("--port");
    if (pi >= 0) argv[pi + 1] = String(port); else argv.push("--port", String(port));
    this.settings.sidecar = "http://127.0.0.1:" + port;
    this.settings.workspaces = { ...(this.settings.workspaces || {}), [name]: dir };
    this.settings.activeWorkspace = name;
    this.settings.sidecarLaunch = { ...L, argv, workspace: dir };
    await this.saveSettings();
    this.workspaceStats.switched++;
    this.workspaceStats.last = { name, dir, create, at: Date.now() };
    const said = await this.sidecarTrigger(false);
    // The graph drops the old workspace's nodes: a fresh load from the new store.
    for (const leaf of this.app.workspace.getLeavesOfType("domvec-graph-view")) {
      try { (leaf.view as any).clearForWorkspace?.(); await (leaf.view as any).reload?.(); } catch { /* the view reloads on its own poll */ }
    }
    new Notice(`domvec: workspace "${name}" ${said === "sidecar ●" ? "open" : "not answering yet"} -- ${dir}`, 8000);
  }

  respawnStats = { checks: 0, respawned: 0, last: null as any };
  private respawning = false;
  async watchSidecar(): Promise<void> {
    if (this.respawning) return;
    this.respawnStats.checks++;
    const h: any = await this.sidecar.health().catch(() => null);
    if (h && h.launch && h.launch.python && Array.isArray(h.launch.argv)) {
      try { window.localStorage.setItem("domvec-sidecar-launch", JSON.stringify(h.launch)); } catch { /* a convenience */ }
      const was = JSON.stringify(this.settings.sidecarLaunch || null);
      if (was !== JSON.stringify(h.launch) && (!this.settings.activeWorkspace || h.launch.workspace === this.settings.sidecarLaunch?.workspace)) { this.settings.sidecarLaunch = h.launch; await this.saveSettings(); }
      return;
    }
    const L = this.settings.sidecarLaunch;
    if (h || !L || !L.workspace || (window as any).__domvecPlantNoRespawn) return;
    const req = (window as any).require;
    const fs = req("fs"), path = req("path"), cp = req("child_process");
    const marker = path.join(L.workspace, "supervisor_gave_up.json");
    if (!fs.existsSync(marker)) return;
    this.respawning = true;
    try {
      const why = fs.readFileSync(marker, "utf8");
      fs.unlinkSync(marker);
      const argv = ["supervise", ...L.argv.filter((a: string) => a !== "supervise" && a !== "serve")];
      const log = fs.openSync(path.join(L.workspace, "sidecar.log"), "a");
      const child = cp.spawn(L.python, ["-X", "faulthandler", "-m", "domvec.obsidian", ...argv],
        { cwd: L.cwd || undefined, detached: true, windowsHide: true, stdio: ["ignore", log, log],
          env: { ...(window as any).process.env, PYTHONIOENCODING: "utf-8" } });
      child.unref();
      this.respawnStats.respawned++;
      this.respawnStats.last = { at: Date.now(), pid: child.pid, why: why.slice(0, 200) };
      new Notice("domvec: the sidecar's supervisor gave up -- started a fresh one");
    } catch (e) {
      this.respawnStats.last = { at: Date.now(), error: String(e).slice(0, 200) };
    } finally {
      this.respawning = false;
    }
  }

  /**
   * The CLIPBOARD (PLUGIN_GOAL 134: "The clipboard is a basic markdown panel per
   * all the other 'same' panel constraints and dynamically aggregates on
   * right-clicks"): a plain note, `domvec/clipboard.md`, open on the plane --
   * every chunk right-clicked in the browser appended to it once, under its
   * page. Planted `__domvecPlantNoClipboard`: right-clicks add nothing.
   */
  /**
   * Copy and paste from the cell under the MOUSE (PLUGIN_GOAL 134: "copy-paste
   * comes from the perspective view of the cell hovered by the mouse"): with
   * nothing selected, Ctrl+C copies the hovered cell's markdown -- a plane
   * panel's note or a chunk panel's lines -- and Ctrl+V, outside an editor,
   * appends the clipboard to the hovered cell's note. Planted
   * `__domvecPlantNoHoverCopy`: the keys do what they did.
   */
  hoverCopyStats = { copied: 0, pasted: 0, last: "" };
  private mouseAt = { x: -1, y: -1 };
  private hookHoverCopy(): void {
    this.registerDomEvent(window, "mousemove", (e: MouseEvent) => { this.mouseAt = { x: e.clientX, y: e.clientY }; }, true);
    this.registerDomEvent(window, "keydown", (e: KeyboardEvent) => { void this.hoverCopy(e); }, true);
  }
  async hoverCopy(e: KeyboardEvent): Promise<string> {
    if ((window as any).__domvecPlantNoHoverCopy || !(e.ctrlKey || e.metaKey)) return "";
    const k = e.key.toLowerCase();
    if (k !== "c" && k !== "v") return "";
    const sel = window.getSelection();
    if (k === "c" && sel && String(sel).length) return "";
    const under = document.elementFromPoint(this.mouseAt.x, this.mouseAt.y) as HTMLElement | null;
    if (!under) return "";
    const card = under.closest(".domvec-panel-card") as HTMLElement | null;
    const bb = card ? null : under.closest(".domvec-billboard, .domvec-bb") as HTMLElement | null;
    const path = card?.dataset.path || "";
    if (k === "c") {
      let text = "";
      if (path) { const f: any = this.app.vault.getAbstractFileByPath(path); if (f) text = await this.app.vault.read(f); }
      else if (bb) {
        const gv: any = this.app.workspace.getLeavesOfType("domvec-graph-view")[0]?.view;
        const id = gv ? [...gv.billboards.entries()].find(([, en]: any) => en.el === bb || en.el.contains(bb))?.[0] : "";
        const pay: any = id ? await gv.chunkPayload(String(id)).catch(() => null) : null;
        text = ((pay && pay.lines) || []).map((l: any) => String(l.text || "")).join(String.fromCharCode(10));
      }
      if (!text) return "";
      e.preventDefault(); e.stopPropagation();
      await navigator.clipboard.writeText(text);
      this.hoverCopyStats.copied++; this.hoverCopyStats.last = path || "chunk";
      return "copied";
    }
    // Paste: only outside an editor -- inside one, the editor pastes as usual.
    const active = document.activeElement as HTMLElement | null;
    if (!path || (active && (active.isContentEditable || active.tagName === "INPUT" || active.tagName === "TEXTAREA"))) return "";
    const f: any = this.app.vault.getAbstractFileByPath(path);
    if (!f) return "";
    e.preventDefault(); e.stopPropagation();
    const clip = await navigator.clipboard.readText();
    if (!clip) return "";
    const NL = String.fromCharCode(10);
    await this.app.vault.process(f, (t: string) => t.replace(/\s*$/, "") + NL + NL + clip + NL);
    this.hoverCopyStats.pasted++; this.hoverCopyStats.last = path;
    return "pasted";
  }

  clipStats = { added: 0, repeats: 0 };
  async clipboardAdd(cid: string, url: string): Promise<boolean> {
    if ((window as any).__domvecPlantNoClipboard || !cid) return false;
    const path = "domvec/clipboard.md";
    const NL = String.fromCharCode(10);
    let f: any = this.app.vault.getAbstractFileByPath(path);
    if (!f) f = await this.app.vault.create(path, "clipboard" + NL);
    const text = await this.app.vault.read(f);
    if (text.includes("<!-- cid:" + cid + " -->")) { this.clipStats.repeats++; return false; }
    const gv: any = this.app.workspace.getLeavesOfType("domvec-graph-view")[0]?.view;
    const pay: any = gv ? await gv.chunkPayload(cid).catch(() => null) : null;
    const md = ((pay && pay.lines) || []).map((l: any) => String(l.text || "")).join(NL).trim();
    if (!md) return false;
    await this.app.vault.process(f, (t: string) => t.replace(/\s*$/, "") + NL + NL + "<!-- cid:" + cid + " -->" + NL + "*" + url + "*" + NL + md + NL);
    this.clipStats.added++;
    if (!this.desk.panelOf(path)) await this.desk.open(f).catch(() => null);
    return true;
  }

  /**
   * The graph's sidecar button (PLUGIN_GOAL 130): verify the sidecar the way
   * the MCP's `live_health` does -- is it answering, what does the store hold,
   * which powers are on -- and, when none answers and a launch is on record,
   * start one (supervised) and wait for it. `quiet` only reads the state.
   */
  sidecarStats = { checked: 0, started: 0, stopped: 0, last: null as any };
  private sidecarStarting: Promise<string> | null = null;
  userStoppedSidecar = false;

  private setSidecarButtons(text: string): void {
    for (const leaf of this.app.workspace.getLeavesOfType("domvec-graph-view")) {
      const b = (leaf.view as any)?.sidecarButton as HTMLElement | null;
      if (b && b.textContent !== text) b.setText(text);
    }
  }

  private onSidecarReady(h: any): void {
    this.serverEnact = !!(h && h.enact);
    this.setSidecarButtons("sidecar ●");
    if (this.sidecar?.vaultRoot) {
      void this.sidecar.egoPost("vault_root", { root: this.sidecar.vaultRoot, name: this.app.vault.getName() });
    }
    if (h && h.launch && h.launch.python && Array.isArray(h.launch.argv)) {
      try { window.localStorage.setItem("domvec-sidecar-launch", JSON.stringify(h.launch)); } catch { /* convenience */ }
      const was = JSON.stringify(this.settings.sidecarLaunch || null);
      if (was !== JSON.stringify(h.launch) && (!this.settings.activeWorkspace || h.launch.workspace === this.settings.sidecarLaunch?.workspace)) {
        this.settings.sidecarLaunch = h.launch;
        void this.saveSettings();
      }
    }
    for (const leaf of this.app.workspace.getLeavesOfType("domvec-graph-view")) {
      const v: any = leaf.view;
      if (!v) continue;
      const stText = String(v.statusEl?.textContent || v.containerEl?.querySelector?.(".domvec-graph-status")?.textContent || "");
      if (v.layoutMode === "empty" || (typeof v.projEpoch === "number" && v.projEpoch < 0) || /no sidecar/i.test(stText)) {
        try { void v.reload?.(); } catch { /* reload retries on its own */ }
      }
    }
  }

  private async pollSidecarStatus(): Promise<void> {
    if (this.sidecarStarting) return;
    // Do not disturb a check that temporarily nulled sidecarLaunch (PG-130 planted arm).
    if (!this.settings.sidecarLaunch && this.settings.activeWorkspace) return;
    await this.syncSidecarUrl();
    const h: any = await this.sidecar.health().catch(() => null);
    if (h && h.ok && h.backend !== "starting" && h.backend !== "dead") {
      this.onSidecarReady(h);
    } else if (h && (h.backend === "starting" || h.warming)) {
      this.setSidecarButtons("sidecar …");
    } else {
      this.setSidecarButtons("sidecar ○");
    }
  }

  sidecarMenu(e: MouseEvent, button: HTMLElement): void {
    const menu = new Menu();
    menu.addItem((it) => it.setTitle("Verify / start sidecar").setIcon("play")
      .onClick(() => { button.setText("sidecar …"); void this.sidecarTrigger(false).then((t) => button.setText(t)); }));
    menu.addItem((it) => it.setTitle("Restart sidecar gracefully").setIcon("refresh-cw")
      .onClick(() => { button.setText("sidecar …"); void this.restartSidecar().then((t) => button.setText(t)); }));
    menu.addItem((it) => it.setTitle("Stop sidecar gracefully").setIcon("square")
      .onClick(() => { button.setText("sidecar …"); void this.stopSidecar(false).then((t) => button.setText(t)); }));
    menu.showAtMouseEvent(e);
  }

  async stopSidecar(force = false): Promise<string> {
    this.userStoppedSidecar = true;
    await this.syncSidecarUrl();
    const base = String(this.settings.sidecar || "").trim().replace(/\/+$/, "");
    const port = Number((base.match(/:(\d+)$/) || [])[1]) || 8788;
    this.setSidecarButtons("sidecar …");
    try {
      await fetch(`${base}/shutdown?stop=1`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
        signal: AbortSignal.timeout(5000),
      });
    } catch { /* may already be down or starting */ }
    let down = false;
    for (let i = 0; i < 12; i++) {
      await new Promise((r) => setTimeout(r, 250));
      const h = await this.sidecar.health().catch(() => null);
      if (!h) { down = true; break; }
    }
    if (!down) {
      const L = this.launchTemplate();
      if (L && L.python) {
        const cp = (window as any).require("child_process");
        await new Promise<void>((done) => {
          const p = cp.spawn(L.python, ["-c", `from domvec.obsidian.controls import stop_sidecar; print(stop_sidecar(port=${port}, force=${force ? "True" : "False"}))`],
            { cwd: L.cwd || undefined, windowsHide: true });
          p.on("exit", () => done()); p.on("error", () => done());
          window.setTimeout(done, 15000);
        });
      }
      for (let i = 0; i < 20; i++) {
        const h = await this.sidecar.health().catch(() => null);
        if (!h) { down = true; break; }
        await new Promise((r) => setTimeout(r, 250));
      }
    }
    this.sidecarStats.stopped = (this.sidecarStats.stopped || 0) + 1;
    this.sidecarStats.last = { ok: false, stopped: down, at: Date.now(), port };
    const label = down ? "sidecar ○" : "sidecar ●";
    this.setSidecarButtons(label);
    new Notice(down ? `domvec sidecar ○ stopped (port ${port})` : `domvec sidecar: still running on port ${port}`, 5000);
    return label;
  }

  async restartSidecar(): Promise<string> {
    await this.stopSidecar(true);
    return this.sidecarTrigger(false);
  }

  async sidecarTrigger(quiet = false): Promise<string> {
    this.sidecarStats.checked++;
    await this.syncSidecarUrl();
    const say = (h: any) => {
      const powers = ["capture", "kernel", "enact"].filter((k) => h[k]).join(" ");
      return `pages ${h.pages ?? "?"} · chunks ${h.chunks_total ?? "?"} · no vector ${h.chunks_without_vector ?? "?"} · ${powers}`;
    };
    const isReady = (h: any) => !!(h && h.ok && h.backend !== "starting" && h.backend !== "dead");
    const isStarting = (h: any) => !!(h && (h.backend === "starting" || h.warming));

    if (quiet) {
      if (this.sidecarStarting) return "sidecar …";
      const h: any = await this.sidecar.health().catch(() => null);
      if (isReady(h)) {
        this.sidecarStats.last = { ok: true, at: Date.now() };
        this.onSidecarReady(h);
        return "sidecar ●";
      }
      if (isStarting(h)) return "sidecar …";
      return "sidecar ○";
    }

    this.userStoppedSidecar = false;
    if (this.sidecarStarting && !(window as any).__domvecPlantDuplicateSidecarSpawn) {
      return this.sidecarStarting;
    }

    const run = (async (): Promise<string> => {
      let h: any = await this.sidecar.health().catch(() => null);
      if (isReady(h)) {
        this.sidecarStats.last = { ok: true, at: Date.now() };
        this.onSidecarReady(h);
        new Notice("domvec sidecar ✓ " + say(h), 6000);
        return "sidecar ●";
      }
      // A vault with no sidecar of its own yet (a new vault): its own fresh
      // workspace, "default", on its own port -- nothing inherited (144).
      if (!this.settings.sidecarLaunch && this.launchTemplate() && !this.settings.activeWorkspace) {
        await this.useWorkspace("default", !this.workspaceList()["default"]);
        const hDef: any = await this.sidecar.health().catch(() => null);
        if (isReady(hDef)) { this.onSidecarReady(hDef); return "sidecar ●"; }
        return "sidecar ✕";
      }
      const L = this.settings.sidecarLaunch;
      if (!L || !L.python || !Array.isArray(L.argv)) {
        new Notice("domvec sidecar ✕ not answering, and no launch on record -- start it once from the MCP or a terminal", 8000);
        this.setSidecarButtons("sidecar ✕");
        return "sidecar ✕";
      }
      const req = (window as any).require;
      const fs = req("fs"), path = req("path"), cp = req("child_process");
      const argv = ["supervise", ...L.argv.filter((a: string) => a !== "supervise" && a !== "serve")];
      const activeName = this.settings.activeWorkspace || "";
      const dir = (activeName && this.settings.workspaces?.[activeName]) || L.workspace;
      if (dir) {
        const wi = argv.indexOf("--workspace");
        if (wi >= 0 && wi + 1 < argv.length) argv[wi + 1] = dir;
        else argv.push("--workspace", dir);
      }
      let port = 0;
      const pi = argv.indexOf("--port");
      if (pi >= 0 && pi + 1 < argv.length && /^\d+$/.test(String(argv[pi + 1]))) {
        port = Number(argv[pi + 1]);
      } else if (dir) {
        port = this.workspacePort(dir);
        if (pi >= 0) argv[pi + 1] = String(port);
        else argv.push("--port", String(port));
      }
      if (port > 0 && !(window as any).__domvecPlantStaleSidecarPort) {
        const want = `http://127.0.0.1:${port}`;
        if (this.settings.sidecar !== want) {
          this.settings.sidecar = want;
          await this.saveSettings();
          h = await this.sidecar.health().catch(() => null);
          if (isReady(h)) {
            this.sidecarStats.last = { ok: true, at: Date.now() };
            this.onSidecarReady(h);
            new Notice("domvec sidecar ✓ " + say(h), 6000);
            return "sidecar ●";
          }
        }
      }
      if (!isStarting(h) || (window as any).__domvecPlantDuplicateSidecarSpawn) {
        const wsDir = dir || L.workspace;
        if (wsDir) fs.mkdirSync(wsDir, { recursive: true });
        const log = fs.openSync(path.join(wsDir, "sidecar.log"), "a");
        const child = cp.spawn(L.python, ["-X", "faulthandler", "-m", "domvec.obsidian", ...argv],
          { cwd: L.cwd || undefined, detached: true, windowsHide: true, stdio: ["ignore", log, log],
            env: { ...(window as any).process.env, PYTHONIOENCODING: "utf-8" } });
        child.unref();
        this.sidecarStats.started++;
        this.setSidecarButtons("sidecar …");
        new Notice("domvec sidecar: starting (pid " + child.pid + ") ...", 4000);
      } else {
        this.setSidecarButtons("sidecar …");
        new Notice("domvec sidecar: worker starting — waiting ...", 4000);
      }
      const deadline = Date.now() + 90000;
      let step = 0;
      while (Date.now() < deadline) {
        await new Promise((r) => setTimeout(r, step++ < 20 ? 500 : 1000));
        if (this.userStoppedSidecar) {
          this.setSidecarButtons("sidecar ○");
          return "sidecar ○";
        }
        h = await this.sidecar.health().catch(() => null);
        if (isReady(h)) {
          new Notice("domvec sidecar ✓ started -- " + say(h), 8000);
          this.sidecarStats.last = { ok: true, started: true, at: Date.now() };
          this.onSidecarReady(h);
          return "sidecar ●";
        }
      }
      new Notice("domvec sidecar ✕ started but not answering after 90 s -- see sidecar.log", 10000);
      this.setSidecarButtons("sidecar ✕");
      return "sidecar ✕";
    })();

    this.sidecarStarting = run;
    try {
      return await run;
    } finally {
      if (this.sidecarStarting === run) this.sidecarStarting = null;
    }
  }

  // ---- retrieval links drawn (G-7) -----------------------------------------
  //
  // A note the reader wrote a retrieval link into (the `[]()` gesture) goes
  // into the store as a page, through the sidecar's `/note`: its links become
  // page links, relinked, and the 3D graph draws them as it draws any page's
  // (2026-10-24: 890 page-to-page links drawn, 0 from a note -- no note was
  // ever in the store, so no retrieval link could be). Planted
  // `__domvecPlantNoNoteIndex`: nothing is indexed.
  noteStats = { indexed: 0, errors: 0, last: null as any };

  // ---- the ego reservoir placed by UMAP (item 43) --------------------------
  //
  // "UMAP happens on the ego reservoir for all computation graph nodes as
  // artifacts of various kinds" (2026-10-30). A computation-graph artifact is
  // a note: a slate (`domvec: slate`, the cockpit among them) or a note with
  // a code cell (a function node, G-279, and its stored readout). Each is
  // indexed as a `vault://` page whenever it changes, so the global UMAP
  // places it among the pages and chunks it reads and writes -- the
  // reservoir is not a separate picture. Planted `__domvecPlantNoReservoirIndex`.
  reservoirStats = { indexed: 0, skipped: 0 };
  async isReservoirNote(file: TFile): Promise<boolean> {
    const fm = this.app.metadataCache.getFileCache(file)?.frontmatter;
    if (fm && String(fm.domvec || "") === "slate") return true;
    // The reader's own panels are ego artifacts (PLUGIN_GOAL 74c, 77): a note
    // the plane's tools made, or one open on the plane -- markdown alone too.
    if (file.path.startsWith(PLANE_FOLDER + "/") || this.desk.panelOf(file.path)) return true;
    const text = await this.app.vault.cachedRead(file);
    // The frontmatter from the TEXT too: on `create` the metadata cache has
    // not parsed it yet, and a new slate read as a plain note.
    if (/^---\r?\n(?:.*\r?\n)*?domvec:\s*slate\s*\r?\n(?:.*\r?\n)*?---/.test(text)) return true;
    // A cell note is a function node once it has RUN -- a python cell AND a
    // stored readout. This vault is the repository: a design doc with an
    // illustrative ```python block is not a notebook, and indexing it would
    // grow the corpus every time the doc was edited.
    return /^\s*(`{3,}|~{3,})\s*(python|py|python3)\b/m.test(text) && /^\s*<!--\s*nb-output\s/m.test(text);
  }
  async indexIfReservoir(file: TFile, why: string): Promise<void> {
    if ((window as any).__domvecPlantNoReservoirIndex) return;
    if (!(await this.isReservoirNote(file))) { this.reservoirStats.skipped++; return; }
    this.reservoirStats.indexed++;
    // The cockpit's fields are LIVE state -- throttle, last key, results rows
    // -- written several times a second while the craft flies. Indexed on
    // every write, it re-indexed 19 times in a minute (9.4 s each under the
    // sidecar's work lock) and a search waited 23 s behind it (2026-11-01).
    // Still indexed whenever it changes (G-291): after 30 s of quiet.
    this.indexNoteSoon(file, why, file.path === COCKPIT_PATH ? 30000 : 4000);
  }
  async indexReservoir(): Promise<number> {
    let n = 0;
    for (const f of this.app.vault.getMarkdownFiles()) {
      if (await this.isReservoirNote(f)) { n++; await this.indexNote(f, "reservoir"); }
    }
    return n;
  }
  private noteTimers = new Map<string, number>();
  /** Notes deleted this session: an index already in flight must not bring one back. */
  private deletedNotes = new Set<string>();
  indexNoteSoon(file: TFile, why: string, delayMs = 2500): void {
    if ((window as any).__domvecPlantNoNoteIndex) return;
    window.clearTimeout(this.noteTimers.get(file.path));
    this.noteTimers.set(file.path, window.setTimeout(() => { this.noteTimers.delete(file.path); void this.indexNote(file, why); }, delayMs));
  }
  async indexNote(file: TFile, why: string): Promise<any> {
    if ((window as any).__domvecPlantNoNoteIndex) return null;
    if (this.deletedNotes.has(file.path) && !this.app.vault.getAbstractFileByPath(file.path)) return null;
    const text = await this.app.vault.cachedRead(file);
    const got = await this.sidecar.note(file.path, text, this.app.vault.getName());
    if (!got || got.error) {
      this.noteStats.errors++;
      this.noteStats.last = { path: file.path, why, error: got ? got.error : "no answer" };
      return got;
    }
    this.noteStats.indexed++;
    this.noteStats.last = { path: file.path, why, url: got.url, chunks: got.chunks, links: (got.links || []).length, ms: got.ms };
    const kept = this.settings.indexedNotes || [];
    if (!kept.includes(file.path)) { this.settings.indexedNotes = [...kept, file.path]; await this.saveSettings(); }
    return got;
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
        cls: "domvec-error",
        text: "domvec: this block carries no cid",
      });
      return;
    }
    const surface = new ChunkSurface(el, cid, this,
      // From the context's own frontmatter first: a note opened as it is
      // created renders its fence before the metadata cache has read it.
      { notePath: ((ctx.frontmatter?.domvec === "chunk" && !(window as any).__domvecPlantNoHalves)
                   || this.isChunkNote(ctx.sourcePath)) ? ctx.sourcePath : undefined, sourcePath: ctx.sourcePath });
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

class DomvecSettingTab extends PluginSettingTab {
  constructor(app: App, private plugin: DomvecPlugin) {
    super(app, plugin);
  }

  display() {
    const { containerEl } = this;
    containerEl.empty();

    new Setting(containerEl)
      .setName("Sidecar address")
      .setDesc(
        "Where the domvec Python sidecar answers. Leave empty to work purely " +
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

/** PLUGIN_GOAL 144: the name of a new, empty workspace. */
class WorkspaceNameModal extends Modal {
  constructor(app: App, private done: (name: string) => void, private title = "New workspace") { super(app); }
  onOpen(): void {
    this.titleEl.setText(this.title);
    const input = this.contentEl.createEl("input", { type: "text", attr: { placeholder: this.title === "New workspace" ? "project name" : "/html/body/..." } });
    input.style.width = "100%";
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") { this.close(); this.done(input.value); } });
    window.setTimeout(() => input.focus(), 0);
  }
  onClose(): void { this.contentEl.empty(); }
}

/** PLUGIN_GOAL 144: pick one of this vault's workspaces. */
class WorkspacePickModal extends SuggestModal<string> {
  constructor(app: App, private all: Record<string, string>, private active: string, private done: (name: string) => void) { super(app); }
  getSuggestions(q: string): string[] { return Object.keys(this.all).filter((n) => n.toLowerCase().includes(q.toLowerCase())); }
  renderSuggestion(n: string, el: HTMLElement): void {
    el.createEl("div", { text: n + (n === this.active ? "  (open)" : "") });
    el.createEl("small", { text: this.all[n] });
  }
  onChooseSuggestion(n: string): void { this.done(n); }
}
