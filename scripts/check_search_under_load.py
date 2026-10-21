"""G-223 (PLUGIN_GOAL 152): retrieval while the store is being written --
the condition that took 73 s to a first result on 2026-10-18 (captures
waiting 44-90 s for the work lock, checkpoints 40-116 s). Fast archive.org
visits with scrolling keep captures flowing; meanwhile three searches run
through the field. Reported: each search's first and last tier time, and
the sidecar's own profile over the window (capture lock waits, render,
checkpoints, embeds). The before arm is the measurement recorded in the PRD
on the 67.8 GB store. Reader-idle gated; field restored; stamp restored."""
import json, sys, time, urllib.request
sys.path.insert(0, r"<home>\Documents\vertiscope")
from vertiscope.obsidian.live import Live
live = Live()
if live.evaluate("window.__vertiscope.reader.idleMs()") < 60000:
    print("aborted: reader active"); sys.exit(1)
stamp = live.evaluate("window.__vertiscopeReaderAt || 0")
PLANTED = "--planted" in sys.argv
ENV = dict(a[6:].split("=", 1) for a in sys.argv if a.startswith("--env="))
if "--restart" in sys.argv or PLANTED or ENV:
    sys.path.insert(0, r"<home>\Documents\vertiscope\scripts")
    from store_offline import restart
    env = {"VERTISCOPE_PLANT_INDEX_REBUILD": "1" if PLANTED else "0", "VERTISCOPE_PLANT_NO_TRAIN_YIELD": "0"}
    env.update(ENV)
    print("restart", restart(env=env))
    time.sleep(20)
t_start = time.time()
JS = r"""(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const b = app.workspace.getLeavesOfType("vertiscope-browser-view")[0].view;
  const f = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view.searchField;
  const was = { v: f.input.value, k: f.k, n: f.total };
  const tag = Date.now();
  let browsing = true;
  const browse = (async () => {
    for (const u of ["https://archive.org/?l=" + tag, "https://archive.org/search?query=jazz&l=" + tag, "https://archive.org/details/audio?l=" + tag,
                     "https://archive.org/search?query=radio+drama&l=" + tag, "https://archive.org/details/movies?l=" + tag]) {
      b.go(u); await sleep(4000);
      for (let i = 0; i < 14; i++) { b.webview.sendInputEvent({ type: "mouseWheel", x: 400, y: 400, deltaX: 0, deltaY: -500 }); await sleep(200); }
    }
    browsing = false;
  })();
  const out = [];
  try {
    await sleep(6000);
    for (const q of ["cowboy", "radio drama", "patricia trie"]) {
      f.input.value = q; f.k = 50; f.total = 200;
      const t0 = performance.now(); await f.run();
      for (let i = 0; i < 240 && f.tierStats.pages_done < f.tierStats.pages; i++) await sleep(250);
      out.push({ q, first_ms: f.tierStats.first_ms, last_ms: f.tierStats.last_ms, total_ms: Math.round(performance.now() - t0), retrieved: f.hits.length, browsing });
      await sleep(3000);
    }
    await browse;
    return JSON.stringify({ out, queue: b.captureQueue.length, retries: b.captureRetries });
  } finally { f.input.value = was.v; f.k = was.k; f.total = was.n; await f.run(); }
})()"""
r = json.loads(live.evaluate(JS))
time.sleep(20)
prof = json.load(urllib.request.urlopen("http://127.0.0.1:8788/profile", timeout=60))
def win(kind, key):
    v = [x.get(key) for x in prof.get(kind, []) if x.get("at", 0) >= t_start and x.get(key) is not None]
    return {"n": len(v), "max": max(v) if v else None, "median": sorted(v)[len(v) // 2] if v else None}
r["sidecar"] = {"capture_lock_wait_ms": win("capture", "lock_wait"), "capture_render_ms": win("capture", "render"),
                "checkpoint_ms": win("checkpoint", "ms"), "embed_lock_wait_ms": win("embed", "lock_wait_ms"),
                "project_train_ms": win("project", "ms_train")}
r["planted"] = PLANTED or ENV
print(json.dumps(r, indent=1))
live.evaluate("(()=>{window.__vertiscopeReaderAt = %s; return 1})()" % json.dumps(stamp))
