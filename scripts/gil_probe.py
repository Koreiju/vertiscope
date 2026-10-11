"""Is the sidecar's whole process stalled while the store writes? (2026-10-10:
"Significant render lag on streamed updates and saves ... a blocking issue with
data persistence versus immediate diff-based updates.") Times the cached
/health -- pure Python, no store, no model -- every 200 ms, and prints the
latency distribution beside the captures recorded meanwhile."""
import json, sys, time, urllib.request
B = "http://127.0.0.1:8788"
secs = float(sys.argv[1]) if len(sys.argv) > 1 else 60
lat, t_end = [], time.time() + secs
while time.time() < t_end:
    t = time.perf_counter()
    try:
        urllib.request.urlopen(B + "/health", timeout=30).read()
    except Exception:
        pass
    lat.append(((time.perf_counter() - t) * 1000, time.time()))
    time.sleep(0.2)
ms = sorted(x for x, _ in lat)
q = lambda p: round(ms[min(len(ms) - 1, int(p * len(ms)))], 1)
prof = json.load(urllib.request.urlopen(B + "/profile", timeout=60))
caps = [c for c in prof.get("capture", []) if c.get("at", 0) > t_end - secs]
slow = [(round(x), time.strftime("%H:%M:%S", time.localtime(a))) for x, a in lat if x > 250]
print(json.dumps({"samples": len(ms), "p50": q(.5), "p95": q(.95), "max": q(1.0), "over_250ms": len(slow),
                  "slow_at": slow[:12], "captures": [{"at": time.strftime("%H:%M:%S", time.localtime(c["at"])),
                  "store_ms": c.get("store"), "total_ms": c.get("total")} for c in caps][:12]}))
