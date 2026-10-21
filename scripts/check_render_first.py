"""G-252 (PLUGIN_GOAL 180): rendering comes FIRST and vectorization after it
-- a fresh page's chunks are drawn as grey nodes and their panels open from
the sensor's own tree before anything is stored, embedded or placed;
storing, the vectors and the projection follow and replace them (2026-10-18:
"seeing immediate response on rendering first and getting vectorization and
projection layouts as a downstream task that doesn't block immediate diff
rendering ... the panels could theoretically render in their gray node
layouts right out the gate").

Per page, FRESH (cache-busted, so nothing of it is stored): the visit's
stage marks from the pipeline profiler (renderer clock from navigation:
`drain` the first delta left the page, `grey` the first grey node drawn,
`projected` the first placed, `stored` the first stored chunk drawn), and an
EARLY hover -- the real pointer on a visible text block as soon as the
first grey node is drawn -- scored: did a panel open, how long after the
pointer, at which stage, and was it the grey (sensor-tree) panel.

Clean vs planted `no-force-panel` (a grey chunk has no panel; the hover
waits on the store, as before PLUGIN_GOAL 125). Reader-idle gated; plugin
reloaded first; the reader's page restored.
"""
import json, sys
sys.path.insert(0, r"<home>\Documents\vertiscope")
from vertiscope.obsidian.live import Live
live = Live()
if live.evaluate("window.__vertiscope.reader.idleMs()") < 60000:
    print("aborted: reader active"); sys.exit(1)
stamp = live.evaluate("window.__vertiscopeReaderAt || 0")
was = live.evaluate("app.workspace.getLeavesOfType('vertiscope-browser-view')[0].view.webview.getURL()")
live.reload_plugin()
PAGES = [a for a in sys.argv[1:] if a.startswith("http")] or [
    "https://bandcamp.com/radio?show=1010",
    "https://huggingface.co/docs/transformers/quicktour",
    "https://en.wikipedia.org/wiki/Radix_tree",
]
JS = r"""(async (planted, start) => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
  const b = app.workspace.getLeavesOfType("vertiscope-browser-view")[0].view;
  const P = window.__vertiscope.profile;
  const mode = v.panelsOn; v.panelsOn = "flyto";
  if (planted) b.plant.add("no-force-panel");
  try {
    for (const k of [...v.billboards.keys()]) v.closeBillboard(k);
    const url = start + (start.includes("?") ? "&" : "?") + "g252=" + Date.now();
    b.go(url);
    const visit = () => { const vs = P.visits(); return vs.filter((x) => x.url.includes("g252=")).slice(-1)[0] || null; };
    const t0 = performance.now();
    let vis = null;
    for (let i = 0; i < 200; i++) { await sleep(100); vis = visit(); if (vis && vis.marks && vis.marks.grey !== undefined) break; }
    const greyAt = Math.round(performance.now() - t0);
    const FIND = `(function(){
      var els = document.querySelectorAll('p, li, h2, h3, td, article, section div');
      for (var i = 0; i < els.length; i++) {
        var e = els[i], r = e.getBoundingClientRect(), t = (e.innerText || '').trim();
        if (t.length > 30 && t.length < 600 && r.top > 60 && r.bottom < innerHeight - 20 && r.width > 150 && r.height > 12)
          return JSON.stringify({ x: r.left + Math.min(60, r.width / 2), y: r.top + Math.min(10, r.height / 2), t: t.slice(0, 40) });
      }
      return 'null'; })()`;
    let hov = null;
    const at = JSON.parse(await b.webview.executeJavaScript(FIND));
    if (at) {
      const h0 = performance.now();
      b.webview.sendInputEvent({ type: "mouseMove", x: Math.round(at.x), y: Math.round(at.y) });
      await sleep(150);
      b.webview.sendInputEvent({ type: "mouseMove", x: Math.round(at.x) + 1, y: Math.round(at.y) + 1 });
      let e = null;
      for (let i = 0; i < 80; i++) { await sleep(50); e = v.hoverBb && v.billboards.get(v.hoverBb); if (e && (e.el.textContent || "").trim().length > 10) break; e = null; }
      const vv = visit();
      hov = { opened: !!e, ms: e ? Math.round(performance.now() - h0) : null, grey: e ? String(v.hoverBb).startsWith("f:") : null,
              stored_yet: !!(vv && vv.marks && vv.marks.stored !== undefined), target: at.t };
    }
    await sleep(14000);
    vis = visit();
    for (const k of [...v.billboards.keys()]) v.closeBillboard(k);
    return JSON.stringify({ planted, page: start.replace(/^https:\/\//, "").slice(0, 45), marks: vis ? vis.marks : null, grey_wait_ms: greyAt, hover: hov,
                            grey_before_stored: !!(vis && vis.marks.grey !== undefined && (vis.marks.stored === undefined || vis.marks.grey <= vis.marks.stored)) });
  } finally { v.panelsOn = mode; b.plant.delete("no-force-panel"); }
})"""
try:
    for planted in (False, True):
        for page in PAGES:
            print(live.evaluate(JS + "(%s, %s)" % ("true" if planted else "false", json.dumps(page)), timeout=180))
finally:
    if was and was.startswith("http"):
        live.evaluate("(() => { app.workspace.getLeavesOfType('vertiscope-browser-view')[0].view.go(%s); return 1; })()" % json.dumps(was))
    live.evaluate("(()=>{window.__vertiscopeReaderAt = %s; return 1})()" % json.dumps(stamp))
