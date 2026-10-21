"""PLUGIN_GOAL 90 (G-163): is each overlay box where its chunk IS, on every page?

The reader's own test, made exhaustive: point at the page, and the outline the
overlay draws for what is under the pointer must contain the pointer. For a grid
of points over the viewport, the deepest element at each point is found by the
browser's own hit testing -- `elementFromPoint`, descended through every OPEN
shadow root -- and the sensor is asked which chunk that element belongs to and
where that chunk's box is. A point outside its own chunk's box is a box drawn in
the wrong place. The hit test shares no code with the sensor's box arithmetic,
so the two cannot agree by sharing a mistake.

Denominator: grid points that land on an element the sensor maps to a chunk.
Points on no chunk (page margins, a closed shadow root, an iframe) are counted
apart and never scored.

Planted arm: every box shifted 40 px down-right -- the score must collapse, or
the measurement cannot see a wrong box. Gated on reader idle; the browser cell
is put back where it was.

    python scripts/check_overlay_hits.py [url ...]
"""

from __future__ import annotations

import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from live_probe import Probe, ReaderActed  # noqa: E402

PAGES = [
    "https://archive.org/",
    "https://www.youtube.com/",
    "https://www.imdb.com/",
    "https://duckduckgo.com/?q=patricia+trie&ia=web",
    "https://bandcamp.com/",
    "https://en.wikipedia.org/wiki/Okapi",
    "https://www.rfc-editor.org/rfc/rfc9110.html",
    "https://github.com/",
    "https://news.ycombinator.com/",
    "https://www.richardmille.com/",
]

B = 'app.workspace.getLeavesOfType("vertiscope-browser-view")[0].view'

# In the guest: the grid, the deep hit, the chunk, the box test. Read-only.
HITS = r"""(function(shift){
  var h = window.__vertiscopeSensor; if (!h || !h.at) return JSON.stringify({ error: 'no sensor' });
  function deep(x, y) {
    var el = document.elementFromPoint(x, y), guard = 0;
    while (el && el.shadowRoot && el.shadowRoot.elementFromPoint && guard++ < 16) {
      var inner = el.shadowRoot.elementFromPoint(x, y);
      if (!inner || inner === el) break;
      el = inner;
    }
    return el;
  }
  var tight = 0, displaced = 0, examples = [];
  var W = innerWidth, H = innerHeight, pts = 0, onChunk = 0, inside = 0, offBy = [], atMs = [], shadowPts = 0, shadowInside = 0;
  for (var y = 20; y < H - 10; y += 40) for (var x = 20; x < W - 10; x += 60) {
    pts++;
    var el = deep(x, y); if (!el) continue;
    var t0 = performance.now(), c = null;
    try { c = h.at(el); } catch (e) {}
    atMs.push(performance.now() - t0);
    if (!c || !c.box) continue;
    onChunk++;
    var b = c.box, bx = b[0] + shift, by = b[1] + shift;
    var inShadow = !!(el.getRootNode && el.getRootNode() !== document);
    if (inShadow) shadowPts++;
    var ok = x >= bx - 1 && x <= bx + b[2] + 1 && y >= by - 1 && y <= by + b[3] + 1;
    if (ok) { inside++; if (inShadow) shadowInside++; }
    else {
      offBy.push(Math.round(Math.max(bx - x, x - (bx + b[2]), by - y, y - (by + b[3]), 0)));
      // TIGHT: the box overlaps the element under the pointer -- drawn round
      // the chunk's content, the pointer on its container's padding. DISPLACED:
      // the box does not touch that element at all -- drawn somewhere else.
      var er = el.getBoundingClientRect();
      var meets = bx < er.right && bx + b[2] > er.left && by < er.bottom && by + b[3] > er.top;
      if (meets) tight++; else { displaced++; if (examples.length < 4) examples.push({ pt: [x, y], el: (el.tagName || '').toLowerCase(), el_rect: [er.left, er.top, er.width, er.height].map(Math.round), box: [bx, by, b[2], b[3]].map(Math.round) }); }
    }
  }
  atMs.sort(function(a, b){ return a - b; }); offBy.sort(function(a, b){ return a - b; });
  return JSON.stringify({ points: pts, on_chunk: onChunk, inside: inside, tight: tight, displaced: displaced, examples: examples, shadow_points: shadowPts, shadow_inside: shadowInside,
                          miss_px_p50: offBy.length ? offBy[offBy.length >> 1] : 0, miss_px_max: offBy.length ? offBy[offBy.length - 1] : 0,
                          at_ms_p50: atMs.length ? Math.round(atMs[atMs.length >> 1] * 1000) / 1000 : null,
                          at_ms_p99: atMs.length ? Math.round(atMs[Math.floor(atMs.length * 0.99)] * 1000) / 1000 : null });
})(%d)"""


def page_hits(p, url, settle=10):
    p.ev("(()=>{%s.go(%s);return 1})()" % (B, json.dumps(url)))
    t0 = time.time()
    while time.time() - t0 < 40:
        time.sleep(1); p.guard()
        try:
            if not p.ev("%s.webview.isLoading()" % B):
                break
        except Exception:
            pass
    time.sleep(settle); p.guard()
    out = {}
    for arm, shift, yclip in (("clean", 0, False), ("planted_shift40", 40, False), ("planted_yclip", 0, True)):
        # `planted_yclip`: the sensor's old vertical clip, flipped at run time.
        js = ("(function(){var h=window.__vertiscopeSensor;if(h&&h.plants)h.plants.yclip=%s;"
              "try{return %s}finally{if(h&&h.plants)h.plants.yclip=false}})()" % ("true" if yclip else "false", HITS % shift))
        got = p.ev("(async()=>%s.webview.executeJavaScript(%s))()" % (B, json.dumps(js)))
        out[arm] = json.loads(got) if got else None
    out["drawn"] = drawn_hits(p)
    return out


# The outline the plugin actually DRAWS (on a stored page, the union of the
# stored chunk's elements -- not the sensor's box): real pointer moves over a
# coarser grid, the overlay's own rect read back after each.
DRAWN = r"""(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const b = %s;
  const wc = window.require("@electron/remote").webContents.fromId(b.webview.getWebContentsId());
  const vp = JSON.parse(await b.webview.executeJavaScript("JSON.stringify([innerWidth, innerHeight])"));
  let n = 0, inside = 0, none = 0, displaced = 0;
  for (let y = 40; y < vp[1] - 20; y += 80) for (let x = 30; x < vp[0] - 20; x += 90) {
    wc.sendInputEvent({ type: "mouseMove", x: x - 3, y }); await sleep(30);
    wc.sendInputEvent({ type: "mouseMove", x, y }); await sleep(170);
    const h = b.pipebox && b.pipebox.hover;
    if (!h || !h.rect) { none++; continue; }
    n++;
    const r = h.rect;
    if (x >= r.x - 1 && x <= r.x + r.w + 1 && y >= r.y - 1 && y <= r.y + r.h + 1) inside++;
    else {
      // Displaced: the outline does not even reach the pointer's row or column band.
      const dx = Math.max(r.x - x, x - (r.x + r.w), 0), dy = Math.max(r.y - y, y - (r.y + r.h), 0);
      if (Math.max(dx, dy) > 40) displaced++;
    }
  }
  wc.sendInputEvent({ type: "mouseMove", x: -8, y: -8 }); wc.sendInputEvent({ type: "mouseLeave", x: -8, y: -8 });
  return JSON.stringify({ moves: n + none, outlined: n, inside, displaced_over_40px: displaced, no_outline: none });
})()"""


def drawn_hits(p):
    out = {}
    for arm, plant in (("clean", False), ("planted_stale_union", True)):
        p.ev("(()=>{const b=%s;if(b.pipebox)b.pipebox.plantStaleUnion=%s;return 1})()" % (B, "true" if plant else "false"))
        try:
            got = p.ev(DRAWN % B)
        finally:
            p.ev("(()=>{const b=%s;if(b.pipebox)b.pipebox.plantStaleUnion=false;return 1})()" % B)
        out[arm] = json.loads(got) if got else None
    return out


def main(argv):
    pages = argv or PAGES
    p = Probe()
    start = p.ev("%s.webview.getURL()" % B)
    rows = []
    try:
        for url in pages:
            r = page_hits(p, url)
            c = r.get("clean") or {}
            share = (c.get("inside", 0) / c["on_chunk"]) if c.get("on_chunk") else None
            yc = r.get("planted_yclip") or {}
            pl = r.get("planted_shift40") or {}
            pshare = (pl.get("inside", 0) / pl["on_chunk"]) if pl.get("on_chunk") else None
            rows.append({"url": url, "share_inside": None if share is None else round(share, 3),
                         "planted_share": None if pshare is None else round(pshare, 3),
                         "planted_yclip_displaced": yc.get("displaced"), "drawn": r.get("drawn"), **{k: c.get(k) for k in
                         ("points", "on_chunk", "inside", "tight", "displaced", "examples", "shadow_points", "shadow_inside", "miss_px_p50", "miss_px_max", "at_ms_p50", "at_ms_p99")}})
            print(json.dumps(rows[-1]))
    except ReaderActed as e:
        print("stopped:", e)
    finally:
        try:
            if start and start.startswith("http"):
                p.ev("(()=>{%s.go(%s);return 1})()" % (B, json.dumps(start)))
        except Exception:
            pass
    out = pathlib.Path(__file__).resolve().parent.parent / "build_analytics" / "overlay_hits.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
