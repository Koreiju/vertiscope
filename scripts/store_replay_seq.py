"""Replay a dumped statement SEQUENCE (statements.jsonl) on a COPY of the store,
in one process and one connection, as the sidecar ran it. A `COPY ... FROM df`
is rebuilt from the next statement's rows (the fallback carries the same rows).

    python replay_seq.py <db> <statements.jsonl> [--skip-copy] [--checkpoint-after-delete]
"""
import json
import sys

import kuzu
import pandas as pd

db_path, log = sys.argv[1], sys.argv[2]
flags = set(sys.argv[3:])
db = kuzu.Database(db_path); c = kuzu.Connection(db)
stmts = [x for x in (json.loads(l) for l in open(log, encoding="utf-8") if l.strip()) if "query" in x]
for i, s in enumerate(stmts):
    q, p = s["query"], s["params"] or {}
    if q.startswith("COPY Anchors FROM df"):
        if "--skip-copy" in flags:
            print(i, "COPY skipped", flush=True); continue
        rows = stmts[i + 1]["params"]["rows"]
        df = pd.DataFrame({"from": [r["cid"] for r in rows], "to": [r["aid"] for r in rows], "ord": [int(r["ord"]) for r in rows]})
        try:
            c.execute("COPY Anchors FROM df"); print(i, "COPY ok", len(rows), flush=True)
            if "--stop-after-copy-ok" in flags: break
            stmts[i + 1]["skip"] = True      # the fallback only runs when COPY raised
        except Exception as e:
            print(i, "COPY raised:", str(e)[:160], flush=True)
        continue
    if s.get("skip"):
        print(i, "fallback not needed", flush=True); continue
    print(i, "run", " ".join(q.split())[:70], flush=True)
    c.execute(q, p)
    if "--checkpoint-after-delete" in flags and "DELETE" in q:
        c.execute("CHECKPOINT"); print(i, "checkpoint", flush=True)
print("sequence ok", flush=True)
