"""Do a live page's stored lines carry addresses whose element holds their text?
arXiv's listing, captured fresh in the browser cell; read-only in the page."""
import sys, json, time
sys.path.insert(0, r"<home>\Documents\vertiscope\scripts")
from live_probe import Probe
p = Probe()
if p.ev("window.__vertiscope.reader.idleMs()") < 60000:
    print("reader active: not run"); sys.exit(0)
B = 'app.workspace.getLeavesOfType("vertiscope-browser-view")[0].view'
V = 'app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view'
URL = sys.argv[1] if len(sys.argv) > 1 else "https://arxiv.org/list/stat.ML/recent"
start = p.ev("%s.webview.getURL()" % B)
p.ev("(()=>{%s.go(%s);return 1})()" % (B, json.dumps(URL)))
time.sleep(8)
URL = p.ev("%s.webview.getURL()" % B) or URL
print("landed on", URL)
try:
    for _ in range(240):
        time.sleep(1)
        n = p.ev("(async()=>(await %s.sidecar.pageCids(%s)).length)()" % (V, json.dumps(URL)))
        if n and n > 20: break
    time.sleep(15)
    JS = r"""(async (U) => {
      const b = %s, v = %s;
      const cids = await v.sidecar.pageCids(U);
      const rows = [];
      for (const c of cids) {
        const pay = await v.sidecar.chunk(c).catch(() => null);
        const ls = (pay && pay.lines) || [];
        // PLANTED arm: the old positional zip -- the keys present, gaps closed, onto the lines.
        const compact = ls.map((l) => String(l.key || "")).filter(Boolean);
        for (let li = 0; li < ls.length; li++) {
          const l = ls[li];
          const k = PLANTED ? (compact[li] || "") : String(l.key || ""); const xp = k.split("|")[1] || "";
          if (!xp || !/\/text\(\)(\[\d+\])?$/.test(xp)) continue;   // text-node addresses only
          rows.push([c, String(l.text || ""), xp]);
        }
      }
      // The live element at each stored xpath, read in the page.
      const live = await b.webview.executeJavaScript("(function(xs){return xs.map(function(x){try{var n=document.evaluate(x,document,null,XPathResult.FIRST_ORDERED_NODE_TYPE,null).singleNodeValue;return n?String(n.textContent||n.nodeValue||'').replace(/\\s+/g,' ').slice(0,300):null}catch(e){return null}})})(" + JSON.stringify(rows.map((r) => r[2])) + ")");
      let held = 0, wrong = 0, gone = 0, worded = 0; const ex = [];
      const words = (t) => (t.replace(/\[([^\]]*)\]\([^)]*\)/g, "$1").match(/[A-Za-z]{3,}/g) || []).slice(0, 1);   // the FIRST word: a line is keyed at its first text node
      rows.forEach((r, i) => {
        const w = words(r[1]); if (!w.length) return; worded++;
        const t = live[i];
        if (t == null) { gone++; return; }
        if (w.every((x) => t.includes(x))) held++;
        else { wrong++; if (ex.length < 6) ex.push({ text: r[1].slice(0, 50), at: r[2].slice(-45), live: t.slice(0, 50) }); }
      });
      return JSON.stringify({ chunks: cids.length, lines: rows.length, worded, held, wrong, gone, ex });
    })"""
    for planted in (False, True):
        print("planted" if planted else "clean  ", p.ev(JS.replace("PLANTED", "true" if planted else "false") % (B, V) + "(%s)" % json.dumps(URL)))
finally:
    if start and start.startswith("http"):
        p.ev("(()=>{%s.go(%s);return 1})()" % (B, json.dumps(start)))
