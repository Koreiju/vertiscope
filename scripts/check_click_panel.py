"""G-224 (PLUGIN_GOAL 153): click-to-panel latency, measured.

Ten drawn chunk nodes, each opened through the click's own call
(`openBillboard`) and timed until its panel shows content (text or a
picture). Cold (first open) and warm (closed and reopened). The panel's
payload fetch is timed separately (`chunkPayload`), so the remainder is the
render. Reader-idle gated; panels closed after; the reader stamp restored.
"""
import json, sys
sys.path.insert(0, r"<home>\Documents\vertiscope")
from vertiscope.obsidian.live import Live
live = Live()
if live.evaluate("window.__vertiscope.reader.idleMs()") < 60000:
    print("aborted: reader active"); sys.exit(1)
stamp = live.evaluate("window.__vertiscopeReaderAt || 0")
JS = r"""(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
  let nodes = v.graph.graphData().nodes.filter((n) => n.level === "chunk" && !n.force && !String(n.id).includes("|"));
  let unfolded = null;
  if (nodes.length < 10) {
    // Unfold a page, as a click on it does, so its chunks are drawn.
    const pages = v.graph.graphData().nodes.filter((n) => n.level === "page" && !n.force && (n.members || 0) >= 30 && (n.members || 0) <= 400);
    unfolded = pages[Math.floor(Math.random() * pages.length)];
    if (unfolded) { await v.togglePage(unfolded); for (let i = 0; i < 50; i++) { await sleep(200);
      nodes = v.graph.graphData().nodes.filter((n) => n.level === "chunk" && !n.force && n.url === unfolded.url); if (nodes.length >= 10) break; } }
  }
  const pick = nodes.sort(() => Math.random() - 0.5).slice(0, 6);
  // Shown = the chunk's OWN first line is in the panel (the address header
  // is there at once and is not the content).
  const firstLine = {};
  const shown = (id) => { const e = v.billboards.get(id); if (!e) return false; const el = e.el;
    const want = firstLine[id]; const norm = (x) => String(x || "").toLowerCase().replace(/[^a-z0-9]+/g, "");
    return want ? norm(el.textContent).includes(want) : !!el.querySelector("img"); };
  const open = async (n) => {
    const t0 = performance.now();
    void v.openBillboard(n);
    for (let i = 0; i < 250 && !shown(n.id); i++) await sleep(10);
    return shown(n.id) ? Math.round(performance.now() - t0) : -1;
  };
  const out = [];
  for (const n of pick) {
    v.payloadCache.delete(n.id);
    const tp = performance.now(); const pay = await v.chunkPayload(n.id); const payload = Math.round(performance.now() - tp);
    const line = ((pay && pay.lines) || []).map((l) => String(l.text || "").trim()).find((s) => s.length >= 6 && !s.startsWith("!["));
    firstLine[n.id] = line ? line.toLowerCase().replace(/[^a-z0-9]+/g, "").slice(0, 10) : "";
    v.closeBillboard(n.id);
    v.payloadCache.delete(n.id);
    const cold = await open(n);
    v.closeBillboard(n.id);
    const warm = await open(n);
    v.closeBillboard(n.id);
    out.push({ id: String(n.id).slice(-10), payload, cold, warm });
  }
  const q = (a, f) => { const s = [...a].sort((x, y) => x - y); return s[Math.min(s.length - 1, Math.floor(f * s.length))]; };
  if (unfolded) await v.togglePage(unfolded);
  return JSON.stringify({ n: out.length, drawn_chunks: nodes.length, unfolded: unfolded ? unfolded.url.slice(0, 60) : null,
    cold: { p50: q(out.map((o) => o.cold), .5), p90: q(out.map((o) => o.cold), .9) },
    warm: { p50: q(out.map((o) => o.warm), .5), p90: q(out.map((o) => o.warm), .9) },
    payload: { p50: q(out.map((o) => o.payload), .5), p90: q(out.map((o) => o.payload), .9) }, rows: out });
})()"""
print(live.evaluate(JS))
live.evaluate("(()=>{window.__vertiscopeReaderAt = %s; return 1})()" % json.dumps(stamp))
