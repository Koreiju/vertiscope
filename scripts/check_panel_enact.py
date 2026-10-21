"""G-46 / G-68 / G-183 end to end, with --enact: a field typed in a 3D panel and
Enter pressed there reaches the LIVE page through its trie address. Planted
(`act-noop`): the page is untouched. Reader-idle gated; the cell restored."""
import sys, json, time
sys.path.insert(0, r"<home>\Documents\vertiscope\scripts")
from live_probe import Probe
p = Probe()
if p.ev("window.__vertiscope.reader.idleMs()") < 60000:
    print("reader active: not run"); sys.exit(0)
B = 'app.workspace.getLeavesOfType("vertiscope-browser-view")[0].view'
start = p.ev("%s.webview.getURL()" % B)
JS = r"""(async (planted, word) => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
  const b = app.workspace.getLeavesOfType("vertiscope-browser-view")[0].view;
  const url = b.webview.getURL();
  const cids = await v.sidecar.pageCids(url);
  let cid = null;
  for (const c of cids) {
    const pay = await v.sidecar.chunk(c).catch(() => null);
    if ((pay && pay.lines || []).some((l) => /\/input\|/.test(String(l.key || "")))) { cid = c; break; }
  }
  if (!cid) return JSON.stringify({ error: "no chunk with the search box", url });
  for (const id of [...v.billboards.keys()]) v.closeBillboard(id);
  await sleep(300);
  const node = v.graph.graphData().nodes.find((n) => String(n.id) === cid) || { id: cid, url, level: "chunk", x: 0, y: 0, z: 0 };
  await v.openBillboard(node);
  const entry = v.billboards.get(cid);
  let field = null, f0 = null;
  for (let i = 0; i < 40 && !field; i++) { await sleep(250); f0 = entry && entry.el.querySelector(".vertiscope-bb-body iframe"); field = f0 && f0.contentDocument && f0.contentDocument.querySelector("[data-vertiscope-act='type']"); }
  if (!field) return JSON.stringify({ error: "no live field in the panel", cid });
  if (planted) b.plant.add("act-noop");
  try {
    f0.focus(); field.focus(); field.value = word;
    field.dispatchEvent(new (f0.contentWindow.Event)("input", { bubbles: true }));
    field.dispatchEvent(new (f0.contentWindow.KeyboardEvent)("keydown", { key: "Enter", bubbles: true, cancelable: true }));
    let landed = "";
    for (let i = 0; i < 40; i++) { await sleep(500); landed = b.webview.getURL(); if (landed.includes("q=" + word)) break; }
    const readout = entry.el.querySelector(".vertiscope-act-readout");
    return JSON.stringify({ planted, cid, before: url.slice(0, 70), after: landed.slice(0, 70), reached: landed.includes("q=" + word),
                            readout: readout ? readout.textContent.slice(0, 120) : null });
  } finally { b.plant.delete("act-noop"); }
})"""
try:
    for planted, word in ((False, "giraffe"), (True, "zebra")):
        p.ev("(()=>{%s.go('https://duckduckgo.com/?q=okapi&ia=web');return 1})()" % B)
        time.sleep(25)
        print(p.ev(JS + "(%s, %s)" % ("true" if planted else "false", json.dumps(word))))
finally:
    if start and start.startswith("http"):
        p.ev("(()=>{%s.go(%s);return 1})()" % (B, json.dumps(start)))
