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
