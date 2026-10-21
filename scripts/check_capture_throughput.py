"""G-226 (PLUGIN_GOAL 155): capture throughput while archive.org streams.

A graceful restart with the arm's environment (clean, or planted
`VERTISCOPE_PLANT_ANCHOR_MATCH=1`: anchors by the two-lookup statement), the
warmup waited out, then fast archive.org visits with scrolling for ~70 s
and 40 s to settle. From the sidecar's own profile over the window: anchor
cost per row, store time, total capture time; from the plugin: the capture
queue left behind and the oldest drain still waiting. Reader-idle gated."""
import json, sys, time, urllib.request
sys.path.insert(0, r"<home>\Documents\vertiscope")
sys.path.insert(0, r"<home>\Documents\vertiscope\scripts")
from vertiscope.obsidian.live import Live
from store_offline import restart
B = "http://127.0.0.1:8788"
ENV = dict(a[6:].split("=", 1) for a in sys.argv if a.startswith("--env="))
live = Live()
if live.evaluate("window.__vertiscope.reader.idleMs()") < 60000:
    print("aborted: reader active"); sys.exit(1)
stamp = live.evaluate("window.__vertiscopeReaderAt || 0")
prof = lambda: json.load(urllib.request.urlopen(B + "/profile", timeout=60))
env = {"VERTISCOPE_PLANT_ANCHOR_MATCH": "0", "VERTISCOPE_PLANT_INDEX_REBUILD": "0", "VERTISCOPE_PLANT_NO_TRAIN_YIELD": "0"}
env.update(ENV)
t_r = time.time()
restart(env=env)
for _ in range(48):
    try:
        if any(r.get("at", 0) >= t_r for r in prof().get("warm_containment", [])):
            break
    except Exception:                               # noqa: BLE001
        pass
    time.sleep(5)
# the queue the plugin held before: drained first, so the arm starts clean
for _ in range(60):
    if live.evaluate("app.workspace.getLeavesOfType('vertiscope-browser-view')[0].view.captureQueue.length") == 0:
        break
    time.sleep(5)
t0 = time.time()
r = json.loads(live.evaluate(r"""(async () => { const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const b = app.workspace.getLeavesOfType("vertiscope-browser-view")[0].view; const tag = Date.now();
  for (const u of ["https://archive.org/?t=" + tag, "https://archive.org/search?query=jazz&t=" + tag, "https://archive.org/details/audio?t=" + tag,
                   "https://archive.org/search?query=radio+drama&t=" + tag]) {
    b.go(u); await sleep(3500);
    for (let i = 0; i < 40; i++) { b.webview.sendInputEvent({ type: "mouseWheel", x: 400, y: 400, deltaX: 0, deltaY: -500 }); await sleep(300); } }
  await sleep(40000);
  const q = b.captureQueue; const now = performance.now();
  return JSON.stringify({ left_in_queue: q.length, oldest_waiting_s: q.length ? Math.round((now - Math.min(...q.map((j) => j.queuedAt || now))) / 1000) : 0 }); })()"""))
caps = [x for x in prof().get("capture", []) if x.get("at", 0) >= t0]
anch = sum(x.get("ms_anchors", 0) for x in caps); rows = sum(x.get("anchors_incoming", 0) for x in caps)
st = sorted(x.get("store", 0) for x in caps); tot = sorted(x.get("total", 0) for x in caps)
q = lambda a, f: round(a[min(len(a) - 1, int(f * len(a)))]) if a else None
r.update({"env": ENV, "captures": len(caps), "anchors": rows, "ms_per_anchor": round(anch / max(rows, 1), 2),
          "store_ms": {"p50": q(st, .5), "p90": q(st, .9), "sum_s": round(sum(st) / 1000)},
          "capture_ms": {"p50": q(tot, .5), "p90": q(tot, .9)}})
print(json.dumps(r))
live.evaluate("(()=>{window.__vertiscopeReaderAt = %s; return 1})()" % json.dumps(stamp))
