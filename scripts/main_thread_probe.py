"""Obsidian's MAIN THREAD while the reader browses: long tasks (>50 ms) and
frame gaps for N seconds, with the plugin's own work attributed by wrapping
its hot methods (read-only timing; restored afterwards)."""
import json, sys, time
sys.path.insert(0, r"<home>\Documents\vertiscope")
from vertiscope.obsidian.live import Live
secs = float(sys.argv[1]) if len(sys.argv) > 1 else 40
L = Live()
L.evaluate(r"""(() => {
  const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
  const b = app.workspace.getLeavesOfType("vertiscope-browser-view")[0].view;
  const P = window.__mtp = { long: [], frames: [], spent: {}, orig: [] };
  try { P.obs = new PerformanceObserver((l) => { for (const e of l.getEntries()) P.long.push([Math.round(e.startTime), Math.round(e.duration)]); });
        P.obs.observe({ entryTypes: ["longtask"] }); } catch (e) { P.noLong = String(e); }
  let last = performance.now();
  const tick = () => { const t = performance.now(); P.frames.push(t - last); last = t; if (P.on) requestAnimationFrame(tick); };
  P.on = true; requestAnimationFrame(tick);
  const wrap = (o, name, tag) => { const f = o[name]; if (typeof f !== "function") return; P.orig.push([o, name, f]);
    o[name] = function (...a) { const t = performance.now(); const r = f.apply(this, a);
      const done = () => { P.spent[tag] = (P.spent[tag] || 0) + (performance.now() - t); };
      if (r && typeof r.then === "function") { r.then(done, done); } else done(); return r; }; };
  for (const m of ["fitChunkSizes", "applyProjected", "absorb", "applyDiff", "redrawForce", "batchSync", "expireHoverPanels"]) wrap(v, m, "graph." + m);
  for (const m of ["saveFormsSlice", "tick", "snapshotChunk"]) wrap(b, m, "browser." + m);
  return 1; })()""")
time.sleep(secs)
print(L.evaluate(r"""(() => {
  const P = window.__mtp; P.on = false; try { P.obs.disconnect(); } catch (e) {}
  for (const [o, n, f] of P.orig) o[n] = f;
  const fr = P.frames.slice().sort((a, b) => a - b), q = (p) => fr.length ? Math.round(fr[Math.min(fr.length - 1, Math.floor(p * fr.length))]) : null;
  const longMs = P.long.reduce((a, x) => a + x[1], 0);
  const spent = Object.fromEntries(Object.entries(P.spent).map(([k, v]) => [k, Math.round(v)]).sort((a, b) => b[1] - a[1]));
  return JSON.stringify({ frames: fr.length, gap_p50: q(.5), gap_p95: q(.95), gap_max: q(1), over_100ms: fr.filter((x) => x > 100).length,
                          long_tasks: P.long.length, long_ms: longMs, worst: P.long.sort((a, b) => b[1] - a[1]).slice(0, 6), spent, noLong: P.noLong || null,
                          idle: window.__vertiscope.reader.idleMs() });
})()"""))
