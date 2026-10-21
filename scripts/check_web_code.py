"""G-233 (PLUGIN_GOAL 162): a web code block is ONE code artifact -- its text
whole, at the <pre> -- never its highlighting spans, never a "button" chunk.

A page with many code samples (the transformers quicktour) is opened in the
cell with a fresh query per arm, left to settle, and its STORED chunks read:
how many fenced code blocks, how many chunks are rooted BELOW a <pre> (span
fragments), how many read only "button"/"copy". Clean vs planted
`codespans` (the sensor booted with code cut into spans). Reader-idle gated;
plugin reloaded first; the reader's page restored.
"""
import json, re, sys, time, urllib.parse, urllib.request
sys.path.insert(0, r"<home>\Documents\vertiscope")
from vertiscope.obsidian.live import Live
SC = "http://127.0.0.1:8788"
live = Live()
if live.evaluate("window.__vertiscope.reader.idleMs()") < 60000:
    print("aborted: reader active"); sys.exit(1)
stamp = live.evaluate("window.__vertiscopeReaderAt || 0")
B = "app.workspace.getLeavesOfType('vertiscope-browser-view')[0].view"
was = live.evaluate(B + ".webview.getURL()")
live.reload_plugin()
BASE = sys.argv[1] if len(sys.argv) > 1 else "https://huggingface.co/docs/transformers/quicktour"
get = lambda u: json.load(urllib.request.urlopen(u, timeout=60))
try:
    for planted in (False, True):
        url = BASE + "?g233=%s%d" % ("p" if planted else "c", int(time.time()))
        live.evaluate("(() => { const b = %s; if (%s) b.plant.add('codespans'); else b.plant.delete('codespans'); return 1; })()" % (B, "true" if planted else "false"))
        live.evaluate("(() => { %s.go(%s); return 1; })()" % (B, json.dumps(url)))
        n0, t0 = -1, time.time()
        while time.time() - t0 < 150:
            time.sleep(10)
            cids = get(SC + "/page_status?cids=1&url=" + urllib.parse.quote(url, safe="")).get("cids") or []
            if cids and len(cids) == n0: break
            n0 = len(cids)
        fenced = below_pre = buttons = 0; sample = ""
        for c in cids:
            p = get(SC + "/chunk/" + c)
            xp = str(p.get("xpath", "")); text = " ".join(l.get("text", "") for l in (p.get("lines") or [])).strip()
            if re.search(r"/pre(\[\d+\])?/", xp + "/") and not xp.endswith("/pre") and not re.search(r"/pre\[\d+\]$", xp):
                below_pre += 1
            if text.lower() in ("button", "copy", "copied", "copy code"): buttons += 1
            if "```" in text or "from transformers import" in text:
                fenced += 1
                if not sample and "pipeline" in text: sample = text[:120]
        print(json.dumps({"arm": "planted" if planted else "clean", "url": url, "chunks": len(cids), "code_chunks": fenced,
                          "chunks_below_a_pre": below_pre, "button_only_chunks": buttons, "sample": sample}))
finally:
    live.evaluate("(() => { %s.plant.delete('codespans'); return 1; })()" % B)
    if was and was.startswith("http"): live.evaluate("(() => { %s.go(%s); return 1; })()" % (B, json.dumps(was)))
    live.evaluate("(()=>{window.__vertiscopeReaderAt = %s; return 1})()" % json.dumps(stamp))
