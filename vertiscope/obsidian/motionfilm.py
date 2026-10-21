"""Film the 3D view while the pipeline feeds it, and draw what was anomalous
onto what the reader saw (2026-09-29: "improve the fidelity of your MCP
tooling harness to capture the details of what anomalous and specific
behavior I'm describing").

Three instruments at once, on one clock:

* the plugin's flight recorder (`motion.ts`, `__vertiscope.motion`): every node's
  world and screen position per rendered frame, the velocity each force added
  to it, and the pipeline's events -- then teleports, vibration, drift,
  runaways, flicker (a node that vanished and came back), pulsing (a node
  whose drawn size keeps jumping), page churn, long links, and why nodes are
  not visible;
* screenshots of the graph canvas: what the reader saw;
* the inspection camera (`__vertiscope.inspect`): the open page rendered off
  screen at ITS scale, from the reader's viewing direction, without moving
  the reader's camera -- where an open page's 1,100 chunks are not a 9-pixel
  dot.

It writes an annotated overview, a contact sheet of the overview with each
anomaly's path drawn in, a contact sheet of the zoomed film, and the full
recorder result as JSON; it returns a summary small enough for a tool reply.
Read-only, except for the optional scroll-and-hover gesture it can drive.
"""

import base64
import io
import json
import time
from pathlib import Path
from typing import Dict, Optional

COLOURS = {"teleports": (255, 60, 60), "vibrating": (255, 220, 0), "drifting": (0, 220, 255),
           "flicker": (255, 120, 255), "pulsing": (120, 255, 120)}


def _js(live, body: str):
    return live.json_eval("(async () => JSON.stringify(await (async () => {" + body + "})()))()")


def _png(data: str):
    from PIL import Image
    return Image.open(io.BytesIO(base64.b64decode(data))).convert("RGB")


def inspect(live, url: str = "", size: int = 480, path: str = "") -> Dict:
    """One off-screen frame of a page at its own scale; writes the PNG."""
    got = _js(live, "return window.__vertiscope.inspect(%s, %d);" % (json.dumps(url), int(size)))
    if not got or got.get("error"):
        return got or {"error": "no reply"}
    out = Path(path) if path else Path("build_analytics") / ("inspect_%d.png" % int(time.time()))
    out.parent.mkdir(parents=True, exist_ok=True)
    _png(got["png"].split(",", 1)[1]).save(out)
    return {"path": str(out), "url": got["url"], "nodes": got["nodes"], "streaming": got["streaming"],
            "radius": got["radius"], "center": got["center"]}


def film(live, seconds: float = 16, drive_seconds: float = 8, url: str = "", out_dir: str = "",
         tag: str = "", reload: bool = False, every_s: float = 0.3,
         flags: Optional[Dict] = None, frames_on: bool = True) -> Dict:
    from PIL import Image, ImageDraw
    out = Path(out_dir or "build_analytics") / "motion"
    out.mkdir(parents=True, exist_ok=True)
    tag = tag or time.strftime("m%H%M%S")
    if reload:
        live.reload_plugin(settle=6)
        time.sleep(10)
    box = _js(live, """const v = app.workspace.getLeavesOfType('vertiscope-graph-view')[0].view;
      const r = v.graph.renderer().domElement.getBoundingClientRect();
      return { x: r.left, y: r.top, w: r.width, h: r.height };""")
    if not url:
        url = _js(live, "return app.workspace.getLeavesOfType('vertiscope-browser-view')[0].view.webview.getURL();")
    # A planted arm: view flags set for this run only (e.g. {"plantNoCalm": true}).
    flags = dict(flags or {})
    if flags:
        _js(live, "const v = app.workspace.getLeavesOfType('vertiscope-graph-view')[0].view; "
                  "Object.assign(v, %s); return true;" % json.dumps(flags))
    _js(live, "return window.__vertiscope.motion.start({ seconds: %s });" % float(seconds))
    if drive_seconds > 0:
        _js(live, "return window.__vertiscope.stress.start(%s);" % json.dumps(
            {"url": url, "seconds": drive_seconds, "segment": drive_seconds}))
    frames, zoom = [], []
    t0 = time.time()
    while time.time() - t0 < seconds + 0.5:
        t = time.time()
        ms = round((t - t0) * 1000)
        if not frames_on:
            # The null arm for the camera instruments: a screenshot forces a
            # composite and an inspection frame reads pixels back from the GPU,
            # and either can stall the frames being measured.
            time.sleep(every_s)
            continue
        try:
            shot = live._cdp("Page.captureScreenshot", {"format": "png", "clip": {
                "x": box["x"], "y": box["y"], "width": box["w"], "height": box["h"], "scale": 1}})
            frames.append((ms, _png(shot["data"])))
            # The page the cell SHOWS (after redirects), not the URL asked for.
            z = _js(live, "return window.__vertiscope.inspect('', 480);")
            if z and z.get("png"):
                zoom.append((ms, _png(z["png"].split(",", 1)[1]),
                             {p[0]: (p[1], p[2], p[3]) for p in z["points"]}, z["nodes"], z["streaming"], z["radius"]))
        except Exception:                           # noqa: BLE001 -- a lost frame is a gap, not a failure
            pass
        time.sleep(max(0.0, every_s - (time.time() - t)))
    res = None
    if flags:
        _js(live, "const v = app.workspace.getLeavesOfType('vertiscope-graph-view')[0].view; "
                  "Object.assign(v, %s); return true;" % json.dumps({k: False for k in flags}))
    for _ in range(40):
        st = _js(live, "return window.__vertiscope.motion.state();")
        if st.get("result"):
            res = st["result"]
            break
        time.sleep(1)
    if not res:
        return {"error": "the recorder returned nothing", "state": st}
    (out / (tag + ".json")).write_text(json.dumps(res), encoding="utf-8")

    def annotate(img, upto=None):
        im = img.copy()
        d = ImageDraw.Draw(im)
        for kind, col in COLOURS.items():
            for k, a in enumerate(res.get(kind, [])[:8]):
                pts = [(p[0], p[1]) for p in a["track"] if upto is None or p[2] <= upto]
                pts = [p for p in pts if -2000 < p[0] < 4000 and -2000 < p[1] < 4000]
                if len(pts) > 1:
                    d.line(pts, fill=col, width=2)
                if pts:
                    x, y = pts[-1]
                    d.ellipse([x - 4, y - 4, x + 4, y + 4], outline=col, width=2)
                    if upto is None:
                        d.text((x + 6, y - 6), "%s%d %s" % (kind[0].upper(), k, a["name"][:22]), fill=col)
        return im

    paths = {"json": str(out / (tag + ".json"))}
    if frames:
        annotate(frames[-1][1]).save(out / (tag + "_annotated.png"))
        paths["annotated"] = str(out / (tag + "_annotated.png"))
        pick = frames[:: max(1, len(frames) // 12)][:12]
        w, h = frames[0][1].size
        tw, th = w // 2, h // 2
        sheet = Image.new("RGB", (4 * tw, ((len(pick) + 3) // 4) * th), (20, 20, 20))
        dd = ImageDraw.Draw(sheet)
        for i, (ms, im) in enumerate(pick):
            sheet.paste(annotate(im, ms).resize((tw, th)), ((i % 4) * tw, (i // 4) * th))
            dd.text(((i % 4) * tw + 6, (i // 4) * th + 4), "t=%d ms" % ms, fill=(255, 255, 0))
        sheet.save(out / (tag + "_sheet.png"))
        paths["sheet"] = str(out / (tag + "_sheet.png"))
    zoom_jumps = []
    if zoom:
        for (ta, _ia, pa, *_x), (tb, _ib, pb, *_y) in zip(zoom, zoom[1:]):
            for k, (fa, xa, ya) in pa.items():
                if k in pb:
                    fb, xb, yb = pb[k]
                    zoom_jumps.append((((xb - xa) ** 2 + (yb - ya) ** 2) ** 0.5, k, bool(fa), ta, tb))
        zoom_jumps.sort(reverse=True)
        big = {j[1] for j in zoom_jumps[:25]}
        zs = zoom[:: max(1, len(zoom) // 16)][:16]
        zt = zs[0][1].size[0] // 2
        zsheet = Image.new("RGB", (4 * zt, ((len(zs) + 3) // 4) * zt), (20, 20, 20))
        zd = ImageDraw.Draw(zsheet)
        for i, (ms, im, pts, nn, ns, rad) in enumerate(zs):
            im2 = im.copy()
            d2 = ImageDraw.Draw(im2)
            for k, (_f, x, y) in pts.items():
                if k in big:
                    d2.ellipse([x - 6, y - 6, x + 6, y + 6], outline=(255, 60, 60), width=2)
            zsheet.paste(im2.resize((zt, zt)), ((i % 4) * zt, (i // 4) * zt))
            zd.text(((i % 4) * zt + 4, (i // 4) * zt + 3), "t=%d  %s nodes, %s streaming, r=%s" % (ms, nn, ns, rad),
                    fill=(255, 255, 0))
        zsheet.save(out / (tag + "_zoom.png"))
        paths["zoom"] = str(out / (tag + "_zoom.png"))
    events: Dict[str, int] = {}
    for e in res.get("events", []):
        events[e["kind"]] = events.get(e["kind"], 0) + 1
    summary = {k: res.get(k) for k in ("seconds", "frames", "fps", "moving_per_frame", "alpha", "visibility", "stalls",
                                       "counts", "world_scale", "stacked", "clumps", "force_totals", "links",
                                       "page_churn", "camera_moved_frames")}
    for kind in ("teleports", "runaway", "vibrating", "drifting", "flicker", "pulsing"):
        summary[kind] = [{k: v for k, v in a.items() if k != "track"} for a in res.get(kind, [])[:5]]
    summary["events"] = events
    summary["zoom"] = {"frames": len(zoom), "radius": [z[5] for z in zoom][::4],
                       "largest_jumps_px": [(round(j[0]), j[1], "streaming" if j[2] else "stored", j[3], j[4])
                                            for j in zoom_jumps[:8]]}
    # On the page being driven, and everywhere else: scrolling one page must
    # not shake the others. The page's URL as the cell ended on it: a tag page
    # redirects (/tag/question -> /tag/question/3), and judging by the URL
    # asked for put every node of the driven page "elsewhere".
    try:
        url = _js(live, "return app.workspace.getLeavesOfType('vertiscope-browser-view')[0].view.webview.getURL();") or url
    except Exception:                           # noqa: BLE001
        pass
    by = res.get("by_url") or {}
    summary["on_page_vs_elsewhere"] = {
        k: {"on_page": sum(n for uu, n in by.get(k, []) if uu.split("#")[0] == url.split("#")[0]),
            "elsewhere": sum(n for uu, n in by.get(k, []) if uu.split("#")[0] != url.split("#")[0])}
        for k in ("teleports", "vibrating", "drifting", "pulsing")}
    summary["by_url"] = by
    summary["url"] = url
    summary["flags"] = flags
    summary["files"] = paths
    return summary
