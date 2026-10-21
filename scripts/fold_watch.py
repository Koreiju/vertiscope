"""Watch the open page's stream fold while the reader browses (read-only).
Every 10 s: streamed nodes (covered / uncovered / branches), placed, the
store's count, the projector's last online update. A covered streamed node
still drawn on two consecutive samples 20 s apart is FLAGGED."""
import json, sys, time
sys.path.insert(0, r"<home>\Documents\vertiscope")
from vertiscope.obsidian.live import Live

L = Live()
JS = r'''(async()=>{const b=app.workspace.getLeavesOfType("vertiscope-browser-view")[0].view;const v=app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
const U=b.session;if(!U)return JSON.stringify({});const d=v.graph.graphData();const t=b.forceTrees.get(U);const held=t?t.held():[];const cov=t?b.coversFor(U,held):{};
const f=d.nodes.filter(n=>n.url===U&&n.force&&n.level!=="page");const placed=d.nodes.filter(n=>n.url===U&&!n.force&&n.level!=="page");
const covIds=f.filter(n=>!n.branch&&cov[n.id]).map(n=>n.id);
return JSON.stringify({t:Date.now(),url:U,force_covered:covIds.length,force_uncovered:f.filter(n=>!n.branch&&!cov[n.id]).length,branches:f.filter(n=>n.branch).length,
placed:placed.length,held:held.length,covered:Object.keys(cov).length,cov_ids:covIds.slice(0,50),hold:f.filter(n=>n.holdAt).length,fixed:f.filter(n=>n.fx!==undefined&&n.fx!==null).length,
calm:v.calmStats,active:[...v.activeUntil.entries()].filter(([u,t])=>t>performance.now()).map(([u])=>u.slice(8,40))});})()'''
prev = {}
end = time.time() + float(sys.argv[1] if len(sys.argv) > 1 else 1800)
while time.time() < end:
    try:
        r = json.loads(L.evaluate(JS, timeout=20) or "{}")
    except Exception as e:  # noqa: BLE001
        print("err", str(e)[:100], flush=True); time.sleep(10); continue
    if r:
        stuck = [i for i in r.get("cov_ids", []) if i in prev.get(r["url"], set())]
        try:
            proj = L.get("/projector")
            lo = proj.get("last_online") or {}
            r["online_at"] = lo.get("at"); r["online_moved"] = lo.get("chunks_moved")
        except Exception:  # noqa: BLE001
            pass
        ids = set(r.pop("cov_ids", None) or [])
        r["STUCK"] = len(stuck)
        print(json.dumps(r), flush=True)
        prev = {r["url"]: ids}
    time.sleep(10)
