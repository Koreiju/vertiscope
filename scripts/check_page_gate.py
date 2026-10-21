"""G-249 / G-247 (PLUGIN_GOAL 176-178): a bot check or an error response is a
page STATE -- not stored, not streamed -- and a check passing does not reset
the page's stream.

Against `fixture_gate_server.py` (local, our own imitation of the shape, no
real check involved). Per arm:

 1. FIRST visit: the url is armed, so the browser cell gets the interstitial
    ("DDoS-Guard", "Checking your browser ..."), whose script reloads to the
    real page after 2 s. Then: what the STORE holds for the url (any check
    text? the real paragraphs?), and the captures' summed delta.
 2. REVISIT through the check (armed again, the cell reloaded): the captures'
    summed delta for the url -- a reset reads as the page's chunks removed
    and added again; continuity as ~nothing changed.
 3. A 502: chunks stored for that url.

Clean vs planted `store-gates` (the gate off: the state is stored as the
page, as before). Reader-idle gated; plugin reloaded first; the reader's
page restored after; reader stamp restored.
"""
import json, subprocess, sys, time, urllib.request
sys.path.insert(0, r"<home>\Documents\vertiscope")
from vertiscope.obsidian.live import Live
B, FX = "http://127.0.0.1:8788", "http://127.0.0.1:8793"
live = Live()
if live.evaluate("window.__vertiscope.reader.idleMs()") < 60000:
    print("aborted: reader active"); sys.exit(1)
stamp = live.evaluate("window.__vertiscopeReaderAt || 0")

def get(u, timeout=30):
    return json.load(urllib.request.urlopen(u, timeout=timeout))
def post(u):
    return json.load(urllib.request.urlopen(urllib.request.Request(u, data=b"", method="POST"), timeout=10))
try:
    get(FX + "/gate/hits", 3)
except Exception:
    # Detached, its own stdio: an inherited stdout held the caller's pipe open.
    subprocess.Popen([sys.executable, r"<home>\Documents\vertiscope\scripts\fixture_gate_server.py"],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0))
    time.sleep(2)
# The reader's page, read BEFORE the reload: after it the cell may show
# whatever it last loaded, and a restore to that left the reader on this
# probe's 502 fixture (2026-10-18).
was = live.evaluate("app.workspace.getLeavesOfType('vertiscope-browser-view')[0].view.webview.getURL()")
if not (was or "").startswith("http") or "127.0.0.1:8793" in (was or ""):
    was = ""
live.reload_plugin()

def stored_text(url):
    cids = get(B + "/page_status?cids=1&url=" + urllib.request.quote(url, safe="")).get("cids") or []
    text = []
    for c in cids:
        try:
            p = get(B + "/chunk/" + c)
            text += [str(l.get("text", "")) for l in (p.get("lines") or [])] or [str(p.get("markdown", ""))]
        except Exception:
            pass
    return cids, text
def deltas(url, since):
    caps = [x for x in get(B + "/profile", 60).get("capture", [])
            if x.get("at", 0) >= since and str(x.get("url", "")) == url]
    d = {k: sum((x.get("delta") or {}).get(k, 0) for x in caps) for k in ("added", "changed", "removed")}
    d["captures"] = len(caps); d["unchanged_skipped"] = sum(x.get("unchanged_skipped", 0) for x in caps)
    return d
def until_real(k, n, limit=40):
    t0 = time.time()
    while time.time() - t0 < limit:
        if (get(FX + "/gate/hits").get(k) or {}).get("real", 0) >= n: return True
        time.sleep(0.5)
    return False
JS_GO = "(() => { const b = app.workspace.getLeavesOfType('vertiscope-browser-view')[0].view; b.go(%s); return 1; })()"
JS_RELOAD = "(() => { app.workspace.getLeavesOfType('vertiscope-browser-view')[0].view.webview.reload(); return 1; })()"
JS_PLANT = "(() => { const b = app.workspace.getLeavesOfType('vertiscope-browser-view')[0].view; if (%s) b.plant.add('store-gates'); else b.plant.delete('store-gates'); return JSON.stringify(b.gateStats); })()"

try:
    for planted in (False, True):
        k = ("p" if planted else "c") + str(int(time.time()))
        url = FX + "/gate/page?d=12000&k=" + k
        g0 = json.loads(live.evaluate(JS_PLANT % ("true" if planted else "false")))
        out = {"arm": "planted" if planted else "clean"}
        # 1. first visit, through the check
        post(FX + "/gate/arm?k=" + k); t1 = time.time()
        live.evaluate(JS_GO % json.dumps(url))
        # DURING the check (it reloads itself at 12 s): what the store holds.
        time.sleep(9)
        cids0, text0 = stored_text(url)
        out["during_check"] = {"stored_chunks": len(cids0),
                               "check_text_stored": any("Checking your browser" in t or "DDoS-Guard" in t for t in text0)}
        out["first_reached_real"] = until_real(k, 1)
        time.sleep(20)
        cids, text = stored_text(url)
        out["first"] = {"stored_chunks": len(cids), "check_text_stored": any("Checking your browser" in t or "DDoS-Guard" in t for t in text),
                        "real_text_stored": any("Paragraph 7 of the real page" in t for t in text), **deltas(url, t1)}
        # 2. revisit through the check
        post(FX + "/gate/arm?k=" + k); t2 = time.time()
        live.evaluate(JS_RELOAD)
        out["revisit_reached_real"] = until_real(k, 2)
        time.sleep(20)
        cids2, text2 = stored_text(url)
        out["revisit"] = {"stored_chunks": len(cids2), "check_text_stored": any("Checking your browser" in t for t in text2), **deltas(url, t2)}
        # 3. a 502
        bad = FX + "/gate/502?k=" + k
        live.evaluate(JS_GO % json.dumps(bad)); time.sleep(15)
        out["error_page_chunks_stored"] = len(stored_text(bad)[0])
        g1 = json.loads(live.evaluate(JS_PLANT % "false"))
        out["gated"] = {"docs": g1["docs"] - g0["docs"], "drains": g1["drains"] - g0["drains"], "last": g1["last"]}
        print(json.dumps(out))
finally:
    live.evaluate(JS_PLANT % "false")
    if was and was.startswith("http"): live.evaluate(JS_GO % json.dumps(was))
    live.evaluate("(()=>{window.__vertiscopeReaderAt = %s; return 1})()" % json.dumps(stamp))
