"""G-233 (PLUGIN_GOAL 162), as the reader met it: hovering a code sample on a
docs page opened a panel holding a FRAGMENT of it (highlighting spans split
over two chunks; the copy button its own chunk reading "button").

The transformers quicktour, fresh per arm; the REAL pointer (`sendInputEvent`)
moved onto a highlighted span in the middle of up to six visible <pre> blocks;
the panel that opens is scored: does it hold the block's FIRST and LAST code
lines (the whole block), and is it more than a button. Clean vs planted
(`codespans` -- the sensor cuts code into spans -- and `ForceTree.
plantCodeAsText` -- the unit search ignores the code block). Reader-idle
gated; plugin reloaded first; the reader's page and panel mode restored.
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
START = next((a for a in sys.argv[1:] if a.startswith("http")), "https://huggingface.co/docs/transformers/quicktour")
JS = r"""(async (planted, start) => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
  const b = app.workspace.getLeavesOfType("vertiscope-browser-view")[0].view;
  const mode = v.panelsOn; v.panelsOn = "flyto";
  const FT = window.__vertiscopeForceTree;
  if (planted) { b.plant.add("codespans"); if (FT) FT.plantCodeAsText = true; }
  try {
    const url = start + (start.includes("?") ? "&" : "?") + "g233h=" + Date.now();
    b.go(url); for (let i = 0; i < 60 && !(b.webview.getURL() || "").includes("g233h="); i++) await sleep(500);
    await sleep(8000);
    const FIND = `(function(){
      var out = [];
      document.querySelectorAll('pre').forEach(function (p) {
        var lines = (p.innerText || '').split(String.fromCharCode(10)).map(function (s) { return s.trim(); }).filter(function (s) { return s.length > 3; });
        var spans = p.querySelectorAll('span'); if (lines.length < 2 || spans.length < 3) return;
        var s = spans[Math.floor(spans.length / 2)], r = s.getBoundingClientRect();
        if (r.width < 2 || r.top < 60 || r.bottom > innerHeight - 20) return;
        out.push({ first: lines[0].slice(0, 40), last: lines[lines.length - 1].slice(0, 40), n: lines.length, x: r.left + r.width / 2, y: r.top + r.height / 2 });
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
                   has_first: norm(text).includes(norm(blk.first)), has_last: norm(text).includes(norm(blk.last)), chars: text.length });
      }
      b.webview.sendInputEvent({ type: "mouseWheel", x: 400, y: 400, deltaX: 0, deltaY: -450 });
      await sleep(1500);
    }
    return JSON.stringify({ planted, blocks: blocks.length, whole: res.filter((r) => r.whole).length, res });
  } finally { v.panelsOn = mode; b.plant.delete("codespans"); if (FT) FT.plantCodeAsText = false; for (const k of [...v.billboards.keys()]) v.closeBillboard(k); }
})"""
try:
    for planted in (False, True):
        print(live.evaluate(JS + "(%s, %s)" % ("true" if planted else "false", json.dumps(START)), timeout=240))
finally:
    if was and was.startswith("http"):
        live.evaluate("(() => { app.workspace.getLeavesOfType('vertiscope-browser-view')[0].view.go(%s); return 1; })()" % json.dumps(was))
    live.evaluate("(()=>{window.__vertiscopeReaderAt = %s; return 1})()" % json.dumps(stamp))
