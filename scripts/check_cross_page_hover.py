"""Edge case: a hover never resolves to another page's chunk (2026-10-17:
"very serious url and chunk degradation that must be fixed and tested for as
an edge case" -- a hover on TMDB opened an archive.org chunk's panel).

Between archive.org and TMDB, both directions, the REAL pointer moves over
the page continuously while it loads (`sendInputEvent`). Every hover the
graph receives and every panel it opens is recorded with the url of the
node it resolved to, against the page the browser SHOWS at that moment.
Scored: cross-page targets (a node of another page) and cross-page panels.
Clean vs planted (`session-at-load` + `cross-page-hover`: the session moved
at load end and hovers read through whatever tree the session named).
Reader-idle gated; the reader stamp restored.
"""
import json, sys
sys.path.insert(0, r"<home>\Documents\vertiscope")
from vertiscope.obsidian.live import Live
live = Live()
if live.evaluate("window.__vertiscope.reader.idleMs()") < 60000:
    print("aborted: reader active"); sys.exit(1)
stamp = live.evaluate("window.__vertiscopeReaderAt || 0")
JS = r"""(async (planted) => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
  const b = app.workspace.getLeavesOfType("vertiscope-browser-view")[0].view;
  const key = (u) => String(u || "").split("#")[0];
  if (planted) { b.plant.add("session-at-load"); b.plant.add("cross-page-hover"); }
  // Judged only AFTER the new page has committed (the session is the leg's
  // page): before that the old page is still on screen and its hovers are
  // its own. Panels judged at the moment they OPEN, by the node's page.
  // The judge must not be the code under test: a leg counts from the moment
  // the WEBVIEW reports its new document committed (its own did-navigate),
  // whatever session the app holds -- the planted fault lives in the window
  // where the session lags the document.
  let leg = "", committed = false;
  const onNav = (e) => { if (e && e.isMainFrame !== false && key(e.url) === key(leg)) committed = true; };
  b.webview.addEventListener("did-navigate", onNav);
  const seen = [], opened = [];
  const orig = v.highlightChunk.bind(v);
  v.highlightChunk = (cid, url, stored) => {
    orig(cid, url, stored);
    if (!cid || !committed) return;
    const t = v.graph.graphData().nodes.find((n) => n.hovered);
    seen.push({ target: t ? key(t.url) : "" });
  };
  const origOpen = v.openBillboard.bind(v);
  v.openBillboard = async (node, ...rest) => {
    if (committed) opened.push(key(node && node.url));
    return origOpen(node, ...rest);
  };
  const panelUrl = async (id) => { if (!id) return ""; const p = await v.chunkPayload(id).catch(() => null); return key(p && p.url); };
  const legs = [];
  try {
    for (const to of ["https://www.themoviedb.org/person/942536-gillian-welch", "https://archive.org/", "https://www.themoviedb.org/movie/134-o-brother-where-art-thou"]) {
      const from = seen.length, from2 = opened.length;
      leg = to; committed = false;
      b.go(to);
      const t0 = performance.now();
      while (performance.now() - t0 < 14000) {
        const x = 200 + Math.round(Math.random() * 500), y = 150 + Math.round(Math.random() * 500);
        b.webview.sendInputEvent({ type: "mouseMove", x, y });
        await sleep(120);
      }
      const mine = seen.slice(from), pans = opened.slice(from2);
      const cross = mine.filter((s) => s.target && s.target !== key(to));
      legs.push({ to: to.slice(8, 50), hovers: mine.length, cross_targets: cross.length,
                  panels: pans.length, cross_panels: pans.filter((u) => u && u !== key(to)).length, refused: b.hoverStats.cross_page_refused });
    }
    return JSON.stringify({ planted, legs });
  } finally {
    v.highlightChunk = orig; v.openBillboard = origOpen;
    b.webview.removeEventListener("did-navigate", onNav);
    b.plant.delete("session-at-load"); b.plant.delete("cross-page-hover");
    for (const k of [...v.billboards.keys()]) v.closeBillboard(k);
  }
})"""
for planted in (False, True):
    r = json.loads(live.evaluate(JS + "(%s)" % ("true" if planted else "false")))
    print(json.dumps(r))
    cross = sum(l["cross_targets"] + l["cross_panels"] for l in r["legs"])
    print("%s: %d cross-page targets/panels over %d hovers" % ("planted" if planted else "clean  ", cross, sum(l["hovers"] for l in r["legs"])))
live.evaluate("(()=>{window.__vertiscopeReaderAt = %s; return 1})()" % json.dumps(stamp))
