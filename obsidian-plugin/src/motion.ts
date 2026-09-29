/**
 * A flight recorder for the 3D view (2026-09-29: "The force-directed methods
 * are still throwing glitches. You'll need to improve the fidelity of your
 * MCP tooling harness to capture the details of what anomalous and specific
 * behavior I'm describing").
 *
 * A screenshot shows where things ARE; a glitch is how they MOVE. For a
 * window of seconds this records, from inside the render loop:
 *
 *   per frame   every node's world position and its SCREEN position (what the
 *               reader sees), the simulation's alpha, how many nodes moved
 *   per force   the velocity each force added to each node, summed -- so an
 *               anomalous node names the force that threw it
 *   events      drains, placements, folds, graphData swaps, reheats, on the
 *               same clock
 *
 * and then says what was anomalous: teleports (a big jump in one frame),
 * vibration (direction flipping with little net travel), stored nodes
 * drifting when they should hold, coincident pairs, collapsed clusters -- and
 * why nodes are not visible (sub-pixel, stacked, off the canvas, behind the
 * camera). Read-only: it reads positions and velocities, never writes them.
 */

export interface MotionOptions {
  /** Seconds to record (default 10, at most 60). */
  seconds?: number;
  /** Nodes tracked at most (default 4000). */
  cap?: number;
}

interface Meta { id: string; url: string; level: string; force: boolean; name: string; }

const FORCES = ["link", "center", "charge", "home", "contain", "collide", "treeSpring", "hold"];

export class MotionRecorder {
  recording = false;
  private startedAt = 0;
  private wall0 = 0;
  private maxFrames = 600;
  private cap = 4000;
  private times: number[] = [];
  private alphas: number[] = [];
  private movingPx: number[] = [];
  private slot = new Map<string, number>();
  private meta: Meta[] = [];
  private world: Float32Array[] = [];
  private screen: Float32Array[] = [];
  private sizePx: Float32Array[] = [];
  /** Each node's drawn half-extent in WORLD units, per frame: pulsing. */
  private half: Float32Array[] = [];
  private dv = new Map<string, Float64Array>();
  events: { t: number; kind: string; detail: any }[] = [];
  lastAlpha = 0;
  private stopTimer = 0;
  private result: any = null;
  /** Set by the view: what the analysis needs to know about the canvas. */
  box = { w: 1, h: 1 };
  /** Set by the view: the graph's links, read once when the window closes. */
  linksNow: (() => any[]) | null = null;
  private cams: number[][] = [];
  /** Frames where the READER's camera moved: screen motion there is theirs. */
  private camMoved: boolean[] = [];

  camera(c: number[]): void {
    if (!this.recording) return;
    const prev = this.cams[this.cams.length - 1];
    this.camMoved.push(!!prev && c.some((v, i) => Math.abs(v - prev[i]) > 1e-6));
    this.cams.push(c);
  }

  start(o: MotionOptions = {}): any {
    const secs = Math.min(60, Math.max(1, o.seconds ?? 10));
    this.cap = o.cap ?? 4000;
    this.maxFrames = Math.ceil(secs * 75);
    this.times = []; this.alphas = []; this.movingPx = [];
    this.slot.clear(); this.meta = []; this.world = []; this.screen = []; this.sizePx = []; this.half = [];
    this.dv.clear(); this.events = []; this.result = null; this.cams = []; this.camMoved = [];
    this.startedAt = performance.now();
    this.wall0 = Date.now();
    this.recording = true;
    window.clearTimeout(this.stopTimer);
    this.stopTimer = window.setTimeout(() => this.stop(), secs * 1000);
    return { recording: true, seconds: secs, wall0: this.wall0 };
  }

  event(kind: string, detail: any = null): void {
    if (!this.recording) return;
    this.events.push({ t: Math.round(performance.now() - this.startedAt), kind, detail });
    if (this.events.length > 2000) this.events.splice(0, 500);
  }

  private slotOf(n: any): number {
    const id = String(n.id);
    let s = this.slot.get(id);
    if (s !== undefined) return s;
    if (this.meta.length >= this.cap) return -1;
    s = this.meta.length;
    this.slot.set(id, s);
    this.meta.push({ id, url: String(n.url || ""), level: String(n.level || ""), force: !!n.force,
                     name: String(n.name || "").slice(0, 60) });
    const f = this.maxFrames;
    const w = new Float32Array(f * 3); w.fill(NaN);
    const sc = new Float32Array(f * 2); sc.fill(NaN);
    const sz = new Float32Array(f); sz.fill(NaN);
    const hf = new Float32Array(f); hf.fill(NaN);
    this.world.push(w); this.screen.push(sc); this.sizePx.push(sz); this.half.push(hf);
    return s;
  }

  /**
   * Called by a force wrapper around the force: velocities before, then after.
   * Only while recording; O(nodes) per force per tick.
   */
  forceBefore(nodes: any[]): Float64Array | null {
    if (!this.recording) return null;
    const b = new Float64Array(nodes.length * 3);
    for (let i = 0; i < nodes.length; i++) {
      const n = nodes[i];
      b[i * 3] = n.vx || 0; b[i * 3 + 1] = n.vy || 0; b[i * 3 + 2] = n.vz || 0;
    }
    return b;
  }

  forceAfter(name: string, nodes: any[], before: Float64Array | null, alpha: number): void {
    this.lastAlpha = alpha;
    if (!this.recording || !before) return;
    let acc = this.dv.get(name);
    if (!acc || acc.length < this.cap) { acc = new Float64Array(this.cap); this.dv.set(name, acc); }
    for (let i = 0; i < nodes.length; i++) {
      const n = nodes[i];
      const s = this.slot.get(String(n.id));
      if (s === undefined) continue;
      const dx = (n.vx || 0) - before[i * 3], dy = (n.vy || 0) - before[i * 3 + 1], dz = (n.vz || 0) - before[i * 3 + 2];
      const d = Math.sqrt(dx * dx + dy * dy + dz * dz);
      if (Number.isFinite(d)) acc[s] += d;
      else acc[s] += 1e9;                                  // a non-finite write is the loudest thing a force can do
    }
  }

  /** One rendered frame: every node's world and screen position. */
  frame(nodes: any[], project: (x: number, y: number, z: number) => [number, number, number],
        halfOf: (n: any) => number, pxPerUnitAt: (depth: number) => number): void {
    if (!this.recording) return;
    const f = this.times.length;
    if (f >= this.maxFrames) { this.stop(); return; }
    this.times.push(performance.now() - this.startedAt);
    this.alphas.push(this.lastAlpha);
    let moving = 0;
    for (const n of nodes) {
      const s = this.slotOf(n);
      if (s < 0) continue;
      const w = this.world[s];
      w[f * 3] = n.x; w[f * 3 + 1] = n.y; w[f * 3 + 2] = n.z || 0;
      const [sx, sy, depth] = project(n.x, n.y, n.z || 0);
      const sc = this.screen[s];
      sc[f * 2] = sx; sc[f * 2 + 1] = sy;
      const hw = halfOf(n);
      this.half[s][f] = hw;
      this.sizePx[s][f] = depth > 0 ? hw * pxPerUnitAt(depth) : -1;
      if (f > 0 && Number.isFinite(sc[f * 2 - 2])) {
        const d = Math.hypot(sx - sc[f * 2 - 2], sy - sc[f * 2 - 1]);
        if (d > 1) moving++;
      }
    }
    this.movingPx.push(moving);
  }

  stop(): any {
    if (!this.recording) return this.result;
    this.recording = false;
    window.clearTimeout(this.stopTimer);
    this.result = this.analyse();
    return this.result;
  }

  state(): any {
    return { recording: this.recording, frames: this.times.length, nodes: this.meta.length,
             elapsed_ms: this.recording ? Math.round(performance.now() - this.startedAt) : null,
             result: this.result };
  }

  private analyse(): any {
    const F = this.times.length;
    const secs = F > 1 ? (this.times[F - 1] - this.times[0]) / 1000 : 0;
    const per: any[] = [];
    const W = this.box.w, H = this.box.h;
    for (let s = 0; s < this.meta.length; s++) {
      const sc = this.screen[s], w = this.world[s];
      let first = -1, last = -1, path = 0, maxJump = 0, jumpAt = -1, flips = 0, wpath = 0;
      let wJump = 0, wJumpAt = -1, nearCam = 0;
      const sz = this.sizePx[s];
      let pdx = 0, pdy = 0;
      for (let f = 0; f < F; f++) {
        const x = sc[f * 2], y = sc[f * 2 + 1];
        if (!Number.isFinite(x)) continue;
        if (first < 0) { first = f; last = f; continue; }
        const px = sc[last * 2], py = sc[last * 2 + 1];
        // World motion first: it is the node's own, whatever the camera does.
        const wd = Math.hypot(w[f * 3] - w[last * 3], w[f * 3 + 1] - w[last * 3 + 1], w[f * 3 + 2] - w[last * 3 + 2]);
        wpath += wd;
        if (wd > wJump && last === f - 1) { wJump = wd; wJumpAt = f; }
        if (this.camMoved[f]) { last = f; continue; }       // the reader moved, not the node
        // Screen motion only in front of the camera: a node crossing the
        // camera plane projects to millions of pixels (the first capture's
        // "11,062,043 px" jump was that, not the node).
        if (!(sz[f] > 0 && sz[last] > 0)) { nearCam++; last = f; continue; }
        const dx = x - px, dy = y - py, d = Math.hypot(dx, dy);
        path += d;
        if (d > maxJump && last === f - 1) { maxJump = d; jumpAt = f; }
        if (Math.abs(dx) > 0.5 && pdx && Math.sign(dx) !== Math.sign(pdx)) flips++;
        if (Math.abs(dy) > 0.5 && pdy && Math.sign(dy) !== Math.sign(pdy)) flips++;
        if (Math.abs(dx) > 0.5) pdx = dx;
        if (Math.abs(dy) > 0.5) pdy = dy;
        last = f;
      }
      if (first < 0) continue;
      const net = Math.hypot(sc[last * 2] - sc[first * 2], sc[last * 2 + 1] - sc[first * 2 + 1]);
      const size = this.sizePx[s][last];
      const x = sc[last * 2], y = sc[last * 2 + 1];
      // Flicker: gone for a stretch and back (a node the reader saw vanish).
      // Pulsing: its drawn size jumping by more than a quarter, frame to frame.
      let gaps = 0, inGap = false, pulses = 0;
      const hf = this.half[s];
      for (let f = first + 1; f <= last; f++) {
        const here = Number.isFinite(sc[f * 2]);
        if (!here && !inGap) { inGap = true; gaps++; }
        if (here) inGap = false;
        const a = hf[f - 1], b = hf[f];
        if (Number.isFinite(a) && Number.isFinite(b) && Math.abs(b - a) > 0.25 * Math.max(a, b, 1e-9)) pulses++;
      }
      const wnet = Math.hypot(w[last * 3] - w[first * 3], w[last * 3 + 1] - w[first * 3 + 1], w[last * 3 + 2] - w[first * 3 + 2]);
      per.push({ s, first, last, path, net, maxJump, jumpAt, flips, wpath, size, wJump, wJumpAt, wnet, nearCam, gaps, pulses,
                 halfFirst: hf[first], halfLast: hf[last],
                 far: Math.hypot(w[last * 3], w[last * 3 + 1], w[last * 3 + 2]),
                 x, y, wx: w[last * 3], wy: w[last * 3 + 1], wz: w[last * 3 + 2],
                 onCanvas: x >= 0 && x <= W && y >= 0 && y <= H, behind: size < 0 });
    }
    const flipRate = (p: any) => (secs > 0 ? p.flips / secs : 0);
    const topForces = (s: number) => {
      const out: [string, number][] = [];
      for (const [name, acc] of this.dv) if (acc[s] > 0) out.push([name, acc[s]]);
      out.sort((a, b) => b[1] - a[1]);
      return out.slice(0, 3).map(([n, v]) => [n, v >= 1e9 ? "NON-FINITE" : Math.round(v * 100) / 100]);
    };
    const eventNear = (f: number) => {
      if (f < 0) return null;
      const t = this.times[f];
      let best: any = null;
      for (const e of this.events) if (e.t <= t && t - e.t <= 600 && (!best || e.t > best.t)) best = e;
      return best ? { kind: best.kind, before_ms: Math.round(t - best.t), detail: best.detail } : null;
    };
    const track = (s: number) => {
      const sc = this.screen[s], pts: number[][] = [];
      const step = Math.max(1, Math.floor(F / 80));
      for (let f = 0; f < F; f += step) if (Number.isFinite(sc[f * 2])) pts.push([Math.round(sc[f * 2]), Math.round(sc[f * 2 + 1]), Math.round(this.times[f])]);
      return pts;
    };
    const describe = (p: any, extra: any = {}) => ({
      ...this.meta[p.s], path_px: Math.round(p.path), net_px: Math.round(p.net),
      max_jump_px: Math.round(p.maxJump), jump_at_ms: p.jumpAt >= 0 ? Math.round(this.times[p.jumpAt]) : null,
      world_jump: Math.round(p.wJump * 100) / 100, world_jump_at_ms: p.wJumpAt >= 0 ? Math.round(this.times[p.wJumpAt]) : null,
      // The frame gap the jump happened across: a long one is a STALL (the
      // main thread held, a glide ran its course unseen), not a force.
      jump_gap_ms: p.wJumpAt > 0 ? Math.round(this.times[p.wJumpAt] - this.times[p.wJumpAt - 1]) : null,
      world_path: Math.round(p.wpath), world_net: Math.round(p.wnet), frames_near_camera: p.nearCam,
      vanished: p.gaps, size_jumps: p.pulses,
      half_first_last: [p.halfFirst, p.halfLast].map((v: number) => Math.round(v * 100) / 100),
      world_end: [p.wx, p.wy, p.wz].map((v: number) => Math.round(v * 10) / 10),
      flips_per_s: Math.round(flipRate(p) * 10) / 10, size_px: Math.round(p.size * 10) / 10,
      forces: topForces(p.s), near_event: eventNear(p.jumpAt), track: track(p.s), ...extra });
    const byScore = (xs: any[], key: (p: any) => number) => xs.slice().sort((a, b) => key(b) - key(a)).slice(0, 12);
    const links0 = this.linksNow ? this.linksNow() : [];
    const ll: number[] = [];
    for (const l of links0) { const a = l.source, b = l.target; if (a && b && typeof a === "object") { const d = Math.hypot(a.x - b.x, a.y - b.y, (a.z || 0) - (b.z || 0)); if (Number.isFinite(d)) ll.push(d); } }
    ll.sort((a, b) => a - b);
    const scaleW = ll.length ? ll[ll.length >> 1] : 20;
    const teleports = per.filter((p) => (p.wJump > Math.max(10, 0.5 * scaleW) && p.wJumpAt > p.first) || (p.maxJump > 60 && p.jumpAt > p.first));
    const runaway = per.filter((p) => !(p.far < 1e5));
    const flicker = per.filter((p) => p.gaps >= 1);
    const pulsing = per.filter((p) => p.pulses >= 2);
    // Each page's drawn membership over time: churn is a page redrawn in pieces.
    const byUrl = new Map<string, number[]>();
    for (let s = 0; s < this.meta.length; s++) {
      const u = this.meta[s].url; if (!u) continue;
      let a = byUrl.get(u); if (!a) { a = new Array(F).fill(0); byUrl.set(u, a); }
      const sc = this.screen[s];
      for (let f = 0; f < F; f++) if (Number.isFinite(sc[f * 2])) a[f]++;
    }
    const churn = [...byUrl.entries()].map(([u, a]) => {
      let up = 0, down = 0;
      for (let f = 1; f < F; f++) { const d = a[f] - a[f - 1]; if (d > 0) up += d; else down -= d; }
      return { url: u.slice(-60), first: a[0], last: a[F - 1], added: up, removed: down,
               min: Math.min(...a), max: Math.max(...a),
               series: a.filter((_v, i) => i % Math.max(1, Math.floor(F / 40)) === 0) };
    }).filter((c) => c.removed > 0).sort((x, y) => y.removed - x.removed).slice(0, 5);
    const vibrating = per.filter((p) => flipRate(p) >= 6 && p.path >= 40 && p.path >= 3 * Math.max(p.net, 1));
    const drifting = per.filter((p) => !this.meta[p.s].force && this.meta[p.s].level !== "page" && p.net >= 80);
    // Coincident: identical world positions at the end.
    const keyOf = (p: any) => `${p.wx.toFixed(4)},${p.wy.toFixed(4)},${p.wz.toFixed(4)}`;
    const groups = new Map<string, any[]>();
    for (const p of per) { if (!Number.isFinite(p.wx)) continue; const k = keyOf(p); (groups.get(k) || groups.set(k, []).get(k)!).push(p); }
    const stacked = [...groups.values()].filter((g) => g.length > 1);
    // Collapsed: many nodes within 3 px on screen.
    const cells = new Map<string, number>();
    for (const p of per) if (p.onCanvas && !p.behind) { const k = `${Math.floor(p.x / 3)},${Math.floor(p.y / 3)}`; cells.set(k, (cells.get(k) || 0) + 1); }
    const clumps = [...cells.entries()].filter(([, c]) => c >= 15).sort((a, b) => b[1] - a[1]);
    // Why a node is not seen.
    const vis = { tracked: per.length, visible: 0, sub_pixel: 0, off_canvas: 0, behind_camera: 0,
                  stacked_under_another: stacked.reduce((a, g) => a + g.length - 1, 0) };
    for (const p of per) {
      if (p.behind) vis.behind_camera++;
      else if (!p.onCanvas) vis.off_canvas++;
      else if (!(p.size >= 0.75)) vis.sub_pixel++;
      else vis.visible++;
    }
    const q = (xs: number[], pp: number) => { if (!xs.length) return null; const s = xs.slice().sort((a, b) => a - b); return s[Math.min(s.length - 1, Math.floor(pp * s.length))]; };
    const step = Math.max(1, Math.floor(F / 60));
    // Links: the ones far longer than the rest, with what they join.
    const links = this.linksNow ? this.linksNow() : [];
    const lens: { l: number; a: any; b: any }[] = [];
    for (const l of links) {
      const a = l.source, b = l.target;
      if (typeof a !== "object" || typeof b !== "object" || !a || !b) continue;
      const len = Math.hypot(a.x - b.x, a.y - b.y, (a.z || 0) - (b.z || 0));
      if (Number.isFinite(len)) lens.push({ l: len, a, b });
    }
    const lenMed = q(lens.map((x) => x.l), 0.5) || 0;
    const tag = (n: any) => ({ id: String(n.id).slice(0, 60), level: n.level, force: !!n.force, url: String(n.url || "").slice(-50) });
    const longLinks = lens.filter((x) => x.l > Math.max(8 * lenMed, 50)).sort((x, y) => y.l - x.l)
      .slice(0, 10).map((x) => ({ length: Math.round(x.l), from: tag(x.a), to: tag(x.b) }));
    return {
      seconds: Math.round(secs * 10) / 10, frames: F, fps: secs > 0 ? Math.round(F / secs) : null,
      wall0: this.wall0, canvas: this.box,
      moving_per_frame: { p50: q(this.movingPx, 0.5), p95: q(this.movingPx, 0.95), max: Math.max(0, ...this.movingPx) },
      alpha: { first: this.alphas[0], last: this.alphas[F - 1], max: Math.max(0, ...this.alphas) },
      series: this.times.filter((_t, i) => i % step === 0).map((t, j) => [Math.round(t), this.movingPx[j * step], Math.round((this.alphas[j * step] || 0) * 1000) / 1000]),
      visibility: vis,
      // Frames the main thread held for over 100 ms, and what came just before.
      stalls: (() => {
        const out: any[] = [];
        for (let f = 1; f < F; f++) {
          const gap = this.times[f] - this.times[f - 1];
          if (gap > 100) out.push({ at_ms: Math.round(this.times[f]), gap_ms: Math.round(gap), after: eventNear(f) });
        }
        const gaps = out.map((o) => o.gap_ms).sort((a, b) => b - a);
        return { n: out.length, worst_ms: gaps[0] || 0, total_ms: gaps.reduce((a, b) => a + b, 0), list: out.slice(0, 20) };
      })(),
      camera_moved_frames: this.camMoved.filter(Boolean).length,
      links: { n: lens.length, median_len: Math.round(lenMed * 100) / 100, long: longLinks },
      counts: { teleports: teleports.length, runaway: runaway.length, vibrating: vibrating.length, drifting: drifting.length,
                flicker: flicker.length, pulsing: pulsing.length,
                stacked_groups: stacked.length, clumps: clumps.length },
      teleports: byScore(teleports, (p) => p.wJump).map((p) => describe(p)),
      runaway: byScore(runaway, (p) => p.far).map((p) => describe(p)),
      flicker: byScore(flicker, (p) => p.gaps).map((p) => describe(p)),
      pulsing: byScore(pulsing, (p) => p.pulses).map((p) => describe(p)),
      page_churn: churn,
      // Every anomaly counted by page, in full (the lists above are top 12).
      by_url: (() => {
        const tally = (xs: any[]) => { const m = new Map<string, number>(); for (const p of xs) { const u = this.meta[p.s].url; m.set(u, (m.get(u) || 0) + 1); } return [...m.entries()].sort((a, b) => b[1] - a[1]).slice(0, 8); };
        return { teleports: tally(teleports), vibrating: tally(vibrating), drifting: tally(drifting), pulsing: tally(pulsing) };
      })(),
      world_scale: Math.round(scaleW * 100) / 100,
      vibrating: byScore(vibrating, (p) => p.flips).map((p) => describe(p)),
      drifting: byScore(drifting, (p) => p.net).map((p) => describe(p)),
      stacked: stacked.sort((a, b) => b.length - a.length).slice(0, 8).map((g) => ({ n: g.length, at: [g[0].wx, g[0].wy, g[0].wz].map((v: number) => Math.round(v * 1000) / 1000), ids: g.slice(0, 6).map((p: any) => this.meta[p.s].id) })),
      clumps: clumps.slice(0, 8).map(([k, c]) => ({ cell_px: k.split(",").map((v) => Number(v) * 3), nodes: c })),
      force_totals: [...this.dv.entries()].map(([n, acc]) => [n, Math.round(acc.reduce((a, b) => a + (b >= 1e9 ? 0 : b), 0))]).sort((a: any, b: any) => b[1] - a[1]),
      events: this.events.slice(0, 400),
    };
  }
}

export const MOTION_FORCES = FORCES;
