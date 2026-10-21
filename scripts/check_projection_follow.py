"""G-253 (PLUGIN_GOAL 181): every scanned chunk reaches the 3D view PROJECTED
once it is vectorized -- the grey node it started as is replaced by the
stored chunk at its fitted place -- and nothing grey is left behind (2026-10-18:
"a lot of diff scans not yet at least projected after vectorization").

Per page, FRESH (cache-busted): sampled every second for `--secs` (60):
grey chunk nodes drawn for the page (streamed, not unit), stored chunk nodes
drawn for it, the sidecar's own counts (chunks stored, embedded, projected).
Scored at the end: projected-and-drawn / projected-by-the-sidecar (the
denominator is what the projector placed -- the view is answerable for those),
grey left, seconds until the last grey node went, grey nodes that TIMED OUT
instead of becoming stored (the lifecycle's own counter). Then a unit panel is
opened and closed: its unit node must go with it (planted `plantKeepUnits`).

Reader-idle gated; plugin reloaded first; the reader's page restored.
"""
import json, sys, time, urllib.parse, urllib.request
sys.path.insert(0, r"<home>\Documents\vertiscope")
from vertiscope.obsidian.live import Live
live = Live()
if live.evaluate("window.__vertiscope.reader.idleMs()") < 60000:
    print("aborted: reader active"); sys.exit(1)
stamp = live.evaluate("window.__vertiscopeReaderAt || 0")
was = live.evaluate("app.workspace.getLeavesOfType('vertiscope-browser-view')[0].view.webview.getURL()")
restore = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--restore=")), was)
secs = int(next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--secs=")), "60"))
ARMS = [False, True] if "--arms" in sys.argv else [False]
live.reload_plugin()
PAGES = [a for a in sys.argv[1:] if a.startswith("http")] or [
    "https://en.wikipedia.org/wiki/Radix_tree", "https://bandcamp.com/"]
SAMPLE = r"""((u) => {
  const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
  const k = (x) => String(x || "").split("#")[0];
  const nodes = v.graph.graphData().nodes.filter((n) => k(n.url) === k(u));
  return JSON.stringify({ grey: nodes.filter((n) => n.force && !n.unit && n.level === "chunk").length,
                          stored: nodes.filter((n) => !n.force && n.level === "chunk").length,
                          units: nodes.filter((n) => n.unit).length, timed_out: v.forceTimedOut,
                          life: (() => { const l = v.lifecycleState(u); return { drawn: l.drawn, saved: l.saved, placed_after_saved: l.saved_to_placed_ms.n }; })(),
                          idle: window.__vertiscope.reader.idleMs() });
})"""


def side(url):
    q = urllib.parse.quote(url, safe="")
    try:
        d = json.load(urllib.request.urlopen("http://127.0.0.1:8788/page_status?url=" + q, timeout=30))
        return {"chunks": d.get("chunks"), "embedded": d.get("embedded"), "projected": d.get("projected")}
    except Exception as exc:                        # noqa: BLE001
        return {"error": str(exc)[:80]}


try:
  for planted in ARMS:
    live.evaluate("(() => { app.workspace.getLeavesOfType('vertiscope-graph-view')[0].view.plantUncoveredClock = %s; return 1; })()" % ("true" if planted else "false"))
    for page in PAGES:
        url = page + ("&" if "?" in page else "?") + "g253=%d" % int(time.time() * 1000)
        live.evaluate("(() => { app.workspace.getLeavesOfType('vertiscope-browser-view')[0].view.go(%s); return 1; })()" % json.dumps(url))
        t0 = time.time(); trace = []; last_grey = None; to0 = None; aborted = False
        while time.time() - t0 < secs:
            time.sleep(1)
            s = json.loads(live.evaluate(SAMPLE + "(%s)" % json.dumps(url)))
            if s["idle"] < 3000 and time.time() - t0 > 2:
                aborted = True; break
            if to0 is None: to0 = s["timed_out"]
            trace.append((round(time.time() - t0), s["grey"], s["stored"]))
            if s["grey"]: last_grey = round(time.time() - t0)
        sc = side(url)
        end = json.loads(live.evaluate(SAMPLE + "(%s)" % json.dumps(url)))
        proj = sc.get("projected") or 0
        print(json.dumps({"planted_uncovered_clock": planted, "page": page[8:50], "aborted_reader_active": aborted, "life": end["life"], "sidecar": sc, "view_stored_drawn": end["stored"],
                          "drawn_of_projected": round(end["stored"] / proj, 3) if proj else None, "grey_left": end["grey"],
                          "last_grey_s": last_grey, "timed_out": end["timed_out"] - (to0 or end["timed_out"]),
                          "trace": trace[::5]}))
        if aborted: break
  live.evaluate("(() => { app.workspace.getLeavesOfType('vertiscope-graph-view')[0].view.plantUncoveredClock = false; return 1; })()")
  if True:
    # A unit panel opened and closed: its unit node goes with it.
    for planted in (False, True):
        print(live.evaluate(r"""((planted) => {
          const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
          v.plantKeepUnits = planted;
          const base = v.graph.graphData().nodes.find((n) => !n.force && n.level === "chunk");
          const id = String(base.id) + "|/probe/unit" + (planted ? "p" : "c");
          const n = v.ensureUnitNode({ id, url: base.url, level: "chunk", virtual: true, x: base.x, y: base.y, z: base.z });
          const before = v.graph.graphData().nodes.includes(n);
          v.billboards.set(id, { el: document.createElement("div"), node: n, pinned: false });
          v.closeBillboard(id);
          const after = v.graph.graphData().nodes.some((m) => String(m.id) === id);
          if (after) { v.plantKeepUnits = false; v.dropUnitNode(id); }
          v.plantKeepUnits = false;
          return JSON.stringify({ planted, unit_drawn_while_open: before, unit_left_after_close: after, colour: n.color, base_colour: base.color });
        })(%s)""" % ("true" if planted else "false")))
finally:
    if restore and restore.startswith("http"):
        live.evaluate("(() => { app.workspace.getLeavesOfType('vertiscope-browser-view')[0].view.go(%s); return 1; })()" % json.dumps(restore))
    live.evaluate("(()=>{window.__vertiscopeReaderAt = %s; return 1})()" % json.dumps(stamp))
