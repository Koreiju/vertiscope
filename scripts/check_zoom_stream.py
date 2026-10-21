"""G-227 (PLUGIN_GOAL 156): a zoom stays smooth while a stream flows.

archive.org visits with scrolling keep drains arriving; during them the
graph canvas gets a 2 s wheel zoom (wheel events on the canvas, as a mouse
sends), and every frame interval in that window is recorded, with how many
stream deltas were applied INSIDE it. Clean (deltas held while the reader
moves the camera, applied when it rests) vs planted `plantNoDeltaDefer`,
alternated, two each. The plugin reloaded first; reader-idle gated; the
camera pose restored after each zoom; the reader stamp restored.
"""
import json, sys
sys.path.insert(0, r"<home>\Documents\vertiscope")
from vertiscope.obsidian.live import Live
live = Live()
if live.evaluate("window.__vertiscope.reader.idleMs()") < 60000:
    print("aborted: reader active"); sys.exit(1)
stamp = live.evaluate("window.__vertiscopeReaderAt || 0")
live.reload_plugin()
JS = r"""(async (planted, tag) => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
  const b = app.workspace.getLeavesOfType("vertiscope-browser-view")[0].view;
  v.plantNoDeltaDefer = planted;
  const g = v.graph, cam = g.camera(), ctl = g.controls();
  const pose = { p: cam.position.clone(), t: ctl.target.clone() };
  let applied = 0, inZoom = false;
  const orig = v.applyForceDelta.bind(v);
  v.applyForceDelta = (d) => { if (inZoom) applied++; return orig(d); };
  try {
    b.go("https://archive.org/search?query=radio+drama&z=" + tag + (planted ? "p" : "c"));
    await sleep(3500);
    const scroll = (async () => { for (let i = 0; i < 30; i++) { b.webview.sendInputEvent({ type: "mouseWheel", x: 400, y: 400, deltaX: 0, deltaY: -400 }); await sleep(150); } })();
    await sleep(1200);
    const c = v.canvasEl, r = c.getBoundingClientRect();
    const frames = []; let last = performance.now(), on = true;
    const tick = (t) => { frames.push(t - last); last = t; if (on) requestAnimationFrame(tick); };
    requestAnimationFrame(tick);
    inZoom = true;
    const d0 = v.deltaStats.deferred;
    for (let i = 0; i < 40; i++) {
      c.dispatchEvent(new WheelEvent("wheel", { deltaY: i < 20 ? 120 : -120, clientX: r.left + r.width / 2, clientY: r.top + r.height / 2, bubbles: true, cancelable: true }));
      await sleep(50);
    }
    inZoom = false; on = false;
    await scroll; await sleep(1600);
    frames.shift();
    const s = [...frames].sort((a, b) => a - b);
    const q = (f) => Math.round(s[Math.min(s.length - 1, Math.floor(f * s.length))] || 0);
    return JSON.stringify({ planted, frames: frames.length, p50: q(0.5), p95: q(0.95), max: q(1), over_50ms: frames.filter((x) => x > 50).length,
                            deltas_in_zoom: applied, deferred: v.deltaStats.deferred - d0 });
  } finally {
    v.applyForceDelta = orig; v.plantNoDeltaDefer = false;
    g.cameraPosition(pose.p, pose.t, 0);
  }
})"""
import time
for i, planted in enumerate((False, True, False, True)):
    print(live.evaluate(JS + "(%s, %d)" % ("true" if planted else "false", int(time.time() * 1000) + i)))
live.evaluate("(()=>{window.__vertiscopeReaderAt = %s; return 1})()" % json.dumps(stamp))
