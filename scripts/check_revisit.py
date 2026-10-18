"""G-221 (PLUGIN_GOAL 150): going BACK to a scanned page diffs, it does not
rescan whole.

Page A visited and left to settle; page B visited; then `goBack()` to A.
The first visit and the revisit are compared: grey (streaming) nodes the
graph drew, captures sent, and -- from the sidecar's own profile -- what the
store did with A each time (chunks added / changed / skipped as unchanged,
anchors written, store ms). Reader-idle gated; the reader stamp restored.
"""
import json, sys, time, urllib.request
sys.path.insert(0, r"<home>\Documents\domvec")
from domvec.obsidian.live import Live
B = "http://127.0.0.1:8788"
live = Live()
if live.evaluate("window.__domvec.reader.idleMs()") < 60000:
    print("aborted: reader active"); sys.exit(1)
stamp = live.evaluate("window.__domvecReaderAt || 0")
A = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1].startswith("http") else "https://en.wikipedia.org/wiki/Patricia_tree"
Bp = "https://en.wikipedia.org/wiki/Radix_sort"
prof = lambda: json.load(urllib.request.urlopen(B + "/profile", timeout=60))
JS = r"""(async (url, back) => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const b = app.workspace.getLeavesOfType("domvec-browser-view")[0].view;
  const v = app.workspace.getLeavesOfType("domvec-graph-view")[0].view;
  const f0 = { added: v.forceStats.added, drains: v.forceStats.drains };
  let caps = 0; const orig = b.captureOne.bind(b);
  b.captureOne = async (job) => { if (String(job.url).split("#")[0] === url.split("#")[0]) caps++; return orig(job); };
  try {
    if (back) b.webview.goBack(); else b.go(url);
    await sleep(20000);
    return JSON.stringify({ grey_added: v.forceStats.added - f0.added, drains: v.forceStats.drains - f0.drains, captures: caps });
  } finally { b.captureOne = orig; }
})"""
def visit(url, back=False):
    t0 = time.time()
    r = json.loads(live.evaluate(JS + "(%s, %s)" % (json.dumps(url), "true" if back else "false")))
    caps = [x for x in prof().get("capture", []) if x.get("at", 0) >= t0 and str(x.get("url", "")).split("#")[0] == url]
    d = {k: sum((x.get("delta") or {}).get(k, 0) for x in caps) for k in ("added", "changed", "removed", "moved")}
    r.update({"store_captures": len(caps), "delta": d, "unchanged_skipped": sum(x.get("unchanged_skipped", 0) for x in caps),
              "anchors_written": sum(x.get("anchors_fresh", 0) for x in caps), "store_ms": round(sum(x.get("store", 0) for x in caps))})
    return r
first = visit(A)
other = visit(Bp)
again = visit(A, back=True)
print(json.dumps({"page": A, "first": first, "revisit": again}, indent=1))
live.evaluate("(()=>{window.__domvecReaderAt = %s; return 1})()" % json.dumps(stamp))
