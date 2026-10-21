import json, sys, time
sys.path.insert(0, r"<home>\Documents\vertiscope")
from vertiscope.obsidian.live import Live
L = Live()
JS = r'''(()=>{const v=app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;const d=v.graph.graphData();
const rms=(ns,f)=>{if(!ns.length)return null;const c=[0,1,2].map(i=>ns.reduce((a,n)=>a+f(n)[i],0)/ns.length);return Math.round(Math.sqrt(ns.reduce((a,n)=>{const p=f(n);return a+(p[0]-c[0])**2+(p[1]-c[1])**2+(p[2]-c[2])**2},0)/ns.length)*10)/10};
const P=d.nodes.filter(n=>n.level==="page"&&!n.force&&Number.isFinite(n.x));const C=d.nodes.filter(n=>n.level!=="page"&&!n.force&&Number.isFinite(n.x)&&Number.isFinite(n.fitX));
const nn=(ns)=>{const s=ns.slice(0,400).map(a=>{let m=Infinity;for(const b of ns)if(b!==a)m=Math.min(m,Math.hypot(a.x-b.x,a.y-b.y,(a.z||0)-(b.z||0)));return m}).sort((a,b)=>a-b);return s.length?Math.round(s[s.length>>1]*10)/10:null};
const cam=v.graph.camera().position;
return JSON.stringify({t:Date.now(),pages:P.length,page_rms:rms(P,n=>[n.x,n.y,n.z||0]),page_fit_rms:rms(P.filter(n=>Number.isFinite(n.fitX)),n=>[n.fitX,n.fitY,n.fitZ||0]),page_nn:nn(P),
chunks:C.length,chunk_off_p50:C.length?Math.round(C.map(n=>Math.hypot(n.x-n.fitX,n.y-n.fitY,(n.z||0)-(n.fitZ||0))).sort((a,b)=>a-b)[C.length>>1]*10)/10:null,
url:(app.workspace.getLeavesOfType("vertiscope-browser-view")[0].view||{}).session,cam_d:Math.round(Math.hypot(cam.x,cam.y,cam.z))});})()'''
out = []
for i in range(int(sys.argv[1]) if len(sys.argv) > 1 else 24):
    try:
        r = json.loads(L.evaluate(JS, timeout=20)); out.append(r); print(json.dumps(r), flush=True)
    except Exception as e:
        print("err", e, flush=True)
    time.sleep(5)
