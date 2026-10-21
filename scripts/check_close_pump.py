"""A closed browser view sends no more captures (2026-10-18). After a plugin
reload the old view's capture pump kept sending its queue -- and retrying
refusals -- beside the new view's; two sensors' drains for one url
interleaved on the sidecar's session and both were refused in a loop.

Fast archive.org visits build a queue; the view is held; the plugin is
reloaded; the closed view's capture calls are counted for 60 s, with the
sidecar's refusals. Clean vs planted (`pump-after-close`). Reader-idle gated.
"""
import json, sys, time
sys.path.insert(0, r"<home>\Documents\vertiscope")
from vertiscope.obsidian.live import Live
import urllib.request
live = Live()
if live.evaluate("window.__vertiscope.reader.idleMs()") < 60000:
    print("aborted: reader active"); sys.exit(1)
stamp = live.evaluate("window.__vertiscopeReaderAt || 0")
live.reload_plugin()          # the view under test runs the code on disk

def refused_since(t0):
    d = json.load(urllib.request.urlopen("http://127.0.0.1:8788/profile", timeout=30))
    return sum(1 for r in d.get("capture_refused", []) if r.get("at", 0) >= t0)

PREP = r"""(async (planted) => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const b = app.workspace.getLeavesOfType("vertiscope-browser-view")[0].view;
  if (planted) b.plant.add("pump-after-close");
  const tag = Date.now();
  for (const u of ["https://archive.org/?c=" + tag, "https://archive.org/search?query=jazz&c=" + tag, "https://archive.org/details/audio?c=" + tag]) {
    b.go(u); await sleep(4500);
    for (let i = 0; i < 10; i++) { b.webview.sendInputEvent({ type: "mouseWheel", x: 400, y: 400, deltaX: 0, deltaY: -500 }); await sleep(150); }
  }
  window.__closedView = b; window.__closedSends = 0;
  const orig = b.sidecar.capture.bind(b.sidecar);
  b.sidecar.capture = (...a) => { if (b.closed || b.webview === null) window.__closedSends++; return orig(...a); };
  return JSON.stringify({ queue: b.captureQueue.length });
})"""
for planted in (False, True):
    q = json.loads(live.evaluate(PREP + "(%s)" % ("true" if planted else "false")))
    t0 = time.time()
    live.reload_plugin()
    time.sleep(60)
    r = json.loads(live.evaluate("""(() => { const b = window.__closedView; const out = { closed_sends: window.__closedSends, left_in_queue: b ? b.captureQueue.length : null, abandoned: b ? b.abandonedOnClose : null };
      if (b) b.plant.delete("pump-after-close"); return JSON.stringify(out); })()"""))
    r.update({"planted": planted, "queue_before_reload": q["queue"], "sidecar_refused_60s": refused_since(t0)})
    print(json.dumps(r))
live.evaluate("(()=>{ delete window.__closedView; window.__vertiscopeReaderAt = %s; return 1})()" % json.dumps(stamp))
