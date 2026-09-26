"""The fresh-store harness tears down only what it made, and stops all of it.

Two ways it could go wrong that a live run would not show:

* **Tearing down too much.** `fresh_workspace` deletes the previous test
  store. A glob one level too wide deletes the working corpus beside it.
* **Stopping too little.** `supervise` runs `serve` as a CHILD process.
  Terminating the parent alone leaves the child holding the store and the
  port, so the next run cannot start and the "fresh" store is not fresh.
  The planted arm shows that a plain terminate really does leave it running,
  so the tree kill is doing something.
"""

import os
import subprocess
import sys
import time

import pytest

from domvec.obsidian import freshrun


def test_fresh_workspace_is_empty_and_spares_everything_else(tmp_path, monkeypatch):
    runs = tmp_path / "test_runs"
    monkeypatch.setattr(freshrun, "RUNS", runs)
    old = runs / "run_20260101_000000"
    old.mkdir(parents=True)
    (old / "store.kuzu").write_text("previous test store")
    keep = runs / "notes.txt"                 # in RUNS, but not a run
    keep.write_text("keep")
    corpus = tmp_path / "corpus123"           # beside RUNS: the real store
    corpus.mkdir()
    (corpus / "store.kuzu").write_text("working corpus")

    ws = freshrun.fresh_workspace()

    assert ws.is_dir() and list(ws.iterdir()) == []
    assert not old.exists()
    assert keep.read_text() == "keep"
    assert (corpus / "store.kuzu").read_text() == "working corpus"


def _alive(pid: int) -> bool:
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", "PID eq %d" % pid, "/NH"],
                             capture_output=True, text=True).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _parent_with_child(tmp_path):
    """A parent process that starts a long-lived child, as `supervise` does."""
    pidfile = tmp_path / "child.pid"
    code = ("import subprocess,sys,time;"
            "c=subprocess.Popen([sys.executable,'-c','import time;time.sleep(120)']);"
            "open(%r,'w').write(str(c.pid));time.sleep(120)" % str(pidfile))
    parent = subprocess.Popen([sys.executable, "-c", code])
    for _ in range(100):
        if pidfile.exists() and pidfile.read_text():
            return parent, int(pidfile.read_text())
        time.sleep(0.1)
    parent.kill()
    pytest.fail("the child never started")


def test_kill_tree_stops_the_child_too(tmp_path):
    parent, child = _parent_with_child(tmp_path)
    freshrun._kill_tree(parent)
    time.sleep(0.5)
    assert parent.poll() is not None
    assert not _alive(child)


@pytest.mark.skipif(os.name != "nt", reason="POSIX terminate is per-process too, "
                    "but the planted arm is measured where the sidecar runs")
def test_planted_plain_terminate_leaves_the_child(tmp_path):
    """Non-vacuity: the defect the tree kill exists for is real."""
    parent, child = _parent_with_child(tmp_path)
    parent.terminate()
    parent.wait(timeout=10)
    time.sleep(0.5)
    try:
        assert _alive(child)
    finally:
        subprocess.call(["taskkill", "/PID", str(child), "/F"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
