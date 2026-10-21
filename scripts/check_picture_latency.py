"""G-208: a hovered picture lands fast even after the pointer swept the cloud.

Chunk view. The pointer sweeps 40 places across the panel (each reveals its
pictures and queues their decodes -- the backlog a real sweep leaves), then
rests on a picture-holding chunk whose picture was never loaded. Scored: ms
until that picture is in the atlas. Three resting places per arm, each a
fresh picture. Clean (newest decode first) vs `plantFifoLoads` (the old
first-in-first-out). Reader-idle gated per arm.
"""
import json
import sys

sys.path.insert(0, r"<home>\Documents\vertiscope")
from vertiscope.obsidian.live import Live

live = Live()
JS = r"""(async (planted, skip) => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  if (window.__vertiscope.reader.idleMs() < 60000) return JSON.stringify({ aborted: "reader active" });
  const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
  if (v.level !== "chunk") return JSON.stringify({ aborted: "not in chunk view" });
  const g = v.graph, W = v.canvasEl.clientWidth, H = v.canvasEl.clientHeight;
  v.plantNoDrift = true; v.batch.plantFifoLoads = planted;
  const at = (n) => g.graph2ScreenCoords(n.x, n.y, n.z || 0);
  const point = (x, y) => { v.pointerNdc = [x / W * 2 - 1, -(y / H * 2 - 1)]; v.detailDirty = true; v.detailAt = 0; v.refreshDetail(g); v.batchSync(); };
  const fresh = g.graphData().nodes.filter((n) => n.image && n.image.src && n.level === "chunk" && Number.isFinite(n.x) && !n.__bpic
    && !v.batch.cells?.has?.(n.image.src)).filter((n) => { const s = at(n); return s.x > 80 && s.y > 100 && s.x < W - 80 && s.y < H - 100; });
  const out = [];
  // Each arm starts from an empty decode queue: the arm before must not
  // leave its backlog to this one (the first run's arms were confounded so).
  for (let i = 0; i < 300 && v.batch.queue.length - (v.batch.queueAt || 0) > 0; i++) await sleep(100);
  try {
    for (let k = 0; k < 3; k++) {
      const target = fresh[skip + k * 37];
      if (!target) break;
      for (let i = 0; i < 40; i++) { point(60 + ((i * 97) % (W - 120)), 90 + ((i * 53) % (H - 180))); await sleep(50); }
      const s = at(target); point(s.x, s.y);
      const t0 = performance.now(); let ms = null;
      for (let i = 0; i < 100; i++) { await sleep(100); v.batchSync(); if (target.__bpic) { ms = Math.round(performance.now() - t0); break; } }
      out.push({ ms, queued: v.batch.queue ? v.batch.queue.length - (v.batch.queueAt || 0) : null });
    }
    return JSON.stringify({ planted, out });
  } finally { v.batch.plantFifoLoads = false; v.plantNoDrift = false; }
})"""
res = {}
for planted, skip in ((False, 0), (True, 11)):
    r = json.loads(live.evaluate(JS + "(%s, %d)" % ("true" if planted else "false", skip)))
    print(json.dumps(r))
    if r.get("aborted"):
        sys.exit(1)
    res[planted] = [x["ms"] if x["ms"] is not None else 10000 for x in r["out"]]
c, p = sorted(res[False]), sorted(res[True])
ok = len(c) == 3 and c[1] <= 1500 and c[1] * 3 <= p[1]
print("G-208 latency %s: hovered picture landed p50 %d ms newest-first vs %d ms first-in-first-out (after a 40-place sweep)"
      % ("PASS" if ok else "FAIL", c[1], p[1]))
