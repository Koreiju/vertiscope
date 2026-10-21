"""G-183 live: a panel field holds while typed in, and Enter sends value + Enter.

The act is INTERCEPTED (v.onAct replaced by a recorder): nothing reaches the
live page. Clean and planted (plantRedrawWhileTyping) arms. Reader-idle gated.
"""
import sys, json, time
sys.path.insert(0, r"<home>\Documents\vertiscope\scripts")
from live_probe import Probe
p = Probe()
if p.ev("window.__vertiscope.reader.idleMs()") < 60000:
    print("reader active: not run"); sys.exit(0)
JS = r"""(async (planted) => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
  const b = app.workspace.getLeavesOfType("vertiscope-browser-view")[0].view;
  const url = b.webview.getURL();
  // A chunk of the open page whose lines include a typed field.
  const cids = await v.sidecar.pageCids(url);
  let cid = null;
  for (const c of cids) {
    const pay = await v.sidecar.chunk(c).catch(() => null);
    if ((pay && pay.lines || []).some((l) => /combobox|textbox|search/.test(String(l.control_key || l.key || "")))) { cid = c; break; }
  }
  if (!cid) return JSON.stringify({ error: "no chunk with a field on " + url });
  const node = v.graph.graphData().nodes.find((n) => String(n.id) === cid) || { id: cid, url, level: "chunk", x: 0, y: 0, z: 0 };
  for (const id of [...v.billboards.keys()]) v.closeBillboard(id);
  await sleep(300);
  await v.openBillboard(node);
  const entry = v.billboards.get(cid);
  if (!entry) return JSON.stringify({ error: "no billboard", cid });
  // The fast path paints first, then re-draws with the controls addressed.
  for (let i = 0; i < 40; i++) { await sleep(250); const f = entry.el.querySelector(".vertiscope-bb-body iframe"); if (f && f.contentDocument && f.contentDocument.querySelector("[data-vertiscope-act='type']")) break; }
  const frameOf = () => entry.el.querySelector(".vertiscope-bb-body iframe");
  const f0 = frameOf();
  const doc = f0 && f0.contentDocument;
  const field = doc && doc.querySelector("[data-vertiscope-act='type']");
  if (!field) return JSON.stringify({ error: "no live field in the panel", cid, frame: !!f0 });
  v.plantRedrawWhileTyping = planted;
  const acts = []; const was = v.onAct; v.onAct = async (c, rec) => { acts.push(rec); return { ok: true, stage: "done" }; };
  try {
    f0.focus(); field.focus();
    field.value = "okapi";
    field.dispatchEvent(new (f0.contentWindow.KeyboardEvent)("keydown", { key: "i", bubbles: true }));
    field.dispatchEvent(new (f0.contentWindow.Event)("input", { bubbles: true }));
    const held0 = v.panelStats.held;
    // A capture rewrites this chunk while the reader is typing.
    v.refreshBillboards([cid]);
    await sleep(1200);
    const sameFrame = frameOf() === f0;
    const valueKept = sameFrame && field.value === "okapi";
    const held = v.panelStats.held - held0;
    // Enter in the field: the value and the page's Enter, as one act.
    let enter = null;
    if (sameFrame) {
      field.dispatchEvent(new (f0.contentWindow.KeyboardEvent)("keydown", { key: "Enter", bubbles: true, cancelable: true }));
      await sleep(300);
      enter = acts.length ? { action: acts[0].action, value: acts[0].value, enter: !!acts[0].enter } : null;
    }
    // Leaving the field releases the held redraw.
    const rel0 = v.panelStats.released;
    if (sameFrame && f0.contentWindow) {
      field.blur(); field.dispatchEvent(new (f0.contentWindow.FocusEvent)("focusout", { bubbles: true }));
      await sleep(800);
    }
    return JSON.stringify({ planted, cid, tag: field.tagName, same_frame: sameFrame, value_kept: valueKept, held, enter,
                            released: v.panelStats.released - rel0 });
  } finally {
    v.onAct = was; v.plantRedrawWhileTyping = false;
  }
})"""
arms = [a == "planted" for a in (sys.argv[1:] or ["clean", "planted"])]
for planted in arms:
    try:
        print(p.ev(JS + "(%s)" % ("true" if planted else "false")))
    except Exception as e:
        print(json.dumps({"planted": planted, "threw": str(e)[:400]}))
