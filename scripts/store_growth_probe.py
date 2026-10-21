"""G-218: which WRITE grows the store? Measured on a COMPACTED COPY, never
the live store.

    python scripts/store_growth_probe.py <compacted copy dir>

Each step writes one kind of update the sidecar makes, CHECKPOINTs, and
reports the file's growth against the data written:

  md_restore   SET c.md on N chunks in 2,000-row UNWIND batches (what
               `restore_markdown` does: 66,449 rows on 2026-10-18)
  md_one       the same N rows one statement each... skipped above 2,000
  drawn        SET c.drawn on N chunks (the projector's flag)
  null         CHECKPOINT with nothing written (the floor)
"""
import os
import sys
import time

import kuzu

db_path = os.path.join(sys.argv[1], "graph.kuzu")
N = int(sys.argv[2]) if len(sys.argv) > 2 else 20000
db = kuzu.Database(db_path, buffer_pool_size=4 * 1024 ** 3)
c = kuzu.Connection(db)
size = lambda: os.path.getsize(db_path) / 1e6


def q(s, p=None):
    r = c.execute(s, p or {})
    out = []
    while r.has_next():
        out.append(r.get_next())
    return out


rows = q("MATCH (c:Chunk) WHERE c.md IS NOT NULL AND size(c.md) > 0 RETURN c.cid, c.md LIMIT %d" % N)
data_mb = sum(len(md.encode("utf-8")) for _, md in rows) / 1e6
print("chunks", len(rows), "their md %.1f MB" % data_mb, "store %.1f MB" % size(), flush=True)


def step(name, fn):
    c.execute("CHECKPOINT"); b = size(); t = time.time()
    fn(); c.execute("CHECKPOINT")
    print("%-12s grew %+8.1f MB  (%.1f s)" % (name, size() - b, time.time() - t), flush=True)


step("null", lambda: None)
step("md_restore", lambda: [c.execute("UNWIND $rows AS r MATCH (c:Chunk {cid: r.cid}) SET c.md = r.md",
                                      {"rows": [{"cid": cid, "md": md + " "} for cid, md in rows[i:i + 2000]]})
                            for i in range(0, len(rows), 2000)])
step("md_restore2", lambda: [c.execute("UNWIND $rows AS r MATCH (c:Chunk {cid: r.cid}) SET c.md = r.md",
                                       {"rows": [{"cid": cid, "md": md} for cid, md in rows[i:i + 2000]]})
                             for i in range(0, len(rows), 2000)])
import random
step("drawn", lambda: [c.execute("UNWIND $rows AS r MATCH (c:Chunk {cid: r.cid}) SET c.drawn = r.d",
                                 {"rows": [{"cid": cid, "d": [random.random() * 100 for _ in range(3)]} for cid, _ in rows[i:i + 5000]]})
                       for i in range(0, len(rows), 5000)])
step("drawn_again", lambda: [c.execute("UNWIND $rows AS r MATCH (c:Chunk {cid: r.cid}) SET c.drawn = r.d",
                                       {"rows": [{"cid": cid, "d": [random.random() * 100 for _ in range(3)]} for cid, _ in rows[i:i + 5000]]})
                             for i in range(0, len(rows), 5000)])
emb = q("MATCH (c:Chunk) WHERE c.embedding IS NOT NULL RETURN c.cid, c.embedding LIMIT 5000")
print("embedding rows", len(emb), "dims", len(emb[0][1]) if emb else 0, flush=True)
step("embedding", lambda: [c.execute("UNWIND $rows AS r MATCH (c:Chunk {cid: r.cid}) SET c.embedding = r.e",
                                     {"rows": [{"cid": cid, "e": e} for cid, e in emb[i:i + 500]]})
                           for i in range(0, len(emb), 500)])
print("final store %.1f MB" % size())
