"""G-193: "first priority a COMPLETE projection of the page: every vectorised
chunk of the url projected".

A fresh page (cache-busted, so the store has none of it) streamed through a
HIDDEN browser cell; `/page_status` polled each second for its stored,
embedded and projected chunk counts. Reported: when each first appeared, and
when the page was COMPLETE (projected == embedded == stored, holding for 3 s).

Reader-idle gated.    python scripts/check_page_projection.py [url ...]
"""
import json
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, r"<home>\\Documents\\domvec")
from domvec.obsidian.live import Live  # noqa: E402

B = "http://127.0.0.1:8788"
DEFAULT = ["https://en.wikipedia.org/wiki/Suffix_array", "https://en.wikipedia.org/wiki/Rope_(data_structure)"]


def status(url):
    with urllib.request.urlopen(B + "/page_status?url=" + urllib.parse.quote(url, safe=""), timeout=60) as r:
        return json.load(r)


def one(live, base):
    url = "%s?g193=%d" % (base, int(time.time() * 1000))
    live.evaluate("""(() => { const c = app.workspace.getLeavesOfType('domvec-browser-view').map(l => l.view)
      .find(v => !(v.containerEl && v.containerEl.offsetWidth > 0)); if (!c) return 0; c.go(%s); return 1; })()""" % json.dumps(url))
    t0 = time.time()
    first = {}
    complete_at, held = None, 0
    last = {}
    while time.time() - t0 < 180:
        time.sleep(1)
        try:
            st = status(url)
        except Exception:                           # noqa: BLE001
            continue
        stored = int(st.get("chunks") or 0)
        emb = int(st.get("embedded") or 0)
        proj = int(st.get("projected") or 0)
        last = {"stored": stored, "embedded": emb, "projected": proj}
        t = round(time.time() - t0, 1)
        for k, v in (("stored", stored), ("embedded", emb), ("projected", proj)):
            if v and k not in first:
                first[k] = t
        if stored and emb == stored and proj == emb:
            held += 1
            if complete_at is None:
                complete_at = t
            if held >= 3:
                break
        else:
            held, complete_at = 0, None
    return {"url": url[-50:], "first_s": first, "complete_s": complete_at, "last": last}


def main():
    live = Live()
    idle = live.evaluate("window.__domvec.reader.idleMs()")
    if idle < 60000:
        print(json.dumps({"aborted": "reader active %.0f s ago" % (idle / 1000)}))
        return 2
    stamp = live.evaluate("window.__domvecReaderAt || 0")
    out = []
    try:
        for u in (sys.argv[1:] or DEFAULT):
            out.append(one(live, u))
    finally:
        live.evaluate("(()=>{window.__domvecReaderAt=%d;return 1})()" % stamp)
    print(json.dumps(out, indent=1))
    return 0 if all(r["complete_s"] is not None for r in out) else 1


if __name__ == "__main__":
    raise SystemExit(main())
