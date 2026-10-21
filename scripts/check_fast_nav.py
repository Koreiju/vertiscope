"""G-203: fast multi-page navigation -- grey nodes streamed seconds ago on one
page persist while the next page streams, and every page's diff reaches the
store.

Three new urls (Wikipedia ignores the query, so each is a page the store has
never held), 3 s on each. Per page: the most grey (force) nodes it drew while
browsed, how many are still drawn 0.5 s and 5 s after leaving it, and how
many chunks the store holds for it 40 s later. Clean vs planted
(`drop-on-leave`, the old drop at the moment of leaving). Reader-idle gated;
the browser goes back where it was.
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

JS = r"""(async (planted, tag) => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  if (window.__vertiscope.reader.idleMs() < 60000) return JSON.stringify({ aborted: "reader active" });
  const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
  const b = app.workspace.getLeavesOfType("vertiscope-browser-view")[0].view;
  const start = b.webview.getURL();
  if (planted) b.plant.add("drop-on-leave");
  const pages = ["Suffix_tree", "Ternary_search_tree", "Judy_array"].map((p) => "https://en.wikipedia.org/wiki/" + p + "?g203=" + tag);
  const grey = (u) => v.graph.graphData().nodes.filter((n) => n.force && n.url === u && n.level !== "page").length;
  const rec = pages.map((u) => ({ url: u, peak: 0, after_05s: null, after_5s: null }));
  const watch = setInterval(() => { for (const r of rec) r.peak = Math.max(r.peak, grey(r.url)); }, 100);
  try {
    for (let i = 0; i < pages.length; i++) {
      b.go(pages[i]);
      await sleep(3000);
      if (i > 0) { const r = rec[i - 1]; setTimeout(() => { r.after_05s = grey(r.url); }, 500); setTimeout(() => { r.after_5s = grey(r.url); }, 5000); }
    }
    b.go(start);
    const last = rec[rec.length - 1];
    setTimeout(() => { last.after_05s = grey(last.url); }, 500); setTimeout(() => { last.after_5s = grey(last.url); }, 5000);
    await sleep(6000);
    return JSON.stringify({ planted, rec });
  } finally { clearInterval(watch); b.plant.delete("drop-on-leave"); }
})"""
rows = []
for planted in (False, True):
    tag = "%s%d" % ("p" if planted else "c", int(time.time()))
    r = json.loads(live.evaluate(JS + "(%s, %s)" % ("true" if planted else "false", json.dumps(tag))))
    if r.get("aborted"):
        print(r); sys.exit(1)
    time.sleep(40)
    for x in r["rec"]:
        x["stored"] = len(live.json_eval("(async()=>JSON.stringify(await app.workspace.getLeavesOfType('vertiscope-graph-view')[0].view.sidecar.pageCids(%s)))()" % json.dumps(x["url"])) or [])
    print(json.dumps(r))
    rows.append(r)
c, p = rows
kept = all(x["after_05s"] and x["after_05s"] >= 0.5 * x["peak"] for x in c["rec"] if x["peak"])
dropped = all((x["after_05s"] or 0) < 0.5 * x["peak"] for x in p["rec"] if x["peak"])
stored = all(x["stored"] > 0 for x in c["rec"])
print("G-203 %s: grey nodes kept on leaving %s (planted dropped %s); every page stored %s"
      % ("PASS" if kept and dropped and stored else "FAIL", kept, dropped, stored))
