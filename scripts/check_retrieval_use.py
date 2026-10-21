"""G-231 / G-232 (PLUGIN_GOAL 160, 161): retrieval as the reader uses it.

G-231: the reader's own query ("small language models site:arxiv.org", the
one on screen when they wrote "retrieval usage is buggy") at 200 / 200:
how many DISTINCT pages the results come from and how many distinct labels
the strip shows. Clean (a page counts for at most n/6; labels are the
result's own words) vs planted `plantUncappedShare` (two pages took all
200, every item read "duckduckgo.com/").

G-232: right-click mode -- a strip hover flies and opens NO panel; a
right-click on the item opens it. Planted `plantStripIgnoresToggle`: the
hover opens the panel anyway. The reader's mode and field are restored.
The plugin reloaded first; reader-idle gated; the reader stamp restored.
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
  const f = v.searchField;
  const was = { q: f.input.value, k: f.k, n: f.total, mode: v.panelsOn };
  f.plantUncappedShare = planted; v.plantStripIgnoresToggle = planted;
  try {
    f.input.value = "small language models site:arxiv.org"; f.k = 200; f.total = 200;
    await f.run();
    for (let i = 0; i < 200 && f.tierStats.pages_done < f.tierStats.pages; i++) await sleep(250);
    await sleep(500);
    const urls = new Set(f.hits.map((h) => h.url.split("#")[0]));
    const labels = new Set([...f.strip.children].map((el) => el.querySelector(".vertiscope-search3d-item-label")?.textContent || ""));
    // G-232: right-click mode
    v.panelsOn = "rightclick";
    for (const k of [...v.billboards.keys()]) v.closeBillboard(k);
    const item = f.strip.children[2];
    const fl = v.focusStats.flown, asked = v.focusStats.asked;
    item.dispatchEvent(new MouseEvent("mouseenter"));
    await sleep(1500);
    const hoverPanel = v.billboards.size, hoverAsked = v.focusStats.asked - asked;
    item.dispatchEvent(new MouseEvent("mouseleave"));
    await sleep(300);
    for (const k of [...v.billboards.keys()]) v.closeBillboard(k);
    item.dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
    await sleep(1500);
    const rightPanel = v.billboards.size;
    for (const k of [...v.billboards.keys()]) v.closeBillboard(k);
    return JSON.stringify({ planted, hits: f.hits.length, pages: f.tierStats.pages, distinct_urls: urls.size, distinct_labels: labels.size,
                            sample_labels: [...labels].slice(0, 4), rightclick_mode: { hover_asked_focus: hoverAsked, hover_panels: hoverPanel, right_click_panels: rightPanel } });
  } finally {
    f.plantUncappedShare = false; v.plantStripIgnoresToggle = false; v.panelsOn = was.mode;
    f.input.value = was.q; f.k = was.k; f.total = was.n; await f.run();
  }
})"""
for planted in (False, True):
    print(live.evaluate(JS + "(%s)" % ("true" if planted else "false")))
live.evaluate("(()=>{window.__vertiscopeReaderAt = %s; return 1})()" % json.dumps(stamp))
