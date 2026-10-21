"""A capture's NEW addresses and their anchors, on a real-size store copy:
which write form? (Live 2026-10-18: bandcamp's feed shifts ~200 addresses a
capture; the fused MERGE+SET+MATCH+CREATE took 11-15 s of each capture.)

  A fused    UNWIND MERGE Address SET 7 cols, MATCH Chunk, CREATE Anchors
  B split    UNWIND MERGE Address SET 7 cols; then COPY Anchors
  C copy     COPY Address (new rows only); then COPY Anchors

Each arm writes `k` addresses that do not exist yet, anchored to real
chunks; `n` rounds each, reads running alongside.

  python scripts/store_address_bench.py <copy-of-store> [n=10] [k=290]
"""
import random, sys, threading, time, uuid
sys.path.insert(0, r"<home>\Documents\vertiscope")
import pandas as pd
from vertiscope.graphstore import GraphStore

path = sys.argv[1]
n = int(sys.argv[2]) if len(sys.argv) > 2 else 10
k = int(sys.argv[3]) if len(sys.argv) > 3 else 290
g = GraphStore(path)
GraphStore._ANCHOR_COPY[0] = True
cids = [r[0] for r in g._rows("MATCH (c:Chunk) RETURN c.cid LIMIT 20000")]
urls = [r[0] for r in g._rows("MATCH (p:Page) RETURN p.url LIMIT 200")]
rnd = random.Random(3)
stop = threading.Event(); reads = [0]


def reader():
    while not stop.is_set():
        try:
            g._rows("MATCH (p:Page {url: $u})-[:HasChunk]->(c:Chunk)-[:Anchors]->(a:Address) RETURN c.cid, a.xpath LIMIT 2000", {"u": rnd.choice(urls)})
            reads[0] += 1
        except Exception:                            # noqa: BLE001
            pass
        time.sleep(0.05)


def rows():
    out = []
    for i in range(k):
        aid = uuid.uuid4().hex[:16]
        out.append({"aid": aid, "akey": "u|/x/%s|text" % aid, "url": "https://bench.test/", "xp": "/x/%s" % aid, "tag": "text",
                    "acc": "text()", "val": "v", "ch": "h", "cid": rnd.choice(cids), "ord": 20000 + i})
    return out


def fused(rs):
    g._batch("UNWIND $rows AS r MERGE (a:Address {aid: r.aid}) SET a.akey = r.akey, a.url = r.url, a.xpath = r.xp, "
             "a.tag = r.tag, a.accessor = r.acc, a.value = r.val, a.content_hash = r.ch "
             "WITH a, r MATCH (c:Chunk {cid: r.cid}) CREATE (c)-[:Anchors {ord: r.ord}]->(a)", rs)


def split(rs):
    g._batch("UNWIND $rows AS r MERGE (a:Address {aid: r.aid}) SET a.akey = r.akey, a.url = r.url, a.xpath = r.xp, "
             "a.tag = r.tag, a.accessor = r.acc, a.value = r.val, a.content_hash = r.ch", rs)
    g._create_anchors([{"cid": r["cid"], "aid": r["aid"], "ord": r["ord"]} for r in rs])


def copy(rs):
    df = pd.DataFrame({"aid": [r["aid"] for r in rs], "akey": [r["akey"] for r in rs], "url": [r["url"] for r in rs],
                       "xpath": [r["xp"] for r in rs], "tag": [r["tag"] for r in rs], "accessor": [r["acc"] for r in rs],
                       "value": [r["val"] for r in rs], "content_hash": [r["ch"] for r in rs]})
    with g._read_lock, g._db_lock:
        g.conn.execute("COPY Address FROM df")
    g._create_anchors([{"cid": r["cid"], "aid": r["aid"], "ord": r["ord"]} for r in rs])


th = threading.Thread(target=reader, daemon=True); th.start()
for name, fn in (("fused", fused), ("split", split), ("copy", copy)):
    ms = []
    errs = []
    for _ in range(n):
        rs = rows()
        before = len(g.copy_errors)
        t0 = time.perf_counter()
        try:
            fn(rs)
        except Exception as exc:                     # noqa: BLE001
            errs.append(str(exc)[:120]); continue
        ms.append((time.perf_counter() - t0) * 1000)
        if len(g.copy_errors) > before:
            errs.append(g.copy_errors[-1][:120])
    ms.sort()
    got = g._rows("MATCH (a:Address {aid: $a})<-[e:Anchors]-(c:Chunk) RETURN count(e)", {"a": rs[0]["aid"]})[0][0]
    print("%-6s %d x %d rows  p50 %8.1f ms  max %8.1f ms  errors %d %s  (last row anchored %d)" % (
        name, len(ms), k, ms[len(ms) // 2] if ms else -1, ms[-1] if ms else -1, len(errs), errs[:1], got))
stop.set(); th.join(2)
print("reads alongside", reads[0])
g.close()
