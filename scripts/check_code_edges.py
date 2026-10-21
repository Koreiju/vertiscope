"""G-241: the code graph's CALLS / INHERITS drawn between an open code page's
chunks -- typed colours, a switch per kind, never forces.

A `code://repo/` module with many calls is unfolded the way a click does
(`togglePage`). Read: the edges the sidecar mapped (`/cpg_edges`), what the
scene batch DREW (`codeEdgeStats.drawn`, the batch's line count), the graph's
force links before and after (unchanged: drawn, not forces), then CALLS
switched off (none drawn), on again. Clean vs planted `plantNoCodeEdges`.
Reader-idle gated; plugin reloaded first; the page folded back.
"""
import json, sys, time, urllib.parse, urllib.request
sys.path.insert(0, r"<home>\Documents\vertiscope")
from vertiscope.obsidian.live import Live
SC = "http://127.0.0.1:8788"
live = Live()
if live.evaluate("window.__vertiscope.reader.idleMs()") < 60000:
    print("aborted: reader active"); sys.exit(1)
stamp = live.evaluate("window.__vertiscopeReaderAt || 0")
live.reload_plugin()
URL = sys.argv[1] if len(sys.argv) > 1 else "code://repo/graphstore.py"
mapped = json.load(urllib.request.urlopen(SC + "/cpg_edges?url=" + urllib.parse.quote(URL, safe=""), timeout=120))
print(json.dumps({"url": URL, "rows": mapped["rows"], "mapped_edges": len(mapped["edges"]),
                  "kinds": {k: sum(1 for e in mapped["edges"] if e["kind"] == k) for k in ("CALLS", "INHERITS")}}))
JS = r"""(async (url, planted) => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
  for (let i = 0; i < 120 && !v.graph.graphData().nodes.some((n) => n.url === url && n.level === "page"); i++) await sleep(500);
  const page = v.graph.graphData().nodes.find((n) => n.url === url && n.level === "page");
  if (!page) return JSON.stringify({ planted, error: "page not drawn" });
  v.plantNoCodeEdges = planted;
  const links0 = v.graph.graphData().links.length;
  await v.togglePage(page);
  for (let i = 0; i < 40; i++) { await sleep(500); if (v.graph.graphData().nodes.filter((n) => n.url === url && n.level !== "page").length > 3) break; }
  await sleep(4000); v.batchDirty = true; await sleep(2500);       // drawn on the next frames (a covered window: ~1 fps)
  const chunks = v.graph.graphData().nodes.filter((n) => n.url === url && n.level !== "page").length;
  const on = { ...v.codeEdgeStats.drawn };
  const lines_on = v.batch ? v.batch.lastStats.lines : null;
  const linksAfter = v.graph.graphData().links.length;
  v.codeEdgeKinds.CALLS = false; v.batchDirty = true; await sleep(2500);
  const off = { ...v.codeEdgeStats.drawn }; const lines_off = v.batch ? v.batch.lastStats.lines : null;
  v.codeEdgeKinds.CALLS = true; v.batchDirty = true; await sleep(2500);
  const back = { ...v.codeEdgeStats.drawn };
  await v.togglePage(page); v.plantNoCodeEdges = false;
  return JSON.stringify({ planted, chunks_drawn: chunks, drawn: on, batch_lines: lines_on, calls_off: off, batch_lines_calls_off: lines_off,
                          calls_on_again: back, force_links_before: links0, force_links_after_unfold: linksAfter });
})"""
try:
    for planted in (False, True):
        print(live.evaluate(JS + "(%s, %s)" % (json.dumps(URL), "true" if planted else "false"), timeout=180))
finally:
    live.evaluate("(()=>{window.__vertiscopeReaderAt = %s; return 1})()" % json.dumps(stamp))
