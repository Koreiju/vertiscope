/**
 * Collect an in-app verify run that is ALREADY running (`confirm.mjs`
 * starts one and polls it; if that poller is stopped, the run goes on inside
 * the plugin and its verdicts would be lost). Waits for the run to end and
 * records every result through the one writer, `confirmations.py`.
 *
 *   node confirm_collect.mjs
 */
import { writeFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import { evaluate } from "./cdp.mjs";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
let st;
for (;;) {
  st = await evaluate("window.__vertiscope.verify.state()");
  if (!st || !st.running) break;
  await new Promise((r) => setTimeout(r, 5000));
}
const results = (st && st.results) || [];
for (const r of results) console.log(`${r.pass ? "PASS" : "FAIL"}  ${r.id}`);
if (st && st.stoppedBecause) console.log(`stopped: ${st.stoppedBecause}`);
mkdirSync(join(ROOT, "build_analytics"), { recursive: true });
const raw = join(ROOT, "build_analytics", "confirm_last_run.json");
writeFileSync(raw, JSON.stringify({ results }, null, 2), "utf8");
const rec = spawnSync(process.env.PYTHON || "python",
  ["-m", "vertiscope.obsidian.confirmations", raw, "--store", process.env.VERTISCOPE_STORE || "working", "--runner", "confirm.mjs"],
  { cwd: ROOT, encoding: "utf8" });
console.log((rec.stdout || rec.stderr || "").trim());
console.log(`${results.filter((r) => r.pass).length} of ${results.length} pass`);
