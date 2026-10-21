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

import { Verifier } from "./verify";
import type { App } from "obsidian";
import { uiState } from "./uistate";
import { profiler } from "./profile";
import { StressRun } from "./stress";
import { SessionSwitch } from "./session";
import { treeVerdict } from "./treeguard";
import { isolation, WORLD } from "./isolate";
import { anomalies } from "./anomalies";

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

/**
 * Bumped whenever the `fetch` wrapper below changes, so a reloaded plugin
 * replaces the previous instance's closure instead of deferring to it.
 */
const HARNESS_WRAPPER = 2;

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
  // The live checks, run inside the plugin (`G-75`): one verifier for the
  // app's lifetime, so a run in progress survives a pane closing.
  const verifier = new Verifier(app, sidecarBase);
  const trace = new Trace();
  // An empty test workspace, or the reader's own (`session.ts`).
  const session = new SessionSwitch(app, verifier);

  // ---- the boundary ----
  const w = window as any;
  // **The guard holds the TRACE, not a boolean.**
  //
  // A plain `__vertiscopeFetchWrapped` flag survived a plugin reload while the
  // closure it guarded did not: the old wrapper stayed installed, writing
  // into the previous instance's `Trace`, and every gesture after a reload
  // reported `calls: 0` for work that plainly happened. Keeping the live
  // trace on the window and re-pointing it makes the wrapper outlive the
  // instance on purpose rather than by accident.
  w.__vertiscopeTrace = trace;
  // **Versioned, because a boolean guard cannot be re-earned.**
  //
  // `__vertiscopeFetchWrapped = true` stayed true across a plugin reload while
  // the closure it guarded belonged to the previous instance, so a build
  // that changed the wrapper could never install it and every gesture after
  // a reload reported `calls: 0` for work that plainly happened. Bumping
  // this constant is how a new wrapper says it is new; the old one is left
  // in the chain and simply delegates.
  if (w.__vertiscopeFetchWrapped !== HARNESS_WRAPPER) {
    const real = w.fetch.bind(w);
    w.fetch = async (input: any, init?: any) => {
      const url = typeof input === "string" ? input
        : (input && input.url) ? input.url : String(input);
      const base = (sidecarBase() || "").trim().replace(/\/+$/, "");
      const ours = base && url.startsWith(base);
      const live = w.__vertiscopeTrace || trace;
      if (!ours || !live.recording) return real(input, init);

      const t0 = performance.now();
      let res: Response;
      try {
        res = await real(input, init);
      } catch (e) {
        (w.__vertiscopeTrace || trace).add({
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
      (w.__vertiscopeTrace || trace).add({
        method: (init && init.method) || "GET",
        route: url.slice(base.length).split("?")[0],
        ms, status: res.status, bytes: len, reply,
      });
      return res;
    };
    w.__vertiscopeFetchWrapped = HARNESS_WRAPPER;
  }

  // ---- gestures, through the application's own paths ----
  const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

  const leaf = (type: string) => (app.workspace.getLeavesOfType(type)[0] as any);
  const stress = new StressRun(() => ({ browser: leaf("vertiscope-browser-view")?.view,
                                         graph: leaf("vertiscope-graph-view")?.view }));

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
        // No `profile`: the pipeline's statistics are the browser cell's
        // corner box now (`G-76`) -- see the `pipebox` gesture.
        const cmd = { graph: "vertiscope-open-graph", browser: "vertiscope-open-browser",
                      terminal: "vertiscope-open-terminal" }[arg as string];
        if (!cmd) return { error: "no such pane: " + arg };
        // **Prefixed with the plugin id**, which is how Obsidian stores a
        // plugin's commands. Called bare, `executeCommandById` returns false
        // and does nothing -- so `open` was a no-op for every pane, and it
        // looked as though it worked only because the graph happened to be
        // open already. It says so now when a command does not run.
        const ran = (app as any).commands.executeCommandById("vertiscope-bridge:" + cmd);
        if (!ran) return { error: "command did not run: vertiscope-bridge:" + cmd };
        await sleep(1200);
        const l = await ready("vertiscope-" + arg + "-view");
        if (l) app.workspace.revealLeaf(l);
        await sleep(600);
        return { opened: arg };
      }
      case "reveal": {
        const l = await ready("vertiscope-" + arg + "-view");
        if (!l) return { error: "not open: " + arg };
        app.workspace.revealLeaf(l);
        await sleep(600);
        return { revealed: arg };
      }
      case "scan": {
        const l = await ready("vertiscope-browser-view");
        if (!l?.view) return { error: "no browser" };
        await l.view.scan(arg || {});
        return { scan: l.view.lastScan };
      }
      case "navigate": {
        const l = await ready("vertiscope-browser-view");
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
      /**
       * Unravel a page one patricia step (`G-54`), through the projector's
       * own `unfoldNode`.
       *
       * `arg` is a url, or omitted to open the page with the most chunks.
       * The reply carries what the step revealed -- branch count, reach,
       * and the gap to the nearest other page -- because "it unfolded" and
       * "it unfolded INSIDE its own territory" are different claims and
       * only the second one is the requirement.
       */
      case "unfold": {
        const l = await ready("vertiscope-graph-view");
        const view: any = l?.view;
        const proj: any = view?.projector || view;
        if (!proj?.graph) return { error: "no projector" };
        const data: any = proj.graph.graphData();
        const pages = data.nodes.filter((n: any) => n.level === "page");
        const hub = arg
          ? pages.find((n: any) => n.url === arg || n.id === "page:" + arg)
          : pages.slice().sort(
              (a: any, b: any) => (b.members ?? 0) - (a.members ?? 0))[0];
        if (!hub) return { error: "no such page: " + arg };
        const before = data.nodes.length;
        await proj.unfoldNode(hub);
        await sleep(1200);
        const after: any = proj.graph.graphData();
        const by = new Map<string, any>(after.nodes.map((n: any) => [n.id, n]));
        const dist = (a: any, b: any) =>
          Math.hypot(a.x - b.x, a.y - b.y, a.z - b.z);
        // Branches only: an inter-page link leaves the same hub, and
        // counting one as a branch once read as a spill that was not one.
        const kids = after.links
          .filter((e: any) => ((e.source?.id ?? e.source) === hub.id))
          .map((e: any) => by.get(e.target?.id ?? e.target))
          .filter((k: any) => k && k.level !== "page" && k.url === hub.url);
        let gap = Infinity;
        for (const o of after.nodes) {
          if (o === hub || o.level !== "page") continue;
          const t = dist(o, hub);
          if (t < gap) gap = t;
        }
        // From the ANCHOR, not the hub: containment is defined against the
        // page's position in the fit, and the hub is a node the collider
        // moves. Measuring from it reported a spill that was not one.
        const at = kids[0]?.anchorPos;
        const from = at ? { x: at[0], y: at[1], z: at[2] } : hub;
        const room = kids[0]?.room ?? null;
        const reach = kids.length
          ? Math.max(...kids.map((k: any) => dist(k, from))) : 0;
        return {
          page: hub.url, nodes_before: before, nodes_after: after.nodes.length,
          branches: kids.length,
          room: room === null ? null : Math.round(room * 10) / 10,
          reach_from_anchor: Math.round(reach * 10) / 10,
          reach_from_hub: kids.length
            ? Math.round(Math.max(...kids.map((k: any) => dist(k, hub))) * 10) / 10
            : 0,
          gap_to_nearest_page: Math.round(gap * 10) / 10,
          stayed_inside: reach <= gap * 0.5,
        };
      }
      /**
       * Press a node, which is what a reader does (`G-40`, `G-57`).
       *
       * Through the projector's own click path rather than a synthetic
       * mouse event, because a hit test against a rotated 3D scene is a
       * source of flake that says nothing about the requirement.
       */
      case "click": {
        const l = await ready("vertiscope-graph-view");
        const view: any = l?.view;
        const proj: any = view?.projector || view;
        if (!proj?.graph) return { error: "no projector" };
        const data: any = proj.graph.graphData();
        const node = data.nodes.find(
          (n: any) => n.id === arg || n.url === arg || n.id === "page:" + arg);
        if (!node) return { error: "no such node: " + arg };
        const handler = proj.graph.onNodeClick();
        if (typeof handler !== "function") return { error: "no click handler" };
        await handler(node);
        await sleep(1500);
        const br: any = leaf("vertiscope-browser-view")?.view;
        return {
          clicked: node.id, level: node.level,
          browser_url: br?.webview ? (() => {
            try { return br.webview.getURL(); } catch { return null; }
          })() : null,
          billboards: proj.billboards ? proj.billboards.size : 0,
        };
      }
      /**
       * Run a retrieval the way the overlay does (`G-56`, `G-71`), and
       * report what it put ON SCREEN rather than what the sidecar returned.
       * Those came apart once already: hits arrived and nothing was drawn.
       */
      case "retrieve": {
        const l = await ready("vertiscope-graph-view");
        const view: any = l?.view;
        const proj: any = view?.projector || view;
        if (!proj?.graph) return { error: "no projector" };
        const before = proj.graph.graphData().nodes.length;
        const got = await (app as any).plugins
          .getPlugin("vertiscope-bridge")?.sidecar?.search(String(arg || ""), 8);
        const hits = (got && (got.hits || [])) || [];
        const byUrl: Record<string, string[]> = {};
        for (const h of hits) {
          if (!h?.cid || !h?.url) continue;
          (byUrl[h.url] = byUrl[h.url] || []).push(h.cid);
        }
        for (const [url, cids] of Object.entries(byUrl)) {
          if (typeof proj.showHits === "function") await proj.showHits(url, cids);
        }
        await sleep(1200);
        const after: any = proj.graph.graphData();
        const drawn = new Set(after.nodes.map((n: any) => n.id));
        return {
          query: arg, hits: hits.length,
          pages_touched: Object.keys(byUrl).length,
          nodes_before: before, nodes_after: after.nodes.length,
          hits_now_drawn: hits.filter((h: any) => drawn.has(h.cid)).length,
        };
      }
      /**
       * Reload the plugin -- **the first act of any probe that scores it.**
       *
       * A collider probe once passed with its own target defect planted and
       * returned numbers identical to the clean run, because it reopened
       * the pane but never reloaded the code. `npm run build` had replaced
       * a file nobody was running.
       */
      case "reload": {
        const plugins = (app as any).plugins;
        await plugins.disablePlugin("vertiscope-bridge");
        await plugins.enablePlugin("vertiscope-bridge");
        await sleep(4000);
        return { reloaded: true, enabled: !!plugins.getPlugin("vertiscope-bridge") };
      }
      case "level": {
        // The projector's own switch, not a re-fetch: this is the thing a
        // reader presses.
        const l = await ready("vertiscope-graph-view");
        if (!l?.view) return { error: "no graph" };
        if (typeof l.view.setLevel === "function") {
          await l.view.setLevel(arg);
        } else {
          return { error: "no setLevel on the view" };
        }
        await sleep(1500);
        return { level: arg };
      }
      /**
       * Open or close the pipeline readout in the browser's corner (`G-76`).
       * The same state a reader's click sets -- so what a tool opens, the
       * person watching sees open.
       */
      /**
       * Run the checks the way a person does: open the corner box and PRESS
       * its button -- "run all", or "fresh store" (`G-87`). `arg` is "all"
       * or "fresh"; `{fresh, ids}` runs a subset, which has no button, so
       * that one goes straight to the verifier the buttons call. Returns at
       * once; the run shows in the box, and `ui()` reads it back.
       */
      case "checks": {
        const l = await ready("vertiscope-browser-view");
        const pb: any = l?.view?.pipebox;
        if (!pb) return { error: "no corner box" };
        // Remembered, so whoever reads the verdicts can put the box back the
        // way the reader had it: left open after a run it covered a third of
        // the page (P104: no panel may cover the view).
        pb.openedForChecks = !pb.expanded;
        pb.setExpanded(true);
        await sleep(400);
        const v: any = (window as any).__vertiscope?.verify;
        if (arg && typeof arg === "object" && Array.isArray(arg.ids) && arg.ids.length) {
          const st = arg.fresh ? v.startFresh(arg.ids) : v.start(arg.ids);
          return { started: st.run, total: st.total, pressed: null };
        }
        const want = arg === "fresh" ? "fresh store" : "run all";
        const button = Array.from(pb.el.querySelectorAll("button.vertiscope-pipebox-run"))
          .find((b: any) => (b.textContent || "").trim() === want) as HTMLElement | undefined;
        if (!button) return { error: `no "${want}" button in the box -- is a run going?` };
        button.click();
        await sleep(300);
        return { pressed: want, started: v.state().run };
      }
      /**
       * Reload THIS plugin, so the build on disk is the one that runs. Done
       * on a timer after replying, because the reload ends the code that was
       * asked -- the reply has to leave first.
       */
      case "reload": {
        const id = "vertiscope-bridge";
        const plugins = (app as any).plugins;
        setTimeout(() => {
          void plugins.disablePlugin(id).then(() => plugins.enablePlugin(id));
        }, 200);
        return { reloading: id };
      }
      case "pipebox": {
        const l = await ready("vertiscope-browser-view");
        const pb: any = l?.view?.pipebox;
        if (!pb) return { error: "no corner box" };
        const want = arg === "toggle" ? !pb.expanded
          : arg === "restore" ? (pb.openedForChecks ? false : pb.expanded) : arg !== "close";
        pb.setExpanded(want);
        if (arg === "restore") pb.openedForChecks = false;
        await sleep(300);
        return { expanded: pb.expanded };
      }
      /**
       * Pin a chunk, as a right-click does (`G-78`). `arg` is an xpath in
       * the page, or `{x, y}` in the page's viewport. Returns what pinned it
       * -- the outline, the markdown side and the billboard are read back
       * from `ui()`, not asserted here.
       */
      case "pin": {
        const l = await ready("vertiscope-browser-view");
        const view: any = l?.view;
        if (!view) return { error: "no browser" };
        let xpath = typeof arg === "string" ? arg : "";
        if (!xpath && arg && typeof arg.x === "number") {
          xpath = await view.webview.executeJavaScript(
            "(function(){var el=document.elementFromPoint(" + arg.x + "," + arg.y + ");" +
            "if(!el) return '';var parts=[];" +
            "while(el && el.nodeType===1 && el.tagName){" +
            "var tag=el.tagName.toLowerCase(),i=1,sib=el.previousElementSibling;" +
            "while(sib){if(sib.tagName===el.tagName)i++;sib=sib.previousElementSibling;}" +
            "parts.unshift(i>1?tag+'['+i+']':tag);el=el.parentElement;}" +
            "return '/'+parts.join('/');})()");
        }
        if (!xpath) return { error: "nothing to pin" };
        const got = await view.pinXpath(xpath);
        await sleep(1500);
        return got;
      }
      case "unpin": {
        const l = await ready("vertiscope-browser-view");
        const view: any = l?.view;
        if (!view) return { error: "no browser" };
        const all = view.pinnedState().map((p: any) => p.cid);
        for (const cid of (arg === "all" || !arg) ? all : [arg]) view.unpin(cid);
        await sleep(500);
        return { unpinned: arg || "all", left: view.pinnedState().length };
      }
      default:
        return { error: "unknown gesture: " + name };
    }
  }

  w.__vertiscope = {
    /** Hardware-in-the-loop checks (`G-75`): start a run, read its state.
     *  `start` returns at once; poll `state()` -- a full run is minutes. */
    /** The empty-workspace switch: `empty()` starts a test workspace on its
     *  own sidecar, `reader()` returns to the reader's own. */
    session: {
      empty: () => session.empty(),
      reader: () => session.reader(),
      restart: () => session.restart(),
      state: () => session.state(),
      switcher: session,
    },
    verify: {
      list: () => verifier.list(),
      start: (ids?: string[], label?: string) => verifier.start(ids, label || ""),
      /** Every check on a FRESH store this app starts and fills (`G-87`). */
      startFresh: (ids?: string[]) => verifier.startFresh(ids),
      stop: (why?: string) => verifier.stop(why),
      state: () => verifier.state,
    },
    ui: () => uiState(app),
    /** Rapid scroll and hover on one page, every pipeline stage read per
     *  segment: time, memory, the 3D stream, render (`stress.ts`). `start`
     *  returns at once; poll `state()`. */
    stress: {
      start: (o?: any) => stress.start(o || {}),
      stop: () => stress.stop(),
      state: () => stress.state(),
    },
    /** The 3D view's flight recorder: every node's motion, per-force pushes and
     *  pipeline events over a window, then the anomalies (`motion.ts`).
     *  `start` returns at once; `state().result` once the window closes. */
    motion: {
      start: (o?: any) => leaf("vertiscope-graph-view")?.view?.motion?.start(o || {}) ?? { error: "no graph view" },
      stop: () => leaf("vertiscope-graph-view")?.view?.motion?.stop() ?? null,
      state: () => leaf("vertiscope-graph-view")?.view?.motion?.state() ?? { error: "no graph view" },
    },
    /** An off-screen camera framed on one page (default: the one browsed),
     *  rendered to a PNG data URL -- the page at the scale its glitches live. */
    // Where the sensor runs: the isolated world's call count, and every
    // fall-back to the page's main world (2026-10-06).
    isolation: () => ({ world: WORLD, ...isolation }),
    // Everything the reader reported on 2026-10-06, measured by the app's
    // own objects: phantoms, stale links, the stream's tree shape, panels,
    // pictures, the overlay's bounds, latency. One instrument for the MCP
    // server, the checks and the probes.
    anomalies: () => anomalies(app, () => profiler().list()),
    // Is what the 3D view draws a tree, over EVERY drawn edge? (2026-10-04)
    tree: () => {
      const g = leaf("vertiscope-graph-view")?.view?.graph;
      if (!g) return { error: "no graph view" };
      const d = g.graphData();
      return treeVerdict(d.nodes, d.links);
    },
    inspect: (url?: string, size?: number) => leaf("vertiscope-graph-view")?.view?.inspect(url || "", size || 480) ?? { error: "no graph view" },
    /** Milliseconds since the reader last used this app (rule g's gate). */
    reader: { idleMs: () => Date.now() - ((window as any).__vertiscopeReaderAt || 0) },
    /** The pipeline profiler: traces from the page to the pixels. */
    profile: {
      summary: () => profiler().summary(),
      traces: (n = 20) => profiler().list().slice(-n),
      visits: () => profiler().visits(),
      reset: () => { profiler().reset(); return true; },
    },
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
  w.__vertiscopeUI = () => uiState(app);
}
