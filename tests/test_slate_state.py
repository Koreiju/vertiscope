"""A search does not rank the slate that holds its own query.

Retrieval, 2026-11-15: the `ego` slate (`domvec/ego.md`) holds the search
cell -- the query the reader typed and the results it read out -- and the
vault reader indexed the whole slate as ONE paragraph (`/p[1]`). Every search
then found its own query there: rank 2 for `unionRect xpaths ...` was the
slate itself, and its results block echoed every earlier result.

A slate is now addressed by its indentation tree; the search cell's subtree
is the search's STATE (`/cell[k]/state[j]`), and the search route keeps a
vault chunk under `/state` to the ego scope, as it keeps a notebook cell's
`/output` (T-13).

Planted `PLANT_SLATE_AS_PARAGRAPH`: one paragraph again -- the echo returns.
Planted `markdown.PLANT_NO_STATE_BOUNDARY`: the state is addressed apart but
the chunker merges it back into the note's one chunk -- the echo returns.
"""
import pytest

from domvec import markdown as M
from domvec import vault as V
from domvec.obsidian.sidecar import search_payload
from domvec.workspace import Workspace

from test_obsidian_layout import _StubEmbedder

SLATE = """---
domvec: slate
---
ego
\tview\tmap
\tcamera\tfirst
\tthrottle\t100
\tsearch
\t\tquery\tunionRect xpaths sensor resolver shadow roots
\t\tdb\ttrue
\t\tk\t20
\t\tresults
\t\t\t1\tunionRect of every xpath the sensor resolver kept
\t\t\t2\tshadow roots the resolver walked
notes
\tcamera paths for the orchid survey
"""

PAGE = ("<html><body><main><h2>Resolver</h2><p>The sensor resolver walks shadow roots and "
        "returns the xpaths it kept; unionRect bounds them.</p>"
        "<p>Orchid pollen is carried by bees.</p></main></body></html>")


def test_a_slate_is_addressed_by_its_tree():
    tags = V.tag_note(SLATE)
    got = {t.xpath: t.subcategory for t in tags}
    assert got.get("/cell[1]") == "visible" and got.get("/cell[1]/state[1]") == "output", got
    assert got.get("/cell[2]") == "visible", got
    state = next(t.value for t in tags if t.xpath == "/cell[1]/state[1]")
    rest = next(t.value for t in tags if t.xpath == "/cell[1]")
    assert "unionRect" in state and "unionRect" not in rest and "camera" in rest


def test_a_plain_note_is_untouched():
    tags = V.tag_note("---\ntags: x\n---\nego\n\tsearch\n\t\tquery\tq\n")
    assert [t.xpath for t in tags][:2] == ["/frontmatter[1]", "/p[1]"], [t.xpath for t in tags]


@pytest.mark.parametrize("planted", [None, "paragraph", "no_boundary"])
def test_the_search_does_not_find_its_own_query(tmp_path, monkeypatch, planted):
    monkeypatch.setattr(V, "PLANT_SLATE_AS_PARAGRAPH", [planted == "paragraph"])
    monkeypatch.setattr(M, "PLANT_NO_STATE_BOUNDARY", planted == "no_boundary")
    with Workspace(tmp_path / "ws", embedder=_StubEmbedder()) as w:
        w.index_html(PAGE, "https://resolver.test/")
        w.index_note(SLATE, "domvec/ego.md")
        w.flush_vectors()
        got = search_payload(w, "unionRect xpaths sensor resolver shadow roots", 5, where="all")
    urls = [h["url"] for h in got["hits"]]
    slate = [u for u in urls if u.endswith("ego.md")]
    if planted:
        assert slate, urls
    else:
        assert not slate and urls and urls[0] == "https://resolver.test/", urls
