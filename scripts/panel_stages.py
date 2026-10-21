"""Where a panel's open time goes (read-only timing; methods restored after).
Opens up to N stored chunks of the open page through the app's own
openBillboard, wrapping each stage of the panel path."""
import json, sys
sys.path.insert(0, r"<home>\Documents\vertiscope")
from vertiscope.obsidian.live import Live
N = int(sys.argv[1]) if len(sys.argv) > 1 else 6
print(Live().evaluate(r"""(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
  const b = app.workspace.getLeavesOfType("vertiscope-browser-view")[0].view;
  const U = b.session;
  const spent = {}, orig = [];
  const wrap = (o, name, tag) => { const f = o[name]; if (typeof f !== "function") return; orig.push([o, name, f]);
    o[name] = function (...a) { const t = performance.now(); const r = f.apply(this, a);
      const done = () => { (spent[tag] = spent[tag] || []).push(Math.round(performance.now() - t)); };
      if (r && typeof r.then === "function") r.then(done, done); else done(); return r; }; };
  for (const m of ["chunkPayload", "pageFormFor", "completePageSnapshot", "renderForm", "tryPageForm", "upgradeToPage"]) wrap(v, m, "graph." + m);
  wrap(v.sidecar, "savedSnapshot", "sidecar.savedSnapshot"); wrap(v.sidecar, "chunk", "sidecar.chunk");
  wrap(b, "snapshotChunk", "browser.snapshotChunk");
  const rows = [];
  try {
    const cids = (await v.sidecar.pageCids(U)).slice(0, %d);
    for (const cid of cids) {
      for (const bb of v.billboardState()) v.closeBillboard(bb.id);
      v.payloadCache.delete(cid);
      let n = v.graph.graphData().nodes.find((x) => x.id === cid);
      if (!n) { const got = await v.sidecar.place([cid]); if (got && got.nodes) v.absorb(got.nodes, got.edges); n = v.graph.graphData().nodes.find((x) => x.id === cid); }
      if (!n) continue;
      const t0 = performance.now();
      await v.openBillboard(n);
      const e = v.billboards.get(cid);
      const opened = Math.round(performance.now() - t0);
      await sleep(2500);
      rows.push({ cid: cid.slice(0, 8), open_ms: opened, first_paint: e ? e.firstPaintMs : null, page_paint: e ? e.pagePaintMs : null, form: e ? e.form : null });
      v.closeBillboard(cid);
    }
  } finally { for (const [o, n, f] of orig) o[n] = f; }
  const stat = Object.fromEntries(Object.entries(spent).map(([k, xs]) => { const s = xs.slice().sort((a, b) => a - b); return [k, { n: s.length, p50: s[s.length >> 1], max: s[s.length - 1] }]; }));
  return JSON.stringify({ url: U, rows, stages: stat });
})()""" % N, timeout=180))
