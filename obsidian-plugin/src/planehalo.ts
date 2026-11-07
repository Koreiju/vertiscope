/**
 * The halo that slides -- 2D only, ego only (PLUGIN_GOAL 81-84, 2026-11-01:
 * "when we click on a computation graph artifact (either node or panel form),
 * we see a polar-coordinate force-directed layout on similarity-based
 * proximity diffs local to the node. So, radial coordinates are similarity to
 * the node ... and angular coordinates in 2D are the lateral retrieved result
 * similarities to each other"; RESERVOIR_DESIGN 10.10).
 *
 * Opened by a click on a panel's header node (no drag); Escape, or the same
 * click, closes it. The focus is that panel's note; its retrieval is the EGO's
 * (`/search?where=ego`), cut to the results that can be RENDERED around the
 * ring ("only the top-most renderable retrieval results ever call this
 * layout").
 *
 * Layout: radius `r0 + (1 - s / s_max) * R` (s the additive score against the
 * focus -- links count through its PageRank term); angle from the results'
 * own pairwise similarity: chained greedily by similarity, spread evenly in
 * that order, then relaxed -- similar results pulled together, any two closer
 * than a node's width pushed apart.
 *
 * Sliding: with the pointer OUTSIDE the focus's card, its motion moves a
 * cursor over the layout -- by the pointer's own delta (moving back retraces),
 * with a gain that grows with speed, so a fast short stroke travels as a slow
 * long one does (my reading, RESERVOIR_DESIGN 9.8). The result nearest the
 * cursor is the navigated one, lit, with the shortest path back to the focus
 * over the halo's similarity graph traced. A click sticks it: its note opened
 * on the plane where it sits.
 */
import { App, TFile } from "obsidian";
import type { PlaneDesk } from "./planepanels";
import type { Sidecar } from "./sidecar";

interface HNode { key: string; url: string; cid: string; label: string; preview: string; kind: string; s: number; r: number; theta: number; x: number; y: number }

export interface HaloHost { app: App; desk: PlaneDesk; sidecar: () => Sidecar | null; plane: () => HTMLElement | null }

const SVG = "http://www.w3.org/2000/svg";

export class PlaneHalo {
  focus = "";
  nodes: HNode[] = [];
  sim: number[][] = [];
  cursor = { x: 0, y: 0 };
  navigated = -1;
  trace: number[] = [];
  stats = { opened: 0, closed: 0, results: 0, laid: 0, slides: 0, travelled: 0, navigated: 0, stuck: 0, last_stuck: "",
            r0: 0, R: 0, cap: 0, neighbour_sim: 0, random_sim: 0, rekeyed: 0 };
  /** Planted (item 81): angles in the retrieval's rank order, the lateral similarity ignored. */
  plantRankAngles = false;
  private svg: SVGSVGElement | null = null;
  private centre = { x: 0, y: 0 };
  private lastMove = { x: 0, y: 0, t: 0 };
  private onMove = (e: PointerEvent) => { this.mouse = { x: e.clientX, y: e.clientY }; if (this.plantDeltaSlide) this.slide(e); };
  /** PLUGIN_GOAL 134(g): "the nodes slide over their deltas per the mouse's
   *  proximity from the invisible fixed origin ... and the motion velocity
   *  vector is the magnitude of the mouse from the origin" -- a joystick, not
   *  a drag. Planted `plantDeltaSlide`: the pointer's own deltas, as before. */
  plantDeltaSlide = false;
  /** Planted (134g): the other panels stay open while "similar" runs. */
  plantNoFold = false;
  private mouse = { x: -1, y: -1 };
  private raf = 0;
  private lastTick = 0;
  private folded: string[] = [];
  drift = { ticks: 0, travelled: 0, culled: 0 };
  private tick = (t: number) => {
    if (!this.focus) return;
    this.raf = window.requestAnimationFrame(this.tick);
    const plane = this.host.plane(), p = this.host.desk.panelOf(this.focus);
    const dt = this.lastTick ? Math.min(64, t - this.lastTick) : 16; this.lastTick = t;
    if (!plane || !p || this.mouse.x < 0 || this.plantDeltaSlide) return;
    const pr = plane.getBoundingClientRect(), cr = p.card.getBoundingClientRect();
    if (this.mouse.x >= cr.left && this.mouse.x <= cr.right && this.mouse.y >= cr.top && this.mouse.y <= cr.bottom) return;
    const ox = this.mouse.x - pr.left - this.centre.x, oy = this.mouse.y - pr.top - this.centre.y;
    const k = 0.0025 * dt;                       // velocity = offset from the origin
    const lim = this.stats.r0 + this.stats.R + 30;
    let x = this.cursor.x + ox * k, y = this.cursor.y + oy * k;
    const dx = x - this.centre.x, dy = y - this.centre.y, d = Math.hypot(dx, dy);
    if (d > lim) { x = this.centre.x + (dx / d) * lim; y = this.centre.y + (dy / d) * lim; }
    const step = Math.hypot(x - this.cursor.x, y - this.cursor.y);
    if (step < 0.05) return;
    this.cursor = { x, y }; this.drift.ticks++; this.drift.travelled += step; this.stats.slides++;
    this.navigate(); this.draw(plane);
  };
  private onDown = (e: PointerEvent) => this.stick(e);
  private onKey = (e: KeyboardEvent) => { if (e.key === "Escape" && this.focus) this.close(); };

  constructor(private host: HaloHost) {}

  /** The header node clicked: the halo of that panel, or closed if it is open. */
  async toggle(path: string): Promise<boolean> {
    if (this.focus === path) { this.close(); return false; }
    return this.open(path);
  }

  /** `query`: the soft-link field's text (item 90) in place of the note's own words. */
  async open(path: string, query = ""): Promise<boolean> {
    this.close();
    const sc = this.host.sidecar(), plane = this.host.plane(), p = this.host.desk.panelOf(path);
    const f = this.host.app.vault.getAbstractFileByPath(path);
    if (!sc || !plane || !p || !(f instanceof TFile)) return false;
    this.focus = path;
    this.stats.opened++;
    // The type graph's ranks (G-317), once: what each code kind weighs.
    if (!this.typeRank) {
      try {
        const got: any = await (sc as any).get("/typegraph");
        if (got && got.ready && got.ranks) this.typeRank = got.ranks;
      } catch { /* the term then weighs every kind 1 */ }
    }
    // The focus's place: its header node's centre, in plane coordinates.
    const pr = plane.getBoundingClientRect();
    const head = (p.card.querySelector(".domvec-plane-head-node, .domvec-var-title") as HTMLElement | null) || p.card;
    const hr = head.getBoundingClientRect();
    this.centre = { x: hr.left + hr.width / 2 - pr.left, y: hr.top + hr.height / 2 - pr.top };
    // How many can be rendered: the ring's circumference over a node's width.
    const R = Math.max(90, Math.min(pr.width, pr.height) * 0.32), r0 = 54, slot = 96;
    const cap = Math.max(3, Math.min(16, Math.floor((2 * Math.PI * (r0 + R * 0.6)) / slot)));
    this.stats.r0 = r0; this.stats.R = Math.round(R); this.stats.cap = cap;
    // The ego's retrieval for the note's own words.
    const text = query.trim() ? query.trim() : (await this.host.app.vault.cachedRead(f)).replace(/^---[\s\S]*?\n---\n?/, "").replace(/[`{}#>*_]/g, " ").trim().slice(0, 240);
    const url = "vault://" + this.host.app.vault.getName() + "/" + path;
    const got: any = await sc.search(text || f.basename, { k: 3 * cap + 1, where: "ego" });
    if (this.focus !== path) return false;
    this.focusKey = url; this.history = [];
    this.focusKind = this.kindOf(url);
    const hits = this.strict(((got && got.hits) || []).filter((h: any) => h.url !== url)).slice(0, cap);
    await this.place(hits);
    if (this.focus !== path) return false;
    this.cursor = { ...this.centre };
    this.navigated = -1; this.trace = [];
    this.draw(plane);
    window.addEventListener("pointermove", this.onMove, true);
    window.addEventListener("pointerdown", this.onDown, true);
    window.addEventListener("keydown", this.onKey, true);
    // The rest of the plane folds onto the query (134g), back on close.
    this.folded = [];
    if (!this.plantNoFold) for (const q of this.host.desk.panels) {
      if (q.path === path || q.card.hasClass("is-collapsed")) continue;
      this.host.desk.toggleMinimized(q.path); this.folded.push(q.path);
    }
    this.lastTick = 0; this.raf = window.requestAnimationFrame(this.tick);
    return true;
  }

  /** Results laid out round the current centre: radius by similarity, angle
   *  by the results' own similarity to one another. */
  private async place(hits: any[]): Promise<void> {
    const sc = this.host.sidecar()!;
    const r0 = this.stats.r0, R = this.stats.R;
    this.stats.results = hits.length;
    const top = Math.max(1e-9, ...hits.map((h: any) => Number(h.score) || 0));
    const vault = "vault://" + this.host.app.vault.getName() + "/";
    this.nodes = hits.map((h: any) => {
      const s = Math.max(0, Number(h.score) || 0) / top;
      const isNote = String(h.url || "").startsWith("vault://");
      const label = isNote ? String(h.url).split("/").pop()!.replace(/\.md$/, "") : String(h.preview || h.cid).split("\n")[0].slice(0, 24);
      const url = String(h.url || "");
      // TYPE-AWARE similarity (PLUGIN_GOAL 92: "of the similar most datatype
      // and layer of abstraction"): the result's kind against the focus's,
      // as one more additive term (0.2 of it, re-normalized).
      const kind = this.kindOf(url);
      // Weighted by the type graph's PageRank (G-317): a kind central to the
      // code's structure counts for more than a peripheral one.
      const t = this.plantNoTypeTerm ? 0 : this.typeMatch(this.focusKind, kind) * this.rankOf(kind);
      const s2 = this.plantNoTypeTerm ? s : 0.8 * s + 0.2 * t;
      return { key: isNote ? url : String(h.cid), url, cid: String(h.cid || ""), label, kind,
               preview: String(h.preview || ""), s: s2, r: r0 + (1 - s2) * R, theta: 0, x: 0, y: 0 };
    });
    void vault;
    // Lateral similarity, from the store.
    const pw: any = this.nodes.length > 1 ? await sc.egoPost("ego/pairwise" as any, { keys: this.nodes.map((n) => n.key) }) : null;
    const at = new Map<string, number>(((pw && pw.keys) || []).map((k: string, i: number) => [k, i]));
    this.sim = this.nodes.map((a) => this.nodes.map((b) => {
      const i = at.get(a.key), j = at.get(b.key);
      return i !== undefined && j !== undefined ? Number(pw.sim[i][j]) : 0;
    }));
    this.layout();
  }

  /** Angles: chained by similarity, spread, then relaxed. */
  private layout(): void {
    const n = this.nodes.length;
    if (!n) return;
    let order = this.nodes.map((_, i) => i);
    if (!this.plantRankAngles && n > 2) {
      // Greedy chain from the most similar to the focus.
      const left = new Set(order);
      let cur = 0; order = [cur]; left.delete(cur);
      while (left.size) {
        let best = -1, bs = -1;
        for (const j of left) if (this.sim[cur][j] > bs) { bs = this.sim[cur][j]; best = j; }
        order.push(best); left.delete(best); cur = best;
      }
    }
    order.forEach((i, k) => { this.nodes[i].theta = (2 * Math.PI * k) / n - Math.PI / 2; });
    if (!this.plantRankAngles && n > 2) {
      const minSep = 64;
      for (let it = 0; it < 40; it++) {
        for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++) {
          const a = this.nodes[i], b = this.nodes[j];
          let d = b.theta - a.theta; d = Math.atan2(Math.sin(d), Math.cos(d));
          const rm = (a.r + b.r) / 2, arc = Math.abs(d) * rm;
          // Pulled by similarity (above the set's mean), pushed under a node's width.
          const pull = 0.01 * (this.sim[i][j] - 0.5) * d;
          const push = arc < minSep ? 0.04 * Math.sign(d || 1) * (minSep - arc) / rm : 0;
          a.theta += pull - push; b.theta -= pull - push;
        }
      }
    }
    for (const h of this.nodes) { h.x = this.centre.x + h.r * Math.cos(h.theta); h.y = this.centre.y + h.r * Math.sin(h.theta); }
    this.stats.laid++;
    // How lateral similarity shows: angular neighbours vs any two.
    const byAngle = this.nodes.map((h, i) => ({ i, t: Math.atan2(Math.sin(h.theta), Math.cos(h.theta)) })).sort((a, b) => a.t - b.t);
    let nb = 0, nn = 0, all = 0, na = 0;
    for (let k = 0; k < byAngle.length; k++) { const i = byAngle[k].i, j = byAngle[(k + 1) % byAngle.length].i; if (i !== j) { nb += this.sim[i][j]; nn++; } }
    for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++) { all += this.sim[i][j]; na++; }
    this.stats.neighbour_sim = nn ? Math.round((nb / nn) * 1000) / 1000 : 0;
    this.stats.random_sim = na ? Math.round((all / na) * 1000) / 1000 : 0;
  }

  /** The pointer's motion outside the focus card: a cursor over the layout. */
  private slide(e: PointerEvent): void {
    const plane = this.host.plane(), p = this.host.desk.panelOf(this.focus);
    if (!plane || !p) return;
    const t = performance.now();
    const dx = e.clientX - this.lastMove.x, dy = e.clientY - this.lastMove.y, dt = Math.max(1, t - this.lastMove.t);
    const fresh = t - this.lastMove.t > 250;
    this.lastMove = { x: e.clientX, y: e.clientY, t };
    if (fresh) return;                                   // a new stroke starts here
    const cr = p.card.getBoundingClientRect();
    if (e.clientX >= cr.left && e.clientX <= cr.right && e.clientY >= cr.top && e.clientY <= cr.bottom) return;
    const v = Math.hypot(dx, dy) / dt;                   // px per ms
    // Speed scales the step: a fast short stroke travels as far as a slow
    // long one (item 82), within bounds.
    const gain = Math.max(0.3, Math.min(4, v / 0.15));
    const lim = this.stats.r0 + this.stats.R + 30;
    let x = this.cursor.x + dx * gain * 0.6, y = this.cursor.y + dy * gain * 0.6;
    const ox = x - this.centre.x, oy = y - this.centre.y, d = Math.hypot(ox, oy);
    if (d > lim) { x = this.centre.x + (ox / d) * lim; y = this.centre.y + (oy / d) * lim; }
    this.stats.travelled += Math.hypot(x - this.cursor.x, y - this.cursor.y);
    this.cursor = { x, y };
    this.stats.slides++;
    this.navigate();
    this.draw(plane);
  }

  /** The navigated result: nearest the cursor, within reach; its path traced.
   *  Rested on (0.6 s), it becomes the new retrieval key (item 91). */
  navigate(): void {
    let best = -1, bd = 46;
    this.nodes.forEach((h, i) => { const d = Math.hypot(h.x - this.cursor.x, h.y - this.cursor.y); if (d < bd) { bd = d; best = i; } });
    if (best !== this.navigated) {
      if (best >= 0) this.stats.navigated++;
      window.clearTimeout(this.dwell);
      if (best >= 0 && !this.plantNoRekey) { const at = best; this.dwell = window.setTimeout(() => { if (this.navigated === at) void this.rekey(at); }, 600); }
    }
    this.navigated = best;
    this.trace = best >= 0 ? this.shortestPath(best) : [];
  }

  /** Foci passed through, oldest first: the trace back runs through them. */
  history: { key: string; x: number; y: number }[] = [];
  /** Planted (item 91): the layout never re-forms round the navigated node. */
  plantNoRekey = false;
  private dwell = 0;
  /** The navigated node as the new FOCUS (item 91): its own ego retrieval laid
   *  out round it -- same datatype ranks nearer through the additive score --
   *  the foci already passed through left out, the trace extended. */
  async rekey(i: number): Promise<boolean> {
    const sc = this.host.sidecar(), plane = this.host.plane(), h = this.nodes[i];
    if (!sc || !plane || !h) return false;
    this.history.push({ key: this.focusKey || this.focus, x: this.centre.x, y: this.centre.y });
    this.focusKey = h.key;
    this.focusKind = h.kind || this.kindOf(h.url);
    this.centre = { x: h.x, y: h.y };
    const seen = new Set(this.history.map((q) => q.key).concat([h.key, "vault://" + this.host.app.vault.getName() + "/" + this.focus]));
    const got: any = await sc.search((h.preview || h.label).slice(0, 240), { k: 3 * this.stats.cap + seen.size, where: "ego" });
    const hits = this.strict(((got && got.hits) || []).filter((x: any) => !seen.has(String(x.url).startsWith("vault://") ? String(x.url) : String(x.cid)))).slice(0, this.stats.cap);
    await this.place(hits);
    this.cursor = { ...this.centre };
    this.navigated = -1; this.trace = [];
    this.stats.rekeyed++;
    this.draw(plane);
    return true;
  }
  /** The key of the current focus (the opened panel's note, or a re-keyed node). */
  focusKey = "";
  /** The focus's kind (item 92): what like-kinds sit nearer to. */
  focusKind = "";
  /** Planted (item 92): kind plays no part. */
  plantNoTypeTerm = false;
  /**
   * TYPE-STRICT (PLUGIN_GOAL 113, G-330: "remaining type-strict in our panel
   * representations and interactions with the per-node-type ... retrieval
   * polar-radial-force-directed 2D navigation fields"): the field holds only
   * results of the focus's own kind -- a notebook's halo is notebooks, a
   * slate's slates -- asked for three times over so the filter still fills
   * the ring. Planted `plantLooseType`: every kind, as the additive term had it.
   */
  plantLooseType = false;
  typeStats = { kept: 0, dropped: 0, last: null as any };
  private strict(hits: any[]): any[] {
    if (this.plantLooseType || !this.focusKind) return hits;
    const kept = hits.filter((h: any) => this.kindOf(String(h.url || "")) === this.focusKind);
    this.typeStats.kept += kept.length; this.typeStats.dropped += hits.length - kept.length;
    this.typeStats.last = { focus: this.focusKind, kept: kept.length, of: hits.length };
    return kept;
  }
  /** An artifact's kind and layer: a slate, a notebook (a note with a python
   *  cell), a markdown note, code, or a web chunk. */
  /** The type graph's PageRank by kind (G-317), from `/typegraph`. */
  typeRank: Record<string, number> | null = null;
  /** Planted (G-317): every kind weighs 1 -- the type graph's ranks ignored. */
  plantUniformTypeRank = false;
  /** What a kind weighs in the type term: its rank in the type graph (code kinds), else 1. */
  rankOf(kind: string): number {
    if (this.plantUniformTypeRank || !this.typeRank) return 1;
    const r = this.typeRank[kind];
    return typeof r === "number" && r > 0 ? r : 1;
  }
  kindOf(url: string): string {
    const vault = "vault://" + this.host.app.vault.getName() + "/";
    if (url.startsWith("code://")) {
      // The layer of abstraction (item 92): a module, a class, a function, a method.
      const q = url.includes("#") ? url.slice(url.indexOf("#") + 1) : "";
      if (!q) return "module";
      const parts = q.split(".");
      const last = parts[parts.length - 1];
      if (parts.length >= 2 && /^[a-z_]/.test(last)) return "method";
      return /^[A-Z]/.test(last) ? "class" : "function";
    }
    if (!url.startsWith(vault)) return "web";
    const f = this.host.app.vault.getAbstractFileByPath(url.slice(vault.length));
    if (!(f instanceof TFile)) return "markdown";
    const cache = this.host.app.metadataCache.getFileCache(f);
    if (String(cache?.frontmatter?.domvec || "") === "slate") return "slate";
    return (cache?.sections || []).some((x) => x.type === "code") ? "notebook" : "markdown";
  }
  /** 1 for the same kind, 0.5 for the same family (a note of another kind), 0 otherwise. */
  typeMatch(a: string, b: string): number {
    if (!a || !b) return 0;
    if (a === b) return 1;
    const notes = ["slate", "notebook", "markdown"], code = ["module", "class", "function", "method"];
    return (notes.includes(a) && notes.includes(b)) || (code.includes(a) && code.includes(b)) ? 0.5 : 0;
  }

  /** Dijkstra from the focus (-1) over the halo: focus -> each result at
   *  1 - s, result -> its two most similar at 1 - sim. */
  shortestPath(to: number): number[] {
    const n = this.nodes.length;
    const dist = new Array(n).fill(Infinity), prev = new Array(n).fill(-1), done = new Array(n).fill(false);
    for (let i = 0; i < n; i++) dist[i] = 1 - this.nodes[i].s;
    const nbrs = this.nodes.map((_, i) => this.nodes.map((__, j) => j).filter((j) => j !== i)
      .sort((a, b) => this.sim[i][b] - this.sim[i][a]).slice(0, 2));
    for (let k = 0; k < n; k++) {
      let u = -1;
      for (let i = 0; i < n; i++) if (!done[i] && (u < 0 || dist[i] < dist[u])) u = i;
      if (u < 0) break;
      done[u] = true;
      for (const v of nbrs[u]) { const w = dist[u] + (1 - this.sim[u][v]); if (w < dist[v]) { dist[v] = w; prev[v] = u; } }
    }
    const path: number[] = [];
    for (let v = to; v >= 0; v = prev[v]) path.unshift(v);
    return path;
  }

  /** A click while a result is lit: stuck on the plane where it sits. */
  private stick(e: PointerEvent): void {
    if (e.button !== 0 || this.navigated < 0) return;
    const p = this.host.desk.panelOf(this.focus);
    const t = e.target as HTMLElement;
    if (p && p.card.contains(t)) return;
    const h = this.nodes[this.navigated];
    e.preventDefault(); e.stopPropagation();
    void this.stickNode(h);
  }

  async stickNode(h: HNode): Promise<boolean> {
    this.stats.stuck++; this.stats.last_stuck = h.key;
    const vault = "vault://" + this.host.app.vault.getName() + "/";
    if (!h.url.startsWith(vault)) return false;          // a tagged chunk: its place is the world's
    const f = this.host.app.vault.getAbstractFileByPath(h.url.slice(vault.length));
    if (!(f instanceof TFile)) return false;
    await this.host.desk.open(f);
    const q = this.host.desk.panelOf(f.path);
    if (q) { q.card.style.left = `${Math.max(0, h.x - 40)}px`; q.card.style.top = `${Math.max(0, h.y - 14)}px`; }
    return true;
  }

  private draw(plane: HTMLElement): void {
    if (!this.svg) {
      this.svg = document.createElementNS(SVG, "svg") as SVGSVGElement;
      this.svg.classList.add("domvec-halo2d");
      plane.appendChild(this.svg);
    }
    const svg = this.svg;
    while (svg.firstChild) svg.firstChild.remove();
    const el = (tag: string, attrs: Record<string, any>, text?: string) => {
      const e = document.createElementNS(SVG, tag);
      for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, String(v));
      if (text) e.textContent = text;
      svg.appendChild(e);
      return e;
    };
    for (const h of this.nodes) el("line", { x1: this.centre.x, y1: this.centre.y, x2: h.x, y2: h.y, class: "ray" });
    // The trace back: through every focus passed, then to the navigated one.
    const back = [...this.history.map((q) => ({ x: q.x, y: q.y })), this.centre, ...this.trace.map((i) => this.nodes[i])];
    if (back.length > 1) el("polyline", { points: back.map((q) => `${q.x},${q.y}`).join(" "), class: "trace" });
    for (const q of this.history) el("circle", { cx: q.x, cy: q.y, r: 5, class: "node past" });
    // Only what is IN VIEW is drawn (134g).
    const W = plane.clientWidth, H = plane.clientHeight;
    this.nodes.forEach((h, i) => {
      if (h.x < -20 || h.y < -20 || h.x > W + 20 || h.y > H + 20) { this.drift.culled++; return; }
      el("circle", { cx: h.x, cy: h.y, r: 8, class: i === this.navigated ? "node lit" : "node" });
      el("text", { x: h.x + 11, y: h.y + 4, class: "label" }, h.label);
    });
    // No dot under the pointer (2026-11-07: "this annoying yellow dot that
    // appears randomly and follows the mouse around"). Planted
    // `__domvecPlantHaloCursor`: drawn, as before.
    if ((window as any).__domvecPlantHaloCursor) el("circle", { cx: this.cursor.x, cy: this.cursor.y, r: 3, class: "cursor" });
  }

  close(): void {
    if (!this.focus) return;
    this.focus = "";
    this.stats.closed++;
    window.cancelAnimationFrame(this.raf); this.raf = 0;
    for (const q of this.folded) { const pp = this.host.desk.panelOf(q); if (pp && pp.card.hasClass("is-collapsed")) this.host.desk.toggleMinimized(q); }
    this.folded = [];
    window.removeEventListener("pointermove", this.onMove, true);
    window.removeEventListener("pointerdown", this.onDown, true);
    window.removeEventListener("keydown", this.onKey, true);
    this.svg?.remove(); this.svg = null;
    window.clearTimeout(this.dwell);
    this.nodes = []; this.navigated = -1; this.trace = []; this.history = []; this.focusKey = "";
  }
}
