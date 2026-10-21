"""The sensor's chunking of one element set on a FRESH load, in a hidden window
(the reader's page is untouched). Reports, per element matching SEL, its chunk
id and box: after the first fold, and again after WAIT seconds of the page's
own mutations (the repair path).

  python fresh_fold.py <url> <css-selector-of-the-container> [<text-filter>]
"""
import json, sys
sys.path.insert(0, r"<home>\Documents\vertiscope")
from vertiscope.obsidian.live import Live

url, sel = sys.argv[1], sys.argv[2]
flt = sys.argv[3] if len(sys.argv) > 3 else ""
L = Live()
probe = r"""(function(){var h=window.__ff;var rows=[...document.querySelectorAll(%s)].filter(function(r){return !%s||r.innerText.indexOf(%s)>=0});
if(!rows.length)return JSON.stringify({rows:0});var row=rows[0];var out={};var els=[row].concat([...row.querySelectorAll('*')]);
for(var i=0;i<els.length;i++){var e=els[i];var c=null;try{c=h.at(e);}catch(z){}var k=c?String(c.id):'none';out[k]=out[k]||[];if(out[k].length<4)out[k].push(e.tagName.toLowerCase()+(typeof e.className==='string'&&e.className?'.'+e.className.split(' ')[0]:''));}
return JSON.stringify({rows:rows.length,chunks:out});})()""" % (json.dumps(sel), json.dumps(flt), json.dumps(flt))
print(L.evaluate(r"""(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const v = app.workspace.getLeavesOfType("vertiscope-browser-view")[0].view;
  const src = %s || (await v.sidecar.sensor()).source;
  const { BrowserWindow } = window.require("@electron/remote");
  const w = new BrowserWindow({ show: false, width: 1280, height: 900, webPreferences: { offscreen: false } });
  try {
    await w.loadURL(%s);
    await sleep(2500);
    const wc = w.webContents;
    await wc.executeJavaScriptInIsolatedWorld(1033, [{ code: '(function(){window.__ff=(' + src + ')({known:[],variants:%s});return 1;})()' }]);
    await sleep(1200);
    await wc.executeJavaScriptInIsolatedWorld(1033, [{ code: 'window.__ff.drain();1' }]);
    const first = await wc.executeJavaScriptInIsolatedWorld(1033, [{ code: %s }]);
    await sleep(%d);
    await wc.executeJavaScriptInIsolatedWorld(1033, [{ code: 'window.__ff.drain();1' }]);
    const later = await wc.executeJavaScriptInIsolatedWorld(1033, [{ code: %s }]);
    return JSON.stringify({ first: JSON.parse(first), after_wait: JSON.parse(later) });
  } finally { w.destroy(); }
})()""" % (json.dumps(open(__import__("os").environ["SENSOR_SRC"], encoding="utf-8").read() if __import__("os").environ.get("SENSOR_SRC") else ""), json.dumps(url), __import__("os").environ.get("VARIANTS", "{}"), json.dumps(probe), int(float(sys.argv[4]) * 1000) if len(sys.argv) > 4 else 8000, json.dumps(probe)), timeout=90))
