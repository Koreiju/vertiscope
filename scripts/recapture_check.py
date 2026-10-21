"""Recapture pages in the browser cell (reader idle) and read what the STORE
now holds: the comparison table's Konqueror row (G-152) and culinarypedia's
headings (G-143). Returns the cell to the page it started on."""
import json, re, sys, time, urllib.parse, urllib.request
sys.path.insert(0, "scripts")
from live_probe import Probe

B = 'app.workspace.getLeavesOfType("vertiscope-browser-view")[0].view'
SC = "http://127.0.0.1:8788"
CWB = "https://en.wikipedia.org/wiki/Comparison_of_web_browsers"
CUL = "https://culinarypedia.com/2026/05/01/the-best-chicken-dishes-from-diners-drive-ins-anddives/"


def get(path):
    return json.load(urllib.request.urlopen(SC + path, timeout=120))


def captured(p, url, since):
    last = None
    t0 = time.time()
    while time.time() - t0 < 300:
        time.sleep(5); p.guard()
        caps = [r for r in get("/profile").get("capture", []) if r["url"] == url and r["at"] > since]
        if caps and len(caps) == last and time.time() - caps[-1]["at"] > 12:
            return caps
        last = len(caps)
    return []


def stored_lines(url):
    pm = get("/page_map?url=" + urllib.parse.quote(url, safe=""))["chunks"]
    out = []
    for cid in pm:
        c = get("/chunk/" + cid)
        out.append((cid, c.get("xpath", ""), [l["text"] for l in c.get("lines", [])],
                    [(l.get("key") or "").split("|")[1] if "|" in (l.get("key") or "") else "" for l in c.get("lines", [])]))
    return out


def main():
    p = Probe()
    back = p.ev(B + ".webview.getURL()")
    out = {}
    try:
        t0 = time.time()
        if back == CWB:
            p.ev("(()=>{%s.webview.reload();return 1})()" % B)
        else:
            p.ev("(()=>{%s.go(%s);return 1})()" % (B, json.dumps(CWB)))
        caps = captured(p, CWB, t0)
        rows = [(x, t) for _c, _x, ts, xs in stored_lines(CWB) for t, x in zip(ts, xs) if "section[2]/table/tbody/tr[88]/" in x]
        out["G-152"] = {"captures": len(caps), "written": sum((r.get("dirty") or 0) - (r.get("unchanged_skipped") or 0) for r in caps),
                        "tr88": [t.strip()[:28] for _x, t in rows][:6]}
        t1 = time.time()
        p.ev("(()=>{%s.go(%s);return 1})()" % (B, json.dumps(CUL)))
        caps = captured(p, CUL, t1)
        H = re.compile(r"\s*#{1,6} ")
        heads = []
        for _cid, x, ts, _xs in stored_lines(CUL):
            for j, t in enumerate(ts):
                if H.match(t) and "/article/" in x + "/":
                    heads.append((j, len(ts)))
        out["G-143"] = {"captures": len(caps), "headings": len(heads), "opening": sum(1 for j, _n in heads if j == 0),
                        "closing": sum(1 for j, n in heads if j == n - 1 and n > 1)}
    finally:
        p.ev("(()=>{%s.go(%s);return 1})()" % (B, json.dumps(back)))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
