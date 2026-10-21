"""G-222 (PLUGIN_GOAL 151) and G-229 (PLUGIN_GOAL 158), live.

G-222, the results strip above the search bar: after a search, (a) the strip
holds one item per result in the slider's window; (b) moving the BAR to a
fraction moves the strip to the same fraction of its own span (planted
`plantStripUnlinked`: it stays); (c) an item is lit as its node
(`stripLight`); (d) hovering an item flies to that result (the focus
target's id is the hit's, or its page's).

G-229, the reader's zoom persists: after the search, the camera is pulled
back to 4x its distance (a zoom-out); then four later results are hovered
through the hover path; the camera's distance after each flight is compared
with the zoomed-out one (planted `plantClampKeptZoom`: the speck clamp pulls
each flight back in).

The plugin reloaded first; the field, panels toggle and camera restored;
reader-idle gated; the reader stamp restored.
"""
import json, sys
sys.path.insert(0, r"<home>\Documents\vertiscope")
from vertiscope.obsidian.live import Live
live = Live()
if live.evaluate("window.__vertiscope.reader.idleMs()") < 60000:
    print("aborted: reader active"); sys.exit(1)
stamp = live.evaluate("window.__vertiscopeReaderAt || 0")
live.reload_plugin()
JS = r"""(async (planted) => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
  const f = v.searchField, g = v.graph, cam = g.camera(), ctl = g.controls();
  const was = { q: f.input.value, k: f.k, n: f.total, mode: v.panelsOn, p: cam.position.clone(), t: ctl.target.clone() };
  f.plantStripUnlinked = planted; v.plantClampKeptZoom = planted; v.panelsOn = "flyto";
  try {
    // A query whose later results stand on DISTINCT nodes, so hovering them
    // flies (results on one page all resolve to that page in url view).
    let query = "";
    for (const q of ["music", "wikipedia", "saddle", "patricia trie", "history", "cowboy"]) {
      f.input.value = q; f.k = 12; f.total = 40;
      await f.run();
      for (let i = 0; i < 120 && f.tierStats.pages_done < f.tierStats.pages; i++) await sleep(250);
      await sleep(600);
      const ids = new Set((v.searchState ? v.searchState.targets : []).slice(3, 8).filter(Boolean).map((n) => n.id));
      query = q;
      if (ids.size >= 4) break;
    }
    const win = f.window;
    const items = f.strip.children.length;
    // (b) the bar to 50%, then 100%
    const follow = [];
    for (const frac of [0.5, 1.0]) {
      const bar = f.scroller.scrollWidth - f.scroller.clientWidth;
      f.scroller.scrollLeft = Math.round(frac * bar);
      await sleep(120);
      const span = f.strip.scrollWidth - f.strip.clientWidth;
      follow.push({ frac, strip_frac: span > 0 ? +(f.strip.scrollLeft / span).toFixed(3) : null, span });
    }
    // (c) lights
    const lit = [...f.strip.children].slice(0, 5).map((el) => +(+el.style.opacity).toFixed(3));
    // (d) hover an item -> a flight to its node
    const k = Math.min(3, win.length - 1);
    const f0 = v.focusStats.flown;
    f.strip.children[k].dispatchEvent(new MouseEvent("mouseenter"));
    let flown = 0; for (let i = 0; i < 40 && !flown; i++) { await sleep(100); flown = v.focusStats.flown - f0; }
    const target = String(v.focusStats.last || "");
    const hit = win[k];
    f.strip.children[k].dispatchEvent(new MouseEvent("mouseleave"));
    const hitMatch = !!hit && (target.includes(hit.cid.slice(0, 40)) || target.includes(hit.url.slice(0, 40)));
    // G-229: zoom out to 4x, then hover four later results
    await sleep(600);
    const dir = cam.position.clone().sub(ctl.target);
    const D0 = dir.length() * 4;
    g.cameraPosition(ctl.target.clone().add(dir.setLength(D0)), ctl.target.clone(), 0);
    await sleep(300);
    const dists = [];
    let flights = 0;
    // Four distinct SMALL nodes (the speck clamp's targets), flown to by the
    // hover path one after another, the camera zoomed out before the first.
    const small = g.graphData().nodes.filter((n) => n.level === "page" && Number.isFinite(n.x))
      .map((n) => [v.drawnRadiusOf(n), n]).sort((a, b) => a[0] - b[0]).slice(0, 40).map((x) => x[1]);
    for (let j = 0; j < 4; j++) {
      const n = small[j * 9];
      const fl = v.focusStats.flown;
      v.focusOn(n);
      for (let i = 0; i < 40 && v.focusStats.flown === fl; i++) await sleep(100);
      flights += v.focusStats.flown - fl;
      await sleep(600);
      dists.push(+(cam.position.distanceTo(ctl.target) / D0).toFixed(2));
    }
    v.focusOn(null);
    return JSON.stringify({ planted, query, panel: v.hoverBb ? String(v.hoverBb).slice(-30) : '', window: win.length, items, follow, lit, hover_flew: flown > 0, hover_target_is_hit: hitMatch,
                            zoom_kept_ratio: dists, zoom_flights: flights, strip: f.stripStats, strip_hovers: v.searchStats.strip_hovers });
  } finally {
    f.plantStripUnlinked = false; v.plantClampKeptZoom = false; v.panelsOn = was.mode;
    f.input.value = was.q; f.k = was.k; f.total = was.n; await f.run();
    g.cameraPosition(was.p, was.t, 0);
  }
})"""
for planted in (False, True):
    print(live.evaluate(JS + "(%s)" % ("true" if planted else "false")))
live.evaluate("(()=>{window.__vertiscopeReaderAt = %s; return 1})()" % json.dumps(stamp))
