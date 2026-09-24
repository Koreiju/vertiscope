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

import type { Sidecar } from "./sidecar";
import { profiler } from "./profile";

/** The xpath of an element, by the trie's convention (see `portMarkdown`). */
const XPATH_OF = "var parts=[];" +
  "while(el && el.nodeType===1 && el.tagName){" +
  "var tag=el.tagName.toLowerCase(),i=1,sib=el.previousElementSibling;" +
  "while(sib){if(sib.tagName===el.tagName)i++;sib=sib.previousElementSibling;}" +
  "parts.unshift(i>1?tag+'['+i+']':tag);el=el.parentElement;}" +
  "return '/'+parts.join('/');";

export interface HoverState {
  xpath: string;
  cid: string;
  matched: string;
  walked: number;
  rect: { x: number; y: number; w: number; h: number } | null;
  lines: number;
  at: number;
}

export class PipelineBox {
  readonly el: HTMLElement;
  private mini: HTMLElement;
  private full: HTMLElement;
  private outline: HTMLElement;
  private expanded = false;
  private timer = 0;
  private hoverTimer = 0;
  private status: any = null;
  private statusUrl = "";
  private lastStatusPoll = 0;
  private hoverBusy = false;
  private resolved = new Map<string, { cid: string; matched: string; walked: number; lines: number }>();
  hover: HoverState | null = null;

  constructor(private wrap: HTMLElement, private sidecar: Sidecar,
              private webview: () => any,
              private onHoverChunk: (cid: string, url: string) => void) {
    this.outline = wrap.createDiv({ cls: "domvec-chunk-outline" });
    this.outline.hide();
    this.el = wrap.createDiv({ cls: "domvec-pipebox" });
    this.mini = this.el.createDiv({ cls: "domvec-pipebox-mini" });
    this.full = this.el.createDiv({ cls: "domvec-pipebox-full" });
    this.full.hide();
    this.el.addEventListener("mouseenter", () => { this.expanded = true; this.draw(); });
    this.el.addEventListener("mouseleave", () => { this.expanded = false; this.draw(); });
    this.timer = window.setInterval(() => void this.tick(), 1000);
    // Hover is polled rather than listened for: mouse events over a webview
    // go to the GUEST, and listening there would mean installing a handler
    // in the page. Reading `:hover` five times a second installs nothing.
    this.hoverTimer = window.setInterval(() => void this.pollHover(), 200);
    this.draw();
  }

  destroy() {
    window.clearInterval(this.timer);
    window.clearInterval(this.hoverTimer);
    this.el.remove();
    this.outline.remove();
  }

  private url(): string {
    try { return this.webview()?.getURL() || ""; } catch { return ""; }
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
    if (url && url !== "about:blank" &&
        (url !== this.statusUrl || now - this.lastStatusPoll >= every)) {
      this.lastStatusPoll = now;
      this.statusUrl = url;
      this.status = await this.sidecar.pageStatus(url).catch(() => null);
    }
    this.draw();
  }

  // ---- hover --------------------------------------------------------------

  private async pollHover() {
    const wv = this.webview();
    if (!wv || this.hoverBusy || !this.visible()) return;
    this.hoverBusy = true;
    try {
      const got = await wv.executeJavaScript(
        "(function(){var hs=document.querySelectorAll(':hover');" +
        "if(!hs.length) return null;var el=hs[hs.length-1];" +
        XPATH_OF.replace("return", "var xp=") +
        "return xp;})()").catch(() => null);
      const xpath = typeof got === "string" ? got : "";
      if (!xpath) { this.clearHover(); return; }
      const url = this.url();
      let hit = this.resolved.get(xpath);
      if (!hit) {
        const r: any = await this.sidecar.resolve(url, xpath).catch(() => null);
        if (!r || !r.cid) { this.clearHover(); return; }
        hit = { cid: String(r.cid), matched: String(r.matched_xpath || xpath),
                walked: Number(r.ancestors_walked || 0),
                lines: (r.lines || []).length };
        if (this.resolved.size > 400) this.resolved.clear();
        this.resolved.set(xpath, hit);
      }
      // The CHUNK's box, not the hovered leaf's: the reader is pointing at a
      // word and the thing the trie holds is the section around it.
      const rect = await wv.executeJavaScript(
        "(function(){var n=document.evaluate(" + JSON.stringify(hit.matched) +
        ",document,null,XPathResult.FIRST_ORDERED_NODE_TYPE,null).singleNodeValue;" +
        "if(!n) return null;if(n.nodeType===3)n=n.parentElement;if(!n) return null;" +
        "var b=n.getBoundingClientRect();return {x:b.left,y:b.top,w:b.width,h:b.height};})()")
        .catch(() => null);
      const changed = !this.hover || this.hover.cid !== hit.cid;
      this.hover = { xpath, cid: hit.cid, matched: hit.matched, walked: hit.walked,
                     rect: rect || null, lines: hit.lines, at: performance.now() };
      this.placeOutline();
      if (changed) this.onHoverChunk(hit.cid, url);
      if (this.expanded) this.draw();
    } finally {
      this.hoverBusy = false;
    }
  }

  private clearHover() {
    if (!this.hover) return;
    this.hover = null;
    this.outline.hide();
    this.onHoverChunk("", "");
    if (this.expanded) this.draw();
  }

  /** The outline sits in the CELL over the webview, never in the page. */
  private placeOutline() {
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
      let chunks = 0, hub = false, hovered = false;
      for (const n of nodes) {
        if (n.url !== url) continue;
        if (n.level === "page") hub = true;
        else chunks++;
        if (this.hover && n.id === this.hover.cid) hovered = true;
      }
      return { chunks, hub, hovered };
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
    const dot = this.mini.createSpan({ cls: "domvec-pipebox-dot" });
    dot.addClass(!s ? "is-idle" : healthy ? "is-ok" : "is-warn");
    if (!s || !url || url === "about:blank") {
      this.mini.createSpan({ text: "pipeline idle" });
    } else {
      const parts: string[] = [];
      if (lastSeen) parts.push(fmt(lastSeen.stages.end_to_end));
      parts.push(`${proj ? proj.chunks : "?"}/${drawable} in graph`);
      this.mini.createSpan({ text: parts.join(" · ") });
    }

    if (!this.expanded) { this.full.hide(); return; }
    this.full.show();
    this.full.empty();
    if (!s) {
      this.full.createDiv({ cls: "domvec-pipebox-muted",
        text: url && url !== "about:blank" ? "asking the sidecar…" : "no page loaded" });
      return;
    }

    // ---- the chain every chunk travels ------------------------------------
    this.section("This page's chunks");
    const chain = this.full.createDiv({ cls: "domvec-pipebox-chain" });
    const step = (label: string, n: number | string, of: number, ok: boolean) => {
      const c = chain.createDiv({ cls: `domvec-pipebox-step ${ok ? "is-ok" : "is-warn"}` });
      c.createDiv({ cls: "domvec-pipebox-n", text: String(n) });
      c.createDiv({ cls: "domvec-pipebox-l", text: label });
      if (typeof n === "number" && of) c.title = `${n} of ${of}`;
    };
    step("stored", s.chunks, s.chunks, s.empty_md === 0);
    step("embedded", s.embedded, s.chunks, s.embedded >= s.chunks);
    step("projected", s.projected ?? "?", drawable,
         typeof s.projected === "number" && s.projected >= drawable);
    step("in graph", proj ? proj.chunks : "?", drawable, !!proj && proj.chunks >= drawable);
    step("page hub", proj ? (proj.hub ? "yes" : "no") : "?", 0, !!proj && proj.hub);
    if (s.empty_md) this.line(`${s.empty_md} chunks stored with no markdown`, true);
    if (proj && !proj.hub) this.line("chunks are in the graph with no page node to hang from", true);

    this.line(`window ${s.window} tokens · chunk p50 ${s.tokens_p50}, max ${s.tokens_max}` +
              (s.over_window ? ` · ${s.over_window} OVER the window` : " · none over"),
              s.over_window > 0);

    // ---- the last drain ----------------------------------------------------
    if (last) {
      this.section(`Last drain · ${String(last.facts?.outcome || "?")}` +
                   (last.facts?.why ? ` (${last.facts.why})` : ""));
      const st = last.stages || {};
      const strip = this.full.createDiv({ cls: "domvec-pipebox-strip" });
      for (const [k, label] of [
        ["fold", "fold"], ["sidecar.absorb", "trie"], ["sidecar.render", "markdown"],
        ["sidecar.store", "store"], ["vector_wait", "embed"], ["sidecar.place", "place"],
        ["visible", "drawn"], ["end_to_end", "total"],
      ] as [string, string][]) {
        if (typeof st[k] !== "number") continue;
        const cell = strip.createDiv({ cls: "domvec-pipebox-cell" });
        cell.createDiv({ cls: "domvec-pipebox-n", text: fmt(st[k]) });
        cell.createDiv({ cls: "domvec-pipebox-l", text: label });
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
      const bar = this.full.createDiv({ cls: "domvec-pipebox-growth" });
      const fill = bar.createDiv({ cls: "domvec-pipebox-growthfill" });
      fill.style.width = `${Math.min(100, (growth / 2) * 100)}%`;
      this.line(`${s.chunks_now.toLocaleString()} chunks against ${s.fitted_chunks.toLocaleString()} ` +
                `fitted · ${growth.toFixed(2)}× of the 2× refit` +
                (s.stale ? " · REFIT DUE" : ""), !!s.stale);
      this.line(`this page's anchor: ${s.anchor}` +
                (s.anchor === "estimated" ? " (placed into the fit, refit will fit it)" : ""),
                s.anchor === "none");
    } else {
      this.line("no fit in this process yet — open the graph", true);
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

  private section(title: string) {
    this.full.createDiv({ cls: "domvec-pipebox-h", text: title });
  }

  private line(text: string, warn = false, muted = false) {
    this.full.createDiv({
      cls: `domvec-pipebox-line${warn ? " is-warn" : ""}${muted ? " domvec-pipebox-muted" : ""}`,
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
