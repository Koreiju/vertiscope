"""D-40 diagnosis: does every PUSHED drain become a host trace, and how long
after it arrives?

Live, in the plugin's browser cell, Julia's /latest (fresh query string),
scrolled 15 wheel steps. Every pushed drain message the cell receives is
recorded as it arrives (its chunk ids, parsed); 20 s after the scroll the
profiler's live traces are matched to each push by chunk ids: absorbed or
not, arrival -> `host_epoch`, and what the trace says happened.

Reader-idle gated; the reader's page restored.
"""
import json, sys, time
sys.path.insert(0, r"<home>\Documents\vertiscope")
from vertiscope.obsidian.live import Live
live = Live()
if live.evaluate("window.__vertiscope.reader.idleMs()") < 60000:
    print("aborted: reader active"); sys.exit(1)
stamp = live.evaluate("window.__vertiscopeReaderAt || 0")
was = live.evaluate("app.workspace.getLeavesOfType('vertiscope-browser-view')[0].view.webview.getURL()")
PAGE = "https://discourse.julialang.org/latest?pa=%d" % int(time.time() * 1000)
JS = r"""(async (PAGE) => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const b = app.workspace.getLeavesOfType("vertiscope-browser-view")[0].view;
  const pushes = [];
  const onMsg = (e) => { const m = String((e && e.message) || ""); const i = m.indexOf("drain {"); if (i < 0) return;
    try { const p = JSON.parse(m.slice(i + 6)); pushes.push({ at: Date.now(), ids: (p.chunks || []).map((c) => Number(c.id)), removed: (p.removed || []).length, len: m.length }); }
    catch (x) { pushes.push({ at: Date.now(), ids: [], bad: true, len: m.length }); } };
  b.webview.addEventListener("console-message", onMsg);
  try {
    b.go(PAGE);
    for (let i = 0; i < 100; i++) { await sleep(300); try { if (b.webview.getURL() === PAGE && !b.webview.isLoading()) break; } catch (e) {} }
    await sleep(5000);
    const t0 = Date.now();
    for (let k = 0; k < 15; k++) { b.webview.sendInputEvent({ type: "mouseWheel", x: 300, y: 300, deltaX: 0, deltaY: -500 }); await sleep(400); }
    await sleep(20000);
    const traces = window.__vertiscopeProfiler.list().filter((t) => t.kind === "live" && Array.isArray(t.facts.chunk_ids) && t.facts.chunk_ids.length);
    const rows = pushes.filter((p) => p.at >= t0 - 2000).map((p) => {
      const t = p.ids.length ? traces.find((t) => t.facts.chunk_ids.some((id) => p.ids.includes(id)) && t.facts.host_epoch >= p.at - 50) : null;
      return { at_s: Math.round((p.at - t0) / 100) / 10, n: p.ids.length, ids: p.ids.length ? [Math.min(...p.ids), Math.max(...p.ids)] : [], removed: p.removed, kb: Math.round(p.len / 1024), bad: !!p.bad,
               traced: !!t, absorb_after_ms: t ? t.facts.host_epoch - p.at : null, why: t ? (t.facts.why || t.facts.outcome || null) : null,
               pump_wait: t ? Math.round(t.stages.pump_wait || 0) : null };
    });
    return JSON.stringify({ pushes: rows.length, with_chunks: rows.filter((r) => r.n).length, traced: rows.filter((r) => r.traced).length,
                            pushed_payloads: b.pushedPayloads, rows }, null, 0);
  } finally { b.webview.removeEventListener("console-message", onMsg); }
})"""
try:
    print(live.evaluate(JS + "(%s)" % json.dumps(PAGE), timeout=180))
finally:
    if was and was.startswith("http"):
        live.evaluate("(() => { app.workspace.getLeavesOfType('vertiscope-browser-view')[0].view.go(%s); return 1; })()" % json.dumps(was))
    live.evaluate("(()=>{window.__vertiscopeReaderAt = %s; return 1})()" % json.dumps(stamp))
