"""D-48 probe (2026-10-07). Usage: python scripts/store_torn_wal.py 0.03 0.1 0.18 0.26

Does setting a WAL aside after a crash leave rows with EMPTY strings?

Scratch store only. A child writes N chunk rows (md strings) in batches,
then CHECKPOINTs; the parent kills it hard after `delay` seconds. Then:
  arm "aside":  the WAL is renamed away (what supervise.quarantine_wal does)
  arm "replay": the WAL is left for kuzu to replay
and the store is opened and its rows counted: total, empty md, md intact.
"""
import os, shutil, subprocess, sys, time, json

import tempfile
ROOT = os.path.join(tempfile.gettempdir(), "vertiscope_torn_wal")
os.makedirs(ROOT, exist_ok=True)
CHILD = r'''
import kuzu, sys, random, string, os
p = sys.argv[1]; phase = sys.argv[2]
db = kuzu.Database(p, buffer_pool_size=1 << 30); c = kuzu.Connection(db)
if phase == "seed":
    c.execute("CREATE NODE TABLE Chunk(cid STRING, md STRING, line_count INT64, PRIMARY KEY(cid))")
    c.execute("CALL auto_checkpoint=false")
rng = random.Random(int(sys.argv[3]))
start = int(sys.argv[4]); n = int(sys.argv[5])
c.execute("CALL auto_checkpoint=false")
for b in range(start, start + n, 2000):
    rows = [{"cid": "c%07d" % i, "md": "chunk %d " % i + "".join(rng.choice(string.ascii_letters + " ") for _ in range(300)), "n": 3}
            for i in range(b, min(b + 2000, start + n))]
    c.execute("UNWIND $rows AS r MERGE (x:Chunk {cid: r.cid}) SET x.md = r.md, x.line_count = r.n", {"rows": rows})
if phase == "seed":
    c.execute("CHECKPOINT")
    print("seeded", flush=True); sys.exit(0)
# update phase: rewrite every md (MERGE..SET on existing rows), then checkpoint
print("wrote", flush=True)
c.execute("CHECKPOINT")
print("checkpointed", flush=True)
'''


def count(path):
    import kuzu
    db = kuzu.Database(path, buffer_pool_size=256 << 20)
    c = kuzu.Connection(db)
    r = c.execute("MATCH (x:Chunk) RETURN count(x), sum(CASE WHEN x.md IS NULL OR size(x.md) = 0 THEN 1 ELSE 0 END), sum(CASE WHEN x.line_count > 0 THEN 1 ELSE 0 END)")
    row = r.get_next()
    del c, db
    return {"rows": row[0], "empty_md": row[1], "with_line_count": row[2]}


def run(arm, delay, n=60000):
    d = os.path.join(ROOT, "torn_%s_%s" % (arm, str(delay).replace(".", "_")))
    shutil.rmtree(d, ignore_errors=True); os.makedirs(d)
    p = os.path.join(d, "g.kuzu")
    child = os.path.join(ROOT, "torn_child.py")
    open(child, "w").write(CHILD)
    subprocess.run([sys.executable, child, p, "seed", "1", "0", str(n)], check=True, capture_output=True)
    # second wave rewrites the same rows (MERGE..SET), killed mid-way
    pr = subprocess.Popen([sys.executable, child, p, "update", "2", "0", str(n)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    # wait for the child to finish writing, THEN kill `delay` s into its CHECKPOINT
    line = pr.stdout.readline()
    t0 = time.time()
    while time.time() - t0 < delay and pr.poll() is None:
        time.sleep(0.002)
    killed = pr.poll() is None
    if killed:
        pr.kill()
    so, se = pr.communicate()
    wal = p + ".wal"
    wal_size = os.path.getsize(wal) if os.path.exists(wal) else None
    if arm == "aside" and os.path.exists(wal):
        os.rename(wal, wal + ".aside")
    try:
        res = count(p)
    except Exception as e:  # noqa: BLE001
        res = {"open_error": str(e)[:200]}
    return {"arm": arm, "delay": delay, "killed": killed, "child_said": so.strip().split("\n")[-1:] , "wal_bytes": wal_size, **res}


if __name__ == "__main__":
    for delay in [float(x) for x in sys.argv[1:]] or [1.0, 2.0, 3.0]:
        for arm in ("replay", "aside"):
            print(json.dumps(run(arm, delay), default=int), flush=True)
