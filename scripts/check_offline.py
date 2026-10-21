"""G-59..G-62 live, in the browser cell, reader idle.

1. G-60  save offline ON, land on a stored page: it is saved as presented.
2. G-61/62  the cell emulates "offline"; navigating to that page fails to
         load and the saved form opens from a local file -- INFILLED when it
         holds too little of the trace: its own layout AND a `.dv-infill`
         block of the chunks it lacked.
3. G-61/62  a stored page never saved opens REBUILT from the scan trace.
4. G-59  offline, a chunk's panel docks into a main pane (planted
         `plantOfflineBillboard`: it stays a billboard).
Restored after: emulation off, save offline back to its setting, the cell on
the page it started on.
"""
import json
import sys
import time

sys.path.insert(0, "scripts")
from live_probe import Probe, ReaderActed  # noqa: E402

B = 'app.workspace.getLeavesOfType("vertiscope-browser-view")[0].view'
V = 'app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view'
SAVED_URL = sys.argv[1] if len(sys.argv) > 1 else "https://en.wikipedia.org/wiki/Okapi"
TRACED_URL = sys.argv[2] if len(sys.argv) > 2 else "https://en.wikipedia.org/wiki/Axolotl"

# Offline through Chromium's own protocol, on the cell's webContents only: a
# session-level emulation let both pages load from the HTTP cache, so nothing
# failed and nothing switched (the first run). The cache is off while offline.
EMULATE = """(async()=>{const b=%s;const off=%s;const wc=window.require("@electron/remote").webContents.fromId(b.webview.getWebContentsId());
const d=wc.debugger;if(!d.isAttached())d.attach("1.3");
await d.sendCommand("Network.enable");
await d.sendCommand("Network.emulateNetworkConditions",{offline:off,latency:0,downloadThroughput:-1,uploadThroughput:-1});
await d.sendCommand("Network.setCacheDisabled",{cacheDisabled:off});
if(!off)d.detach();return 1})()"""


def land(p, url, wait_s=40):
    p.ev("(()=>{%s.go(%s);return 1})()" % (B, json.dumps(url)))
    t0 = time.time()
    while time.time() - t0 < wait_s:
        time.sleep(1)
        p.guard()
        try:
            if p.ev(B + ".webview.getURL()") and not p.ev(B + ".webview.isLoading()"):
                return p.ev(B + ".webview.getURL()")
        except Exception:                       # noqa: BLE001
            pass
    return p.ev(B + ".webview.getURL()")


def wait_offline(p, url, cap_s=90):
    """Until the cell shows the offline form of `url` (a local file), or cap_s."""
    t0 = time.time()
    while time.time() - t0 < cap_s:
        time.sleep(1); p.guard()
        try:
            cur = p.ev(B + ".webview.getURL()") or ""
            if p.ev(B + ".offlineFor") == url and cur.startswith("file:") and not p.ev(B + ".webview.isLoading()"):
                return round(time.time() - t0, 1)
        except Exception:                       # noqa: BLE001
            pass
    return None


def page_text(p):
    return p.ev("(async()=>{try{return await %s.webview.executeJavaScript('document.body?document.body.innerText:\"\"')}catch(e){return ''}})()" % B) or ""


def layout(p):
    """The saved page's own layout (Wikipedia's `#mw-content-text`), and what
    was infilled into it. The traced page is the null arm: no saved layout."""
    return json.loads(p.ev("(async()=>await %s.webview.executeJavaScript(`JSON.stringify({"
                           "saved_layout:!!document.querySelector('#mw-content-text'),"
                           "infill_chunks:document.querySelectorAll('.dv-infill .dv-chunk').length,"
                           "infill_note:(document.querySelector('.dv-infill-note')||{}).textContent||''})`))()" % B))


def dock_check(p, url, plant):
    return json.loads(p.ev("""(async()=>{const v=%s;const sleep=(ms)=>new Promise(r=>setTimeout(r,ms));
      v.plantOfflineBillboard=%s;const d0=v.docked;
      const cids=await v.sidecar.pageCids(%s);let n=null;
      for(const id of cids.slice(0,30)){n=v.graph.graphData().nodes.find(x=>x.id===id);if(!n){const g=await v.sidecar.place([id]);if(g&&g.nodes)v.absorb(g.nodes,g.edges);n=v.graph.graphData().nodes.find(x=>x.id===id);}if(n)break;}
      if(!n)return JSON.stringify({error:"no placeable chunk"});
      for(const bb of v.billboardState())v.closeBillboard(bb.id);
      await v.openBillboard(n);await sleep(2500);
      const pane=app.workspace.getLeavesOfType("vertiscope-panel-view")[0];
      const inPane=!!(pane&&pane.view.contentEl.querySelector('.vertiscope-bb[data-cid="'+n.id+'"]'));
      const inGraph=!!v.containerEl.querySelector('.vertiscope-bb[data-cid="'+n.id+'"]');
      const text=(pane&&inPane)?pane.view.contentEl.innerText.trim().length:0;
      v.closeBillboard(n.id);v.plantOfflineBillboard=false;
      return JSON.stringify({docked:v.docked-d0,in_pane:inPane,in_graph:inGraph,pane_chars:text});})()"""
                           % (V, "true" if plant else "false", json.dumps(url))))


def main():
    p = Probe()
    start = p.ev(B + ".webview.getURL()")
    setting = p.ev('app.plugins.getPlugin("vertiscope-bridge").settings.saveOffline')
    out = {}
    try:
        # 1. G-60
        p.ev('(async()=>{const pl=app.plugins.getPlugin("vertiscope-bridge");pl.settings.saveOffline=true;await pl.saveSettings();return 1})()')
        land(p, SAVED_URL)
        t0 = time.time()
        while time.time() - t0 < 60 and not p.ev(B + ".offlineStats.saved"):
            time.sleep(2); p.guard()
        out["G-60"] = {"stats": p.ev("JSON.stringify(%s.offlineStats)" % B),
                       "info": p.ev("(async()=>JSON.stringify(await %s.sidecar.offlineInfo(%s)))()" % (B, json.dumps(SAVED_URL)))}
        live_text = page_text(p)
        # 2. G-62, the saved form
        p.ev(EMULATE % (B, "true"))
        p.ev("(()=>{%s.offlineFor='';return 1})()" % B)
        land(p, "about:blank", 10)
        land(p, SAVED_URL)
        opened_s = wait_offline(p, SAVED_URL)
        got = p.ev(B + ".webview.getURL()")
        txt = page_text(p)
        words = set(w for w in live_text.split() if len(w) > 4)
        seen = set(w for w in txt.split() if len(w) > 4)
        out["G-61/62 saved"] = {"url": got[:60], "offlineFor": p.ev(B + ".offlineFor"), "chars": len(txt), "opened_after_s": opened_s,
                                "live_words_present": round(len(words & seen) / max(1, len(words)), 3),
                                "form": p.ev("JSON.stringify(%s.offlineStats.last)" % B), **layout(p)}
        # 4. G-59 while offline: docked, and planted
        out["G-59"] = [dock_check(p, SAVED_URL, False), dock_check(p, SAVED_URL, True)]
        # 3. G-61/62, the traced form (a page never saved)
        p.ev("(()=>{%s.offlineFor='';return 1})()" % B)
        land(p, TRACED_URL)
        opened_t = wait_offline(p, TRACED_URL)
        txt = page_text(p)
        out["G-62 traced"] = {"url": p.ev(B + ".webview.getURL()")[:60], "offlineFor": p.ev(B + ".offlineFor"), "opened_after_s": opened_t,
                              "chars": len(txt), "banner": txt[:240].replace("\n", " "), **layout(p),
                              "pictures": p.ev("(async()=>await %s.webview.executeJavaScript('document.images.length'))()" % B),
                              "pictures_loaded": p.ev("(async()=>await %s.webview.executeJavaScript('[...document.images].filter(i=>i.complete&&i.naturalWidth>0).length'))()" % B)}
        out["stats"] = p.ev("JSON.stringify(%s.offlineStats)" % B)
    except ReaderActed as e:
        out["stopped"] = str(e)
    finally:
        p.ev(EMULATE % (B, "false"))
        p.ev('(async()=>{const pl=app.plugins.getPlugin("vertiscope-bridge");pl.settings.saveOffline=%s;await pl.saveSettings();return 1})()'
             % ("true" if setting else "false"))
        p.ev("(()=>{%s.offlineFor='';return 1})()" % B)
        for l in ("vertiscope-panel-view",):
            p.ev('(()=>{app.workspace.detachLeavesOfType("%s");return 1})()' % l)
        land(p, start)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
