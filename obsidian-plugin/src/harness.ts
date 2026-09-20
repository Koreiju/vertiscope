/**
 * The harness: one wrapper over the UI layer, for observation, interaction
 * and the backend work that follows from it.
 *
 * **The problem it exists for.** The live checks could read JavaScript
 * properties and nothing else. That told us what the backend intended, never
 * what a reader saw, and never what a gesture COST: three checks passed --
 * "nodes are discernible, not a clump", "nodes never overlap", "every node
 * is on screen" -- while the pane showed 558 nodes piled into one quadrant
 * with a fifth of them off the canvas. Verifying by screenshot is the other
 * failure: expensive, and a picture cannot be asserted on.
 *
 * So there are three things here and they are deliberately one object:
 *
 *   * `ui()`   -- the interface as a data structure, in SCREEN pixels,
 *                 distinguishing drawn from merely present.
 *   * `trace`  -- every sidecar call, captured at the `fetch` boundary.
 *   * `act()`  -- a named gesture, run through the application's own code
 *                 paths, returning the UI before, the UI after, and the
 *                 backend calls it caused.
 *
 * **Why `fetch` and not the client's methods.** `Sidecar` has a dozen call
 * sites and gains more. Wrapping each one is a refactor that goes stale;
 * wrapping the boundary catches every route, including ones written later,
 * and cannot drift from the code it watches.
 *
 * **Why a gesture returns before/after/trace together.** A chained
 * interaction -- click a node, watch the browser move, watch the trie get
 * written, watch the panel redraw -- was a dozen round trips and a guess
 * about ordering. One call now answers "what did this do, everywhere".
 */

import type { App } from "obsidian";
import { uiState } from "./uistate";

export interface TraceCall {
  /** Milliseconds since the recording started. */
  at: number;
  method: string;
  /** Path only: the base is noise and repeats on every row. */
  route: string;
  ms: number;
  status: number | string;
  bytes: number | null;
  /** A few fields from the reply, for routes whose reply is the point. */
  reply?: Record<string, unknown>;
}

/** Reply fields worth keeping. Everything else is bulk. */
const KEEP = [
  "ms", "dirty", "addresses", "chunks", "n", "level", "space", "from_store",
  "unplaced", "why", "stale", "error", "depth", "branches", "leaves",
  "chunks_removed", "hits", "total", "place_error",
];

function summarise(body: any): Record<string, unknown> | undefined {
  if (!body || typeof body !== "object") return undefined;
  const out: Record<string, unknown> = {};
  for (const k of KEEP) {
    if (k in body) {
      const v = (body as any)[k];
      // Counts, not contents: `hits` is a list of chunks and the number is
      // the fact. A trace that carries payloads is a transcript, not a trace.
      out[k] = Array.isArray(v) ? v.length : v;
    }
  }
  return Object.keys(out).length ? out : undefined;
}

class Trace {
  private calls: TraceCall[] = [];
  private t0 = 0;
  recording = false;
  /** Bounded, so a forgotten recording cannot grow without limit. */
  private cap = 500;

  start(cap = 500) {
    this.calls = [];
    this.cap = cap;
    this.t0 = performance.now();
    this.recording = true;
  }

  add(call: Omit<TraceCall, "at">) {
    if (!this.recording || this.calls.length >= this.cap) return;
    this.calls.push({ at: Math.round(performance.now() - this.t0), ...call });
  }

  stop(): TraceCall[] {
    this.recording = false;
    return this.calls;
  }

  drain(): TraceCall[] {
    const got = this.calls;
    this.calls = [];
    return got;
  }

  /** The shape of the work, rather than every row of it. */
  summary(calls = this.calls) {
    const byRoute: Record<string, { n: number; ms: number }> = {};
    for (const c of calls) {
      const r = byRoute[c.route] || (byRoute[c.route] = { n: 0, ms: 0 });
      r.n += 1;
      r.ms += c.ms;
    }
    for (const r of Object.values(byRoute)) r.ms = Math.round(r.ms);
    return {
      calls: calls.length,
      total_ms: Math.round(calls.reduce((a, c) => a + c.ms, 0)),
      by_route: byRoute,
      failures: calls.filter((c) => c.status !== 200).length,
    };
  }
}

export function installHarness(app: App, sidecarBase: () => string) {
  const trace = new Trace();

  // ---- the boundary ----
  const w = window as any;
  if (!w.__domvecFetchWrapped) {
    const real = w.fetch.bind(w);
    w.fetch = async (input: any, init?: any) => {
      const url = typeof input === "string" ? input
        : (input && input.url) ? input.url : String(input);
      const base = (sidecarBase() || "").trim().replace(/\/+$/, "");
      const ours = base && url.startsWith(base);
      if (!ours || !trace.recording) return real(input, init);

      const t0 = performance.now();
      let res: Response;
      try {
        res = await real(input, init);
      } catch (e) {
        trace.add({
          method: (init && init.method) || "GET",
          route: url.slice(base.length).split("?")[0],
          ms: Math.round(performance.now() - t0),
          status: "threw", bytes: null,
          reply: { error: String(e).slice(0, 80) },
        });
        throw e;
      }
      const ms = Math.round(performance.now() - t0);
      const len = Number(res.headers.get("content-length") || 0) || null;

      // **Cloned, and only when small.** Reading the body would consume it
      // and the caller would get an empty stream; cloning a megabyte layout
      // to count its keys is a cost the trace should not impose.
      let reply: Record<string, unknown> | undefined;
      const type = res.headers.get("content-type") || "";
      if (type.includes("json") && (len === null || len < 65536)) {
        try { reply = summarise(await res.clone().json()); } catch { /* not json */ }
      }
      trace.add({
        method: (init && init.method) || "GET",
        route: url.slice(base.length).split("?")[0],
        ms, status: res.status, bytes: len, reply,
      });
      return res;
    };
    w.__domvecFetchWrapped = true;
  }

  // ---- gestures, through the application's own paths ----
  const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

  const leaf = (type: string) => (app.workspace.getLeavesOfType(type)[0] as any);

  /**
   * A leaf that is loaded, laid out, and usable.
   *
   * **Three states, and only the first is obvious.** A leaf in a background
   * tab hands back a DEFERRED stub with none of the view's methods;
   * `loadIfDeferred` resolves BEFORE the guest emits `dom-ready`, and every
   * webview method then throws "The WebView must be attached to the DOM and
   * the dom-ready event emitted"; and a loaded, ready pane in a background
   * tab still has a 0x0 box, so any coordinate taken from it is meaningless.
   * A gesture that skips these reports the application as broken when it is
   * merely behind another tab -- which is what `navigate` did.
   */
  const ready = async (type: string, ms = 30000) => {
    const until = Date.now() + ms;
    let l: any = null;
    while (Date.now() < until) {
      l = leaf(type);
      if (l) {
        if (l.loadIfDeferred) await l.loadIfDeferred();
        if (l.view) break;
      }
      await sleep(250);
    }
    if (!l || !l.view) return l;
    // Laid out: a background tab has no box, and the guest has no viewport.
    app.workspace.revealLeaf(l);
    const wv = l.view.webview;
    if (wv) {
      while (Date.now() < until) {
        try { wv.getURL(); break; } catch { await sleep(200); }
      }
      // And a real size, or a click lands nowhere.
      while (Date.now() < until) {
        const r = l.view.containerEl?.getBoundingClientRect?.();
        if (r && r.width > 50 && r.height > 50) break;
        await sleep(200);
      }
    }
    return l;
  };

  async function gesture(name: string, arg?: any): Promise<any> {
    switch (name) {
      case "open": {
        const cmd = { graph: "domvec-open-graph", browser: "domvec-open-browser",
                      terminal: "domvec-open-terminal" }[arg as string];
        if (!cmd) return { error: "no such pane: " + arg };
        await (app as any).commands.executeCommandById(cmd);
        await sleep(1200);
        const l = await ready("domvec-" + arg + "-view");
        if (l) app.workspace.revealLeaf(l);
        await sleep(600);
        return { opened: arg };
      }
      case "reveal": {
        const l = await ready("domvec-" + arg + "-view");
        if (!l) return { error: "not open: " + arg };
        app.workspace.revealLeaf(l);
        await sleep(600);
        return { revealed: arg };
      }
      case "scan": {
        const l = await ready("domvec-browser-view");
        if (!l?.view) return { error: "no browser" };
        await l.view.scan(arg || {});
        return { scan: l.view.lastScan };
      }
      case "navigate": {
        const l = await ready("domvec-browser-view");
        if (!l?.view) return { error: "no browser" };
        l.view.go(arg);
        for (let i = 0; i < 80; i++) {
          await sleep(250);
          try {
            if (!l.view.webview.isLoading() &&
                l.view.webview.getURL().indexOf(arg) === 0) break;
          } catch { /* not ready */ }
        }
        return { url: l.view.webview.getURL() };
      }
      case "level": {
        // The projector's own switch, not a re-fetch: this is the thing a
        // reader presses.
        const l = await ready("domvec-graph-view");
        if (!l?.view) return { error: "no graph" };
        if (typeof l.view.setLevel === "function") {
          await l.view.setLevel(arg);
        } else {
          return { error: "no setLevel on the view" };
        }
        await sleep(1500);
        return { level: arg };
      }
      default:
        return { error: "unknown gesture: " + name };
    }
  }

  w.__domvec = {
    ui: () => uiState(app),
    trace: {
      start: (cap?: number) => trace.start(cap),
      stop: () => trace.stop(),
      drain: () => trace.drain(),
      summary: () => trace.summary(),
      recording: () => trace.recording,
    },
    /**
     * Do a thing, and report everything it touched.
     *
     * `full` returns every captured call; the default returns the SHAPE --
     * counts and milliseconds by route -- because that is what answers "did
     * this gesture do the backend work it should have" without paying for a
     * transcript.
     */
    act: async (name: string, arg?: any, opts: { full?: boolean } = {}) => {
      const before = uiState(app);
      trace.start();
      let result: any;
      try {
        result = await gesture(name, arg);
      } catch (e) {
        result = { threw: String(e).slice(0, 200) };
      }
      const calls = trace.stop();
      const after = uiState(app);
      return {
        gesture: name, arg, result,
        backend: opts.full ? calls : trace.summary(calls),
        ui_before: before,
        ui_after: after,
      };
    },
  };
  w.__domvecUI = () => uiState(app);
}
