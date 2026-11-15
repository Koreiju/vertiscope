"""Reproduce the native store crash on a SCRATCH COPY, never the working store.

    python -m domvec.analytics.store_crash --source <graph.kuzu> --minutes 10
    python -m domvec.analytics.store_crash --source <graph.kuzu> --arms split,shared --minutes 10

115 access violations (0xC0000005) are logged in `crashes.log` across ten
statements, and crashes per hour ran 1.00 while the store was GROWN (after a
checkpoint that grew it by >= 500 MB, before the next compaction) against
0.01 while clean (2026-11-08..15). That is an association, confounded by
activity. This harness drives the sidecar's own write mix through the
application's own `GraphStore`, on a copy:

- writer: `SET c.embedding` on ~100 scattered chunks a batch (the embed
  thread's statement, one of the logged crashers), and the anchor wipe;
- reader: the split read connection (`_rows`), as the pane's polls use it;
- checkpointer: `GraphStore.checkpoint()` once the WAL passes 8 MB, as
  `_checkpoint_forever` does, recording the store's size before and after.

Each arm runs in a CHILD process, so a native crash is an exit code, not this
process dying. Arms:

  split    -- the sidecar as shipped: a second read connection beside the writer
  shared   -- `DOMVEC_SHARED_READS=1`: one connection for reads and writes
  capture, capture_shared -- the same, plus a re-capture's Address MERGE ... SET
              of every string column on one page's addresses per batch (the
              statement 55 of the 115 logged crashes were in)
  planted  -- the child dereferences a null pointer: the harness must call
              THIS a native crash, or it cannot see one (non-vacuity)

Writes `build_analytics/store_crash.md` and `.json`.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ACCESS_VIOLATION = 3221225477          # 0xC0000005 as Windows reports the exit
OUT = Path("build_analytics")


def _child(store_path: str, seconds: float, arm: str, seed: int) -> None:
    """Runs IN the child. Prints one JSON line per event; exits 0 at time-out."""
    import threading
    import numpy as np
    if arm == "planted":
        import faulthandler
        print(json.dumps({"event": "planting"}), flush=True)
        faulthandler._read_null()       # a native access violation (ctypes would catch it as OSError)
        return
    from domvec.graphstore import GraphStore, EMBED_DIM
    gs = GraphStore(store_path)
    rng = np.random.default_rng(seed)
    cids = [r[0] for r in gs._rows("MATCH (c:Chunk) RETURN c.cid")]
    urls = [r[0] for r in gs._rows("MATCH (p:Page) RETURN p.url")]
    print(json.dumps({"event": "open", "chunks": len(cids), "pages": len(urls),
                      "split": gs._read_conn is not None}), flush=True)
    wal = Path(store_path + ".wal")
    db = Path(store_path)
    stop = threading.Event()
    counts = {"writes": 0, "reads": 0, "checkpoints": 0, "read_errors": 0}

    def reader():
        r = np.random.default_rng(seed + 1)
        while not stop.is_set():
            u = urls[int(r.integers(len(urls)))]
            try:
                gs._rows("MATCH (c:Chunk) WHERE c.url = $u RETURN c.cid, c.md, c.embedding LIMIT 40", {"u": u})
                counts["reads"] += 1
            except Exception:           # noqa: BLE001
                counts["read_errors"] += 1
            time.sleep(0.02)

    th = threading.Thread(target=reader, daemon=True)
    th.start()
    t_end = time.time() + seconds
    capture = arm.startswith("capture")
    counts["address_rows"] = 0
    while time.time() < t_end:
        if capture:
            # A re-capture: one page's addresses MERGEd again with every
            # string column SET -- the statement 55 of 115 logged crashes
            # were in -- and its values changed, as a page that moved.
            u = urls[int(rng.integers(len(urls)))]
            got = gs._rows("MATCH (a:Address) WHERE a.url = $u RETURN a.aid, a.akey, a.xpath, a.tag, "
                           "a.accessor, a.value, a.content_hash LIMIT 400", {"u": u})
            if got:
                tick = counts["writes"]
                rows = [{"aid": r[0], "akey": r[1] or "", "url": u, "xp": r[2] or "", "tag": r[3] or "",
                         "acc": r[4] or "", "val": ((r[5] or "") + " ~%d" % tick)[:400], "ch": r[6] or ""} for r in got]
                if arm.startswith("capture_value"):
                    # Only the column that changed: does the growth follow the
                    # number of string columns rewritten?
                    gs._batch("UNWIND $rows AS r MERGE (a:Address {aid: r.aid}) SET a.value = r.val", rows)
                else:
                    gs._batch("UNWIND $rows AS r MERGE (a:Address {aid: r.aid}) "
                              "SET a.akey = r.akey, a.url = r.url, a.xpath = r.xp, a.tag = r.tag, "
                              "a.accessor = r.acc, a.value = r.val, a.content_hash = r.ch", rows)
                counts["address_rows"] += len(rows)
        pick = rng.choice(len(cids), size=min(100, len(cids)), replace=False)
        rows = [{"cid": cids[i], "emb": rng.normal(size=EMBED_DIM).astype("float32").tolist()} for i in pick]
        gs._batch("UNWIND $rows AS r MATCH (c:Chunk {cid: r.cid}) SET c.embedding = r.emb", rows)
        counts["writes"] += 1
        if counts["writes"] % 10 == 0:
            few = [{"cid": cids[int(i)]} for i in rng.choice(len(cids), size=5, replace=False)]
            gs._batch("UNWIND $rows AS r MATCH (c:Chunk {cid: r.cid})-[e:Anchors]->(:Address) DELETE e", few)
        size = wal.stat().st_size if wal.exists() else 0
        if size >= 8_000_000:
            before = db.stat().st_size
            ms = gs.checkpoint()
            after = db.stat().st_size
            counts["checkpoints"] += 1
            print(json.dumps({"event": "checkpoint", "wal_mb": round(size / 1e6, 2), "before_mb": round(before / 1e6, 1),
                              "after_mb": round(after / 1e6, 1), "ms": ms, "at_s": round(seconds - (t_end - time.time()), 1),
                              **counts}), flush=True)
    stop.set()
    th.join(timeout=5)
    print(json.dumps({"event": "done", **counts}), flush=True)
    gs.close()


def _copy(source: Path, dest: Path) -> None:
    if dest.exists():
        dest.unlink()
    for side in (Path(str(dest) + ".wal"),):
        if side.exists():
            side.unlink()
    shutil.copyfile(source, dest)
    wal = Path(str(source) + ".wal")
    if wal.exists() and wal.stat().st_size:
        raise SystemExit("source has a WAL (%s): copy a CLOSED store" % wal)


def run_arm(source: Path, scratch: Path, arm: str, seconds: float, seed: int = 0) -> dict:
    dest = scratch / ("crash_%s.kuzu" % arm)
    if arm != "planted":
        _copy(source, dest)
    env = dict(os.environ)
    env.pop("DOMVEC_SHARED_READS", None)
    if arm.endswith("shared"):
        env["DOMVEC_SHARED_READS"] = "1"
    started = time.time()
    p = subprocess.run([sys.executable, "-X", "faulthandler", "-m", "domvec.analytics.store_crash", "--child",
                        "--store", str(dest), "--seconds", str(seconds), "--arm", arm, "--seed", str(seed)],
                       capture_output=True, text=True, env=env, timeout=seconds + 600)
    events = []
    for line in p.stdout.splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            pass
    cps = [e for e in events if e.get("event") == "checkpoint"]
    last = ([e for e in events if e.get("event") in ("done", "checkpoint")] or [{}])[-1]
    out = {"arm": arm, "exit": p.returncode, "native_crash": p.returncode == ACCESS_VIOLATION,
           "ran_s": round(time.time() - started, 1), "checkpoints": len(cps),
           "grew_mb": [round(e["after_mb"] - e["before_mb"], 1) for e in cps],
           "writes": last.get("writes"), "reads": last.get("reads"), "read_errors": last.get("read_errors"),
           "address_rows": last.get("address_rows"),
           "stderr_tail": p.stderr[-1500:] if p.returncode not in (0,) else ""}
    if arm != "planted":
        for f in (dest, Path(str(dest) + ".wal")):
            try:
                f.unlink()
            except OSError:
                pass
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--child", action="store_true")
    ap.add_argument("--store")
    ap.add_argument("--seconds", type=float, default=600)
    ap.add_argument("--arm", default="split")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--source")
    ap.add_argument("--minutes", type=float, default=10)
    ap.add_argument("--arms", default="planted,split,shared")
    ap.add_argument("--scratch", default=str(OUT / "crash_scratch"))
    a = ap.parse_args(argv)
    if a.child:
        _child(a.store, a.seconds, a.arm, a.seed)
        return 0
    source = Path(a.source)
    scratch = Path(a.scratch)
    scratch.mkdir(parents=True, exist_ok=True)
    results = []
    for arm in a.arms.split(","):
        r = run_arm(source, scratch, arm.strip(), a.minutes * 60)
        print(json.dumps({k: v for k, v in r.items() if k != "stderr_tail"}), flush=True)
        results.append(r)
    OUT.mkdir(exist_ok=True)
    (OUT / "store_crash.json").write_text(json.dumps({"source": str(source), "results": results}, indent=1), encoding="utf-8")
    lines = ["# store_crash", "", "source: `%s` (copied per arm; mtime %s)" % (source, time.ctime(source.stat().st_mtime)), "",
             "| arm | exit | native crash | ran s | checkpoints | grew MB per checkpoint | writes | reads |", "|---|---|---|---|---|---|---|---|"]
    for r in results:
        lines.append("| %s | %s | %s | %s | %s | %s | %s | %s |" % (r["arm"], r["exit"], r["native_crash"], r["ran_s"], r["checkpoints"],
                                                                 ", ".join(str(g) for g in r["grew_mb"][:12]), r["writes"], r["reads"]))
    planted = [r for r in results if r["arm"] == "planted"]
    if planted and not planted[0]["native_crash"]:
        lines += ["", "**VACUOUS: the planted crash was not seen as one (exit %s).**" % planted[0]["exit"]]
    (OUT / "store_crash.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
