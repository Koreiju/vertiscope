/**
 * The live checks, run INSIDE the plugin (`G-75`) -- hardware in the loop.
 *
 * Every requirement check in `checks/live.mjs` drives the running app and
 * reads back what it did. From a terminal those checks talk to Obsidian over
 * CDP, which means a check can only be run by something outside the app, and
 * what it saw is visible only in that terminal. Here the same module runs in
 * the plugin's own window: `evaluate` is this window's eval, the results
 * stream into the browser cell's corner box as each check finishes, and the
 * MCP tools start a run and read it through `window.__vertiscope.verify`.
 *
 * One list of checks, two runners, no copies: `confirm.mjs` is now a client
 * of this same module. A check never reloads the plugin here -- that would
 * end the run that is executing it -- so a runner that must score freshly
 * built code reloads FIRST, from outside, and then asks the plugin to run.
 */

import type { App } from "obsidian";
// @ts-ignore -- plain ESM, bundled by esbuild; typed where it is used below.
import { makeChecks } from "../checks/live.mjs";

export interface CheckResult {
  id: string;
  asks: string;
  pass: boolean;
  evidence: any;
  ms: number;
}

export interface VerifyState {
  run: number;
  running: boolean;
  total: number;
  done: number;
  current: string;
  startedAt: number;
  finishedAt: number;
  results: CheckResult[];
  stoppedBecause: string;
  /** Why the run is waiting now ("" when it is not), how often it paused for
   *  the reader, and how many checks it re-ran because the reader acted in
   *  them (item 98). */
  paused?: string;
  pauses?: number;
  resumed?: number;
  /** What the run read -- "fresh run_…, 12/12 pages seeded" or "working". */
  label: string;
  /** A fresh-store run's seeding, one row per page it browsed. */
  seed?: { url: string; held: boolean; chunks: number | null; s: number; left?: string }[];
  /**
   * A fresh-store run's PHASE TRACE (`G-89`): the graph's representation as
   * the store fills, sampled while seeding -- one row whenever the mode, the
   * page being seeded or the projector's fitted state changes. What the
   * phase contracts are checked against, in order.
   */
  phases?: { t: number; mode: string; nodes: number; force_nodes: number;
             force_pages: number; multi_parent: number; drains: number;
             fitted: boolean | null; seeding: number }[];
  /** A fresh-store run's teardown: back on the working store, test sidecar gone. */
  teardown?: { sidecar: string; test_sidecar_stopped: boolean } | null;
}

/**
 * The pages a fresh store is filled with, by browsing them in the cell --
 * the product's own capture path. Local fixtures (served on a loopback port)
 * first, then the public pages the checks name: G-78/G-79/G-82 open Radix
 * tree, G-80 opens Trie, G-40/G-16 want books.toscrape; the rest give the
 * projector and the ranking more than one subject to separate.
 */
const SEED_FIXTURES = [
  "inline_prose.html", "mixed_inline.html", "link_family.html",
  "metadata_family.html", "svg_diagram.html", "shadow_catalogue.html",
  // Forty records of one shape: what the merge layer groups (G-27, G-63).
  "records_catalog.html",
];
const SEED_PAGES = [
  "https://en.wikipedia.org/wiki/Radix_tree",
  "https://en.wikipedia.org/wiki/Trie",
  "https://books.toscrape.com/",
  "https://en.wikipedia.org/wiki/B-tree",
  "https://en.wikipedia.org/wiki/Hash_table",
  "https://en.wikipedia.org/wiki/Suffix_tree",
];
/** The test sidecar's port: beside the working one, never instead of it. */
const TEST_PORT = 8790;

/**
 * The last run, kept on the WINDOW, which outlives the plugin. A runner that
 * scores freshly built code reloads the plugin; the fresh-store runner
 * reloads it again afterwards to put the plugin back. Held on the Verifier
 * alone, the verdicts vanished from the corner box with that second reload,
 * before anyone had looked at them.
 */
const KEEP = "__vertiscopeLastRun";

export class Verifier {
  state: VerifyState = (window as any)[KEEP] || {
    run: 0, running: false, total: 0, done: 0, current: "",
    startedAt: 0, finishedAt: 0, results: [], stoppedBecause: "", label: "",
  };

  constructor(private app: App, private sidecarUrl: () => string) {
    // A run the reload interrupted is not still running; say what ended it.
    if (this.state.running) {
      this.state.running = false;
      this.state.current = "";
      this.state.stoppedBecause = "the plugin was reloaded mid-run";
    }
  }

  /** What a runner hands the check module, provided from inside the app. */
  private env() {
    const app = this.app;
    const SIDECAR = this.sidecarUrl().trim().replace(/\/+$/, "");
    return {
      SIDECAR,
      // The window's own eval, awaited, and handed back BY VALUE -- the
      // same shape CDP's `returnByValue` gives the terminal runner, so a
      // check cannot pass here on a live object it would not get there.
      evaluate: async (code: string) => {
        const value = await (0, eval)(code);
        return value === undefined ? undefined : JSON.parse(JSON.stringify(value));
      },
      // The fixture pages the checks browse to, served from the vault's own
      // `tests/fixtures` -- the vault is the repository -- on a loopback
      // port, exactly as the terminal runner serves them.
      serveFixtures: async () => {
        const http = (window as any).require("http");
        const fs = (window as any).require("fs/promises");
        const path = (window as any).require("path");
        const base = (app.vault.adapter as any).basePath || "";
        const dir = path.join(base, "tests", "fixtures");
        const server = http.createServer(async (req: any, res: any) => {
          const name = decodeURIComponent(String(req.url || "/").split("?")[0])
            .replace(/^\/+/, "").replace(/\.\./g, "");
          try {
            const body = await fs.readFile(path.join(dir, name));
            // By extension: a fixture's picture has to load as a picture
            // (D-36's check reads whether the panels' images loaded).
            const ext = String(path.extname(name)).toLowerCase();
            const type = ({ ".svg": "image/svg+xml", ".png": "image/png", ".json": "application/json" } as any)[ext]
              || "text/html; charset=utf-8";
            res.writeHead(200, { "content-type": type });
            res.end(body);
          } catch {
            res.writeHead(404).end("no such fixture");
          }
        });
        await new Promise((r) => server.listen(0, "127.0.0.1", r));
        const port = server.address().port;
        return {
          origin: "http://127.0.0.1:" + port,
          close: () => new Promise((r) => server.close(r)),
        };
      },
    };
  }

  /** Every check: id and what it asks. */
  list(): { id: string; asks: string }[] {
    return makeChecks(this.env()).CHECKS.map((c: any) => ({ id: c.id, asks: c.asks }));
  }

  private async sidecarAlive(): Promise<boolean> {
    // Three tries, 15 s each: a long store write on the 32 GB store stalls
    // the sidecar's whole process for seconds (Kuzu holds the interpreter),
    // and one 10 s probe called a busy sidecar dead twice (2026-10-07).
    for (let i = 0; i < 3; i++) {
      try {
        const res = await fetch(this.sidecarUrl().replace(/\/+$/, "") + "/health",
                                { signal: AbortSignal.timeout(15000) });
        if (res.ok) return true;
      } catch { /* try again */ }
    }
    return false;
  }

  /** Start a run and return at once; `state` says how it is going. */
  start(ids?: string[], label = ""): VerifyState {
    if (!this.state.running) void this.run(ids, label);
    return this.state;
  }

  async run(ids?: string[], label = ""): Promise<VerifyState> {
    if (this.state.running) return this.state;
    const { CHECKS, wakeProjector } = makeChecks(this.env());
    const chosen = ids && ids.length
      ? CHECKS.filter((c: any) => ids.includes(c.id)) : CHECKS;
    this.state = {
      run: this.state.run + 1, running: true, total: chosen.length, done: 0,
      current: "", startedAt: Date.now(), finishedAt: 0, results: [],
      stoppedBecause: "", label,
    };
    (window as any)[KEEP] = this.state;
    try {
      await this.runChecks(chosen, wakeProjector);
    } finally {
      this.state.running = false;
      this.state.current = "";
      this.state.finishedAt = Date.now();
    }
    return this.state;
  }

  /** The checks themselves, into `this.state`, which the caller set up. */
  /** Quiet the run waits for after the reader acts, and the most it waits. */
  resumeIdleMs = 30000;
  resumeMaxMs = 30 * 60000;
  /** Planted (item 98): the reader's input ENDS the run, as before. */
  plantStopOnReader = false;

  /** Wait for the reader to stop; false if they never do (or a stop is asked). */
  private async waitForQuiet(): Promise<boolean> {
    const t0 = performance.now();
    this.state.paused = "the reader is using the app";
    this.state.pauses = (this.state.pauses || 0) + 1;
    try {
      while (!this.stopWhy && performance.now() - t0 < this.resumeMaxMs) {
        const idle = Date.now() - ((window as any).__vertiscopeReaderAt || 0);
        if (idle >= this.resumeIdleMs) return true;
        await new Promise((r) => setTimeout(r, 1000));
      }
      return false;
    } finally {
      this.state.paused = "";
    }
  }

  /** Asked to stop: the run ends before its next check. */
  private stopWhy = "";
  stop(why = "asked to stop"): void { this.stopWhy = why; }

  private async runChecks(chosen: any[], wakeProjector: () => Promise<any>): Promise<void> {
    this.state.total = chosen.length;
    this.stopWhy = "";
    // The READER's last input when the run began: a run never goes on over
    // the reader (2026-10-10: a run drove the browser cell while the reader
    // navigated to archive.org). Its own synthetic hovers do not stamp this.
    //
    // It PAUSES and RESUMES (2026-10-11, PLUGIN_GOAL 98: "tests should
    // auto-resume after I interact with the GUI/plugin"): the reader's input
    // stops the run where it is, it waits for `resumeIdleMs` of quiet, and it
    // carries on -- re-running the check the reader's input landed in, whose
    // verdict was measured over the reader and cannot be trusted. It gives up
    // only after `resumeMaxMs` of waiting. Planted: the old stop.
    const stamp = () => (window as any).__vertiscopeReaderAt || 0;
    let reader0 = stamp();
    await wakeProjector().catch(() => null);
    {
      const queue = [...chosen];
      const retried = new Map<string, number>();
      while (queue.length) {
        const check = queue[0];
        if (!this.stopWhy && stamp() !== reader0) {
          if (this.plantStopOnReader || !(await this.waitForQuiet())) {
            this.state.stoppedBecause = this.stopWhy || "the reader used the app";
            break;
          }
          reader0 = stamp();
          await wakeProjector().catch(() => null);
        }
        if (this.stopWhy) {
          this.state.stoppedBecause = this.stopWhy;
          break;
        }
        queue.shift();
        this.state.current = check.id;
        // Each check starts from the same UI, whatever the last one left.
        const reset = await this.isolate();
        const t0 = performance.now();
        let got: any;
        try {
          got = await check.run();
        } catch (err: any) {
          got = { pass: false, evidence: { threw: String(err?.message || err).slice(0, 300) } };
        }
        // The reader acted DURING this check: its verdict is the reader's as
        // much as the app's. Run it again once they are done (twice at most).
        if (stamp() !== reader0 && !this.plantStopOnReader && (retried.get(check.id) || 0) < 2) {
          retried.set(check.id, (retried.get(check.id) || 0) + 1);
          this.state.resumed = (this.state.resumed || 0) + 1;
          queue.unshift(check);
          continue;
        }
        const result: CheckResult = {
          id: check.id, asks: check.asks, pass: !!got?.pass,
          evidence: got?.evidence ?? null, ms: Math.round(performance.now() - t0),
        };
        // A check that parks the browser cell (live capture off, to purge its
        // fixture) must not leave it parked: S-12 did, and the NEXT fresh run
        // seeded twelve pages that were never captured -- 0 pages stored after
        // 20 minutes. Put back, and said.
        if (this.restoreLive()) {
          result.evidence = { ...(result.evidence || {}), left_live_capture_off: true };
        }
        if (reset.pins || reset.billboards || reset.menus) {
          result.evidence = { ...(result.evidence || {}), reset_before: reset };
        }
        // Same rule as the terminal runner: a dead sidecar fails every check
        // after it for THAT reason, so the run stops and says so.
        if (!result.pass && !(await this.sidecarAlive())) {
          result.evidence = { ...(result.evidence || {}), sidecar: "died mid-check" };
          this.state.results.push(result);
          this.state.done++;
          this.state.stoppedBecause = `the sidecar died during ${check.id}`;
          break;
        }
        this.state.results.push(result);
        this.state.done++;
      }
    }
  }

  // -- the fresh store (`G-87`), run from inside the app -------------------

  /** Start a fresh-store run and return at once. */
  startFresh(ids?: string[]): VerifyState {
    if (!this.state.running) void this.runFresh(ids);
    return this.state;
  }

  /**
   * Every check against a FRESH, EMPTY store that this app fills itself.
   *
   * 2026-09-26: *"tear down the current db so that all new tests run in a
   * fresh and empty db"*, then *"All tests run inside of the GUI"*. The first
   * version orchestrated from a terminal -- a Python process started the
   * sidecar, flipped this plugin's setting over CDP and drove the browser
   * from outside -- so only the check bodies ran here. Now the whole run is
   * the app's: it starts a sidecar on an empty workspace (a child process, on
   * its own port, so the working one keeps serving), points itself at it IN
   * MEMORY ONLY (a reload or a crash falls back to the saved setting, the
   * working store), fills it by browsing `SEED_*` in the browser cell, runs
   * the checks, and puts itself back. Each step shows in the corner box as
   * it happens; the working store is never opened.
   */
  async runFresh(ids?: string[]): Promise<VerifyState> {
    if (this.state.running) return this.state;
    const plugin: any = (this.app as any).plugins.getPlugin("vertiscope-bridge");
    const working = String(plugin?.settings?.sidecar || "");
    const total = ids && ids.length ? ids.length : this.list().length;
    this.state = {
      run: this.state.run + 1, running: true, total, done: 0,
      current: "starting a sidecar on an empty store", startedAt: Date.now(),
      finishedAt: 0, results: [], stoppedBecause: "", label: "fresh store",
      seed: [], teardown: null, phases: [],
    };
    (window as any)[KEEP] = this.state;
    const req = (window as any).require;
    const path = req("path");
    const fsp = req("fs/promises");
    const base = (this.app.vault.adapter as any).basePath || "";
    const testUrl = `http://127.0.0.1:${TEST_PORT}`;
    let child: any = null;
    let readerPage = "";
    let fixtures: any = null;
    try {
      // 1. An empty workspace; the previous test store goes.
      const runs = path.join(base, "build", "test_runs");
      await fsp.mkdir(runs, { recursive: true });
      for (const old of await fsp.readdir(runs)) {
        if (old.startsWith("run_")) {
          await fsp.rm(path.join(runs, old), { recursive: true, force: true });
        }
      }
      const stamp = new Date().toISOString().replace(/[-:T]/g, "").slice(0, 14);
      const name = `run_${stamp}`;
      const ws = path.join(runs, name);
      await fsp.mkdir(ws);
      // 2. Its sidecar -- on a FREE port. A run interrupted (a reload
      // mid-run) leaves its test sidecar holding the port, and the next run
      // would find it "healthy" and use a store that is not fresh.
      await this.freeTestPort();
      child = this.spawnSidecar(ws, base, plugin?.settings?.python || "python");
      if (!(await this.waitHealthy(testUrl, 240000, child))) {
        throw new Error(`the test sidecar did not answer /health (see ${name}/sidecar.log)`);
      }
      // 3. This app, on it -- in memory only. Both panes open and LOADED
      // first: a pane in a background tab is a deferred stub with no view,
      // and the phase trace read "none" for a whole run because of it -- a
      // planted G-89 then "failed" for a reason that had nothing to do with
      // the force tree.
      await this.ensurePanes();
      // The page the reader had open, to go back to afterwards.
      readerPage = this.browserUrl();
      plugin.settings.sidecar = testUrl;
      this.resetGraphs("switched to a fresh store");
      await this.redrawGraphs();
      // 4. Fill it by browsing, sampling the graph's phase as it goes --
      // with live capture ON, whatever the last run left it as.
      this.restoreLive();
      fixtures = await this.env().serveFixtures();
      const urls = [...SEED_FIXTURES.map((f) => `${fixtures.origin}/${f}`), ...SEED_PAGES];
      let seeding = 0;
      let sampling = true;
      const sampler = (async () => {
        let fitted: boolean | null = null;
        let lastFitAsk = 0;
        while (sampling) {
          if (Date.now() - lastFitAsk > 1000) {
            lastFitAsk = Date.now();
            const p = await this.ask(testUrl, "/projector", 3000);
            fitted = p ? !!p.fitted : null;
          }
          this.samplePhase(seeding, fitted);
          await sleep(250);
        }
      })();
      for (let i = 0; i < urls.length; i++) {
        seeding = i + 1;
        const short = urls[i].replace(/^https?:\/\//, "").slice(0, 40);
        this.state.current = `seeding ${i + 1}/${urls.length} · ${short}`;
        const got: any = await this.seedOne(urls[i], testUrl);
        this.state.seed!.push(got);
        if (got.left) {
          this.state.stoppedBecause = `the browser left ${urls[i]} for ${got.left} while it was being seeded `
            + `-- a reader navigating the shared cell; the run stops rather than fight them`;
          break;
        }
      }
      if (this.state.stoppedBecause) throw new Error(this.state.stoppedBecause);
      this.state.current = "waiting for the projector to fit the seeded store";
      await this.waitFitted(testUrl, 300000);
      // The pane reaches the fit on its own (its load retries); give it the
      // time a reader would, then stop sampling.
      // ... and until the diff drawn force-directed has collapsed into the
      // page view: the transform placing the pending chunks is the phase the
      // trace must end on (`G-89` C7).
      for (let i = 0; i < 300; i++) {
        const v: any = this.app.workspace.getLeavesOfType("vertiscope-graph-view")[0]?.view;
        if (!v) break;
        const drawn = v.pendingState ? v.pendingState().drawn : 0;
        if (v.layoutMode === "projector" && drawn === 0) break;
        await sleep(500);
      }
      await sleep(1500);
      sampling = false;
      await sampler;
      const held = this.state.seed!.filter((r) => r.held).length;
      // The window's frame rate goes on every verdict of the run: a covered
      // window is throttled to one frame a second, which slows timers and the
      // layout's simulation too, and a run measured then scores the throttle
      // (2026-09-27: D-35 and G-94 failed on it). Launch flags that prevent
      // it: docs/OBSIDIAN_BRIDGE.md.
      const frames: number[] = [];
      for (let i = 0; i < 5; i++) {
        const f0 = performance.now();
        await Promise.race([new Promise((r) => requestAnimationFrame(() => r(null))), sleep(2000)]);
        frames.push(performance.now() - f0);
      }
      frames.sort((a, b) => a - b);
      const frameMs = Math.round(frames[2]);
      this.state.label = `fresh ${name}, ${held}/${urls.length} pages seeded, `
        + (frameMs < 50 ? `frames ${frameMs} ms` : `WINDOW THROTTLED (${frameMs} ms frames)`);
      // 5. The checks -- built NOW, after the switch. `makeChecks` reads the
      // sidecar's address once, when it is called; built before step 3, every
      // check asked the WORKING store while the app captured into the test
      // one (S-12 read 137 pages on a 12-page store, 2026-09-26).
      const { CHECKS, wakeProjector } = makeChecks(this.env());
      const chosen = ids && ids.length
        ? CHECKS.filter((c: any) => ids.includes(c.id)) : CHECKS;
      await this.runChecks(chosen, wakeProjector);
    } catch (err: any) {
      this.state.stoppedBecause = String(err?.message || err).slice(0, 200);
    } finally {
      // 6. Back on the working store, whatever happened.
      if (plugin?.settings) plugin.settings.sidecar = working;
      this.resetGraphs("back on the working store");
      // And the browser cell back on the reader's page, freshly loaded: a page
      // left open across the switch kept a sensor whose dictionary the
      // WORKING sidecar never received, and scanning there was lost until a
      // reload (2026-09-27: "Total scan feature loss" on the planted arm's
      // DuckDuckGo page, which was also left on screen).
      // ... unless the READER took the cell somewhere during the run: then it
      // stays on their page, reloaded for a fresh sensor, not dragged back.
      let back = readerPage;
      if (/a reader navigating/.test(this.state.stoppedBecause)) {
        try { back = (this.app.workspace.getLeavesOfType("vertiscope-browser-view")[0]?.view as any)?.webview?.getURL() || readerPage; }
        catch { /* the cell is gone */ }
      }
      this.backToReader(back);
      try { await fixtures?.close(); } catch { /* already closed */ }
      await this.stopSidecar(child);
      let stopped = false;
      try { await fetch(testUrl + "/health", { signal: AbortSignal.timeout(2000) }); }
      catch { stopped = true; }
      this.state.teardown = { sidecar: working, test_sidecar_stopped: stopped };
      await this.redrawGraphs();
      this.state.running = false;
      this.state.current = "";
      this.state.finishedAt = Date.now();
    }
    return this.state;
  }

  /** Stop whatever still listens on the test port (Windows: netstat + taskkill). */
  private async freeTestPort(): Promise<void> {
    const alive = await this.ask(`http://127.0.0.1:${TEST_PORT}`, "/health", 2000);
    if (!alive) return;
    const proc = (window as any).process;
    const cp = (window as any).require("child_process");
    if (proc.platform !== "win32") return;
    const out: string = await new Promise((r) => cp.execFile("netstat", ["-ano", "-p", "TCP"],
      { windowsHide: true }, (_e: any, so: string) => r(String(so || ""))));
    const pids = new Set<string>();
    for (const line of out.split(/\r?\n/)) {
      const f = line.trim().split(/\s+/);
      if (f.length >= 5 && f[1].endsWith(`:${TEST_PORT}`) && f[3] === "LISTENING") pids.add(f[4]);
    }
    for (const pid of pids) {
      await new Promise((r) => cp.execFile("taskkill", ["/PID", pid, "/T", "/F"],
        { windowsHide: true }, () => r(null)));
    }
    for (let i = 0; i < 20; i++) {
      if (!(await this.ask(`http://127.0.0.1:${TEST_PORT}`, "/health", 1000))) return;
      await sleep(500);
    }
  }

  /**
   * The shared UI back to a known state before a check (checks were
   * contaminating each other). Under a fresh run's load the browser's input
   * events arrive LATE -- G-39's right-clicks landed seconds after it ended,
   * pinning chunks of whatever page the next check had open -- so pins,
   * open menus and billboards from before are let go, live capture is on,
   * and the guest is given a moment with no load or drain in flight.
   */
  private async isolate(): Promise<{ pins: number; billboards: number; menus: number }> {
    const out = { pins: 0, billboards: 0, menus: 0 };
    await sleep(400);                            // let late input land first
    for (const m of Array.from(document.querySelectorAll(".menu"))) { m.remove(); out.menus++; }
    for (const l of this.app.workspace.getLeavesOfType("vertiscope-browser-view")) {
      const b: any = l.view;
      if (!b || typeof b.pinnedState !== "function") continue;
      for (const p of b.pinnedState()) { b.unpin(p.cid); out.pins++; }
      for (let i = 0; i < 25; i++) {
        let loading = false;
        try { loading = !!b.webview?.isLoading(); } catch { /* not ready */ }
        if (!loading && !b.draining && !b.capturing) break;
        await sleep(200);
      }
    }
    for (const l of this.app.workspace.getLeavesOfType("vertiscope-graph-view")) {
      const g: any = l.view;
      if (!g || !g.billboards) continue;
      for (const id of Array.from(g.billboards.keys())) { g.closeBillboard(id); out.billboards++; }
    }
    this.restoreLive();
    return out;
  }

  /** The url the browser cell shows, if any. */
  private browserUrl(): string {
    try {
      const b: any = this.app.workspace.getLeavesOfType("vertiscope-browser-view")[0]?.view;
      const u = b?.webview?.getURL?.() || "";
      return /^https?:/.test(u) && !/127\.0\.0\.1|localhost/.test(u) ? u : "";
    } catch { return ""; }
  }

  /** The browser cell restarts capture on the reader's page (or a blank one). */
  private backToReader(url: string): void {
    for (const l of this.app.workspace.getLeavesOfType("vertiscope-browser-view")) {
      const b: any = l.view;
      try {
        if (typeof b?.restartCapture === "function") b.restartCapture();
        if (b?.go) b.go(url || "about:blank");
      } catch { /* the cell is gone */ }
    }
  }

  /** Live capture back on in every browser cell; true if any was off. */
  restoreLive(): boolean {
    let was = false;
    for (const l of this.app.workspace.getLeavesOfType("vertiscope-browser-view")) {
      const v: any = l.view;
      if (v && v.live === false && typeof v.setLive === "function") {
        v.setLive(true);
        was = true;
      }
    }
    return was;
  }

  /** `supervise serve` on `ws`, logging beside the store. */
  spawnSidecar(ws: string, base: string, python: string, port = TEST_PORT): any {
    const req = (window as any).require;
    const cp = req("child_process");
    const fs = req("fs");
    const path = req("path");
    const log = fs.createWriteStream(path.join(ws, "sidecar.log"));
    const child = cp.spawn(python, [
      "-m", "vertiscope.obsidian", "supervise", "--workspace", ws,
      "--port", String(port), "--semantic", "--capture",
      // Test sidecars only (the Verifier's, and the empty test workspace's):
      // a panel gesture is adjudicated by `/enact mode=plan`, which the flag
      // gates (G-111). The reader's own sidecar is started elsewhere and keeps
      // whatever flags the reader chose.
      "--enact",
    ], { cwd: base, windowsHide: true,
         // A latent window of seconds, so G-129's refit can be watched in a run.
         env: { ...(window as any).process.env, PYTHONIOENCODING: "utf-8", VERTISCOPE_LATENT_S: "20" } });
    child.stdout?.pipe(log);
    child.stderr?.pipe(log);
    return child;
  }

  /** `supervise` runs `serve` as a CHILD: stop the whole tree, or the child
   *  keeps the store and the port and the next run is not fresh. */
  async stopSidecar(child: any): Promise<void> {
    if (!child || child.exitCode !== null) return;
    const proc = (window as any).process;
    if (proc.platform === "win32") {
      const cp = (window as any).require("child_process");
      await new Promise((r) => cp.execFile(
        "taskkill", ["/PID", String(child.pid), "/T", "/F"],
        { windowsHide: true }, () => r(null)));
    } else {
      child.kill();
    }
    for (let i = 0; i < 40 && child.exitCode === null; i++) await sleep(250);
  }

  async ask(base: string, route: string, ms = 10000): Promise<any> {
    try {
      const res = await fetch(base + route, { signal: AbortSignal.timeout(ms) });
      return res.ok ? await res.json() : null;
    } catch {
      return null;
    }
  }

  async waitHealthy(url: string, ms: number, child: any): Promise<boolean> {
    const until = Date.now() + ms;
    while (Date.now() < until) {
      if (child && child.exitCode !== null) return false;
      const got = await this.ask(url, "/health", 5000);
      if (got && got.ok) return true;
      await sleep(2000);
    }
    return false;
  }

  /**
   * Browse one page and wait until the store HOLDS it and every chunk has a
   * vector -- the two things every check then reads. Landing is what
   * captures (the cell's `did-stop-loading`), so this presses nothing.
   */
  private async seedOne(url: string, sidecar: string) {
    const t0 = Date.now();
    if (!this.app.workspace.getLeavesOfType("vertiscope-browser-view").length) {
      await (this.app as any).commands.executeCommandById("vertiscope-bridge:vertiscope-open-browser");
      await sleep(1500);
    }
    const b: any = this.app.workspace.getLeavesOfType("vertiscope-browser-view")[0]?.view;
    if (!b || !b.go) return { url, held: false, chunks: null, s: 0 };
    b.go(url);
    let held = false;
    let chunks: number | null = null;
    const same = (u: string) => u.replace(/\/+$/, "") === url.replace(/\/+$/, "");
    // Where the cell actually IS (2026-09-28: a run sat 34 min on "seeding
    // 8/13 · Radix_tree" while the cell showed discourse's /top, the test
    // store busy storing a page nobody seeded). The cell is shared with the
    // reader: not there yet, it is sent once more; there and then gone to
    // another page, someone navigated it, and the run stops rather than
    // fight them -- or seed from a page that is not the seed.
    const doc = (u: string) => String(u || "").split("#")[0].replace(/\/+$/, "");
    let landed = false, resent = false;
    for (let i = 0; i < 60; i++) {
      await sleep(2000);
      let here = "";
      try { here = b.webview?.getURL() || ""; } catch { /* not attached */ }
      if (doc(here) === doc(url)) landed = true;
      else if (landed && /^https?:/.test(here)) {
        return { url, held: false, chunks, s: Math.round((Date.now() - t0) / 1000), left: here };
      } else if (!landed && !resent && i >= 5) { resent = true; b.go(url); }
      const pages = await this.ask(sidecar, "/pages");
      held = !!pages && (pages.urls || []).some(same);
      const health = await this.ask(sidecar, "/health");
      chunks = health ? health.chunks_total ?? null : null;
      if (held && health && !health.chunks_without_vector) break;
    }
    return { url, held, chunks, s: Math.round((Date.now() - t0) / 1000) };
  }

  private async waitFitted(sidecar: string, ms: number): Promise<void> {
    const until = Date.now() + ms;
    while (Date.now() < until) {
      const p = await this.ask(sidecar, "/projector?drawable=1", 30000);
      if (p && p.fitted && !p.fitting && !p.queue && !p.drawable_unprojected) return;
      await sleep(3000);
    }
  }

  /** The graph and the browser cell open, each with a real view behind it. */
  async ensurePanes(): Promise<void> {
    const cmds = (this.app as any).commands;
    for (const [type, cmd] of [["vertiscope-graph-view", "vertiscope-open-graph"],
                               ["vertiscope-browser-view", "vertiscope-open-browser"]]) {
      if (!this.app.workspace.getLeavesOfType(type).length) {
        cmds.executeCommandById(`vertiscope-bridge:${cmd}`);
        await sleep(1500);
      }
      for (const l of this.app.workspace.getLeavesOfType(type)) {
        if ((l as any).loadIfDeferred) await (l as any).loadIfDeferred();
      }
    }
    await sleep(500);
  }

  /** Every graph pane, emptied: the store it drew is not the one now in use. */
  resetGraphs(why: string): void {
    for (const l of this.app.workspace.getLeavesOfType("vertiscope-graph-view")) {
      const v: any = l.view;
      if (v && typeof v.resetForStore === "function") v.resetForStore(why);
    }
  }

  /** One row of the phase trace, only when something in it changed. */
  private samplePhase(seeding: number, fitted: boolean | null): void {
    const leaf: any = this.app.workspace.getLeavesOfType("vertiscope-graph-view")[0];
    if (leaf?.isDeferred && leaf.loadIfDeferred) void leaf.loadIfDeferred();
    const v: any = leaf?.view;
    const data: any = v?.graph ? v.graph.graphData() : { nodes: [], links: [] };
    const force = data.nodes.filter((n: any) => n.force);
    const parents = new Map<string, number>();
    for (const l of data.links) {
      if (!l.force) continue;
      const t = typeof l.target === "object" ? l.target.id : l.target;
      parents.set(t, (parents.get(t) || 0) + 1);
    }
    const row = {
      t: Date.now(), mode: String(v?.layoutMode ?? "none"), nodes: data.nodes.length,
      force_nodes: force.length,
      force_pages: force.filter((n: any) => n.level === "page").length,
      multi_parent: [...parents.values()].filter((n) => n > 1).length,
      drains: v?.forceStats?.drains ?? 0, fitted, seeding,
    };
    const trace = this.state.phases!;
    const last = trace[trace.length - 1];
    if (!last || last.mode !== row.mode || last.seeding !== row.seeding
        || last.fitted !== row.fitted || last.force_pages !== row.force_pages) {
      trace.push(row);
    } else {
      // Same phase: keep the latest counts on the row, not a new row.
      Object.assign(last, { nodes: row.nodes, force_nodes: row.force_nodes,
                            multi_parent: Math.max(last.multi_parent, row.multi_parent),
                            drains: row.drains });
    }
  }

  /** Every open graph pane, redrawn from the sidecar the plugin points at. */
  async redrawGraphs(): Promise<void> {
    for (const l of this.app.workspace.getLeavesOfType("vertiscope-graph-view")) {
      const v: any = l.view;
      if (v && typeof v.reload === "function") {
        try { await v.reload(); } catch { /* the pane says why itself */ }
      }
    }
  }
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

