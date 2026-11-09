"""D-2 / T-1, stage 1: the markdown level of an address (PLUGIN_GOAL 154,
"Markdown line in the key"): domain / url-tail / xpath / markdown /
content-detection."""
from domvec.address import ContentAddress as A, md_hash

LEAF = A("https://x.test/a", "/html/body/p[2]", "text.visible", "text()")


def test_an_unrendered_address_keeps_the_four_part_key():
    assert LEAF.md == ""
    assert LEAF.key().count("|") == 3
    assert A.parse(LEAF.key()) == LEAF


def test_a_rendered_address_names_its_line_between_xpath_and_detection():
    r = LEAF.rendered("Some **bold** text")
    url, xpath, md, tag, acc = r.key().split("|")
    assert (url, xpath, tag, acc) == (LEAF.url, LEAF.xpath, LEAF.tag, LEAF.accessor)
    assert md == md_hash("Some **bold** text") and len(md) == 12
    assert A.parse(r.key()) == r
    assert r.leaf() == LEAF


def test_two_renderings_of_one_leaf_are_two_addresses():
    a, b = LEAF.rendered("one form"), LEAF.rendered("one  form")
    assert a != b and a.key() != b.key() and a.aid != b.aid
    assert a.leaf() == b.leaf() == LEAF


def test_a_piece_keeps_its_markdown_level():
    r = A(LEAF.url, LEAF.xpath, LEAF.tag, LEAF.accessor + "~812", md="abc123abc123")
    assert r.whole().md == "abc123abc123"
    assert r.leaf() == LEAF


def test_a_new_store_writes_anchors_at_the_markdown_level(tmp_path):
    """Stage 2: a store with the column renders and anchors every line at the
    markdown level, each one's leaf a trie address; planted PLANT_NO_MD_LEVEL
    keeps the four-part anchors."""
    from domvec import markdown as md
    from domvec.workspace import Workspace
    html = "<html><body><h1>T</h1><p>one line</p><p>two <b>bold</b> line</p></body></html>"

    def run(path, planted):
        md.PLANT_NO_MD_LEVEL = planted
        try:
            with Workspace(path, context_window=256) as ws:
                ws.index_html(html, "https://x.test/p")
                ws.settle()
                assert ws.store.md_level
                got = [a for c in ws.store.chunks("https://x.test/p") for a, _v in ws.store.addresses_of(c.cid)]
                return got
        finally:
            md.PLANT_NO_MD_LEVEL = False

    clean = run(tmp_path / "a", False)
    assert clean and all(a.md and len(a.md) == 12 for a in clean)
    assert all(A.parse(a.key()) == a for a in clean)
    planted = run(tmp_path / "b", True)
    assert planted and not any(a.md for a in planted)
    assert {a.leaf() for a in clean} == set(planted)
