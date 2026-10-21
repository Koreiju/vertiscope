"""G-208: in chunk view, a hovered node presents its picture -- loaded, at a
size a reader can see, on top of the glow.

Chunk view (left there: it is where the reader was). The pointer is put on
picture-holding chunks one at a time, as a hover puts it; after up to 8 s for
the atlas, each is scored: revealed, drawn as a picture (not a pending orb),
and its on-screen radius in pixels. Clean vs `plantTinyReveal` (revealed at
the one orb size). One presented picture is photographed for the eye.
Reader-idle gated.
"""
import base64
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
  const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
  if (v.level !== "chunk") { const b = [...v.containerEl.querySelectorAll("button")].find((x) => (x.textContent || "").trim() === "pages"); if (b) b.click(); }
  for (let i = 0; i < 80; i++) { await sleep(500); if (v.level === "chunk" && v.graph && v.graph.graphData().nodes.length > 5000) break; }
  await sleep(2500);
  v.plantTinyReveal = planted; v.plantNoFrontDim = planted; v.plantNoDrift = true;
  const g = v.graph, W = v.canvasEl.clientWidth, H = v.canvasEl.clientHeight;
  const cam = g.camera(), e = cam.matrixWorld.elements, right = [e[0], e[1], e[2]];
  const out = [];
  try {
    const cand = g.graphData().nodes.filter((n) => n.image && n.image.src && n.level !== "page" && n.level !== "path" && Number.isFinite(n.x));
    for (const n of cand) {
      if (out.length >= 6) break;
      const s = g.graph2ScreenCoords(n.x, n.y, n.z || 0);
      if (!(s.x > 80 && s.y > 100 && s.x < W - 80 && s.y < H - 100)) continue;
      v.pointerNdc = [s.x / W * 2 - 1, -(s.y / H * 2 - 1)]; v.detailDirty = true; v.detailAt = 0;
      v.refreshDetail(g); v.batchSync();
      let loaded = false;
      for (let i = 0; i < 16 && !loaded; i++) { await sleep(500); v.batchSync(); loaded = !!n.__bpic; }
      const l = v.lookOf(n, g.nodeRelSize(), v.drawnMedia);
      const half = l.half * (n.__bpic ? 1 : v.zoomScale);
      // Radius on screen from the node's depth NOW: a right vector taken once
      // went stale when chunk view rebuilt the camera, and projected 929 px.
      const cm = g.camera(), P = cm.position, me = cm.matrixWorld.elements;
      const depth = -((n.x - P.x) * me[8] + (n.y - P.y) * me[9] + ((n.z || 0) - P.z) * me[10]);
      const pxPer = H * cm.projectionMatrix.elements[5] / (2 * depth);
      const front = [...v.dimFront].length;
      const frontDark = [...v.dimFront].filter((m) => { const lm = v.lookOf(m, g.nodeRelSize(), v.drawnMedia); return lm.alpha <= 0.2; }).length;
      // In front and NOT dark: nodes in the cylinder nearer than the picture, as the pass sees them.
      out.push({ revealed: v.detail.has(n), picture: !!l.picture, loaded, front, front_dark: frontDark,
                 radius_px: Math.round(half * pxPer * 10) / 10,
                 at: [Math.round(s.x), Math.round(s.y)] });
    }
    const c = v.canvasEl.getBoundingClientRect();
    return JSON.stringify({ planted, out, canvas: [c.left, c.top], inner: innerWidth });
  } finally { v.plantTinyReveal = false; v.plantNoFrontDim = false; v.plantNoDrift = false; }
})"""
rows = {}
for planted in (False, True):
    r = json.loads(live.evaluate(JS + "(%s)" % ("true" if planted else "false")))
    if r.get("aborted"):
        print(r); sys.exit(1)
    rows[planted] = r
    px = [x["radius_px"] for x in r["out"]]
    print(("planted" if planted else "clean  "), "n", len(px), "loaded", sum(x["loaded"] for x in r["out"]), "radius px", px,
          "front dark", [(x["front_dark"], x["front"]) for x in r["out"]])
    if not planted and r["out"]:
        data = live._cdp("Page.captureScreenshot", {"format": "png"})["data"]
        open(r"<home>\Documents\vertiscope\build_analytics\hover_picture.png", "wb").write(base64.b64decode(data))
        rows["last_at"] = r["out"][-1]["at"]
c, p = rows[False]["out"], rows[True]["out"]
med = lambda xs: sorted(xs)[len(xs) // 2] if xs else 0
ok = (len(c) >= 3 and all(x["revealed"] and x["picture"] for x in c) and sum(x["loaded"] for x in c) >= 0.8 * len(c)
      and min(x["radius_px"] for x in c) >= 11 and max(x["radius_px"] for x in c) <= 65
      and med([x["radius_px"] for x in p]) < 3)
dim_ok = sum(x["front"] for x in c) > 0 and all(x["front_dark"] == x["front"] for x in c) and sum(x["front"] for x in p) == 0
print("G-213 %s: nodes in front of the presented picture dark %d/%d (planted: %d marked)"
      % ("PASS" if dim_ok else "FAIL", sum(x["front_dark"] for x in c), sum(x["front"] for x in c), sum(x["front"] for x in p)))
print("G-208 %s: presented picture radius p50 %.1f px (planted %.1f px), %d/%d loaded within 8 s"
      % ("PASS" if ok else "FAIL", med([x["radius_px"] for x in c]), med([x["radius_px"] for x in p]), sum(x["loaded"] for x in c), len(c)))
print("photo at", rows.get("last_at"))
