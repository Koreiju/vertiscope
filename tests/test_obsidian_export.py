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

from vertiscope.obsidian.export import _reflow, _rewrite_links, _slug, _title_of
from vertiscope.obsidian import export_vault
from vertiscope.obsidian.export import link_targets


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
    from vertiscope.workspace import Workspace
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
    fence = text.split("```vertiscope", 1)[1].split("```", 1)[0]
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


# --- the note reads once ------------------------------------------------------

def test_the_prose_is_folded_rather_than_shown_beside_the_panel():
    """The note showed the same chunk twice: the panel, then prose under it.

    A callout is a blockquote, so folding costs nothing that made the prose
    necessary -- links stay parsed, search still finds the words, the file is
    still a plain-text archive -- and the `-` collapses it by default, so a
    reader gets one folded line instead of a second copy.
    """
    from vertiscope.obsidian.export import _FOLD, _note

    class Chunk:
        cid, url, xpath, part, chars = "c1", "https://x.test/", "/html", 0, 12
        md = markdown = "words"

    note = _note(Chunk(), "a line\n\nanother [[note|line]]\n")
    body = note.split("---", 2)[-1]
    assert _FOLD in body
    for line in body.splitlines():
        if line.startswith(("```", "---")) or not line.strip():
            continue
        if line.startswith("cid:") or line == _FOLD:
            continue
        assert line.startswith(">"), \
            "a prose line escaped the fold and renders below it: %r" % line


def test_a_blank_line_does_not_break_the_fold():
    """A bare blank line ENDS a callout.

    The rest of the prose then falls out of it and renders below the fold,
    which is the whole thing being fixed -- and it looks fine on a chunk that
    happens to have no blank line in it.
    """
    from vertiscope.obsidian.export import _folded

    out = _folded("first\n\nsecond\n")
    assert "\n>\n" in out, out
    assert not any(l and not l.startswith(">") for l in out.splitlines()[1:])


def test_the_wikilinks_survive_the_fold():
    """The edges the graph is built from are inside the quote now.

    If they did not survive, every vault edge would vanish and the graph would
    go empty -- silently, since a note with no links is a perfectly ordinary
    note.
    """
    from vertiscope.obsidian.export import _folded

    out = _folded("see [[other-note|Other]] for more\n")
    assert "[[other-note|Other]]" in out


def test_a_chunk_with_no_prose_gets_no_empty_callout():
    """An empty fold is a line of chrome standing for nothing."""
    from vertiscope.obsidian.export import _folded

    assert _folded("") == ""
    assert _folded("\n   \n") == ""


# --- the page's own brackets are not wikilinks --------------------------------

def test_a_citation_marker_does_not_become_a_wikilink():
    """Wikipedia renders a citation as `[107]`.

    The distiller draws the link around it as `[[ 107 ]](#cite_note-...)` -- an
    ordinary markdown link whose LABEL is `[ 107 ]` -- and Obsidian reads the
    leading `[[` as a wikilink to a note called "107". Measured in the running
    app: 153 distinct phantom targets over 180 occurrences.

    A broken edge is worse than an absent one. An absent edge is nothing; a
    broken edge says the vault is missing a page it never had.
    """
    from vertiscope.obsidian.export import _neutralise

    out = _neutralise("[[ 107 ]](#cite_note-moore2011-107)")
    assert out == r"[\[ 107 \]](#cite_note-moore2011-107)"
    assert "[[" not in out


def test_an_ordinary_link_is_untouched():
    from vertiscope.obsidian.export import _neutralise

    assert _neutralise("[words](url)") == "[words](url)"
    assert _neutralise("plain prose") == "plain prose"


def test_the_escape_runs_before_the_export_makes_its_own_links():
    """The ordering IS the rule.

    Before `_rewrite_links` the text is distilled markdown and holds no
    wikilinks, so every `[[` in it is the page's. Afterwards the only ones are
    the export's own, and escaping those would empty the graph rather than fix
    it.
    """
    import inspect

    from vertiscope.obsidian import export

    source = inspect.getsource(export.export_vault)
    assert "_rewrite_links(_neutralise(" in source, \
        "the escape must wrap the text going INTO the rewrite"


def test_a_real_wikilink_survives_the_export():
    """Non-vacuity: the escape must not eat the edges it sits next to."""
    from vertiscope.obsidian.export import _neutralise, _rewrite_links
    from vertiscope.graphstore import canonical_url

    target = "https://o.test/"
    canon = canonical_url(target, "https://x.test/")
    body, hits, _misses = _rewrite_links(
        _neutralise("see [Other](%s) and [[ 12 ]](#c)" % target),
        "https://x.test/",
        {canon: "cid-1"},
        {"cid-1": "other-note"})
    assert "[[other-note|Other]]" in body, body
    assert r"[\[ 12 \]]" in body, body
    assert hits == 1


# --- a label may hold balanced brackets ---------------------------------------

def test_a_label_with_nested_brackets_is_still_a_link():
    """coinmarketcap writes `[Sun [New] SUN](/currencies/sun-token/)`.

    CommonMark allows balanced brackets in a label. A pattern that cannot
    hold a raw `]` fails to match ANYWHERE in that string -- so the link was
    never rewritten, its relative target stayed relative, and Obsidian filed
    it as an internal edge to a note that does not exist. It was the last
    dangling edge in the vault.
    """
    from vertiscope.obsidian.export import _LINK

    m = _LINK.search("[Sun [New] SUN](/currencies/sun-token/)")
    assert m is not None
    assert m.group(1) == "Sun [New] SUN"
    assert m.group(2) == "/currencies/sun-token/"


def test_the_escaped_form_still_matches():
    """Non-regression: the citation escape must keep working."""
    from vertiscope.obsidian.export import _LINK

    m = _LINK.search(r"[\[ 107 \]](#cite_note-107)")
    assert m is not None and m.group(2) == "#cite_note-107"


def test_a_bracket_never_reaches_a_wikilink_alias():
    """Obsidian reads a wikilink only as far as the first `]`.

    `[[note|Sun [New] SUN]]` parses as `[[note|Sun [New` and spills ` SUN]]`
    into the note as loose text -- a broken link and a broken sentence. This
    case only became reachable once the pattern above started matching labels
    with brackets in them.
    """
    from vertiscope.graphstore import canonical_url
    from vertiscope.obsidian.export import _neutralise, _rewrite_links

    base = "https://coinmarketcap.com/"
    canon = canonical_url("/currencies/sun-token/", base)
    body, hits, _ = _rewrite_links(
        _neutralise("[Sun [New] SUN](/currencies/sun-token/)"),
        base, {canon: "cid-1"}, {"cid-1": "sun-note"})
    assert hits == 1, body
    assert "[[sun-note|Sun New SUN]]" in body, body
    # The alias holds no bracket and no pipe of its own.
    alias = body.split("|", 1)[1].split("]]")[0]
    assert "[" not in alias and "]" not in alias


def test_an_unresolvable_nested_label_is_absolutised_not_left_relative():
    """The failure this fixes: a relative target Obsidian reads as internal."""
    from vertiscope.obsidian.export import _neutralise, _rewrite_links

    body, hits, misses = _rewrite_links(
        _neutralise("[Sun [New] SUN](/currencies/sun-token/)"),
        "https://coinmarketcap.com/", {}, {})
    assert hits == 0 and misses == 1
    assert "https://coinmarketcap.com/currencies/sun-token/" in body, body


def test_an_escape_backslash_never_reaches_an_alias():
    """The regression this test exists for: 1 dangling edge became 102.

    Stripping only the brackets from an escaped citation label leaves a bare
    backslash on each side, and a trailing backslash before the closing ]]
    escapes it -- so the wikilink never closes. Every citation link in the
    corpus broke at once, and the export's own counts did not move. Only the
    running app showed it.
    """
    from vertiscope.obsidian.export import _ALIAS_UNSAFE

    escaped = "BS[ 16 BS]".replace("BS", chr(92))
    alias = " ".join(_ALIAS_UNSAFE.sub("", escaped).split())
    assert alias == "16"
    assert chr(92) not in alias
    assert "[" not in alias and "]" not in alias


def test_the_alias_never_ends_in_an_escape():
    """Stated as the property, not as the one input that broke."""
    from vertiscope.obsidian.export import _ALIAS_UNSAFE

    cases = ["BS[ 107 BS]", "aBS", "[x]", "a|b", "plain words"]
    for words in [c.replace("BS", chr(92)) for c in cases]:
        alias = " ".join(_ALIAS_UNSAFE.sub("", words).split())
        assert not alias.endswith(chr(92)), words
        assert "[" not in alias and "]" not in alias, words
        assert "|" not in alias, words


def test_a_label_does_not_swallow_the_links_beside_it():
    """The regression allowing balanced brackets caused, before it was guarded.

    arxiv writes a row of links inside one bracketed group:

        [17] arXiv:2608.13200 [ [pdf](/pdf/x) , [html](...) , [other](...) ]

    Allowing a balanced pair inside a label let one match run from the `[ `
    all the way to the last url -- label ` [pdf](/pdf/x) , [html](...) ,
    [other`, target the LAST link. Three links became one, the relative
    `/pdf/x` was never absolutised, and Obsidian filed it as an internal edge
    to a note that does not exist. One dangling edge became a hundred and two.
    """
    from vertiscope.obsidian.export import _LINK

    line = ("- [17] arXiv:2608.13200 [ [pdf](/pdf/2608.13200) , "
            "[html](https://arxiv.org/html/x) , "
            "[other](https://arxiv.org/format/x) ]")
    found = [(m.group(1), m.group(2)) for m in _LINK.finditer(line)]
    assert found == [
        ("pdf", "/pdf/2608.13200"),
        ("html", "https://arxiv.org/html/x"),
        ("other", "https://arxiv.org/format/x"),
    ], found


def test_a_relative_target_in_a_bracketed_row_is_absolutised():
    """The consequence, at the level the vault actually sees.

    Obsidian treats `[words](/relative/path)` as an INTERNAL link, so a
    relative target that survives the rewrite becomes a dangling vault edge.
    """
    from vertiscope.obsidian.export import _neutralise, _rewrite_links

    line = "[ [pdf](/pdf/2608.13200) , [html](https://arxiv.org/html/x) ]"
    body, _hits, misses = _rewrite_links(
        _neutralise(line), "https://arxiv.org/list/cs-cl/recent", {}, {})
    assert misses == 2
    assert "https://arxiv.org/pdf/2608.13200" in body, body
    assert "](/pdf/" not in body, body
