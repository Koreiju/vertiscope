"""Which chunk each labelled field of the open page belongs to -- in the page's
own chunking, and in the store (read-only). The 2026-10-10 archive.org report:
"per-field chunk degradation on overlay ... the summary panel is probably within
a safe margin of the context window limit for chunks".

  python scripts/field_units.py Addeddate Boxid Camera Identifier Isbn Notes
"""
import json
import sys

sys.path.insert(0, r"<home>\Documents\vertiscope")
from vertiscope.obsidian.live import Live  # noqa: E402

want = sys.argv[1:] or ["Addeddate", "Boxid", "Camera", "Identifier", "Isbn", "Notes"]
L = Live()
print(L.evaluate(r"""(async () => {
  const b = app.workspace.getLeavesOfType("vertiscope-browser-view")[0].view, pb = b.pipebox, U = b.session;
  const WANT = %s;
  const r = JSON.parse(await b.webview.executeJavaScript("(function(W){var h=window.__vertiscopeSensor;var out=[];var all=[];(function walk(root){root.querySelectorAll('*').forEach(function(e){all.push(e);if(e.shadowRoot)walk(e.shadowRoot);});})(document);all.forEach(function(e){var t=(e.textContent||'').trim();if(W.indexOf(t)>=0&&!out.some(function(o){return o.t===t;})){var c=null;try{c=h.at(e);}catch(z){}out.push({t:t,tag:e.tagName.toLowerCase(),shadow:e.getRootNode()!==document,chunk:c?c.id:null,box:c&&c.box?c.box.map(Math.round):null});}});return JSON.stringify(out);})(" + JSON.stringify(WANT) + ")"));
  for (const x of r) { if (x.chunk != null) x.stored = b.storedCidFor("f:" + U + "#" + x.chunk, U) || null; }
  const stored = [...new Set(r.map((x) => x.stored).filter(Boolean))];
  return JSON.stringify({ session: U, map_chunks: pb.map.chunks, page_chunks: [...new Set(r.map((x) => x.chunk))].length,
                          stored_chunks: stored.length, rows: r });
})()""" % json.dumps(want), timeout=40))
