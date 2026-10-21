"""G-223 (PLUGIN_GOAL 152): search latency while the store is being written,
measured as a DISTRIBUTION, not three searches.

The three-search probe (`check_search_under_load.py`) read the field's tier
stats, which can belong to an earlier query, and started 20 s after a
restart -- inside the sidecar's own warmup (containment warm ~100 s) -- so
its arms mixed startup cost into the comparison. This one:

  * restarts with the arm's environment when asked, then WAITS for the
    warmup to finish (the profile's `warm_containment` record, or 240 s);
  * starts fast archive.org browsing in the app (captures flowing) and
    does not wait on it;
  * meanwhile asks `/search` directly every ~1.5 s with a FRESH query each
    time (no memo), for `--seconds`; reports wall-time p50 / p90 / max, the
    share of wall time spent outside the search's own phases (waiting), and
    the projector training that overlapped.

Arms: `--env=KEY=VAL` (e.g. VERTISCOPE_PLANT_NO_TRAIN_YIELD=1). Reader-idle
gated; the reader stamp restored.
"""
import json, random, sys, time, urllib.parse, urllib.request
sys.path.insert(0, r"<home>\Documents\vertiscope")
sys.path.insert(0, r"<home>\Documents\vertiscope\scripts")
from vertiscope.obsidian.live import Live

B = "http://127.0.0.1:8788"
SECONDS = int(next((a.split("=")[1] for a in sys.argv if a.startswith("--seconds=")), "90"))
ENV = dict(a[6:].split("=", 1) for a in sys.argv if a.startswith("--env="))
live = Live()
if live.evaluate("window.__vertiscope.reader.idleMs()") < 60000:
    print("aborted: reader active"); sys.exit(1)
stamp = live.evaluate("window.__vertiscopeReaderAt || 0")


def prof():
    return json.load(urllib.request.urlopen(B + "/profile", timeout=60))


if "--restart" in sys.argv or ENV:
    from store_offline import restart
    env = {"VERTISCOPE_PLANT_INDEX_REBUILD": "0", "VERTISCOPE_PLANT_NO_TRAIN_YIELD": "0"}
    env.update(ENV)
    t_r = time.time()
    print("restart", restart(env=env), json.dumps(env), flush=True)
    deadline = time.time() + 240
    while time.time() < deadline:
        try:
            if any(r.get("at", 0) >= t_r for r in prof().get("warm_containment", [])):
                break
        except Exception:                           # noqa: BLE001
            pass
        time.sleep(5)
    print("warm after %.0f s" % (time.time() - t_r), flush=True)

WORDS = ("cowboy saddle radio drama trie patricia archive jazz movie horse river "
         "library music science history engine graph vector search browser shadow "
         "node tree map page chunk west east north south old new film audio book").split()
t0 = time.time()
live.evaluate(r"""(() => { const b = app.workspace.getLeavesOfType("vertiscope-browser-view")[0].view;
  const tag = Date.now(); const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  (async () => { for (const u of ["https://archive.org/?q=" + tag, "https://archive.org/search?query=jazz&q=" + tag,
      "https://archive.org/details/audio?q=" + tag, "https://archive.org/search?query=radio+drama&q=" + tag,
      "https://archive.org/details/movies?q=" + tag, "https://archive.org/details/texts?q=" + tag]) {
    b.go(u); await sleep(4000);
    for (let i = 0; i < 14; i++) { b.webview.sendInputEvent({ type: "mouseWheel", x: 400, y: 400, deltaX: 0, deltaY: -500 }); await sleep(250); } } })();
  return 1; })()""")
rnd = random.Random(int(t0))
walls, waits = [], []
while time.time() - t0 < SECONDS:
    q = "%s %s %d" % (rnd.choice(WORDS), rnd.choice(WORDS), rnd.randrange(10 ** 6))
    t = time.perf_counter()
    try:
        d = json.load(urllib.request.urlopen(B + "/search?k=50&q=" + urllib.parse.quote(q), timeout=300))
    except Exception as exc:                        # noqa: BLE001
        print("err", exc); continue
    wall = (time.perf_counter() - t) * 1000
    inside = sum(v for k, v in (d.get("timing") or {}).items() if isinstance(v, (int, float)) and k not in ("select_reads", "memo"))
    walls.append(wall); waits.append(max(0.0, wall - inside))
    time.sleep(1.5)
walls.sort()
p = prof()
train = [r for r in p.get("project", []) if r.get("at", 0) >= t0 and "ms_train" in r]
q = lambda a, f: round(a[min(len(a) - 1, int(f * len(a)))]) if a else None
print(json.dumps({"env": ENV, "samples": len(walls), "wall_ms": {"p50": q(walls, .5), "p90": q(walls, .9), "max": q(walls, 1.0)},
                  "waiting_share": round(sum(waits) / max(1.0, sum(walls)), 2),
                  "train_runs": len(train), "train_ms_max": max([r["ms_train"] for r in train], default=None),
                  "capture_lock_wait_max": max([r.get("lock_wait", 0) for r in p.get("capture", []) if r.get("at", 0) >= t0], default=None)}))
live.evaluate("(()=>{window.__vertiscopeReaderAt = %s; return 1})()" % json.dumps(stamp))
