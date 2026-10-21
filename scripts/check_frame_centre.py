"""Item 116: the cloud is framed where it is.

`reframe` with the cloud as it is (null arm), and with the whole cloud shifted
off the origin -- the shape a fresh store with a page or two has -- in the
clean build and with `plantOriginFrame` (every framing aimed at the origin,
as before). Scored by what the reader sees: how far the picture's middle sits
from the pane's (`dx`, `dy`, fractions of the pane) and how much of the pane
it fills (`w`, `h`). The shift is undone exactly; nothing is stored.
Reader-idle gated; reloads the plugin first so the LOADED build is scored.
"""
import json
import sys
import time

sys.path.insert(0, r"<home>\Documents\vertiscope")
from vertiscope.obsidian.live import Live

live = Live()
got = live.reload_plugin(settle=4, wait=True, force="--force" in sys.argv)
if got.get("refused"):
    print(got["refused"]); sys.exit(1)

# Wait for a still cloud. Straight after a reload the relax pass puts nodes
# back on their stored drawn places, and it did so DURING the first run's
# reframe: the shifted cloud snapped home, scoring the planted arm centred
# and the clean one off (2026-10-17). `held` below re-checks it per row.
STILL = r"""(async () => { const ns = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view.graph.graphData().nodes;
  const a = ns.map((n) => [n.x, n.y, n.z]); await new Promise((r) => setTimeout(r, 1000));
  let m = 0; ns.forEach((n, i) => { if (a[i]) m = Math.max(m, Math.abs(n.x - a[i][0]) + Math.abs(n.y - a[i][1]) + Math.abs(n.z - a[i][2])); });
  return m; })()"""
for i in range(120):
    moved = live.evaluate(STILL)
    if moved is not None and moved < 0.5:
        break
print("still after %d s (moved %.2f)" % (i + 1, moved or 0))

JS = r"""(async (shift, planted) => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
  const ns = v.graph.graphData().nodes;
  // Every place a node calls HOME moves with it -- the fit's position, the
  // drawn place, the anchor -- or the reframe's reheat pulls it back there
  // within 500 ms (measured: the cloud's middle 871 -> 31) and the score is
  // of a cloud that is no longer offset. This is what an offset FIT is.
  const move = (k) => { for (const n of ns) [["x", 0], ["y", 1], ["z", 2]].forEach(([a, i]) => {
      const s = k * shift[i];
      for (const f of [a, "f" + a, "fit" + a.toUpperCase()]) if (Number.isFinite(n[f])) n[f] += s;
      if (n.anchorPos && Number.isFinite(n.anchorPos[a])) n.anchorPos[a] += s;
      if (Array.isArray(n.drawnAt) && Number.isFinite(n.drawnAt[i])) n.drawnAt[i] += s; }); };
  // Abort before touching anything if the reader is back: the reader saw
  // "significant and persistent un-settling" while an earlier run of this
  // kept reframing under them (2026-10-17).
  if (window.__vertiscope.reader.idleMs() < 60000) return JSON.stringify({ aborted: "reader active" });
  v.plantOriginFrame = planted;
  const home = ns.map((n) => n.x);
  // Restore by VALUE, never by subtracting: the reheat had already pulled
  // nodes home when the old "move(-1)" ran, which threw them the shift's
  // length the other way and the forces flew them back -- a jolt the
  // reader could see.
  const saved = ns.map((n) => ({ x: n.x, y: n.y, z: n.z, fx: n.fx, fy: n.fy, fz: n.fz, fitX: n.fitX, fitY: n.fitY,
    fitZ: n.fitZ, anchor: n.anchorPos ? { ...n.anchorPos } : null, drawn: Array.isArray(n.drawnAt) ? [...n.drawnAt] : null }));
  const cam0 = v.graph.cameraPosition(), tgt0 = v.graph.controls().target.clone();
  const restore = () => { ns.forEach((n, i) => { const o = saved[i];
      for (const k of ["x", "y", "z", "fx", "fy", "fz", "fitX", "fitY", "fitZ"]) n[k] = o[k];
      if (o.anchor) Object.assign(n.anchorPos, o.anchor);
      if (o.drawn) n.drawnAt.splice(0, o.drawn.length, ...o.drawn); });
    v.graph.cameraPosition({ x: cam0.x, y: cam0.y, z: cam0.z }, tgt0, 0); };
  move(1);
  try {
    v.reframe();
    // Read between the 400 ms flight and the reframe's own 450 ms pass,
    // which re-faces every open page's disc (G-94): it releases page pins
    // and recomputes chunk places from the stored layout, so any shift is
    // undone BY DESIGN after it (traced: fx -> null, fitX 174 -> -795).
    await sleep(430);
    const c = v.screenCoverage();
    // The shift must still be in place when the picture is scored.
    let off = 0; ns.forEach((n, i) => { off += n.x - home[i]; });
    // ...and on the nodes DRAWN: the stream replaces graphData while the
    // reader browses (737 -> 736 nodes between rows), and a shift made on
    // the old objects is not in the new ones.
    const held = v.graph.graphData().nodes === ns && Math.abs(off / ns.length - shift[0]) < 1;
    const r = (x) => Math.round(x * 1000) / 1000;
    return JSON.stringify({ shift, planted, n: ns.length, held, w: r(c.w), h: r(c.h), dx: r(c.dx), dy: r(c.dy) });
  } finally { restore(); v.plantOriginFrame = false; }
})"""

rows = []
for shift in ([0, 0, 0], [900, 300, 0], [-600, 0, 400]):
    for planted in (False, True):
        for attempt in range(8):
            row = json.loads(live.evaluate(JS + "(%s, %s)" % (json.dumps(shift), "true" if planted else "false")))
            if row.get("aborted"):
                print("aborted: reader active"); sys.exit(1)
            if row["held"]:
                break
            time.sleep(3)
        row["attempts"] = attempt + 1
        rows.append(row)
        print(json.dumps(row))
rows = [r for r in rows if r["held"]]
if not any(any(r["shift"]) for r in rows):
    print("no shifted row held; no score"); sys.exit(1)

worst = lambda planted, shifted: max(max(abs(r["dx"]), abs(r["dy"])) for r in rows
                                    if r["planted"] == planted and (any(r["shift"]) == shifted))
fill = lambda planted: min(max(r["w"], r["h"]) for r in rows if r["planted"] == planted and any(r["shift"]))
print("clean: off-centre %.3f (null %.3f), fills >= %.2f" % (worst(False, True), worst(False, False), fill(False)))
print("planted: off-centre %.3f (null %.3f), fills >= %.2f" % (worst(True, True), worst(True, False), fill(True)))
