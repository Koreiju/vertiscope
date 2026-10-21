"""G-248 (PLUGIN_GOAL 177): a PDF the browser cell reaches is downloaded and
chunked like a page -- kept in the workspace, its text in the store under its
own url, vectorised and drawn in the 3D view.

Clean: an arXiv PDF opened in the cell; read: the cell's own `pdfStats`, the
store's chunks for that url and whether they hold the paper's words, the
kept file, and the graph's drawn nodes for the url after placement. Planted
`no-pdf` (another PDF, so the store cannot carry the clean arm's answer): the
PDF is left to the viewer, as before. Reader-idle gated; plugin reloaded
first; the reader's page restored.
"""
import json, sys, time, urllib.parse, urllib.request
sys.path.insert(0, r"<home>\Documents\vertiscope")
from vertiscope.obsidian.live import Live
SC = "http://127.0.0.1:8788"
live = Live()
if live.evaluate("window.__vertiscope.reader.idleMs()") < 60000:
    print("aborted: reader active"); sys.exit(1)
stamp = live.evaluate("window.__vertiscopeReaderAt || 0")
B = "app.workspace.getLeavesOfType('vertiscope-browser-view')[0].view"
G = "app.workspace.getLeavesOfType('vertiscope-graph-view')[0].view"
was = live.evaluate(B + ".webview.getURL()")
live.reload_plugin()
ARMS = [(False, "https://arxiv.org/pdf/2005.14165", ["language", "few-shot"]),
        (True, "https://arxiv.org/pdf/1409.0473", ["translation", "align"])]
get = lambda u: json.load(urllib.request.urlopen(u, timeout=60))
try:
    for planted, url, words in ARMS:
        live.evaluate("(() => { const b = %s; if (%s) b.plant.add('no-pdf'); else b.plant.delete('no-pdf'); return 1; })()"
                      % (B, "true" if planted else "false"))
        s0 = json.loads(live.evaluate("JSON.stringify(%s.pdfStats)" % B))
        live.evaluate("(() => { %s.go(%s); return 1; })()" % (B, json.dumps(url)))
        t0 = time.time(); sent = False
        while time.time() - t0 < (30 if planted else 150):
            s1 = json.loads(live.evaluate("JSON.stringify(%s.pdfStats)" % B))
            if s1["sent"] > s0["sent"] or (s1["error"] and s1["error"] != s0["error"]):
                sent = s1["sent"] > s0["sent"]; break
            time.sleep(2)
        took = round(time.time() - t0, 1)
        kind = live.evaluate("(async () => { try { return await %s.webview.executeJavaScript('document.contentType'); } catch (e) { return 'err'; } })()" % B)
        time.sleep(45 if sent else 15)                # vectors, then placement
        cids = get(SC + "/page_status?cids=1&url=" + urllib.parse.quote(url, safe="")).get("cids") or []
        text = ""
        for c in cids[:40]:
            p = get(SC + "/chunk/" + c)
            text += " ".join(l.get("text", "") for l in (p.get("lines") or [])).lower() + " "
        drawn = live.evaluate("(() => { const k = (u) => String(u || '').split('#')[0]; return %s.graph.graphData().nodes.filter((n) => n.level !== 'page' && k(n.url) === k(%s)).length; })()"
                              % (G, json.dumps(url)))
        print(json.dumps({"arm": "planted" if planted else "clean", "url": url, "content_type": kind, "sent": sent, "took_s": took,
                          "stats": {k: s1.get(k) for k in ("pages", "chunks", "error", "ms", "read_ms", "store_ms", "bytes")}, "stored_chunks": len(cids),
                          "words_found": [w for w in words if w in text], "drawn_nodes": drawn}))
finally:
    live.evaluate("(() => { %s.plant.delete('no-pdf'); return 1; })()" % B)
    if was and was.startswith("http"): live.evaluate("(() => { %s.go(%s); return 1; })()" % (B, json.dumps(was)))
    live.evaluate("(()=>{window.__vertiscopeReaderAt = %s; return 1})()" % json.dumps(stamp))
