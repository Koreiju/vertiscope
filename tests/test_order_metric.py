"""The order metric could not represent a sentence with a link in it.

`score_order` ranked a rendered line by its **owner element**, and `_owner`
strips `/text()[n]`. Every text child of one element therefore collapsed onto
a single position, taken from the first, so a paragraph was one point in the
reading order. Prose that returns to itself between inline links -- which is
what a sentence with a link in it is -- reads as an inversion at every return.

The metric consequently scored *label grouping* as perfect order and true
reading order as broken. Measured on tests/fixtures/mixed_inline.html, one
capture rendered both ways:

    label-grouped      owner-keyed  0 inversions    exact-keyed  1
    reading order      owner-keyed  3 inversions    exact-keyed  0

That is not a rounding difference, it is the sign. Correcting the live path's
ordering moved the corpus from 4,475 inversions to 29,776 by the old rank,
concentrated entirely on prose pages with inline links, while an independent
recall check over the same change fell from 1,620 unseen words to 786. Three
measures called it an improvement and this one called it a six-fold
regression, because it was reporting on itself.

The owner fallback is kept deliberately: markdown merges an anchor's href and
its words into one `[words](url)` line, so a rendered line's exact address is
one of several the page holds there. Exact first, owner second.
"""

from vertiscope.address import ContentAddress
from vertiscope.analytics.affine import score_order
from vertiscope.analytics.groundtruth import PageTruth, PageUnit

URL = "https://x.test/p"

#: A paragraph whose children alternate, in the order the page draws them.
UNITS = [
    ("/html/body/p/text()[1]", "Physics studies"),
    ("/html/body/p/a", "https://x.test/matter"),
    ("/html/body/p/a/text()[1]", "matter"),
    ("/html/body/p/text()[2]", "and"),
    ("/html/body/p/a[2]/text()[1]", "energy"),
    ("/html/body/p/text()[3]", "across space and time."),
]

TRUTH = PageTruth(
    url=URL,
    units=[PageUnit(xpath=x, kind="text", value=v, drawn=True, shadow=False)
           for x, v in UNITS],
    elements=[], shadow_hosts=[])


def addr(xpath):
    return ContentAddress(URL, xpath, "paragraph", "text()[0]|text.visible")


def scored(order):
    """`order` is a list of (xpath, text) as the renderer emitted them."""
    return score_order("page->markdown", TRUTH,
                       [addr(x) for x, _t in order],
                       texts=[t for _x, t in order])


READING = [(x, v) for x, v in UNITS]
GROUPED = [(x, v) for x, v in UNITS if "/a" not in x] + \
          [(x, v) for x, v in UNITS if "/a" in x]


# --- the sign of the answer --------------------------------------------------


def test_reading_order_is_scored_as_ordered():
    out = scored(READING)
    assert out.inversions == 0, out.sample


def test_label_grouping_is_scored_as_disordered():
    """The case the old rank called perfect."""
    assert scored(GROUPED).inversions > 0


def test_grouping_never_scores_better_than_reading_order():
    """The property that failed, stated directly. This is the whole point of
    the metric: whichever way the two are counted, the order the page draws
    must not come out worse than one that tears its links out of it."""
    assert scored(READING).inversions <= scored(GROUPED).inversions


# --- and it must still be able to fail ---------------------------------------


def test_a_reversed_render_is_caught():
    """Non-vacuity: a rank that forgave everything would pass the tests
    above, and the old one nearly did."""
    out = scored(list(reversed(READING)))
    assert out.inversions >= 4, out.inversions


def test_a_merged_anchor_line_still_finds_its_place():
    """Markdown emits `[matter](url)` as one line addressed at the anchor,
    and the page holds several units there. The owner fallback is what keeps
    that from dropping out of the count entirely."""
    order = [("/html/body/p/text()[1]", "Physics studies"),
             ("/html/body/p/a", "[matter](https://x.test/matter)"),
             ("/html/body/p/text()[2]", "and")]
    out = scored(order)
    assert out.lines == 3
    assert out.inversions == 0


def test_headings_are_left_out_of_the_count():
    """A heading is deliberately drawn with the card it labels, so counting
    it would make the number a function of page layout."""
    order = [("/html/body/p/text()[3]", "# a heading placed on purpose"),
             ("/html/body/p/text()[1]", "Physics studies")]
    assert scored(order).lines == 1
