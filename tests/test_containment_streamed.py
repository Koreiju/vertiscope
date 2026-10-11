"""The chunk hierarchy holds however a page's chunks were streamed in.

`_link_containment` links a chunk to its nearest enclosing chunk only among
one write's chunks, so a page captured a drain at a time held almost none:
RFC 9110 drew all 1,172 chunks off its url node (2026-10-11, "it looks like a
shortcut where there's just all the recursive chunks linked to their root URL
node"). `contains_within` reads the trie's parent from the page's chunk roots.
"""

from domvec import graphstore
from domvec.address import ContentAddress
from domvec.graphstore import GraphStore, _nearest_enclosing
from domvec.markdown import MarkdownChunk, MarkdownLine

URL = "https://example.org/streamed"


def _chunk(xpath, word):
    addr = ContentAddress(url=URL, xpath=xpath + "/p/text()[1]", tag="text.p", accessor="text")
    return MarkdownChunk(url=URL, xpath=xpath, lines=[MarkdownLine(depth=0, text=word, address=addr)])


def test_nearest_enclosing_is_the_longest_proper_prefix():
    rows = [("body", "/html/body"), ("sec", "/html/body/div[2]"), ("deep", "/html/body/div[2]/section/p"),
            ("side", "/html/body/aside")]
    assert sorted(_nearest_enclosing(rows)) == sorted([("body", "sec"), ("sec", "deep"), ("body", "side")])
    # No enclosing chunk: no edge -- the page node takes it.
    assert _nearest_enclosing([("a", "/html/body/div"), ("b", "/html/body/nav")]) == []


def test_a_parent_streamed_after_its_children_still_holds_them(tmp_path):
    store = GraphStore(tmp_path / "g.kuzu")
    kids = [_chunk("/html/body/div[2]", "alpha"), _chunk("/html/body/div[3]", "beta")]
    parent = _chunk("/html/body", "gamma")
    # Two drains: the children first, then the chunk that encloses them.
    store.ingest(URL, [], kids, complete=False)
    store.ingest(URL, [], [parent], complete=False)
    got = set(store.contains_within(URL))
    want = {(parent.cid, kids[0].cid), (parent.cid, kids[1].cid)}
    assert want <= got
    # Planted: the stored edges, written per drain -- the parent never met its children.
    graphstore.PLANT_STORED_CONTAINMENT[0] = True
    try:
        assert not (want & set(store.contains_within(URL)))
    finally:
        graphstore.PLANT_STORED_CONTAINMENT[0] = False
