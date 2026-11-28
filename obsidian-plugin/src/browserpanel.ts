/**
 * The browser cell as a panel on the plane, with its own cockpit (PLUGIN_GOAL
 * 71-72, 2026-11-01: "our full web browser panel feature + all functionalities
 * should be translated to its draggable panel/computation graph analogue;
 * includes "cockpit" for browser tools/actions on the panel, as well as the
 * actual web browser rendering the interactive HTML").
 *
 * One card on the plane, two leaves: the BROWSER COCKPIT -- a slate note
 * whose fields ARE the browser's tools, bound both ways as the ego cockpit's
 * are (G-280) -- and the browser itself, the same `BrowserView` the
 * standalone pane and the notebook's browser fence are (G-36). The slate's
 * title, `browser`, is the card's header node (item 54): it drags the card,
 * a right-click on it collapses the browser to that node.
 *
 *   browser
 *   	url	https://...        typed: the browser goes there; navigation writes it back
 *   	back	go                 a click on the value: one page back
 *   	forward	go                 ... forward
 *   	scan	go                 ... the page scanned now
 *   	live	true               a click toggles: the page streamed into the store, or not
 *   	boxes	false              ... the chunk outlines shown, or not
 *   	scope	live               live: the real page; page: the page rebuilt from the
 *   	                           store (offline) -- the scope ladder's upper two rungs
 *   	                           (item 72; `chunk` is the billboard's, RESERVOIR_DESIGN 10.2)
 *
 * The browser's own toolbar stays until the slate covers every action (UR
 * S.4: chrome goes, but not before its replacement is seen to work).
 */
import { App, Component, MarkdownRenderer, MarkdownView, TFile } from "obsidian";
import { foldsOf, parseSlate, setFolds, type SlateLine } from "./slatefold";
import type { PlaneDesk } from "./planepanels";
import { chunkNoteState } from "./planecard";
import { capabilitiesOf, panelText, withMissing, type Capability } from "./governing";

/** The browser's governing artifact (T-10): its methods are the panel's fields. */
export const BROWSER_GOVERNING_PATH = "domvec/governing/browser.py";

export const BROWSER_COCKPIT_PATH = "domvec/browser.md";
/** The scope ladder, narrowest first (item 72; RESERVOIR_DESIGN 10.2). */
export const LADDER = ["chunk", "page", "live"] as const;
const T = "\t";
const BROWSER_TEXT = ["---", "domvec: slate", "---", "browser",
  T + "url" + T, T + "back" + T + "false", T + "forward" + T + "false", T + "scan" + T + "false",
  T + "live" + T + "true", T + "boxes" + T + "false", T + "scope" + T + "live", ""].join("\n");

export interface BrowserPanelHost { browserViewType: string; desk: PlaneDesk }

export class BrowserPanel {
  browserLeaf: any = null;
  /** The chunk rung: the chunk rendered as a chunk note's fence renders it. */
  private chunkEl: HTMLElement | null = null;
  private chunkComp: Component | null = null;
  chunkShown = "";
  stats = { exited: 0, opened: 0, went: 0, back: 0, forward: 0, scans: 0, toggles: 0, written: 0, scope: "" as string, split: 0, joined: 0, restoredUrl: 0, framed: 0 };
  /** Planted (item 71): the cockpit's fields bind nothing. */
  plantUnbound = false;
  private seenUrl = "";
  plantScopeFirstRead = false;
  /** Planted: the action fields read "go", as before. */
  plantGoActions = false;
  plantNoExit = false;
  /** Planted: pulled apart with no link drawn between the halves (135(b)). */
  plantPairNoLink = false;
  /** Planted: opened with no url, the slate's url is not loaded (about:blank stays). */
  plantNoRestoreUrl = false;
  /** The pair's pull-apart, while split: undoes it. */
  private unsplit: (() => void) | null = null;
  private scopeTry = 0;
  private hooked = new WeakSet<HTMLElement>();

  /** `path`: this instance's cockpit note -- one per browser instance
   *  (PLUGIN_GOAL 87: "several instances of browsers (each with several tabs)
   *  could be running their own sessions at a time"). */
  constructor(private app: App, private host: BrowserPanelHost, readonly path: string = BROWSER_COCKPIT_PATH) {}

  /** Planted (T-10): the hard-coded field list, the code not read. */
  plantHardFields = false;
  governStats = { read: 0, caps: 0, added: 0 };
  /** The governing class's capabilities, read from the vault each time (an
   *  edit to the class shows on the next open). */
  async capabilities(): Promise<Capability[]> {
    const g = this.app.vault.getAbstractFileByPath(BROWSER_GOVERNING_PATH);
    if (!(g instanceof TFile)) return [];
    const caps = capabilitiesOf(await this.app.vault.read(g));
    this.governStats.read++; this.governStats.caps = caps.length;
    return caps;
  }

  /** The slate's view on the plane, if open. */
  slateView(): MarkdownView | null { return this.host.desk.viewOf(this.path); }
  /** The browser's view inside the card, if mounted. */
  view(): any { return this.browserLeaf?.view || null; }

  /** The browser on the plane: its cockpit note (made on first use) and the
   *  browser beneath it, in one card. */
  async open(url = ""): Promise<any> {
    let f = this.app.vault.getAbstractFileByPath(this.path);
    if (!(f instanceof TFile)) {
      if (!this.app.vault.getAbstractFileByPath("domvec")) await this.app.vault.createFolder("domvec").catch(() => undefined);
      // Its slate titled for its note: `browser`, `browser 2`, ...
      const title = this.path.slice(this.path.lastIndexOf("/") + 1).replace(/\.md$/, "");
      const caps = this.plantHardFields ? [] : await this.capabilities();
      f = await this.app.vault.create(this.path, caps.length ? panelText(title, caps) : BROWSER_TEXT.replace("\nbrowser\n", "\n" + title + "\n"));
    } else if (!this.plantGoActions) {
      // Actions are booleans now (2026-11-07: "there should be no 'go' for
      // booleans"): a note written with `go` reads `false`; a click acts.
      await this.app.vault.process(f as TFile, (t: string) => t.replace(/^(\t(?:back|forward|scan)\t)go[ \t]*$/gm, "$1false"));
    }
    // A method added to the governing class is a field added to the panel.
    if (f instanceof TFile && !this.plantHardFields) {
      const caps = await this.capabilities();
      if (caps.length) await this.app.vault.process(f, (t: string) => { const r = withMissing(t, caps); this.governStats.added += r.added.length; return r.text; });
    }
    // Asked to open, it opens: the slate's REMEMBERED fold state said
    // "collapsed" (a right-click on its title, kept per note) and came back
    // after the note's text loaded -- the browser shown as its node alone.
    try {
      const k = "domvec.slate.folds:" + this.path;
      const st = JSON.parse(window.localStorage.getItem(k) || "null");
      if (st && st.collapsed) { st.collapsed = false; window.localStorage.setItem(k, JSON.stringify(st)); }
    } catch { /* a convenience */ }
    const desk = this.host.desk;
    const existing = desk.panelOf(this.path);
    await desk.open(f as TFile, {
      mount: async (card: HTMLElement) => {
        card.addClass("domvec-browser-card");
        // Clean header tool strip (G-443, PLUGIN_GOAL 200 d): split and exit
        // grouped in one flex container so buttons never overlap each other.
        const tools = card.createDiv({ cls: "domvec-browser-card-tools" });
        const Leaf = (this.app.workspace as any).activeLeaf?.constructor ?? (this.app.workspace.getMostRecentLeaf() as any)?.constructor;
        const leaf = new Leaf(this.app);
        leaf.containerEl.addClass("domvec-browser-panel-leaf");
        card.appendChild(leaf.containerEl);
        await leaf.setViewState({ type: this.host.browserViewType, active: false });
        this.browserLeaf = leaf;
        // PLUGIN_GOAL 135(b): "the markdown and browser panels in the 2D plane
        // appear as one unit, but should still be able to be pulled apart and
        // show solid links between the two". The browser keeps its DOM parent
        // (a reparented <webview> reloads its page) and is offset out of the
        // card; a solid undirected link joins the halves, right-click toggles
        // it translucent (135(d)), the split control again rejoins.
        const sp = tools.createSpan({ cls: "domvec-browser-card-split", text: "⇹" });
        sp.setAttr("aria-label", "pull the browser apart from its markdown");
        sp.onpointerdown = (e: PointerEvent) => e.stopPropagation();
        sp.onclick = (e: MouseEvent) => { e.stopPropagation(); this.togglePair(); };
        // Its exit (2026-11-07: "no option to exit a 2D plane browser cell").
        // Planted `plantNoExit`: none, as before.
        if (!this.plantNoExit) {
          const x = tools.createSpan({ cls: "domvec-browser-card-exit", text: "×" });
          x.setAttr("aria-label", "close this browser cell");
          x.onpointerdown = (e: PointerEvent) => e.stopPropagation();
          x.onclick = (e: MouseEvent) => { e.stopPropagation(); this.stats.exited++; const q = desk.panelOf(this.path); if (q) q.leaf.detach(); };
        }
        const chunkEl = card.createDiv({ cls: "domvec-browser-chunk" });
        chunkEl.style.display = "none";
        this.chunkEl = chunkEl;
        // The ladder's gesture (item 72): the wheel over the header node steps
        // the scope -- in, toward the chunk; out, toward the live page.
        const onWheel = (e: WheelEvent) => {
          if (!(e.target as HTMLElement)?.closest?.(".domvec-var-title")) return;
          e.preventDefault(); e.stopPropagation();
          this.step(e.deltaY < 0 ? -1 : 1);
        };
        card.addEventListener("wheel", onWheel, { capture: true, passive: false });
        return () => {
          card.removeEventListener("wheel", onWheel, true);
          this.chunkComp?.unload(); this.chunkComp = null; try { this.chunkLeaf?.detach(); } catch { /* gone */ } this.chunkLeaf = null; this.chunkEl = null; this.chunkShown = "";
          try { leaf.detach(); } catch { /* gone */ }
          this.unsplit?.(); this.unsplit = null;
          if (this.browserLeaf === leaf) this.browserLeaf = null;
        };
      },
    });
    if (!existing) {
      this.stats.opened++;
      if (!this.path.startsWith("domvec-checks/")) void desk.attachToEgo(this.path);
    }
    const sv = this.slateView();
    if (sv) this.hook(sv);
    // Asked to open, it opens: a slate left collapsed to its node (its fold
    // state is remembered) is unfolded -- the browser was asked for.
    const cm: any = (sv?.editor as any)?.cm;
    if (cm) { const st = foldsOf(cm); if (st.collapsed) cm.dispatch({ effects: setFolds.of({ ...st, collapsed: false }) }); }
    if (url) await this.go(url);
    else if (!this.plantNoRestoreUrl) {
      // Opened (or restored at load) with no url asked: the slate's own url is
      // the page. The browser half sat on about:blank under a slate reading
      // frutigeraeroarchive.org/music -- the url drove the browser only on an
      // EDIT of the slate (2026-11-07, seen in a screenshot).
      const want = (this.field(this.fields(), "url")?.value || "").trim();
      const v = this.view();
      let shown = ""; try { shown = String(v?.shownUrl?.() || v?.webview?.getURL?.() || ""); } catch { /* not ready */ }
      if (/^https?:/.test(want) && (!shown || shown === "about:blank")) { this.seenUrl = want; await this.go(want); this.stats.restoredUrl++; }
    }
    return this.view();
  }

  /** Is the pair pulled apart? */
  get isSplit(): boolean { return !!this.unsplit; }

  /** Pull the browser half out of its card, or put it back (135(b)). */
  togglePair(): boolean {
    if (this.unsplit) { this.unsplit(); this.unsplit = null; this.stats.joined++; return false; }
    const leafEl: HTMLElement | undefined = this.browserLeaf?.containerEl;
    const card = leafEl?.parentElement;
    if (!leafEl || !card) return false;
    const w = card.offsetWidth; let h = Math.max(260, leafEl.offsetHeight);
    card.addClass("is-split");
    // Where the plane has room: beside the slate, else below it -- and kept
    // inside the plane (first build placed it right of a narrow pane, clipped).
    const plane = card.parentElement as HTMLElement;
    const pw = plane?.clientWidth || 1e9, ph = plane?.clientHeight || 1e9;
    const slateEl = card.querySelector(":scope > .workspace-leaf:not(.domvec-browser-panel-leaf)") as HTMLElement | null;
    const cl = card.offsetLeft, ct = card.offsetTop, ch = slateEl ? slateEl.offsetTop + slateEl.offsetHeight : 200;
    let dx = w + 60, dy = 0;
    // Below the slate, shrunk to the room left -- never back over it.
    if (cl + dx + w > pw) { dx = 0; dy = ch + 50; h = Math.max(160, Math.min(h, ph - ct - dy - 8)); }
    const clamp = () => { dx = Math.max(-cl, Math.min(dx, pw - cl - w)); dy = Math.max(-ct, Math.min(dy, ph - ct - h)); };
    clamp();
    leafEl.addClass("is-pulled");
    const place = () => { leafEl.style.left = dx + "px"; leafEl.style.top = dy + "px"; leafEl.style.width = w + "px"; leafEl.style.height = h + "px"; };
    place();
    const grip = leafEl.createDiv({ cls: "domvec-browser-grip", text: "browser ⠿" });
    leafEl.prepend(grip);
    grip.onpointerdown = (e: PointerEvent) => {
      e.preventDefault(); e.stopPropagation();
      const sx = e.clientX - dx, sy = e.clientY - dy;
      const mv = (m: PointerEvent) => { dx = m.clientX - sx; dy = m.clientY - sy; clamp(); place(); draw(); };
      const up = () => { window.removeEventListener("pointermove", mv); window.removeEventListener("pointerup", up); };
      window.addEventListener("pointermove", mv); window.addEventListener("pointerup", up);
    };
    const NS = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(NS, "svg");
    svg.classList.add("domvec-pair-link");
    const line = document.createElementNS(NS, "line");
    svg.appendChild(line);
    if (!this.plantPairNoLink) card.appendChild(svg);
    let solid = true;
    line.addEventListener("contextmenu", (e) => { e.preventDefault(); e.stopPropagation(); solid = !solid; line.setAttribute("stroke-opacity", solid ? "0.95" : "0.25"); svg.dataset.on = String(solid); });
    const draw = () => {
      // In the card's own coordinates: the slate's centre to the browser's.
      const slate = card.querySelector(":scope > .workspace-leaf:not(.domvec-browser-panel-leaf)") as HTMLElement | null;
      // Edge to edge: the facing sides of the two halves, never across either.
      const sTop = slate ? slate.offsetTop : 0, sBot = slate ? slate.offsetTop + slate.offsetHeight : 80;
      let sx: number, sy: number, bx: number, by: number;
      if (dy >= sBot) { sx = bx = Math.max(dx, 0) / 2 + Math.min(dx + w, card.offsetWidth) / 2; sy = sBot; by = dy; }
      else if (dx >= card.offsetWidth) { sy = by = (sTop + sBot) / 2; sx = card.offsetWidth; bx = dx; }
      else { sx = card.offsetWidth / 2; sy = (sTop + sBot) / 2; bx = dx + w / 2; by = dy + h / 2; }
      const x0 = Math.min(sx, bx) - 4, y0 = Math.min(sy, by) - 4;
      svg.style.left = x0 + "px"; svg.style.top = y0 + "px";
      svg.setAttribute("width", String(Math.abs(bx - sx) + 8)); svg.setAttribute("height", String(Math.abs(by - sy) + 8));
      line.setAttribute("x1", String(sx - x0)); line.setAttribute("y1", String(sy - y0));
      line.setAttribute("x2", String(bx - x0)); line.setAttribute("y2", String(by - y0));
    };
    line.setAttribute("stroke-opacity", "0.95"); svg.dataset.on = "true";
    draw();
    const ro = new ResizeObserver(draw); ro.observe(card);
    this.unsplit = () => {
      ro.disconnect(); svg.remove(); grip.remove();
      card.removeClass("is-split"); leafEl.removeClass("is-pulled");
      leafEl.style.left = leafEl.style.top = leafEl.style.width = leafEl.style.height = "";
    };
    this.stats.split++;
    return true;
  }

  /** The browser to a url, once its webview takes one (dom-ready). */
  async go(url: string): Promise<void> {
    const v = this.view();
    if (!v || typeof v.go !== "function") return;
    for (let i = 0; i < 100; i++) {
      try { v.webview?.getURL(); break; } catch { await new Promise((r) => setTimeout(r, 100)); }
    }
    try { v.go(url); this.stats.went++; } catch { /* not ready */ }
  }

  private fields(): SlateLine[] {
    const sv = this.slateView();
    return sv ? parseSlate(sv.editor.getValue()) : [];
  }
  private field(fs: SlateLine[], key: string): SlateLine | undefined {
    return fs.find((f) => f.depth === 1 && f.key === key);
  }
  private write(fl: SlateLine, value: string): void {
    const sv = this.slateView();
    if (!sv || fl.value === value) return;
    sv.editor.replaceRange(value, { line: fl.line, ch: fl.valueFrom }, { line: fl.line, ch: fl.valueFrom + fl.value.length });
    this.stats.written++;
  }

  /** A click on an action's or a toggle's VALUE: the slate is the toolbar. */
  private hook(sv: MarkdownView): void {
    const el = sv.contentEl;
    if (this.hooked.has(el)) return;
    this.hooked.add(el);
    el.addEventListener("mousedown", (e: MouseEvent) => {
      if (e.button !== 0 || this.plantUnbound) return;
      const cm: any = (sv.editor as any).cm;
      const pos = cm?.posAtCoords?.({ x: e.clientX, y: e.clientY });
      if (pos == null) return;
      const ln = cm.state.doc.lineAt(pos);
      const fl = this.fields().find((f) => f.line === ln.number - 1 && f.depth === 1);
      if (!fl) return;
      const ch = pos - ln.from;
      if (!(ch >= fl.valueFrom && ch <= fl.valueFrom + fl.value.length && fl.value.length)) return;
      const v = this.view();
      if (!v) return;
      const val = fl.value.trim();
      let acted = true;
      if (fl.key === "back") { const w = v.webview; if (w?.canGoBack?.()) { w.goBack(); this.stats.back++; } }
      else if (fl.key === "forward") { const w = v.webview; if (w?.canGoForward?.()) { w.goForward(); this.stats.forward++; } }
      else if (fl.key === "scan") { void v.scan?.(); this.stats.scans++; }
      else if (val === "true" || val === "false") { this.write(fl, val === "true" ? "false" : "true"); this.stats.toggles++; }
      else if (fl.key === "scope") { this.write(fl, LADDER[(Math.max(0, LADDER.indexOf(val as any)) + 1) % LADDER.length]); this.stats.toggles++; }
      else acted = false;
      if (acted) { e.preventDefault(); e.stopPropagation(); }
    }, true);
  }

  /** The text read: an edit in the cockpit drives the browser. */
  onEdit(file: TFile | null): void {
    if (!file || file.path !== this.path || this.plantUnbound) return;
    const v = this.view();
    if (!v) return;
    const fs = this.fields();
    const url = (this.field(fs, "url")?.value || "").trim();
    const shown = String(v.shownUrl?.() || v.webview?.getURL?.() || "");
    if (url && /^(https?:|file:|about:)/.test(url) && url !== shown && url !== this.seenUrl) { this.seenUrl = url; void this.go(url); }
    const live = (this.field(fs, "live")?.value || "").trim();
    if ((live === "true" || live === "false") && (live === "true") !== !!v.live) v.setLive?.(live === "true");
    const boxes = (this.field(fs, "boxes")?.value || "").trim();
    if ((boxes === "true" || boxes === "false") && (boxes === "true") !== !!v.boxesShown?.()) void v.toggleBoxes?.(boxes === "true");
    const scope = (this.field(fs, "scope")?.value || "").trim();
    // Only a CHANGE of scope acts. The first read of the note is not one: it
    // swapped the live page for the saved copy in temp whenever the reader
    // first typed into the control markdown (2026-11-07). Planted
    // `plantScopeFirstRead`: the first read acts, as before.
    if (scope && !this.stats.scope && !this.plantScopeFirstRead) { this.stats.scope = scope; return; }
    if (scope && scope !== this.stats.scope) {
      this.stats.scope = scope;
      // The ladder's upper rungs (item 72): the page rebuilt from the store,
      // or the live page again -- the same address either way.
      if (scope === "page" && !v.offlineFor) void v.openOffline?.(shown);
      else if (scope === "live" && v.offlineFor) { const u = v.offlineFor; v.offlineFor = ""; v.go(u); }
    }
  }

  /** The browser's own state written back: where it is now, what is on. */
  sync(): void {
    if (this.plantUnbound) return;
    const v = this.view(), sv = this.slateView();
    if (!v || !sv) return;
    const fs = this.fields();
    const shown = String(v.offlineFor || v.shownUrl?.() || "");
    // `scope` is a declared state, kept: `page` until the store can rebuild
    // the page (a page just visited may not be stored yet), `live` otherwise.
    const scope = (this.field(fs, "scope")?.value || "").trim();
    const now = performance.now();
    // The chunk rung in the browser's place; any other rung, the browser.
    const chunk = scope === "chunk";
    if (this.chunkEl && this.browserLeaf) {
      this.chunkEl.style.display = chunk ? "" : "none";
      // 137(4): the chunk rung is a BROWSER cell framed on the chunk, with its
      // markdown beneath -- not the markdown in the browser's place. Planted
      // `plantChunkMarkdownOnly`: the browser hidden, as before.
      this.browserLeaf.containerEl.style.display = chunk && this.plantChunkMarkdownOnly ? "none" : "";
      if (chunk) {
        void this.showChunk(v);
        // The page reflows under a frame (lazy images, late fonts): the frame
        // follows the chunk, re-read each second -- a clip set once drifted
        // off the chunk within seconds on Wikipedia's B-tree page.
        if (this.framed && !this.plantChunkMarkdownOnly && now - this.frameAt > 1000) { this.frameAt = now; void this.reframe(v); }
      } else if (this.framed || this.chunkShown) this.unframe(v);
    }
    if (scope === "page" && !v.offlineFor && now - this.scopeTry > 3000) {
      this.scopeTry = now;
      const u = String(v.shownUrl?.() || v.webview?.getURL?.() || "");
      if (/^https?:/.test(u)) void v.openOffline?.(u);
    }
    const urlF = this.field(fs, "url");
    if (urlF && shown && shown !== "about:blank" && urlF.value.trim() !== shown && shown !== this.seenUrl) {
      this.seenUrl = shown;
      this.write(urlF, shown);
    }
  }

  /** One rung along the ladder: written into the slate's `scope` field, which
   *  `sync` then keeps (the field is the state; the gesture only edits it). */
  ladderSteps = 0;
  step(dir: -1 | 1): string {
    const fs = this.fields(), fl = this.field(fs, "scope");
    if (!fl) return "";
    const at = Math.max(0, LADDER.indexOf((fl.value.trim() || "live") as any));
    const next = LADDER[Math.max(0, Math.min(LADDER.length - 1, at + dir))];
    this.write(fl, next);
    this.ladderSteps++;
    return next;
  }

  /** The chunk rung shown: the chunk the reader last hovered in the browser,
   *  else the page's first -- through the `domvec` fence, so it is the same
   *  interactive surface a chunk note draws. */
  private async showChunk(v: any): Promise<void> {
    if (!this.chunkEl) return;
    const h = v.lastHovered;
    let cid = h ? String(h.stored || h.cid || "") : "";
    if (!cid) {
      // The page's own address -- on the page rung the view shows the page
      // REBUILT, whose own url is not the page's (`offlineFor` is).
      const url = String(v.offlineFor || v.shownUrl?.() || "");
      const cids = url ? await v.sidecar?.pageCids?.(url) : [];
      cid = (cids && cids[0]) || "";
    }
    if (!cid || cid === this.chunkShown) return;
    this.chunkShown = cid;
    if (!this.plantChunkMarkdownOnly) void this.frame(v, cid);
    // PLUGIN_GOAL 140(a): "I should only see one unified markdown panel. This
    // panel format is deprecated." -- and 133(c): ONE markdown panel, the same
    // code for a billboard's markdown half, a code panel and a notebook cell,
    // with every special feature. So the chunk's markdown is its note
    // (`domvec/chunks/<cid>.md`, as a billboard's) in a real editor leaf, never
    // the fenced `domvec` block with its markdown / shadow-DOM toggle.
    // Planted `plantChunkFencedBlock`: the old block.
    this.chunkComp?.unload();
    this.chunkComp = new Component();
    this.chunkComp.load();
    try { this.chunkLeaf?.detach(); } catch { /* gone */ }
    this.chunkLeaf = null;
    this.chunkEl.empty();
    const NL = "\n";
    if (this.plantChunkFencedBlock) {
      await MarkdownRenderer.render(this.app, "```domvec" + NL + "cid: " + cid + NL + "```", this.chunkEl, this.path, this.chunkComp);
      return;
    }
    const pay: any = await v.sidecar?.chunk?.(cid);
    if (this.chunkShown !== cid || !this.chunkEl) return;
    if (pay?.xpath) this.chunkAddr.set(cid, { url: pay.url, xpath: pay.xpath });
    const md = ((pay && pay.lines) || []).map((l: any) => String(l.text ?? "")).join(NL);
    const folder = "domvec/chunks", path = `${folder}/${cid.replace(/[^\w.-]+/g, "_")}.md`;
    const vault = this.app.vault;
    if (!vault.getAbstractFileByPath(folder)) await vault.createFolder(folder).catch(() => undefined);
    let f: any = vault.getAbstractFileByPath(path);
    if (!f) f = await vault.create(path, md);
    const Leaf: any = (this.app.workspace as any).activeLeaf?.constructor ?? (this.app.workspace.getMostRecentLeaf() as any)?.constructor;
    if (!Leaf || this.chunkShown !== cid || !this.chunkEl) return;
    const leaf = new Leaf(this.app);
    leaf.containerEl.addClass("domvec-browser-chunk-leaf");
    this.chunkEl.appendChild(leaf.containerEl);
    await leaf.openFile(f, chunkNoteState(f.path));
    this.chunkLeaf = leaf;
  }

  /** The chunk the browser is framed on, and its frame (host px), while framed. */
  framed: { cid: string; xpath: string; rect: { top: number; left: number; width: number; height: number } } | null = null;
  plantChunkMarkdownOnly = false;
  plantChunkFencedBlock = false;
  private chunkLeaf: any = null;
  private chunkAddr = new Map<string, { url: string; xpath: string }>();
  /** Frame the live browser on one chunk: clipped in OUR element (the webview
   *  tag), never in the page; the page stays live and interactive within it. */
  private async frame(v: any, cid: string): Promise<void> {
    // The chunk's address, asked once per cid: the store is busy while the
    // browser captures (a /chunk took 1.8 s, /health 10 s, live).
    let pay: any = this.chunkAddr.get(cid);
    if (!pay) { pay = await v.sidecar?.chunk?.(cid); if (pay?.xpath) this.chunkAddr.set(cid, { url: pay.url, xpath: pay.xpath }); }
    const wv: HTMLElement | null = v?.webview || null;
    if (!pay || !pay.xpath || !wv) return;
    let shown = ""; try { shown = String(v.shownUrl?.() || (wv as any).getURL()); } catch { /* */ }
    const key = (u: string) => { try { const x = new URL(u); return x.host + x.pathname.replace(/\/$/, ""); } catch { return u; } };
    if (key(pay.url) !== key(shown)) { await this.go(pay.url); await new Promise((r) => setTimeout(r, 2500)); }
    const rect = await v.chunkFrame?.(pay.xpath);
    if (this.chunkShown !== cid) return;
    // Not found yet (the page still loading): asked again on the next sync.
    if (!rect) { this.chunkShown = ""; return; }
    this.clipTo(wv, rect);
    this.framed = { cid, xpath: pay.xpath, rect };
    this.stats.framed = (this.stats.framed || 0) + 1;
  }
  private frameAt = 0;
  async reframe(v: any): Promise<void> {
    const f = this.framed, wv: HTMLElement | null = v?.webview || null;
    if (!f || !wv) return;
    const rect = await v.chunkFrame?.(f.xpath);
    if (!rect || this.framed !== f) return;
    this.clipTo(wv, rect); f.rect = rect;
  }
  private clipTo(wv: HTMLElement, rect: { top: number; left: number; width: number; height: number }): void {
    const W = wv.clientWidth, H = wv.clientHeight;
    const top = Math.max(0, rect.top), left = Math.max(0, rect.left);
    const bottom = Math.max(0, H - (rect.top + rect.height)), right = Math.max(0, W - (rect.left + rect.width));
    wv.style.clipPath = `inset(${top}px ${right}px ${bottom}px ${left}px)`;
    wv.classList.add("domvec-chunk-framed");
  }
  private unframe(v: any): void {
    const wv: HTMLElement | null = v?.webview || null;
    if (wv) { wv.style.clipPath = ""; wv.classList.remove("domvec-chunk-framed"); }
    this.framed = null; this.chunkShown = "";
  }

  close(): void { this.host.desk.closePath(this.path); }
}
