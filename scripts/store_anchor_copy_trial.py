"""Is COPY safe -- in time AND in bytes -- for a capture's anchors on a REAL-SIZE store, in the pool the
sidecar would give it? (`_ANCHOR_COPY` was made opt-in on 2026-10-18 after a
2 GiB pool refused 41 rows on a 5.1 GB store; the floor is 4 GiB since.)

On a COPY of a working store (never the live one): `batches` captures' worth
of anchors (`k` each, real chunk and address ids) through the sidecar's own
`_create_anchors` with `_ANCHOR_COPY` on, while a reader thread runs the
page-map query the app runs between captures. Then the same through the
statement form, for the time it replaces. Reports ms per batch, refusals,
and whether the store reopens afterwards.

  python scripts/store_anchor_copy_trial.py <copy-of-store> [batches=30] [k=290]
"""
import os, random, sys, threading, time
sys.path.insert(0, r"<home>\Documents\vertiscope")
from vertiscope.graphstore import GraphStore, _pool_for

path = sys.argv[1]
batches = int(sys.argv[2]) if len(sys.argv) > 2 else 30
k = int(sys.argv[3]) if len(sys.argv) > 3 else 290
print("pool for this store: %.1f GiB" % (_pool_for(path) / 2 ** 30))
g = GraphStore(path)
t = time.perf_counter()
cids = [r[0] for r in g._rows("MATCH (c:Chunk) RETURN c.cid LIMIT 20000")]
aids = [r[0] for r in g._rows("MATCH (a:Address) RETURN a.aid LIMIT 200000")]
urls = [r[0] for r in g._rows("MATCH (p:Page) RETURN p.url LIMIT 200")]
anchors0 = g._rows("MATCH ()-[e:Anchors]->() RETURN count(*)")[0][0]
print("sampled %d cids, %d aids, %d urls; anchors %d (%.1f s)" % (len(cids), len(aids), len(urls), anchors0, time.perf_counter() - t))
rnd = random.Random(7)
stop = threading.Event()
reads = {"n": 0, "errors": []}


def reader():
    while not stop.is_set():
        u = rnd.choice(urls)
        try:
            g._rows("MATCH (p:Page {url: $u})-[:HasChunk]->(c:Chunk)-[:Anchors]->(a:Address) RETURN c.cid, a.xpath LIMIT 2000", {"u": u})
            reads["n"] += 1
        except Exception as exc:                     # noqa: BLE001
            reads["errors"].append(str(exc)[:120])
        time.sleep(0.05)


def batch():
    return [{"cid": rnd.choice(cids), "aid": rnd.choice(aids), "ord": 10_000 + i} for i in range(k)]


th = threading.Thread(target=reader, daemon=True); th.start()
out = {}
size = lambda: os.path.getsize(path) + (os.path.getsize(path + ".wal") if os.path.exists(path + ".wal") else 0)
for mode in ("copy", "statement"):
    GraphStore._ANCHOR_COPY[0] = mode == "copy"
    ms, refused = [], 0
    n = batches if mode == "copy" else max(2, batches // 10)
    bytes0 = size()
    for _ in range(n):
        before = len(g.copy_errors)
        t0 = time.perf_counter()
        try:
            g._create_anchors(batch())
        except Exception as exc:                     # noqa: BLE001
            print("RAISED", mode, str(exc)[:160]); refused += 1; break
        ms.append((time.perf_counter() - t0) * 1000)
        if len(g.copy_errors) > before:
            refused += 1; print("COPY refused:", g.copy_errors[-1][:160])
    ms.sort()
    try:
        g._execute("CHECKPOINT")
    except Exception:                                # noqa: BLE001
        pass
    # BYTES too: a live trial of COPY as the default grew the store 1.6 -> 6.9
    # GB in six minutes; the first version of this script timed only.
    out[mode] = {"batches": len(ms), "p50_ms": round(ms[len(ms) // 2], 1) if ms else None, "max_ms": round(ms[-1], 1) if ms else None, "refused": refused, "poisoned": g.poisoned,
                 "grew_mb": round((size() - bytes0) / 1e6, 1), "grew_kb_per_anchor": round((size() - bytes0) / 1e3 / max(1, len(ms) * k), 1)}
    print(mode, out[mode])
stop.set(); th.join(2)
print("reads alongside: %d, errors %d %s" % (reads["n"], len(reads["errors"]), reads["errors"][:2]))
anchors1 = g._rows("MATCH ()-[e:Anchors]->() RETURN count(*)")[0][0]
print("anchors %d -> %d (+%d)" % (anchors0, anchors1, anchors1 - anchors0))
g.close()
g2 = GraphStore(path)
print("reopened; anchors", g2._rows("MATCH ()-[e:Anchors]->() RETURN count(*)")[0][0])
g2.close()
