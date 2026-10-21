"""G-201: uBlock Origin in the browser cell -- loaded, and blocking.

The extension's state as the plugin loaded it (`__vertiscopeAdblock`), then an
ad-heavy page (a recipe site, as the reader browses them) visited twice in
the browser cell: with uBlock loaded, and with it removed from the cell's
session (planted), the page reloaded each time. Scored on what reached the
network: the page's own resource entries whose host is a known ad/tracking
host. A request uBlock cancels never completes and is not an entry. The
extension is put back afterwards; the browser returns to where it was.
Reader-idle gated.
"""
import json
import sys
import time

sys.path.insert(0, r"<home>\Documents\vertiscope")
from vertiscope.obsidian.live import Live

live = Live()
if live.evaluate("window.__vertiscope.reader.idleMs()") < 60000:
    print("aborted: reader active"); sys.exit(1)
print("loaded:", json.dumps(live.json_eval("JSON.stringify(window.__vertiscopeAdblock || null)")))

PAGE = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1].startswith("http") else "https://www.allrecipes.com/recipe/25473/the-perfect-basic-burger/"
JS = r"""(async (planted, page) => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const b = app.workspace.getLeavesOfType("vertiscope-browser-view")[0].view;
  const ses = require("electron").remote.session.fromPartition("persist:vertiscope");
  const exts = ses.extensions || ses;
  const ub = (exts.getAllExtensions() || []).find((e) => /uBlock/i.test(e.name || ""));
  if (planted && ub) exts.removeExtension(ub.id);
  try {
    b.go("about:blank"); await sleep(800);
    b.go(page);
    await sleep(15000);
    const names = await b.webview.executeJavaScript("performance.getEntriesByType('resource').map(function(e){return e.name})");
    const ad = /(doubleclick|googlesyndication|googletagservices|adservice|adsystem|adnxs|taboola|outbrain|criteo|pubmatic|rubiconproject|openx|moatads|scorecardresearch|quantserve|amazon-adsystem|adsafeprotected|3lift|sharethrough|teads|casalemedia|indexww|smartadserver|yieldmo|gumgum|media\.net|krxd|bluekai|demdex|everesttech|bidswitch|chartbeat|connatix|primis|aniview)/i;
    const hosts = names.map((u) => { try { return new URL(u).host; } catch (e) { return ""; } });
    const adHits = hosts.filter((h) => ad.test(h));
    return JSON.stringify({ planted, resources: names.length, ad_requests: adHits.length,
                            ad_hosts: [...new Set(adHits)].slice(0, 12), ublock_present: !!ub });
  } finally {
    if (planted && ub) await exts.loadExtension(ub.path, { allowFileAccess: false });
  }
})"""
start = live.evaluate("app.workspace.getLeavesOfType('vertiscope-browser-view')[0].view.webview.getURL()")
rows = []
try:
    for planted in (False, True):
        r = json.loads(live.evaluate(JS + "(%s, %s)" % ("true" if planted else "false", json.dumps(PAGE))))
        print(json.dumps(r))
        rows.append(r)
finally:
    if start and start.startswith("http"):
        live.evaluate("(()=>{app.workspace.getLeavesOfType('vertiscope-browser-view')[0].view.go(%s); return 1})()" % json.dumps(start))
c, p = rows
ok = c["ublock_present"] and p["ad_requests"] > 0 and c["ad_requests"] <= 0.2 * p["ad_requests"]
print("G-201 %s: ad/tracking requests that reached the network %d with uBlock vs %d without (%d vs %d resources)"
      % ("PASS" if ok else "FAIL", c["ad_requests"], p["ad_requests"], c["resources"], p["resources"]))
