"""After a plugin RELOAD, no code of the closed views keeps running.

2026-10-11: the window-held profiler was replaced back and forth between two
builds after a reload -- the closed graph view's timers (the web-follow, the
hover-panel sweep, the settle) were never cleared and kept calling the OLD
build's code. Now `onClose` clears them; a timer that still fires on a closed
view counts itself on the window (`__domvecClosedTicks`).

Each arm starts a search (which starts the web-follow timer), reloads the
plugin, and counts closed-view ticks over 12 s. Planted
(`__domvecPlantLeakTimers`): the timers are left running -- the count must
rise, or this cannot see a leak. Not an in-plugin check: reloading the plugin
would end the verifier running it.

**And by the renderer's own profile (2026-10-24).** The tick counter sees
only timers on a view that was CLOSED. A view that never was kept its whole
frame loop: a chunk view from a load hours old was still syncing 96k nodes
every 2 s, and the counter read 0. So each arm also profiles the renderer
for 5 s after the reload. A script id names a BUILD, not a load (V8 reuses
the script when the source is unchanged), so the replaced load is measured by
its own frames: a view of an older load counts every frame it runs while
planted to run on (`__domvecOldGenFrames`), and is stopped and counted
(`__domvecOrphanStops`) when not. The profile still names any older BUILD
still running (`older_builds`). Arms:
`skip-close` (`__domvecPlantSkipClose`: the views are never closed) must
still read ~0 -- the frame loop's load-generation guard stops them;
`orphan` (that plus `__domvecPlantOrphanLoop`: the guard off) must not.

    python scripts/check_reload_leak.py
"""
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from live_probe import Probe  # noqa: E402

V = 'app.workspace.getLeavesOfType("domvec-graph-view")[0].view'
B = 'app.workspace.getLeavesOfType("domvec-browser-view")[0]?.view'


def profile_by_script(p, secs=5.0):
    """Self samples per `plugin:domvec-bridge` script id over `secs`."""
    p.call("Profiler.enable")
    p.call("Profiler.setSamplingInterval", interval=500)
    p.call("Profiler.start")
    time.sleep(secs)
    prof = p.call("Profiler.stop")["profile"]
    hits = {}
    for x in prof["samples"]:
        hits[x] = hits.get(x, 0) + 1
    per = {}
    for n in prof["nodes"]:
        cf = n["callFrame"]
        if "domvec-bridge" in cf["url"]:
            per[int(cf["scriptId"])] = per.get(int(cf["scriptId"]), 0) + hits.get(n["id"], 0)
    return per


def arm(p, planted, skip_close=False, orphan=False):
    p.ev("(()=>{window.__domvecClosedTicks=0;window.__domvecPlantLeakTimers=%s;"
         "window.__domvecPlantSkipClose=%s;window.__domvecPlantOrphanLoop=%s;return 1})()"
         % ("true" if planted else "false", "true" if skip_close else "false", "true" if orphan else "false"))
    p.ev("(()=>{window.__domvecOldGenFrames=0;window.__domvecOrphanStops=0;return 1})()")
    before = profile_by_script(p, 2.0)
    current = max(before) if before else None
    # A search in flight: its web-follow timer runs for 30 s.
    timer = p.ev("""(async()=>{const v=%s,b=%s;if(b)b.plantNoWebSearch=true;
      for(let i=0;i<40&&!v.searchField;i++)await new Promise(r=>setTimeout(r,250));
      v.searchField.input.value="okapi";await v.searchField.run();
      // The follow timer starts on SUBMIT (followStore), not on run(): this
      // arm planted nothing from the day that moved (2026-10-24, 0 ticks).
      v.followStore("okapi");return !!v.webTimer})()""" % (V, B))
    time.sleep(1)
    p.ev('(async()=>{await app.plugins.disablePlugin("domvec-bridge");await app.plugins.enablePlugin("domvec-bridge");return 1})()')
    time.sleep(12)
    ticks = p.ev("window.__domvecClosedTicks||0")
    f0 = p.ev("window.__domvecOldGenFrames||0")
    after = profile_by_script(p, 5.0)
    frames = p.ev("window.__domvecOldGenFrames||0") - f0
    p.ev("(()=>{window.__domvecPlantLeakTimers=false;window.__domvecPlantSkipClose=false;"
         "window.__domvecPlantOrphanLoop=false;return 1})()")
    return {"planted": planted, "skip_close": skip_close, "orphan": orphan, "closed_view_ticks": ticks,
            "follow_timer_started": timer, "old_load_frames_5s": frames,
            "orphan_stops": p.ev("window.__domvecOrphanStops||0"),
            "this_build_samples": after.get(current, 0) if current is not None else None,
            "older_builds": {k: v for k, v in after.items() if current is not None and k < current and v > 5}}


def main():
    p = Probe()
    clean = arm(p, False)
    planted = arm(p, True)
    skip = arm(p, False, skip_close=True)
    orphan = arm(p, False, skip_close=True, orphan=True)
    # Leave the reader a clean plugin: one more reload, timers cleared.
    p.ev('(async()=>{await app.plugins.disablePlugin("domvec-bridge");await app.plugins.enablePlugin("domvec-bridge");return 1})()')
    ok = (clean["closed_view_ticks"] == 0 and planted["follow_timer_started"] and planted["closed_view_ticks"] > 0
          and clean["old_load_frames_5s"] == 0 and skip["old_load_frames_5s"] == 0 and skip["orphan_stops"] >= 1
          and orphan["old_load_frames_5s"] > 50)
    print(json.dumps({"pass": ok, "clean": clean, "planted": planted, "skip_close": skip, "orphan": orphan}))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
