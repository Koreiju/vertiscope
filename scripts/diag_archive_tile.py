"""Diagnose archive.org tile hover: for each visible tile, the hovered
element address the sensor pushes, the tile's real text on the page, and
what the force tree holds at that address (every chunk, live or retained).
Reader-idle gated; the reader stamp restored."""
import json, sys
sys.path.insert(0, r"<home>\Documents\vertiscope")
from vertiscope.obsidian.live import Live
live = Live()
if live.evaluate("window.__vertiscope.reader.idleMs()") < 60000:
    print("aborted: reader active"); sys.exit(1)
stamp = live.evaluate("window.__vertiscopeReaderAt || 0")
if "--reload" in sys.argv: print(live.reload_plugin())
JS = r"""(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const b = app.workspace.getLeavesOfType("vertiscope-browser-view")[0].view;
  const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
  if (!(b.webview.getURL() || "").startsWith("https://archive.org/")) {
    b.go("https://archive.org/?probe=" + Date.now()); await sleep(9000);
    for (let i = 0; i < 10; i++) { b.webview.sendInputEvent({ type: "mouseWheel", x: 400, y: 400, deltaX: 0, deltaY: -400 }); await sleep(300); }
    await sleep(5000);
  }
  const tiles = JSON.parse(await b.webview.executeJavaScript(`(function(){ try {
    var out=[]; (function g(r){ r.querySelectorAll('*').forEach(function(e){ if(e.shadowRoot) g(e.shadowRoot); });
      r.querySelectorAll('a[href*="/details/"]').forEach(function(a){
        function deep(e){ var s=''; e.childNodes.forEach(function(c){ s += c.nodeType===3 ? c.textContent : (c.nodeType===1 ? deep(c) : ''); });
          if (e.shadowRoot) s += ' ' + deep(e.shadowRoot); return s; }
        var t=deep(a).split(String.fromCharCode(10)).join(' ').split(String.fromCharCode(9)).join(' ').replace(/  +/g,' ').trim(); var bb=a.getBoundingClientRect();
        if (t.length>5 && bb.width>100 && bb.top>80 && bb.bottom<innerHeight-40) out.push({t:t.slice(0,50), x:bb.left+bb.width/2, y:bb.top+bb.height/2}); }); })(document);
    return JSON.stringify(out.slice(0,4)); } catch (e) { return JSON.stringify([{err: String(e)}]); } })()`));
  if (tiles[0] && tiles[0].err) return JSON.stringify(tiles);
  const tree = b.forceTrees.get(b.session) || [...b.forceTrees.values()].pop();
  const out = [];
  for (const tile of tiles) {
    b.webview.sendInputEvent({ type: "mouseMove", x: Math.round(tile.x), y: Math.round(tile.y) });
    await sleep(500);
    const at = JSON.parse(await b.webview.executeJavaScript(`(function(){ var e=document.elementFromPoint(${Math.round(tile.x)},${Math.round(tile.y)}); while (e && e.shadowRoot) { var d=e.shadowRoot.elementFromPoint(${Math.round(tile.x)},${Math.round(tile.y)}); if (!d || d===e) break; e=d; }
      var arts=[], n=e; while (n) { if (n.tagName==='ARTICLE') { var i=1, s=n.previousElementSibling; while (s) { if (s.tagName==='ARTICLE') i++; s=s.previousElementSibling; } arts.push(i); } n = n.parentNode || n.host; }
      return JSON.stringify({tag: e && e.tagName, arts: arts}); })()`));
    const h = b.pipebox && b.pipebox.hover || {};
    const el = String(h.xpath || "");
    const hits = [];
    const cfe0 = tree && tree.chunkForElement ? tree.chunkForElement(el) : null;
    const canon = (x) => String(x || "").replace(/\/#shadow-root\/slot(\[\d+\])?(?=\/|$)/g, "");
    const art = (canon(el).match(/^.*article\[\d+\]/) || [""])[0];
    const look = (id, hd, kind) => { if (!hd || !hd.addrs || !art) return; hd.addrs.forEach((a, i) => { const c = canon(a); if (c === art || c.startsWith(art + "/")) hits.push({ kind, id: id.slice(-6), t: String((hd.text||[])[i]||"").slice(0, 50) }); }); };
    if (tree) { for (const hd of tree.chunks.values()) look(hd.id, hd, "live"); for (const [id, hd] of tree.retained) look(id, hd, "kept"); }
    const cfe = tree && tree.chunkForElement ? tree.chunkForElement(el) : null;
    out.push({ page: at, tile: tile.t, cid: h.cid, stored: h.stored, el: el, cfe, hovered: v.hoverBb, hits: hits.slice(0, 80) });
  }
  return JSON.stringify({ url: b.webview.getURL(), session: b.session, out });
})()"""
r = json.loads(live.evaluate(JS))
print(json.dumps(r))
live.evaluate("(()=>{window.__vertiscopeReaderAt = %s; return 1})()" % json.dumps(stamp))
