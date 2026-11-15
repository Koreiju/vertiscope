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

#: A start that STALLED: no answer on /health inside `START_DEADLINE_S`, and
#: no CPU spent for `START_STALL_S` -- killed and started again (2026-10-24:
#: a child started after a compaction sat 10 min with torch and OpenBLAS
#: loaded, 2.3 s of CPU, its main thread in a kernel wait, and the reader's
#: sidecar was simply gone). Planted `DOMVEC_PLANT_NO_START_DEADLINE=1`.
STUCK_CODE = 70
START_DEADLINE_S = float(os.environ.get("DOMVEC_START_DEADLINE_S") or 240.0)
START_STALL_S = float(os.environ.get("DOMVEC_START_STALL_S") or 60.0)
#: The EARLY stall: a child that has spent under `EARLY_CPU_S` of CPU after
#: `EARLY_S` never got past the interpreter's own start. Every hung child on
#: 2026-10-24/25 sat at 13 MB and 0.02 s of CPU inside the Store Python's
#: package lookup, where a healthy start has spent seconds importing by then;
#: waiting out `START_DEADLINE_S` for each cost 4 min a try, and they came in
#: runs (a compaction child too, which held the sidecar down under a 1 h
#: timeout). Planted `DOMVEC_PLANT_NO_START_DEADLINE` covers both.
EARLY_S = float(os.environ.get("DOMVEC_EARLY_S") or 25.0)
EARLY_CPU_S = 0.5
#: ...and still SMALL. A child of a freshly installed venv waits on Windows
#: Defender scanning every new torch/numba DLL as it loads them: little CPU
#: for half a minute, but hundreds of MB resident. Killed on CPU alone, a new
#: user's first start was killed three times and the supervisor gave up
#: (2026-11-15, the README proof: exit 70 three times in 84 s). The hang this
#: rule exists for sat at 13 MB. Planted `DOMVEC_PLANT_EARLY_CPU_ONLY=1`.
EARLY_RSS_MB = 40.0
#: Stalled starts in a row after which this supervisor gives up: once one
#: hangs, every later child of the same supervisor hung too (2026-10-25,
#: five in a row), while a FRESH supervisor's first child always started. It
#: leaves `supervisor_gave_up.json` in the workspace and exits; the plugin,
#: seeing that and no sidecar, starts a fresh supervisor.
GIVE_UP_STALLS = 3

#: A worker that DIED BUT DID NOT EXIT (2026-11-14 19:55): two chat turns
#: generated on one gpt4all model at once, faulthandler wrote "Windows fatal
#: exception: access violation" and the thread dumps to the err log -- and
#: the process then sat in its teardown for nine minutes, one thread, no CPU,
#: no answer on its port, 23 GB still mapped, while the front answered
#: /health from its cache. Once a child had answered /health once this loop
#: stopped looking at it, so nothing restarted it. Now: a fatal dump in the
#: log the child writes, AND no /health, AND no CPU for `FATAL_GRACE_S` --
#: all three, so a busy worker (which answers, or spends CPU) is never read
#: as dead. Planted `DOMVEC_PLANT_NO_FATAL_WATCH=1`.
HUNG_CODE = 71
FATAL_GRACE_S = float(os.environ.get("DOMVEC_FATAL_GRACE_S") or 20.0)
FATAL_MARKS = ("Fatal Python error:", "Windows fatal exception:", "Segmentation fault")
#: The current worker as the front reports it: when a fatal dump was seen
#: and whether a kill could not end the process. The 19:55 worker read as
#: "busy" for twenty minutes; with this it reads "dead". A kill that does not
#: finish in `KILL_WAIT_S` is a process the KERNEL is holding (its rundown
#: stuck in a driver -- that one kept its sockets, 565 handles and 23 GB after
#: TerminateProcess): it is logged as unkillable and this loop goes on rather
#: than waiting on it forever.
WORKER = {"pid": None, "fatal_at": None, "unkillable_at": None}
KILL_WAIT_S = float(os.environ.get("DOMVEC_KILL_WAIT_S") or 30.0)


class _FatalWatch:
    """New text in the child's err log, scanned for a fatal dump. Reads only
    what was appended since the child started, and only when the file grew."""

    def __init__(self, path: Optional[Path]):
        self.path = path
        self.at = self._size()
        self.seen: Optional[float] = None

    def _size(self) -> int:
        try:
            return self.path.stat().st_size if self.path is not None else 0
        except OSError:
            return 0

    def poll(self) -> Optional[float]:
        if self.path is None or self.seen is not None:
            return self.seen
        size = self._size()
        if size > self.at:
            try:
                with self.path.open("rb") as fh:
                    fh.seek(max(0, self.at - 64))      # a mark split across two polls
                    text = fh.read(size - self.at + 64).decode("utf-8", "replace")
            except OSError:
                return None
            self.at = size
            if any(m in text for m in FATAL_MARKS):
                self.seen = time.time()
        return self.seen


def _port_of(args: List[str]) -> Optional[int]:
    for i, a in enumerate(args):
        if a == "--port" and i + 1 < len(args):
            try:
                return int(args[i + 1])
            except ValueError:
                return None
    return None


def _healthy(port: int) -> bool:
    import urllib.request
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/health" % port, timeout=5) as r:
            return r.status == 200
    except Exception:                               # noqa: BLE001
        return False


class _Tree:
    """The child AND its descendants, read as one process.

    A venv's `python.exe` on Windows is a launcher: it starts the real
    interpreter as ITS child and waits, at 11.7 MB and 0.02 s of CPU for good.
    Watching only the launcher, every rule here read a busy worker as hung: on a
    fresh venv's first start the real worker stood at 525 MB and 21 s of CPU
    when the early-stall rule killed it, three times, and the supervisor gave
    up (2026-11-15, the README proof's process samples). The CPU and size that
    count are the tree's. Planted `DOMVEC_PLANT_WATCH_LAUNCHER=1`: the launcher
    alone, as before.
    """

    def __init__(self, ps):
        self.ps = ps

    def _all(self):
        if os.environ.get("DOMVEC_PLANT_WATCH_LAUNCHER") == "1":
            return [self.ps]
        try:
            return [self.ps] + self.ps.children(recursive=True)
        except Exception:                           # noqa: BLE001
            return [self.ps]

    def cpu_times(self):
        user = system = 0.0
        for p in self._all():
            try:
                t = p.cpu_times(); user += t.user; system += t.system
            except Exception:                       # noqa: BLE001
                continue
        return type("T", (), {"user": user, "system": system})()

    def memory_info(self):
        rss = 0
        for p in self._all():
            try:
                rss += p.memory_info().rss
            except Exception:                       # noqa: BLE001
                continue
        return type("M", (), {"rss": rss})()


def _kill(proc, ps) -> None:
    """The child's whole tree, children first: killing a venv launcher alone
    left the real interpreter running, holding the port and the store."""
    if ps is not None and os.environ.get("DOMVEC_PLANT_WATCH_LAUNCHER") != "1":
        try:
            for c in ps.ps.children(recursive=True):
                try:
                    c.kill()
                except Exception:                   # noqa: BLE001
                    pass
        except Exception:                           # noqa: BLE001
            pass
    proc.kill()


def _run_child(command: List[str], env: dict, port: Optional[int], *,
               capture: bool = False, timeout: Optional[float] = None,
               fatal_log: Optional[Path] = None):
    """The child, run to its exit -- or killed as a STALLED start (early: no
    CPU to speak of after `EARLY_S`; late: no /health in `START_DEADLINE_S`
    and no CPU for `START_STALL_S`). With `capture`, (code, stdout)."""
    # **stdin is NUL, never inherited.** The cause of every start that hung
    # (2026-10-23..25): a supervisor launched by the MCP server inherited
    # that server's stdin -- a pipe it is always blocked READING, waiting
    # for the next request -- and passed it to each child. On Windows a
    # synchronous query on a pipe waits behind a pending read on it, so a
    # child's interpreter startup (its check of the standard handles) sat in
    # a kernel wait until the next MCP message arrived: 13 MB, one thread,
    # no CPU. The first child started only because the server was busy
    # answering `sidecar_start` at that moment. Reproduced in isolation
    # (a blocked reader on the pipe: HUNG > 15 s; DEVNULL: 0.08 s).
    # Planted: `DOMVEC_PLANT_INHERIT_STDIN=1`.
    stdin = None if os.environ.get("DOMVEC_PLANT_INHERIT_STDIN") == "1" else subprocess.DEVNULL
    # Windowless (`procs.hidden`): the plugin starts this supervisor DETACHED
    # (no console), and a console child of a console-less parent is given a
    # new VISIBLE window -- one per worker start (PLUGIN_GOAL 157).
    from ..procs import hidden
    proc = subprocess.Popen(command, **hidden(env=env, stdin=stdin,
                            stdout=subprocess.PIPE if capture else None, text=capture))
    started = time.time()
    planted = os.environ.get("DOMVEC_PLANT_NO_START_DEADLINE") == "1"
    healthy = port is None or planted
    early_done = planted
    try:
        import psutil
        ps = _Tree(psutil.Process(proc.pid))
    except Exception:                               # noqa: BLE001
        ps = None
    last_cpu, last_move = None, time.time()
    fatal = _FatalWatch(None if os.environ.get("DOMVEC_PLANT_NO_FATAL_WATCH") == "1" else fatal_log)
    WORKER.update(pid=proc.pid, fatal_at=None, unkillable_at=None)
    dead_cpu = None

    def done(code):
        return (code, proc.stdout.read() if capture and proc.stdout else "") if capture else code

    while True:
        try:
            code = proc.wait(timeout=2.0)
            return done(code)
        except subprocess.TimeoutExpired:
            pass
        if timeout and time.time() - started > timeout:
            _kill(proc, ps); proc.wait()
            return done(STUCK_CODE)
        if not early_done and time.time() - started > EARLY_S:
            early_done = True
            try:
                t = ps.cpu_times() if ps is not None else None
                rss = ps.memory_info().rss / 1e6 if ps is not None else 0.0
                small = rss < EARLY_RSS_MB or os.environ.get("DOMVEC_PLANT_EARLY_CPU_ONLY") == "1"
                if t is not None and (t.user + t.system) < EARLY_CPU_S and small:
                    _kill(proc, ps); proc.wait()
                    return done(STUCK_CODE)
            except Exception:                       # noqa: BLE001
                pass
        if healthy:
            seen = fatal.poll()
            if seen is None:
                continue
            try:
                t = ps.cpu_times() if ps is not None else None
                cpu = (t.user + t.system) if t is not None else None
            except Exception:                       # noqa: BLE001
                cpu = None
            if dead_cpu is None or cpu is None or cpu - dead_cpu[0] > 0.5:
                dead_cpu = (cpu if cpu is not None else 0.0, time.time())
            WORKER["fatal_at"] = seen
            if time.time() - seen > FATAL_GRACE_S and time.time() - dead_cpu[1] > FATAL_GRACE_S and not _healthy(port):
                _kill(proc, ps)
                try:
                    proc.wait(timeout=KILL_WAIT_S)
                except subprocess.TimeoutExpired:
                    WORKER["unkillable_at"] = time.time()
                return done(HUNG_CODE)
            continue
        if _healthy(port):
            healthy = True
            continue
        try:
            t = ps.cpu_times() if ps is not None else None
            cpu = (t.user + t.system) if t is not None else None
        except Exception:                           # noqa: BLE001
            cpu = None
        if cpu is None or last_cpu is None or cpu - last_cpu > 0.5:
            last_cpu, last_move = cpu, time.time()
        now = time.time()
        if now - started > START_DEADLINE_S and now - last_move > START_STALL_S:
            _kill(proc, ps)
            proc.wait()
            return done(STUCK_CODE)

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


def _compact_in_child(workspace: Path) -> dict:
    """`compact` run as its own process; its JSON result. Watched like a
    sidecar start: a child stalled at its start is killed and tried once more,
    and then the compaction is skipped -- the sidecar starts either way."""
    for attempt in (1, 2):
        code, out = _run_child([sys.executable, "-m", "domvec.obsidian.compact", str(workspace)],
                               dict(os.environ), None, capture=True, timeout=3600)
        if code == STUCK_CODE:
            continue
        lines = [ln for ln in (out or "").splitlines() if ln.strip().startswith("{")]
        return json.loads(lines[-1]) if lines else {"error": "compaction exited %s" % code}
    return {"error": "compaction child stalled at its start twice; skipped"}


def _compact_logged(workspace: Path, why: str) -> dict:
    """Compact the store (nothing has it open) and say so in both logs.

    In its OWN process, never in this one (2026-10-24): compacted in-process,
    the supervisor held kuzu afterwards, and every child it started next hung
    at interpreter startup -- 13 MB, one thread, inside the Store Python's
    package lookup (`windows.staterepositorycore.dll`), 0.02 s of CPU --
    four in a row at 22:43 and 23:23, while a Python started anywhere else
    came up in 0.1 s. Planted `DOMVEC_PLANT_COMPACT_IN_PROCESS=1`.
    """
    try:
        if os.environ.get("DOMVEC_PLANT_COMPACT_IN_PROCESS") == "1":
            from .compact import compact
            got = compact(workspace)
        else:
            got = _compact_in_child(workspace)
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
    # THE FRONT (PLUGIN_GOAL 148, step 1 of the split): this process -- the
    # one that outlives every crash -- owns the public port and always
    # answers; the worker serves on an internal one. Planted
    # DOMVEC_NO_FRONT=1: the worker on the public port, as before.
    public = _port_of(serve_args)
    if public and command is None and os.environ.get("DOMVEC_NO_FRONT") != "1":
        from .front import BACKEND_OFFSET, start_front, supervisor_launch
        backend = public + BACKEND_OFFSET
        serve_args = list(serve_args)
        serve_args[serve_args.index("--port") + 1] = str(backend)
        try:
            start_front(public, backend, supervisor_launch(str(workspace)))
            print("front on %d -> worker on %d" % (public, backend), flush=True)
        except OSError as exc:                      # the port is taken: run as before
            print("front not started (%s); worker on %d" % (exc, public), flush=True)
            serve_args[serve_args.index("--port") + 1] = str(public)
    command = command or [sys.executable, "-X", "faulthandler", "-m",
                          "domvec.obsidian", "serve", "--workspace",
                          str(workspace), *serve_args]
    crashes: List[float] = []
    stalls_in_a_row = 0
    compacted_this_burst = False
    log = workspace / "crashes.log"
    while True:
        started = time.time()
        # The child knows a supervisor will act on COMPACT_CODE.
        code = _run_child(command, {**os.environ, "DOMVEC_SUPERVISED": "1"}, _port_of(serve_args),
                          fatal_log=workspace / "sidecar.err.log")
        if code == 0:
            return 0                           # a clean stop is not a crash
        if code == RESTART_CODE:
            continue                           # asked for (POST /shutdown): not a crash
        if code == COMPACT_CODE:               # asked for: outgrown, or its pool refused
            _compact_logged(workspace, "asked")
            continue
        now = time.time()
        stalls_in_a_row = stalls_in_a_row + 1 if code == STUCK_CODE else 0
        if stalls_in_a_row >= GIVE_UP_STALLS:
            note = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "stalls": stalls_in_a_row,
                    "why": "every start of this supervisor stalled at the interpreter; a fresh one is wanted"}
            try:
                (workspace / "supervisor_gave_up.json").write_text(json.dumps(note), encoding="utf-8")
                with log.open("a", encoding="utf-8") as fh:
                    fh.write("%s supervisor gave up after %d stalled starts in a row" % (note["at"], stalls_in_a_row) + chr(10))
            except OSError:
                pass
            print("supervisor gave up after %d stalled starts" % stalls_in_a_row, flush=True)
            return STUCK_CODE
        if code == HUNG_CODE:
            note = "%s died without exiting: a fatal dump in sidecar.err.log, then no /health and no CPU for %.0f s -- killed, starting again" % (
                time.strftime("%Y-%m-%d %H:%M:%S"), FATAL_GRACE_S) + chr(10)
            if WORKER.get("unkillable_at"):
                note = note.strip() + ("; pid %s did NOT end within %.0f s of the kill -- the kernel is holding it (a driver), "
                                       "and its port may stay bound until Windows is restarted" % (WORKER.get("pid"), KILL_WAIT_S)) + chr(10)
            try:
                with log.open("a", encoding="utf-8") as fh:
                    fh.write(note)
            except OSError:
                pass
            print(note.strip(), flush=True)
        if code == STUCK_CODE:
            note = "%s start stalled: no /health in %.0f s, no CPU for %.0f s -- killed, starting again" % (
                time.strftime("%Y-%m-%d %H:%M:%S"), now - started, START_STALL_S) + chr(10)
            try:
                with log.open("a", encoding="utf-8") as fh:
                    fh.write(note)
            except OSError:
                pass
            print(note.strip(), flush=True)
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
        # which loses what the WAL held. Planted `DOMVEC_PLANT_NO_CRASH_COMPACT`.
        if len(crashes) >= 2 and not compacted_this_burst and os.environ.get("DOMVEC_PLANT_NO_CRASH_COMPACT") != "1":
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
