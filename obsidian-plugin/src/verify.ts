/**
 * The live checks, run INSIDE the plugin (`G-75`) -- hardware in the loop.
 *
 * Every requirement check in `checks/live.mjs` drives the running app and
 * reads back what it did. From a terminal those checks talk to Obsidian over
 * CDP, which means a check can only be run by something outside the app, and
 * what it saw is visible only in that terminal. Here the same module runs in
 * the plugin's own window: `evaluate` is this window's eval, the results
 * stream into the browser cell's corner box as each check finishes, and the
 * MCP tools start a run and read it through `window.__domvec.verify`.
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
}

export class Verifier {
  state: VerifyState = {
    run: 0, running: false, total: 0, done: 0, current: "",
    startedAt: 0, finishedAt: 0, results: [], stoppedBecause: "",
  };

  constructor(private app: App, private sidecarUrl: () => string) {}

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
            res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
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
    try {
      const res = await fetch(this.sidecarUrl().replace(/\/+$/, "") + "/health",
                              { signal: AbortSignal.timeout(10000) });
      return res.ok;
    } catch {
      return false;
    }
  }

  /** Start a run and return at once; `state` says how it is going. */
  start(ids?: string[]): VerifyState {
    if (!this.state.running) void this.run(ids);
    return this.state;
  }

  async run(ids?: string[]): Promise<VerifyState> {
    if (this.state.running) return this.state;
    const { CHECKS, wakeProjector } = makeChecks(this.env());
    const chosen = ids && ids.length
      ? CHECKS.filter((c: any) => ids.includes(c.id)) : CHECKS;
    this.state = {
      run: this.state.run + 1, running: true, total: chosen.length, done: 0,
      current: "", startedAt: Date.now(), finishedAt: 0, results: [],
      stoppedBecause: "",
    };
    try {
      await wakeProjector().catch(() => null);
      for (const check of chosen) {
        this.state.current = check.id;
        const t0 = performance.now();
        let got: any;
        try {
          got = await check.run();
        } catch (err: any) {
          got = { pass: false, evidence: { threw: String(err?.message || err).slice(0, 300) } };
        }
        const result: CheckResult = {
          id: check.id, asks: check.asks, pass: !!got?.pass,
          evidence: got?.evidence ?? null, ms: Math.round(performance.now() - t0),
        };
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
    } finally {
      this.state.running = false;
      this.state.current = "";
      this.state.finishedAt = Date.now();
    }
    return this.state;
  }
}
