"""G-13: "Re-projections over umaps can be batched in a queue at a latency
that adapts to match the time scaling of the umap updates."

Two arms on the running app, the same pages streamed through a HIDDEN browser
cell (the reader's visible page is left alone), each page cache-busted so
every chunk is new and goes through the projector's queue:

  adaptive  the queue waits, from its oldest item, as long as a drain costs;
  fixed     planted `/plant fixed-batch` -- drained the moment it is woken.

Per arm, from the projector's own status: drains, chunks placed, chunks per
drain, and each placed chunk's wait in the queue (p50 / p95). The window
should put more chunks into each drain and keep their wait near the drain's
own cost.

Reader-idle gated.    python scripts/check_batch_window.py
"""
import json
import sys
import time
import urllib.request

sys.path.insert(0, r"<home>\\Documents\\domvec")
from domvec.obsidian.live import Live  # noqa: E402

SIDECAR = "http://127.0.0.1:8788"
PAGES = ["https://en.wikipedia.org/wiki/Bloom_filter", "https://en.wikipedia.org/wiki/Count%E2%80%93min_sketch",
         "https://en.wikipedia.org/wiki/HyperLogLog", "https://en.wikipedia.org/wiki/Skip_list"]


def status():
    with urllib.request.urlopen(SIDECAR + "/projector", timeout=30) as r:
        return json.load(r)["batching"]


def plant(on, name="fixed-batch"):
    req = urllib.request.Request(SIDECAR + "/plant", data=json.dumps({"name": name, "on": bool(on)}).encode(),
                                 headers={"Content-Type": "application/json", "X-Domvec-Client": "obsidian-plugin"})
    return json.load(urllib.request.urlopen(req, timeout=30))


def arm(live, tag):
    before = status()
    for u in PAGES:
        url = "%s?g13=%s%d" % (u, tag, int(time.time() * 1000))
        live.evaluate("""(() => { const c = app.workspace.getLeavesOfType('domvec-browser-view').map(l => l.view)
          .find(v => !(v.containerEl && v.containerEl.offsetWidth > 0)); if (!c) return 0; c.go(%s); return 1; })()""" % json.dumps(url))
        time.sleep(25)
    time.sleep(30)                                   # the embedder and the queue catch up
    after = status()
    drains = after["drains"] - before["drains"]
    placed = after["batched"] - before["batched"]       # chunks taken off the queue
    new = after["waits_seen"] - before["waits_seen"]
    waits = sorted(after["waits_tail"][-new:]) if new > 0 else []
    q = lambda p: waits[min(len(waits) - 1, int(p * len(waits)))] if waits else None  # noqa: E731
    return {"drains": drains, "placed": placed, "per_drain": round(placed / drains, 2) if drains else None,
            "wait_p50_ms": q(0.5), "wait_p95_ms": q(0.95), "waits": len(waits),
            "cost_ms": after["cost_ms"], "window_ms": after["window_ms"], "windows": after["windows"] - before["windows"]}


def main():
    live = Live()
    idle = live.evaluate("window.__domvec.reader.idleMs()")
    if idle < 60000:
        print(json.dumps({"aborted": "reader active %.0f s ago" % (idle / 1000)}))
        return 2
    stamp = live.evaluate("window.__domvecReaderAt || 0")
    out = {}
    try:
        # Fixed FIRST: the arm that runs right after a start meets the
        # start's backlog, and that should not be the adaptive one's waits.
        plant(False, "adaptive-window")
        out["fixed"] = arm(live, "f")
        plant(True, "adaptive-window")
        out["adaptive"] = arm(live, "a")
    finally:
        plant(False, "adaptive-window")
        plant(False)
        live.evaluate("(()=>{window.__domvecReaderAt=%d;return 1})()" % stamp)
    a, f = out["adaptive"], out["fixed"]
    # Does the window EARN its place? A quarter more chunks per drain, for at
    # most twice the wait. (2026-10-24: +6% for 4.5x the wait -- it did not,
    # and it is off by default.)
    out["window_helps"] = bool(a["drains"] and f["drains"] and a["per_drain"] and f["per_drain"]
                               and a["per_drain"] >= 1.25 * f["per_drain"]
                               and (a["wait_p50_ms"] or 0) <= 2 * max(1.0, f["wait_p50_ms"] or 0))
    out["pass"] = bool(a["windows"] > 0 and f["drains"] and a["drains"])          # both arms measured
    print(json.dumps(out, indent=1))
    return 0 if out["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
