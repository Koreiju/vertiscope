"""The vault export, and the one property that makes it worth anything.

An exported note can look perfect in a text editor and contribute nothing to
Obsidian's graph, because Obsidian builds the graph from links it PARSES, and
a link indented four spaces is inside a code block. The first working version
of this export hit exactly that: 82 of 98 notes had a body indented ten
columns by the distiller's DOM depth, and all seven wikilinks it produced were
unreachable. Every test here exists to keep that from coming back quietly.
"""

import pytest

from markdown_it import MarkdownIt

from domvec.obsidian.export import _reflow, _rewrite_links, _title_of
from domvec.obsidian import export_vault


COMMONMARK = MarkdownIt("commonmark")


def _links_a_parser_can_see(text: str) -> int:
    """Wikilinks that survive block parsing -- the only ones the graph gets."""
    body = text.split("---", 2)[-1]
    buried = sum(tok.content.count("[[")
                 for tok in COMMONMARK.parse(body)
                 if tok.type == "code_block")
    return body.count("[[") - buried


# --- the indentation property ------------------------------------------------

def test_reflow_keeps_nesting_but_not_the_column():
    """Depth survives; the absolute column that made it code does not."""
    md = "\n".join([
        "          - Page 1 of 50",
        "            - deeper",
        "          - sibling",
    ])
    out = _reflow(md)
    assert out.splitlines() == ["- Page 1 of 50", "  - deeper", "- sibling"]


def test_a_reflowed_link_is_still_visible_to_a_parser():
    """The whole point: the link must survive block parsing.

    Asserted through a real CommonMark parser rather than by measuring
    indentation, because "indent >= 4" is not the question -- four spaces
    inside a list is nesting, and only four spaces starting a block is code.
    A hand-rolled indent check called two perfectly reachable links buried.
    """
    md = "          - see [next](https://x.test/2)"
    raw, _, _ = _rewrite_links(md, "https://x.test/",
                               {"https://x.test/2": "c2"}, {"c2": "Page Two"})
    assert _links_a_parser_can_see(raw) == 0, \
        "unreflowed: a ten-column indent should bury the link"

    flowed, hits, _ = _rewrite_links(_reflow(md), "https://x.test/",
                                     {"https://x.test/2": "c2"},
                                     {"c2": "Page Two"})
    assert hits == 1
    assert _links_a_parser_can_see(flowed) == 1


# --- the rewrite ---------------------------------------------------------------

def test_rewrite_keeps_the_sentence_and_reports_both_counts():
    """A resolved link reads the same; an unresolved one is left alone.

    Both counts are asserted because a rewrite that resolves nothing looks
    exactly like one that works if only the hits are reported.
    """
    md = "read [next](https://x.test/2) and [away](https://other.test/)"
    out, hits, misses = _rewrite_links(
        md, "https://x.test/", {"https://x.test/2": "c2"}, {"c2": "Page Two"})
    assert hits == 1 and misses == 1
    assert "[[Page Two|next]]" in out
    assert "[away](https://other.test/)" in out, "unresolved link was mangled"


def test_title_ignores_the_marker_and_names_the_content():
    assert _title_of("   - Page 1 of 50") == "Page 1 of 50"
    assert _title_of("## [Travel](https://x.test/t)") == "Travel"


# --- end to end ----------------------------------------------------------------

HOME = ("<html><body><h1>Home</h1><p>the front page</p>"
        "<a href='https://a.test/sub.html'>go on</a></body></html>")
SUB = "<html><body><h1>Sub</h1><p>second page</p></body></html>"


@pytest.fixture()
def ws(tmp_path):
    from domvec.workspace import Workspace
    with Workspace(tmp_path / "ws") as workspace:
        yield workspace


def test_a_web_link_becomes_a_graph_edge(ws, tmp_path):
    """The feature, stated as one assertion.

    A link between two scanned pages has to arrive in the vault as a wikilink
    a parser can see. Anything less and the graph view -- the entire reason
    the export exists -- shows disconnected dots.
    """
    ws.index_html(SUB, "https://a.test/sub.html")
    ws.index_html(HOME, "https://a.test")

    report = export_vault(ws, tmp_path / "vault", urls=ws.pages())
    assert report.note_count > 0
    assert report.wikilinks > 0, "no web link survived into the vault"

    reachable = sum(_links_a_parser_can_see(p.read_text(encoding="utf-8"))
                    for p in report.notes.values())
    assert reachable >= report.wikilinks, \
        "links were written but a parser cannot see them"


def test_the_payload_fence_carries_only_the_cid(ws, tmp_path):
    """State the plugin reads must come from the store, not the note.

    A note that carried its own copy of the chunk would drift from the store
    the moment either changed, and the vault is a rendering, not a source.
    """
    ws.index_html(HOME, "https://a.test")
    report = export_vault(ws, tmp_path / "vault", urls=ws.pages())
    cid, path = next(iter(report.notes.items()))
    text = path.read_text(encoding="utf-8")
    fence = text.split("```domvec", 1)[1].split("```", 1)[0]
    assert fence.strip() == "cid: %s" % cid
