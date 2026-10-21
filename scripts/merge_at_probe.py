"""Hidden-window probe: with the sensor's `merge` variant on, what does `at()`
answer for each member of a field list, after one fold and after a second?"""
import json, sys
sys.path.insert(0, r"<home>\Documents\vertiscope")
from vertiscope.obsidian.live import Live
url = sys.argv[1] if len(sys.argv) > 1 else "https://archive.org/details/binocularvisions0000unse"
sel = sys.argv[2] if len(sys.argv) > 2 else "dl"
probe = r"""(function(S){var h=window.__ff;var dl=[...document.querySelectorAll(S)].find(function(e){return /Addeddate/.test(e.innerText||'');});if(!dl)return JSON.stringify({none:true});
var kids=[...dl.children].slice(0,14);return JSON.stringify(kids.map(function(k){var c=null;try{c=h.at(k);}catch(e){return [k.tagName,'threw '+e];}
var sl=h.slotOf?h.slotOf(k):'no slotOf';var ps=k.previousSibling,pt=ps?(ps.nodeType===1?ps.tagName:'#'+ps.nodeType):null;return [k.tagName,(k.innerText||'').trim().slice(0,14),c?c.id:null,sl,pt,getComputedStyle(k).display];}));})(%s)""" % json.dumps(sel)
print(Live().evaluate(r"""(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const v = app.workspace.getLeavesOfType("vertiscope-browser-view")[0].view;
  const src = (await v.sidecar.sensor()).source;
  const { BrowserWindow } = window.require("@electron/remote");
  const w = new BrowserWindow({ show: false, width: 1280, height: 900 });
  try {
    await w.loadURL(%s); await sleep(3000);
    const wc = w.webContents;
    await wc.executeJavaScriptInIsolatedWorld(1034, [{ code: '(function(){window.__ff=(' + src + ')({known:[],variants:{merge:true,semantic:true}});return 1;})()' }]);
    await sleep(800);
    const d1 = await wc.executeJavaScriptInIsolatedWorld(1034, [{ code: 'JSON.stringify((function(){var p=window.__ff.drain();return {chunks:(p.chunks||[]).length};})())' }]);
    const a1 = await wc.executeJavaScriptInIsolatedWorld(1034, [{ code: %s }]);
    await sleep(1500);
    const d2 = await wc.executeJavaScriptInIsolatedWorld(1034, [{ code: 'JSON.stringify((function(){var p=window.__ff.drain();return {chunks:(p.chunks||[]).length};})())' }]);
    const a2 = await wc.executeJavaScriptInIsolatedWorld(1034, [{ code: %s }]);
    return JSON.stringify({ drain1: JSON.parse(d1), at1: JSON.parse(a1), drain2: JSON.parse(d2), at2: JSON.parse(a2) });
  } finally { w.destroy(); }
})()""" % (json.dumps(url), json.dumps(probe), json.dumps(probe)), timeout=120))
