"""G-245, the STREAMED case: a page being browsed, whose chunks arrive as
grey (force-tree) and projected nodes before the store holds them. Where does
its url node stand against them? (`check_url_centroids.py` measures pages
unfolded from the store: 0.044 of the cloud's rms off centre, clean.)

A page not in the store is opened in the browser cell; at 6, 12 and 20 s the
url node's distance from the centroid of that page's drawn chunk nodes is read
as a fraction of their rms radius, split by kind. Reader-idle gated; the
reader's page restored after.
"""
import json, sys, time
sys.path.insert(0, r"<home>\Documents\vertiscope")
from vertiscope.obsidian.live import Live
live = Live()
if live.evaluate("window.__vertiscope.reader.idleMs()") < 60000:
    print("aborted: reader active"); sys.exit(1)
stamp = live.evaluate("window.__vertiscopeReaderAt || 0")
PAGES = ["https://en.wikipedia.org/wiki/AVL_tree", "https://en.wikipedia.org/wiki/Red%E2%80%93black_tree",
         "https://en.wikipedia.org/wiki/B%2B_tree", "https://en.wikipedia.org/wiki/Rope_(data_structure)",
         "https://en.wikipedia.org/wiki/Finger_tree", "https://en.wikipedia.org/wiki/Cartesian_tree"]
B = "app.workspace.getLeavesOfType('vertiscope-browser-view')[0].view"
G = "app.workspace.getLeavesOfType('vertiscope-graph-view')[0].view"
was = live.evaluate(B + ".webview.getURL()")          # the reader's page, BEFORE the reload
if "127.0.0.1:8793" in (was or "") or "g245=" in (was or ""): was = ""
live.reload_plugin()
M = r"""((url) => {
  const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view; const ns = v.graph.graphData().nodes;
  const key = (u) => String(u || "").split("#")[0];
  const page = ns.find((n) => n.level === "page" && key(n.url) === key(url));
  const cs = ns.filter((n) => n.level !== "page" && n.level !== "path" && key(n.url) === key(url) && Number.isFinite(n.x));
  const drawn = (n) => [n.x, n.y, n.z || 0], fit = (n) => [n.fitX ?? n.x, n.fitY ?? n.y, n.fitZ ?? n.z ?? 0];
  const one = (a, get) => {
    const c = [0, 0, 0]; for (const n of a) { const p = get(n); for (let i = 0; i < 3; i++) c[i] += p[i]; } for (let i = 0; i < 3; i++) c[i] /= a.length;
    let rms = 0; for (const n of a) { const p = get(n); rms += (p[0] - c[0]) ** 2 + (p[1] - c[1]) ** 2 + (p[2] - c[2]) ** 2; } rms = Math.sqrt(rms / a.length);
    const q = get(page); const off = Math.hypot(q[0] - c[0], q[1] - c[1], q[2] - c[2]);
    return { ratio: +(off / Math.max(1e-6, rms)).toFixed(3), off: +off.toFixed(1), rms: +rms.toFixed(1) }; };
  // Drawn (where the reader sees it) and TARGET (`fitX`: where the layout
  // is taking it): a gap between them is a glide still in flight.
  const part = (sel) => { const a = cs.filter(sel); if (a.length < 3 || !page) return { n: a.length };
    return { n: a.length, drawn: one(a, drawn), target: one(a, fit) }; };
  const lag = (n) => Math.hypot(n.x - (n.fitX ?? n.x), n.y - (n.fitY ?? n.y), (n.z || 0) - (n.fitZ ?? n.z ?? 0));
  const lags = { page: page ? +lag(page).toFixed(1) : null, page_pinned: !!page && page.fx != null, page_gliding: !!page && !!page.__glide,
                 chunk_mean: cs.length ? +(cs.reduce((a, n) => a + lag(n), 0) / cs.length).toFixed(1) : null,
                 chunk_gliding: cs.filter((n) => n.__glide).length, chunk_pinned: cs.filter((n) => n.fx != null).length };
  return JSON.stringify({ page: !!page, lags, mode: v.layoutMode, tele: page && v.teleStats.get(page.url), all: part(() => true), grey: part((n) => n.force && !n.projected),
                          projected: part((n) => n.projected), stored: part((n) => !n.force && !n.projected) });
})"""
try:
    for i, planted in enumerate([False, True, False, True, False, True][:int(sys.argv[1]) if len(sys.argv) > 1 else 6]):
        url = PAGES[i] + "?g245=%d" % int(time.time())      # never stored: a new page
        live.evaluate("(() => { %s.plantNoRecentre = %s; %s.plantTeleByForce = %s; return 1; })()" % (G, "true" if planted else "false", G, "true" if planted else "false"))
        g0 = live.evaluate(G + ".teleGlides")
        live.evaluate("(() => { %s.go(%s); return 1; })()" % (B, json.dumps(url)))
        t0 = time.time(); rows = []
        for at in (6, 12, 20, 35):
            time.sleep(max(0, at - (time.time() - t0)))
            m = json.loads(live.evaluate(M + "(%s)" % json.dumps(url)))
            a = m.get("all") or {}
            rows.append({"t_s": at, "n": a.get("n"), "drawn": (a.get("drawn") or {}).get("ratio"), "target": (a.get("target") or {}).get("ratio"), **(m.get("lags") or {})})
        print(json.dumps({"arm": "planted" if planted else "clean", "url": url.split("/")[-1], "tele_glides": live.evaluate(G + ".teleGlides") - g0, "rows": rows}))
finally:
    live.evaluate("(() => { %s.plantNoRecentre = false; %s.plantTeleByForce = false; return 1; })()" % (G, G))
    if was and was.startswith("http"): live.evaluate("(() => { %s.go(%s); return 1; })()" % (B, json.dumps(was)))
    live.evaluate("(()=>{window.__vertiscopeReaderAt = %s; return 1})()" % json.dumps(stamp))
