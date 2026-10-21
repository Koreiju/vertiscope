"""G-214: the idle turn starts after a few seconds and keeps turning while
the reader is away.

Watches the running pane for 90 s (no input made): every second, whether the
turn is active, and the reader-stamp tally by source (`__vertiscopeReaderBy`).
Scored: the turn on within 6 s of the last real input, active for the rest,
and no stop that a non-reader source caused. Read-only; reader-idle gated at
the start (a reader coming back mid-watch is reported, not scored).
"""
import json
import sys
import time

sys.path.insert(0, r"<home>\Documents\vertiscope")
from vertiscope.obsidian.live import Live

live = Live()
G = "app.workspace.getLeavesOfType('vertiscope-graph-view')[0].view"
idle0 = live.evaluate("window.__vertiscope.reader.idleMs()")
if idle0 < 10000:
    print("aborted: reader active"); sys.exit(1)
by0 = live.json_eval("JSON.stringify(window.__vertiscopeReaderBy || {})") or {}
st0 = live.json_eval("JSON.stringify(%s.driftStats)" % G)
samples = []
for i in range(90):
    s = live.json_eval("JSON.stringify({a: %s.driftStats.active, idle: window.__vertiscope.reader.idleMs(), turned: %s.driftStats.turned})" % (G, G))
    samples.append(s)
    time.sleep(1)
by1 = live.json_eval("JSON.stringify(window.__vertiscopeReaderBy || {})") or {}
st1 = live.json_eval("JSON.stringify(%s.driftStats)" % G)
delta = {k: by1.get(k, 0) - by0.get(k, 0) for k in set(by0) | set(by1) if by1.get(k, 0) != by0.get(k, 0)}
active = sum(1 for s in samples if s["a"])
returned = any(s["idle"] < 4000 for s in samples)
print(json.dumps({"after_ms": live.evaluate(G + ".idleDriftAfterMs"), "active_s": active, "of_s": len(samples),
                  "stops": st1["stopped"] - st0["stopped"], "turned_rad": round(st1["turned"] - st0["turned"], 2),
                  "stamps_by_source": delta, "reader_returned": returned}))
ok = not returned and active >= len(samples) - 2 and st1["stopped"] - st0["stopped"] == 0
print("G-214 %s" % ("PASS" if ok else ("NOT SCORED: the reader came back" if returned else "FAIL")))
