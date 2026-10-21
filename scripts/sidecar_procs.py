"""The sidecar's processes, found by their ARGUMENTS (never by matching a
command-line string, which also matches the script doing the looking), and a
graceful stop of all of them: every supervisor first (they never write), then
`/shutdown` to the server.

    python scripts/sidecar_procs.py           list
    python scripts/sidecar_procs.py stop      stop all
"""
import os
import sys
import time
import urllib.request

import psutil

PORT = 8788


def procs():
    me = os.getpid()
    out = []
    for p in psutil.process_iter(["pid", "cmdline"]):
        if p.info["pid"] == me:
            continue
        a = p.info["cmdline"] or []
        if "-m" in a and "vertiscope.obsidian" in a:
            i = a.index("vertiscope.obsidian")
            kind = a[i + 1] if i + 1 < len(a) else ""
            if kind in ("serve", "supervise"):
                out.append((p.info["pid"], kind, p))
    return out


def stop(timeout=300):
    for pid, kind, p in procs():
        if kind == "supervise":
            try:
                p.kill()
            except psutil.Error:
                pass
    time.sleep(1)
    if any(k == "serve" for _, k, _ in procs()):
        try:
            urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:%d/shutdown" % PORT, data=b"", method="POST"),
                                   timeout=120).read()
        except Exception:                           # noqa: BLE001
            pass
    t0 = time.time()
    while procs() and time.time() - t0 < timeout:
        time.sleep(1)
    return [(pid, k) for pid, k, _ in procs()]


if __name__ == "__main__":
    if sys.argv[1:] == ["stop"]:
        print("left:", stop())
    else:
        for pid, kind, p in procs():
            print(pid, kind)
