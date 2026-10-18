"""G-218: what does writing an embedding cost on disk, by column type and by
batch size? A fresh store per case: 8,192 chunks created WITHOUT a vector (as
a capture creates them), then every vector SET afterwards (as the embedder
does), in batches of B rows, CHECKPOINT, file growth reported against the
data written (8,192 x 768 x 4 or 8 bytes).

    python scripts/store_growth_vectors.py <scratch dir>
"""
import os
import shutil
import sys
import time

import kuzu
import numpy as np

root = sys.argv[1]
N, D = 8192, 768
vecs = np.random.default_rng(0).standard_normal((N, D)).astype(np.float32)


def case(coltype, batch, at_create=False):
    d = os.path.join(root, "%s_%d_%s" % (coltype.replace("[", "").replace("]", ""), batch, at_create))
    shutil.rmtree(d, ignore_errors=True); os.makedirs(d)
    path = os.path.join(d, "g.kuzu")
    db = kuzu.Database(path, buffer_pool_size=2 * 1024 ** 3); c = kuzu.Connection(db)
    c.execute("CREATE NODE TABLE Chunk(cid STRING, md STRING, embedding %s, PRIMARY KEY (cid))" % coltype)
    if at_create:
        for i in range(0, N, batch):
            c.execute("UNWIND $rows AS r CREATE (:Chunk {cid: r.cid, md: r.md, embedding: r.e})",
                      {"rows": [{"cid": "c%d" % j, "md": "x" * 200, "e": vecs[j].tolist()} for j in range(i, min(N, i + batch))]})
    else:
        c.execute("UNWIND range(0, %d) AS i CREATE (:Chunk {cid: 'c' + string(i), md: 'x'})" % (N - 1))
    c.execute("CHECKPOINT"); b = os.path.getsize(path); t = time.time()
    if not at_create:
        for i in range(0, N, batch):
            c.execute("UNWIND $rows AS r MATCH (c:Chunk {cid: r.cid}) SET c.embedding = r.e",
                      {"rows": [{"cid": "c%d" % j, "e": vecs[j].tolist()} for j in range(i, min(N, i + batch))]})
            if batch <= 64 and i % (batch * 16) == 0:
                c.execute("CHECKPOINT")      # the live sidecar checkpoints between captures
    c.execute("CHECKPOINT")
    grew = (os.path.getsize(path) - b) / 1e6
    raw = N * D * (8 if "DOUBLE" in coltype else 4) / 1e6
    print("%-12s batch %5d %-9s grew %8.1f MB for %6.1f MB of vectors (x%.1f), %.1f s"
          % (coltype, batch, "at create" if at_create else "SET after", grew, raw, grew / raw, time.time() - t), flush=True)
    del c, db
    shutil.rmtree(d, ignore_errors=True)


for coltype in ("DOUBLE[]", "FLOAT[]", "FLOAT[768]"):
    for batch in (16, 512, 2048):
        case(coltype, batch)
case("FLOAT[768]", 512, at_create=True)
case("DOUBLE[]", 512, at_create=True)
