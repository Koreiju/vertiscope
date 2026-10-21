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

    python -m vertiscope.obsidian supervise --workspace build/ws [serve options]
"""

from __future__ import annotations

import json
import os
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

#: The exit a sidecar makes when its store has outgrown its last compaction
#: (`sidecar._compact_due`): the supervisor rebuilds the store compact while
#: nothing has it open (`compact.compact`), then starts the sidecar again.
COMPACT_CODE = 76

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


def _compact_logged(workspace: Path, why: str) -> dict:
    """Compact the store (nothing has it open) and say so in both logs."""
    try:
        from .compact import compact
        got = compact(workspace)
    except Exception as exc:                   # noqa: BLE001 -- never stays down for it
        got = {"error": "%s: %s" % (type(exc).__name__, str(exc)[:200])}
    rec = {k: got.get(k) for k in ("before_mb", "after_mb", "swapped", "why_not", "error", "s")}
    for name, line in (("store_growth.log", json.dumps({"at": time.strftime("%Y-%m-%d %H:%M:%S"), "why": why, "compacted": rec})),
                       ("crashes.log", "%s compacted (%s): %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), why, json.dumps(rec)))):
        try:
            with (workspace / name).open("a", encoding="utf-8") as fh:
                fh.write(line + chr(10))
        except OSError:
            pass
    print("compacted (%s): %s" % (why, rec), flush=True)
    return got


def supervise(workspace: Path, serve_args: List[str], *,
              command: Optional[List[str]] = None, pause: float = 1.0) -> int:
    """Run `serve` with `serve_args` in a child process; restart it on a crash.

    `command` replaces the child for a test that plants a crash."""
    command = command or [sys.executable, "-X", "faulthandler", "-m",
                          "vertiscope.obsidian", "serve", "--workspace",
                          str(workspace), *serve_args]
    crashes: List[float] = []
    compacted_this_burst = False
    log = workspace / "crashes.log"
    while True:
        started = time.time()
        # The child knows a supervisor will act on COMPACT_CODE.
        code = subprocess.call(command, env={**os.environ, "VERTISCOPE_SUPERVISED": "1"})
        if code == 0:
            return 0                           # a clean stop is not a crash
        if code == RESTART_CODE:
            continue                           # asked for (POST /shutdown): not a crash
        if code == COMPACT_CODE:               # asked for: outgrown, or its pool refused
            _compact_logged(workspace, "asked")
            continue
        now = time.time()
        crashes = [t for t in crashes if now - t < WINDOW_S] + [now]
        if len(crashes) == 1:
            compacted_this_burst = False
        line = "%s exit=%s after=%.0fs statement=%s" % (
            time.strftime("%Y-%m-%d %H:%M:%S"), code, now - started,
            _statement(workspace)) + chr(10)
        try:
            with log.open("a", encoding="utf-8") as fh:
                fh.write(line)
        except OSError:
            pass
        print("sidecar crashed (%s); %s" % (code, line.strip()), flush=True)
        # Two crashes inside a minute: the STORE, not the moment, is the
        # problem -- 2026-10-18 13:39-13:44 every start segfaulted 22 s in, at
        # CHECKPOINT, replaying a WAL its pool could not hold; compacted with
        # a larger pool it opened, folded that WAL and shrank 5,143 -> 1,543
        # MB. Tried once per burst, and BEFORE setting the WAL aside below,
        # which loses what the WAL held. Planted `VERTISCOPE_PLANT_NO_CRASH_COMPACT`.
        if len(crashes) >= 2 and not compacted_this_burst and os.environ.get("VERTISCOPE_PLANT_NO_CRASH_COMPACT") != "1":
            compacted_this_burst = True
            if _compact_logged(workspace, "two crashes in a minute").get("swapped"):
                crashes = []
                time.sleep(pause)
                continue
        # Two starts in a row that could not even open the store, with a
        # write-ahead log present: the log is the thing that will not replay.
        quick = [t for t in crashes if now - t < WINDOW_S]
        if now - started < FAILED_OPEN_S and len(quick) >= 2:
            aside = quarantine_wal(workspace)
            if aside is not None:
                note = "%s store would not open twice; write-ahead log set aside as %s" % (
                    time.strftime("%Y-%m-%d %H:%M:%S"), aside.name) + chr(10)
                try:
                    with log.open("a", encoding="utf-8") as fh:
                        fh.write(note)
                except OSError:
                    pass
                print(note.strip(), flush=True)
                crashes = []                 # a fresh chance to start
        if len(crashes) >= BURST:
            print("%d crashes inside %.0f s -- not restarting" % (BURST, WINDOW_S),
                  flush=True)
            return code or 1
        time.sleep(pause)
