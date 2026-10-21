"""Rebuild the store compact: kuzu's own EXPORT/IMPORT round trip (G-218).

Kuzu never gives back the pages an update leaves behind. Measured on
2026-10-18 (`scripts/store_growth_vectors.py`, `scripts/store_growth_probe.py`):
writing a vector into an existing row grows the file by 4-5.5x the vector on a
fresh store and **33x** on the working one (5,000 embeddings: +1,026 MB for
31 MB of floats); markdown rewrites ~1-2x. The embedder writes every vector
into a row that already exists, so the file grows without bound -- 67.8 GB for
1.4 GB of content once, and 1.44 -> 5.14 GB within 40 minutes of a rebuild.

The round trip is the remedy (32 s for the working store) and this is it,
used by `scripts/compact_store.py` (by hand) and by the supervisor (when the
sidecar exits with `COMPACT_CODE` because its store outgrew its last
compaction). The order is the safety: counts before, export, import into a
NEW file, counts after -- any difference and NOTHING is swapped -- then the
swap by rename, the previous file kept.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Dict, Optional

#: Primary keys, so a relationship counts only when both its ends exist (an
#: untyped `count(r)` also counts edges whose source was DELETED, which EXPORT
#: rightly leaves out -- the first two manual runs aborted on exactly that).
PK = {"Page": "url", "Chunk": "cid", "Address": "aid", "Layout": "key", "CodeNode": "key"}

#: The previous file an AUTOMATIC compaction keeps. One, replaced each time:
#: a store compacting itself every few hours must not fill the disk with
#: copies of itself. Files kept by a person (`graph.kuzu.orig-<stamp>`) are
#: never touched.
AUTO_KEEP = "graph.kuzu.prev-auto"

#: Written after every compaction: the size it left, the baseline growth is
#: measured against (`sidecar._compact_due`).
MARK = "compacted.json"


def counts(conn) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for name, kind in sorted(conn.execute("CALL show_tables() RETURN name, type").get_all()):
        if str(kind).upper().startswith("NODE"):
            out[name] = int(conn.execute("MATCH (n:%s) RETURN count(n)" % name).get_all()[0][0])
            continue
        n = 0
        for row in conn.execute("CALL show_connection('%s') RETURN *" % name).get_all():
            ka, kb = PK.get(row[0], "rowid"), PK.get(row[1], "rowid")
            n += int(conn.execute(
                "MATCH (a:%s)-[r:%s]->(b:%s) WHERE a.%s IS NOT NULL AND b.%s IS NOT NULL "
                "WITH a.%s AS x RETURN count(x)" % (row[0], name, row[1], ka, kb, ka)).get_all()[0][0])
        out[name] = n
    return out


def compact(workspace: Path, *, keep_as: Optional[str] = None, pool_bytes: int = 6 * 1024 ** 3,
            log=print) -> Dict:
    """Rebuild `workspace/graph.kuzu` compact. The store must not be open
    elsewhere. Returns what happened; `swapped` is False whenever anything
    did not match, and then the original is untouched."""
    from ..graphstore import open_kuzu

    workspace = Path(workspace)
    db = workspace / "graph.kuzu"
    stamp = time.strftime("%Y%m%d-%H%M%S")
    work = workspace / ("compact-work-" + stamp)
    t = {}
    out: Dict = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "before_mb": round(db.stat().st_size / 1e6, 1),
                 "swapped": False}
    t0 = time.time()
    old, oc = open_kuzu(db, pool_bytes)
    oc.execute("CHECKPOINT")
    before = counts(oc)
    t["count"] = round(time.time() - t0, 1)
    try:
        t0 = time.time()
        work.mkdir(parents=True, exist_ok=True)
        oc.execute("EXPORT DATABASE '%s'" % str(work / "export").replace("\\", "/"))
        del oc, old
        t["export"] = round(time.time() - t0, 1)
        t0 = time.time()
        new_path = work / "graph.kuzu"
        new, nc = open_kuzu(new_path, pool_bytes)
        nc.execute("IMPORT DATABASE '%s'" % str(work / "export").replace("\\", "/"))
        nc.execute("CHECKPOINT")
        after = counts(nc)
        del nc, new
        t["import"] = round(time.time() - t0, 1)
        out.update(counts_before=before, counts_after=after)
        if after != before:
            out["why_not"] = "counts differ"
            log("compact: counts differ; the original is untouched")
            return out
        keep = workspace / (keep_as or AUTO_KEEP)
        if keep.exists():
            keep.unlink()
        os.replace(str(db), str(keep))
        wal = workspace / "graph.kuzu.wal"
        if wal.exists():
            os.replace(str(wal), str(keep) + ".wal")
        shutil.move(str(new_path), str(db))
        out.update(swapped=True, after_mb=round(db.stat().st_size / 1e6, 1), kept=keep.name, s=t)
        (workspace / MARK).write_text(json.dumps(out), encoding="utf-8")
        log("compact: %.1f -> %.1f MB, kept %s" % (out["before_mb"], out["after_mb"], keep.name))
        return out
    finally:
        shutil.rmtree(work, ignore_errors=True)
