"""Reload vertiscope-bridge so the LOADED code is the deployed build: disable,
clear any stale view registrations, enable (not awaited over CDP), reopen
the graph and browser views, and wait for the graph. Reader-idle gated."""
import sys, json, time
sys.path.insert(0, r"<home>\Documents\vertiscope\scripts")
from live_probe import Probe
p = Probe()
if p.ev("window.__vertiscope.reader.idleMs()") < 60000 and "--force" not in sys.argv:
    print("reader active: not reloaded"); sys.exit(1)
p.ev("""(async()=>{ await app.plugins.disablePlugin('vertiscope-bridge'); return 1; })()""")
p.n += 1
p.ws.send(json.dumps({"id": p.n, "method": "Runtime.evaluate", "params": {"expression": "window.__dvReload='start'; app.plugins.enablePlugin('vertiscope-bridge').then(()=>{window.__dvReload='done'}, (e)=>{window.__dvReload='err '+e}); 1", "returnByValue": True}}))
time.sleep(1)
p = Probe()
for i in range(60):
    time.sleep(2)
    if p.ev("String(window.__dvReload)") != "start": break
print("enable:", p.ev("String(window.__dvReload)"))
# Rebuild each view IN THE LEAF IT HAS -- never blank it and open another:
# that left 13 empty leaves splitting the window and the views 0 px wide
# (2026-10-12). Open a view only where none exists.
p.ev("""(async()=>{ for (const t of ['vertiscope-graph-view','vertiscope-browser-view']) {
    const ls = app.workspace.getLeavesOfType(t);
    const race = (pr) => Promise.race([pr, new Promise((r) => setTimeout(r, 15000))]);
    if (ls.length) { for (const l of ls) await race(l.setViewState({ type: t, active: false })); }
    if (!app.workspace.getLeavesOfType(t).length) await race(window.__vertiscope.act('open', t === 'vertiscope-graph-view' ? 'graph' : 'browser')); }
  return 1; })()""")
for i in range(90):
    time.sleep(2)
    r = p.ev("(()=>{const v=app.workspace.getLeavesOfType('vertiscope-graph-view')[0]?.view; return v&&v.graph? v.graph.graphData().nodes.length : 0})()")
    if r and r > 50: break
print("graph nodes:", r)
