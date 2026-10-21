"""G-218 (PLUGIN_GOAL 146): rebuild the graph store compact.

The store is ONE kuzu file that has only grown: 67.8 GB for ~70k chunks and
~1.7M addresses, where the content (768-float embeddings dominating) is a
few hundred MB. Kuzu does not give back the pages an UPDATE leaves behind,
and every embedding, `drawn` and anchor rewrite left some. Rebuilt by the
database's own round trip: EXPORT DATABASE (Parquet) from the old file, then
IMPORT DATABASE into an empty one.

The order is the safety:
  1. reader idle in Obsidian (the app's own gate), else refuse;
  2. the sidecar stopped GRACEFULLY -- the supervisor ended first (it never
     writes), then `/shutdown` to the server, which takes the work lock and
     exits; never a kill mid-write;
  3. the old store opened, its WAL replayed and checkpointed, every table
     counted;
  4. exported and imported into a NEW file beside it; every table counted
     again -- any difference and NOTHING is swapped;
  5. swapped by rename: the original is KEPT as `graph.kuzu.orig-<stamp>`
     (the reader decides when it goes);
  6. the sidecar started again with the command line it had.

Without `--go`, only reports what it would do. Every phase is timed.
"""
import json, os, shutil, subprocess, sys, time, urllib.request
from pathlib import Path

REPO = Path(r"<home>\Documents\vertiscope")
sys.path.insert(0, str(REPO))
WS = Path(next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--workspace=")), str(REPO / "build" / "corpus123")))
GO = "--go" in sys.argv
PORT = 8788
DB = WS / "graph.kuzu"
STAMP = time.strftime("%Y%m%d-%H%M%S")
WORK = REPO / "build" / ("compact-" + STAMP)
T = {}


def lap(name, t0):
    T[name] = round(time.time() - t0, 1)
    print("  %-10s %7.1f s" % (name, T[name]), flush=True)


def procs():
    import psutil
    out = []
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        cmd = " ".join(p.info.get("cmdline") or [])
        if "python" in (p.info.get("name") or "").lower() and "-m vertiscope.obsidian" in cmd and (" serve" in cmd or " supervise" in cmd):
            out.append((p.info["pid"], cmd, p.info.get("cmdline")))
    return out


def counts(conn):
    """Rows per table. A relationship counts when BOTH its endpoints exist:
    the old store held 2,548 `Anchors` and 10 `Contains` edges to nodes
    since deleted (an untyped `count(r)` includes them; they join to nothing
    and EXPORT rightly leaves them out). Those are reported, not compared."""
    tables = conn.execute("CALL show_tables() RETURN name, type").get_all()
    out, orphans = {}, {}
    for name, kind in sorted(tables):
        if str(kind).upper().startswith("NODE"):
            out[name] = int(conn.execute("MATCH (n:%s) RETURN count(n)" % name).get_all()[0][0])
            continue
        pairs = conn.execute("CALL show_connection('%s') RETURN *" % name).get_all()
        n = 0
        for row in pairs:
            # `count(r)` takes a fast path that counts edges whose SOURCE
            # node was deleted (2,548 Anchors from deleted chunks); counting a
            # key of each endpoint counts only edges that join to something.
            ka, kb = PK.get(row[0], "rowid"), PK.get(row[1], "rowid")
            n += int(conn.execute("MATCH (a:%s)-[r:%s]->(b:%s) WHERE a.%s IS NOT NULL AND b.%s IS NOT NULL "
                                  "WITH a.%s AS x RETURN count(x)" % (row[0], name, row[1], ka, kb, ka)).get_all()[0][0])
        out[name] = n
        raw = int(conn.execute("MATCH ()-[r:%s]->() RETURN count(r)" % name).get_all()[0][0])
        if raw != n:
            orphans[name] = raw - n
    COUNTS_ORPHANS.update(orphans)
    return out


COUNTS_ORPHANS = {}
PK = {"Page": "url", "Chunk": "cid", "Address": "aid", "Layout": "key", "CodeNode": "key"}


def reader_idle_ms():
    from vertiscope.obsidian.live import Live
    return Live().evaluate("window.__vertiscope.reader.idleMs()")


free = shutil.disk_usage(str(WS)).free
print(json.dumps({"store": str(DB), "store_gb": round(DB.stat().st_size / 1e9, 2),
                  "free_gb": round(free / 1e9, 1), "work": str(WORK), "go": GO}))
running = procs()
for pid, cmd, _ in running:
    print("  running", pid, cmd[:140])
if not GO:
    print("dry run: pass --go to rebuild"); sys.exit(0)

idle = reader_idle_ms()
if idle < 120000:
    print("refused: the reader is active in Obsidian (%d s idle)" % (idle // 1000)); sys.exit(1)

# 2. graceful stop
t0 = time.time()
serve_cmd = next((argv for _, cmd, argv in running if " supervise" in cmd), None) or next((argv for _, cmd, argv in running), None)
import psutil
for pid, cmd, _ in running:
    if " supervise" in cmd:
        psutil.Process(pid).kill()                 # the supervisor never writes
try:
    print("  shutdown:", urllib.request.urlopen(urllib.request.Request(
        "http://127.0.0.1:%d/shutdown" % PORT, data=b"", method="POST"), timeout=600).read()[:120])
except Exception as exc:                            # noqa: BLE001
    print("  shutdown: no answer (%s)" % exc)
deadline = time.time() + 900
while procs() and time.time() < deadline:
    time.sleep(1)
if procs():
    print("ABORT: the sidecar did not exit; nothing touched"); sys.exit(2)
lap("stop", t0)

import kuzu
ok = False
try:
    # 3. open, replay, checkpoint, count
    t0 = time.time()
    old = kuzu.Database(str(DB), buffer_pool_size=8 * 1024 ** 3)
    oc = kuzu.Connection(old)
    oc.execute("CHECKPOINT")
    before = counts(oc)
    lap("open+count", t0)
    print("  before", json.dumps(before), "orphan edges dropped:", json.dumps(COUNTS_ORPHANS))
    # 4. export, import, count
    t0 = time.time()
    WORK.mkdir(parents=True, exist_ok=True)
    oc.execute("EXPORT DATABASE '%s'" % str(WORK / "export").replace("\\", "/"))
    del oc, old
    lap("export", t0)
    exp_gb = sum(f.stat().st_size for f in (WORK / "export").rglob("*") if f.is_file()) / 1e9
    print("  export_gb %.2f" % exp_gb)
    t0 = time.time()
    new_path = WORK / "graph.kuzu"
    new = kuzu.Database(str(new_path), buffer_pool_size=8 * 1024 ** 3)
    nc = kuzu.Connection(new)
    nc.execute("IMPORT DATABASE '%s'" % str(WORK / "export").replace("\\", "/"))
    nc.execute("CHECKPOINT")
    after = counts(nc)
    del nc, new
    lap("import", t0)
    print("  after ", json.dumps(after))
    if after != before:
        print("ABORT: counts differ; the original is untouched"); sys.exit(3)
    new_gb = new_path.stat().st_size / 1e9
    print("  new_gb %.2f (was %.2f)" % (new_gb, DB.stat().st_size / 1e9))
    # 5. swap, keeping the original
    t0 = time.time()
    keep = DB.with_name("graph.kuzu.orig-" + STAMP)
    os.replace(str(DB), str(keep))
    wal = DB.with_name("graph.kuzu.wal")
    if wal.exists():
        os.replace(str(wal), str(keep) + ".wal")
    shutil.move(str(new_path), str(DB))
    lap("swap", t0)
    print("  kept", keep)
    ok = True
finally:
    # 6. start again, as it was
    t0 = time.time()
    if serve_cmd:
        log = open(WS / "sidecar.log", "a", encoding="utf-8")
        subprocess.Popen(serve_cmd, cwd=str(REPO), stdout=log, stderr=open(WS / "sidecar.err.log", "a", encoding="utf-8"),
                         creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0))
    up = False
    for _ in range(180):
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/checkpointing" % PORT, timeout=5); up = True; break
        except Exception:                           # noqa: BLE001
            time.sleep(2)
    lap("restart", t0)
    print(json.dumps({"ok": ok, "up": up, "timings_s": T}))
