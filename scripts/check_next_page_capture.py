"""G-253 (PLUGIN_GOAL 181): leaving a busy page, the NEXT page's chunks are
saved -- and so leave grey for their projected place -- without waiting
behind the left page's settle (2026-10-18: "a lot of diff scans not yet at
least projected after vectorization").

A busy page first (bandcamp's homepage, its feed rewriting itself) for
`--busy` seconds, then a fresh article. Measured on the article: seconds from
navigation until the first of its grey nodes is covered by a stored chunk,
and until the profiler's `stored` mark (its first stored chunk drawn). Clean
vs planted `settle-in-age-order` (the left page's settle before the new
page's first capture, as before). Reader-idle gated; plugin reloaded first;
the reader's page restored.
"""
import json, sys, time
sys.path.insert(0, r"<home>\Documents\vertiscope")
from vertiscope.obsidian.live import Live
live = Live()
if live.evaluate("window.__vertiscope.reader.idleMs()") < 60000:
    print("aborted: reader active"); sys.exit(1)
stamp = live.evaluate("window.__vertiscopeReaderAt || 0")
was = live.evaluate("app.workspace.getLeavesOfType('vertiscope-browser-view')[0].view.webview.getURL()")
restore = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--restore=")), was)
busy_s = int(next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--busy=")), "25"))
live.reload_plugin()
time.sleep(4)
BUSY = "https://bandcamp.com/"
NEXT = next((a for a in sys.argv[1:] if a.startswith("http")), "https://en.wikipedia.org/wiki/Trie")
PROBE = r"""((u) => {
  const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
  const b = app.workspace.getLeavesOfType("vertiscope-browser-view")[0].view;
  const k = (x) => String(x || "").split("#")[0];
  const specs = [...v.forceSpecs.values()].filter((s) => k(s.url) === k(u) && s.parent && !s.branch);
  const vis = window.__vertiscope.profile.visits().filter((x) => x.url === k(u) || (x.aliases || []).includes(k(u))).slice(-1)[0];
  return JSON.stringify({ grey: specs.length, covered: specs.filter((s) => s.cid).length, stored_mark: vis ? vis.marks.stored ?? null : null,
                          backlog: b.captureBacklog, idle: window.__vertiscope.reader.idleMs() });
})"""
go = lambda u: live.evaluate("(() => { app.workspace.getLeavesOfType('vertiscope-browser-view')[0].view.go(%s); return 1; })()" % json.dumps(u))
try:
    for planted in (False, True):
        live.evaluate("(() => { const b = app.workspace.getLeavesOfType('vertiscope-browser-view')[0].view; b.plant[%s]('settle-in-age-order'); return 1; })()" % ("'add'" if planted else "'delete'"))
        go(BUSY + "?nb=%d" % int(time.time() * 1000))
        time.sleep(busy_s)
        nxt = NEXT + "?np=%d" % int(time.time() * 1000)
        go(nxt)
        t0 = time.time(); first_cover = None; stored = None; backlog0 = None
        while time.time() - t0 < 120:
            time.sleep(1)
            s = json.loads(live.evaluate(PROBE + "(%s)" % json.dumps(nxt)))
            if backlog0 is None: backlog0 = s["backlog"]
            if s["idle"] < 3000 and time.time() - t0 > 3:
                print("aborted: reader active"); raise SystemExit(1)
            if first_cover is None and s["covered"]:
                first_cover = round(time.time() - t0, 1)
            if s["stored_mark"] is not None and stored is None:
                stored = round(s["stored_mark"] / 1000, 1)
            if first_cover is not None and stored is not None:
                break
        print(json.dumps({"planted_settle_in_age_order": planted, "next": NEXT[8:], "backlog_on_arrival": backlog0,
                          "first_grey_covered_s": first_cover, "first_stored_drawn_s": stored, "grey_then": s["grey"], "covered_then": s["covered"]}))
finally:
    live.evaluate("(() => { app.workspace.getLeavesOfType('vertiscope-browser-view')[0].view.plant.delete('settle-in-age-order'); return 1; })()")
    if restore and restore.startswith("http"):
        go(restore)
    live.evaluate("(()=>{window.__vertiscopeReaderAt = %s; return 1})()" % json.dumps(stamp))
