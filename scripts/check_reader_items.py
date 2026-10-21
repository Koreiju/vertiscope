"""Live checks, each with its planted arm, reader-guarded; everything changed
is restored.

G-149 a right-click reopens what the reader folded -- with one of its chunks
      pinned (still drawn), the old rule folded again (`plantToggleByDrawn`).
(80)  no two of an open page's chunks overlap as drawn, none in the url node's
      drawn body (`plantNoRelax`: the cloud is not relaxed). Replaced G-147's
      sphere arm when the sphere was removed (2026-10-11).
G-146 pictures only near the pointer's ray, url nodes always
      (`plantAllPictures`: every picture node draws its picture)."""
import json, sys, time
sys.path.insert(0, "scripts")
from live_probe import Probe, ReaderActed
from check_chunk_view import V, load_level

OPEN = "(()=>{const d=%s.graph.graphData();const c={};for(const n of d.nodes)if(n.level!=='page'&&n.url)c[n.url]=(c[n.url]||0)+1;" \
       "return Object.entries(c).sort((a,b)=>b[1]-a[1])[0]?.[0]||''})()" % V


def toggle_arm(p, url, plant):
    p.ev("%s.plantToggleByDrawn=%s;1" % (V, "true" if plant else "false"))
    count = "(()=>%s.graph.graphData().nodes.filter(n=>n.url===%s&&n.level!=='page').length)()" % (V, json.dumps(url))
    page = "%s.graph.graphData().nodes.find(n=>n.level==='page'&&n.url===%s)" % (V, json.dumps(url))
    before = p.ev(count)
    pin = p.ev("(async()=>{const v=%s;const c=v.graph.graphData().nodes.find(n=>n.url===%s&&n.level!=='page'&&!n.force);await v.openBillboard(c,true);return c.id})()" % (V, json.dumps(url)))
    first = p.ev("(async()=>JSON.stringify(await %s.togglePage(%s)))()" % (V, page))
    time.sleep(2); p.guard()
    after_fold = p.ev(count)
    second = p.ev("(async()=>JSON.stringify(await %s.togglePage(%s)))()" % (V, page))
    time.sleep(6); p.guard()
    after_second = p.ev(count)
    p.ev("(()=>{%s.closeBillboard(%s);return 1})()" % (V, json.dumps(pin)))
    # Leave the page open as the reader had it.
    if p.ev(count) < before // 2:
        p.ev("(async()=>{%s.plantToggleByDrawn=false;await %s.togglePage(%s);return 1})()" % (V, V, page))
        time.sleep(6)
    return {"plant": plant, "before": before, "first": json.loads(first)["action"], "after_fold": after_fold,
            "second": json.loads(second)["action"], "after_second": after_second}


CLUMP = """(()=>{const v=%s,d=v.graph.graphData(),rs=v.graph.nodeRelSize(),m=v.drawnMedia;const h=(n)=>v.lookOf(n,rs,m).half;
const pages=d.nodes.filter(n=>n.level==='page'&&Number.isFinite(n.x));const out=[];
for(const p of pages){const own=d.nodes.filter(n=>n.level!=='page'&&!n.force&&n.url===p.url&&Number.isFinite(n.x));if(own.length<5)continue;
const hs=own.map(h);let over=0,deep=0;for(let i=0;i<own.length;i++)for(let j=i+1;j<own.length;j++){const a=own[i],b=own[j];
const dd=Math.hypot(a.x-b.x,a.y-b.y,(a.z||0)-(b.z||0)),s=hs[i]+hs[j];if(dd<0.98*s){over++;if(dd<0.5*s)deep++;}}
const hp=h(p);const inBody=own.filter((c,i)=>Math.hypot(c.x-p.x,c.y-p.y,(c.z||0)-(p.z||0))<0.98*(hp+hs[i])).length;
const sorted=hs.slice().sort((x,y)=>x-y);
out.push({url:p.url.slice(8,50),own:own.length,overlaps:over,deep,in_url_body:inBody,half_p50:Math.round(sorted[sorted.length>>1]*10)/10,half_max:Math.round(sorted[sorted.length-1]*10)/10,page_half:Math.round(hp*10)/10});}
return JSON.stringify(out)})()""" % V


def clump_arm(p, plant):
    """Item (80): an open page's chunks do not overlap AS DRAWN, nor sit in
    the url node's drawn body. Planted: the clump the reader saw (2026-10-11,
    "Giant clumping problem") -- chunks at FULL size (`plantBigChunks`, no
    shrink to the room) and not relaxed (`plantNoRelax`). The first plant was
    `plantNoRelax` alone, and it read 0 overlaps like the clean arm: with the
    chunks shrunk to their room the telescope alone keeps them apart, so that
    arm could not fail."""
    p.ev("(()=>{const v=%s,P=%s,d=v.graph.graphData();v.plantBigChunks=false;v.plantNoRelax=P;v.fitChunkSizes(d);"
         "if(P){for(const n of d.nodes){if(n.level!=='page'&&!n.force&&n.fullVal!==undefined)n.val=n.fullVal;}v.plantBigChunks=true;v.graph.nodeVal(v.graph.nodeVal());}"
         "v.graph.d3ReheatSimulation();return 1})()" % (V, "true" if plant else "false"))
    time.sleep(8)
    for _ in range(30):
        time.sleep(1); p.guard()
        if not p.ev("%s.glides.size" % V): break
    time.sleep(1)
    return {"plant": plant, "pages": json.loads(p.ev(CLUMP))}


PICS = """(()=>{const v=%s,g=v.graph,rs=g.nodeRelSize();let withImg=0,drawn=0,chunkDrawn=0;for(const n of g.graphData().nodes){if(!n.image||!n.image.src)continue;withImg++;
const lk=v.lookOf(n,rs,v.drawnMedia);if(lk.picture){drawn++;if(n.level!=='page'&&n.level!=='path')chunkDrawn++;}}return JSON.stringify({withImg,drawn,chunkDrawn,media:v.drawnMedia})})()""" % V


def main():
    p = Probe()
    start = p.ev("%s.level" % V)
    out = {}
    try:
        load_level(p, ""); time.sleep(3)
        url = p.ev(OPEN) or p.ev('app.workspace.getLeavesOfType("vertiscope-browser-view")[0].view.webview.getURL()')
        out["url"] = url
        page = "%s.graph.graphData().nodes.find(n=>n.level==='page'&&n.url===%s)" % (V, json.dumps(url))
        opened_here = False
        if url and p.ev("!!" + page) and not p.ev(OPEN):
            p.ev("(async()=>{await %s.togglePage(%s);return 1})()" % (V, page))
            opened_here = True
            time.sleep(8); p.guard()
        out["opened_for_check"] = opened_here
        if url and p.ev(OPEN):
            out["G-149"] = [toggle_arm(p, url, False), toggle_arm(p, url, True)]
        if opened_here and p.ev(OPEN):
            p.ev("(async()=>{%s.plantToggleByDrawn=false;await %s.togglePage(%s);return 1})()" % (V, V, page))
        # Item (80) on a CROWDED page: the stored page with the most chunks
        # (a page node's val is sqrt of its chunk count). On the 8-chunk
        # fixture both arms read 0 -- full-size chunks still fit its room, so
        # that page cannot show a clump either way.
        big = p.ev("(()=>{const d=%s.graph.graphData();const ps=d.nodes.filter(n=>n.level==='page'&&/^https?:/.test(n.url||'')&&!/127[.]0[.]0[.]1|localhost/.test(n.url)).sort((a,b)=>(b.fullVal??b.val)-(a.fullVal??a.val));return ps.length?ps[0].url:''})()" % V)
        if big:
            bigNode = "%s.graph.graphData().nodes.find(n=>n.level==='page'&&n.url===%s)" % (V, json.dumps(big))
            p.ev("(async()=>{await %s.togglePage(%s);return 1})()" % (V, bigNode))
            time.sleep(10); p.guard()
            out["(80) no clump"] = {"url": big, "arms": [clump_arm(p, True), clump_arm(p, False)]}
            p.ev("(async()=>{await %s.togglePage(%s);return 1})()" % (V, bigNode))
            time.sleep(3)
        out["G-146 pages view"] = json.loads(p.ev(PICS))
        load_level(p, "chunk"); time.sleep(3)
        out["G-146 chunk view"] = json.loads(p.ev(PICS))
        p.ev("%s.plantAllPictures=true;1" % V)
        out["G-146 chunk view planted"] = json.loads(p.ev(PICS))
    except ReaderActed as e:
        out["stopped"] = str(e)
    finally:
        p.ev("(()=>{const v=%s;v.plantToggleByDrawn=false;v.plantNoRelax=false;v.plantBigChunks=false;v.plantAllPictures=false;return 1})()" % V)
        try:
            if p.ev("%s.level" % V) == "":
                p.ev("(()=>{const v=%s;v.fitChunkSizes(v.graph.graphData());return 1})()" % V)
            load_level(p, start)
        except Exception as e:                 # noqa: BLE001
            out["restore"] = str(e)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
