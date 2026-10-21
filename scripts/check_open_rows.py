"""Live checks for three rows built but never checked (2026-10-18 inventory):

  G-211  the k/n fields: k SHOWN of n RETRIEVED, an edit takes effect, no
         50 cap -- n set to 120 retrieves more than 50 (if the corpus
         matches that many), k results lit
  G-209  a search's rendering glows as the default view does: each lit
         result drawn as glowing glass (`lookOf`); planted
         `plantOpaqueResults` -> opaque, no glass
  G-203  fast multi-page navigation: the grey nodes a page streamed persist
         when the reader moves on while that page settles; planted
         `drop-on-leave` -> gone at the moment of leaving

Reader-idle gated; plugin reloaded first; the reader's page restored.
"""
import json, sys, time
sys.path.insert(0, r"<home>\Documents\vertiscope")
from vertiscope.obsidian.live import Live
live = Live()
if live.evaluate("window.__vertiscope.reader.idleMs()") < 60000:
    print("aborted: reader active"); sys.exit(1)
stamp = live.evaluate("window.__vertiscopeReaderAt || 0")
was = live.evaluate("app.workspace.getLeavesOfType('vertiscope-browser-view')[0].view.webview.getURL()")
live.reload_plugin()
time.sleep(4)

SEARCH = r"""(async (planted) => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
  const sf = v.searchField;
  if (!sf) return JSON.stringify({ error: "no search field" });
  v.plantOpaqueResults = planted;
  try {
    // Results light the node that stands for them NOW: in url view a page's
    // favicon (a picture -- it stays a picture, with a glow). Unfold a page
    // whose chunks match so some results are ORBS, which G-209 is about.
    const tp = v.graph.graphData().nodes.find((n) => n.level === "page" && !n.force && String(n.url).split("#")[0] === "https://en.wikipedia.org/wiki/Trie");
    // togglePage FOLDS an unfolded page: undo it if it did.
    if (tp && !v.graph.graphData().nodes.some((n) => !n.force && n.level === "chunk" && String(n.url).split("#")[0] === "https://en.wikipedia.org/wiki/Trie")) {
      const r = await v.togglePage(tp); await sleep(2500);
      if (r && r.action === "collapse") { await v.togglePage(tp); await sleep(2500); }
    }
    // A query from the Trie article's own chunks: "trie prefix tree lookup"
    // ranks earlier probes' DuckDuckGo result pages first, all favicons.
    sf.input.value = "trie insertion deletion null links children of a node";
    sf.setTotal(120);
    await sf.run();
    for (let i = 0; i < 80 && sf.hits.length < Math.min(51, sf.matching || 51); i++) await sleep(500);
    sf.setK(30);
    // the strip scrolled to its end: all k shown
    sf.scroller.scrollLeft = sf.scroller.scrollWidth; sf.onScroll(true);
    await sleep(1200);
    const st = v.searchState || {};
    const rs = v.graph.nodeRelSize(), media = v.media();
    const lit = (st.targets || []).filter(Boolean).slice(0, st.shown || 0);
    const looks = lit.map((n) => ({ n, l: v.lookOf(n, rs, media) })).filter((x) => x.l);
    const orbs = looks.filter((x) => !x.l.picture);
    const out = { planted, query: sf.query, retrieved: sf.hits.length, shown: st.shown, matching: sf.matching,
                  k_field: sf.kInput.value, n_field: sf.nInput.value, over_50: sf.hits.length > 50,
                  lit: looks.length, orbs: orbs.length,
                  orbs_glass_glowing: orbs.filter((x) => x.l.glass && (x.l.alpha || 0) > 1).length,
                  orbs_opaque: orbs.filter((x) => x.l.translucent === false).length };
    sf.input.value = ""; await sf.run();
    return JSON.stringify(out);
  } finally { v.plantOpaqueResults = false; }
})"""

NAV = r"""(async (a, b2, planted) => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const b = app.workspace.getLeavesOfType("vertiscope-browser-view")[0].view;
  const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
  if (planted) b.plant.add("drop-on-leave"); else b.plant.delete("drop-on-leave");
  const k = (x) => String(x || "").split("#")[0];
  const greyOf = (u) => v.graph.graphData().nodes.filter((n) => n.force && !n.unit && n.level === "chunk" && k(n.url) === k(u)).length;
  try {
    b.go(a);
    let before = 0;
    for (let i = 0; i < 30; i++) { await sleep(500); before = greyOf(a); if (before >= 10) break; }
    await sleep(1500); before = greyOf(a);
    b.go(b2);
    await sleep(1200);
    const after = greyOf(a);
    return JSON.stringify({ planted, a_grey_before_leaving: before, a_grey_1s_after_leaving: after });
  } finally { b.plant.delete("drop-on-leave"); }
})"""
try:
    for planted in (False, True):
        print("G-209/G-211", live.evaluate(SEARCH + "(%s)" % ("true" if planted else "false"), timeout=120))
    for planted in (False, True):
        t = int(time.time() * 1000)
        print("G-203", live.evaluate(NAV + "(%s, %s, %s)" % (json.dumps("https://en.wikipedia.org/wiki/B-tree?nv=%d" % t),
                                                             json.dumps("https://en.wikipedia.org/wiki/Heap_(data_structure)?nv=%d" % t),
                                                             "true" if planted else "false"), timeout=120))
finally:
    if was and was.startswith("http"):
        live.evaluate("(() => { app.workspace.getLeavesOfType('vertiscope-browser-view')[0].view.go(%s); return 1; })()" % json.dumps(was))
    live.evaluate("(()=>{window.__vertiscopeReaderAt = %s; return 1})()" % json.dumps(stamp))
