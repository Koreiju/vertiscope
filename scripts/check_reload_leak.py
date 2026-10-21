"""After a plugin RELOAD, no code of the closed views keeps running.

2026-10-11: the window-held profiler was replaced back and forth between two
builds after a reload -- the closed graph view's timers (the web-follow, the
hover-panel sweep, the settle) were never cleared and kept calling the OLD
build's code. Now `onClose` clears them; a timer that still fires on a closed
view counts itself on the window (`__vertiscopeClosedTicks`).

Each arm starts a search (which starts the web-follow timer), reloads the
plugin, and counts closed-view ticks over 12 s. Planted
(`__vertiscopePlantLeakTimers`): the timers are left running -- the count must
rise, or this cannot see a leak. Not an in-plugin check: reloading the plugin
would end the verifier running it.

    python scripts/check_reload_leak.py
"""
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from live_probe import Probe  # noqa: E402

V = 'app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view'
B = 'app.workspace.getLeavesOfType("vertiscope-browser-view")[0]?.view'


def arm(p, planted):
    p.ev("(()=>{window.__vertiscopeClosedTicks=0;window.__vertiscopePlantLeakTimers=%s;return 1})()" % ("true" if planted else "false"))
    # A search in flight: its web-follow timer runs for 30 s.
    p.ev("""(async()=>{const v=%s,b=%s;if(b)b.plantNoWebSearch=true;
      for(let i=0;i<40&&!v.searchField;i++)await new Promise(r=>setTimeout(r,250));
      v.searchField.input.value="okapi";await v.searchField.run();return 1})()""" % (V, B))
    time.sleep(1)
    p.ev('(async()=>{await app.plugins.disablePlugin("vertiscope-bridge");await app.plugins.enablePlugin("vertiscope-bridge");return 1})()')
    time.sleep(12)
    ticks = p.ev("window.__vertiscopeClosedTicks||0")
    p.ev("(()=>{window.__vertiscopePlantLeakTimers=false;return 1})()")
    return {"planted": planted, "closed_view_ticks": ticks}


def main():
    p = Probe()
    clean = arm(p, False)
    planted = arm(p, True)
    # Leave the reader a clean plugin: one more reload, timers cleared.
    p.ev('(async()=>{await app.plugins.disablePlugin("vertiscope-bridge");await app.plugins.enablePlugin("vertiscope-bridge");return 1})()')
    ok = clean["closed_view_ticks"] == 0 and planted["closed_view_ticks"] > 0
    print(json.dumps({"pass": ok, "clean": clean, "planted": planted}))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
