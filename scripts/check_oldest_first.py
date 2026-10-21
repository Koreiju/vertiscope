"""G-226 (PLUGIN_GOAL 155): a scan registers its chunks oldest-first.

Three archive.org pages visited in turn, each scrolled (drains queue behind
the store), then 40 s left to settle. Every capture job is recorded --
its page, when its oldest drain was queued, when the store answered -- and
reported per page in visit order: how long its drains waited to register.
Clean (the queue serves the OLDEST job first) vs planted
`current-page-first` (the page on screen first, as before). The plugin is
reloaded first; reader-idle gated; the reader stamp restored.
"""
import json, sys, time
sys.path.insert(0, r"<home>\Documents\vertiscope")
from vertiscope.obsidian.live import Live
live = Live()
if live.evaluate("window.__vertiscope.reader.idleMs()") < 60000:
    print("aborted: reader active"); sys.exit(1)
stamp = live.evaluate("window.__vertiscopeReaderAt || 0")
live.reload_plugin()
JS = r"""(async (planted, tag) => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const b = app.workspace.getLeavesOfType("vertiscope-browser-view")[0].view;
  if (planted) b.plant.add("current-page-first");
  const log = [];
  const orig = b.captureOne.bind(b);
  b.captureOne = async (job) => { const q = job.queuedAt || performance.now(); await orig(job); log.push({ url: job.url, waited: Math.round(performance.now() - q), at: performance.now() }); };
  const pages = ["https://archive.org/search?query=jazz&o=" + tag, "https://archive.org/details/audio?o=" + tag, "https://archive.org/search?query=radio+drama&o=" + tag];
  const t0 = performance.now();
  try {
    for (const u of pages) {
      b.go(u); await sleep(3000);
      for (let i = 0; i < 16; i++) { b.webview.sendInputEvent({ type: "mouseWheel", x: 400, y: 400, deltaX: 0, deltaY: -500 }); await sleep(250); }
      await sleep(1000);
    }
    await sleep(40000);
    const key = (u) => u.split("&")[0].split("?o=")[0];
    const per = pages.map((p) => {
      const mine = log.filter((x) => x.url.includes("o=" + tag) && key(x.url) === key(p));
      const w = mine.map((x) => x.waited).sort((a, b) => a - b);
      return { page: key(p).slice(19, 60), jobs: mine.length, p50: w[w.length >> 1] ?? null, max: w[w.length - 1] ?? null,
               last_stored_s: mine.length ? +((Math.max(...mine.map((x) => x.at)) - t0) / 1000).toFixed(1) : null };
    });
    return JSON.stringify({ planted, per, left_in_queue: b.captureQueue.length });
  } finally { b.captureOne = orig; b.plant.delete("current-page-first"); }
})"""
for i, planted in enumerate((False, True, False, True)):
    print(live.evaluate(JS + "(%s, %d)" % ("true" if planted else "false", int(time.time() * 1000) + i)))
live.evaluate("(()=>{window.__vertiscopeReaderAt = %s; return 1})()" % json.dumps(stamp))
