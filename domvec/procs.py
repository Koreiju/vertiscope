"""How domvec starts processes, and what they put on the screen.

**Why this exists (PLUGIN_GOAL 157).** "whenever I run the sidecar,
especially in the GUI, I get like 4 to 5 different command lines spawning".
The cause is a Windows rule, not the process count: a console program whose
parent has NO console is given a NEW, visible console window. The plugin
starts the supervisor with Node's `detached: true` (DETACHED_PROCESS -- no
console at all), so every console child below it -- the worker, each worker
restart, every `git` and `taskkill` -- opened a window of its own.

The standard-library fix is one creation flag: `CREATE_NO_WINDOW` gives the
child a console that is never shown, and the child's own children INHERIT that
hidden console instead of being given new ones. So one flag at the top of the
tree covers everything below it, and `hidden()` puts it on every call here.

The processes themselves stay: the front/worker split is for crash isolation
and restarts (exit 76 compaction, a wedged worker), not for the GIL -- the
embedder already runs on a thread, and torch releases the GIL in its kernels.

`census()` is the measurement: the process tree under a root pid, and the
VISIBLE top-level windows any of them own. Planted:
`DOMVEC_PLANT_CONSOLE_WINDOWS=1` drops the flag, so the census has to count
windows again.
"""
from __future__ import annotations

import os
import subprocess
import sys
from typing import Dict, List

WINDOWS = sys.platform == "win32"


def planted() -> bool:
    return os.environ.get("DOMVEC_PLANT_CONSOLE_WINDOWS") == "1"


def hidden(**kw) -> Dict:
    """`subprocess` keyword arguments with the window suppressed (Windows);
    any `creationflags` the caller passed are kept."""
    if WINDOWS and not planted():
        kw["creationflags"] = kw.get("creationflags", 0) | subprocess.CREATE_NO_WINDOW
    return kw


def _visible_windows() -> Dict[int, List[str]]:
    """pid -> titles of its visible top-level windows (ctypes, stdlib)."""
    out: Dict[int, List[str]] = {}
    if not WINDOWS:
        return out
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def each(hwnd, _l):
        if not user32.IsWindowVisible(hwnd):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, buf, 256)
        cls = ctypes.create_unicode_buffer(128)
        user32.GetClassNameW(hwnd, cls, 128)
        out.setdefault(pid.value, []).append("%s [%s]" % (buf.value, cls.value))
        return True

    user32.EnumWindows(proto(each), 0)
    return out


def census(root_pid: int) -> Dict:
    """The tree under `root_pid` and the visible windows it owns.

    A console window is owned, as Windows reports it, by the console host
    (`conhost.exe` / `OpenConsole.exe`) or by Windows Terminal -- so hosts
    that are CHILDREN of a tree process are counted as that tree's too.
    """
    try:
        import psutil
    except ImportError:
        return {"error": "psutil missing"}
    try:
        root = psutil.Process(root_pid)
        tree = [root] + root.children(recursive=True)
    except psutil.Error as exc:
        return {"error": str(exc)}
    wins = _visible_windows()
    procs, windows = [], []
    for p in tree:
        try:
            name = p.name()
            cmd = " ".join(p.cmdline())[:120]
        except psutil.Error:
            continue
        procs.append({"pid": p.pid, "ppid": p.ppid(), "name": name, "cmd": cmd})
        for t in wins.get(p.pid, []):
            windows.append({"pid": p.pid, "name": name, "window": t})
    return {"root": root_pid, "processes": len(procs),
            "consoles": sum(1 for p in procs if p["name"].lower() in ("conhost.exe", "openconsole.exe")),
            "visible_windows": len(windows), "windows": windows, "tree": procs,
            "planted": planted()}
