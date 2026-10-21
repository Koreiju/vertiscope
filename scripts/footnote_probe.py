"""Does a chunk's MARKDOWN form draw footnote jumps as marks, not raw
`32(#cite_note-...)` text? (2026-10-11.) Opens one panel on the open page
whose markdown holds a cite note; prints what the reader sees."""
import json, sys
sys.path.insert(0, r"<home>\Documents\vertiscope")
from vertiscope.obsidian.live import Live
word = sys.argv[1] if len(sys.argv) > 1 else "cite_note"
print(Live().evaluate(r"""(async () => {
  const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
  const b = app.workspace.getLeavesOfType("vertiscope-browser-view")[0].view;
  const W = %s;
  const cids = await v.sidecar.pageCids(b.session);
  let hit = null;
  for (const c of cids) { const p = await v.chunkPayload(c); const md = p && p.lines ? p.lines.map((l) => l.text).join(" ") : ""; if (md.includes(W) && md.includes("cite_note")) { hit = c; break; } }
  if (!hit) return JSON.stringify({ error: "no chunk with a cite note", stored: cids.length });
  let n = v.graph.graphData().nodes.find((x) => x.id === hit);
  if (!n) { const got = await v.sidecar.place([hit]); if (got && got.nodes) v.absorb(got.nodes, got.edges); n = v.graph.graphData().nodes.find((x) => x.id === hit); }
  await v.openBillboard(n);
  await new Promise((r) => setTimeout(r, 1500));
  const e = v.billboards.get(hit);
  if (e.form !== "markdown") await v.switchForm(e, "markdown");
  await new Promise((r) => setTimeout(r, 800));
  const md = e.el.querySelector(".vertiscope-bb-md");
  const t = md ? md.innerText : "";
  const sups = md ? [...md.querySelectorAll("sup")].map((s) => s.innerText).slice(0, 5) : [];
  v.closeBillboard(hit);
  return JSON.stringify({ raw_cite_text: /cite_note/.test(t), sups, head: t.slice(0, 160) });
})()""" % json.dumps(word), timeout=90))
