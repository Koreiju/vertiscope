"""Frame cost in chunk view at full size, and picking with static proxy
matrices. Arms: clean; planted `plantSyncEveryFrame` (the batch rewritten every
frame); planted `plantProxyAutoMatrix` (proxies recomposed every frame, a
reload of the level). Picking: a synthetic pointer over the 10 nearest
on-screen nodes must name each through the graph's own tooltip (G-107's
method); the reader stamp is restored around each dispatch."""
import json, sys, time
sys.path.insert(0, "scripts")
from live_probe import Probe, ReaderActed
from check_chunk_view import V, load_level

PICK = r"""(async()=>{const v=%s,g=v.graph,el=g.renderer().domElement,d=g.graphData();const sleep=(ms)=>new Promise(r=>setTimeout(r,ms));
const cam=g.camera(),box=el.getBoundingClientRect(),label=g.nodeLabel();
const text=(h)=>{const e=document.createElement("div");e.innerHTML=h;return (e.textContent||"").trim();};
const cands=[];for(const n of d.nodes){if(n.force||!n.__threeObj||!Number.isFinite(n.x))continue;const V3=n.__threeObj.position.constructor;const p=new V3(n.x,n.y,n.z||0).project(cam);
if(Math.abs(p.x)>0.9||Math.abs(p.y)>0.9||p.z>1)continue;cands.push({n,sx:box.left+(p.x+1)/2*box.width,sy:box.top+(1-p.y)/2*box.height,z:p.z});}
cands.sort((a,c)=>a.z-c.z);let asked=0,hit=0;const stamp=window.__vertiscopeReaderAt;
for(const c of cands.slice(0,10)){asked++;el.dispatchEvent(new PointerEvent("pointermove",{clientX:c.sx,clientY:c.sy,bubbles:true,pointerType:"mouse"}));window.__vertiscopeReaderAt=stamp;
await sleep(1300);const want=text(typeof label==="function"?label(c.n):String(c.n.name||""));
const tips=[...document.querySelectorAll(".float-tooltip-kap, .scene-tooltip, .graph-tooltip")].map(e=>(e.textContent||"").trim());if(want&&tips.some(t=>t===want))hit++;}
el.dispatchEvent(new PointerEvent("pointermove",{clientX:box.left+2,clientY:box.top+2,bubbles:true,pointerType:"mouse"}));window.__vertiscopeReaderAt=stamp;
return JSON.stringify({asked,hit});})()""" % V


def arm(p, name):
    p.guard()
    s0 = json.loads(p.ev("JSON.stringify(%s.batchStats)" % V))
    script = p.script_seconds(5)
    s1 = json.loads(p.ev("JSON.stringify(%s.batchStats)" % V))
    out = {"arm": name, "script_s_of_5": script, "synced": s1["synced"] - s0["synced"], "skipped": s1["skipped"] - s0["skipped"],
           "nodes": p.ev("%s.graph.graphData().nodes.length" % V)}
    out["pick"] = json.loads(p.ev(PICK))
    return out


def main():
    p = Probe()
    start = p.ev("%s.level" % V)
    out = []
    try:
        load_level(p, "chunk"); time.sleep(5)
        out.append(arm(p, "clean"))
        p.ev("%s.plantSyncEveryFrame=true;1" % V)
        out.append(arm(p, "planted sync every frame"))
        p.ev("%s.plantSyncEveryFrame=false;%s.plantProxyAutoMatrix=true;1" % (V, V))
        load_level(p, ""); load_level(p, "chunk"); time.sleep(5)
        out.append(arm(p, "planted proxy auto matrix"))
    except ReaderActed as e:
        out.append({"stopped": str(e)})
    finally:
        p.ev("%s.plantSyncEveryFrame=false;%s.plantProxyAutoMatrix=false;1" % (V, V))
        try:
            load_level(p, start)
        except Exception as e:                 # noqa: BLE001
            out.append({"restore": str(e)})
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
