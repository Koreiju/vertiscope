"""Addendum X, the quick rows, live -- each with its planted or null arm.

G-206 smaller at full view: buried discs as drawn (seenLayout) after a
reframe, clean vs `plantNoZoomScale`; and zoomed to a fifth of the full-view
distance the factor must be 1 (null arm: nothing shrinks up close).
G-200 one back/forward set: Obsidian's header arrows hidden on the browser
view (null arm: still shown on the graph view, which uses them).
G-202 url-bar words: typed into the address bar, Enter -> DuckDuckGo; a host
-> the host (planted `address-literal`: the words go nowhere useful).
G-196 panels toggle: in right-click mode a hover opens no panel and a
right-click on a chunk node opens one (null arm: fly-to mode, as before).

Reader-idle gated per step; the camera, the browser url and the panel mode
are put back.
"""
import json
import sys
import time

sys.path.insert(0, r"<home>\Documents\vertiscope")
from vertiscope.obsidian.live import Live

live = Live()
if "--no-reload" not in sys.argv:
    got = live.reload_plugin(settle=4, wait=True)
    if got.get("refused"):
        print(got["refused"]); sys.exit(1)

def idle_or_exit():
    if live.evaluate("window.__vertiscope.reader.idleMs()") < 60000:
        print("aborted: reader active"); sys.exit(1)

G = "app.workspace.getLeavesOfType('vertiscope-graph-view')[0].view"
B = "app.workspace.getLeavesOfType('vertiscope-browser-view')[0].view"

# --- G-206 -------------------------------------------------------------------
idle_or_exit()
ZOOM = r"""(async (planted) => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const v = %s, g = v.graph;
  const cam0 = g.cameraPosition(), t0 = g.controls().target.clone();
  v.plantNoZoomScale = planted;
  try {
    v.reframe(); await sleep(1500);
    const full = v.seenLayout(), fScale = v.zoomScale, D = v.fullViewDist;
    const t = g.controls().target, c = g.camera().position;
    const dir = c.clone().sub(t).normalize();
    g.cameraPosition({ x: t.x + dir.x * D / 5, y: t.y + dir.y * D / 5, z: t.z + dir.z * D / 5 }, t, 0);
    await sleep(400);
    const nearScale = v.zoomScale;
    return JSON.stringify({ planted, full_view: { drawn: full.drawn, buried: full.buried, overlapping: full.overlapping,
                            scale: Math.round(fScale * 100) / 100, fullViewDist: Math.round(D) }, near_scale: Math.round(nearScale * 100) / 100 });
  } finally {
    v.plantNoZoomScale = false;
    g.cameraPosition({ x: cam0.x, y: cam0.y, z: cam0.z }, t0, 0);
  }
})""" % G
rows = {}
for planted in (False, True):
    rows[planted] = json.loads(live.evaluate(ZOOM + "(%s)" % ("true" if planted else "false")))
    print("G-206", json.dumps(rows[planted]))
c, p = rows[False], rows[True]
g206 = (c["full_view"]["buried"] < p["full_view"]["buried"] and c["full_view"]["scale"] <= 0.55
        and c["near_scale"] == 1 and p["full_view"]["scale"] == 1)
print("G-206 %s: buried at full view %d clean vs %d planted (of %d drawn)"
      % ("PASS" if g206 else "FAIL", c["full_view"]["buried"], p["full_view"]["buried"], c["full_view"]["drawn"]))

# --- G-200 -------------------------------------------------------------------
NAV = r"""(() => { const vis = (t) => { const c = app.workspace.getLeavesOfType(t)[0].view.containerEl.querySelector('.view-header-nav-buttons');
  return c ? getComputedStyle(c).display !== 'none' : null; };
  return JSON.stringify({ browser_header_nav: vis('vertiscope-browser-view'), graph_header_nav: vis('vertiscope-graph-view'),
    browser_bar_nav: [...%s.containerEl.querySelectorAll('button')].filter((b) => /^[\u2190\u2192]$/.test((b.textContent||'').trim())).length }); })()""" % B
nav = json.loads(live.evaluate(NAV))
g200 = nav["browser_header_nav"] is False and nav["graph_header_nav"] is True and nav["browser_bar_nav"] == 2
print("G-200 %s %s" % ("PASS" if g200 else "FAIL", json.dumps(nav)))

# --- G-202 -------------------------------------------------------------------
idle_or_exit()
ADDR = r"""(async (text, planted) => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const b = %s;
  if (planted) b.plant.add("address-literal");
  try {
    b.address.value = text;
    b.address.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    let u = ""; for (let i = 0; i < 40; i++) { await sleep(250); u = b.webview.getURL(); if (u && u !== "about:blank" && !u.startsWith("chrome-error")) break; }
    return u;
  } finally { b.plant.delete("address-literal"); }
})""" % B
start = live.evaluate("%s.webview.getURL()" % B)
# The synthetic Enter counts as reader input; the stamp is put back so the
# gate keeps measuring the READER (it aborted G-196 on our own keypress).
stamp = live.evaluate("window.__vertiscopeReaderAt || 0")
try:
    words = live.evaluate(ADDR + "(%s, false)" % json.dumps("patricia trie radix"))
    host = live.evaluate(ADDR + "(%s, false)" % json.dumps("en.wikipedia.org/wiki/Radix_tree"))
    plant = live.evaluate(ADDR + "(%s, true)" % json.dumps("patricia trie radix"))
finally:
    if start and start.startswith("http"):
        live.evaluate("(()=>{%s.go(%s); return 1})()" % (B, json.dumps(start)))
    live.evaluate("(()=>{window.__vertiscopeReaderAt = %s; return 1})()" % json.dumps(stamp))
g202 = ("duckduckgo.com" in words and "patricia" in words and "wikipedia.org/wiki/Radix_tree" in host
        and "duckduckgo.com" not in (plant or ""))
print("G-202 %s words -> %s | host -> %s | planted -> %s" % ("PASS" if g202 else "FAIL", words[:70], host[:60], (plant or "")[:60]))

# --- G-196 -------------------------------------------------------------------
idle_or_exit()
PANELS = r"""(async (mode) => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const v = %s;
  const was = v.panelsOn;
  v.setPanelsOn(mode);
  const before = { ...v.panelModeStats };
  const chunk = v.graph.graphData().nodes.find((n) => !n.force && n.level === "chunk" && n.url && !v.billboards.has(n.id));
  if (!chunk) return JSON.stringify({ error: "no chunk node drawn" });
  try {
    for (const id of [...v.billboards.keys()]) v.closeBillboard(id);
    v.hoverPanel(chunk);
    await sleep(v.hoverDwellMs + 1500);
    const byHover = v.billboards.has(chunk.id);
    for (const id of [...v.billboards.keys()]) v.closeBillboard(id);
    // The graph's own right-click handler, as a click on the node calls it.
    const handler = v.graph.onNodeRightClick();
    if (handler) handler(chunk, new MouseEvent("contextmenu"));
    await sleep(1500);
    const byRight = v.billboards.has(chunk.id);
    for (const id of [...v.billboards.keys()]) v.closeBillboard(id);
    return JSON.stringify({ mode, by_hover: byHover, by_right_click: byRight,
                            skipped: v.panelModeStats.hover_skipped - before.hover_skipped });
  } finally { v.setPanelsOn(was); }
})""" % G
rc = json.loads(live.evaluate(PANELS + "('rightclick')"))
ft = json.loads(live.evaluate(PANELS + "('flyto')"))
print("G-196 right-click mode", json.dumps(rc))
print("G-196 fly-to mode     ", json.dumps(ft))
g196 = (not rc.get("by_hover")) and rc.get("by_right_click") and ft.get("by_hover")
print("G-196 %s" % ("PASS" if g196 else "FAIL"))
