"""D-40 diagnosis: new topics the page adds while the reader scrolls -- do
their sensor chunk ids reach the host in a drain?

Live, in the plugin's browser cell, Julia's /latest (fresh query string):
the page's own MutationObserver records each added element of >= 40
characters; after a scroll of 15 wheel steps, each one's chunk id is read
from the sensor (`h.at`) -- at once, and the host's live traces for the
window are read: which ids they carried, and why the others were empty.
Prints both sides so the mismatch can be seen rather than inferred.

Reader-idle gated; the reader's page restored.
"""
import json, sys, time
sys.path.insert(0, r"<home>\Documents\vertiscope")
from vertiscope.obsidian.live import Live
live = Live()
if live.evaluate("window.__vertiscope.reader.idleMs()") < 60000:
    print("aborted: reader active"); sys.exit(1)
stamp = live.evaluate("window.__vertiscopeReaderAt || 0")
was = live.evaluate("app.workspace.getLeavesOfType('vertiscope-browser-view')[0].view.webview.getURL()")
PAGE = "https://discourse.julialang.org/latest?ids=%d" % int(time.time() * 1000)
JS = r"""(async (PAGE) => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const b = app.workspace.getLeavesOfType("vertiscope-browser-view")[0].view;
  b.go(PAGE);
  for (let i = 0; i < 100; i++) { await sleep(300); try { if (b.webview.getURL() === PAGE && !b.webview.isLoading()) break; } catch (e) {} }
  await sleep(5000);
  await b.webview.executeJavaScript(`(function () {
    var log = []; window.__idsProbe = log; window.__idsBefore = document.body.innerText;
    new MutationObserver(function (recs) { var t = Date.now();
      recs.forEach(function (r) { r.addedNodes.forEach(function (n) {
        if (n.nodeType === 1 && (n.textContent || '').trim().length >= 40) log.push({ t: t, el: n, tag: n.tagName, cls: String(n.className || '').slice(0, 40), text: n.textContent.trim().slice(0, 50) }); }); });
    }).observe(document.documentElement, { childList: true, subtree: true }); return 1; })()`);
  const pushes = [];
  const SIG = (window.__vertiscopeSignal || "");
  const onMsg = (e) => { const m = String((e && e.message) || ""); const i = m.indexOf("drain {"); if (i < 0) return;
    let ok = true, chunks = -1; try { const p = JSON.parse(m.slice(i + 6)); chunks = (p.chunks || []).length; } catch (x) { ok = false; }
    pushes.push({ len: m.length, ok, chunks, tail: ok ? "" : m.slice(-60) }); };
  b.webview.addEventListener("console-message", onMsg);
  const t0 = Date.now();
  for (let k = 0; k < 15; k++) { b.webview.sendInputEvent({ type: "mouseWheel", x: 300, y: 300, deltaX: 0, deltaY: -500 }); await sleep(400); }
  await sleep(4000);
  const t1 = Date.now();
  const seen = await b.webview.executeJavaScript(`(function () { var h = window.__vertiscopeSensor;
    return window.__idsProbe.slice(0, 400).map(function (m) { var g = null; try { g = h && h.at ? h.at(m.el) : null; } catch (x) {}
      return { fresh: window.__idsBefore.indexOf(m.text.split(String.fromCharCode(10))[0].trim().slice(0, 40)) < 0, t: m.t, tag: m.tag, cls: m.cls, text: m.text, id: g ? g.id : null, connected: m.el.isConnected,
               anc: g ? null : (function () { var e = m.el, d = 0; while (e && d < 8) { try { var a = h.at(e); if (a) return { id: a.id, up: d }; } catch (x) {} e = e.parentElement; d++; } return null; })() }; }); })()`);
  b.webview.removeEventListener("console-message", onMsg);
  const traces = window.__vertiscopeProfiler.list().filter((t) => t.url.startsWith("https://discourse.julialang.org/") && t.kind === "live"
    && typeof t.facts.host_epoch === "number" && t.facts.host_epoch >= t0 && t.facts.host_epoch <= t1 + 10000);
  const allT = window.__vertiscopeProfiler.list().filter((t) => (t.start || t.t0 || t.at || 0) >= 0).slice(-60);
  const kinds = {}; for (const t of allT) { const k = t.kind + "|" + (t.facts.why || t.facts.gated || t.outcome || t.facts.outcome || "") + "|" + (Array.isArray(t.facts.chunk_ids) ? t.facts.chunk_ids.length : "-") + "|" + String(t.url).slice(0, 45); kinds[k] = (kinds[k] || 0) + 1; }
  const traceKeys = allT.length ? Object.keys(allT[allT.length - 1]) : [];
  const carried = new Set(traces.flatMap((t) => t.facts.chunk_ids || []));
  const why = {}; for (const t of traces) { const w = t.facts.why || t.facts.outcome || "?"; why[w] = (why[w] || 0) + 1; }
  return JSON.stringify({ added: seen.length, with_id: seen.filter((s) => s.id).length, connected: seen.filter((s) => s.connected).length,
    answered: seen.filter((s) => s.id && carried.has(s.id)).length, fresh: seen.filter((s) => s.fresh).length,
    fresh_answered: seen.filter((s) => s.fresh && s.id && carried.has(s.id)).length, fresh_ids: [...new Set(seen.filter((s) => s.fresh).map((s) => s.id))].slice(0, 12), traces: traces.length, why, last60: kinds, traceKeys, pushes: pushes.length, push_failed: pushes.filter((x) => !x.ok).length, push_lens: pushes.map((x) => x.len).slice(0, 20), push_chunks: pushes.map((x) => x.chunks).slice(0, 20), fail_tail: (pushes.find((x) => !x.ok) || {}).tail, carried_sample: [...carried].slice(0, 8),
    seen_sample: seen.filter((s) => s.fresh).slice(0, 4) }, null, 1);
})"""
try:
    print(live.evaluate(JS + "(%s)" % json.dumps(PAGE), timeout=180))
finally:
    if was and was.startswith("http"):
        live.evaluate("(() => { app.workspace.getLeavesOfType('vertiscope-browser-view')[0].view.go(%s); return 1; })()" % json.dumps(was))
    live.evaluate("(()=>{window.__vertiscopeReaderAt = %s; return 1})()" % json.dumps(stamp))
