"""Is every picture, video and sound the reader can SEE in a chunk? (2026-10-06)

*"screenshot the page and then puzzle-piece the images from the chunks ...
until we clearly have fully detected all the possible elements and content
we're after."*

Against the page open in the browser cell of the running app:

1. The store's addresses for the page (`/page_map`: every chunk's element
   xpaths) are resolved IN the page by the sensor's own `resolve` -- the set
   of elements the trie accounts for.
2. Every media element in the composed tree (open shadow roots included) is
   enumerated: `img`, `picture`, `video`, `audio`, `canvas`, `iframe`, an
   `svg` with no svg ancestor, and any element painting a CSS
   `background-image: url(...)`. Each is COVERED when it, or the picture or
   video it sits in, is an element the trie holds; otherwise MISSING.
3. The cell is captured (`webContents.capturePage`) and every on-screen
   media element is outlined -- green covered, red missing -- so the result
   is a picture a person can check, not only a number.

**Denominators, named.** `visible` is what the reader can see right now
(in the viewport, non-zero box, not hidden); `all` is everything the page
holds. Detection is answerable for `all`; the screenshot shows `visible`.
A CSS background is counted separately: the trie has no detection kind
for it yet, so it is reported, not silently folded into "missing".

Read-only: nothing is written into the page; the reads run in the sensor's
isolated world.

Run: ``python -m vertiscope.analytics.media_coverage [--out PATH]``
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import sys
from pathlib import Path
from typing import Dict

from ..obsidian.live import Live

BV = "app.workspace.getLeavesOfType('vertiscope-browser-view')[0].view"

PAGE_JS = r"""(function(xs){
 var h = window.__vertiscopeSensor;
 var held = new Set(), unresolved = 0;
 for (var i = 0; i < xs.length; i++) {
   var n = null;
   try { n = h && h.node ? h.node(xs[i]) : null; } catch (e) { n = null; }
   if (!n) { try { n = document.evaluate(xs[i], document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue; } catch (e) { n = null; } }
   if (n && n.nodeType === 3) n = n.parentElement;
   if (n) held.add(n); else unresolved++;
 }
 var vw = innerWidth, vh = innerHeight, items = [];
 function inControl(el) {
   // An icon drawn INSIDE a control the trie holds (a link, a button) is part
   // of that control: counted apart from covered and from missing.
   for (var a = el.parentElement, k = 0; a && k < 6; a = a.parentElement, k++) {
     if ((a.tagName === 'A' || a.tagName === 'BUTTON' || a.getAttribute('role') === 'button') && held.has(a)) return true;
     if (a.parentElement === null && a.getRootNode && a.getRootNode().host) a = a.getRootNode().host;
   }
   return false;
 }
 function covered(el) {
   if (held.has(el)) return true;
   var p = el.parentElement;
   if (p && (p.tagName === 'PICTURE' || p.tagName === 'VIDEO' || p.tagName === 'AUDIO') && held.has(p)) return true;
   for (var c = el.firstElementChild; c; c = c.nextElementSibling) if (held.has(c)) return true;
   return false;
 }
 function src(el) {
   var t = el.tagName;
   if (t === 'IMG') return el.currentSrc || el.getAttribute('src') || el.getAttribute('data-src') || '';
   if (t === 'VIDEO' || t === 'AUDIO') return el.currentSrc || el.getAttribute('src') || el.getAttribute('poster') || '';
   if (t === 'IFRAME') return el.getAttribute('src') || '';
   return '';
 }
 function add(el, kind, url) {
   var r = el.getBoundingClientRect(), cs = getComputedStyle(el);
   var on = r.width > 1 && r.height > 1 && r.bottom > 0 && r.right > 0 && r.top < vh && r.left < vw
            && cs.visibility !== 'hidden' && cs.display !== 'none' && +cs.opacity > 0.02;
   var cov = kind === 'background' ? false : covered(el);
   items.push({kind: kind, url: String(url || '').slice(0, 200), covered: cov, in_control: !cov && inControl(el),
               visible: on, box: [r.left, r.top, r.width, r.height].map(Math.round), tag: el.tagName.toLowerCase()});
 }
 function walk(root) {
   var it = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT), el;
   while ((el = it.nextNode())) {
     var t = el.tagName;
     if (t === 'IMG') add(el, 'image', src(el));
     else if (t === 'VIDEO') add(el, 'video', src(el));
     else if (t === 'AUDIO') add(el, 'audio', src(el));
     else if (t === 'CANVAS') add(el, 'canvas', '');
     else if (t === 'IFRAME') add(el, 'iframe', src(el));
     else if ((t === 'svg' || t === 'SVG') && !(el.parentElement && el.parentElement.closest && el.parentElement.closest('svg'))) add(el, 'svg', '');
     var bi = '';
     try { bi = getComputedStyle(el).backgroundImage; } catch (e) {}
     if (bi && bi.indexOf('url(') >= 0) add(el, 'background', (bi.match(/url\(["']?([^"')]+)/) || [])[1]);
     if (el.shadowRoot) walk(el.shadowRoot);
   }
 }
 walk(document);
 return JSON.stringify({url: location.href, addresses: xs.length, unresolved: unresolved, held: held.size,
                        viewport: [vw, vh], items: items});
})"""


def measure(live: Live, out: str = "") -> Dict:
    url = live.evaluate(BV + ".webview.getURL()")
    pm = live.get("/page_map?url=" + __import__("urllib.parse", fromlist=["quote"]).quote(url.split("#")[0], safe=""))
    xs = sorted({x for v in (pm.get("chunks") or {}).values() for x in (v or [])})
    code = PAGE_JS + "(" + json.dumps(xs) + ")"
    got = json.loads(live.evaluate("(async()=>await %s.webview.executeJavaScript(%s))()" % (BV, json.dumps(code)),
                                   timeout=120))
    items = got["items"]

    def tally(rows):
        out = {}
        for r in rows:
            k = r["kind"]
            o = out.setdefault(k, {"n": 0, "covered": 0, "in_control": 0})
            o["n"] += 1
            o["covered"] += int(r["covered"])
            o["in_control"] += int(bool(r.get("in_control")))
        return out

    vis = [r for r in items if r["visible"]]
    report = {"url": got["url"], "store_chunks": len(pm.get("chunks") or {}), "addresses": got["addresses"],
              "unresolved": got["unresolved"], "all": tally(items), "visible": tally(vis),
              "missing_visible": [r for r in vis if not r["covered"]][:40]}
    # The picture: the cell captured, every on-screen media element outlined.
    shot = live.evaluate("(async()=>{const v=%s; const wc=window.require('@electron/remote').webContents.fromId(v.webview.getWebContentsId());"
                         " const img=await wc.capturePage(); return img.toDataURL();})()" % BV, timeout=60)
    if shot and str(shot).startswith("data:image"):
        from PIL import Image, ImageDraw
        im = Image.open(io.BytesIO(base64.b64decode(shot.split(",", 1)[1]))).convert("RGB")
        sx = im.width / max(1, got["viewport"][0])
        sy = im.height / max(1, got["viewport"][1])
        d = ImageDraw.Draw(im)
        for r in vis:
            x, y, w, h = r["box"]
            col = (40, 220, 90) if r["covered"] else ((255, 170, 0) if r["kind"] == "background" else (255, 40, 40))
            d.rectangle([x * sx, y * sy, (x + w) * sx, (y + h) * sy], outline=col, width=3)
        path = Path(out or "build_analytics/media_coverage.png")
        path.parent.mkdir(parents=True, exist_ok=True)
        im.save(path)
        report["picture"] = str(path)
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m vertiscope.analytics.media_coverage")
    ap.add_argument("--out", default="")
    args = ap.parse_args(argv)
    print(json.dumps(measure(Live(), args.out), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
