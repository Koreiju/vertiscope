"""One arm of the poisoned-store repro: a FRESH copy of the live store into
build/ws-repro, a `serve` on it (port 8788) with the given env, then wait for
the plugin's queued capture: report how the process ended and what it wrote.

    python repro_arm.py '{"VERTISCOPE_ANCHOR_COPY": "1"}' [wait_s]
"""
import json, os, shutil, subprocess, sys, time
from pathlib import Path
import psutil

REPO = Path(r"<home>\Documents\vertiscope")
LIVE, WS = REPO / "build" / "corpus123", REPO / "build" / "ws-repro"
env_add = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
wait_s = float(sys.argv[2]) if len(sys.argv) > 2 else 240
for f in ("graph.kuzu", "graph.kuzu.wal"):
    if (LIVE / f).exists():
        shutil.copy2(LIVE / f, WS / f)
for f in ("statements.jsonl",):
    (WS / f).unlink(missing_ok=True)
crashes_before = (WS / "crashes.log").read_text(encoding="utf-8", errors="replace") if (WS / "crashes.log").exists() else ""
argv = json.loads((LIVE / "sidecar.argv.json").read_text(encoding="utf-8"))
argv = [str(WS) if a == str(LIVE) else a for a in argv]
argv[argv.index("supervise")] = "serve"
p = subprocess.Popen(argv, cwd=str(REPO), env={**os.environ, "VERTISCOPE_DUMP_ROWS": "1", **env_add},
                     stdout=open(WS / "serve.out.log", "a"), stderr=open(WS / "serve.err.log", "a"),
                     creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS)
t0 = time.time(); code = None
while time.time() - t0 < wait_s:
    code = p.poll()
    if code is not None:
        break
    time.sleep(1)
stmts = [json.loads(l) for l in open(WS / "statements.jsonl", encoding="utf-8")] if (WS / "statements.jsonl").exists() else []
anchors = [s for s in stmts if "query" in s and "Anchors" in s["query"]]
crashes = (WS / "crashes.log").read_text(encoding="utf-8", errors="replace")[len(crashes_before):] if (WS / "crashes.log").exists() else ""
out = {"env": env_add, "exit": code if code is not None else "still running", "after_s": round(time.time() - t0),
       "exit_meaning": {None: "-", 75: "restart requested (poisoned)", 3221225477: "ACCESS VIOLATION (segfault)"}.get(code, str(code)),
       "statements": len(stmts), "anchor_statements": len(anchors),
       "copy_errors": [s["copy_error"][:90] for s in stmts if "copy_error" in s], "crashes_log": crashes.strip()[:200]}
if code is None:
    # Still serving: the capture went through. Stop it the graceful way.
    import urllib.request
    try:
        urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:8788/shutdown", data=b"", method="POST"), timeout=120).read()
    except Exception:
        pass
    for _ in range(120):
        if p.poll() is not None:
            break
        time.sleep(1)
    out["stopped"] = p.poll()
print(json.dumps(out))
