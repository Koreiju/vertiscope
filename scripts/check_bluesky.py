"""G-199: Bluesky -- scanned nodes persist, a scanned page's url node unfolds
and folds on click, embedded media shows.

A public profile is opened in the browser cell and scrolled (a feed recycles
like archive.org's list). Scored: grey nodes drawn after the scroll and how
many are retained; the url node clicked twice through the graph's own click
handler -- chunk nodes of the page drawn before / after one click / after
two; and how many of the page's grey chunks carry a picture in their lines.
Reader-idle gated; the browser goes back where it was.
"""
import json, sys
sys.path.insert(0, r"<home>\Documents\vertiscope")
from vertiscope.obsidian.live import Live
live = Live()
if live.evaluate("window.__vertiscope.reader.idleMs()") < 60000:
    print("aborted: reader active"); sys.exit(1)
stamp = live.evaluate("window.__vertiscopeReaderAt || 0")
URL = sys.argv[1] if len(sys.argv) > 1 else "https://bsky.app/profile/bsky.app"
JS = r"""(async (url) => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
  const b = app.workspace.getLeavesOfType("vertiscope-browser-view")[0].view;
  const start = b.webview.getURL();
  try {
    b.go(url); for (let i = 0; i < 60 && !(b.webview.getURL() || "").includes("bsky.app"); i++) await sleep(500);
    await sleep(7000);
    for (let i = 0; i < 40; i++) { b.webview.sendInputEvent({ type: "mouseWheel", x: 400, y: 400, deltaX: 0, deltaY: -600 }); await sleep(200); }
    await sleep(4000);
    const s = b.session, t = b.forceTrees.get(s);
    const nodes = () => v.graph.graphData().nodes.filter((n) => n.url === s);
    const count = () => { const ns = nodes(); return { grey: ns.filter((n) => n.force && n.level !== "page" && n.level !== "path").length,
                                                      stored: ns.filter((n) => !n.force && n.level !== "page").length }; };
    const page = nodes().find((n) => n.level === "page" && !n.force) || nodes().find((n) => n.level === "page");
    const before = count();
    // What a click on a url node runs, AWAITED: the unfold places the page's
    // stored chunks through the sidecar, which can take seconds under a
    // capture backlog -- a fixed wait read an unfinished unfold as empty.
    let one = null, two = null, r1 = null, r2 = null;
    if (page) { r1 = await v.togglePage(page); await sleep(500); one = count(); r2 = await v.togglePage(page); await sleep(800); two = count(); }
    // A grey chunk with a picture line: its panel, and the images loaded in it.
    let greyPanel = null;
    const gid = t ? t.held().map((h) => h.id).find((id) => (t.linesOf(id) || []).some((l) => l.startsWith("![](")) && v.graph.graphData().nodes.some((n) => n.id === id)) : null;
    if (gid) {
      for (const k of [...v.billboards.keys()]) v.closeBillboard(k);
      await v.openBillboard(v.graph.graphData().nodes.find((n) => n.id === gid));
      await sleep(3500);
      const e = v.billboards.get(gid);
      const imgs = e ? [...e.el.querySelectorAll("img")] : [];
      greyPanel = { imgs: imgs.length, loaded: imgs.filter((i) => i.complete && i.naturalWidth > 0).length };
      v.closeBillboard(gid);
    }
    const pics = t ? t.held().filter((h) => (t.linesOf(h.id) || []).some((l) => /\.(jpe?g|png|webp|gif)|cdn\.bsky|image/i.test(l))).length : null;
    return JSON.stringify({ session: s.slice(0, 80), live: t ? t.held().length : 0, retained: t ? t.retainedCount() : 0,
                            page: page ? { id: String(page.id).slice(0, 60), force: !!page.force } : null, before, one, two, toggles: [r1 && r1.action, r2 && r2.action], chunks_with_picture_lines: pics, grey_panel: greyPanel });
  } finally { if (start && start.startsWith("http")) b.go(start); }
})"""
r = json.loads(live.evaluate(JS + "(%s)" % json.dumps(URL)))
live.evaluate("(()=>{window.__vertiscopeReaderAt = %s; return 1})()" % json.dumps(stamp))
print(json.dumps(r))
