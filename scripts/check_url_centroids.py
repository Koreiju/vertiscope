"""G-245 (PLUGIN_GOAL 174): a url node stands at the centroid of its chunks.

Up to eight pages of different sizes (10-600 stored chunks) are unfolded the
way a click unfolds them (`togglePage`), the layout left to settle, and for
every page with three or more drawn chunks the distance from its url node to
the centroid of those chunks is read, as a fraction of the cloud's rms
radius (0 = dead centre; ~1 = at the cloud's edge, which is what "sitting at
the edge of their chunks' fans" looks like). Split by what drew the chunk:
stored (telescoped), projected-before-stored, grey stream.

Clean vs planted `plantOffCentre` (the telescope offsets from the page point,
not the chunks' centroid). Pages the probe unfolded are folded back.
Reader-idle gated; plugin reloaded first; the reader stamp restored.
"""
import json, sys, time
sys.path.insert(0, r"<home>\Documents\vertiscope")
from vertiscope.obsidian.live import Live
live = Live()
if live.evaluate("window.__vertiscope.reader.idleMs()") < 60000:
    print("aborted: reader active"); sys.exit(1)
stamp = live.evaluate("window.__vertiscopeReaderAt || 0")
live.reload_plugin()
time.sleep(20)

MEASURE = r"""(() => {
  const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view; const ns = v.graph.graphData().nodes;
  const pages = new Map(); for (const n of ns) if (n.level === "page" && !n.force) pages.set(String(n.url).split("#")[0], n);
  const by = new Map();
  for (const n of ns) if (n.level !== "page" && n.level !== "path" && Number.isFinite(n.x)) {
    const u = String(n.url || "").split("#")[0]; if (!by.has(u)) by.set(u, []); by.get(u).push(n); }
  const rows = [];
  for (const [u, cs] of by) {
    const p = pages.get(u); if (!p || cs.length < 3) continue;
    const c = [0, 0, 0]; for (const n of cs) { c[0] += n.x; c[1] += n.y; c[2] += (n.z || 0); }
    for (let i = 0; i < 3; i++) c[i] /= cs.length;
    let rms = 0; for (const n of cs) rms += (n.x - c[0]) ** 2 + (n.y - c[1]) ** 2 + ((n.z || 0) - c[2]) ** 2;
    rms = Math.sqrt(rms / cs.length);
    const off = Math.hypot(p.x - c[0], p.y - c[1], (p.z || 0) - c[2]);
    rows.push({ url: u.slice(-50), n: cs.length, grey: cs.filter((n) => n.force && !n.projected).length,
                projected: cs.filter((n) => n.projected).length, ratio: +(off / Math.max(1e-6, rms)).toFixed(3),
                off: +off.toFixed(1), rms: +rms.toFixed(1) });
  }
  return JSON.stringify(rows.sort((a, b) => b.ratio - a.ratio));
})()"""
UNFOLD = r"""(async (planted) => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
  v.plantOffCentre = planted;
  const ns = v.graph.graphData().nodes;
  const drawn = new Set(ns.filter((n) => n.level !== "page").map((n) => String(n.url || "").split("#")[0]));
  const pages = ns.filter((n) => n.level === "page" && !n.force && n.url && !drawn.has(String(n.url).split("#")[0])
                          && (n.members || 0) >= 10 && (n.members || 0) <= 600);
  pages.sort((a, b) => (a.members || 0) - (b.members || 0));
  const pick = []; for (let i = 0; i < 8 && pages.length; i++) pick.push(pages[Math.floor((i + 0.5) * pages.length / 8)]);
  const opened = [];
  for (const p of pick) { if (!p) continue; const r = await v.togglePage(p); if (r.action === "expand") opened.push(p.url); }
  window.__g245 = opened;
  await sleep(8000);
  return JSON.stringify({ opened: opened.length });
})"""
FOLD = r"""(async () => {
  const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
  const ns = v.graph.graphData().nodes;
  for (const u of window.__g245 || []) { const p = ns.find((n) => n.level === "page" && n.url === u); if (p) await v.togglePage(p); }
  v.plantOffCentre = false; return 1;
})()"""
try:
    for planted in (False, True):
        o = json.loads(live.evaluate(UNFOLD + "(%s)" % ("true" if planted else "false"), timeout=240))
        rows = json.loads(live.evaluate(MEASURE))
        r = sorted(x["ratio"] for x in rows)
        stored = sorted(x["ratio"] for x in rows if not x["grey"] and not x["projected"])
        med = lambda a: a[len(a) // 2] if a else None
        print(json.dumps({"arm": "planted" if planted else "clean", **o, "pages": len(rows),
                          "ratio_median": med(r), "ratio_max": r[-1] if r else None,
                          "stored_only_median": med(stored), "over_0.5": sum(1 for x in r if x > 0.5),
                          "worst": rows[:4]}))
        live.evaluate(FOLD, timeout=120)
        time.sleep(3)
finally:
    live.evaluate("(()=>{const v = app.workspace.getLeavesOfType('vertiscope-graph-view')[0].view; v.plantOffCentre = false; return 1})()")
    live.evaluate("(()=>{window.__vertiscopeReaderAt = %s; return 1})()" % json.dumps(stamp))
