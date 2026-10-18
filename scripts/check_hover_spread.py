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
sys.path.insert(0, r"<home>\Documents\domvec")
from domvec.obsidian.live import Live
live = Live()
if live.evaluate("window.__domvec.reader.idleMs()") < 60000:
    print("aborted: reader active"); sys.exit(1)
stamp = live.evaluate("window.__domvecReaderAt || 0")
live.reload_plugin()
JS = r"""(async (planted) => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const v = app.workspace.getLeavesOfType("domvec-graph-view")[0].view;
  v.plantNoHoverSpread = planted;
  const all = () => v.graph.graphData().nodes;
  const pages = all().filter((n) => n.level === "page" && !n.force && (n.members || 0) >= 20 && (n.members || 0) <= 150);
  const page = pages[Math.floor(Math.random() * pages.length)];
  await v.togglePage(page);
  let mem = [];
  for (let i = 0; i < 50; i++) { await sleep(200); mem = all().filter((n) => n !== page && n.level !== "page" && n.url === page.url && Number.isFinite(n.x)); if (mem.length >= 10) break; }
  await sleep(2500);                                   // let the unfold settle
  const ratio = () => { let m = Infinity; for (let i = 0; i < mem.length; i++) for (let j = i + 1; j < mem.length; j++) {
      const a = mem[i], b = mem[j]; const d = Math.hypot(a.x - b.x, a.y - b.y, (a.z || 0) - (b.z || 0));
      m = Math.min(m, d / (v.drawnRadiusOf(a) + v.drawnRadiusOf(b))); } return +m.toFixed(3); };
  const before = ratio();
  const homes = mem.map((n) => [n.x, n.y, n.z || 0]);
  v.highlightChunk(String(mem[0].id), page.url, "");
  await sleep(700);
  const during = ratio();
  v.highlightChunk("", "", "");
  await sleep(700);
  const back = Math.max(...mem.map((n, i) => Math.hypot(n.x - homes[i][0], n.y - homes[i][1], (n.z || 0) - homes[i][2])));
  const out = { planted, page: page.url.slice(0, 50), nodes: mem.length, k: v.spreadStats.last_k, closest_before: before, closest_during: during,
                max_return_error: +back.toFixed(3) };
  v.plantNoHoverSpread = false;
  await v.togglePage(page);
  return JSON.stringify(out);
})"""
for planted in (False, True, False):
    print(live.evaluate(JS + "(%s)" % ("true" if planted else "false")))
live.evaluate("(()=>{window.__domvecReaderAt = %s; return 1})()" % json.dumps(stamp))
