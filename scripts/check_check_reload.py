"""G-247 (PLUGIN_GOAL 176): a bot check that reloads the page does not reset
its stream in the 3D view.

Against `fixture_gate_server.py`: the real page is visited and left to settle;
its drawn nodes (chunks and streamed nodes, not the url node) are recorded by
id. Then the url is ARMED and the cell reloaded: a DDoS-Guard-style check for
12 s, which reloads itself into the real page. The page's drawn node ids are
read DURING the check and AFTER the real page is back, as counts and as the
share of the settled ids still drawn. A reset reads as the page's nodes gone
during the check or replaced after it.

Clean vs planted `store-gates` (the check stored and streamed as the page).
Reader-idle gated; plugin reloaded first; the reader's page restored.
"""
import json, subprocess, sys, time, urllib.request
sys.path.insert(0, r"<home>\Documents\vertiscope")
from vertiscope.obsidian.live import Live
FX = "http://127.0.0.1:8793"
live = Live()
if live.evaluate("window.__vertiscope.reader.idleMs()") < 60000:
    print("aborted: reader active"); sys.exit(1)
stamp = live.evaluate("window.__vertiscopeReaderAt || 0")
B = "app.workspace.getLeavesOfType('vertiscope-browser-view')[0].view"
G = "app.workspace.getLeavesOfType('vertiscope-graph-view')[0].view"
was = live.evaluate(B + ".webview.getURL()")
if "127.0.0.1:8793" in (was or ""): was = ""
try:
    urllib.request.urlopen(FX + "/gate/hits", timeout=3).read()
except Exception:
    subprocess.Popen([sys.executable, r"<home>\Documents\vertiscope\scripts\fixture_gate_server.py"],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0))
    time.sleep(2)
live.reload_plugin()
IDS = r"""((url) => { const k = (u) => String(u || '').split('#')[0];
  const ns = %s.graph.graphData().nodes.filter((n) => n.level !== 'page' && n.level !== 'path' && k(n.url) === k(url));
  return JSON.stringify({ ids: ns.map((n) => String(n.id)), grey: ns.filter((n) => n.force && !n.projected).length,
                          check_text: ns.some((n) => /checking your browser|ddos-guard/i.test(String(n.name || ''))) }); })""" % G
hits = lambda k: json.load(urllib.request.urlopen(FX + "/gate/hits", timeout=5)).get(k) or {}
try:
    for planted in (False, True):
        k = ("rc" if not planted else "rp") + str(int(time.time()))
        url = FX + "/gate/page?d=12000&k=" + k
        live.evaluate("(() => { const b = %s; if (%s) b.plant.add('store-gates'); else b.plant.delete('store-gates'); return 1; })()"
                      % (B, "true" if planted else "false"))
        live.evaluate("(() => { %s.go(%s); return 1; })()" % (B, json.dumps(url)))
        time.sleep(25)
        before = json.loads(live.evaluate(IDS + "(%s)" % json.dumps(url)))
        urllib.request.urlopen(urllib.request.Request(FX + "/gate/arm?k=" + k, data=b"", method="POST"), timeout=5).read()
        live.evaluate("(() => { %s.webview.reload(); return 1; })()" % B)
        time.sleep(7)
        during = json.loads(live.evaluate(IDS + "(%s)" % json.dumps(url)))
        t0 = time.time()
        while hits(k).get("real", 0) < 2 and time.time() - t0 < 30: time.sleep(0.5)
        time.sleep(15)
        after = json.loads(live.evaluate(IDS + "(%s)" % json.dumps(url)))
        b = set(before["ids"])
        kept = lambda s: round(len(b & set(s["ids"])) / max(1, len(b)), 2)
        print(json.dumps({"arm": "planted" if planted else "clean", "before": len(b),
                          "during": {"n": len(during["ids"]), "kept": kept(during), "grey": during["grey"], "check_text_drawn": during["check_text"]},
                          "after": {"n": len(after["ids"]), "kept": kept(after), "grey": after["grey"], "check_text_drawn": after["check_text"]}}))
finally:
    live.evaluate("(() => { %s.plant.delete('store-gates'); return 1; })()" % B)
    if was and was.startswith("http"): live.evaluate("(() => { %s.go(%s); return 1; })()" % (B, json.dumps(was)))
    live.evaluate("(()=>{window.__vertiscopeReaderAt = %s; return 1})()" % json.dumps(stamp))
