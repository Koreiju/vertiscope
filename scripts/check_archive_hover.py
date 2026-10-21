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
sys.path.insert(0, r"<home>\Documents\vertiscope")
from vertiscope.obsidian.live import Live
live = Live()
if live.evaluate("window.__vertiscope.reader.idleMs()") < 60000:
    print("aborted: reader active"); sys.exit(1)
stamp = live.evaluate("window.__vertiscopeReaderAt || 0")
print(live.reload_plugin())  # score the loaded build
ONLY_GEN = "--only-gen" in sys.argv
ONLY_LIGHT = "--only-light" in sys.argv
ONLY_PICK = "--only-pick" in sys.argv
ONLY_LINK = "--only-link" in sys.argv     # G-242: planted __vertiscopePlantNoWrapLink only
SCROLL = int(next((a.split("=")[1] for a in sys.argv if a.startswith("--scroll=")), "14"))
START = next((a for a in sys.argv[1:] if a.startswith("http")), "https://archive.org/")
JS = r"""(async (planted, start, onlyGen, scroll, onlyLight, onlyPick, onlyLink) => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
  const b = app.workspace.getLeavesOfType("vertiscope-browser-view")[0].view;
  const mode = v.panelsOn; v.panelsOn = "flyto";  // the reader's toggle, restored below
  if (planted && onlyLink) { window.__vertiscopePlantNoWrapLink = true; } else if (planted && onlyPick) { window.__vertiscopePlantPick = true; } else if (planted && onlyLight) { /* set in the page once its sensor runs */ } else if (planted && onlyGen) { window.__vertiscopePlantGen = true; } else if (planted) { b.plant.add("ancestor-over-grey"); b.plant.add("ancestor-any-depth"); b.plant.add("whole-grey-chunk"); b.plant.add("grey-unit-by-hover-chunk"); v.plantNoVirtualPanel = true; v.plantTrustStored = true; window.__vertiscopePlantGen = true; if (b.pipebox) { b.pipebox.plantAnyDepth = true; b.pipebox.plantChunkOnlyNotify = true; } window.__vertiscopePlantNoCanon = true; }
  try {
    const url = start + (start.includes("?") ? "&" : "?") + "probe=" + Date.now();
    b.go(url); for (let i = 0; i < 60 && !(b.webview.getURL() || "").includes("probe="); i++) await sleep(500);
    await sleep(7000);
    // Planted in the page's sensor: the hover walks the light DOM (a second
    // address for every slotted element).
    if (planted && onlyLight) await b.webview.executeJavaScript("(function(){var h=window.__vertiscopeSensor; if (h && h.plants) h.plants.lightpath = true; return !!h})()");
    for (let i = 0; i < scroll; i++) { b.webview.sendInputEvent({ type: "mouseWheel", x: 400, y: 400, deltaX: 0, deltaY: -500 }); await sleep(250); }
    await sleep(4000);
    // Visible tiles: their title link's centre, found through every shadow root.
    const tiles = JSON.parse(await b.webview.executeJavaScript(`(function(){
      var out=[]; (function g(r){ r.querySelectorAll('*').forEach(function(e){ if(e.shadowRoot) g(e.shadowRoot); });
        r.querySelectorAll('a[href*="/details/"]').forEach(function(a){
          // A tile draws its title inside its OWN shadow root: read through them.
          function deep(e){ var s=''; e.childNodes.forEach(function(c){ s += c.nodeType===3 ? c.textContent : (c.nodeType===1 ? deep(c) : ''); });
            if (e.shadowRoot) s += ' ' + deep(e.shadowRoot); return s; }
          var t=deep(a).split(String.fromCharCode(10)).join(' ').split(String.fromCharCode(9)).join(' ').replace(/  +/g,' ').trim(); if (t.length<8) t=(a.getAttribute('href')||'').split('/details/')[1]||'';
          var b=a.getBoundingClientRect();
          if (t.length>5 && b.width>100 && b.top>80 && b.bottom<innerHeight-40) out.push({t:t.slice(0,60), href:(a.getAttribute('href')||'').split('?')[0].split('/details/').pop(), x:b.left+b.width/2, y:b.top+b.height/2}); }); })(document);
      return JSON.stringify(out.slice(0,12)); })()`));
    const picks = tiles.slice(0, 8);
    const res = [];
    for (const pass of [1, 2]) { if (pass === 2) await sleep(3000);
    for (const tile of picks) {
      for (const k of [...v.billboards.keys()]) v.closeBillboard(k);
      b.webview.sendInputEvent({ type: "mouseMove", x: Math.round(tile.x), y: Math.round(tile.y) });
      await sleep(400);
      b.webview.sendInputEvent({ type: "mouseMove", x: Math.round(tile.x) + 2, y: Math.round(tile.y) + 1 });
      let id = "", text = "";
      for (let i = 0; i < 40; i++) { await sleep(100); id = v.hoverBb || ""; const e = id && v.billboards.get(id); text = e ? (e.el.textContent || "") : ""; if (text.trim().length > 20) break; }
      // The tile UNDER THE POINTER now, read from the page at the moment the
      // panel is judged: the virtual list re-lays out between listing and
      // hovering, and scoring against the listed title blamed the app for
      // the page's own motion. Its /details/ id is the identity.
      const under = JSON.parse(await b.webview.executeJavaScript(`(function(){ var x=${Math.round(tile.x) + 2}, y=${Math.round(tile.y) + 1};
        var e=document.elementFromPoint(x,y); while (e && e.shadowRoot) { var d=e.shadowRoot.elementFromPoint(x,y); if (!d || d===e) break; e=d; }
        var n=e; while (n && n.tagName!=='ARTICLE') n = n.parentNode || n.host;
        if (!n) return JSON.stringify(null);
        var href=''; (function g(r){ if (href) return; var a=r.querySelector('a[href*="/details/"]'); if (a) { href=a.getAttribute('href'); return; } r.querySelectorAll('*').forEach(function(c){ if (c.shadowRoot) g(c.shadowRoot); }); })(n);
        return JSON.stringify({href: href.split('?')[0]}); })()`));
      const slug = under && under.href ? under.href.split("/details/").pop() : "";
      const words = tile.t.toLowerCase().split(/[^a-z0-9]+/).filter((w) => w.length > 3 && w !== "items" && !/^[0-9]+$/.test(w)).slice(0, 2);
      res.push({ pass, title: tile.t.slice(0, 40), panel: id.slice(-30), grey: id.startsWith("f:"),
                 has_title: slug ? text.includes(slug) || (slug === tile.href && words.every((w) => text.toLowerCase().includes(w))) : (words.length > 0 && words.every((w) => text.toLowerCase().includes(w))),
                 slug, listed_slug: tile.href,
                 survey: /Feedback Survey/i.test(text), link: !!slug && text.includes("/details/" + slug), got: text.replace(/  +/g,' ').slice(0, 260) });
    } }
    const box = (b.containerEl.querySelector(".vertiscope-pipebox") || {}).textContent || "";
    return JSON.stringify({ planted, stale_stored: v.hoverStats.stale_stored || 0, url: b.webview.getURL().slice(-50), session: b.session.slice(-50), tiles: tiles.length, res, box: box.slice(0, 80) });
  } finally { v.panelsOn = mode; window.__vertiscopePlantPick = false; b.plant.delete("ancestor-over-grey"); b.plant.delete("ancestor-any-depth"); b.plant.delete("whole-grey-chunk"); b.plant.delete("grey-unit-by-hover-chunk"); v.plantNoVirtualPanel = false; v.plantTrustStored = false; window.__vertiscopePlantGen = false; if (b.pipebox) { b.pipebox.plantAnyDepth = false; b.pipebox.plantChunkOnlyNotify = false; } window.__vertiscopePlantNoCanon = false; window.__vertiscopePlantNoWrapLink = false; for (const k of [...v.billboards.keys()]) v.closeBillboard(k); }
})"""
for planted in (False, True):
    args = ("true" if planted else "false", json.dumps(START), "true" if ONLY_GEN else "false", SCROLL, "true" if ONLY_LIGHT else "false", "true" if ONLY_PICK else "false", "true" if ONLY_LINK else "false")
    r = json.loads(live.evaluate(JS + "(%s, %s, %s, %d, %s, %s, %s)" % args))
    print(json.dumps(r))
    ok = sum(1 for x in r["res"] if x["has_title"])
    print("%s: %d/%d tiles opened their own panel; %d carried the tile's link; %d opened the survey" % ("planted" if planted else "clean", ok, len(r["res"]), sum(1 for x in r["res"] if x.get("link")), sum(1 for x in r["res"] if x["survey"])))
live.evaluate("(()=>{window.__vertiscopeReaderAt = %s; return 1})()" % json.dumps(stamp))
