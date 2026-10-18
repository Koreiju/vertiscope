"""archive.org, as the reader uses it (2026-10-17: "still quite a bit of work
to do with archive" -- a tile hovered opened the search page's hidden
"Feedback Survey" container, and the corner box read "0/0 in graph").

A fresh search visit, scrolled until the list has rewritten its url, then
the REAL pointer moved over result tiles (inside their shadow roots) with
`sendInputEvent`, as a mouse arrives. Scored per tile: the panel that opens,
and whether its text holds the tile's own title. Also the corner box's line.
Reader-idle gated; the reader stamp restored; the browser left on the visit.
"""
import json, sys
sys.path.insert(0, r"<home>\Documents\domvec")
from domvec.obsidian.live import Live
live = Live()
if live.evaluate("window.__domvec.reader.idleMs()") < 60000:
    print("aborted: reader active"); sys.exit(1)
stamp = live.evaluate("window.__domvecReaderAt || 0")
JS = r"""(async (planted) => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const v = app.workspace.getLeavesOfType("domvec-graph-view")[0].view;
  const b = app.workspace.getLeavesOfType("domvec-browser-view")[0].view;
  if (planted) b.plant.add("ancestor-over-grey");
  try {
    const url = "https://archive.org/search?query=old+time+radio&probe=" + Date.now();
    b.go(url); for (let i = 0; i < 60 && !(b.webview.getURL() || "").includes("old+time+radio"); i++) await sleep(500);
    await sleep(7000);
    for (let i = 0; i < 24; i++) { b.webview.sendInputEvent({ type: "mouseWheel", x: 400, y: 400, deltaX: 0, deltaY: -500 }); await sleep(220); }
    await sleep(4000);
    // Visible tiles: their title link's centre, found through every shadow root.
    const tiles = JSON.parse(await b.webview.executeJavaScript(`(function(){
      var out=[]; (function g(r){ r.querySelectorAll('*').forEach(function(e){ if(e.shadowRoot) g(e.shadowRoot); });
        r.querySelectorAll('a[href^="/details/"]').forEach(function(a){ var t=(a.textContent||'').trim(); var b=a.getBoundingClientRect();
          if (t.length>8 && b.width>40 && b.top>80 && b.bottom<innerHeight-40) out.push({t:t.slice(0,60), x:b.left+b.width/2, y:b.top+b.height/2}); }); })(document);
      return JSON.stringify(out.slice(0,12)); })()`));
    const picks = tiles.filter((x, i) => i % 3 === 0).slice(0, 4);
    const res = [];
    for (const tile of picks) {
      for (const k of [...v.billboards.keys()]) v.closeBillboard(k);
      b.webview.sendInputEvent({ type: "mouseMove", x: Math.round(tile.x), y: Math.round(tile.y) });
      await sleep(400);
      b.webview.sendInputEvent({ type: "mouseMove", x: Math.round(tile.x) + 2, y: Math.round(tile.y) + 1 });
      let id = "", text = "";
      for (let i = 0; i < 40; i++) { await sleep(100); id = v.hoverBb || ""; const e = id && v.billboards.get(id); text = e ? (e.el.textContent || "") : ""; if (text.trim().length > 20) break; }
      const words = tile.t.toLowerCase().split(/\W+/).filter((w) => w.length > 3).slice(0, 3);
      res.push({ title: tile.t.slice(0, 40), panel: id.slice(-30), grey: id.startsWith("f:"),
                 has_title: words.length > 0 && words.every((w) => text.toLowerCase().includes(w)),
                 survey: /Feedback Survey/i.test(text) });
    }
    const box = (b.containerEl.querySelector(".domvec-pipebox") || {}).textContent || "";
    return JSON.stringify({ planted, url: b.webview.getURL().slice(-50), session: b.session.slice(-50), tiles: tiles.length, res, box: box.slice(0, 80) });
  } finally { b.plant.delete("ancestor-over-grey"); for (const k of [...v.billboards.keys()]) v.closeBillboard(k); }
})"""
for planted in (False, True):
    r = json.loads(live.evaluate(JS + "(%s)" % ("true" if planted else "false")))
    print(json.dumps(r))
    ok = sum(1 for x in r["res"] if x["has_title"])
    print("%s: %d/%d tiles opened their own panel; %d opened the survey" % ("planted" if planted else "clean", ok, len(r["res"]), sum(1 for x in r["res"] if x["survey"])))
live.evaluate("(()=>{window.__domvecReaderAt = %s; return 1})()" % json.dumps(stamp))
