"""The supervisor restarts a crashed sidecar, records why, and knows when to stop.

Planted: the child is a process that exits the way the D-23 segfault does
(139), and the breadcrumb names a statement. Without the supervisor a crash
ended the sidecar; with it, each crash is one line in crashes.log naming that
statement, and a burst stops the loop rather than hiding a process that cannot
stay up.
"""

import sys
import time

from domvec.obsidian.supervise import BURST, supervise

CRASH = [sys.executable, "-c", "import os; os._exit(139)"]
CLEAN = [sys.executable, "-c", "raise SystemExit(0)"]


def test_a_crashing_child_is_restarted_logged_and_stopped_after_a_burst(tmp_path):
    (tmp_path / "last_statement.txt").write_text(
        "1.0 n=64 UNWIND $rows AS r MATCH (p:Page {url: r.url}) ...",
        encoding="utf-8")
    code = supervise(tmp_path, [], command=CRASH, pause=0.0)
    assert code == 139
    all_lines = (tmp_path / "crashes.log").read_text(encoding="utf-8").splitlines()
    lines = [l for l in all_lines if "exit=" in l]
    assert len(lines) == BURST, "restarted %d times, not %d" % (len(lines), BURST)
    assert all("exit=139" in l and "UNWIND $rows" in l for l in lines)
    # The second crash tried ONE compaction first (here there is no store,
    # so it failed and the loop went on to the burst limit).
    tried = [l for l in all_lines if "compacted (two crashes in a minute)" in l]
    assert len(tried) == 1 and '"error"' in tried[0]


def test_a_clean_stop_is_not_a_crash(tmp_path):
    assert supervise(tmp_path, [], command=CLEAN, pause=0.0) == 0
    assert not (tmp_path / "crashes.log").exists()


def _fails_while_wal(ws):
    """A child that cannot open the store while a write-ahead log is present."""
    import sys
    return [sys.executable, "-c",
            "import os,sys; sys.exit(1 if os.path.exists(%r) else 0)"
            % str(ws / "graph.kuzu.wal")]


def test_an_unreplayable_wal_is_set_aside_and_the_store_opens(tmp_path):
    (tmp_path / "graph.kuzu.wal").write_bytes(b"not replayable")
    code = supervise(tmp_path, [], command=_fails_while_wal(tmp_path), pause=0.0)
    assert code == 0
    assert not (tmp_path / "graph.kuzu.wal").exists()
    aside = list(tmp_path.glob("graph.kuzu.wal.unreplayable-*"))
    assert len(aside) == 1 and aside[0].read_bytes() == b"not replayable"
    assert "set aside" in (tmp_path / "crashes.log").read_text(encoding="utf-8")


def test_planted_no_quarantine_gives_up(tmp_path, monkeypatch):
    """Non-vacuity: without the quarantine the same child never starts."""
    import domvec.obsidian.supervise as sv
    monkeypatch.setattr(sv, "quarantine_wal", lambda ws: None)
    (tmp_path / "graph.kuzu.wal").write_bytes(b"not replayable")
    code = sv.supervise(tmp_path, [], command=_fails_while_wal(tmp_path), pause=0.0)
    assert code != 0
    assert (tmp_path / "graph.kuzu.wal").exists()


def test_two_crashes_compact_and_the_store_starts(tmp_path, monkeypatch):
    """2026-10-18: every start died at CHECKPOINT on a WAL its pool could not
    hold; compacted (with a larger pool) it opened. The child here starts only
    once the store was compacted."""
    import json
    import domvec.obsidian.supervise as sv
    done = tmp_path / "compacted.json"
    # Compaction runs in its own process (`_compact_in_child`); replaced here.
    monkeypatch.setattr(sv, "_compact_in_child",
                        lambda ws, **k: (done.write_text(json.dumps({"after_mb": 1})), {"swapped": True, "before_mb": 5, "after_mb": 1})[1])
    child = [sys.executable, "-c", "import os,sys; sys.exit(0 if os.path.exists(%r) else 139)" % str(done)]
    assert sv.supervise(tmp_path, [], command=child, pause=0.0) == 0
    log = (tmp_path / "crashes.log").read_text(encoding="utf-8")
    assert log.count("exit=139") == 2 and "compacted (two crashes in a minute)" in log


def test_planted_no_crash_compact_gives_up(tmp_path, monkeypatch):
    import domvec.obsidian.supervise as sv
    monkeypatch.setenv("DOMVEC_PLANT_NO_CRASH_COMPACT", "1")
    called = []
    monkeypatch.setattr("domvec.obsidian.compact.compact", lambda ws, **k: called.append(1) or {"swapped": True})
    child = [sys.executable, "-c", "import sys; sys.exit(139)"]
    assert sv.supervise(tmp_path, [], command=child, pause=0.0) == 139
    assert called == []


# A child that never answers /health and spends no CPU: a STALLED start
# (2026-10-24, a child after a compaction hung 10 min in the native preload).
SLEEPER = [sys.executable, "-c", "import time; time.sleep(60)"]


def test_a_stalled_start_is_killed_and_logged(tmp_path, monkeypatch):
    import domvec.obsidian.supervise as sv
    monkeypatch.setattr(sv, "START_DEADLINE_S", 1.0)
    monkeypatch.setattr(sv, "START_STALL_S", 1.0)
    monkeypatch.setattr(sv, "BURST", 2)
    t0 = time.time()
    code = sv.supervise(tmp_path, ["--port", "1"], command=SLEEPER, pause=0.0)
    assert code == sv.STUCK_CODE
    assert time.time() - t0 < 30                     # killed, not waited out
    assert "start stalled" in (tmp_path / "crashes.log").read_text(encoding="utf-8")


def test_planted_no_deadline_leaves_it_running(tmp_path, monkeypatch):
    import domvec.obsidian.supervise as sv
    monkeypatch.setattr(sv, "START_DEADLINE_S", 1.0)
    monkeypatch.setattr(sv, "START_STALL_S", 1.0)
    monkeypatch.setenv("DOMVEC_PLANT_NO_START_DEADLINE", "1")
    short = [sys.executable, "-c", "import time; time.sleep(4)"]
    t0 = time.time()
    assert sv.supervise(tmp_path, ["--port", "1"], command=short, pause=0.0) == 0
    assert time.time() - t0 >= 4


def test_an_early_stall_is_killed_before_the_deadline(tmp_path, monkeypatch):
    """A child with almost no CPU after EARLY_S never got past its start
    (2026-10-25: 13 MB, 0.02 s CPU, every time) -- killed then, not at the
    four-minute deadline."""
    import domvec.obsidian.supervise as sv
    monkeypatch.setattr(sv, "EARLY_S", 2.0)
    monkeypatch.setattr(sv, "START_DEADLINE_S", 600.0)
    monkeypatch.setattr(sv, "BURST", 2)
    t0 = time.time()
    code = sv.supervise(tmp_path, ["--port", "1"], command=SLEEPER, pause=0.0)
    assert code == sv.STUCK_CODE and time.time() - t0 < 20


# A child that has LOADED something (200 MB resident) and then waits, as a
# fresh venv's worker waits on Defender scanning its DLLs.
LOADED_WAITER = [sys.executable, "-c", "import time; b = b'x' * 200_000_000; time.sleep(60)"]


def test_a_large_waiting_child_is_not_an_early_stall(tmp_path, monkeypatch):
    """2026-11-15, the README proof: a new user's first start was killed as an
    early stall three times. Large and waiting is loading, not hung."""
    import domvec.obsidian.supervise as sv
    monkeypatch.setattr(sv, "EARLY_S", 2.0)
    monkeypatch.setattr(sv, "START_DEADLINE_S", 600.0)
    t0 = time.time()
    code = sv._run_child(LOADED_WAITER, None, 1, timeout=8.0)
    code = code[0] if isinstance(code, tuple) else code
    assert code == sv.STUCK_CODE and time.time() - t0 >= 7.5      # left to the timeout, not killed at 2 s


def test_planted_cpu_only_kills_the_large_waiting_child(tmp_path, monkeypatch):
    import domvec.obsidian.supervise as sv
    monkeypatch.setattr(sv, "EARLY_S", 2.0)
    monkeypatch.setattr(sv, "START_DEADLINE_S", 600.0)
    monkeypatch.setenv("DOMVEC_PLANT_EARLY_CPU_ONLY", "1")
    t0 = time.time()
    code = sv._run_child(LOADED_WAITER, None, 1, timeout=30.0)
    code = code[0] if isinstance(code, tuple) else code
    assert code == sv.STUCK_CODE and time.time() - t0 < 7.0


# A venv launcher: the process the supervisor starts sits idle while ITS child
# (the real interpreter) works -- here, 5 s of CPU, then both exit 0.
LAUNCHER = [sys.executable, "-c", "import subprocess, sys; sys.exit(subprocess.run([sys.executable, '-c', "
            "'import time; t = time.time(); [sum(range(10000)) for _ in iter(lambda: time.time() - t < 5, False)]']).returncode)"]


def test_a_launchers_busy_child_is_not_an_early_stall(tmp_path, monkeypatch):
    """2026-11-15, the README proof: the supervisor watched the venv's launcher
    (11.7 MB, 0.02 s CPU) while the real worker stood at 525 MB and 21 s of
    CPU, and killed it as an early stall. The tree is what counts."""
    import domvec.obsidian.supervise as sv
    monkeypatch.setattr(sv, "EARLY_S", 2.0)
    monkeypatch.setattr(sv, "START_DEADLINE_S", 600.0)
    code = sv._run_child(LAUNCHER, None, 1, timeout=30.0)
    assert (code[0] if isinstance(code, tuple) else code) == 0


def test_planted_watching_the_launcher_kills_the_busy_child(tmp_path, monkeypatch):
    import domvec.obsidian.supervise as sv
    monkeypatch.setattr(sv, "EARLY_S", 2.0)
    monkeypatch.setattr(sv, "START_DEADLINE_S", 600.0)
    monkeypatch.setenv("DOMVEC_PLANT_WATCH_LAUNCHER", "1")
    monkeypatch.setattr(sv, "EARLY_RSS_MB", 10_000.0)      # the size rule is not this test's
    t0 = time.time()
    code = sv._run_child(LAUNCHER, None, 1, timeout=30.0)
    assert (code[0] if isinstance(code, tuple) else code) == sv.STUCK_CODE and time.time() - t0 < 5


def test_a_stalled_compaction_child_is_skipped_not_waited(tmp_path, monkeypatch):
    import domvec.obsidian.supervise as sv
    monkeypatch.setattr(sv, "EARLY_S", 2.0)
    monkeypatch.setattr(sv.sys, "executable", sys.executable)
    real = sv._run_child
    monkeypatch.setattr(sv, "_run_child", lambda cmd, env, port, **k: real(SLEEPER, env, port, **k))
    t0 = time.time()
    got = sv._compact_in_child(tmp_path)
    assert "stalled" in got.get("error", "") and time.time() - t0 < 30


def test_three_stalls_in_a_row_give_up_with_a_marker(tmp_path, monkeypatch):
    """Once one start hangs, later children of the same supervisor hung too;
    after GIVE_UP_STALLS it leaves `supervisor_gave_up.json` and exits, for
    the plugin to start a fresh one."""
    import json as _json
    import domvec.obsidian.supervise as sv
    monkeypatch.setattr(sv, "EARLY_S", 1.0)
    monkeypatch.setattr(sv, "BURST", 99)
    code = sv.supervise(tmp_path, ["--port", "1"], command=SLEEPER, pause=0.0)
    assert code == sv.STUCK_CODE
    got = _json.loads((tmp_path / "supervisor_gave_up.json").read_text(encoding="utf-8"))
    assert got["stalls"] == sv.GIVE_UP_STALLS
    assert "gave up" in (tmp_path / "crashes.log").read_text(encoding="utf-8")


def test_a_child_starts_while_the_parents_stdin_pipe_is_being_read(monkeypatch):
    """The stall's cause (2026-10-25): the MCP server is always blocked
    reading its stdin pipe, and a supervisor it launched handed that pipe to
    every child -- whose interpreter startup then waited behind the read.
    Reproduced here: fd 0 replaced by a pipe a thread is blocked reading.
    Clean, the child gets NUL and starts; planted, it inherits and hangs."""
    import os
    import threading
    import pytest
    from domvec.obsidian import supervise as sv
    if sys.platform != "win32":
        pytest.skip("the pipe wait is Windows' synchronous I/O")
    r, w = os.pipe()
    saved = os.dup(0)
    os.dup2(r, 0)
    threading.Thread(target=lambda: os.read(0, 1), daemon=True).start()
    try:
        time.sleep(0.3)
        cmd = [sys.executable, "-c", "print(1)"]
        t = time.time()
        assert sv._run_child(cmd, dict(os.environ), None, timeout=10) == 0
        assert time.time() - t < 8
        monkeypatch.setenv("DOMVEC_PLANT_INHERIT_STDIN", "1")
        assert sv._run_child(cmd, dict(os.environ), None, timeout=6) == sv.STUCK_CODE
    finally:
        os.write(w, b"x")
        os.dup2(saved, 0)
        os.close(saved); os.close(r); os.close(w)


# A child that answers /health, then writes a fatal dump to the err log and
# HANGS without exiting -- 2026-11-14 19:55, two chat turns on one gpt4all
# model: "Windows fatal exception: access violation", then nine minutes in
# teardown, one thread, no CPU, no answer, nothing restarted it.
def _dies_without_exiting(port, err, *, busy=False):
    body = (
        "import http.server, threading, time, sys\n"
        "class H(http.server.BaseHTTPRequestHandler):\n"
        "    def do_GET(self): self.send_response(200); self.end_headers(); self.wfile.write(b'ok')\n"
        "    def log_message(self, *a): pass\n"
        "srv = http.server.ThreadingHTTPServer(('127.0.0.1', %d), H)\n"
        "threading.Thread(target=srv.serve_forever, daemon=True).start()\n"
        "time.sleep(3)\n"
        "open(%r, 'a').write('Windows fatal exception: access violation. Current thread 0x1 (most recent call first)')\n"
        "%s\n"
        "t = time.time()\n"
        "while time.time() - t < 40:\n"
        "    %s\n"
    ) % (port, str(err), "pass" if busy else "srv.shutdown(); srv.server_close()",
         "sum(range(20000))" if busy else "time.sleep(0.5)")
    return [sys.executable, "-c", body]


def _free_port():
    import socket
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close()
    return p


def test_a_worker_that_died_without_exiting_is_killed_and_logged(tmp_path, monkeypatch):
    import domvec.obsidian.supervise as sv
    monkeypatch.setattr(sv, "FATAL_GRACE_S", 3.0)
    monkeypatch.setattr(sv, "BURST", 1)
    port = _free_port()
    t0 = time.time()
    code = sv.supervise(tmp_path, ["--port", str(port)],
                        command=_dies_without_exiting(port, tmp_path / "sidecar.err.log"), pause=0.0)
    assert code == sv.HUNG_CODE
    assert time.time() - t0 < 25                     # killed, not waited out (40 s)
    assert "died without exiting" in (tmp_path / "crashes.log").read_text(encoding="utf-8")
    assert sv.WORKER["fatal_at"] is not None and sv.WORKER["unkillable_at"] is None


def test_planted_no_fatal_watch_waits_the_hang_out(tmp_path, monkeypatch):
    """Non-vacuity: without the watch the same child runs its full 40 s."""
    import domvec.obsidian.supervise as sv
    monkeypatch.setattr(sv, "FATAL_GRACE_S", 3.0)
    monkeypatch.setenv("DOMVEC_PLANT_NO_FATAL_WATCH", "1")
    monkeypatch.setattr(sv, "EARLY_S", 600.0)        # the early-stall rule is another watch
    port = _free_port()
    t0 = time.time()
    code = sv.supervise(tmp_path, ["--port", str(port)],
                        command=_dies_without_exiting(port, tmp_path / "sidecar.err.log"), pause=0.0)
    assert code == 0 and time.time() - t0 >= 40


def test_a_fatal_mark_from_a_worker_that_still_answers_is_left_alone(tmp_path, monkeypatch):
    """A handled exception faulthandler reported anyway: the worker still
    answers /health and spends CPU, so it is NOT killed (a busy worker read as
    dead is the opposite defect, and the one this harness has made before)."""
    import domvec.obsidian.supervise as sv
    monkeypatch.setattr(sv, "FATAL_GRACE_S", 3.0)
    port = _free_port()
    t0 = time.time()
    code = sv.supervise(tmp_path, ["--port", str(port)],
                        command=_dies_without_exiting(port, tmp_path / "sidecar.err.log", busy=True), pause=0.0)
    assert code == 0 and time.time() - t0 >= 40


def test_the_front_reports_a_worker_that_died_as_dead_not_busy(monkeypatch):
    """2026-11-14: the front answered `ok: true, backend: busy` for twenty
    minutes over a worker that had crashed and could not exit. Once the
    supervisor has seen the fatal dump and the worker has not answered since,
    the front says `dead`; planted (`DOMVEC_PLANT_NO_FATAL_WATCH=1`) it says
    busy, as before. A worker that answered AFTER the mark stays up."""
    import domvec.obsidian.supervise as sv
    from domvec.obsidian.front import _State, health_body
    st = _State(1, {})
    st.health, st.health_at, st.backend = {"ok": True, "pages": 3}, time.time() - 1200, "busy"
    monkeypatch.setitem(sv.WORKER, "fatal_at", time.time() - 1100)
    monkeypatch.setitem(sv.WORKER, "unkillable_at", time.time() - 1000)
    dead = health_body(st)
    assert dead["backend"] == "dead" and dead["ok"] is False and dead["worker"]["unkillable"] is True
    monkeypatch.setenv("DOMVEC_PLANT_NO_FATAL_WATCH", "1")
    assert health_body(st)["backend"] == "busy"
    monkeypatch.delenv("DOMVEC_PLANT_NO_FATAL_WATCH")
    st.health_at, st.backend = time.time(), "up"            # it answered since: a handled exception
    assert health_body(st)["backend"] == "up"


def test_compacting_a_store_that_was_never_created_says_so(tmp_path):
    """A first start that died before opening the store left compaction to
    crash on FileNotFoundError, read as a second failure (2026-11-15)."""
    from domvec.obsidian.compact import compact
    got = compact(tmp_path)
    assert got["swapped"] is False and "no store" in got["why_not"]
