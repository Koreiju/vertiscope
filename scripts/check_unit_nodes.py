"""G-251 (PLUGIN_GOAL 180): each hovered unit -- a track row, a tile -- opens
its panel from its OWN node, grey before any vector, one level below its
chunk; not every panel from one shared node (bandcamp radio, 2026-10-18:
"hovering over different chunks renders really fast and completely ...
however each panel comes from the same node").

A page with a repeated row list (default: a bandcamp radio show), FRESH per
arm (cache-busted, so nothing is stored and every node is grey); the REAL
pointer on the image and then on the title of up to 8 visible rows. Scored
per arm: distinct panels opened, distinct ANCHORS they hang from (the node
object's id when it is a drawn graph node, else its position), whether the
anchor is in the graph, time from pointer to panel, and whether the panel
was the grey (provisional) form, and how many rows opened two different
panels for their image and their title (`rows_split`). Three arms: clean;
planted `plantSharedAnchor` (the panel hangs from a copy of its chunk's or
page's position, as before); planted `plantSubUnit` (a unit stops at its
first level with three lines -- a part of its row, as before).
Reader-idle gated; plugin reloaded first; the reader's page restored.
"""
import json, sys
sys.path.insert(0, r"<home>\Documents\vertiscope")
from vertiscope.obsidian.live import Live
live = Live()
if live.evaluate("window.__vertiscope.reader.idleMs()") < 60000:
    print("aborted: reader active"); sys.exit(1)
stamp = live.evaluate("window.__vertiscopeReaderAt || 0")
was = live.evaluate("app.workspace.getLeavesOfType('vertiscope-browser-view')[0].view.webview.getURL()")
live.reload_plugin()
START = next((a for a in sys.argv[1:] if a.startswith("http")), "https://bandcamp.com/radio?show=1010")
JS = r"""(async (planted, start) => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
  const b = app.workspace.getLeavesOfType("vertiscope-browser-view")[0].view;
  const mode = v.panelsOn; v.panelsOn = "flyto";
  const FT = window.__vertiscopeForceTree;
  v.plantSharedAnchor = planted === "anchor";
  if (planted === "subunit") { if (FT) FT.plantSubUnit = true; globalThis.__vertiscopePlantSubUnit = true; }
  try {
    const url = start + (start.includes("?") ? "&" : "?") + "g251=" + Date.now();
    b.go(url); for (let i = 0; i < 60 && !(b.webview.getURL() || "").includes("g251="); i++) await sleep(500);
    await sleep(9000);
    // Rows: siblings of one tag, each with an image and two or more text
    // lines, 40-220 px tall, four or more of them; the visible ones.
    const FIND = `(function(){
      var best = null;
      document.querySelectorAll('ul, ol, div, section, tbody').forEach(function (p) {
        var kids = Array.prototype.filter.call(p.children, function (c) {
          var r = c.getBoundingClientRect(); var t = (c.innerText || '').trim();
          return c.querySelector('img') && t.split(String.fromCharCode(10)).filter(Boolean).length >= 2 && r.height >= 40 && r.height <= 220 && r.width > 150;
        });
        if (kids.length >= 4 && (!best || kids.length > best.length)) best = kids;
      });
      if (!best) return '[]';
      return JSON.stringify(best.map(function (c) {
        var r = c.getBoundingClientRect(), im = c.querySelector('img').getBoundingClientRect();
        var t = (c.innerText || '').trim().split(String.fromCharCode(10)).filter(Boolean);
        return { title: t[0].slice(0, 40), img: [im.left + im.width / 2, im.top + im.height / 2],
                 text: [Math.min(r.right - 20, im.right + 60), r.top + Math.min(18, r.height / 3)], top: r.top, bottom: r.bottom };
      }).filter(function (x) { return x.top > 50 && x.bottom < innerHeight - 20; }).slice(0, 8));
    })()`;
    let rows = JSON.parse(await b.webview.executeJavaScript(FIND));
    if (rows.length < 3) {
      b.webview.sendInputEvent({ type: "mouseWheel", x: 400, y: 400, deltaX: 0, deltaY: -500 });
      await sleep(2500);
      rows = JSON.parse(await b.webview.executeJavaScript(FIND));
    }
    const res = [];
    for (const row of rows) {
      for (const part of ["img", "text"]) {
        for (const k of [...v.billboards.keys()]) v.closeBillboard(k);
        const [x, y] = row[part].map(Math.round);
        const t0 = performance.now();
        b.webview.sendInputEvent({ type: "mouseMove", x, y });
        await sleep(300);
        b.webview.sendInputEvent({ type: "mouseMove", x: x + 1, y: y + 1 });
        let e = null, ms = -1;
        for (let i = 0; i < 60; i++) { await sleep(100); e = v.hoverBb && v.billboards.get(v.hoverBb); if (e && (e.el.textContent || "").trim().length > 10) { ms = Math.round(performance.now() - t0); break; } }
        if (!e) { res.push({ row: row.title, part, panel: null }); continue; }
        const nodes = v.graph.graphData().nodes;
        const n = e.node;
        const inGraph = nodes.includes(n);
        res.push({ row: row.title, part, panel: String(v.hoverBb).slice(-60), ms,
                   anchor: inGraph ? "node:" + String(n.id) : "pos:" + [n.x, n.y, n.z].map((q) => Math.round(q || 0)).join(","),
                   inGraph, unit: !!n.unit, grey: !!n.force,
                   provisional: !!(e.el.querySelector(".is-provisional, .vertiscope-provisional") || /provisional/i.test(e.el.className)),
                   text: (e.el.textContent || "").replace(/\s+/g, " ").slice(0, 90) });
      }
    }
    const ok = res.filter((r) => r.panel);
    const panels = new Set(ok.map((r) => r.panel)), anchors = new Set(ok.map((r) => r.anchor));
    // Rows whose two parts opened different panels (a sub-component split).
    const split = [...new Set(ok.map((r) => r.row))].filter((t) => new Set(ok.filter((r) => r.row === t).map((r) => r.panel)).size > 1).length;
    const ms = ok.map((r) => r.ms).sort((a, b) => a - b);
    return JSON.stringify({ planted, rows: rows.length, hovers: res.length, opened: ok.length, panels: panels.size, anchors: anchors.size,
                            in_graph: ok.filter((r) => r.inGraph).length, unit_nodes: ok.filter((r) => r.unit).length,
                            rows_split: split, ms_p50: ms[Math.floor(ms.length / 2)] ?? null, ms_max: ms[ms.length - 1] ?? null,
                            unitStats: v.unitStats, res });
  } finally { v.panelsOn = mode; v.plantSharedAnchor = false; if (FT) FT.plantSubUnit = false; globalThis.__vertiscopePlantSubUnit = false; for (const k of [...v.billboards.keys()]) v.closeBillboard(k); }
})"""
try:
    for planted in ("", "anchor", "subunit"):
        print(live.evaluate(JS + "(%s, %s)" % (json.dumps(planted), json.dumps(START)), timeout=300))
finally:
    if was and was.startswith("http"):
        live.evaluate("(() => { app.workspace.getLeavesOfType('vertiscope-browser-view')[0].view.go(%s); return 1; })()" % json.dumps(was))
    live.evaluate("(()=>{window.__vertiscopeReaderAt = %s; return 1})()" % json.dumps(stamp))
