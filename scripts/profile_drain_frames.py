"""G-90 diagnosis: after a drain, what holds the renderer's main thread so the
next animation frame -- and so the overlay's paint -- arrives ~660 ms late?

Live, a fresh busy page (bandcamp's homepage) for `secs`: every long task
(PerformanceObserver 'longtask', >= 50 ms) with its start and duration, and
the synchronous time of the suspects, wrapped for the run: the browser's
`absorbDrain`, `ForceTree.apply`, the graph's `applyForceDelta`, `absorb`,
`redrawForce`, `collapseCovered`, the scene batch's `sync`, the pipeline
box's `flashBoxes`. Each suspect's calls that overlap a long task are
attributed to it. Read-only on the app's code (wrappers removed after);
reader-idle gated; the reader's page restored.
"""
import json, sys, time
sys.path.insert(0, r"<home>\Documents\vertiscope")
from vertiscope.obsidian.live import Live
live = Live()
if live.evaluate("window.__vertiscope.reader.idleMs()") < 60000:
    print("aborted: reader active"); sys.exit(1)
stamp = live.evaluate("window.__vertiscopeReaderAt || 0")
was = live.evaluate("app.workspace.getLeavesOfType('vertiscope-browser-view')[0].view.webview.getURL()")
PAGE = next((a for a in sys.argv[1:] if a.startswith("http")), "https://bandcamp.com/")
secs = int(next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--secs=")), "40"))
PLANT = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--plant=")), "")
JS = r"""(async (url, secs, plant) => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const b = app.workspace.getLeavesOfType("vertiscope-browser-view")[0].view;
  const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
  const FT = window.__vertiscopeForceTree;
  if (plant) b.plant.add(plant);
  const asks0 = b.shownAsks || 0;
  const calls = [];
  const wraps = [];
  const wrap = (obj, name, label) => {
    if (!obj || typeof obj[name] !== "function") return;
    const orig = obj[name];
    obj[name] = function (...a) {
      const t0 = performance.now();
      const r = orig.apply(this, a);
      if (r && typeof r.then === "function") {
        // the synchronous part only: until the first await
        calls.push({ label, t0, ms: performance.now() - t0, async: true });
        return r;
      }
      calls.push({ label, t0, ms: performance.now() - t0 });
      return r;
    };
    wraps.push(() => { obj[name] = orig; });
  };
  wrap(b, "absorbDrain", "browser.absorbDrain");
  wrap(FT && FT.prototype, "apply", "ForceTree.apply");
  wrap(v, "applyForceDelta", "graph.applyForceDelta");
  wrap(v, "absorb", "graph.absorb");
  wrap(v, "redrawForce", "graph.redrawForce");
  wrap(v, "collapseCovered", "graph.collapseCovered");
  wrap(v, "coverForce", "graph.coverForce");
  wrap(v, "treeSpring", "graph.treeSpring");
  wrap(v.batch, "sync", "batch.sync");
  wrap(b.pipebox, "flashBoxes", "pipebox.flashBoxes");
  wrap(v, "spreadUrl", "graph.spreadUrl");
  // the per-frame passes and the projection path (D-40, 2026-10-19)
  for (const m of ["refreshDetail", "calm", "batchSync", "fitChunkSizes", "applyProjected", "telescope", "fitProxies",
                   "sayCounts", "collideSoon", "glide", "highlightChunk", "openBillboard", "pullDelta", "sync"]) wrap(v, m, "graph." + m);
  for (const m of ["onPushedDrain", "tick", "paintBoxes", "storedCidFor"]) wrap(b, m, "browser." + m);
  if (b.pipebox) for (const m of ["pushedHover", "pageScrolled", "draw", "paint"]) wrap(b.pipebox, m, "pipebox." + m);
  // each force the simulation runs, timed per call
  const g = v.graph;
  for (const name of ["link", "center", "charge", "home", "contain", "collide", "treeSpring", "hold"]) {
    const f = g && g.d3Force(name);
    if (!f) continue;
    const timed = (alpha) => { const t0 = performance.now(); f(alpha); calls.push({ label: "force." + name, t0, ms: performance.now() - t0 }); };
    for (const k of Object.keys(f)) timed[k] = f[k];
    timed.initialize = (...a) => (f.initialize ? f.initialize(...a) : undefined);
    g.d3Force(name, timed);
    wraps.push(() => g.d3Force(name, f));
  }
  const long = [];
  const po = new PerformanceObserver((list) => { for (const e of list.getEntries()) long.push({ t0: e.startTime, ms: e.duration }); });
  try { po.observe({ type: "longtask", buffered: false }); } catch (e) {}
  const frames = [];
  let run = true;
  (async () => { while (run) { const f0 = performance.now(); await new Promise((r) => requestAnimationFrame(r)); frames.push({ t0: f0, ms: performance.now() - f0 }); } })();
  try {
    b.go(url);
    await sleep(6000);
    const wv = b.webview, end = performance.now() + (secs - 6) * 1000;
    while (performance.now() < end) {
      wv.sendInputEvent({ type: "mouseWheel", x: 300, y: 300, deltaX: 0, deltaY: -500 });
      await sleep(140);
      wv.sendInputEvent({ type: "mouseMove", x: 60 + Math.round(Math.random() * 500), y: 80 + Math.round(Math.random() * 500) });
      await sleep(160);
    }
  } finally {
    run = false; po.disconnect(); for (const u of wraps) u();
    if (plant) b.plant.delete(plant);
  }
  const by = {};
  for (const c of calls) { const o = by[c.label] = by[c.label] || { n: 0, total: 0, max: 0 }; o.n++; o.total += c.ms; o.max = Math.max(o.max, c.ms); }
  for (const k in by) { by[k].total = Math.round(by[k].total); by[k].max = Math.round(by[k].max); }
  // What ran inside each long task
  const attrib = long.slice().sort((a, c) => c.ms - a.ms).slice(0, 12).map((L) => ({ ms: Math.round(L.ms),
     inside: calls.filter((c) => c.t0 >= L.t0 - 1 && c.t0 <= L.t0 + L.ms).reduce((m, c) => { m[c.label] = Math.round((m[c.label] || 0) + c.ms); return m; }, {}) }));
  const gaps = frames.map((f) => f.ms).sort((a, c) => a - c);
  const q = (p) => Math.round(gaps[Math.min(gaps.length - 1, Math.floor(p * gaps.length))] || 0);
  return JSON.stringify({ plant, sync_url_asks: (b.shownAsks || 0) - asks0, long_tasks: long.length, long_total_ms: Math.round(long.reduce((s, l) => s + l.ms, 0)),
                          frame_gap: { p50: q(0.5), p95: q(0.95), max: q(1), n: gaps.length }, by, top_long: attrib });
})"""
try:
    print(live.evaluate(JS + "(%s, %d, %s)" % (json.dumps(PAGE + ("&" if "?" in PAGE else "?") + "pf=%d" % int(time.time() * 1000)), secs, json.dumps(PLANT)), timeout=secs + 60))
finally:
    if was and was.startswith("http"):
        live.evaluate("(() => { app.workspace.getLeavesOfType('vertiscope-browser-view')[0].view.go(%s); return 1; })()" % json.dumps(was))
    live.evaluate("(()=>{window.__vertiscopeReaderAt = %s; return 1})()" % json.dumps(stamp))
