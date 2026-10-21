"""Every stored chunk must be REACHABLE, and a reader must not write.

Two defects found the same afternoon, on one page.

Scoping a query to RFC 9110 answered **0 hits for every query** while the
page is the largest in the corpus. It was not the scope filter: 7,955 of
14,129 chunks -- 56.3% -- had an embedding and no frequency row, and
retrieval is a strict triple product, so a zero on the lexical factor is a
veto. Twenty-eight of ninety-six pages could not be returned by any query at
all, scoped or global, and nothing said so: every hit that DID come back
carried all three factors, because only chunks that can be returned ever do.

And `Workspace.close()` saved `freq.npz` with no read-only guard, so every
reader rewrote it on exit -- the sidecar, an MCP server, a diagnostic
script. That is how the file came to be dated today on a store last written
six days earlier.
"""

import json
import pathlib
import shutil
import tempfile

import pytest

from vertiscope.workspace import Workspace

# Long enough to chunk APART. Two short paragraphs come back as ONE chunk --
# correctly, they fit the window -- and then there is nothing to plant a gap
# in half of.
PAGE = ("<html><body>"
        "<div><p>" + ("alpha beta gamma delta epsilon zeta eta theta " * 40)
        + "</p></div>"
        "<div><p>" + ("iota kappa lambda mu nu xi omicron pi rho " * 40)
        + "</p></div>"
        "</body></html>")
URL = "https://fixture.test/lexical-coverage"


@pytest.fixture()
def ws_path():
    tmp = tempfile.mkdtemp()
    try:
        yield pathlib.Path(tmp) / "ws"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_every_stored_chunk_has_a_lexical_row(ws_path):
    """The invariant. A chunk with no row cannot be retrieved, ever."""
    with Workspace(ws_path) as ws:
        ws.index_html(PAGE, URL)
        missing = [c.cid for c in ws.store.chunks()
                   if ws.freq.row_of(c.cid) is None]
        assert not missing, "%d chunk(s) have no frequency row" % len(missing)


def test_rebuild_lexical_repairs_a_gap_and_says_how_big_it_was(ws_path):
    """The repair, with the gap PLANTED rather than hoped for.

    Without planting one, this passes on a workspace that never had a gap --
    which is every fresh workspace, and therefore no evidence at all about
    the corpus where the gap was found.
    """
    with Workspace(ws_path) as ws:
        ws.index_html(PAGE, URL)
        cids = [c.cid for c in ws.store.chunks()]
        assert len(cids) >= 2, "the fixture produced one chunk"

        # Plant it: drop half the rows, exactly as the corpus was found.
        for cid in cids[: len(cids) // 2 or 1]:
            ws.freq.remove(cid)
        gap = [c for c in cids if ws.freq.row_of(c) is None]
        assert gap, "the planted gap did not take"

        got = ws.rebuild_lexical()
        assert got["added"] == len(gap), \
            "repaired %d of %d missing rows" % (got["added"], len(gap))
        still = [c for c in cids if ws.freq.row_of(c) is None]
        assert not still, "%d chunk(s) still have no row" % len(still)


def test_a_read_only_workspace_writes_nothing_on_close(ws_path):
    """`close()` saved the lexical matrix whether or not it was allowed to.

    Asserted on the FILES rather than on a flag: the promise a read-only open
    makes is about the directory, and a guard that was later moved or
    reordered would still satisfy an assertion about `self.read_only`.
    """
    with Workspace(ws_path) as ws:
        ws.index_html(PAGE, URL)

    freq_dir = ws_path / "freq"
    before = {p.name: (p.stat().st_mtime_ns, p.stat().st_size)
              for p in sorted(freq_dir.glob("*"))}
    assert before, "the fixture wrote no frequency files"

    with Workspace(ws_path, read_only=True) as ws:
        # Touch the things a reader touches.
        _ = [c.cid for c in ws.store.chunks()]
        _ = ws.freq.shape

    after = {p.name: (p.stat().st_mtime_ns, p.stat().st_size)
             for p in sorted(freq_dir.glob("*"))}
    assert after == before, \
        "a read-only close rewrote %s" % sorted(
            k for k in after if after.get(k) != before.get(k))


def test_rebuild_lexical_refreshes_a_row_indexed_while_empty(ws_path):
    """A row that EXISTS and says nothing is a veto too.

    Planted the way the corpus got it: a chunk indexed while its markdown was
    empty, whose markdown was later restored. `row_of` is not None, so the
    old repair skipped it, and the chunk stayed unreachable.
    """
    with Workspace(ws_path) as ws:
        ws.index_html(PAGE, URL)
        chunk = next(iter(ws.store.chunks()))
        ws.freq.add(chunk.cid, "")                  # indexed while empty
        row = ws.freq.row_of(chunk.cid)
        assert row is not None and not ws.freq._counts[row], "plant failed"

        got = ws.rebuild_lexical()
        assert got["refreshed"] == 1, got
        assert ws.freq._counts[ws.freq.row_of(chunk.cid)], \
            "the row is still empty"
        assert ws.freq.row_of(chunk.cid) == row, "the row was renumbered"


def test_lexical_rows_survive_a_session_that_never_closed(ws_path):
    """The sidecar is often ended by a hard kill, which runs no `close()`.

    Rows added after open must reach the disk through `save_lexical`, the
    path the sidecar's idle loop takes -- and a second call with nothing new
    must write nothing.
    """
    with Workspace(ws_path) as ws:
        ws.index_html(PAGE, URL)
    ws = Workspace(ws_path)
    try:
        ws.freq.add("planted-cid", "sphinx of black quartz judge my vow")
        assert ws.save_lexical() is True
        assert ws.save_lexical() is False, "saved again with nothing new"
    finally:
        ws.store.close()                            # NOT ws.close(): a kill
    with Workspace(ws_path, read_only=True) as back:
        assert back.freq.row_of("planted-cid") is not None, \
            "a row added in a session that never closed was lost"
        assert back.save_lexical() is False, "a reader wrote the matrix"
