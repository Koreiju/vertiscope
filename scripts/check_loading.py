"""G-254: "loading takes several minutes instead of seconds" (2026-10-12).

The verbatim does not say WHAT was loading, and the row records that. This
probe times the spans a reader waits through in the running app (my reading
of "loading", marked as such in the PRD):

  reload   the plugin disabled and enabled -> enabled, -> the graph drawn
           (nodes on screen and holding still), -> the projector ready;
  chunks   the unit button pressed -> chunk view drawn (every chunk the
           projector holds, UMAP-only) -- the switch "loading" most likely
           named (the verbatim sits among chunk-view messages);
  pages    and back.

The cold first chunk view after a sidecar restart is measured by its own
evidence (G-179: 970 ms with `view_memo.pkl`, 125.4 s without).

Planted arm: the sidecar's per-page edge memo off (`/plant no-edge-memo`,
`layout.PLANT_NO_EDGE_MEMO`) -- every page's containment recomputed on every
chunk-view layout, as before 2026-10-24. The switch must slow, or this
cannot see slow loading.

Reader-idle gated; the reader's view (level) restored.

    python scripts/check_loading.py
"""
import json
import sys
import time
import urllib.request

sys.path.insert(0, r"<home>\Documents\domvec")
from domvec.obsidian.live import Live  # noqa: E402

SIDECAR = "http://127.0.0.1:8788"
GV = "app.workspace.getLeavesOfType('domvec-graph-view')[0]?.view"


def plant(name, on):
    req = urllib.request.Request(SIDECAR + "/plant", data=json.dumps({"name": name, "on": bool(on)}).encode(),
                                 headers={"Content-Type": "application/json", "X-Domvec-Client": "obsidian-plugin"})
    return json.load(urllib.request.urlopen(req, timeout=30))


def switch(live, to_chunks, limit_s=300, slow_remove=False):
    """Press the unit button; seconds until the target view is drawn, and
    until the window is SETTLED -- a full second with no task over 100 ms.
    Drawn is not done: leaving chunk view, the page view was drawn in 1.1 s
    and the window then froze 8.2 s removing 97k objects (2026-10-24)."""
    return live.evaluate("""(async () => {
      const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
      const v = %s; if (!v) return { error: "no graph view" };
      const btn = () => [...v.containerEl.querySelectorAll(".domvec-graph-bar button")].find((b) => /^(pages|chunks)$/.test(b.textContent.trim()));
      const n = () => v.graph ? v.graph.graphData().nodes.length : 0;
      const want = %s;
      if ((v.level === "chunk") === want) return { already: true };
      v.plantSlowRemove = %s;
      try {
        const t0 = performance.now(); btn().click();
        const arrived = () => want ? (v.level === "chunk" && v.umapOnly && n() > 2000) : (v.level !== "chunk" && n() > 0 && n() < 20000);
        while (performance.now() - t0 < %d && !arrived()) await sleep(100);
        const drawn = Math.round(performance.now() - t0) / 1000;
        // Settled: pinged through a MessageChannel, no gap over 100 ms for 1 s.
        const ch = new MessageChannel(); let last = performance.now(), calm = performance.now(), worst = 0;
        const settled = await new Promise((res) => {
          ch.port1.onmessage = () => { const now = performance.now(); const g = now - last; last = now;
            if (g > 100) { calm = now; worst = Math.max(worst, g); }
            if (now - calm >= 1000 || now - t0 > %d) res(Math.round(calm - t0) / 1000); else ch.port2.postMessage(0); };
          ch.port2.postMessage(0); });
        return { ok: arrived(), s: drawn, settled_s: settled, worst_gap_ms: Math.round(worst), nodes: n(),
                 detach: v.detachStats ? { ...v.detachStats } : null };
      } finally { v.plantSlowRemove = false; }
    })()""" % (GV, "true" if to_chunks else "false", "true" if slow_remove else "false", limit_s * 1000, limit_s * 1000), timeout=limit_s + 30)


def reload(live):
    t0 = time.time()
    live.evaluate("(async()=>{await app.plugins.disablePlugin('domvec-bridge');return 1})()")
    live.evaluate("(()=>{window.__dvReload='start';app.plugins.enablePlugin('domvec-bridge')"
                  ".then(()=>{window.__dvReload='done'},(e)=>{window.__dvReload='err '+e});return 1})()")
    out = {}
    last, still = -1, 0
    while time.time() - t0 < 180:
        time.sleep(0.25)
        st = live.evaluate("""(() => { const v = %s; const n = v && v.graph ? v.graph.graphData().nodes.length : 0;
          return { en: String(window.__dvReload), n, proj: !!(v && v.layoutMode === "projector") }; })()""" % GV)
        t = round(time.time() - t0, 2)
        if "enabled_s" not in out and st["en"] == "done":
            out["enabled_s"] = t
        if st["n"] > 0 and "first_nodes_s" not in out:
            out["first_nodes_s"] = t
        still = still + 1 if st["n"] and st["n"] == last else 0
        last = st["n"]
        if "drawn_s" not in out and still >= 8:          # 2 s holding still
            out["drawn_s"] = round(t - 2.0, 2); out["nodes"] = st["n"]
        if st.get("proj") and "projector_s" not in out:
            out["projector_s"] = t
        if "drawn_s" in out and ("projector_s" in out or t > 60):
            break
    return out


def main():
    live = Live()
    idle = live.evaluate("window.__domvec.reader.idleMs()")
    if idle < 60000:
        print(json.dumps({"aborted": "reader active %.0f s ago" % (idle / 1000)}))
        return 2
    stamp = live.evaluate("window.__domvecReaderAt || 0")
    level0 = live.evaluate("%s?.level || ''" % GV)
    out = {"reload": reload(live)}
    time.sleep(3)
    if level0 == "chunk":
        switch(live, False)
    out["clean"] = {"to_chunks": switch(live, True), "to_pages": switch(live, False)}
    try:
        out["plant"] = plant("no-edge-memo", True)
        out["planted"] = {"to_chunks": switch(live, True)}
    finally:
        plant("no-edge-memo", False)
    # Leaving chunk view by the old path: three.js removing each object.
    out["planted"]["to_pages_slow_remove"] = switch(live, False, slow_remove=True)
    if level0 == "chunk":
        switch(live, True)
    live.evaluate("(()=>{window.__domvecReaderAt=%d;return 1})()" % stamp)
    r, c, cp = out["reload"], out["clean"]["to_chunks"], out["clean"]["to_pages"]
    p, pp = out["planted"]["to_chunks"], out["planted"]["to_pages_slow_remove"]
    seconds = lambda x: x is not None and x < 30                                   # noqa: E731
    out["pass"] = (seconds(r.get("drawn_s")) and c.get("ok") and seconds(c.get("settled_s"))
                   and cp.get("ok") and seconds(cp.get("settled_s"))
                   # each planted arm slower where it should be
                   and (not p.get("ok") or p.get("s", 0) > c.get("s", 0))
                   and pp.get("settled_s", 0) > cp.get("settled_s", 0) + 2)
    print(json.dumps(out, indent=1))
    return 0 if out["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
