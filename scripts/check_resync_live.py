"""G-154 live: restart the sidecar under an open page, make the page change,
and read what happened -- the sidecar's refusal, the plugin's resync, the
full capture after it -- and whether any address in the page's store map has
the shape of a mis-decoded one. Reader-guarded; scrolls the cell back."""
import json, re, subprocess, sys, time, urllib.parse, urllib.request
sys.path.insert(0, "scripts")
from live_probe import Probe

B = 'app.workspace.getLeavesOfType("vertiscope-browser-view")[0].view'
SC = "http://127.0.0.1:8788"
get = lambda path: json.load(urllib.request.urlopen(SC + path, timeout=120))
# Mis-decoded ids land table cells under elements that never hold them.
GARBAGE = re.compile(r"/header/tr|/b/small/i\[|/ol/nav/paragraph|/meta/header/")


def garbage(url):
    pm = get("/page_map?url=" + urllib.parse.quote(url, safe=""))["chunks"]
    return sum(1 for xs in pm.values() for x in xs if GARBAGE.search(x)), len(pm)


def scroll(p, ticks, dy):
    p.ev("""(async()=>{const b=%s;const wc=window.require("@electron/remote").webContents.fromId(b.webview.getWebContentsId());
      for(let i=0;i<%d;i++){wc.sendInputEvent({type:"mouseWheel",x:400,y:400,deltaX:0,deltaY:%d});await new Promise(r=>setTimeout(r,250));}return 1})()""" % (B, ticks, dy))


def hover_link(p):
    p.ev("""(async()=>{const b=%s;const wc=window.require("@electron/remote").webContents.fromId(b.webview.getWebContentsId());
      const r=JSON.parse(await b.webview.executeJavaScript(`(function(){var as=[...document.querySelectorAll('#mw-content-text p a[href^="/wiki/"]')].filter(function(a){var q=a.getBoundingClientRect();return q.top>60&&q.bottom<innerHeight-20&&q.width>8;});var a=as[Math.floor(Math.random()*Math.min(as.length,20))];if(!a)return "null";var q=a.getBoundingClientRect();return JSON.stringify({x:q.left+q.width/2,y:q.top+q.height/2});})()`));
      if(!r)return 0;const stamp=window.__vertiscopeReaderAt;
      wc.sendInputEvent({type:"mouseMove",x:Math.round(r.x),y:Math.round(r.y)});await new Promise(z=>setTimeout(z,1200));
      wc.sendInputEvent({type:"mouseMove",x:5,y:5});window.__vertiscopeReaderAt=stamp;return 1})()""" % B)


def main():
    p = Probe()
    url = p.ev(B + ".webview.getURL()")
    out = {"url": url, "garbage_before": garbage(url)}
    resyncs0 = p.ev(B + ".resyncs")
    t0 = time.time()
    subprocess.run(["powershell", "-NoProfile", "-File", "scripts/restart_sidecar.ps1"], check=True)
    for _ in range(90):
        time.sleep(2)
        try: get("/health"); break
        except Exception: pass
    p.guard()
    # A reader's hover over an article link: Wikipedia inserts its preview
    # popup, so the page changes and the sensor has something to send.
    for _ in range(3):
        hover_link(p)
        time.sleep(2)
    for _ in range(40):
        time.sleep(2); p.guard()
        caps = [r for r in get("/profile").get("capture", []) if r["url"] == url and r["at"] > t0]
        if p.ev(B + ".resyncs") > resyncs0 and caps:
            break
    prof = get("/profile")
    out["refused"] = [r.get("why") for r in prof.get("capture_refused", []) if r.get("at", 0) > t0]
    out["resyncs"] = p.ev(B + ".resyncs") - resyncs0
    caps = [r for r in prof.get("capture", []) if r["url"] == url and r["at"] > t0]
    out["captures_after"] = [{"dirty": r.get("dirty"), "skipped": r.get("unchanged_skipped")} for r in caps][:4]
    time.sleep(5)
    out["garbage_after"] = garbage(url)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
