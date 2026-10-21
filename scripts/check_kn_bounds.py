"""G-225 (PLUGIN_GOAL 154): the k/n fields are bounded by the number
matching, not a fixed 2000. Live: the reader's 2000 / 2000 asked for a query,
the fields read back once the tiers finish; and a broad query asked past 2000.
Clean vs planted (`plantFixedCap`). The field's value is restored. Idle-gated.
"""
import json, sys
sys.path.insert(0, r"<home>\Documents\vertiscope")
from vertiscope.obsidian.live import Live
live = Live()
if live.evaluate("window.__vertiscope.reader.idleMs()") < 60000:
    print("aborted: reader active"); sys.exit(1)
stamp = live.evaluate("window.__vertiscopeReaderAt || 0")
live.reload_plugin()
JS = r"""(async (planted, q, k, n) => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const f = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view.searchField;
  const was = { v: f.input.value, k: f.k, n: f.total };
  f.plantFixedCap = planted; f.plantPageSumMatching = planted; f.plantFixedPages = planted;
  try {
    f.input.value = q; f.k = k; f.total = n;
    const t0 = performance.now(); await f.run();
    for (let i = 0; i < 240 && f.tierStats.pages_done < f.tierStats.pages; i++) await sleep(500);
    return JSON.stringify({ planted, q, asked: [k, n], fields: [f.kInput.value, f.nInput.value], max: f.nInput.max,
                            retrieved: f.hits.length, matching: f.matching, pages: f.tierStats.pages, first_ms: f.tierStats.first_ms, ms: Math.round(performance.now() - t0) });
  } finally { f.plantFixedCap = false; f.plantPageSumMatching = false; f.plantFixedPages = false; f.input.value = was.v; f.k = was.k; f.total = was.n; await f.run(); }
})"""
for q, k, n in (("cowboy", 2000, 2000), ("the", 3000, 5000)):
    for planted in (False, True):
        print(live.evaluate(JS + "(%s, %s, %d, %d)" % ("true" if planted else "false", json.dumps(q), k, n)))
live.evaluate("(()=>{window.__vertiscopeReaderAt = %s; return 1})()" % json.dumps(stamp))
