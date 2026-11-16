"""D-2 read off the store: anchors keyed at the markdown level (five parts)
against those that are not (four).

A fresh store has the md column, and every anchor a capture writes carries the
line's md hash. Planted: an anchor whose Address lost its md -- the residue a
pre-migration store holds -- must be counted as four-part, or the measure
could not tell a migrated store from an unmigrated one.
"""
import pytest

from domvec.workspace import Workspace

from test_obsidian_layout import _StubEmbedder

PAGE = ("<html><body><main><h1>Radix</h1><p>A radix tree stores shared prefixes once.</p>"
        "<ul><li>insert</li><li>lookup</li><li>delete</li></ul></main></body></html>")


@pytest.mark.parametrize("planted", [False, True])
def test_every_captured_anchor_is_keyed_at_the_markdown_level(tmp_path, planted):
    with Workspace(tmp_path / "ws", embedder=_StubEmbedder()) as w:
        w.index_html(PAGE, "https://radix.test/")
        store = w.store
        got = store.anchor_levels()
        assert got["md_level"] is True
        assert got["five"] > 0 and got["four"] == 0, got
        if planted:
            store._execute("MATCH ()-[r:Anchors]->(a:Address) WITH a LIMIT 1 SET a.md = ''")
            again = store.anchor_levels()
            assert again["four"] >= 1 and again["five"] == got["five"] - again["four"], again
