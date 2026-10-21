"""G-264 / G-260 (PLUGIN_GOAL 186g, 186h, 186l): a chunk's knowledge-graph
triples are drawn in the 3D view -- entities as nodes hung from the chunk,
triples as lines between them -- from a field in the chunk's panel.

Live: (1) a prose chunk of Wikipedia's Radix tree, through Triplex (GPU);
(2) a `code://` chunk of this repository (`address.py`), through the compact code KG. For
each: the chunk's panel opened, its `triples` field CLICKED, and read: the
entity nodes in the graph (`kg:` ids) and how many are linked to the chunk,
the triple lines drawn, the seconds. Planted `plantNoKg`: no field, nothing
drawn. Reader-idle gated; plugin reloaded first.
"""
import json, sys, urllib.parse, urllib.request
sys.path.insert(0, r"<home>\Documents\vertiscope")
from vertiscope.obsidian.live import Live
live = Live()
if live.evaluate("window.__vertiscope.reader.idleMs()") < 60000:
    print("aborted: reader active"); sys.exit(1)
stamp = live.evaluate("window.__vertiscopeReaderAt || 0")
live.reload_plugin()


def best_chunk(url, prose=True):
    pm = json.load(urllib.request.urlopen("http://127.0.0.1:8788/page_map?url=" + urllib.parse.quote(url, safe=""), timeout=30))
    best = None
    for cid in list(pm.get("chunks", {}))[:60]:
        ch = json.load(urllib.request.urlopen("http://127.0.0.1:8788/chunk/" + cid, timeout=30))
        score = sum(len(l["text"]) for l in ch["lines"] if (len(l["text"]) > 80 if prose else True))
        if not best or score > best[1]:
            best = (cid, score)
    return best[0] if best else None


JS = r"""(async (cid, url, planted) => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
  v.plantNoKg = planted;
  try {
    // The view draws an OPEN page's chunks: unfold it with the reader's own
    // gesture (`togglePage`, a click on its url node).
    let node = v.graph.graphData().nodes.find((n) => String(n.id) === cid);
    if (!node) {
      const page = v.graph.graphData().nodes.find((n) => n.level === "page" && !n.force && String(n.url).split("#")[0] === url);
      if (page) { await v.togglePage(page); await sleep(2500); }
      node = v.graph.graphData().nodes.find((n) => String(n.id) === cid);
    }
    if (!node) return JSON.stringify({ planted, error: "chunk not drawn" });
    for (const k of [...v.billboards.keys()]) v.closeBillboard(k);
    await v.openBillboard(node, false, false);
    const e = v.billboards.get(cid);
    const field = e.el.querySelector(".vertiscope-bb-kg");
    if (!field) { v.closeBillboard(cid); return JSON.stringify({ planted, field: false, kg_nodes: v.graph.graphData().nodes.filter((n) => n.kgEntity && n.kgEntity.cid === cid).length }); }
    const t0 = performance.now();
    field.click();
    for (let i = 0; i < 240 && !/entities/.test(field.textContent || ""); i++) await sleep(500);
    await sleep(1000);
    const d = v.graph.graphData();
    const ents = d.nodes.filter((n) => n.kgEntity && n.kgEntity.cid === cid);
    const linked = ents.filter((n) => d.links.some((l) => (l.target?.id ?? l.target) === n.id && String(l.source?.id ?? l.source) === cid)).length;
    const out = { planted, field: true, label: field.textContent, s: Math.round((performance.now() - t0) / 100) / 10,
                  kg_nodes: ents.length, linked_to_chunk: linked, triples_drawn: v.kgStats.triples_drawn,
                  sample: ents.slice(0, 4).map((n) => n.name) };
    v.closeBillboard(cid);
    return JSON.stringify(out);
  } finally { v.plantNoKg = false; }
})"""
for url, prose in (("https://en.wikipedia.org/wiki/Radix_tree", True), ("code://repo/address.py", False)):
    cid = best_chunk(url, prose)
    print("==", url, cid)
    for planted in (True, False):
        print(live.evaluate(JS + "(%s, %s, %s)" % (json.dumps(cid), json.dumps(url), "true" if planted else "false"), timeout=200))
live.evaluate("(()=>{window.__vertiscopeReaderAt = %s; return 1})()" % json.dumps(stamp))
