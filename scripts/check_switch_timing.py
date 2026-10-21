"""G-179 / G-182 live: chunk-view switch time, and the second switch reading
stored drawn places instead of relaxing. Runs only with the reader idle."""
import sys, json, time
sys.path.insert(0, r"<home>\Documents\vertiscope\scripts")
from live_probe import Probe
p = Probe()
idle = p.ev("window.__vertiscope.reader.idleMs()")
if idle < 60000:
    print("reader active (%d ms idle): not run" % idle); sys.exit(0)
stamp0 = p.ev("window.__vertiscopeReaderAt || 0")
# No reload: the loaded build is current (a reload hung once, 2026-10-12).
for i in range(60):
    time.sleep(2)
    if p.ev("(()=>{const v=app.workspace.getLeavesOfType('vertiscope-graph-view')[0]?.view; return !!(v&&v.graph&&v.graph.graphData().nodes.length>50)})()"): break
JS = r"""(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
  const unit = () => [...v.containerEl.querySelectorAll(".vertiscope-graph-bar button")].find((b) => /^(pages|chunks)$/.test(b.textContent.trim()));
  const chunkView = () => v.level === "chunk" && v.umapOnly && v.graph && v.graph.graphData().nodes.length > 2000;
  const urlView = () => v.level === "" && !v.umapOnly && v.graph && v.graph.graphData().nodes.length < 5000;
  const out = [];
  for (const round of [1, 2]) {
    if (v.level === "chunk") { unit().click(); for (let i = 0; i < 600 && !urlView(); i++) await sleep(250); }
    await sleep(1500);
    const runs0 = v.chunkRelaxStats.runs || 0, skip0 = v.drawnStats.skipped;
    const t0 = performance.now();
    unit().click();
    for (let i = 0; i < 2400 && !chunkView(); i++) await sleep(100);
    const shown = performance.now() - t0;
    // The relax is time-sliced: wait for it to finish (or be skipped).
    for (let i = 0; i < 1200 && (v.chunkRelaxStats.runs || 0) === runs0 && v.drawnStats.skipped === skip0; i++) await sleep(250);
    out.push({ round, shown_ms: Math.round(shown), nodes: v.graph.graphData().nodes.length,
               with_drawn: v.graph.graphData().nodes.filter((n) => n.drawnAt).length,
               relaxed: (v.chunkRelaxStats.runs || 0) > runs0, relax_ms: v.chunkRelaxStats.ms, skipped: v.drawnStats.skipped > skip0,
               posted: v.drawnStats.posted, saved: v.drawnStats.saved, settled_ms: Math.round(performance.now() - t0) });
    await sleep(4000);  // the drawn places post to the sidecar
  }
  return JSON.stringify(out);
})()"""
r = p.ev(JS)
print(json.dumps(json.loads(r), indent=1))
# Restore only a reader stamp this probe could have written (none here; clicks do not stamp).
