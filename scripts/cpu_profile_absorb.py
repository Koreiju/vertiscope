"""G-90 diagnosis: a sampling CPU profile of the renderer while a busy page
streams in, broken down inside `GraphView.absorb` (602 ms max per call,
2026-10-18) -- which functions under it take the time, inclusive.

  python scripts/cpu_profile_absorb.py [url] [--secs=30]

Reader-idle gated; the reader's page restored. Nothing in the app changes.
"""
import json, sys, time
from collections import defaultdict
sys.path.insert(0, r"<home>\Documents\vertiscope")
from vertiscope.obsidian.live import Live
live = Live()
if live.evaluate("window.__vertiscope.reader.idleMs()") < 60000:
    print("aborted: reader active"); sys.exit(1)
stamp = live.evaluate("window.__vertiscopeReaderAt || 0")
was = live.evaluate("app.workspace.getLeavesOfType('vertiscope-browser-view')[0].view.webview.getURL()")
PAGE = next((a for a in sys.argv[1:] if a.startswith("http")), "https://bandcamp.com/")
secs = int(next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--secs=")), "30"))
FOCUS = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--focus=")), "absorb")
try:
    live._cdp("Profiler.enable")
    live._cdp("Profiler.setSamplingInterval", {"interval": 500})
    live._cdp("Profiler.start")
    live.evaluate("(() => { app.workspace.getLeavesOfType('vertiscope-browser-view')[0].view.go(%s); return 1; })()"
                  % json.dumps(PAGE + ("&" if "?" in PAGE else "?") + "cp=%d" % int(time.time() * 1000)))
    time.sleep(secs)
    prof = live._cdp("Profiler.stop")["profile"]
finally:
    if was and was.startswith("http"):
        live.evaluate("(() => { app.workspace.getLeavesOfType('vertiscope-browser-view')[0].view.go(%s); return 1; })()" % json.dumps(was))
    live.evaluate("(()=>{window.__vertiscopeReaderAt = %s; return 1})()" % json.dumps(stamp))

nodes = {n["id"]: n for n in prof["nodes"]}
dt = defaultdict(float)
for sid, d in zip(prof["samples"], prof["timeDeltas"]):
    dt[sid] += d / 1000.0                            # ms of self time per node
parent = {}
for n in prof["nodes"]:
    for c in n.get("children", []):
        parent[c] = n["id"]
incl = {}


def inclusive(i):
    if i in incl:
        return incl[i]
    t = dt[i] + sum(inclusive(c) for c in nodes[i].get("children", []))
    incl[i] = t
    return t


for i in nodes:
    inclusive(i)
name = lambda n: "%s (%s:%d)" % (n["callFrame"]["functionName"] or "(anon)", n["callFrame"]["url"].rsplit("/", 1)[-1][:30], n["callFrame"]["lineNumber"] + 1)
roots = [i for i, n in nodes.items() if n["callFrame"]["functionName"] == FOCUS]
total_focus = sum(incl[i] for i in roots if not any(nodes[a]["callFrame"]["functionName"] == FOCUS for a in [parent.get(i)] if a))
print("profile %.1f s; %s inclusive %.0f ms over %d frames" % (sum(prof["timeDeltas"]) / 1e6, FOCUS, total_focus, len(roots)))
# descendants of the focus, by function, inclusive (counted once per stack)
agg_incl = defaultdict(float)
agg_self = defaultdict(float)


def walk(i, depth, seen):
    n = nodes[i]
    key = name(n)
    if key not in seen:
        agg_incl[key] += incl[i]
    agg_self[key] += dt[i]
    for c in n.get("children", []):
        walk(c, depth + 1, seen | {key})


for r in roots:
    walk(r, 0, set())
print("inclusive under %s:" % FOCUS)
for k, v in sorted(agg_incl.items(), key=lambda kv: -kv[1])[:25]:
    print("  %8.0f ms  %s" % (v, k))
print("self under %s:" % FOCUS)
for k, v in sorted(agg_self.items(), key=lambda kv: -kv[1])[:15]:
    print("  %8.0f ms  %s" % (v, k))
