"""Hidden-window probe: one fold of the sensor (merge + semantic, as the
browser cell runs it) over a page, and where in its drained payload a piece
of text appears -- or does not. Never touches the reader's browser cell.

Usage: python scripts/sensor_payload_probe.py <url> <text> [<text> ...]"""
import json
import sys

sys.path.insert(0, r"<home>\Documents\vertiscope")
from vertiscope.obsidian.live import Live


def main():
    url, needles = sys.argv[1], sys.argv[2:]
    find = r"""(function(N){var p=window.__ff.drain();var cs=p.chunks||[];var out={chunks:cs.length,keys:cs.length?Object.keys(cs[0]):[],hits:{}};
    var s=JSON.stringify(cs);N.forEach(function(n){var i=s.indexOf(n),h=[];while(i>=0&&h.length<4){h.push(s.slice(Math.max(0,i-160),i+60));i=s.indexOf(n,i+1);}out.hits[n]=h;});
    return JSON.stringify(out);})(%s)""" % json.dumps(needles)
    print(Live().evaluate(r"""(async () => {
      const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
      const v = app.workspace.getLeavesOfType("vertiscope-browser-view")[0].view;
      const src = (await v.sidecar.sensor()).source;
      const { BrowserWindow } = window.require("@electron/remote");
      const w = new BrowserWindow({ show: false, width: 1280, height: 900 });
      try {
        await w.loadURL(%s); await sleep(4000);
        const wc = w.webContents;
        await wc.executeJavaScriptInIsolatedWorld(1034, [{ code: '(function(){window.__ff=(' + src + ')({known:[],variants:{merge:true,semantic:true}});return 1;})()' }]);
        await sleep(1500);
        return await wc.executeJavaScriptInIsolatedWorld(1034, [{ code: %s }]);
      } finally { w.destroy(); }
    })()""" % (json.dumps(url), json.dumps(find)), timeout=180))


if __name__ == "__main__":
    main()
