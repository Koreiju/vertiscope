"""A chunk's lines keep their own addresses.

arXiv's listing, 2026-10-12: "Total of 341 entries" keyed to the `h1` that
reads "Machine Learning" -- every line one off from a point on. A line
drawing an address another line also draws got no anchor (the write kept one
anchor per ADDRESS), and the payload zipped the ordered anchors with the lines
by POSITION -- so from that gap on, each line took its neighbour's address.
Anchored per line and read by line index, each line names its own. Planted:
`PLANT_ONE_ANCHOR_PER_ADDRESS` (the lost anchor), `_PLANT_POSITIONAL_ANCHORS`
(the zip); both together reproduce the shift.
"""

from types import SimpleNamespace

from vertiscope import graphstore
from vertiscope.address import ContentAddress
from vertiscope.graphstore import GraphStore
from vertiscope.markdown import MarkdownChunk, MarkdownLine
from vertiscope.obsidian import sidecar

URL = "https://example.org/listing"


def _addr(xpath):
    return ContentAddress(url=URL, xpath=xpath, tag="text.p", accessor="text")


def _chunk():
    h1, d2, d3 = (_addr("/html/body/h1/text()[1]"), _addr("/html/body/div[2]/text()[1]"),
                  _addr("/html/body/div[3]/text()[1]"))
    lines = [
        MarkdownLine(depth=0, text="Machine Learning", address=h1),
        MarkdownLine(depth=0, text="Total of 341 entries", address=d2),
        MarkdownLine(depth=0, text="Showing up to 50 entries", address=d3),
        MarkdownLine(depth=0, text="Total of 341 entries (again)", address=d2),  # the same address twice
    ]
    return MarkdownChunk(url=URL, xpath="/html/body", lines=lines)


def _payload_keys(tmp_path):
    store = GraphStore(tmp_path / "g.kuzu")
    c = _chunk()
    addrs = [(l.address, l.text, "") for l in c.lines if l.address is not None]
    store.ingest(URL, addrs, [c], complete=False)
    ws = SimpleNamespace(store=store, addresses_for=store.addresses_of, context_window=256)
    pay = sidecar.chunk_payload(ws, c.cid)
    want = [l.address.key() if l.address is not None else "" for l in c.lines]
    return [l["key"] for l in pay["lines"]], want


def test_every_line_keeps_its_own_address(tmp_path):
    got, want = _payload_keys(tmp_path)
    assert got == want


def test_the_positional_zip_alone_holds_while_every_line_is_anchored(tmp_path):
    sidecar._PLANT_POSITIONAL_ANCHORS[0] = True
    try:
        got, want = _payload_keys(tmp_path)
    finally:
        sidecar._PLANT_POSITIONAL_ANCHORS[0] = False
    # Together with one anchor per address, the zip shifts: the line whose
    # anchor was lost takes the next line's address -- the arXiv pattern.
    assert got == want                     # alone, with every line anchored, it holds


def test_planted_one_anchor_per_address_loses_a_line(tmp_path):
    graphstore.PLANT_ONE_ANCHOR_PER_ADDRESS[0] = True
    try:
        got, want = _payload_keys(tmp_path)
    finally:
        graphstore.PLANT_ONE_ANCHOR_PER_ADDRESS[0] = False
    assert got[1] == "" and got != want     # by line: the lost line is blank, no shift


def test_both_planted_reproduce_the_arxiv_shift(tmp_path):
    graphstore.PLANT_ONE_ANCHOR_PER_ADDRESS[0] = True
    sidecar._PLANT_POSITIONAL_ANCHORS[0] = True
    try:
        got, want = _payload_keys(tmp_path)
    finally:
        graphstore.PLANT_ONE_ANCHOR_PER_ADDRESS[0] = False
        sidecar._PLANT_POSITIONAL_ANCHORS[0] = False
    # "Total of 341 entries" (line 1) keyed to the NEXT line's element.
    assert got[1] == want[2]


def test_same_markdown_with_moved_addresses_is_not_skipped(tmp_path):
    # A sibling shift that leaves every line's TEXT the same: arXiv's "View
    # HTML" stayed keyed to `a[3]` (the pdf link) because the capture skipped
    # chunks whose markdown was unchanged. The signature of the addresses
    # says what the markdown cannot.
    from vertiscope.graphstore import anchor_sig
    store = GraphStore(tmp_path / "g.kuzu")
    c = _chunk()
    store.ingest(URL, [(l.address, l.text, "") for l in c.lines], [c], complete=False)
    held = store.chunk_sigs([c.cid])[c.cid]
    assert held == (c.markdown, anchor_sig(c), 4)         # unchanged and one anchor a line: skipped
    shifted = MarkdownChunk(url=URL, xpath=c.xpath, lines=[
        MarkdownLine(depth=l.depth, text=l.text,
                     address=_addr(l.address.xpath.replace("div[2]", "div[4]"))) for l in c.lines])
    assert shifted.cid == c.cid and shifted.markdown == c.markdown
    assert held != (shifted.markdown, anchor_sig(shifted), 4)  # moved: written
    # Planted (`_PLANT_SKIP_BY_MD`): by markdown alone it would be skipped.
    assert store.chunk_mds([c.cid])[c.cid] == shifted.markdown


def test_a_chunk_carrying_stale_anchors_is_not_skipped(tmp_path):
    # The skip also counts anchors: one per addressed line, or the chunk is
    # written again -- which is what deletes the extras.
    store = GraphStore(tmp_path / "g.kuzu")
    c = _chunk()
    store.ingest(URL, [(l.address, l.text, "") for l in c.lines], [c], complete=False)
    extra = _addr("/html/body/div[9]/text()[1]")
    store.ingest(URL, [(extra, "x", "")], [], complete=False)
    store._execute("MATCH (k:Chunk {cid: $c}), (a:Address {aid: $a}) CREATE (k)-[:Anchors {ord: 0}]->(a)",
                   {"c": c.cid, "a": extra.aid})
    assert store.chunk_sigs([c.cid])[c.cid][2] == 5       # 4 lines, 5 anchors: not skipped
    store.ingest(URL, [(l.address, l.text, "") for l in c.lines], [c], complete=False)
    assert store.chunk_sigs([c.cid])[c.cid][2] == 4       # written again: the stale one gone


def test_heal_keeps_the_anchor_that_matches_each_line(tmp_path):
    # G-186's clean-up: a chunk carrying a stale anchor beside a line's own,
    # and one past its last line. The anchor whose value reads like the line
    # stays; the others go.
    store = GraphStore(tmp_path / "g.kuzu")
    c = _chunk()
    store.ingest(URL, [(l.address, l.text, "") for l in c.lines], [c], complete=False)
    stale = _addr("/html/body/aside/text()[1]")
    beyond = _addr("/html/body/footer/text()[1]")
    store.ingest(URL, [(stale, "Something else entirely", ""), (beyond, "Footer", "")], [], complete=False)
    for a, o in ((stale, 0), (beyond, 9)):
        store._execute("MATCH (k:Chunk {cid: $c}), (x:Address {aid: $a}) CREATE (k)-[:Anchors {ord: $o}]->(x)",
                       {"c": c.cid, "a": a.aid, "o": o})
    assert store.chunk_sigs([c.cid])[c.cid][2] == 6
    got = store.heal_anchors()
    assert got["chunks"] == 1 and got["beyond_last_line"] == 1 and got["duplicates_resolved"] == 1
    assert store.chunk_sigs([c.cid])[c.cid][2] == 4
    assert [a.key() for a, _v in (store.anchors_by_line(c.cid)[i] for i in range(4))] == [l.address.key() for l in c.lines]
    # Healed: nothing left to do.
    assert store.heal_anchors()["chunks"] == 0
