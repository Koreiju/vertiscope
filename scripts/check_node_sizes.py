"""G-228 (PLUGIN_GOAL 157): why are some orbs huge in front of tiny result
orbs? Read-only: every drawn node's radius as the pane draws it (the app's
own `drawnRadiusOf`), grouped by kind, with the largest named and the inputs
of their size (val, fullVal, members, picture). No input sent, nothing moved.
"""
import json, sys
sys.path.insert(0, r"<home>\Documents\vertiscope")
from vertiscope.obsidian.live import Live
live = Live()
QUERY = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--search=")), "")
if QUERY and live.evaluate("window.__vertiscope.reader.idleMs()") < 60000:
    print("aborted: reader active"); sys.exit(1)
JS = r"""(async (query) => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
  const f = v.searchField, was = f ? f.input.value : "";
  let ms = 0;
  if (query && f) { const t0 = performance.now(); f.input.value = query; await f.run(); await sleep(1500); ms = Math.round(performance.now() - t0); }
  try {
  const nodes = v.graph.graphData().nodes;
  const kind = (n) => n.level === "page" ? "page" : n.force ? (n.branch ? "branch" : "grey") : n.level === "path" ? "path" : "chunk";
  const ranks = v.searchState ? v.searchState.ranks : new Map();
  const rs = v.graph.nodeRelSize();
  const rows = nodes.map((n) => ({ k: kind(n), half: v.baseLook ? v.baseLook(n, rs, v.drawnMedia).half : null, rank: ranks.has(n.id) ? ranks.get(n.id) : null, r: v.drawnRadiusOf(n), val: n.val, full: n.fullVal, members: n.members ?? n.memberCount ?? null,
    pic: !!(n.image && n.image.src), hit: ranks.has(n.id), id: String(n.id).slice(0, 70), url: String(n.url || "").slice(0, 60) }));
  const by = {};
  for (const r of rows) (by[r.k] = by[r.k] || []).push(r.r);
  const q = (a, p) => { const s = [...a].sort((x, y) => x - y); return +s[Math.min(s.length - 1, Math.floor(p * s.length))].toFixed(3); };
  const stats = Object.fromEntries(Object.entries(by).map(([k, a]) => [k, { n: a.length, p10: q(a, .1), p50: q(a, .5), p90: q(a, .9), max: q(a, 1) }]));
  const top = [...rows].sort((a, b) => b.r - a.r).slice(0, 12);
  const hits = rows.filter((r) => r.hit);
  const halves = {}; for (const r of rows) if (r.half != null) (halves[r.k + (r.hit ? "+hit" : "")] = halves[r.k + (r.hit ? "+hit" : "")] || []).push(r.half);
  const hstats = Object.fromEntries(Object.entries(halves).map(([k, a]) => [k, { n: a.length, p50: q(a, .5), p90: q(a, .9), max: q(a, 1) }]));
  // Result pages: the page orbs whose url holds a result
  const hitUrls = new Set(hits.map((h) => h.url));
  const pagesOfHits = rows.filter((r) => r.k === "page" && hitUrls.has(r.url));
  return JSON.stringify({ query, ms, relSize: rs, media: v.media(), stats, drawn_half: hstats, top, hits: hits.length,
    hit_r: hits.length ? { p50: q(hits.map((h) => h.r), .5), max: q(hits.map((h) => h.r), 1) } : null,
    hit_pages: pagesOfHits.length, hit_pages_r: pagesOfHits.length ? { p50: q(pagesOfHits.map((h) => h.r), .5), max: q(pagesOfHits.map((h) => h.r), 1) } : null,
    hit_sample: hits.slice(0, 6) });
  } finally { if (query && f) { f.input.value = was; await f.run(); } }
})"""
r = json.loads(live.evaluate(JS + "(%s)" % json.dumps(QUERY)))
print(json.dumps({k: r[k] for k in ("query", "ms", "relSize", "media", "stats", "drawn_half", "hits", "hit_r", "hit_pages", "hit_pages_r", "hit_sample")}, indent=1))
for t in r["top"]:
    print("%7.3f %-6s val=%s full=%s members=%s pic=%s %s" % (t["r"], t["k"], t.get("val"), t.get("full"), t.get("members"), t["pic"], t["id"]))
