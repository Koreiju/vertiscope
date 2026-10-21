"""Reading order is part of the map, and nothing else was checking it.

An affine map preserves relations, not origin. Containment survives as
indentation, ratios survive as relative size — and *reading order* survives as
the order lines come out. Coverage says every unit arrived; dedup says none
arrived twice; neither says they arrived in the right order, and for a long
time none of them did.

The defect these tests were written for: a scan keys its walk positions on
absolute xpaths and writes an index wherever an element has same-tag
siblings — ``.../ul/li[1]``, ``.../ul/li[2]``. The trie builds its path from
``ContentAddress.path()``, which drops the index on the first of a group —
``.../ul/li``. So the lookup missed for the first sibling of every repeated
group and only for that one. It got ``doc_pos = -1``,
``ordered_children`` sorts unknown positions after known ones, and the first
item of every list, table and card grid was drawn at the bottom of its group.

Every address was right. Every unit was present. Every dedup decision was
right. The page just read in the wrong order, on the snapshot path only,
which is also the path that builds the index.

Measured over the fixture pages before and after: 46 reading-order inversions
against the scan's own composed-tree walk, down to 12 — and of those twelve,
the ones that remain are the renderer deliberately placing a heading with the
card it labels, which is a rearrangement it means to make.
"""

import glob
from pathlib import Path
import io

import pytest

from vertiscope.core.content_tagger import ContentTagger
from vertiscope.core.shadow_html_parser import ShadowDOM
from vertiscope.markdown import render_trie
from vertiscope.stream import StreamingScan
from vertiscope.trie import trie_doc_pos

FIXTURES = sorted(glob.glob("tests/fixtures/*.html"))


def _reading_positions(html, url, window=1200, prose_only=False):
    """Walk position of each rendered text line, in the order drawn.

    The scan's ``doc_pos`` is the reference: it is the order the composed-tree
    walk met the elements, so it handles shadow roots and slots, which a
    light-DOM xpath sort does not.

    ``prose_only`` drops headings. A heading whose words live in child
    elements is deliberately drawn with the card it labels, which puts it
    ahead of content the walk met earlier -- a rearrangement the renderer
    means to make, and one that scales with the number of cards, so counting
    it would make the budget below a function of page layout rather than of
    correctness.
    """
    positions = ContentTagger(ShadowDOM(html)).tag().doc_pos
    scan = StreamingScan(url, context_window=window)
    out = []
    for chunk in render_trie(scan.push(html, passno=0).trie,
                             context_window=window):
        for line in chunk.lines:
            address = line.address
            if address is None or address.category != "text":
                continue
            if prose_only and line.text.lstrip().startswith("#"):
                continue
            owner = address.xpath.split("/text()")[0]
            if owner in positions:
                out.append((positions[owner], line.text))
    return out


def _inversions(pairs):
    return [(a, b) for (a, _t1), (b, _t2) in zip(pairs, pairs[1:]) if a > b]


# --- the mechanism, in isolation --------------------------------------------


def test_doc_pos_is_rekeyed_to_the_tries_own_paths():
    raw = {
        "/html/body/main/ul": 4,
        "/html/body/main/ul/li[1]": 5,
        "/html/body/main/ul/li[2]": 6,
        "/html/body/main/ul/li[1]/h3": 7,
    }
    assert trie_doc_pos(raw) == {
        "/html/body/main/ul": 4,
        "/html/body/main/ul/li": 5,
        "/html/body/main/ul/li[2]": 6,
        "/html/body/main/ul/li/h3": 7,
    }


def test_an_accessor_bracket_is_not_a_sibling_index():
    """``text()[1]`` is a detector's own sub-path, not an ordinal."""
    assert trie_doc_pos({"/a/p/text()[1]": 9}) == {"/a/p/text()[1]": 9}


def test_the_earlier_position_wins_a_collision():
    both = {"/a/li[1]": 8, "/a/li": 3}
    assert trie_doc_pos(both) == {"/a/li": 3}


# --- the defect it caused ---------------------------------------------------


def _rows(pairs):
    body = "".join(
        "<li><h3>Item {}</h3><p>{}</p></li>".format(i, text)
        for i, text in pairs)
    return "<html><body><main><ul>{}</ul></main></body></html>".format(body)


def test_the_first_list_item_is_drawn_first():
    """The whole defect in one assertion.

    Without the re-keying this renders Item 0 last, after Item 5.
    """
    pairs = [(i, "body {}".format(i)) for i in range(6)]
    drawn = [t for _p, t in
             _reading_positions(_rows(pairs), "https://order.test/p",
                                window=100000)]
    assert drawn[0] == "### Item 0", drawn[:3]
    assert drawn == ["### Item 0", "body 0", "### Item 1", "body 1",
                     "### Item 2", "body 2", "### Item 3", "body 3",
                     "### Item 4", "body 4", "### Item 5", "body 5"]


def test_an_inserted_first_row_is_drawn_first():
    pairs = [(i, "body {}".format(i)) for i in range(6)]
    grown = [(-1, "body -1")] + pairs
    drawn = [t for _p, t in
             _reading_positions(_rows(grown), "https://order.test/p",
                                window=100000)]
    assert drawn[0] == "### Item -1", drawn[:3]


def test_a_list_reads_in_order_at_every_depth():
    """Nested repeated siblings: the defect applied at each level."""
    inner = "".join("<li><p>leaf {}-{}</p></li>".format(o, i)
                    for o in range(3) for i in range(3))
    html = ("<html><body><main><ul>"
            + "".join("<li><ul>{}</ul></li>".format(
                "".join("<li><p>leaf {}-{}</p></li>".format(o, i)
                        for i in range(3)))
                for o in range(3))
            + "</ul></main></body></html>")
    assert inner  # the flat form, for reference
    drawn = [t for _p, t in
             _reading_positions(html, "https://order.test/nested",
                                window=100000)]
    assert drawn == ["leaf {}-{}".format(o, i)
                     for o in range(3) for i in range(3)], drawn


def test_table_rows_and_cells_read_in_order():
    html = ("<html><body><main><table>"
            + "".join("<tr>" + "".join("<td>r{}c{}</td>".format(r, c)
                                       for c in range(3)) + "</tr>"
                      for r in range(3))
            + "</table></main></body></html>")
    drawn = [t for _p, t in
             _reading_positions(html, "https://order.test/table",
                                window=100000)]
    flat = " ".join(drawn)
    for r in range(3):
        for c in range(3):
            assert "r{}c{}".format(r, c) in flat
    # Order, not just presence: cell (0,0) must precede (2,2).
    assert flat.index("r0c0") < flat.index("r1c0") < flat.index("r2c2")


# --- the property, on real pages --------------------------------------------


#: Fixtures whose reading order the PYTHON scan gets wrong, named and not
#: hidden. `suffix_definition.html` (taken from the live page, 2026-09-26):
#: text that follows an inline element -- "of length" after a math span --
#: is filed under that element by `StreamingScan`, so it reads before the
#: element's own content: 22 inversions in 55 prose lines. The live sensor
#: addresses each text node as itself and is not affected.
#: `result_cards.html` (D-36's DuckDuckGo-shaped fixture, 2026-09-27) is the
#: same defect: the crumb's " › Tessil › hat-trie" follows an inline `<span>`
#: and is filed under it, so its walk position lands after the snippet's --
#: 4 inversions in 13 prose lines, all four the crumbs.
#: `practice_rows.html` was listed here for an afternoon (2026-10-11): `doc_pos`
#: is level-order, so a block inside a table cell read as "after" the cells
#: beside it. Tables now render a row per line (`D-5`), the inversions went
#: with the cell-per-line form, and the strict marker failed as XPASS.
_KNOWN_ORDER_DEFECTS = {"suffix_definition.html", "result_cards.html"}


@pytest.mark.parametrize("path", [
    pytest.param(f, marks=pytest.mark.xfail(
        reason="StreamingScan files tail text under the preceding inline element",
        strict=True))
    if Path(f).name in _KNOWN_ORDER_DEFECTS else f
    for f in FIXTURES])
def test_fixture_reading_order_is_almost_monotone(path):
    """Inversions are allowed, but only a few and only for known reasons.

    Headings are excluded, because moving them is deliberate. What is left is
    prose, which should come out in the order the walk met it. Over the
    fixture pages plus a saved real page, prose inversions went from 42 to 8
    with the re-keying; the two that survive on `catalog.html` are a booking
    section and a pagination control that the chunker groups elsewhere.

    This is a budget rather than a zero, and it is a weak guard: it would only
    have caught the original defect on one of these fixtures. The sharp check
    is `test_the_first_list_item_is_drawn_first`, which fails outright without
    the re-keying -- see the planted-defect test below.
    """
    html = io.open(path, encoding="utf-8", errors="replace").read()
    pairs = _reading_positions(html, "file://" + path, prose_only=True)
    if len(pairs) < 4:
        pytest.skip("too little text to order")
    bad = _inversions(pairs)
    assert len(bad) <= max(2, len(pairs) // 8), (
        "{}: {} inversions in {} prose lines".format(path, len(bad),
                                                     len(pairs)))


def test_the_defect_returns_if_the_rekeying_is_removed(monkeypatch):
    """The planted defect: leave the scan's keys alone and watch a list invert.

    This is what makes the tests above worth having. `trie_doc_pos` is the
    whole fix, so replacing it with the identity reproduces the bug exactly,
    and the assertion is that the first list item stops being drawn first.
    """
    import vertiscope.trie as trie_module

    monkeypatch.setattr(trie_module, "trie_doc_pos", lambda m: dict(m))
    pairs = [(i, "body {}".format(i)) for i in range(6)]
    drawn = [t for _p, t in
             _reading_positions(_rows(pairs), "https://order.test/planted",
                                window=100000)]
    assert drawn[0] != "### Item 0", (
        "the defect did not reproduce, so the fix above is not what is "
        "keeping these tests green")
    assert "### Item 0" in drawn, "the content is present, only misplaced"
    assert drawn.index("### Item 0") > drawn.index("### Item 5")


def test_the_order_metric_can_fail():
    """Non-vacuity: a shuffled render must be caught.

    The budget above passes trivially if the measurement cannot see disorder,
    which is exactly how the original defect survived every other number in
    the suite.
    """
    pairs = [(i, "t{}".format(i)) for i in range(12)]
    assert _inversions(pairs) == []
    shuffled = [pairs[i] for i in (0, 5, 1, 9, 2, 7, 3, 11, 4, 8, 6, 10)]
    assert len(_inversions(shuffled)) >= 4
