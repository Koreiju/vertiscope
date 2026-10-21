"""A refused capture of a page already LEFT must not rescan the page shown
(2026-10-18; PLUGIN_GOAL 150/152). Fast archive.org visits with scrolling,
so late drains of left pages reach the sidecar after their settle; then the
last page is left alone for 45 s. Counted: resyncs of the shown page (each a
full drain of every chunk, captured again), refusals for left pages, and the
sidecar's own `capture_refused`. Clean vs planted (`resync-any-refusal`).
Reader-idle gated; the plugin reloaded first; the reader stamp restored.
"""
import json, sys, time
sys.path.insert(0, r"<home>\Documents\vertiscope")
from vertiscope.obsidian.live import Live
import urllib.request
live = Live()
if live.evaluate("window.__vertiscope.reader.idleMs()") < 60000:
    print("aborted: reader active"); sys.exit(1)
stamp = live.evaluate("window.__vertiscopeReaderAt || 0")
print(live.reload_plugin())

def refused_since(t0):
    d = json.load(urllib.request.urlopen("http://127.0.0.1:8788/profile", timeout=30))
    return sum(1 for r in d.get("capture_refused", []) if r.get("at", 0) >= t0)

JS = r"""(async (planted) => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const b = app.workspace.getLeavesOfType("vertiscope-browser-view")[0].view;
  if (planted) b.plant.add("resync-any-refusal");
  const r0 = b.resyncs, l0 = b.refusedLeft || 0;
  try {
    const stamp = Date.now();
    for (const u of ["https://archive.org/?p=" + stamp, "https://archive.org/search?query=jazz&p=" + stamp,
                     "https://archive.org/details/audio?p=" + stamp, "https://archive.org/search?query=radio+drama&p=" + stamp]) {
      b.go(u);
      for (let i = 0; i < 40 && !(b.webview.getURL() || "").includes("p=" + stamp) ; i++) await sleep(250);
      await sleep(3500);
      for (let i = 0; i < 12; i++) { b.webview.sendInputEvent({ type: "mouseWheel", x: 400, y: 400, deltaX: 0, deltaY: -500 }); await sleep(150); }
    }
    const atRest = b.resyncs;
    await sleep(45000);
    return JSON.stringify({ planted, resyncs: b.resyncs - r0, resyncs_at_rest: b.resyncs - atRest, refused_left: (b.refusedLeft || 0) - l0, queue: b.captureQueue.length });
  } finally { b.plant.delete("resync-any-refusal"); }
})"""
for planted in (False, True):
    t0 = time.time()
    r = json.loads(live.evaluate(JS + "(%s)" % ("true" if planted else "false")))
    r["sidecar_refused"] = refused_since(t0)
    print(json.dumps(r))
live.evaluate("(()=>{window.__vertiscopeReaderAt = %s; return 1})()" % json.dumps(stamp))
