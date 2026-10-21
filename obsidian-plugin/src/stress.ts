/**
 * The stress gesture: rapid scroll and hover on one page, with every stage of
 * the pipeline read between segments (2026-09-28: "a simple rapid scroll and
 * hover feature while listening and watching for this site specifically
 * (time-memory-profile dentistry)").
 *
 * It lives in the plugin, not in a script beside it, because the question it
 * answers is about the ONE pipeline -- page, sensor fold, push, capture,
 * store, 3D stream, render -- and a driver outside the app could only read
 * that pipeline through whatever the app happened to expose. Here each
 * segment reads the same objects the pipeline writes:
 *
 *   host      timer lag per step (how late the host's own timers ran), JS heap
 *   guest     the page's JS heap and element count (Discourse's endless list
 *             kept 469k nodes when D-38 was a renderer out of memory)
 *   stream    payloads the sensor pushed, drains the 3D view applied, nodes
 *             added -- the "same proportion" the reader asked about
 *   stages    per-stage p50/p95 of every trace that STARTED in the segment
 *   render    draw calls, render CPU ms, batch sync ms (G-107)
 *   guard     non-finite positions caught, and which force wrote them
 *
 * Nothing is written into the page: input goes in as the reader's would
 * (`sendInputEvent`), and the guest is only READ. Rule g: the run stops the
 * moment the reader touches the app.
 */
import { profiler } from "./profile";

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export interface StressOptions {
  /** Load this page first unless the cell already shows it. */
  url?: string;
  /** Total seconds (default 60) and seconds per segment (default 10). */
  seconds?: number;
  segment?: number;
  /** Wheel delta per step, px (default 700; negative scrolls up). */
  wheel?: number;
}

export class StressRun {
  running = false;
  url = "";
  startedAt = 0;
  segments: any[] = [];
  error: string | null = null;
  stopReason = "";
  private stopAsked = false;

  constructor(private views: () => { browser: any; graph: any }) {}

  start(o: StressOptions = {}): any {
    if (this.running) return { error: "a stress run is already going", state: this.state() };
    this.running = true;
    this.stopAsked = false;
    this.stopReason = "";
    this.error = null;
    this.segments = [];
    this.startedAt = Date.now();
    void this.loop(o).catch((e) => { this.error = String(e?.message || e); })
      .finally(() => { this.running = false; (window as any).__vertiscopeStressing = false; });
    return { started: true };
  }

  stop(why = "asked"): any {
    this.stopAsked = true;
    this.stopReason = why;
    return { stopping: this.running };
  }

  state(): any {
    const segs = this.segments;
    const slope = (key: (s: any) => number | null) => {
      const pts = segs.map((s) => [s.at_s, key(s)]).filter((p) => typeof p[1] === "number") as number[][];
      if (pts.length < 2) return null;
      const [a, b] = [pts[0], pts[pts.length - 1]];
      return b[0] > a[0] ? Math.round(((b[1] - a[1]) / (b[0] - a[0])) * 60 * 10) / 10 : null;
    };
    return {
      running: this.running, url: this.url, started_at: this.startedAt, error: this.error,
      stop_reason: this.stopReason, segments: segs,
      // Growth per minute across the run: a leak shows as a slope, not a level.
      host_heap_mb_per_min: slope((s) => s.host.heap_mb),
      guest_heap_mb_per_min: slope((s) => s.guest?.heap_mb ?? null),
      guest_elements_per_min: slope((s) => s.guest?.elements ?? null),
    };
  }

  private async loop(o: StressOptions): Promise<void> {
    const total = (o.seconds ?? 60) * 1000, seg = (o.segment ?? 10) * 1000, wheel = o.wheel ?? 700;
    let { browser: b, graph: g } = this.views();
    if (!b?.webview) throw new Error("no browser cell");
    const w = b.webview;
    // Exact: a prefix test once left the cell on a check's ?g107= variant
    // of the forum -- a page the store had never seen -- and called it done.
    if (o.url && String(w.getURL()) !== o.url) {
      b.go(o.url);
      await sleep(7000);
    }
    this.url = String(w.getURL());
    (window as any).__vertiscopeStressing = true;
    const readerAt0 = (window as any).__vertiscopeReaderAt || 0;
    const t00 = performance.now();
    while (performance.now() - t00 < total && !this.stopAsked) {
      ({ browser: b, graph: g } = this.views());
      const base = {
        pushed: b.pushedPayloads || 0,
        drains: g?.forceStats?.drains || 0, added: g?.forceStats?.added || 0,
        guard: g?.nonFiniteCount || 0, nan: (g?.nanBy || []).length,
        skips: g?.octreeSkips ? g.octreeSkips.collide + g.octreeSkips.charge : 0,
      };
      const t0 = performance.now();
      let asked = 0, steps = 0;
      const r = w.getBoundingClientRect();
      while (performance.now() - t0 < seg && !this.stopAsked) {
        if (((window as any).__vertiscopeReaderAt || 0) !== readerAt0) { this.stop("the reader used the app"); break; }
        w.sendInputEvent({ type: "mouseWheel", x: Math.round(r.width / 2), y: Math.round(r.height / 2),
                           deltaX: 0, deltaY: -wheel });
        await sleep(60); asked += 60;
        for (let k = 0; k < 3; k++) {
          w.sendInputEvent({ type: "mouseMove", x: 60 + Math.floor(Math.random() * Math.max(1, r.width - 120)),
                             y: 80 + Math.floor(Math.random() * Math.max(1, r.height - 160)) });
          await sleep(25); asked += 25;
        }
        steps++;
      }
      const spent = performance.now() - t0;
      this.segments.push(await this.read(b, g, base, t0, steps, spent - asked, t00));
    }
    if (!this.stopReason) this.stopReason = this.stopAsked ? "asked" : "time";
  }

  private async read(b: any, g: any, base: any, t0: number, steps: number, lag: number, t00: number): Promise<any> {
    // The guest, READ only, and never waited on for long: a page that has
    // stopped answering is itself the finding.
    let guest: any = null;
    try {
      guest = await Promise.race([
        b.webview.executeJavaScript(
          "({heap_mb: performance.memory ? Math.round(performance.memory.usedJSHeapSize / 1e6) : null," +
          " elements: document.getElementsByTagName('*').length, scroll_y: Math.round(scrollY)})"),
        sleep(3000).then(() => ({ unanswered_ms: 3000 })),
      ]);
    } catch (e: any) { guest = { error: String(e?.message || e).slice(0, 120) }; }
    // Stages of every trace that started inside this segment.
    const by: Record<string, number[]> = {};
    for (const t of profiler().list()) {
      if (t.t0 < t0) continue;
      for (const [k, v] of Object.entries(t.stages)) (by[k] = by[k] || []).push(v as number);
    }
    const q = (a: number[], p: number) => {
      const s = a.slice().sort((x, y) => x - y);
      return s.length ? Math.round(s[Math.min(s.length - 1, Math.floor(p * (s.length - 1)))] * 10) / 10 : null;
    };
    const stages: Record<string, any> = {};
    for (const [k, a] of Object.entries(by)) stages[k] = { n: a.length, p50: q(a, 0.5), p95: q(a, 0.95) };
    const data = g?.graph?.graphData?.();
    const mem = (performance as any).memory;
    return {
      at_s: Math.round((performance.now() - t00) / 100) / 10,
      steps, timer_lag_ms_per_step: Math.round(lag / Math.max(1, steps)),
      host: { heap_mb: mem ? Math.round(mem.usedJSHeapSize / 1e6) : null },
      guest,
      stream: {
        pushed: (b.pushedPayloads || 0) - base.pushed,
        drains_3d: (g?.forceStats?.drains || 0) - base.drains,
        added_3d: (g?.forceStats?.added || 0) - base.added,
        capture_queue: (b.captureQueue || []).length,
        streaming_drawn: data ? data.nodes.filter((n: any) => n.force).length : null,
        nodes: data ? data.nodes.length : null,
      },
      stages,
      render: typeof g?.renderStats === "function" ? g.renderStats() : null,
      guard: { caught: (g?.nonFiniteCount || 0) - base.guard,
               octree_skips: g?.octreeSkips ? g.octreeSkips.collide + g.octreeSkips.charge - base.skips : null,
               nan_by: (g?.nanBy || []).slice(base.nan).map((x: any) => x.force + ":" + x.nodes) },
    };
  }
}
