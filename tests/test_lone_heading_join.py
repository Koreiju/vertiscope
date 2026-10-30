"""A heading cut from what it heads joins it (`G-86`, `_attach_lone_headings`).

The descent cuts per subtree, so a heading that is a SIBLING of what it heads
came out alone (Python's `### Functions` over its `<dl>`: 11 + 218 tokens).
Joined when it heads the next chunk and the two stay under the lenient bound;
kept apart when the next chunk opens a section at its level or above, or the
join would pass the bound. Planted `PLANT_LONE_HEADING_KEPT_APART`."""

from domvec import markdown as M
from domvec.address import ContentAddress
from domvec.markdown import MarkdownChunk, MarkdownLine


def _chunk(xpath, *texts):
    c = MarkdownChunk(url="https://t.test/p", xpath=xpath)
    for k, t in enumerate(texts):
        c.lines.append(MarkdownLine(depth=0, text=t, address=ContentAddress("https://t.test/p", "%s/x[%d]" % (xpath, k + 1), "text.prose", "text")))
    return c


def test_a_heading_joins_what_it_heads():
    h = _chunk("/html/body/section/h3", "### Functions")
    body = _chunk("/html/body/section/dl", "- compile(pattern) -- compile a pattern", "- search(pattern, s)")
    out = M._attach_lone_headings([h, body], 256)
    assert len(out) == 1 and out[0].lines[0].text == "### Functions"
    assert out[0].xpath == "/html/body/section"


def test_a_heading_over_a_sibling_section_stays():
    a = _chunk("/html/body/h2", "## Alpha")
    b = _chunk("/html/body/h2[2]", "## Beta", "text")
    assert len(M._attach_lone_headings([a, b], 256)) == 2


def test_the_bound_keeps_it_apart():
    h = _chunk("/html/body/h3", "### Big")
    body = _chunk("/html/body/p", "word " * 500)
    assert len(M._attach_lone_headings([h, body], 256)) == 2


def test_planted_kept_apart():
    h = _chunk("/html/body/section/h3", "### Functions")
    body = _chunk("/html/body/section/dl", "- compile(pattern)")
    M.PLANT_LONE_HEADING_KEPT_APART = True
    try:
        assert len(M._attach_lone_headings([h, body], 256)) == 2
    finally:
        M.PLANT_LONE_HEADING_KEPT_APART = False


def test_a_heading_with_its_permalink_still_joins():
    """Live, the store kept `### Functions` + `[¶](#functions)` apart from its
    <dl>: a permalink heads nothing, so the pair is still a heading alone."""
    h = _chunk("/html/body/section/h3", "### Functions", "[¶](#functions)")
    body = _chunk("/html/body/section/dl", "- compile(pattern)")
    out = M._attach_lone_headings([h, body], 256)
    assert len(out) == 1 and out[0].lines[-1].text == "- compile(pattern)"
