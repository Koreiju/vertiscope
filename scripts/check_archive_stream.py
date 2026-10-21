"""G-216 / G-217 / G-198: archive.org scrolled fast -- is the chunk stream a
stable set of unique chunks, does it keep up, and how long from a hover to
a panel?

archive.org is opened in the browser cell and scrolled in rapid wheel steps
for 15 s (the reader's case: "scrolling over archive org still throws tons
of chunk leakage because nested shadow nodes keep mutating older data
in-place"). Sampled every 250 ms:
  * the push queue's depth and the capture backlog (does the stream keep up,
    or "pipe out"?);
  * the page's live force chunks: how many, and how many share their TEXT
    with another live chunk (leakage: one piece of content held twice);
  * per drain: added / removed / rewritten in place (`again`), and ids that
    were removed and later re-added with the same text (churn).
Then hover-to-panel: grey and stored chunks of the page hovered as the
browser hovers them (`highlightChunk`), ms until the panel shows text.
Reader-idle gated; the browser goes back where it was.
"""
import json
import sys
import time

sys.path.insert(0, r"<home>\Documents\vertiscope")
from vertiscope.obsidian.live import Live

live = Live()
if live.evaluate("window.__vertiscope.reader.idleMs()") < 60000:
    print("aborted: reader active"); sys.exit(1)
stamp = live.evaluate("window.__vertiscopeReaderAt || 0")

URL = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1].startswith("http") else "https://archive.org/search?query=radio+drama"
PLANTED = "--planted" in sys.argv
PLANT = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--plant=")), "inpage-is-new-page")
JS = r"""(async (url, planted, plantName) => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
  const b = app.workspace.getLeavesOfType("vertiscope-browser-view")[0].view;
  const start = b.webview.getURL();
  const drains = [];
  const origFD = v.forceDelta.bind(v);
  v.forceDelta = (d) => { if (d && d.url && d.url.includes("archive.org")) drains.push({ at: performance.now(), added: d.added.length,
      again: d.added.filter((a) => a.again).length, removed: d.removed.length }); return origFD(d); };
  const samples = [];
  if (planted && plantName === "drop-removed") window.__dvDropRemoved = true;
  else if (planted) b.plant.add(plantName);
  const FT = (b.forceTrees.values().next().value || {}).constructor;
  if (window.__dvDropRemoved && FT) FT.plantDropRemoved = true;
  const trees0 = new Set(b.forceTrees.keys()), ip0 = { ...b.inPageStats };
  // A fresh visit each run, so the list starts at its first page.
  url = url + (url.includes("?") ? "&" : "?") + "probe=" + Date.now();
  try {
    if (b.webview.getURL() !== url) { b.go(url); for (let i = 0; i < 60 && !(b.webview.getURL() || "").includes("archive.org"); i++) await sleep(500); await sleep(6000); }
    const live = () => { const t = b.forceTrees.get(b.session) || [...b.forceTrees.values()].find((x) => (x.url || "").includes("archive.org"));
      if (!t) return { chunks: 0, dupText: 0 };
      const held = t.held(); const byText = new Map();
      for (const h of held) { const tx = (t.linesOf(h.id) || []).join("\n"); if (!tx) continue; byText.set(tx, (byText.get(tx) || 0) + 1); }
      let dup = 0; for (const n of byText.values()) if (n > 1) dup += n - 1;
      return { chunks: held.length, dupText: dup }; };
    const t0 = performance.now();
    while (performance.now() - t0 < 15000) {
      for (let k = 0; k < 2; k++) { b.webview.sendInputEvent({ type: "mouseWheel", x: 400, y: 400, deltaX: 0, deltaY: -600 }); await sleep(125); }
      const s = live();
      samples.push({ t: Math.round(performance.now() - t0), push: b.pushQueue.length, captures: b.captureBacklog, ...s });
    }
    await sleep(3000);
    const after = live();
    // Hover to panel: grey chunks (the force tree's) and stored ones (the page's map).
    const lat = { grey: [], stored: [] };
    for (const id of [...v.billboards.keys()]) v.closeBillboard(id);
    const t = b.forceTrees.get(b.session);
    const grey = t ? t.held().map((h) => h.id).filter((id) => v.graph.graphData().nodes.some((n) => n.id === id)).slice(0, 4) : [];
    const stored = (await v.sidecar.pageCids(b.session)).filter((c) => v.graph.graphData().nodes.some((n) => String(n.id) === c)).slice(0, 4);
    for (const [kind, ids] of [["grey", grey], ["stored", stored]]) {
      for (const id of ids) {
        const t1 = performance.now();
        v.highlightChunk(id, b.session, kind === "stored" ? id : "");
        let ms = null;
        for (let i = 0; i < 80; i++) { await sleep(25); const e = v.billboards.get(id);
          if (e && (e.el.textContent || "").trim().length > 10) { ms = Math.round(performance.now() - t1); break; } }
        lat[kind].push(ms);
        v.highlightChunk("", "", ""); for (const k of [...v.billboards.keys()]) v.closeBillboard(k);
        await sleep(300);
      }
    }
    const tEnd = b.forceTrees.get(b.session);
    const greyDrawn = v.graph.graphData().nodes.filter((n) => n.force && n.url === b.session && n.level !== "page" && n.level !== "path").length;
    const trees = [...b.forceTrees.keys()].filter((u) => !trees0.has(u) && u.includes("archive.org"));
    return JSON.stringify({ samples, drains, after, lat, mode: v.panelsOn, dwell: v.hoverDwellMs, hoverStats: v.hoverStats,
                            trees: trees.length, inpage: { same_doc: b.inPageStats.same_doc - ip0.same_doc, new_page: b.inPageStats.new_page - ip0.new_page },
                            session: b.session.slice(0, 90), enqueue_merged: b.enqueueMerged,
                            grey_drawn: greyDrawn, retained: tEnd ? tEnd.retainedCount() : null, retain_stats: tEnd ? tEnd.retainStats : null });
  } finally {
    b.plant.delete(plantName);
    if (FT) FT.plantDropRemoved = false; window.__dvDropRemoved = false;
    v.forceDelta = origFD;
    if (start && start.startsWith("http") && !start.includes("archive.org")) b.go(start);
  }
})"""
r = json.loads(live.evaluate(JS + "(%s, %s, %s)" % (json.dumps(URL), "true" if PLANTED else "false", json.dumps(PLANT))))
live.evaluate("(()=>{window.__vertiscopeReaderAt = %s; return 1})()" % json.dumps(stamp))
S, D = r["samples"], r["drains"]
q = lambda xs, p: sorted(xs)[min(len(xs) - 1, int(p * len(xs)))] if xs else None
print(json.dumps({
    "drains": len(D), "added": sum(d["added"] for d in D), "again": sum(d["again"] for d in D), "removed": sum(d["removed"] for d in D),
    "push_queue_max": max((s["push"] for s in S), default=0), "capture_backlog_max": max((s["captures"] for s in S), default=0),
    "capture_backlog_end": S[-1]["captures"] if S else None,
    "live_chunks_end": r["after"]["chunks"], "dup_text_end": r["after"]["dupText"], "dup_text_max": max((s["dupText"] for s in S), default=0),
    "planted": PLANT if PLANTED else False, "enqueue_merged": r.get("enqueue_merged"),
    "grey_drawn_end": r.get("grey_drawn"), "retained_end": r.get("retained"), "retain_stats": r.get("retain_stats"), "trees": r["trees"], "inpage": r["inpage"], "session": r["session"],
    "hover_ms_grey": r["lat"]["grey"], "hover_ms_stored": r["lat"]["stored"], "mode": r["mode"], "dwell": r["dwell"], "hover": r["hoverStats"]}))
