/**
 * The pipeline profiler: one drain, traced from the page to the pixels.
 *
 * **One clock for the end-to-end, and durations for everything else.** The
 * pipeline crosses three processes -- the guest page, this renderer, and the
 * sidecar -- and their clocks cannot be subtracted from each other. So the
 * end-to-end latency is measured entirely in THIS renderer's clock, which
 * sees the drain leave, the reply return, the graph absorb it and the node
 * appear. The guest and the sidecar report DURATIONS of their own stages,
 * and those are checked for consistency against the renderer's view: the
 * sidecar's total cannot exceed the round trip that contained it, and what
 * is left over is transport.
 *
 * **The last stage is observed, not reported.** "The node is on screen" is
 * decided by a listener that reads the 3D graph every animation frame --
 * does the node exist, does it have a scene object, is that object visible,
 * does it project inside the camera frustum -- and not by anything the
 * capture reply or `absorb` claimed. Those two can both say a node was added
 * while the picture shows nothing, and this project has shipped exactly that
 * more than once.
 *
 * Stages, in the order a drain passes through them:
 *
 *   drain        executeJavaScript round trip that pulls the delta out of
 *                the guest. Contains the guest's own fold.
 *   fold         the sensor's `repairMs` for this drain, guest clock.
 *   capture      fetch round trip to `/capture`.
 *   sidecar.*    the sidecar's phases, its clock: decode, absorb (the trie),
 *                render (markdown), lock_wait, store and its ms_* parts,
 *                place (UMAP transform), total.
 *   transport    capture - sidecar.total. Serialisation, the socket, and the
 *                request queue, which nothing else accounts for.
 *   absorb       the graph taking the placed nodes in.
 *   visible      absorb finished -> first frame in which a placed node is
 *                drawn inside the frustum. Observed.
 *   end_to_end   drain start -> first placed node visible.
 */

export interface Trace {
  id: string;
  kind: string;
  url: string;
  /** Renderer clock, ms, at the moment the drain started. */
  t0: number;
  stages: Record<string, number>;
  /** Anything that is not a duration: counts, bytes, why a stage was skipped. */
  facts: Record<string, unknown>;
  done: boolean;
}

const CAP = 300;

/**
 * One page visit, by STAGE (2026-10-11, PLUGIN_GOAL 91: "the diff is streamed
 * into its grey-nodes, projected nodes, local url updated nodes, and the full
 * umap update (also make sure each of these are actually working and running
 * and updates are making it to the 3D panel view ... getting the time
 * profiles reported directly at the point of the interface, but still
 * carrying provenance on the time profile over the backend").
 *
 * Every mark is the renderer's clock since the navigation began, the FIRST
 * time that stage reached the 3D view for this page:
 *
 *   drain      the sensor's first delta left the page
 *   grey       the first streamed (grey) node joined the graph
 *   projected  the first streamed node was placed by the projector
 *   stored     the first stored chunk was DRAWN (the drain trace's observed
 *              "visible" -- its sidecar phases are the provenance)
 *   refit      a full UMAP refit landed while the page was open
 *
 * And each hover on the page, timed from the hover reaching the 3D view to
 * its panel's first paint, tagged with the stage the page had reached -- so
 * "the panel is slow while streaming" is a number per stage, not a feeling.
 */
export const VISIT_STAGES = ["drain", "grey", "projected", "stored", "refit"] as const;
export interface Visit {
  url: string;
  t0: number;
  marks: Record<string, number>;
  /** Where each mark's time came from: a drain trace id, the sidecar's own phases, a fit epoch. */
  prov: Record<string, Record<string, unknown>>;
  hovers: { stage: string; ms: number; paint_ms: number | null; at: number }[];
  /** Other spellings this visit's page took in place (an app's route rewrite). */
  aliases?: string[];
}
const VISIT_CAP = 40;
const key = (url: string) => String(url || "").split("#")[0];

/** Why a trace ended without a node on screen. */
type Outcome = "visible" | "nothing_placed" | "not_seen" | "no_graph";

export class PipelineProfiler {
  private visitsList: Visit[] = [];
  private traces: Trace[] = [];
  private live = new Map<string, Trace>();
  private counter = 0;
  /** Set by the graph view, so the listener can read the scene. */
  graphSource: (() => any) | null = null;
  /** The graph VIEW, for what it knows beyond the renderer (`G-90`). */
  graphView: (() => any) | null = null;

  begin(kind: string, url: string): Trace {
    const t: Trace = {
      id: `${Date.now().toString(36)}-${(this.counter++).toString(36)}`,
      kind, url, t0: performance.now(), stages: {}, facts: {}, done: false,
    };
    this.live.set(t.id, t);
    // A drain is traced as "land" (the first) or "live" (each after).
    if (kind === "land" || kind === "live") this.mark(url, "drain", { trace: t.id, kind });
    return t;
  }

  // ---- visits by stage (item 91) ------------------------------------------

  /** A navigation began: a new visit, its clock at zero. */
  visitStart(url: string): void {
    if (!/^https?:/.test(url || "")) return;
    this.visitsList.push({ url: key(url), t0: performance.now(), marks: {}, prov: {}, hovers: [] });
    if (this.visitsList.length > VISIT_CAP) this.visitsList.shift();
  }

  /** The latest visit to this page, or none. */
  visit(url: string): Visit | undefined {
    const k = key(url);
    for (let i = this.visitsList.length - 1; i >= 0; i--) {
      const v = this.visitsList[i];
      if (v.url === k || (v.aliases && v.aliases.includes(k))) return v;
    }
    return undefined;
  }

  /**
   * The page rewrote its own url in place (bandcamp: `radio?show=1010` ->
   * `radio/1010`): the visit goes on under both. Its stages were marked
   * under the new spelling, matched no visit, and a fresh page read as
   * having reached no stage at all (2026-10-18). Planted `plantNoAlias`.
   */
  plantNoAlias = false;
  visitAlias(url: string): void {
    const v = this.visitsList[this.visitsList.length - 1];
    if (!v || this.plantNoAlias || !/^https?:/.test(url || "")) return;
    const k = key(url);
    if (k === v.url) return;
    (v.aliases = v.aliases || []).push(k);
    if (v.aliases.length > 8) v.aliases.shift();
  }

  /** The FIRST time a stage reached the 3D view on this visit; later ones are not marks. */
  mark(url: string, stage: string, prov: Record<string, unknown> = {}): void {
    const v = this.visit(url);
    if (!v || v.marks[stage] !== undefined) return;
    v.marks[stage] = Math.round(performance.now() - v.t0);
    v.prov[stage] = prov;
  }

  /** The stage this page has reached: the last of `VISIT_STAGES` it has a mark for. */
  stageOf(url: string): string {
    const v = this.visit(url);
    if (!v) return "none";
    let at = "navigating";
    for (const s of VISIT_STAGES) if (v.marks[s] !== undefined) at = s;
    return at;
  }

  /** A hover's panel painted: how long from the hover to the paint, at which stage. */
  hover(url: string, ms: number, paintMs: number | null): void {
    const v = this.visit(url);
    if (!v) return;
    v.hovers.push({ stage: this.stageOf(url), ms: Math.round(ms), paint_ms: paintMs, at: Math.round(performance.now() - v.t0) });
    if (v.hovers.length > 200) v.hovers.shift();
  }

  /** Every visit, newest last, with hover latency per stage (p50, max, n). */
  visits(): any[] {
    return this.visitsList.map((v) => {
      const by: Record<string, number[]> = {};
      for (const h of v.hovers) (by[h.stage] = by[h.stage] || []).push(h.ms);
      const hover: Record<string, unknown> = {};
      for (const [k, a] of Object.entries(by)) {
        const s = a.slice().sort((x, y) => x - y);
        hover[k] = { n: s.length, p50: s[Math.floor((s.length - 1) / 2)], max: s[s.length - 1] };
      }
      return { url: v.url, aliases: v.aliases || [], marks: { ...v.marks }, prov: v.prov, hover, hovers: v.hovers.length };
    });
  }

  get(id: string): Trace | undefined {
    return this.live.get(id);
  }

  stage(t: Trace | undefined, name: string, ms: number) {
    if (!t || !Number.isFinite(ms)) return;
    t.stages[name] = Math.round(ms * 10) / 10;
  }

  fact(t: Trace | undefined, name: string, value: unknown) {
    if (t) t.facts[name] = value;
  }

  /** Fold the sidecar's own phases into the trace, and derive transport. */
  sidecar(t: Trace | undefined, phases: Record<string, number> | undefined,
          total: number | undefined, captureMs: number) {
    if (!t) return;
    for (const [k, v] of Object.entries(phases || {})) {
      if (typeof v === "number") this.stage(t, `sidecar.${k}`, v);
    }
    if (typeof total === "number") {
      this.stage(t, "sidecar.total", total);
      // What the sidecar did not spend inside itself. A NEGATIVE value would
      // mean the sidecar reported more time than the round trip it happened
      // in, which is impossible and is flagged rather than clamped.
      const transport = captureMs - total;
      this.stage(t, "transport", transport);
      if (transport < -1) this.fact(t, "clock_inconsistent", true);
    }
  }

  /**
   * Watch the graph until a node from `cids` is actually drawn, then close
   * the trace. `absorbEnd` is the renderer time `absorb` returned.
   */
  watch(t: Trace | undefined, cids: string[], absorbEnd: number,
        timeoutMs = 8000) {
    if (!t) return;
    if (!cids.length) return this.finish(t, "nothing_placed");
    const want = new Set(cids);
    const started = performance.now();
    const firstFrame = this.frame();

    // **A deadline on the timer clock, not the frame clock.** The check
    // below runs inside `requestAnimationFrame`, and Chrome SUSPENDS rAF in
    // a hidden window -- so a timeout tested only inside it can never fire,
    // and the trace stays open forever. Measured: the listener's own test
    // got "never closed" where it expected "not_seen", with the window
    // minimised. `finish` is idempotent, so whichever of the two closes the
    // trace first wins and the other does nothing.
    const deadline = window.setTimeout(() => {
      if (t.done) return;
      this.fact(t, "waited_ms", Math.round(performance.now() - started));
      this.fact(t, "raf_suspended", this.frame() === firstFrame);
      this.finish(t, "not_seen");
    }, timeoutMs);

    const check = () => {
      if (t.done) { window.clearTimeout(deadline); return; }
      const g = this.graphSource ? this.graphSource() : null;
      if (!g) return this.finish(t, "no_graph");
      const seen = this.visibleAmong(g, want);
      if (seen > 0) {
        const now = performance.now();
        this.stage(t, "visible", now - absorbEnd);
        this.stage(t, "end_to_end", now - t.t0);
        this.fact(t, "visible_nodes", seen);
        this.fact(t, "frames_waited", this.frame() - firstFrame);
        return this.finish(t, "visible");
      }
      if (performance.now() - started > timeoutMs) {
        this.fact(t, "waited_ms", Math.round(performance.now() - started));
        return this.finish(t, "not_seen");
      }
      requestAnimationFrame(check);
    };
    requestAnimationFrame(check);
  }

  /**
   * How many of `want` are genuinely DRAWN right now. The criteria are the
   * ones `uistate.graphState` uses, for the same reasons: a node can be in
   * the data and absent from the scene, in the scene and invisible, or
   * visible and behind the camera -- where `graph2ScreenCoords` still hands
   * back an ordinary-looking screen point.
   */
  private visibleAmong(g: any, want: Set<string>): number {
    let seen = 0;
    try {
      const cam = g.camera();
      cam.updateMatrixWorld?.();
      const proj = cam.projectionMatrix.elements;
      const view = cam.matrixWorldInverse.elements;
      const mul = (m: number[], v: number[]) => [
        m[0] * v[0] + m[4] * v[1] + m[8] * v[2] + m[12] * v[3],
        m[1] * v[0] + m[5] * v[1] + m[9] * v[2] + m[13] * v[3],
        m[2] * v[0] + m[6] * v[1] + m[10] * v[2] + m[14] * v[3],
        m[3] * v[0] + m[7] * v[1] + m[11] * v[2] + m[15] * v[3],
      ];
      for (const n of g.graphData().nodes as any[]) {
        if (!want.has(n.id)) continue;
        const obj = n.__threeObj;
        // Since the scene batch (`G-107`) a node's own object is an INVISIBLE
        // pick proxy and the batch draws the node: a hidden proxy is not a
        // hidden node. Refusing it closed 0 of 300 drains "visible" (2026-10-11).
        if (!obj || (obj.visible === false && !obj.__proxy)) continue;
        const clip = mul(proj, mul(view, [n.x ?? 0, n.y ?? 0, n.z ?? 0, 1]));
        const w = clip[3];
        if (!(w > 0)) continue;
        const x = clip[0] / w, y = clip[1] / w;
        if (x < -1 || x > 1 || y < -1 || y > 1) continue;
        seen++;
      }
    } catch {
      return 0;
    }
    return seen;
  }

  private frame(): number {
    try {
      const g = this.graphSource ? this.graphSource() : null;
      return g ? g.renderer().info.render.frame : 0;
    } catch {
      return 0;
    }
  }

  /** Forget a trace that turned out not to be one (its drain was pushed). */
  drop(t: Trace) {
    this.live.delete(t.id);
  }

  finish(t: Trace, outcome: Outcome) {
    if (t.done) return;
    t.done = true;
    this.fact(t, "outcome", outcome);
    // The stored stage reached the 3D view: observed, with the sidecar's own
    // phases as its provenance.
    if (outcome === "visible" && (t.kind === "land" || t.kind === "live")) {
      this.mark(t.url, "stored", { trace: t.id, end_to_end: t.stages.end_to_end, capture: t.stages.capture,
                                    sidecar_total: t.stages["sidecar.total"], place: t.stages["sidecar.place"],
                                    transport: t.stages.transport });
    }
    this.live.delete(t.id);
    this.traces.push(t);
    if (this.traces.length > CAP) this.traces.shift();
  }

  /** The latest trace for a page, finished or live: the provenance of a stage. */
  lastFor(url: string): Trace | undefined {
    const k = key(url);
    let best: Trace | undefined;
    for (const t of this.live.values()) if (key(t.url) === k && (!best || t.t0 > best.t0)) best = t;
    for (let i = this.traces.length - 1; i >= 0; i--) {
      const t = this.traces[i];
      if (key(t.url) === k) { if (!best || t.t0 > best.t0) best = t; break; }
    }
    return best;
  }

  list(): Trace[] {
    return this.traces.slice();
  }

  /**
   * Finished traces AND the ones still open. A drain's trace closes when its
   * nodes are seen in the 3D view or its deadline passes, so a check reading
   * only `list()` a few seconds after a scroll missed every drain still
   * waiting -- D-40 matched 0 of 15 new topics one run and 14 the next,
   * depending on whether the graph happened to show them in time
   * (2026-10-19). What a drain CARRIED is known the moment it is absorbed.
   */
  listAll(): Trace[] {
    return [...this.traces, ...this.live.values()];
  }

  reset() {
    this.traces = [];
    this.live.clear();
  }

  /**
   * Per stage: n, p50, p90, max, and the share of end-to-end at the median.
   *
   * Percentiles, never a mean. The mean of a latency is dominated by the one
   * drain that waited behind an embed batch, and the median alone hides that
   * that drain exists; both are needed and a mean gives neither.
   */
  summary() {
    const by: Record<string, number[]> = {};
    const outcomes: Record<string, number> = {};
    for (const t of this.traces) {
      const o = String(t.facts.outcome || "?");
      outcomes[o] = (outcomes[o] || 0) + 1;
      for (const [k, v] of Object.entries(t.stages)) (by[k] = by[k] || []).push(v);
    }
    const q = (a: number[], p: number) => {
      const s = a.slice().sort((x, y) => x - y);
      return s.length ? s[Math.min(s.length - 1, Math.floor(p * (s.length - 1)))] : null;
    };
    const e2e = q(by["end_to_end"] || [], 0.5) || 0;
    const stages: Record<string, unknown> = {};
    for (const [k, a] of Object.entries(by)) {
      const p50 = q(a, 0.5) as number;
      stages[k] = {
        n: a.length, p50, p90: q(a, 0.9), max: q(a, 1),
        share_of_e2e: e2e && k !== "end_to_end"
          ? Math.round((p50 / e2e) * 1000) / 10 : null,
      };
    }
    return { traces: this.traces.length, outcomes, stages };
  }
}

/** One per window, so the browser view and the graph view share it. */
export function profiler(): PipelineProfiler {
  const w = window as any;
  // The window outlives a plugin reload: an instance built by an OLDER build
  // lacks what this one added (2026-10-11: "visits is not a function" after a
  // reload). Replaced, keeping the traces it holds.
  // By CAPABILITY, not class: a listener left from the previous plugin load
  // runs the OLD class, and an instanceof test there replaced the new
  // instance with an old one -- the two loads thrashed, and visits vanished.
  const old = w.__vertiscopeProfiler;
  // `visitAlias` (2026-10-18): an instance without it filed a redirected
  // page's stages under no visit. `listAll` (2026-10-19) is the newest.
  if (!old || typeof old.visits !== "function" || typeof old.lastFor !== "function"
      || typeof old.visitAlias !== "function" || typeof old.listAll !== "function") {
    const fresh = new PipelineProfiler();
    try { for (const t of (old?.list?.() || [])) (fresh as any).traces.push(t); } catch { /* an older shape */ }
    try { for (const v of (old?.visitsList || [])) (fresh as any).visitsList.push(v); } catch { /* an older shape */ }
    w.__vertiscopeProfiler = fresh;
  }
  return w.__vertiscopeProfiler as PipelineProfiler;
}
