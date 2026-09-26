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
