"""G-82: a pin whose chunk the store no longer holds re-anchors by its address.

The live G-82 run passed without exercising it (reresolved 0): the stale cid
that failed it before (`561404dd`, "no such chunk") did not recur. So the
path is driven directly: a pin on a real paragraph of Radix_tree, re-keyed
to a cid the store has never had -- what a capture's re-cut leaves behind --
and handed to the graph as the browser hands any pin. Clean: the graph
cannot place it, the browser resolves the pin's url : xpath again, and the
pin and its billboard land on the chunk that draws it. Planted
(`no-pin-reresolve`): the dead cid stays, no billboard. Reader-idle gated;
every pin let go after.
"""
import json
import sys

sys.path.insert(0, r"<home>\Documents\vertiscope")
from vertiscope.obsidian.live import Live

live = Live()
JS = r"""(async (planted, waitUnknown) => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  if (window.__vertiscope.reader.idleMs() < 60000) return JSON.stringify({ aborted: "reader active" });
  const d = window.__vertiscope;
  const b = app.workspace.getLeavesOfType("vertiscope-browser-view")[0].view;
  const g = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
  await d.act("unpin", "all");
  if (!(b.webview.getURL() || "").includes("Radix_tree")) { await d.act("navigate", "https://en.wikipedia.org/wiki/Radix_tree"); await sleep(4000); }
  const url = b.webview.getURL();
  const xpath = "/html/body/div[3]/div/div[3]/main/div[3]/div[2]/div/section/p";
  const read = await b.readPin(url, xpath);
  if (read.error) return JSON.stringify({ error: read.error });
  const real = read.cid, dead = "0000dead0000beef";
  if (planted) b.plant.add("no-pin-reresolve");
  g.plantWaitUnknown = waitUnknown;
  try {
    b.pinned = new Map([[dead, { ...read, cid: dead }]]);
    b.pipebox?.setPins(b.pinList());
    b.onPin(dead);
    let state = null;
    for (let i = 0; i < 70; i++) {
      await sleep(1000);
      const bills = g.billboardState().filter((x) => x.fromBrowser).map((x) => x.id);
      state = { pinned: [...b.pinned.keys()], billboards: bills, s: i + 1 };
      if (bills.includes(real) && !b.pinned.has(dead)) break;
    }
    return JSON.stringify({ planted, waitUnknown, real, dead, ...state, reanchored: b.reanchored.get(dead) || null,
                            counters: { reresolved: b.diffsApplied.pins_reresolved, lost: b.diffsApplied.pins_lost } });
  } finally {
    b.plant.delete("no-pin-reresolve");
    g.plantWaitUnknown = false;
    b.reanchored.delete(dead);
    await d.act("unpin", "all");
    if (b.pinned.size) { b.pinned = new Map(); b.pipebox?.setPins(b.pinList()); }
  }
})"""

got = live.reload_plugin(settle=4, wait=True)
if got.get("refused"):
    print(got["refused"]); sys.exit(1)
rows = []
# clean; planted no-pin-reresolve; planted plantWaitUnknown (the 25 s wait)
for planted, wait in ((False, False), (True, False), (False, True)):
    row = json.loads(live.evaluate(JS + "(%s, %s)" % ("true" if planted else "false", "true" if wait else "false")))
    print(json.dumps(row))
    if row.get("aborted") or row.get("error"):
        sys.exit(1)
    rows.append(row)
clean, plant, waited = rows
ok = lambda r: r["real"] in r["billboards"] and r["dead"] not in r["pinned"]
print("clean: billboard on the live chunk %s in %ss; no-pin-reresolve: %s; wait-unknown: %s in %ss"
      % (ok(clean), clean["s"], ok(plant), ok(waited), waited["s"]))
