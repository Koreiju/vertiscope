"""R-K1: every level of indentation in a chunk holds a line.

`_level_page` levels each chunk from its own lines' parents; the measure
(`vertiscope.analytics.levels.gaps`) must SEE an empty level, or a 0 means nothing.
"""

from vertiscope import markdown
from vertiscope.address import ContentAddress
from vertiscope.analytics.levels import gaps, score
from vertiscope.markdown import MarkdownChunk, MarkdownLine, _level_page


def _chunk(depths, url="https://example.org/", root="/html/body"):
    lines = []
    for i, d in enumerate(depths):
        xp = root + "/div" * (d + 1) + "/p[%d]" % (i + 1)
        lines.append(MarkdownLine(depth=d, text="line %d" % i,
                                  address=ContentAddress(url=url, xpath=xp, tag="text.p", accessor="text")))
    return MarkdownChunk(url=url, xpath=root, lines=lines)


def test_the_measure_sees_an_empty_level():
    # Non-vacuity: a line two steps under its parent, and a chunk off the margin.
    assert gaps([0, 1, 1, 0]) == (0, 0)
    assert gaps([0, 2]) == (1, 0)
    assert gaps([3, 4, 6, 4]) == (1, 3)


def test_levelling_removes_every_gap_and_keeps_nesting():
    chunk = _chunk([4, 6, 6, 9, 6, 4, 5])
    _level_page([chunk])
    got = [ln.depth for ln in chunk.lines]
    assert got == [0, 1, 1, 2, 1, 0, 1]
    assert gaps(got) == (0, 0)


def test_each_chunk_levelled_from_its_own_lines():
    # Depth 5 branches in the first chunk and is a lone wrapper in the second:
    # the page-wide mapping kept it in both, so the second chunk spent an
    # empty level on it. Per chunk, neither does.
    a, b = _chunk([3, 5, 5]), _chunk([3, 7])
    _level_page([a, b])
    assert [ln.depth for ln in b.lines] == [0, 1]
    assert score([a, b])["with_gap"] == 0


def test_planted_page_levels_leave_the_gap():
    a, b = _chunk([3, 5, 5]), _chunk([3, 7])
    was = markdown.PLANT_PAGE_LEVELS
    markdown.PLANT_PAGE_LEVELS = True
    try:
        _level_page([a, b])
    finally:
        markdown.PLANT_PAGE_LEVELS = was
    # Page depths {3, 5, 7} -> {0, 1, 2}: chunk b draws 0 then 2.
    assert [ln.depth for ln in b.lines] == [0, 2]
    assert score([a, b])["with_gap"] == 1


def test_a_contentless_line_folds_into_a_worded_line_of_its_element():
    # R-K2a: `![]` and the worded line at the SAME element -> one line, the mark's
    # address kept as an inline address (counted by `covered`). Planted: two lines.
    from vertiscope.markdown import _fold_contentless
    url = "https://example.org/"
    img = ContentAddress(url=url, xpath="/html/body/figure/img", tag="media.images", accessor="text()")
    cap = ContentAddress(url=url, xpath="/html/body/figure/img", tag="text.accessible", accessor="@alt")
    lone = ContentAddress(url=url, xpath="/html/body/svg", tag="media.images", accessor="text()")
    lines = [MarkdownLine(depth=0, text="![]", address=img), MarkdownLine(depth=0, text="A grazing okapi", address=cap),
             MarkdownLine(depth=0, text="![]", address=lone)]
    out = _fold_contentless(lines)
    assert [ln.text for ln in out] == ["A grazing okapi", "![]"]      # the lone svg mark stays
    assert img in out[0].inline
    chunk = MarkdownChunk(url=url, xpath="/html/body", lines=out)
    assert img.key() in chunk.covered
