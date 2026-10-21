"""What holds the renderer's main thread while a page streams: a sampling
CPU profile for `secs`, top functions by SELF time and by inclusive time
(each function counted once per stack). The long tasks D-40 meets on the
Julia forum are mostly outside the suspects `profile_drain_frames.py` wraps.

  python scripts/cpu_profile_top.py [url] [--secs=40]

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
PAGE = next((a for a in sys.argv[1:] if a.startswith("http")), "https://discourse.julialang.org/latest")
secs = int(next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--secs=")), "40"))
PLANT = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--plant=")), "")
GV = "app.workspace.getLeavesOfType('vertiscope-graph-view')[0].view"
if PLANT:
    live.evaluate("(() => { %s[%s] = true; return 1; })()" % (GV, json.dumps(PLANT)))
tele0 = live.evaluate("JSON.stringify([%s.teleRan, %s.teleSkipped])" % (GV, GV))
try:
    live._cdp("Profiler.enable")
    live._cdp("Profiler.setSamplingInterval", {"interval": 500})
    live._cdp("Profiler.start")
    live.evaluate("(() => { app.workspace.getLeavesOfType('vertiscope-browser-view')[0].view.go(%s); return 1; })()"
                  % json.dumps(PAGE + ("&" if "?" in PAGE else "?") + "cpt=%d" % int(time.time() * 1000)))
    # the reader's scroll, as D-40 does it: wheel steps through the feed
    t0 = time.time()
    time.sleep(8)
    while time.time() - t0 < secs:
        live.evaluate("(() => { const w = app.workspace.getLeavesOfType('vertiscope-browser-view')[0].view.webview; "
                      "w.sendInputEvent({ type: 'mouseWheel', x: 300, y: 300, deltaX: 0, deltaY: -500 }); "
                      "w.sendInputEvent({ type: 'mouseMove', x: 200 + Math.random() * 300, y: 200 + Math.random() * 300 }); return 1; })()")
        time.sleep(0.3)
    prof = live._cdp("Profiler.stop")["profile"]
finally:
    tele1 = live.evaluate("JSON.stringify([%s.teleRan, %s.teleSkipped])" % (GV, GV))
    if PLANT:
        live.evaluate("(() => { %s[%s] = false; return 1; })()" % (GV, json.dumps(PLANT)))
    if was and was.startswith("http"):
        live.evaluate("(() => { app.workspace.getLeavesOfType('vertiscope-browser-view')[0].view.go(%s); return 1; })()" % json.dumps(was))
    live.evaluate("(()=>{window.__vertiscopeReaderAt = %s; return 1})()" % json.dumps(stamp))

nodes = {n["id"]: n for n in prof["nodes"]}
self_ms = defaultdict(float)
for sid, d in zip(prof["samples"], prof["timeDeltas"]):
    self_ms[sid] += d / 1000.0
parent = {c: n["id"] for n in prof["nodes"] for c in n.get("children", [])}
name = lambda n: "%s (%s:%d)" % (n["callFrame"]["functionName"] or "(anon)", n["callFrame"]["url"].rsplit("/", 1)[-1][:28], n["callFrame"]["lineNumber"] + 1)
by_self, by_incl = defaultdict(float), defaultdict(float)
for i, ms in self_ms.items():
    by_self[name(nodes[i])] += ms
    seen, j = set(), i
    while j is not None:
        k = name(nodes[j])
        if k not in seen:
            by_incl[k] += ms; seen.add(k)
        j = parent.get(j)
total = sum(self_ms.values())
idle = sum(v for k, v in by_self.items() if k.startswith(("(idle)", "(program)", "(garbage")))
print("profile %.1f s; busy %.0f ms (idle/program/gc %.0f)" % (total / 1000, total - idle, idle))
t0_, t1_ = json.loads(tele0), json.loads(tele1)
print("planted:", PLANT or "none", "| telescope passes run %d, skipped %d" % (t1_[0] - t0_[0], t1_[1] - t0_[1]))
print("relaxCloud self %.0f ms" % sum(v for k, v in by_self.items() if k.startswith("relaxCloud")))
print("self:")
for k, v in sorted(by_self.items(), key=lambda kv: -kv[1])[:22]:
    print("  %7.0f  %s" % (v, k))
print("inclusive (the plugin only):")
for k, v in sorted(((k, v) for k, v in by_incl.items() if "plugin:" in k), key=lambda kv: -kv[1])[:30]:
    print("  %7.0f  %s" % (v, k))

WHO = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--who=")), "relaxCloud")
chains = defaultdict(float)
for i, ms in self_ms.items():
    j, stack = i, []
    while j is not None:
        stack.append(nodes[j]["callFrame"]["functionName"] or "(anon)")
        j = parent.get(j)
    if WHO in stack:
        k = stack.index(WHO)
        chains[" <- ".join(stack[k:k + 7])] += ms
print("callers of %s (self+below, ms):" % WHO)
for k, v in sorted(chains.items(), key=lambda kv: -kv[1])[:12]:
    print("  %7.0f  %s" % (v, k))

# The LONG TASKS themselves: consecutive busy samples (anything but idle),
# each with the plugin functions that took most of it (inclusive, once per
# stack) -- what a hover's outline waits behind.
def stack_of(i):
    out, j = [], i
    while j is not None:
        out.append(name(nodes[j])); j = parent.get(j)
    return out
tasks, cur, t = [], None, 0.0
for sid, d in zip(prof["samples"], prof["timeDeltas"]):
    t += d / 1000.0
    nm = name(nodes[sid])
    if nm.startswith("(idle)"):
        if cur: tasks.append(cur); cur = None
        continue
    if cur is None: cur = {"t0": t, "ms": 0.0, "by": defaultdict(float)}
    cur["ms"] += d / 1000.0
    for k in set(stack_of(sid)):
        if "plugin:" in k or k.startswith(("(program)", "(garbage", "invoke", "sync ", "compose")):
            cur["by"][k] += d / 1000.0
if cur: tasks.append(cur)
long = [x for x in tasks if x["ms"] >= 50]
print("tasks >= 50 ms: %d, %.0f ms total; >= 150 ms: %d" % (len(long), sum(x["ms"] for x in long), sum(1 for x in long if x["ms"] >= 150)))
agg = defaultdict(float)
for x in long:
    for k, v in x["by"].items(): agg[k] += v
print("inside long tasks (inclusive):")
for k, v in sorted(agg.items(), key=lambda kv: -kv[1])[:25]:
    print("  %7.0f  %s" % (v, k))

import re as _re
GREP = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--grep=")), "")
if GREP:
    print("inclusive matching /%s/:" % GREP)
    for k, v in sorted(((k, v) for k, v in by_incl.items() if _re.search(GREP, k)), key=lambda kv: -kv[1])[:30]:
        print("  %7.0f  (self %5.0f)  %s" % (v, by_self.get(k, 0), k))
