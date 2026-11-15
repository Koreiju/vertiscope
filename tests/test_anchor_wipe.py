"""A chunk whose every anchor is stale is cleared in one statement.

2026-11-15, re-scanning en.wikipedia.org/wiki/Suffix_tree: every one of the
page's 984 held anchors was stale (its lines had moved), and `_reconcile`
deleted them one statement each -- 14.0 s of a 31 s capture, the largest
single phase between the page and the 3D view. A chunk whose held anchors
are ALL stale is now wiped forward from the chunk in one batch, checked
after, with the per-row delete kept for chunks that are only partly stale.
Planted `PLANT_STALE_PER_ROW`: every row its own statement, as before.
"""

from domvec import graphstore
from domvec.address import ContentAddress
from domvec.graphstore import GraphStore
from domvec.markdown import MarkdownChunk, MarkdownLine

URL = "https://example.org/moved"


def _addr(xpath):
    return ContentAddress(url=URL, xpath=xpath, tag="text.p", accessor="text")


def _chunk(div):
    lines = [MarkdownLine(depth=0, text=f"line {i}", address=_addr(f"/html/body/div[{div}]/p[{i}]/text()[1]"))
             for i in range(1, 6)]
    return MarkdownChunk(url=URL, xpath="/html/body", lines=lines)


def _ingest(store, c):
    return store.ingest(URL, [(l.address, l.text, "") for l in c.lines], [c], complete=False)


def _anchors(store, cid):
    return sorted((a, int(o)) for a, o in store._rows(
        "MATCH (c:Chunk {cid: $c})-[e:Anchors]->(a:Address) RETURN a.aid, e.ord", {"c": cid}))


def _moved(tmp_path):
    store = GraphStore(tmp_path / "g.kuzu")
    a = _chunk(2)
    _ingest(store, a)
    b = _chunk(3)                         # the same lines, every address moved
    assert b.cid == a.cid
    counts = _ingest(store, b)
    want = sorted((l.address.aid, i) for i, l in enumerate(b.lines))
    return counts, _anchors(store, b.cid), want


def test_an_all_stale_chunk_is_wiped_in_one_batch(tmp_path):
    counts, got, want = _moved(tmp_path)
    assert counts["anchors_stale"] == 5
    assert counts["anchors_wiped_chunks"] == 1
    assert counts["anchors_stale_by_row"] == 0
    assert got == want                    # exactly the new anchors, one a line


def test_planted_per_row_deletes_each_and_reaches_the_same_state(tmp_path):
    graphstore.PLANT_STALE_PER_ROW[0] = True
    try:
        counts, got, want = _moved(tmp_path)
    finally:
        graphstore.PLANT_STALE_PER_ROW[0] = False
    assert counts["anchors_wiped_chunks"] == 0
    assert counts["anchors_stale_by_row"] == 5
    assert got == want


def test_a_partly_stale_chunk_keeps_its_unchanged_anchors(tmp_path):
    store = GraphStore(tmp_path / "g.kuzu")
    a = _chunk(2)
    _ingest(store, a)
    lines = list(a.lines)
    lines[4] = MarkdownLine(depth=0, text="line 5", address=_addr("/html/body/div[7]/p[5]/text()[1]"))
    b = MarkdownChunk(url=URL, xpath="/html/body", lines=lines)
    counts = _ingest(store, b)
    assert counts["anchors_stale"] == 1
    assert counts["anchors_wiped_chunks"] == 0          # not every anchor stale: by row
    assert counts["anchors_stale_by_row"] == 1
    assert _anchors(store, b.cid) == sorted((l.address.aid, i) for i, l in enumerate(b.lines))


def _timed(tmp_path, per_row, n=400):
    import time
    store = GraphStore(tmp_path / ("r" if per_row else "b"))
    def big(div):
        return MarkdownChunk(url=URL, xpath="/html/body", lines=[
            MarkdownLine(depth=0, text=f"line {i}", address=_addr(f"/html/body/div[{div}]/p[{i}]/text()[1]"))
            for i in range(1, n + 1)])
    _ingest(store, big(2))
    graphstore.PLANT_STALE_PER_ROW[0] = per_row
    try:
        counts = _ingest(store, big(3))
    finally:
        graphstore.PLANT_STALE_PER_ROW[0] = False
    return counts["ms_reconcile"], counts


def test_the_batched_wipe_is_cheaper_than_a_statement_a_row(tmp_path):
    batched, cb = _timed(tmp_path, False)
    per_row, cr = _timed(tmp_path, True)
    print(f"reconcile 400 stale anchors: batched {batched} ms, per row {per_row} ms")
    assert cb["anchors_wiped_chunks"] == 1 and cr["anchors_stale_by_row"] == 400
    assert batched < per_row
