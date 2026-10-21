"""How many pollers ask the sidecar for `/page_status`, and from where?

One pipeline box polls once a second (twice collapsed). The sidecar's
request log showed 8-9 a second, each 0.6-3.9 s, until it stopped
answering (2026-10-19). For `secs`, every `fetch` of `/page_status` in the
app is counted by its caller's stack, so leaked pollers from earlier plugin
loads show as separate call sites (their code is the OLD bundle).

Read-only; `fetch` is put back.
"""
import json, sys
sys.path.insert(0, r"<home>\Documents\vertiscope")
from vertiscope.obsidian.live import Live
secs = int(next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--secs=")), "5"))
JS = r"""(async (secs) => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const orig = window.fetch, seen = [];
  window.fetch = function (u, o) {
    const s = String((u && u.url) || u);
    if (s.includes("page_status")) {
      const lines = String(new Error().stack || "").split(String.fromCharCode(10)).slice(2, 5);
      seen.push(lines.map((x) => x.trim().slice(0, 90)).join(" < "));
    }
    return orig.apply(this, arguments);
  };
  try { await sleep(secs * 1000); } finally { window.fetch = orig; }
  const by = {};
  for (const s of seen) by[s] = (by[s] || 0) + 1;
  return JSON.stringify({ secs, calls: seen.length, per_s: Math.round(seen.length / secs * 10) / 10,
                          browser_leaves: app.workspace.getLeavesOfType("vertiscope-browser-view").length, by }, null, 1);
})"""
print(Live().evaluate(JS + "(%d)" % secs, timeout=secs + 20))
