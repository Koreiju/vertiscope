"""Does a flood of /page_status alone wedge the sidecar on the big store?

2026-10-19: the sidecar on build/corpus123 (100k chunks, 5.8 GB) stopped
answering within a minute of every start -- no CPU, every request thread
stuck, even `/sensor`, and the C-level stack dump could only print
"<freed thread state>". Its request log showed the plugin's pipeline box
keeping 8-9 `/page_status` requests in flight (each 0.6-3.9 s) just
before. Run with the plugin DISABLED so nothing else talks to the
sidecar: `workers` threads ask `/page_status` for one url, back to back,
for `secs`; a monitor asks `/sensor` every 2 s and reports the first
time it does not answer in 10 s.

  python scripts/sidecar_stall_repro.py [--workers=10] [--secs=120] [--url=...]
"""
import sys, threading, time, urllib.parse, urllib.request

BASE = "http://127.0.0.1:8788"
workers = int(next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--workers=")), "10"))
secs = int(next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--secs=")), "120"))
url = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--url=")), "http://127.0.0.1:8931/live_mutate.html?c8=1792395955218")
q = BASE + "/page_status?" + urllib.parse.urlencode({"url": url})
stop = time.time() + secs
lat, errs = [], [0]


def worker():
    while time.time() < stop:
        t0 = time.time()
        try:
            urllib.request.urlopen(q, timeout=30).read()
            lat.append(time.time() - t0)
        except Exception:                           # noqa: BLE001
            errs[0] += 1


ts = [threading.Thread(target=worker, daemon=True) for _ in range(workers)]
for t in ts:
    t.start()
t_start = time.time()
stalled_at = None
while time.time() < stop:
    t0 = time.time()
    try:
        urllib.request.urlopen(BASE + "/sensor", timeout=10).read()
    except Exception:                               # noqa: BLE001
        stalled_at = round(time.time() - t_start, 1)
        break
    time.sleep(2)
s = sorted(lat)
print({"workers": workers, "answered": len(s), "errors": errs[0],
       "p50_s": round(s[len(s) // 2], 2) if s else None, "max_s": round(s[-1], 2) if s else None,
       "sensor_stalled_after_s": stalled_at})
