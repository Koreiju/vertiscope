"""`GraphStore.chunks_many`: one read for many chunks, the same answer as a
read per chunk -- below the scan threshold (per-cid) and above it (one
scan). Search read its hits one query each, twice (2026-10-17). A cid the
store does not hold is absent, not an error."""

from vertiscope.address import ContentAddress
from vertiscope.graphstore import GraphStore
from vertiscope.markdown import MarkdownChunk, MarkdownLine

URL = "https://example.org/many"


def _chunk(i):
    xp = "/html/body/div[%d]" % (i + 1)
    addr = ContentAddress(url=URL, xpath=xp + "/p/text()[1]", tag="text.p", accessor="text")
    return MarkdownChunk(url=URL, xpath=xp, lines=[MarkdownLine(depth=0, text="word%d alpha" % i, address=addr)])


def test_many_equals_one_by_one(tmp_path):
    store = GraphStore(tmp_path / "g.kuzu")
    chunks = [_chunk(i) for i in range(20)]
    store.ingest(URL, [(c.lines[0].address, c.lines[0].text, "") for c in chunks], chunks, complete=False)
    cids = [c.cid for c in chunks]
    for want in (cids[:5], cids):                       # keyed lookups, then the scan
        got = store.chunks_many(want + ["0000dead0000beef"])
        assert set(got) == set(want)
        for cid in want:
            assert got[cid] == store.chunk(cid)
