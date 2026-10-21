"""How fast can a capture's anchors (Chunk -> Address edges) be written?

A scratch store with the real schema (`GraphStore`), N addresses and M chunks
loaded by COPY, then K new anchors written four ways, each on fresh endpoints:
  unwind2   the current fallback: UNWIND, two MATCHes, CREATE
  unwind1   UNWIND, one MATCH clause naming both endpoints
  perrow    one parameterised statement per anchor
  copy      COPY Anchors FROM a frame (the opt-in bulk path)
Live, a bandcamp capture spent 11-12 s on ~290 anchors (2026-10-18); this
says which form a capture should use, and how each scales with N.

  python scripts/store_anchor_bench.py [N=300000] [M=20000] [K=300]
"""
import sys, tempfile, time
sys.path.insert(0, r"<home>\Documents\vertiscope")
import pandas as pd
from vertiscope.graphstore import GraphStore

N = int(sys.argv[1]) if len(sys.argv) > 1 else 300000
M = int(sys.argv[2]) if len(sys.argv) > 2 else 20000
K = int(sys.argv[3]) if len(sys.argv) > 3 else 300

d = tempfile.mkdtemp(prefix="anchor_bench_")
g = GraphStore(d + "/g.kuzu")
t = time.perf_counter()
addr = pd.DataFrame({"aid": ["a%d" % i for i in range(N)], "akey": ["k%d" % i for i in range(N)], "url": "u", "xpath": ["/x/%d" % i for i in range(N)],
                     "tag": "t", "accessor": "text", "value": "v", "content_hash": "h"})
g.conn.execute("COPY Address FROM addr")
chunk_cols = [r[1] for r in g._rows("CALL table_info('Chunk') RETURN *")]
ch = {c: None for c in chunk_cols}
rows = []
for i in range(M):
    r = dict(ch); r.update(cid="c%d" % i, url="u", xpath="/x", part=0, md="m", chars=1, line_count=1, row=i)
    rows.append(r)
g._batch("UNWIND $rows AS r CREATE (:Chunk {cid: r.cid, url: r.url, xpath: r.xpath, part: r.part, md: r.md, chars: r.chars, line_count: r.line_count, row: r.row})", rows, size=2000)
print("loaded %d addresses, %d chunks in %.1f s" % (N, M, time.perf_counter() - t))


def batch(offset):
    return [{"cid": "c%d" % ((offset + i) % M), "aid": "a%d" % ((offset * 7 + i * 13) % N), "ord": i} for i in range(K)]


def run(name, fn, offset):
    rs = batch(offset)
    t0 = time.perf_counter()
    fn(rs)
    ms = (time.perf_counter() - t0) * 1000
    n = g._rows("MATCH (c:Chunk)-[e:Anchors]->(a:Address) WHERE e.ord < $k AND c.cid = $c RETURN count(*)", {"k": K, "c": rs[0]["cid"]})[0][0]
    print("%-8s %d anchors  %8.1f ms  %.2f ms/anchor  (first endpoint holds %d)" % (name, K, ms, ms / K, n))


run("unwind2", lambda rs: g._batch("UNWIND $rows AS r MATCH (c:Chunk {cid: r.cid}) MATCH (a:Address {aid: r.aid}) CREATE (c)-[:Anchors {ord: r.ord}]->(a)", rs), 1)
run("unwind1", lambda rs: g._batch("UNWIND $rows AS r MATCH (c:Chunk {cid: r.cid}), (a:Address {aid: r.aid}) CREATE (c)-[:Anchors {ord: r.ord}]->(a)", rs), 1000)
run("perrow", lambda rs: [g._execute("MATCH (c:Chunk {cid: $c}), (a:Address {aid: $a}) CREATE (c)-[:Anchors {ord: $o}]->(a)", {"c": r["cid"], "a": r["aid"], "o": r["ord"]}) for r in rs], 2000)


def copy(rs):
    df = pd.DataFrame({"from": [r["cid"] for r in rs], "to": [r["aid"] for r in rs], "ord": [r["ord"] for r in rs]})
    g.conn.execute("COPY Anchors FROM df")


run("copy", copy, 3000)
g.close()
