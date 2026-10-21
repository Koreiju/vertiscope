"""G-194: a refit's redraw keeps the reader's view (registered), not a snap.

The camera is first put somewhere a reframe would NOT put it (closer, off to
one side), then the pane is redrawn exactly as a new fit epoch redraws it
(`capturePose` + `reload`). Scored on what the reader sees: how far the url
nodes on screen moved, in pixels (median and p90 over the pages in view).
Clean: the camera comes back registered; planted `plantSnapOnRefit`: the
reframe, as before. The registration's own maths is unit-tested on a real
rotation/scale/shift (`obsidian-plugin/tests/similarity.test.mjs`). Reader-
idle gated; the camera is put back.
"""
import json
import sys

sys.path.insert(0, r"<home>\Documents\vertiscope")
from vertiscope.obsidian.live import Live

live = Live()
if "--no-reload" not in sys.argv:
    got = live.reload_plugin(settle=4, wait=True)
    if got.get("refused"):
        print(got["refused"]); sys.exit(1)

JS = r"""(async (planted) => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  if (window.__vertiscope.reader.idleMs() < 60000) return JSON.stringify({ aborted: "reader active" });
  let v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
  const g0 = v.graph, cam0 = g0.cameraPosition(), t0 = g0.controls().target.clone();
  v.plantNoDrift = true;
  // A view no reframe makes: a third of the way in, toward a page off-centre.
  let pages = [];
  for (let i = 0; i < 60 && pages.length < 10; i++) {
    pages = g0.graphData().nodes.filter((n) => n.level === "page" && !n.force && Number.isFinite(n.x));
    if (pages.length < 10) await sleep(1000);
  }
  if (pages.length < 10) return JSON.stringify({ aborted: "no pages drawn" });
  const aim = pages[Math.floor(pages.length * 0.37)];
  const c = g0.camera().position;
  g0.cameraPosition({ x: aim.x + (c.x - aim.x) * 0.35, y: aim.y + 80, z: aim.z + (c.z - aim.z) * 0.35 }, { x: aim.x, y: aim.y, z: aim.z }, 0);
  await sleep(500);
  const screen = (g) => { const m = new Map(); const W = v.canvasEl.clientWidth, H = v.canvasEl.clientHeight;
    for (const n of g.graphData().nodes) { if (n.level !== "page" || n.force || !Number.isFinite(n.x)) continue;
      const q = g.graph2ScreenCoords(n.x, n.y, n.z || 0); if (q.x >= 0 && q.y >= 0 && q.x <= W && q.y <= H) m.set(n.url, q); } return m; };
  const before = screen(g0);
  v.plantSnapOnRefit = planted;
  try {
    v.capturePose();
    await v.reload();
    await sleep(1500);
    v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
    const after = screen(v.graph);
    const d = [];
    for (const [u, q] of before) { const r = after.get(u); d.push(r ? Math.hypot(r.x - q.x, r.y - q.y) : 1e4); }
    d.sort((a, b) => a - b);
    const q = (p) => d.length ? Math.round(d[Math.min(d.length - 1, Math.floor(p * d.length))]) : null;
    return JSON.stringify({ planted, pages_in_view: before.size, moved_px_p50: q(0.5), moved_px_p90: q(0.9),
                            left_view: d.filter((x) => x >= 1e4).length, refit: v.refitStats });
  } finally {
    v.plantSnapOnRefit = false; v.plantNoDrift = false;
    v.graph.cameraPosition({ x: cam0.x, y: cam0.y, z: cam0.z }, t0, 0);
  }
})"""
rows = []
for planted in (False, True):
    r = json.loads(live.evaluate(JS + "(%s)" % ("true" if planted else "false")))
    print(json.dumps(r))
    if r.get("aborted"):
        sys.exit(1)
    rows.append(r)
c, p = rows
ok = c["moved_px_p90"] is not None and c["moved_px_p90"] <= 3 and p["moved_px_p50"] > 30
print("G-194 %s: url nodes on screen moved p50 %s / p90 %s px registered, vs p50 %s px reframed (planted); %d pages in view"
      % ("PASS" if ok else "FAIL", c["moved_px_p50"], c["moved_px_p90"], p["moved_px_p50"], c["pages_in_view"]))
