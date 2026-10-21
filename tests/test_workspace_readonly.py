"""Two servers, one workspace.

The sidecar and the MCP server are both read-only *in intent* -- the sidecar's
module docstring says no route mutates anything, the MCP's says read-only "on
purpose" -- and both opened the store read-WRITE. Kuzu admits many readers or
one writer, so whichever started first locked the other out of its own
workspace, and the MCP server could not be connected at all while the vault
was being served.

The fix is to ask for the weaker mode. What these tests guard is that asking
for it is not cosmetic: a reader really does share, a writer really is still
excluded, and a read-only open of a path that is not there fails instead of
quietly creating an empty corpus that answers every query with nothing.
"""

from __future__ import annotations

import subprocess
import sys
import time

import pytest

from vertiscope.workspace import Workspace


def _holder(path, read_only: bool):
    """Open `path` in another PROCESS and keep it open.

    Another process and not another thread, because the lock being tested is
    an OS lock on the store directory. Two opens inside one interpreter can
    share a handle and would report success for the wrong reason.
    """
    flag = "True" if read_only else "False"
    proc = subprocess.Popen(
        [sys.executable, "-c",
         "from vertiscope.workspace import Workspace; import time, sys;"
         f"ws = Workspace(r'{path}', read_only={flag});"
         "print('held', flush=True);"
         "time.sleep(30)"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    # Wait for the child to say it has the lock rather than sleeping a guess:
    # a fixed sleep either flakes on a slow machine or wastes time on a fast
    # one, and both failures look like the lock behaving differently.
    deadline = time.time() + 60
    while time.time() < deadline:
        line = proc.stdout.readline()
        if line.startswith("held"):
            return proc
        if proc.poll() is not None:
            proc.wait()
            pytest.fail("holder process died: %s" % line)
    proc.kill()
    pytest.fail("holder never reported holding the store")


@pytest.fixture
def store(tmp_path):
    """A real workspace on disk, written once and then closed.

    Built through the CLI's `index` rather than by reaching into `ingest`,
    because the lock is a property of the store a normal run produces, and a
    hand-assembled one could differ from it in exactly the way that matters.
    """
    from pathlib import Path

    from vertiscope.cli import main

    fixture = Path(__file__).parent / "fixtures" / "catalog.html"
    path = tmp_path / "ws"
    assert main(["index", str(fixture), "-w", str(path)]) == 0
    with Workspace(path) as ws:
        assert ws.stats()["chunks"] > 0, "fixture workspace came out empty"
    return path


def test_two_readers_share_one_store(store):
    """The whole point: the sidecar and the MCP server, at the same time."""
    holder = _holder(store, read_only=True)
    try:
        with Workspace(store, read_only=True) as second:
            assert second.pages(), "the second reader must see the corpus"
    finally:
        holder.kill()


def test_a_writer_is_still_excluded(store):
    """Non-vacuity: prove the planted defect is caught.

    Without this, `read_only=True` could be ignored entirely -- passed to a
    kuzu that never looked at it, or dropped on the way through Workspace --
    and `test_two_readers_share_one_store` would still pass, because two
    read-WRITE opens of an unlocked store in sequence also succeed. The claim
    is that the MODE is doing the work, and the only way to show that is that
    the strong mode still conflicts.
    """
    holder = _holder(store, read_only=True)
    try:
        with pytest.raises(RuntimeError, match="held by another process"):
            Workspace(store, read_only=False)
    finally:
        holder.kill()


def test_a_writer_excludes_readers_too(store):
    """Kuzu is many-readers OR one-writer, not many-readers AND one-writer.

    Worth its own test because the tempting mental model -- "read-only always
    gets in" -- is wrong, and a sidecar started with --enact is a writer. A
    caller that believes otherwise will read the resulting lock error as a
    corrupt store rather than as a scan running somewhere.
    """
    holder = _holder(store, read_only=False)
    try:
        with pytest.raises(RuntimeError, match="held by another process"):
            Workspace(store, read_only=True)
    finally:
        holder.kill()


def test_read_only_refuses_to_create_a_workspace(tmp_path):
    """An empty corpus answers every query with nothing.

    That reads as "the pages are gone", which sends the reader looking for a
    data-loss bug, when the truth is a mistyped path. Fail where the mistake
    was made.
    """
    missing = tmp_path / "no-such-workspace"
    with pytest.raises(FileNotFoundError):
        Workspace(missing, read_only=True)
    assert not missing.exists(), "a read-only open must leave the disk alone"


def test_read_only_does_not_run_the_name_migration(store, monkeypatch):
    """`_retire_readable_names` renames files, and the exclusive lock was the
    proof that made renaming safe.

    A read-only open shares the store with other readers and possibly a
    writer, so that proof is gone. The migration is idempotent and the next
    writable open runs it, so skipping costs nothing.
    """
    called = []
    monkeypatch.setattr(Workspace, "_retire_readable_names",
                        lambda self: called.append(True))

    with Workspace(store, read_only=True):
        pass
    assert called == [], "read-only must not rename anything"

    with Workspace(store, read_only=False):
        pass
    assert called == [True], "a writable open must still migrate"
