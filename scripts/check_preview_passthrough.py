"""G-243 (PLUGIN_GOAL 172): an open HOVER preview does not stop the pointer
reaching the nodes beneath it.

1. NULL arm, no panel open: on-screen nodes are pointed at with the real
   pointer (CDP `Input.dispatchMouseEvent`, the events a mouse sends) until
   one is hovered -- the graph's own tooltip names it. That node is T. A
   measurement that cannot see T hovered with nothing in the way cannot say
   a panel stopped it.
2. A hover preview is opened for another node P (`openBillboard(P, false,
   true)`, the hover's own call) and offset so its BODY covers T. The pointer
   goes to T again, and two things are read where the reader would see
   them: the element under the pointer, and whether the tooltip names T.
3. A click on P (replayed through `openBillboard`) keeps the preview as an
   ordinary panel (pinned, the pointer no longer passes through).

Arms 2-3 clean vs planted `plantPreviewBlocks` (the panel takes the pointer,
as before the fix). Plugin reloaded first; reader-idle gated; the reader
stamp restored; the mouse moved off the canvas after.
"""
import json, sys, time
sys.path.insert(0, r"<home>\Documents\vertiscope")
from vertiscope.obsidian.live import Live
live = Live()
if live.evaluate("window.__vertiscope.reader.idleMs()") < 60000:
    print("aborted: reader active"); sys.exit(1)
stamp = live.evaluate("window.__vertiscopeReaderAt || 0")
live.reload_plugin()

V = 'const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view; const g = v.graph; const cv = v.canvasEl.getBoundingClientRect();'
CANDIDATES = r"""(() => { %s
  for (const k of [...v.billboards.keys()]) v.closeBillboard(k);
  window.__g243was = v.panelsOn; v.panelsOn = "flyto";
  // Room for a 340x300 panel around T, inside the canvas.
  const out = [];
  for (const n of g.graphData().nodes) {
    if (!Number.isFinite(n.x)) continue;
    const c = g.graph2ScreenCoords(n.x, n.y, n.z || 0);
    if (c.x > 200 && c.y > 200 && c.x < cv.width - 200 && c.y < cv.height - 200) out.push(String(n.id));
  }
  return JSON.stringify(out.sort(() => Math.random() - 0.5).slice(0, 25));
})()""" % V
AT = r"""((id) => { %s const n = g.graphData().nodes.find((x) => String(x.id) === id); if (!n) return "null";
  const c = g.graph2ScreenCoords(n.x, n.y, n.z || 0); return JSON.stringify({ x: Math.round(cv.left + c.x), y: Math.round(cv.top + c.y), name: String(n.name || "") }); })""" % V
TIP = r"""((name, px, py) => {
  const tips = [...document.querySelectorAll(".float-tooltip-kap")];
  const shown = tips.filter((x) => getComputedStyle(x).visibility !== "hidden" && getComputedStyle(x).display !== "none").map((x) => x.textContent || "").join(" | ");
  const under = document.elementFromPoint(px, py);
  return JSON.stringify({ names_target: !!name && shown.includes(name.slice(0, 40)),
                          under: under ? (under.closest(".vertiscope-bb") ? "panel" : under.tagName.toLowerCase()) : null });
})"""
OPEN = r"""(async (pid, tid, planted) => { %s
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  for (const k of [...v.billboards.keys()]) v.closeBillboard(k);
  v.plantPreviewBlocks = planted;
  const ns = g.graphData().nodes, P = ns.find((x) => String(x.id) === pid), T = ns.find((x) => String(x.id) === tid);
  await v.openBillboard(P, false, true);
  const e = v.billboards.get(P.id);
  // Placed until it holds still over T: the body fills in after its first
  // paint and changes size, so one measurement can miss.
  let px = 0, py = 0, b = null, ok = false;
  for (let i = 0; i < 10 && !ok; i++) {
    const box = e.el.getBoundingClientRect();
    const pc = g.graph2ScreenCoords(P.x, P.y, P.z || 0), tc = g.graph2ScreenCoords(T.x, T.y, T.z || 0);
    e.dx = Math.round(tc.x - pc.x - box.width / 2);
    e.dy = Math.round(tc.y - pc.y - Math.max(40, box.height / 2));
    await sleep(400);
    const t = g.graph2ScreenCoords(T.x, T.y, T.z || 0);
    px = Math.round(cv.left + t.x); py = Math.round(cv.top + t.y);
    b = e.el.getBoundingClientRect();
    ok = px > b.left + 8 && px < b.right - 8 && py > b.top + 36 && py < b.bottom - 8;
  }
  return JSON.stringify({ px, py, covered: ok, is_preview: e.el.classList.contains("is-preview") });
})""" % V
KEEP = r"""(async (pid) => { %s
  const P = g.graphData().nodes.find((x) => String(x.id) === pid);
  await v.openBillboard(P);                       // the click's own call
  const e = v.billboards.get(pid);
  const kept = !!e && !!e.pinned && !e.el.classList.contains("is-preview");
  for (const k of [...v.billboards.keys()]) v.closeBillboard(k);
  v.plantPreviewBlocks = false;
  return JSON.stringify({ kept_on_click: kept });
})""" % V

def mouse(x, y):
    live._cdp("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
def point(x, y):
    # Approach in steps, as a hand does, so the per-frame pick ranking follows.
    for k in (14, 7, 3, 0):
        mouse(x - k, y - k); time.sleep(0.2)
    time.sleep(0.7)
def hovered(name, x, y):
    return json.loads(live.evaluate(TIP + "(%s, %d, %d)" % (json.dumps(name), x, y)))

# The reload restarts the layout: wait until drawn nodes hold still on
# screen (under 2 px over a second), or nothing can be pointed at.
SNAP = r"""(() => { %s return JSON.stringify(g.graphData().nodes.filter((n) => Number.isFinite(n.x)).slice(0, 400)
  .map((n) => { const c = g.graph2ScreenCoords(n.x, n.y, n.z || 0); return [String(n.id), c.x, c.y]; })); })()""" % V
settle_t0 = time.time()
while time.time() - settle_t0 < 90:
    s0 = {i: (x, y) for i, x, y in json.loads(live.evaluate(SNAP))}; time.sleep(1.0)
    s1 = {i: (x, y) for i, x, y in json.loads(live.evaluate(SNAP))}
    both = [k for k in s0 if k in s1]
    if len(both) > 10 and max(abs(s0[k][0] - s1[k][0]) + abs(s0[k][1] - s1[k][1]) for k in both) < 2: break
print(json.dumps({"settled_s": round(time.time() - settle_t0, 1)}))
try:
    cands = json.loads(live.evaluate(CANDIDATES))
    T = None
    for cid in cands:
        a = json.loads(live.evaluate(AT + "(%s)" % json.dumps(cid)))
        if not a: continue                      # gone meanwhile (a stream replaced it)
        point(a["x"], a["y"])
        if hovered(a["name"], a["x"], a["y"])["names_target"]:
            T = cid; break
        mouse(2, 2); time.sleep(0.3)
    if not T:
        print(json.dumps({"error": "null arm: no candidate hovered", "tried": len(cands)})); sys.exit(2)
    P = next(c for c in cands if c != T)
    print(json.dumps({"arm": "null", "target": T[:60], "hovered": True}))
    for planted in (False, True):
        mouse(2, 2); time.sleep(0.5)
        o = json.loads(live.evaluate(OPEN + "(%s, %s, %s)" % (json.dumps(P), json.dumps(T), "true" if planted else "false"), timeout=60))
        a = json.loads(live.evaluate(AT + "(%s)" % json.dumps(T)))
        point(o["px"], o["py"])
        h = hovered(a["name"], o["px"], o["py"])
        k = json.loads(live.evaluate(KEEP + "(%s)" % json.dumps(P), timeout=60))
        print(json.dumps({"arm": "planted" if planted else "clean", **o, "under": h["under"],
                          "target_hovered": h["names_target"], **k}))
finally:
    mouse(2, 2)
    live.evaluate("(()=>{const v = app.workspace.getLeavesOfType('vertiscope-graph-view')[0].view; v.plantPreviewBlocks = false; if (window.__g243was) v.panelsOn = window.__g243was; return 1})()")
    live.evaluate("(()=>{window.__vertiscopeReaderAt = %s; return 1})()" % json.dumps(stamp))
