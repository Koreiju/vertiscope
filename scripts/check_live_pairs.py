"""G-186: in the LIVE session's render of a page, does each line's address hold
(in the live trie) the value the line draws? Separates a trie whose values sit
under wrong addresses from a render that pairs lines wrongly."""
import sys, json, re, time, urllib.request, urllib.parse
sys.path.insert(0, r"<home>\Documents\vertiscope\scripts")
from live_probe import Probe

URL = sys.argv[1] if len(sys.argv) > 1 else "https://arxiv.org/list/stat.ML/recent"
p = Probe()
if p.ev("window.__vertiscope.reader.idleMs()") < 60000:
    print("reader active: not run"); sys.exit(0)
B = 'app.workspace.getLeavesOfType("vertiscope-browser-view")[0].view'
start = p.ev("%s.webview.getURL()" % B)
p.ev("(()=>{%s.go(%s);return 1})()" % (B, json.dumps(URL)))
try:
    time.sleep(35)
    q = urllib.parse.urlencode({"url": p.ev("%s.webview.getURL()" % B), "keys": "1"})
    got = json.load(urllib.request.urlopen("http://127.0.0.1:8788/live_render?" + q, timeout=60))
    first = lambda t: (re.findall(r"[A-Za-z]{3,}", re.sub(r"\]\([^)]*\)", "]", t or "")) or [""])[0]
    held = wrong = missing = 0
    ex = []
    for c in got.get("chunks", []):
        for text, key, value in c.get("pairs", []):
            w = first(text)
            if not w or not key or "/text()" not in key.split("|")[1]:
                continue
            if value is None:
                missing += 1
            elif w in value:
                held += 1
            else:
                wrong += 1
                if len(ex) < 6:
                    ex.append({"text": text[:50], "at": key.split("|")[1][-40:], "trie": value[:40]})
    print(json.dumps({"session": got.get("session"), "chunks": got.get("chunks_total"),
                      "held": held, "wrong": wrong, "not_in_trie": missing, "ex": ex}, indent=1))
finally:
    if start and start.startswith("http"):
        p.ev("(()=>{%s.go(%s);return 1})()" % (B, json.dumps(start)))
