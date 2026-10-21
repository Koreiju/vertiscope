"""G-207: chunk nodes glow -- seen as points of light, measured in PIXELS.

The graph pane is photographed at full view with the glow on and with it
planted off (`plantNoHalo`), same camera. Scored on what a reader sees: the
pane's mean luminance, and how many separate lit points it holds (connected
blobs of pixels above a brightness floor) against the chunk orbs drawn. A
glow that only brightens the pane without making more nodes visible as
points fails the second. Reader-idle gated; the camera is put back.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, r"<home>\Documents\vertiscope")
from vertiscope.obsidian.live import Live
from PIL import Image
import numpy as np

live = Live()
if "--no-reload" not in sys.argv:
    got = live.reload_plugin(settle=4, wait=True)
    if got.get("refused"):
        print(got["refused"]); sys.exit(1)
if live.evaluate("window.__vertiscope.reader.idleMs()") < 60000:
    print("aborted: reader active"); sys.exit(1)

G = "app.workspace.getLeavesOfType('vertiscope-graph-view')[0].view"
# Each chunk orb's screen position (the glass mesh's nodes), so the score is
# per NODE: is it a visible point of light where it is drawn? Lit-blob counts
# were the wrong denominator -- link segments break into many blobs.
SET = r"""(async (planted) => { const v = %s; v.plantNoHalo = planted; v.plantNoDrift = true;
  await new Promise((r) => setTimeout(r, 700));
  const c = v.canvasEl.getBoundingClientRect(), g = v.graph;
  const pts = [];
  for (const n of g.graphData().nodes) {
    if (n.__bm !== 2 || n.level === "page" || !Number.isFinite(n.x)) continue;
    const q = g.graph2ScreenCoords(n.x, n.y, n.z || 0);
    if (q.x < 4 || q.y < 64 || q.x > c.width - 4 || q.y > c.height - 64) continue;
    pts.push([c.left + q.x, c.top + q.y]);
  }
  return JSON.stringify({ rect: [c.left, c.top, c.width, c.height], inner: innerWidth, pts,
                          glass: v.batch.lastStats.glass, zoom: v.zoomScale }); })""" % G
cam = live.evaluate("(()=>{const g=%s.graph; const c=g.cameraPosition(), t=g.controls().target; return JSON.stringify([c.x,c.y,c.z,t.x,t.y,t.z]);})()" % G)
live.evaluate("(()=>{%s.reframe(); return 1})()" % G)
time.sleep(2.0)

out = {}
try:
    for planted in (False, True):
        info = json.loads(live.evaluate(SET + "(%s)" % ("true" if planted else "false")))
        png = Path(r"<home>\Documents\vertiscope\build_analytics\glow_%s.png" % ("off" if planted else "on"))
        import base64
        data = live._cdp("Page.captureScreenshot", {"format": "png"})["data"]
        png.write_bytes(base64.b64decode(data))
        img = np.asarray(Image.open(png).convert("RGB")).astype(np.float32)
        k = img.shape[1] / info["inner"]
        x, y, w, h = [int(round(v * k)) for v in info["rect"]]
        pane = img[y + int(60 * k): y + h - int(60 * k), x: x + w]          # clear of the bar and the search field
        lum = 0.2126 * pane[..., 0] + 0.7152 * pane[..., 1] + 0.0722 * pane[..., 2]
        lit = lum > 60
        from scipy import ndimage
        _lab, points = ndimage.label(lit)
        full = 0.2126 * img[..., 0] + 0.7152 * img[..., 1] + 0.0722 * img[..., 2]
        peaks = []
        for px, py in info["pts"]:
            X, Y = int(round(px * k)), int(round(py * k))
            peaks.append(float(full[max(0, Y - 2):Y + 3, max(0, X - 2):X + 3].max()))
        peaks = np.asarray(peaks) if peaks else np.zeros(1)
        out[planted] = {"chunk_orbs_in_view": len(info["pts"]), "visible_points": int((peaks > 60).sum()),
                        "peak_p50": round(float(np.median(peaks)), 1), "peak_p10": round(float(np.percentile(peaks, 10)), 1),
                        "mean_luminance": round(float(lum.mean()), 2), "zoom": round(info["zoom"], 2), "png": str(png)}
        print(("planted" if planted else "clean  "), json.dumps(out[planted]))
finally:
    live.evaluate("(()=>{const v=%s; v.plantNoHalo=false; v.plantNoDrift=false; const c=%s; v.graph.cameraPosition({x:c[0],y:c[1],z:c[2]},{x:c[3],y:c[4],z:c[5]},0); return 1})()" % (G, cam))

c, p = out[False], out[True]
n = c["chunk_orbs_in_view"]
# Every orb a visible point with the glow, and the glow is what makes a
# real share of them visible: orbs the bare lens leaves under the floor.
ok = n > 20 and c["visible_points"] >= 0.95 * n and c["visible_points"] - p["visible_points"] >= 0.1 * n
print("G-207 %s: chunk orbs visible as points of light %d/%d with the glow vs %d/%d without; peak luminance p50 %.0f vs %.0f"
      % ("PASS" if ok else "FAIL", c["visible_points"], n, p["visible_points"], p["chunk_orbs_in_view"], c["peak_p50"], p["peak_p50"]))
