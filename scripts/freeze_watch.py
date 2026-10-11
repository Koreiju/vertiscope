"""Rolling CPU profile of Obsidian's renderer, to catch a freeze on the stack.

15 s windows; per window the script time, heap and the top self / inclusive
frames are appended to `build_analytics/freeze_watch.log`. Read-only: the
Profiler and Performance domains over CDP, nothing evaluated in the page.
Note CDP line numbers are 0-based against the deployed `main.js`.

Usage: python scripts/freeze_watch.py <page websocket url> <minutes>
(the page target from http://127.0.0.1:9222/json/list).

Found G-145's freeze: `fitRadiiToSpacing`, all-pairs, 34 s of 35."""
import json, sys, time, collections, os
import websocket


def main() -> None:
    WS, MINUTES = sys.argv[1], float(sys.argv[2])
    LOG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "build_analytics", "freeze_watch.log")
    ws = websocket.create_connection(WS, timeout=300, suppress_origin=True)
    n = [0]
    def call(m, **p):
        n[0] += 1; i = n[0]; ws.send(json.dumps({"id": i, "method": m, "params": p}))
        while True:
            msg = json.loads(ws.recv())
            if msg.get("id") == i: return msg.get("result", msg)
    call("Performance.enable"); call("Profiler.enable"); call("Profiler.setSamplingInterval", interval=1000)
    def metrics(): return {m["name"]: m["value"] for m in call("Performance.getMetrics")["metrics"]}
    end = time.time() + MINUTES * 60
    while time.time() < end:
        a = metrics(); call("Profiler.start"); t0 = time.time(); time.sleep(15)
        prof = call("Profiler.stop")["profile"]; b = metrics(); wall = time.time() - t0
        nodes = {x["id"]: x for x in prof["nodes"]}; parent = {}
        for x in prof["nodes"]:
            for c in x.get("children", []): parent[c] = x["id"]
        dt = collections.Counter()
        for sid, d in zip(prof["samples"], prof["timeDeltas"]): dt[sid] += d
        incl = collections.Counter(); selfc = collections.Counter()
        def key(cf): return "%s:%d" % (cf["functionName"] or "(anon)", cf["lineNumber"])
        for sid, us in dt.items():
            selfc[key(nodes[sid]["callFrame"])] += us / 1000
            seen = set(); cur = sid
            while cur in nodes:
                k = key(nodes[cur]["callFrame"])
                if k not in seen: incl[k] += us / 1000; seen.add(k)
                cur = parent.get(cur)
        script = b["ScriptDuration"] - a["ScriptDuration"]
        with open(LOG, "a", encoding="utf-8") as f:
            f.write("\n== %s wall %.1fs script %.2fs heap %dMB\n" % (time.strftime("%H:%M:%S"), wall, script, b["JSHeapUsedSize"] / 1e6))
            f.write(" self: " + "; ".join("%s %.0f" % (k, v) for k, v in selfc.most_common(10)) + "\n")
            f.write(" incl: " + "; ".join("%s %.0f" % (k, v) for k, v in incl.most_common(28)) + "\n")


if __name__ == "__main__":
    main()
