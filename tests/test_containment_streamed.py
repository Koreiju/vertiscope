"""The chunk hierarchy holds however a page's chunks were streamed in.

`_link_containment` links a chunk to its nearest enclosing chunk only among
one write's chunks, so a page captured a drain at a time held almost none:
RFC 9110 drew all 1,172 chunks off its url node (2026-10-11, "it looks like a
shortcut where there's just all the recursive chunks linked to their root URL
node"). `contains_within` reads the trie's parent from the page's chunk roots.
"""

from vertiscope import graphstore
from vertiscope.address import ContentAddress
from vertiscope.graphstore import GraphStore, _nearest_enclosing
from vertiscope.markdown import MarkdownChunk, MarkdownLine

URL = "https://example.org/streamed"


def _chunk(xpath, word):
    addr = ContentAddress(url=URL, xpath=xpath + "/p/text()[1]", tag="text.p", accessor="text")
    return MarkdownChunk(url=URL, xpath=xpath, lines=[MarkdownLine(depth=0, text=word, address=addr)])


def test_nearest_enclosing_is_the_longest_proper_prefix():
    rows = [("body", "/html/body"), ("sec", "/html/body/div[2]"), ("deep", "/html/body/div[2]/section/p"),
            ("side", "/html/body/aside")]
    assert sorted(_nearest_enclosing(rows)) == sorted([("body", "sec"), ("sec", "deep"), ("body", "side")])
    # By trie node: a part of /html/body whose own addresses all sit under
    # div[5] is a child of the chunk on /html/body, not a sibling of it.
    from vertiscope.graphstore import _trie_nodes
    nodes = _trie_nodes([("body", "/html/body/h1/text()[1]"), ("body", "/html/body/p/text()[1]"),
                         ("part2", "/html/body/div[5]/p/text()[1]"), ("part2", "/html/body/div[5]/ul/li/text()[1]")])
    assert nodes["part2"] == ("html", "body", "div[5]")
    assert _nearest_enclosing(nodes, ["body", "part2"]) == [("body", "part2")]
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


def test_an_undrawn_owner_does_not_take_the_edge(tmp_path):
    # Two chunks on one node (an element and its duplicate copy) and a child
    # under it. Asked among what is DRAWN, the child hangs from the drawn one.
    store = GraphStore(tmp_path / "g.kuzu")
    dup = _chunk("/html/body/section", "one")
    drawn_owner = _chunk("/html/body/section", "two")
    child = _chunk("/html/body/section/ul/li", "three")
    store.ingest(URL, [], [dup, drawn_owner, child], complete=False)
    pairs = set(store.contains_within(URL, among={drawn_owner.cid, child.cid}))
    assert (drawn_owner.cid, child.cid) in pairs


def test_trie_nodes_are_read_once_per_page_until_it_is_written(tmp_path):
    # PLUGIN_GOAL 110: a chunk-view layout asked every page's anchors fresh --
    # 42-66 s over 294 pages. Kept per page, dropped when the page is written.
    store = GraphStore(tmp_path / "g.kuzu")
    kids = [_chunk("/html/body/div[2]", "alpha")]
    parent = _chunk("/html/body", "gamma")
    store.ingest(URL, [], kids + [parent], complete=False)
    first = set(store.contains_within(URL))
    again = set(store.contains_within(URL))
    assert first == again and store.tnode_stats["computed"] == 1 and store.tnode_stats["reused"] == 1
    # A write to the page drops its nodes: the next read sees the new chunk.
    more = _chunk("/html/body/div[3]", "beta")
    store.ingest(URL, [], [more], complete=False)
    assert (parent.cid, more.cid) in set(store.contains_within(URL))
    assert store.tnode_stats["computed"] == 2
    # Planted: no memo -- every call reads the anchors again.
    graphstore.PLANT_NO_TNODE_MEMO[0] = True
    try:
        store.contains_within(URL)
        assert store.tnode_stats["computed"] == 3
    finally:
        graphstore.PLANT_NO_TNODE_MEMO[0] = False
