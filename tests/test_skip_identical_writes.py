"""A capture writes only chunks the store does not already hold identically.

2026-10-11: a new capture session re-sends every chunk of a page as added; the
store rewrote 52 identical chunks on GitHub (2.5 s) and 212 of 212 on a
ScienceDirect article. `chunk_mds` is what the sidecar's filter compares
against. Planted: a changed chunk must NOT read as held.
"""

from vertiscope.workspace import Workspace

HTML = "<html><body><h1>Title</h1>" + "".join(
    "<p>para %d with enough words to chunk across the window</p>" % i for i in range(40)) + "</body></html>"
URL = "http://skip.test/p"


def test_held_markdown_matches_what_a_resend_carries(tmp_path):
    with Workspace(tmp_path) as ws:
        ws.index_html(HTML, URL)
        rows = ws.store._rows("MATCH (c:Chunk {url: $u}) RETURN c.cid, c.md", {"u": URL})
        assert len(rows) >= 2
        held = ws.store.chunk_mds([cid for cid, _ in rows] + ["no-such-cid"])
        assert {cid: md for cid, md in rows} == {k: v for k, v in held.items()}
        assert "no-such-cid" not in held
        # The filter's own test, both ways: the same text is skipped, an edit is not.
        resent = {cid: md for cid, md in rows}
        edited = dict(resent); first = next(iter(edited)); edited[first] = edited[first] + " (edited)"
        assert [c for c, m in resent.items() if held.get(c) != m] == []
        assert [c for c, m in edited.items() if held.get(c) != m] == [first]


def test_empty_ask_reads_nothing(tmp_path):
    with Workspace(tmp_path) as ws:
        assert ws.store.chunk_mds([]) == {} and ws.store.chunk_mds(["", None]) == {}
