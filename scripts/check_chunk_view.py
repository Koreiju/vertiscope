"""G-151: chunk view sits at UMAP alone. Clean arm: nodes at their fit, the
engine idle. Planted arm (`plantChunkForces`): the pages view's forces run in
chunk view and nodes leave their fit. Restores the reader's view."""
import json, sys, time
sys.path.insert(0, "scripts")
from live_probe import Probe, ReaderActed

V = 'app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view'
BTN = '[...%s.containerEl.querySelectorAll("button")].find(b=>b.textContent==="pages"||b.textContent==="chunks")' % V


def load_level(p, want):
    if p.ev("%s.level" % V) != want:
        p.ev("%s.click(); 1" % BTN)
    last, same = -1, 0
    for _ in range(300):
        time.sleep(1); p.guard()
        n = p.ev("(()=>{const v=%s;return v.graph?v.graph.graphData().nodes.length:0})()" % V)
        same = same + 1 if n == last else 0
        last = n
        # Loaded: the level is the one asked for and the count has held 8 s
        # (chunk view arrives in batches: 644 of 22,835 held 3 s once).
        if n and same >= 8 and p.ev("%s.level" % V) == want and (want != "chunk" or n > 5000):
            return n
    raise RuntimeError("level %r never loaded" % want)


def measure(p):
    p.ev("(()=>{const v=%s;v.__ticks=0;const g=v.graph;v.__prevTick=g.onEngineTick();g.onEngineTick(()=>{v.__ticks++;v.__prevTick&&v.__prevTick()});return 1})()" % V)
    script = p.script_seconds(5)
    ticks = p.ev("%s.__ticks" % V)
    p.ev("(()=>{const v=%s;v.graph.onEngineTick(v.__prevTick);delete v.__prevTick;return 1})()" % V)
    off = json.loads(p.ev("""(()=>{const d=%s.graph.graphData();let mx=0,moved=0,n=0;for(const x of d.nodes){if(!Number.isFinite(x.fitX))continue;n++;
      const e=Math.hypot(x.x-x.fitX,x.y-x.fitY,(x.z||0)-(x.fitZ||0));if(e>mx)mx=e;if(e>0.5)moved++;}return JSON.stringify({n,moved,max:+mx.toFixed(2)})})()""" % V))
    return {"umapOnly": p.ev("%s.umapOnly" % V), "script_s_of_5": script, "engine_ticks_5s": ticks, **off}


def main():
    p = Probe()
    start = p.ev("%s.level" % V)
    out = {}
    try:
        load_level(p, "chunk")
        out["clean"] = measure(p)
        p.ev("%s.plantChunkForces=true; 1" % V)
        load_level(p, ""); load_level(p, "chunk")
        p.ev("%s.graph.d3ReheatSimulation(); 1" % V)
        time.sleep(3); p.guard()
        out["planted"] = measure(p)
    except ReaderActed as e:
        out["stopped"] = str(e)
    finally:
        p.ev("%s.plantChunkForces=false; 1" % V)
        try:
            load_level(p, start)
        except Exception as e:                 # noqa: BLE001
            out["restore"] = str(e)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
