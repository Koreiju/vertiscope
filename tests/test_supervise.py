"""The supervisor restarts a crashed sidecar, records why, and knows when to stop.

Planted: the child is a process that exits the way the D-23 segfault does
(139), and the breadcrumb names a statement. Without the supervisor a crash
ended the sidecar; with it, each crash is one line in crashes.log naming that
statement, and a burst stops the loop rather than hiding a process that cannot
stay up.
"""

import sys

from domvec.obsidian.supervise import BURST, supervise

CRASH = [sys.executable, "-c", "import os; os._exit(139)"]
CLEAN = [sys.executable, "-c", "raise SystemExit(0)"]


def test_a_crashing_child_is_restarted_logged_and_stopped_after_a_burst(tmp_path):
    (tmp_path / "last_statement.txt").write_text(
        "1.0 n=64 UNWIND $rows AS r MATCH (p:Page {url: r.url}) ...",
        encoding="utf-8")
    code = supervise(tmp_path, [], command=CRASH, pause=0.0)
    assert code == 139
    lines = (tmp_path / "crashes.log").read_text(encoding="utf-8").splitlines()
    assert len(lines) == BURST, "restarted %d times, not %d" % (len(lines), BURST)
    assert all("exit=139" in l and "UNWIND $rows" in l for l in lines)


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
