"""Wait for the reader's next N hover panels and report how long each took to
paint, and where the time went (read-only)."""
import json, sys, time
sys.path.insert(0, r"<home>\Documents\vertiscope")
from vertiscope.obsidian.live import Live
N = int(sys.argv[1]) if len(sys.argv) > 1 else 5
L = Live()
JS = r'''(()=>{const v=app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;const t=v.panelTimes;
return JSON.stringify({n:t.first_paint.length,first:t.first_paint.slice(-12).map(Math.round),page:t.page_paint.slice(-12).map(Math.round),
log:v.billboardLog.slice(-12).map(e=>({hover:e.from_hover,first:e.first_paint_ms,page:e.page_paint_ms,text:e.text,frame:e.frame,via:e.via})),
form:v.formStats});})()'''
t0 = time.time()
while time.time() - t0 < 900:
    d = json.loads(L.evaluate(JS))
    if d["n"] >= N:
        print(json.dumps(d)); break
    time.sleep(5)
else:
    print("timed out", json.dumps(d))
