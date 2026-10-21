"""G-197 live: a chunk panel shows every picture its chunk holds, and no
picture its chunk does not.

A recipe page as the reader saw it (copykat's Crumbl sugar cookies). Before:
the store's chunks of the page, counted for lines that are pictures of a
namespace URI (`![](http://www.w3.org/1999/xlink)` -- an inline SVG's
`xmlns:xlink` taken as a resource) and for lazy-load stand-ins. Then the
plugin reloaded (it caches the sensor per load; the sidecar reads
`sensor.js` per request), the page re-captured live, and the same counts
taken again, with `panelCompleteness` (the MCP tool `panel_completeness`)
run on the chunks that hold the most pictures: rendered, loaded, broken,
missing, per form.

The fix's planted arm is the sensor test (`tests/test_svg_namespaces.py`,
`plants.xmlnsurl`); here the BEFORE is the store as the old sensor wrote it.
Reader-idle gated; the reader's page restored.
"""
import json, sys, time
sys.path.insert(0, r"<home>\Documents\vertiscope")
from vertiscope.obsidian.live import Live
live = Live()
if live.evaluate("window.__vertiscope.reader.idleMs()") < 60000:
    print("aborted: reader active"); sys.exit(1)
stamp = live.evaluate("window.__vertiscopeReaderAt || 0")
was = live.evaluate("app.workspace.getLeavesOfType('vertiscope-browser-view')[0].view.webview.getURL()")
PAGE = next((a for a in sys.argv[1:] if a.startswith("http")), "https://copykat.com/crumbl-sugar-cookies/")

COUNT = r"""(async (u) => {
  const v = app.workspace.getLeavesOfType('vertiscope-graph-view')[0].view;
  const sc = v.sidecar;
  const cids = await sc.pageCids(u);
  let pics = 0, ns = 0, stand = 0; const rich = [];
  for (const c of cids) {
    const p = await v.chunkPayload(c);
    const im = ((p && p.lines) || []).map((l) => String(l.text || "")).filter((t) => /!\[[^\]]*\]\(/.test(t));
    pics += im.length;
    ns += im.filter((t) => t.includes("w3.org/1999/xlink") || t.includes("w3.org/2000/svg)")).length;
    stand += im.filter((t) => /\(data:image\/svg\+xml[^)]*%3C\/svg%3E\)/.test(t) && !/%3C(path|image|circle|rect|g)\b/i.test(t)).length;
    if (im.length) rich.push([c, im.length]);
  }
  rich.sort((a, b) => b[1] - a[1]);
  return JSON.stringify({ chunks: cids.length, picture_lines: pics, namespace_pictures: ns, lazy_standins: stand, rich: rich.slice(0, 3) });
})"""

try:
    before = json.loads(live.evaluate(COUNT + "(%s)" % json.dumps(PAGE), timeout=180))
    print("before", json.dumps(before), flush=True)
    live.reload_plugin()
    time.sleep(5)
    t = int(time.time() * 1000)
    live.evaluate("(() => { app.workspace.getLeavesOfType('vertiscope-browser-view')[0].view.go(%s); return 1; })()" % json.dumps(PAGE))
    # the capture settles: the page's stored chunk count stops moving
    last, still = -1, 0
    for i in range(60):
        time.sleep(3)
        st = live.evaluate("(async () => JSON.stringify(await app.workspace.getLeavesOfType('vertiscope-graph-view')[0].view.sidecar.pageStatus(%s)))()" % json.dumps(PAGE), timeout=30)
        n = len(live.evaluate("(async () => JSON.stringify(await app.workspace.getLeavesOfType('vertiscope-graph-view')[0].view.sidecar.pageCids(%s)))()" % json.dumps(PAGE), timeout=30) or "")
        still = still + 1 if n == last else 0
        last = n
        if i > 5 and still >= 4:
            break
    after = json.loads(live.evaluate(COUNT + "(%s)" % json.dumps(PAGE), timeout=180))
    print("after ", json.dumps(after), flush=True)
    for cid, _ in after["rich"]:
        print("panel", live.evaluate("(async () => JSON.stringify(await app.workspace.getLeavesOfType('vertiscope-graph-view')[0].view.panelCompleteness(%s, %s)))()"
                                     % (json.dumps(cid), json.dumps(PAGE)), timeout=90), flush=True)
finally:
    if was and was.startswith("http"):
        live.evaluate("(() => { app.workspace.getLeavesOfType('vertiscope-browser-view')[0].view.go(%s); return 1; })()" % json.dumps(was))
    live.evaluate("(()=>{window.__vertiscopeReaderAt = %s; return 1})()" % json.dumps(stamp))
