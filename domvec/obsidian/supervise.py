"""Keep the sidecar up through a native crash, and record each one (`D-23`).

The sidecar segfaults inside kuzu under sustained load -- native, exit 139,
one Python thread in `execute` and every other thread parked. That is not
fixed; this is what makes it survivable. A crash used to end everything the
plugin does until someone restarted the process by hand. With the projector's
fit kept on disk and the lexical rows persisted, a restart is ready in about
eight seconds, so the supervisor turns a crash into an eight-second gap.

It is a mitigation, and it says so: every crash is appended to
`<workspace>/crashes.log` with its exit code and the statement kuzu was
running (`last_statement.txt`, written before every statement by
`GraphStore._breadcrumb`). A crash that repeats faster than it can be useful
to restart -- five inside a minute -- stops the loop rather than hiding a
process that cannot stay up.

    python -m domvec.obsidian supervise --workspace build/ws [serve options]
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional

#: Crashes inside this window that stop the loop instead of restarting.
BURST = 5
WINDOW_S = 60.0

#: A start that dies this fast did not run: it failed to OPEN the store.
FAILED_OPEN_S = 15.0



#: The exit a sidecar makes when asked to RESTART (POST /shutdown): the
#: supervisor starts it again without logging a crash or counting toward
#: setting the write-ahead log aside. Exit 0 stays "stop".
RESTART_CODE = 75

def quarantine_wal(workspace: Path) -> Optional[Path]:
    """Set an unreplayable write-ahead log aside so the store can open.

    A crash mid-write (`D-23`) can leave ``graph.kuzu.wal`` that kuzu then
    fails to replay -- "Caught an unknown exception!" at open, read-only or
    not -- so every restart dies in two seconds and the loop gives up. On
    2026-09-26 the working store sat unopenable until the log was moved by
    hand; the 138 pages were intact behind it.

    Renamed, never deleted: what the log held (the last few captures) is
    unreachable either way, and a renamed file can still be put back.
    """
    wal = workspace / "graph.kuzu.wal"
    if not wal.exists():
        return None
    aside = workspace / ("graph.kuzu.wal.unreplayable-%s" % time.strftime("%Y%m%d-%H%M%S"))
    try:
        wal.rename(aside)
    except OSError:
        return None
    return aside


def _statement(workspace: Path) -> str:
    try:
        return (workspace / "last_statement.txt").read_text(
            encoding="utf-8", errors="replace").strip()
    except OSError:
        return "(no breadcrumb)"


def supervise(workspace: Path, serve_args: List[str], *,
              command: Optional[List[str]] = None, pause: float = 1.0) -> int:
    """Run `serve` with `serve_args` in a child process; restart it on a crash.

    `command` replaces the child for a test that plants a crash."""
    command = command or [sys.executable, "-X", "faulthandler", "-m",
                          "domvec.obsidian", "serve", "--workspace",
                          str(workspace), *serve_args]
    crashes: List[float] = []
    log = workspace / "crashes.log"
    while True:
        started = time.time()
        code = subprocess.call(command)
        if code == 0:
            return 0                           # a clean stop is not a crash
        if code == RESTART_CODE:
            continue                           # asked for (POST /shutdown): not a crash
        now = time.time()
        crashes = [t for t in crashes if now - t < WINDOW_S] + [now]
        # Two starts in a row that could not even open the store, with a
        # write-ahead log present: the log is the thing that will not replay.
        quick = [t for t in crashes if now - t < WINDOW_S]
        if code != 0 and now - started < FAILED_OPEN_S and len(quick) >= 2:
            aside = quarantine_wal(workspace)
            if aside is not None:
                note = "%s store would not open twice; write-ahead log set aside as %s\n" % (
                    time.strftime("%Y-%m-%d %H:%M:%S"), aside.name)
                try:
                    with log.open("a", encoding="utf-8") as fh:
                        fh.write(note)
                except OSError:
                    pass
                print(note.strip(), flush=True)
                crashes = []                 # a fresh chance to start
        line = "%s exit=%s after=%.0fs statement=%s\n" % (
            time.strftime("%Y-%m-%d %H:%M:%S"), code, now - started,
            _statement(workspace))
        try:
            with log.open("a", encoding="utf-8") as fh:
                fh.write(line)
        except OSError:
            pass
        print("sidecar crashed (%s); %s" % (code, line.strip()), flush=True)
        if len(crashes) >= BURST:
            print("%d crashes inside %.0f s -- not restarting" % (BURST, WINDOW_S),
                  flush=True)
            return code or 1
        time.sleep(pause)
