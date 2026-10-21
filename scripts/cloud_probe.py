"""Every OPEN page's chunk cloud as drawn (read-only): overlapping pairs (the
pane's own drawnRadiusOf), chunks inside their url node's drawn radius, the
drawn sizes against the spacing, and links whose endpoints are not drawn."""
import json, sys
sys.path.insert(0, r"<home>\Documents\vertiscope")
from vertiscope.obsidian.live import Live
print(Live().evaluate(r"""(() => {
  const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
  const d = v.graph.graphData();
  const by = {};
  for (const n of d.nodes) if (!n.force && n.level !== "page" && n.url && Number.isFinite(n.x)) (by[n.url] = by[n.url] || []).push(n);
  const pages = d.nodes.filter((n) => n.level === "page" && !n.force);
  const dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y, (a.z || 0) - (b.z || 0));
  const rows = [];
  for (const [u, ns] of Object.entries(by)) {
    if (ns.length < 5) continue;
    const page = pages.find((p) => p.url === u);
    const rp = page ? v.drawnRadiusOf(page) : 0;
    let pairs = 0, worst = 0;
    for (let i = 0; i < ns.length; i++) for (let j = i + 1; j < ns.length; j++) {
      const o = v.drawnRadiusOf(ns[i]) + v.drawnRadiusOf(ns[j]) - dist(ns[i], ns[j]);
      if (o > 0) { pairs++; worst = Math.max(worst, o); }
    }
    const inside = page ? ns.filter((n) => dist(n, page) < rp + v.drawnRadiusOf(n)).length : null;
    const r = ns.map((n) => v.drawnRadiusOf(n)).sort((a, b) => a - b);
    const nn = ns.map((a) => { let m = Infinity; for (const b of ns) if (b !== a) m = Math.min(m, dist(a, b)); return m; }).sort((a, b) => a - b);
    const t = v.teleStats.get(u) || {};
    rows.push({ url: u.slice(8, 60), n: ns.length, overlapping_pairs: pairs, worst: Math.round(worst * 10) / 10,
                inside_page_node: inside, page_r: Math.round(rp * 10) / 10, r_p50: Math.round(r[r.length >> 1] * 10) / 10,
                r_max: Math.round(r[r.length - 1] * 10) / 10, nn_p50: Math.round(nn[nn.length >> 1] * 10) / 10, bound: t.bound, k: t.k });
  }
  const ids = new Set(d.nodes.map((n) => n.id));
  const end = (e) => (typeof e === "object" && e ? e.id : e);
  const dangling = d.links.filter((l) => !ids.has(end(l.source)) || !ids.has(end(l.target))).length;
  const unplaced = d.links.filter((l) => typeof l.source === "object" && typeof l.target === "object" && (!Number.isFinite(l.source.x) || !Number.isFinite(l.target.x))).length;
  return JSON.stringify({ open_pages: rows.length, rows, links: d.links.length, dangling, unplaced, room: v.roomStats,
                          collider: v.collider || null, collide_on: !!v.graph.d3Force("collide") });
})()""", timeout=30))
