"""G-244 (PLUGIN_GOAL 173): a short prose list is ONE unit -- hovering any
bullet opens one panel holding the whole list (a github README showed three
panels at once, each with one bullet of a "Prerequisites" list).

A README, fresh per arm; the REAL pointer on the SECOND item of each short
visible list (2-8 items, each under 200 characters, no links-only grids);
the panel scored: does it hold the list's FIRST and LAST items. Clean vs
planted `plantItemAlways` (the item is the unit whatever the list's size).
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
START = next((a for a in sys.argv[1:] if a.startswith("http")), "https://github.com/psf/requests")
JS = r"""(async (planted, start) => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
  const b = app.workspace.getLeavesOfType("vertiscope-browser-view")[0].view;
  const mode = v.panelsOn; v.panelsOn = "flyto";
  const FT = window.__vertiscopeForceTree;
  const linksMode = start.includes("huggingface.co");
  if (planted && linksMode) { if (FT) FT.plantRelativeLinks = true; }
  else if (planted) { if (FT) FT.plantItemAlways = true; globalThis.__vertiscopePlantItemAlways = true; }
  try {
    const url = start + (start.includes("?") ? "&" : "?") + "g244=" + Date.now();
    b.go(url); for (let i = 0; i < 60 && !(b.webview.getURL() || "").includes("g244="); i++) await sleep(500);
    await sleep(8000);
    const FIND = `(function(){
      var out = [];
      document.querySelectorAll('ul, ol').forEach(function (l) {
        var items = Array.prototype.filter.call(l.children, function (c) { return c.tagName === 'LI'; });
        if (items.length < 2 || items.length > 8) return;
        var texts = items.map(function (li) { return (li.innerText || '').trim(); });
        if (texts.some(function (t) { return t.length < 4 || t.length > 200; })) return;
        if (l.closest('nav, header, footer')) return;
        var r = items[1].getBoundingClientRect();
        if (r.width < 20 || r.top < 60 || r.bottom > innerHeight - 20) return;
        out.push({ first: texts[0].split(String.fromCharCode(10))[0].slice(0, 40), last: texts[texts.length - 1].split(String.fromCharCode(10))[0].slice(0, 40), n: items.length, x: r.left + Math.min(40, r.width / 2), y: r.top + r.height / 2 });
      });
      return JSON.stringify(out.slice(0, 2)); })()`;
    const res = [], seen = new Set();
    let blocks = [];
    for (let step = 0; step < 16 && res.length < 6; step++) {
      const found = JSON.parse(await b.webview.executeJavaScript(FIND)).filter((x) => !seen.has(x.first + x.last));
      for (const blk of found) {
        seen.add(blk.first + blk.last); blocks.push(blk);
        for (const k of [...v.billboards.keys()]) v.closeBillboard(k);
        b.webview.sendInputEvent({ type: "mouseMove", x: Math.round(blk.x), y: Math.round(blk.y) });
        await sleep(400);
        b.webview.sendInputEvent({ type: "mouseMove", x: Math.round(blk.x) + 1, y: Math.round(blk.y) + 1 });
        let text = "";
        for (let i = 0; i < 50; i++) { await sleep(100); const e = v.hoverBb && v.billboards.get(v.hoverBb); text = e ? (e.el.textContent || "") : ""; if (text.trim().length > 15) break; }
        const norm = (s) => s.replace(/\s+/g, "");
        res.push({ lines: blk.n, whole: !!text && norm(text).includes(norm(blk.first)) && norm(text).includes(norm(blk.last)),
                   has_first: norm(text).includes(norm(blk.first)), has_last: norm(text).includes(norm(blk.last)), chars: text.length, first: blk.first, last: blk.last, panel: text.replace(/\s+/g, " ").slice(0, 160),
                   abs_links: (text.match(/https:\/\/huggingface\.co\/docs\//g) || []).length,
                   tails: (text.match(/(^|[\s>])\/docs\/[^\s]+/g) || []).length });
      }
      b.webview.sendInputEvent({ type: "mouseWheel", x: 400, y: 400, deltaX: 0, deltaY: -450 });
      await sleep(1500);
    }
    return JSON.stringify({ planted, blocks: blocks.length, whole: res.filter((r) => r.whole).length, res });
  } finally { v.panelsOn = mode; if (FT) { FT.plantItemAlways = false; FT.plantRelativeLinks = false; } globalThis.__vertiscopePlantItemAlways = false; for (const k of [...v.billboards.keys()]) v.closeBillboard(k); }
})"""
try:
    for planted in (False, True):
        print(live.evaluate(JS + "(%s, %s)" % ("true" if planted else "false", json.dumps(START)), timeout=240))
finally:
    if was and was.startswith("http"):
        live.evaluate("(() => { app.workspace.getLeavesOfType('vertiscope-browser-view')[0].view.go(%s); return 1; })()" % json.dumps(was))
    live.evaluate("(()=>{window.__vertiscopeReaderAt = %s; return 1})()" % json.dumps(stamp))
