/**
 * Live confirmation, keyed by requirement id.
 *
 *   node confirm.mjs                 # every registered check
 *   node confirm.mjs G-6 G-53        # just these
 *
 * **Why this exists rather than more one-off probes.** `design_state.py`
 * computes each row's status from the PRD, which catches a status that drifts
 * from what the document says. It cannot catch a status that drifts from what
 * the APPLICATION does -- and that is the drift that matters. `G-6` sat in
 * `Confirm` citing "31 nodes and 30 edges"; live it was 26 and **0**, and the
 * row had been wrong for as long as the debug port had been shut.
 *
 * So a row is confirmed by a check that RUNS, against the loaded plugin and
 * the running sidecar, and can be run again. A row with no check here is
 * visible as `no live check` rather than quietly assumed -- which is the same
 * denominator discipline `CLAUDE.md` asks for everywhere else.
 *
 * Two rules every check follows:
 *
 *  - **The plugin is reloaded before anything is measured**, and nothing
 *    else is assumed about order. Checks run against whatever state the pane
 *    is in, and any that needs a particular state establishes it itself.
 *    The reload is not optional politeness: a probe scores the instrument
 *    that is LOADED, and the collider probe once passed with its own target
 *    defect planted because a build had replaced a file nobody was running.
 *  - **It reports EVIDENCE, not a boolean.** `pass` is derived from numbers
 *    that are written out, so a reader can disagree with the verdict without
 *    re-running anything.
 */

import { writeFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { evaluate } from "./cdp.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, "..");
const SIDECAR = process.env.VERTISCOPE_SIDECAR || "http://127.0.0.1:8788";

const serveFixtures = async () => {
  const http = await import("node:http");
  const { readFile } = await import("node:fs/promises");
  const dir = join(ROOT, "tests", "fixtures");
  const server = http.createServer(async (req, res) => {
    const name = decodeURIComponent((req.url || "/").split("?")[0])
      .replace(/^\/+/, "").replace(/\.\./g, "");
    try {
      const body = await readFile(join(dir, name));
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
};

import { makeChecks } from "./checks/live.mjs";
const { CHECKS, wakeProjector } = makeChecks({
  evaluate, SIDECAR, serveFixtures,
  askTimeoutMs: process.env.VERTISCOPE_ASK_TIMEOUT_MS,
});


// --------------------------------------------------------------------------

const wanted = process.argv.slice(2);
const chosen = wanted.length
  ? CHECKS.filter((c) => wanted.includes(c.id))
  : CHECKS;

/**
 * Reload the plugin before anything is measured.
 *
 * **A probe scores the instrument that is LOADED, not the one on disk.** The
 * collider probe passed with its own target defect planted and returned
 * numbers identical to the clean run down to a random shuffle landing on
 * 0.004 twice -- because it reopened the pane but never reloaded the plugin,
 * so `npm run build` had replaced a file nobody was running. The tell was the
 * impossible coincidence, not the green.
 *
 * This file's header used to say it reloads nothing. That was a claim about
 * not disturbing pane STATE, which each check establishes for itself anyway,
 * and it read as licence to score a build that was never loaded.
 *
 * Skippable with VERTISCOPE_NO_RELOAD=1, for confirming what is running right
 * now rather than what was just built.
 */
const reloadPlugin = async () => {
  if (process.env.VERTISCOPE_NO_RELOAD === "1") return { reloaded: false };
  const got = await evaluate(`(async () => {
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    const id = "vertiscope-bridge";
    await app.plugins.disablePlugin(id);
    await sleep(800);
    await app.plugins.enablePlugin(id);
    await sleep(2500);
    return { enabled: !!app.plugins.getPlugin(id) };
  })()`, { timeout: 120000 });
  return { reloaded: true, ...got };
};

const reload = await reloadPlugin().catch(
  (e) => ({ reloaded: false, error: String(e).slice(0, 120) }));
console.log(reload.reloaded
  ? `reloaded the plugin (enabled=${reload.enabled})`
  : `NOT reloaded: ${reload.error || "VERTISCOPE_NO_RELOAD=1"}`);

const woke = await wakeProjector().catch(
  (e) => ({ ok: false, error: String(e).slice(0, 120) }));
console.log(woke.ok
  ? "projector is loaded and fronted"
  : `projector NOT ready: ${JSON.stringify(woke)}`);

/**
 * Is the sidecar still there?
 *
 * **Because when it is not, every check fails for one reason and the run
 * looks like a catastrophe.** The sidecar has segfaulted twice under a full
 * suite -- a native crash inside the fitting, no Python traceback -- and
 * the run that followed reported 28 failures with "fetch failed" and
 * "the graph pane never finished its fit", which reads as a broken
 * projector and was a dead process. Naming it costs one request.
 */
const sidecarAlive = async () => {
  try {
    const res = await fetch(`${SIDECAR}/health`,
                            { signal: AbortSignal.timeout(10000) });
    return res.ok;
  } catch {
    return false;
  }
};

if (!(await sidecarAlive())) {
  console.log(`the sidecar at ${SIDECAR} is not answering -- start it with`);
  console.log("  python -m vertiscope.obsidian serve --workspace build/corpus123"
              + " --port 8788 --semantic --capture");
  process.exit(2);
}

const results = [];

// **Run INSIDE the plugin (`G-75`), hardware in the loop.** The plugin has
// just been reloaded from out here, so it is the freshly built code; the
// checks then run in its own window and this script only starts the run and
// reads it back -- the same thing an MCP tool does, and what the corner box
// in the browser cell shows while it happens. There is no other way to run
// them: the terminal path that sent each check body over CDP was removed
// 2026-09-26 ("All tests run on the plugin itself").
const report = (r) => {
  console.log(`${r.pass ? "PASS" : "FAIL"}  ${r.id}  ${r.asks}`);
  if (!r.pass) console.log("      " + JSON.stringify(r.evidence));
};

const ids = chosen.map((c) => c.id);
const started = await evaluate(`(() => {
  const v = window.__vertiscope && window.__vertiscope.verify;
  if (!v) return { error: "this plugin build has no in-app verifier" };
  v.start(${JSON.stringify(ids)});
  return { run: v.state().run, total: v.state().total };
})()`);
if (!started || started.error) {
  console.log(`could not start the run in the app: ${JSON.stringify(started)}`);
  process.exit(2);
}
console.log(`running ${started.total} checks inside the plugin (run ${started.run})`);
let seen = 0;
let pausedSaid = false;
for (;;) {
  await new Promise((r) => setTimeout(r, 2000));
  const st = await evaluate("window.__vertiscope.verify.state()");
  for (const r of st.results.slice(seen)) { report(r); results.push(r); }
  // Paused for the reader, and resumed (PLUGIN_GOAL 98): said once each way.
  if (st.paused && !pausedSaid) { console.log(`paused: ${st.paused} -- resumes after quiet`); pausedSaid = true; }
  if (!st.paused && pausedSaid) { console.log("resumed"); pausedSaid = false; }
  seen = st.results.length;
  if (!st.running) {
    if (st.stoppedBecause) {
      console.log(`
stopped: ${st.stoppedBecause}. Everything after it would`);
      console.log("fail for that reason, and a run that reports 28 broken features");
      console.log("when one process went away is worse than no run at all.");
    }
    break;
  }
}

const passed = results.filter((r) => r.pass).length;

// One writer for the record of what has been seen working, and it MERGES by
// requirement id (`vertiscope/obsidian/confirmations.py`). This file used to
// write it here and REPLACE it, so a three-check run erased every verdict
// before it.
mkdirSync(join(ROOT, "build_analytics"), { recursive: true });
const raw = join(ROOT, "build_analytics", "confirm_last_run.json");
writeFileSync(raw, JSON.stringify({ results }, null, 2), "utf8");
const { spawnSync } = await import("node:child_process");
const rec = spawnSync(process.env.PYTHON || "python",
  ["-m", "vertiscope.obsidian.confirmations", raw, "--store",
   process.env.VERTISCOPE_STORE || "working", "--runner", "confirm.mjs"],
  { cwd: ROOT, encoding: "utf8" });
console.log((rec.stdout || rec.stderr || "").trim());

console.log(`
${passed} of ${results.length} pass ` +
            `-> build_analytics/live_confirmations.md`);
process.exitCode = passed === results.length ? 0 : 1;
