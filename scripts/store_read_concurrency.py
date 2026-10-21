"""Can reads run beside a long write, each thread on its own kuzu connection?
(2026-10-10: "retrieval breakdown during a scan over a large page" -- the
legislation.gov.uk capture held the store 100.6 s, 77.9 s of it one class of
statement, and every search waited behind it on the ONE shared connection.)

A writer thread upserts big UNWIND batches (and checkpoints) on its own
connection; reader threads query on theirs. Reported: reader latency p50/p95/
max, statements each side ran, and whether the process survived. The planted
arm runs the readers on the WRITER's connection behind one lock, as the
sidecar did -- its reads must wait out the writes.

  python scripts/store_read_concurrency.py [seconds] [--shared]
"""
import json
import os
import random
import string
import sys
import tempfile
import threading
import time

import kuzu


def main(seconds: float = 30.0, shared: bool = False) -> dict:
    d = os.path.join(tempfile.gettempdir(), "vertiscope_read_conc_%s" % ("shared" if shared else "split"))
    import shutil
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    db = kuzu.Database(os.path.join(d, "g.kuzu"), buffer_pool_size=1 << 30)
    w = kuzu.Connection(db)
    w.execute("CREATE NODE TABLE Address(aid STRING, url STRING, akey STRING, value STRING, PRIMARY KEY(aid))")
    rng = random.Random(3)
    txt = lambda n: "".join(rng.choice(string.ascii_letters + " ") for _ in range(n))  # noqa: E731
    seed = [{"aid": "a%07d" % i, "url": "u%d" % (i % 50), "akey": "k%d" % i, "value": txt(120)} for i in range(120000)]
    for i in range(0, len(seed), 5000):
        w.execute("UNWIND $rows AS r MERGE (a:Address {aid: r.aid}) SET a.url = r.url, a.akey = r.akey, a.value = r.value",
                  {"rows": seed[i:i + 5000]})
    w.execute("CHECKPOINT")
    lock = threading.Lock()
    stop = threading.Event()
    out = {"shared": shared, "writes": 0, "write_ms": [], "reads": 0, "read_ms": [], "errors": []}

    def writer():
        n = 120000
        while not stop.is_set():
            rows = [{"aid": "a%07d" % rng.randrange(0, n + 20000), "url": "u%d" % rng.randrange(50), "akey": "k", "value": txt(200)}
                    for _ in range(5000)]
            t = time.perf_counter()
            try:
                with lock:
                    w.execute("UNWIND $rows AS r MERGE (a:Address {aid: r.aid}) SET a.url = r.url, a.akey = r.akey, a.value = r.value",
                              {"rows": rows})
                    if out["writes"] % 5 == 4:
                        w.execute("CHECKPOINT")
            except Exception as e:  # noqa: BLE001
                out["errors"].append("w:" + str(e)[:120])
            out["write_ms"].append((time.perf_counter() - t) * 1000)
            out["writes"] += 1

    def reader(i):
        c = w if shared else kuzu.Connection(db)
        while not stop.is_set():
            t = time.perf_counter()
            try:
                if shared:
                    with lock:
                        r = c.execute("MATCH (a:Address {url: $u}) RETURN count(a)", {"u": "u%d" % rng.randrange(50)})
                        r.get_next()
                else:
                    r = c.execute("MATCH (a:Address {url: $u}) RETURN count(a)", {"u": "u%d" % rng.randrange(50)})
                    r.get_next()
            except Exception as e:  # noqa: BLE001
                out["errors"].append("r:" + str(e)[:120])
            out["read_ms"].append((time.perf_counter() - t) * 1000)
            out["reads"] += 1
            time.sleep(0.05)

    ts = [threading.Thread(target=writer)] + [threading.Thread(target=reader, args=(i,)) for i in range(3)]
    for t in ts:
        t.start()
    time.sleep(seconds)
    stop.set()
    for t in ts:
        t.join(timeout=120)
    q = lambda xs, p: round(sorted(xs)[min(len(xs) - 1, int(p * len(xs)))], 1) if xs else None  # noqa: E731
    res = {"shared": shared, "writes": out["writes"], "write_ms_p50": q(out["write_ms"], .5),
           "reads": out["reads"], "read_ms_p50": q(out["read_ms"], .5), "read_ms_p95": q(out["read_ms"], .95),
           "read_ms_max": q(out["read_ms"], 1.0), "errors": out["errors"][:5], "survived": True}
    return res


if __name__ == "__main__":
    secs = float(next((a for a in sys.argv[1:] if not a.startswith("--")), 30))
    print(json.dumps(main(secs, "--shared" in sys.argv)))
