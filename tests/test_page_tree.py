"""A page opens into its patricia TREE: one parent per node, chains collapsed.

The reader's definition (Addendum VII): the subtree of the page's content
nodes in the shadow DOM, where a run of intermediate elements from one node
to the next is ONE link. The graph they were shown instead had nodes with
several parents -- a per-step view's star plus containment among its members
-- which closed into triangles and could not fan out.
"""

from types import SimpleNamespace

from vertiscope.obsidian import layout as L

URL = "https://tree.test/page"


def _chunk(cid, xpath, part=0, md="text"):
    return SimpleNamespace(cid=cid, url=URL, xpath=xpath, part=part, md=md,
                           chars=len(md), dup_n=1, group_n=1, group_of="",
                           redundant=False)


class _Store:
    def __init__(self, chunks):
        self._c = chunks

    def chunks(self, url=""):
        return [c for c in self._c if c.url == url]


def _tree(chunks):
    ws = SimpleNamespace(store=_Store(chunks))
    proj = SimpleNamespace(page_pos={URL: [1.0, 2.0, 3.0]})
    return L.page_tree(ws, URL, proj)


def test_branches_are_nodes_chains_are_links_and_every_node_has_one_parent():
    got = _tree([
        _chunk("c1", "/html/body/div/main/p[1]"),
        _chunk("c2", "/html/body/div/main/p[2]"),
        _chunk("c3", "/html/body/div/aside/ul/li", 0),
        _chunk("c4", "/html/body/div/aside/ul/li", 1),
    ])
    parent = {e["target"]: e["source"] for e in got["edges"]}
    assert got["max_parents"] == 1
    assert len(parent) == len(got["nodes"]), "a node without a parent, or a stray edge"
    ids = {n["cid"] for n in got["nodes"]}
    div, main = "path:%s#/html/body/div" % URL, "path:%s#/html/body/div/main" % URL
    li = "path:%s#/html/body/div/aside/ul/li" % URL
    # The branch points, and only those: html/body and aside/ul are chains.
    assert {n for n in ids if n.startswith("path:")} == {div, main, li}
    assert parent[div] == "page:" + URL
    assert parent[main] == div
    assert parent[li] == div, "the aside/ul chain was not collapsed to one link"
    assert parent["c1"] == main and parent["c2"] == main
    assert parent["c3"] == li and parent["c4"] == li
    assert all(n["pos"] == [1.0, 2.0, 3.0] for n in got["nodes"])


def test_a_deep_single_chain_is_one_link_from_the_page():
    got = _tree([_chunk("only", "/html/body/div/div/div/section/article/p")])
    assert [e for e in got["edges"]] == [{"source": "page:" + URL, "target": "only"}]
    assert got["branches"] == 0


def test_a_chunk_inside_another_chunks_element_hangs_from_the_shared_branch():
    # c1 is rooted at <section>, c2 deeper inside it: <section> holds a chunk
    # AND has a child, so it is a branch, and both hang from it.
    got = _tree([_chunk("c1", "/html/body/section"),
                 _chunk("c2", "/html/body/section/div/p")])
    parent = {e["target"]: e["source"] for e in got["edges"]}
    sec = "path:%s#/html/body/section" % URL
    assert parent["c1"] == sec and parent["c2"] == sec
    assert got["max_parents"] == 1
