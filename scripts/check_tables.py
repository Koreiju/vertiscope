"""G-265 (PLUGIN_GOAL 186k, 2026-10-18: "for tables on pages ... a simple
table view (which we currently don't have rendering correctly for one of the
open wikipedia panels)"): a chunk holding a table renders it as a TABLE in its
markdown panel -- every column, a nested table its own table.

Live, Wikipedia's Trie article FRESH (its infobox holds the 3-column "Time
complexity" table inside a 2-column table): the chunk holding the infobox,
its panel opened in the MARKDOWN form, and the rendered DOM read: how many
<table>s, each one's column count, and whether "Worst case" is in a table
cell. Clean vs planted `GraphView.plantOneTableRun` (one delimiter for both
widths). Reader-idle gated; plugin reloaded first; the reader's page restored.
"""
import json, sys, time, urllib.parse, urllib.request
sys.path.insert(0, r"<home>\Documents\vertiscope")
from vertiscope.obsidian.live import Live
live = Live()
if live.evaluate("window.__vertiscope.reader.idleMs()") < 60000:
    print("aborted: reader active"); sys.exit(1)
stamp = live.evaluate("window.__vertiscopeReaderAt || 0")
was = live.evaluate("app.workspace.getLeavesOfType('vertiscope-browser-view')[0].view.webview.getURL()")
live.reload_plugin()
PAGE = next((a for a in sys.argv[1:] if a.startswith("http")), "https://en.wikipedia.org/wiki/Trie")
go = lambda u: live.evaluate("(() => { app.workspace.getLeavesOfType('vertiscope-browser-view')[0].view.go(%s); return 1; })()" % json.dumps(u))
try:
    url = PAGE + "?tb=%d" % int(time.time() * 1000)
    go(url)
    cid = None
    for _ in range(40):
        time.sleep(3)
        pm = json.load(urllib.request.urlopen("http://127.0.0.1:8788/page_map?url=" + urllib.parse.quote(url, safe=""), timeout=30))
        for c, xs in pm.get("chunks", {}).items():
            if any("/table" in x and "/td/table" in x for x in xs):
                cid = c
                break
        if cid:
            break
    ch = json.load(urllib.request.urlopen("http://127.0.0.1:8788/chunk/" + cid, timeout=30)) if cid else {"lines": []}
    rows = [l["text"] for l in ch["lines"] if l["text"].strip().startswith("|")]
    print(json.dumps({"chunk": cid, "stored_pipe_rows": len(rows), "sample": rows[:6]}))
    JS = r"""(async (cid, url, planted) => {
      const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
      const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
      v.constructor.plantOneTableRun = planted;
      try {
        for (const k of [...v.billboards.keys()]) v.closeBillboard(k);
        const node = { id: cid, url, level: "chunk", virtual: true, x: 0, y: 0, z: 0 };
        await v.openBillboard(node, false, false);
        let e = v.billboards.get(cid);
        for (let i = 0; i < 20 && !(e && e.el.querySelector(".vertiscope-bb-body")); i++) { await sleep(200); e = v.billboards.get(cid); }
        for (let i = 0; i < 10 && e.form !== "markdown"; i++) { await v.switchForm(e, "markdown"); await sleep(500); }
        for (let i = 0; i < 20 && !e.el.querySelector(".vertiscope-bb-body table"); i++) await sleep(250);
        const tables = [...e.el.querySelectorAll(".vertiscope-bb-body table")];
        const out = { planted, form: e.form, tables: tables.length,
                      cols: tables.map((t) => Math.max(...[...t.querySelectorAll("tr")].map((r) => r.children.length))),
                      worst_case_in_cell: [...e.el.querySelectorAll(".vertiscope-bb-body td, .vertiscope-bb-body th")].some((c) => /Worst case/.test(c.textContent || "")) };
        v.closeBillboard(cid);
        return JSON.stringify(out);
      } finally { v.constructor.plantOneTableRun = false; }
    })"""
    if cid:
        for planted in (False, True):
            print(live.evaluate(JS + "(%s, %s, %s)" % (json.dumps(cid), json.dumps(url), "true" if planted else "false"), timeout=60))
finally:
    if was and was.startswith("http"):
        go(was)
    live.evaluate("(()=>{window.__vertiscopeReaderAt = %s; return 1})()" % json.dumps(stamp))
