"""PLUGIN_GOAL 186k (2026-10-18): a page's special files are drawn as their
own nodes, hung from the chunk that links them; a file's panel shows the file
and its size, and its download field ASKS before anything is fetched ("prompt
the user before applying a download on-click").

Live, on a Hugging Face file list (default: OpenJev Flash 9B's GGUF repo),
fresh: the files the store detected (`/files`), the file nodes the 3D view
drew, then a file panel opened, its `download` pressed and the prompt read,
then CANCEL pressed -- and the sidecar asked whether any download started.
Nothing is ever confirmed here. Clean vs planted `plantNoFileNodes`.
Reader-idle gated; plugin reloaded first; the reader's page restored.
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
PAGE = next((a for a in sys.argv[1:] if a.startswith("http")), "https://huggingface.co/openjev/OpenJev-Flash-9B-GGUF/tree/main")
go = lambda u: live.evaluate("(() => { app.workspace.getLeavesOfType('vertiscope-browser-view')[0].view.go(%s); return 1; })()" % json.dumps(u))
JS = r"""(async (u, planted) => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
  v.plantNoFileNodes = planted;
  v.filesLoadedAt && v.filesLoadedAt.clear();
  // Each arm starts with no file node drawn: the other arm's would count.
  for (const x of v.graph.graphData().nodes.filter((x) => x.fileRef)) v.dropUnitNode(String(x.id));
  try {
    await v.loadFiles(u);
    await sleep(500);
    const nodes = v.graph.graphData().nodes.filter((n) => n.fileRef && String(n.url).split("#")[0] === u.split("#")[0]);
    const out = { planted, file_nodes: nodes.length, kinds: [...new Set(nodes.map((n) => n.fileRef.kind))],
                  linked_to_chunk: nodes.filter((n) => v.graph.graphData().links.some((l) => (l.target?.id ?? l.target) === n.id && !String(l.source?.id ?? l.source).startsWith("page:"))).length };
    const n = nodes.find((x) => x.fileRef.ext === ".gguf") || nodes[0];
    if (!n) return JSON.stringify(out);
    await v.openBillboard(n, false, false);
    const e = v.billboards.get(n.id);
    for (let i = 0; i < 40; i++) { await sleep(250); if (/size: (?!asking)/.test(e.el.textContent || "")) break; }
    out.panel_size = ((e.el.textContent || "").match(/size: [^d]*?(?=download|$)/) || [""])[0].trim();
    const dl = e.el.querySelector(".vertiscope-file-dl");
    dl.click();
    await sleep(200);
    out.prompt = (e.el.querySelector(".vertiscope-file-ask") || {}).textContent || null;
    const cancel = [...e.el.querySelectorAll(".vertiscope-file-dl")].find((x) => x.textContent === "cancel");
    cancel && cancel.click();
    await sleep(200);
    out.after_cancel = [...e.el.querySelectorAll(".vertiscope-file-dl")].map((x) => x.textContent);
    out.href = n.fileRef.href;
    out.stats = v.fileStats;
    v.closeBillboard(n.id);
    return JSON.stringify(out);
  } finally { v.plantNoFileNodes = false; }
})"""
try:
    url = PAGE + ("&" if "?" in PAGE else "?") + "fn=%d" % int(time.time() * 1000)
    go(url)
    for _ in range(60):                             # until the store holds the page's files
        time.sleep(3)
        got = json.load(urllib.request.urlopen("http://127.0.0.1:8788/files?url=" + urllib.parse.quote(url, safe=""), timeout=20))
        if got.get("files"):
            break
    print(json.dumps({"stored_files": len(got.get("files") or []),
                      "names": sorted({f["name"] for f in got.get("files") or []})[:8]}))
    for planted in (True, False):
        r = json.loads(live.evaluate(JS + "(%s, %s)" % (json.dumps(url), "true" if planted else "false"), timeout=60))
        if r.get("href"):
            st = json.load(urllib.request.urlopen("http://127.0.0.1:8788/download_status?href=" + urllib.parse.quote(r["href"], safe=""), timeout=20))
            r["download_state_after_cancel"] = st.get("state")
        print(json.dumps(r))
finally:
    if was and was.startswith("http"):
        go(was)
    live.evaluate("(()=>{window.__vertiscopeReaderAt = %s; return 1})()" % json.dumps(stamp))
