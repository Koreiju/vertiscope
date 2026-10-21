"""The store OFFLINE for a moment: the sidecar stopped gracefully, the body
run, the sidecar started again with the command line it had -- whatever the
body does. The supervisor goes first (it never writes); the server gets
`/shutdown`, which takes the work lock and exits; never a kill mid-write.
Refuses while the reader is active in Obsidian.

    from store_offline import offline
    with offline() as db_path: ...
"""
import contextlib, json, subprocess, sys, time, urllib.request
from pathlib import Path

REPO = Path(r"<home>\Documents\vertiscope")
sys.path.insert(0, str(REPO))
PORT = 8788


def procs():
    import psutil
    out = []
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        cmd = " ".join(p.info.get("cmdline") or [])
        if "python" in (p.info.get("name") or "").lower() and "-m vertiscope.obsidian" in cmd and (" serve" in cmd or " supervise" in cmd):
            out.append((p.info["pid"], cmd, p.info.get("cmdline")))
    return out


def reader_idle_ms():
    from vertiscope.obsidian.live import Live
    return Live().evaluate("window.__vertiscope.reader.idleMs()")


@contextlib.contextmanager
def offline(workspace=REPO / "build" / "corpus123", idle_ms=120000, timings=None, env=None):
    timings = timings if timings is not None else {}
    idle = reader_idle_ms()
    if idle < idle_ms:
        raise SystemExit("refused: the reader is active in Obsidian (%d s idle)" % (idle // 1000))
    running = procs()
    argv = next((a for _, c, a in running if " supervise" in c), None) or next((a for _, c, a in running), None)
    # The command line is WRITTEN before anything stops: a helper killed
    # between stop and start (2026-10-18) left the sidecar down with nothing
    # to restart it from. A later call -- or a person -- starts it from here.
    saved = Path(workspace) / "sidecar.argv.json"
    if argv:
        saved.write_text(json.dumps(argv), encoding="utf-8")
    elif saved.exists():
        argv = json.loads(saved.read_text(encoding="utf-8"))
    import psutil
    t0 = time.time()
    for pid, cmd, _ in running:
        if " supervise" in cmd:
            psutil.Process(pid).kill()             # the supervisor never writes
    try:
        urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:%d/shutdown" % PORT, data=b"", method="POST"), timeout=600).read()
    except Exception:                               # noqa: BLE001
        pass
    deadline = time.time() + 900
    while procs() and time.time() < deadline:
        time.sleep(1)
    if procs():
        raise SystemExit("the sidecar did not exit; nothing touched")
    timings["stop"] = round(time.time() - t0, 1)
    try:
        yield Path(workspace) / "graph.kuzu"
    finally:
        t0 = time.time()
        if argv:
            ws = Path(workspace)
            import os
            subprocess.Popen(argv, cwd=str(REPO), env={**os.environ, **(env or {})}, stdout=open(ws / "sidecar.log", "a", encoding="utf-8"),
                             stderr=open(ws / "sidecar.err.log", "a", encoding="utf-8"),
                             creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0))
        for _ in range(180):
            try:
                urllib.request.urlopen("http://127.0.0.1:%d/checkpointing" % PORT, timeout=5)
                break
            except Exception:                       # noqa: BLE001
                time.sleep(2)
        timings["restart"] = round(time.time() - t0, 1)


def restart(env=None, idle_ms=60000):
    """A graceful restart, the new sidecar started with `env` added (a
    planted arm read at startup), or without it."""
    t = {}
    with offline(idle_ms=idle_ms, timings=t, env=env):
        pass
    return t
