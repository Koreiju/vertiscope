"""The vault export, and the one property that makes it worth anything.

An exported note can look perfect in a text editor and contribute nothing to
Obsidian's graph, because Obsidian builds the graph from links it PARSES, and
a link indented four spaces is inside a code block. The first working version
of this export hit exactly that: 82 of 98 notes had a body indented ten
columns by the distiller's DOM depth, and all seven wikilinks it produced were
unreachable. Every test here exists to keep that from coming back quietly.
"""

import re

import pytest

from markdown_it import MarkdownIt

from domvec.obsidian.export import _reflow, _rewrite_links, _slug, _title_of
from domvec.obsidian import export_vault
from domvec.obsidian.export import link_targets


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


# --- the gesture and the export must agree -------------------------------------

def test_link_targets_name_the_same_chunk_the_export_linked_to(ws, tmp_path):
    """One link, one edge, whichever surface wrote it.

    The `/` retrieval gesture rewrites a passage's links using
    `link_targets`, and the export rewrites the same links using
    `_first_chunk_by_page`. If those disagree the graph gets two edges for one
    link -- one from a passage a reader inserted and one from the exported
    note -- pointing at two different chunks of the same page.

    So the rule lives in one place and this asserts the two callers land on
    it. The check is deliberately end-to-end: it reads the notes the export
    actually wrote rather than calling the helper twice.
    """
    ws.index_html(SUB, "https://a.test/sub.html")
    ws.index_html(HOME, "https://a.test")

    report = export_vault(ws, tmp_path / "vault", urls=ws.pages())
    targets = {t["cid"] for t in link_targets(ws)}
    assert targets, "no link targets at all"

    # Every note the export actually linked to, by basename.
    linked = set()
    for path in report.notes.values():
        for match in re.finditer(r"\[\[([^\]|]+)", path.read_text(encoding="utf-8")):
            linked.add(match.group(1))

    if not linked:
        pytest.skip("these pages do not link to one another")

    # Each linked-to note is the chunk `link_targets` names for its page.
    by_name = {p.stem: cid for cid, p in report.notes.items()}
    for name in linked:
        assert by_name.get(name) in targets, (
            "the export linked to %r, which `link_targets` does not name as "
            "any page's landing chunk" % name)


def test_a_target_resolves_through_frontmatter_the_way_the_plugin_does(ws,
                                                                       tmp_path):
    """The plugin maps cid -> note by reading frontmatter. Prove it can.

    `VaultLinks` scans the vault for `cid` in frontmatter, because only the
    vault knows what was exported -- the export may have run to another
    folder, or not at all. A note written without that field would leave every
    passage's links pointing at the web with nothing to say why.
    """
    ws.index_html(HOME, "https://a.test")
    report = export_vault(ws, tmp_path / "vault", urls=ws.pages())

    for target in link_targets(ws):
        path = report.notes.get(target["cid"])
        if path is None:
            continue
        head = path.read_text(encoding="utf-8").split("---", 2)[1]
        assert "cid: %s" % target["cid"] in head, \
            "the landing note does not carry the cid the plugin looks up"
        assert 'url: "%s"' % target["url"] in head


def test_a_note_name_never_starts_with_a_dot():
    """Obsidian ignores dot-prefixed files and folders outright.

    Such a note is written, indexed by nothing, invisible in the vault, and
    any wikilink pointing at it dangles. It is not a corner case: a chunk
    whose first words are a relative url names itself after them, and
    `../../static/oscar/js/bootstrap.min.js` becomes
    `.. .. static oscar js bootstrap.min.js`. Two of the ninety-eight notes in
    the toscrape export were hidden this way, and the count still read
    ninety-eight -- the files existed, the vault just never saw them.
    """
    assert not _slug("../../static/oscar/js/bootstrap.min.js").startswith(".")
    assert not _slug("...").startswith(".")
    assert _slug("...") == "chunk", "a name of only dots must still be a name"
    # Windows strips trailing dots and spaces, so `page.` and `page` are one
    # file and the second export overwrites the first.
    assert not _slug("page.").endswith(".")
    assert not _slug("page ").endswith(" ")


def test_every_exported_note_is_visible_to_the_vault(ws, tmp_path):
    """End to end: no note the export claims is hidden on disk."""
    ws.index_html(
        "<html><body><p><a href='../../static/js/bootstrap.min.js'>"
        "../../static/js/bootstrap.min.js</a></p>"
        "<p>ordinary words</p></body></html>", "https://a.test")
    report = export_vault(ws, tmp_path / "vault", urls=ws.pages())
    for path in report.notes.values():
        assert not path.name.startswith("."), \
            "%s is hidden from Obsidian" % path.name
        assert path.exists()


def test_an_unresolved_link_is_made_absolute(ws, tmp_path):
    """Obsidian treats `[words](relative/path)` as an INTERNAL link.

    A page's own relative hrefs therefore arrived in the vault as links to
    files that do not exist. Measured in the running app on the 98-note
    export: 13 real edges and 263 dangling ones — the graph view showing a few
    hundred phantom nodes around the real ones.

    Worse, some resolved by accident: `docs/index.html` matched
    `obsidian-plugin/node_modules/polished/docs/index.html`, so a book
    catalogue linked into a javascript dependency. An edge that is not merely
    useless but false.
    """
    out, hits, misses = _rewrite_links(
        "see [next](../catalogue/page-2.html) and [gone](/x.html)",
        "https://a.test/books/index.html", {}, {})
    assert hits == 0 and misses == 2
    assert "https://a.test/catalogue/page-2.html" in out, out
    assert "https://a.test/x.html" in out, out
    assert "](../" not in out and "](/x" not in out, \
        "a relative target survived: %s" % out


def test_a_resolved_link_still_wins_over_absolutising(ws, tmp_path):
    """Making unresolved links absolute must not stop the rewrite."""
    out, hits, _ = _rewrite_links(
        "read [next](/two.html)", "https://a.test/one.html",
        {"https://a.test/two.html": "c2"}, {"c2": "Page Two"})
    assert hits == 1
    assert "[[Page Two|next]]" in out
