"""G-230 (PLUGIN_GOAL 159): a hovered url's nodes spread so their pictures
do not overlap, and go back to the fit's place when the hover ends.

A page is unfolded (its chunks drawn, as a click does); the closest pair of
its nodes is measured as distance / (sum of drawn radii) -- below 1 they
overlap; one of its chunks is hovered through the hover path; measured
again after the glide; then the hover ends and every node's distance from
where it stood before is measured. Clean vs planted `plantNoHoverSpread`.
The plugin reloaded first; the page folded back; reader-idle gated.
"""
import json, sys
sys.path.insert(0, r"<home>\Documents\vertiscope")
from vertiscope.obsidian.live import Live
live = Live()
if live.evaluate("window.__vertiscope.reader.idleMs()") < 60000:
    print("aborted: reader active"); sys.exit(1)
stamp = live.evaluate("window.__vertiscopeReaderAt || 0")
live.reload_plugin()
JS = r"""(async (planted) => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
  v.plantNoHoverSpread = planted;
  const all = () => v.graph.graphData().nodes;
  // A page whose drawn nodes CROWD (closest pair under the spread's 1.15
  // gap): on an uncrowded page the spread rightly does nothing (k = 1), and
  // the first run measured only such pages -- nothing was tested.
  // After the reload the fit is drawn again before there is anything to pick.
  for (let i = 0; i < 120 && all().filter((n) => n.level === "page" && !n.force).length < 20; i++) await sleep(500);
  const pages = all().filter((n) => n.level === "page" && !n.force && (n.members || 0) >= 20 && (n.members || 0) <= 300)
    .sort(() => Math.random() - 0.5);
  let page = null, mem = [], before = Infinity, tried = 0;
  // The LIVE nodes, by id: an absorb can replace a node's object, and a
  // measurement held on the old ones watches copies nothing moves.
  const fresh = () => { const ids = new Set(mem.map((n) => String(n.id))); mem = all().filter((n) => ids.has(String(n.id))); };
  const ratio = () => { fresh(); let m = Infinity; for (let i = 0; i < mem.length; i++) for (let j = i + 1; j < mem.length; j++) {
      const a = mem[i], b = mem[j]; const d = Math.hypot(a.x - b.x, a.y - b.y, (a.z || 0) - (b.z || 0));
      m = Math.min(m, d / (v.drawnRadiusOf(a) + v.drawnRadiusOf(b))); } return +m.toFixed(3); };
  for (const p of pages.slice(0, 12)) {
    tried++;
    await v.togglePage(p);
    mem = [];
    for (let i = 0; i < 50; i++) { await sleep(200); mem = all().filter((n) => n !== p && n.level !== "page" && n.url === p.url && Number.isFinite(n.x)); if (mem.length >= 10) break; }
    await sleep(2500);                                 // let the unfold settle
    before = ratio();
    if (before < 1.15 && mem.length <= 400) { page = p; break; }
    await v.togglePage(p);                             // folded back: not crowded
  }
  if (!page) return JSON.stringify({ planted, error: "no crowded page in " + tried, last_closest: before });
  fresh();
  const homes = new Map(mem.map((n) => [String(n.id), [n.x, n.y, n.z || 0]]));
  const targets = new Map(mem.map((n) => [String(n.id), [n.fitX ?? n.x, n.fitY ?? n.y, n.fitZ ?? n.z ?? 0]]));
  const s0 = v.spreadStats.spread;
  v.highlightChunk(String(mem[0].id), page.url, "");
  await sleep(2500);                                 // frames are ~1 s apart when the window is covered
  const during = ratio();
  v.highlightChunk("", "", "");
  await sleep(2500);                                 // frames are ~1 s apart when the window is covered
  fresh();
  const dist = (n, m) => { const h = m.get(String(n.id)); return h ? Math.hypot(n.x - h[0], n.y - h[1], (n.z || 0) - h[2]) : 0; };
  const back = Math.max(...mem.map((n) => dist(n, homes)));
  const backFit = Math.max(...mem.map((n) => dist(n, targets)));
  const out = { planted, tried, page: page.url.slice(0, 50), nodes: mem.length, k: v.spreadStats.last_k, closest_before: before, closest_during: during,
                spread_ran: v.spreadStats.spread - s0, max_from_before: +back.toFixed(3), max_from_fit_target: +backFit.toFixed(3) };
  v.plantNoHoverSpread = false;
  await v.togglePage(page);
  return JSON.stringify(out);
})"""
for planted in (False, True, False, True):
    print(live.evaluate(JS + "(%s)" % ("true" if planted else "false")))
live.evaluate("(()=>{window.__vertiscopeReaderAt = %s; return 1})()" % json.dumps(stamp))
