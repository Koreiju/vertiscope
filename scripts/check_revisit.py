"""G-221 (PLUGIN_GOAL 150): going BACK to a scanned page diffs, it does not
rescan whole.

Page A visited and left to settle; page B visited; then `goBack()` to A.
The first visit and the revisit are compared: grey (streaming) nodes the
graph drew, captures sent, and -- from the sidecar's own profile -- what the
store did with A each time (chunks added / changed / skipped as unchanged,
anchors written, store ms). Reader-idle gated; the reader stamp restored.
"""
import json, sys, time, urllib.parse, urllib.request
sys.path.insert(0, r"<home>\Documents\vertiscope")
from vertiscope.obsidian.live import Live
B = "http://127.0.0.1:8788"
live = Live()
if live.evaluate("window.__vertiscope.reader.idleMs()") < 60000:
    print("aborted: reader active"); sys.exit(1)
stamp = live.evaluate("window.__vertiscopeReaderAt || 0")
A = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1].startswith("http") else "https://en.wikipedia.org/wiki/Hash_table"
Bp = "https://en.wikipedia.org/wiki/Radix_sort"
prof = lambda: json.load(urllib.request.urlopen(B + "/profile", timeout=60))
JS = r"""(async (url, back) => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const b = app.workspace.getLeavesOfType("vertiscope-browser-view")[0].view;
  const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
  const f0 = { added: v.forceStats.added, drains: v.forceStats.drains };
  let caps = 0; const orig = b.captureOne.bind(b);
  b.captureOne = async (job) => { if (String(job.url).split("#")[0] === url.split("#")[0]) caps++; return orig(job); };
  try {
    if (back) b.webview.goBack(); else b.go(url);
    // What the reader SEES: grey (streaming) nodes of this page actually
    // drawn, sampled every 0.5 s. `forceStats.added` counts every chunk a
    // drain carried, including those skipped as stored and unchanged.
    const key = (u) => String(u || "").split("#")[0];
    let greyMax = 0, greySum = 0, samples = 0;
    for (let i = 0; i < 40; i++) {
      await sleep(500);
      const g = v.graph.graphData().nodes.filter((n) => n.force && !n.projected && n.level !== "page" && key(n.url) === key(url)).length;
      greyMax = Math.max(greyMax, g); greySum += g; samples++;
    }
    return JSON.stringify({ grey_drawn_max: greyMax, grey_drawn_mean: Math.round(greySum / samples * 10) / 10,
                            drain_chunks: v.forceStats.added - f0.added, drains: v.forceStats.drains - f0.drains, captures: caps });
  } finally { b.captureOne = orig; }
})"""
def stored_n(url):
    try:
        return len(json.load(urllib.request.urlopen(B + "/page_status?cids=1&url=" + urllib.parse.quote(url, safe=""), timeout=60)).get("cids") or [])
    except Exception:
        return 0


def visit(url, back=False):
    t0 = time.time()
    r = json.loads(live.evaluate(JS + "(%s, %s)" % (json.dumps(url), "true" if back else "false")))
    if not back:
        # Not left until the store HOLDS it: a revisit before the first
        # capture landed is a page not yet stored, and rightly streams again.
        t1 = time.time(); n0 = -1
        while time.time() - t1 < 120:
            n = stored_n(url)
            if n > 0 and n == n0: break
            n0 = n; time.sleep(5)
        r["stored_before_leaving"] = stored_n(url)
    caps = [x for x in prof().get("capture", []) if x.get("at", 0) >= t0 and str(x.get("url", "")).split("#")[0] == url]
    d = {k: sum((x.get("delta") or {}).get(k, 0) for x in caps) for k in ("added", "changed", "removed", "moved")}
    r.update({"store_captures": len(caps), "delta": d, "unchanged_skipped": sum(x.get("unchanged_skipped", 0) for x in caps),
              "anchors_written": sum(x.get("anchors_fresh", 0) for x in caps), "store_ms": round(sum(x.get("store", 0) for x in caps))})
    return r
PLANT = "(() => { const b = app.workspace.getLeavesOfType('vertiscope-browser-view')[0].view; if (%s) b.plant.add('no-map-cache'); else b.plant.delete('no-map-cache'); return 1; })()"
live.reload_plugin()
for planted in (False, True, False, True):
    page = A + ("&" if "?" in A else "?") + "arm=%s%d" % ("p" if planted else "c", int(time.time()))
    live.evaluate(PLANT % ("true" if planted else "false"))
    try:
        first = visit(page)
        other = visit(Bp)
        again = visit(page, back=True)
    finally:
        live.evaluate(PLANT % "false")
    print(json.dumps({"arm": "planted" if planted else "clean", "page": page,
                      "first": {k: first.get(k) for k in ("grey_drawn_max", "store_ms", "unchanged_skipped", "stored_before_leaving")},
                      "revisit": {k: again[k] for k in ("grey_drawn_max", "grey_drawn_mean", "store_ms", "unchanged_skipped", "anchors_written")}}))
live.evaluate("(()=>{window.__vertiscopeReaderAt = %s; return 1})()" % json.dumps(stamp))
