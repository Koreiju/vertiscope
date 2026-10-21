"""A picture is folded; a diagram is not.

An inline `<svg>` is in `FOLDED`, so the fold renders it as one media
reference and does not descend. That is right for an icon: a page carrying two
hundred `<path>` elements should not turn each into content.

It is wrong for a diagram whose labels are the document.
`sqlite.org/lang_select.html` holds 139 svgs with 2,447 `<text>` elements and
14,037 characters -- the SQL grammar, drawn as railroad diagrams -- and not one
address of it reached the trie. Capture recall on that page was 37.9%: a
reader got the prose around the diagrams and none of the grammar.

The rule is now narrow: an svg is a picture unless it contains `<text>`.
Descent is by the ordinary path rather than a targeted query, so the addresses
are the composed tree's and match ground truth by construction.

Both halves are asserted, because the guard is what keeps this from becoming
over-capture -- the failure this codebase already has a name for, DuckDuckGo's
region filter putting eighty option lines ahead of the first result.
Structurally faithful is not the same as useful.

    VERTISCOPE_LIVE=1 python -m pytest tests/test_svg_capture.py -q
"""

import os
import pathlib
import time

import pytest

from vertiscope.browser import browser_session
from vertiscope.config import load_config
from vertiscope.sensing import Sensor
from vertiscope.stream import StreamingScan

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "svg_diagram.html"
URI = FIXTURE.resolve().as_uri()

LIVE = pytest.mark.skipif(
    not os.environ.get("VERTISCOPE_LIVE"),
    reason="needs a real browser; set VERTISCOPE_LIVE=1")

LABELS = ("SELECT", "result-column", "FROM", "table-or-subquery")


@pytest.fixture(scope="module")
def captured():
    with browser_session(load_config()) as driver:
        driver.get(URI)
        time.sleep(1.0)
        sensor = Sensor(driver, URI, budget=1200)
        sensor.boot()
        time.sleep(0.5)
        spine = StreamingScan(URI, context_window=1200)
        for _ in range(5):
            snap = sensor.drain(1)
            spine.absorb(snap.units, snap.passno,
                         removed=snap.removed_addresses,
                         moved=snap.moved_addresses)
            if snap.settled and not snap.units:
                break
            time.sleep(0.2)
        yield [(leaf.address, leaf.value or "")
               for leaf in spine.trie.leaves() if leaf.address]


@LIVE
def test_a_diagrams_labels_reach_the_trie(captured):
    values = {value for _address, value in captured}
    for label in LABELS:
        assert label in values, "{!r} never reached the trie".format(label)


@LIVE
def test_they_are_addressed_by_the_composed_path(captured):
    """Not by a targeted query that would invent its own addressing.

    Ground truth addresses these at `.../svg[2]/text[n]/text()[1]`. Anything
    else and the coverage arrows would score correct capture as invention.
    """
    hit = [a for a, v in captured if v == "SELECT"]
    assert hit, "the first label is missing"
    assert "/svg" in hit[0].xpath and "/text" in hit[0].xpath


@LIVE
def test_an_icon_is_still_one_picture(captured):
    """The guard. Without it every path and circle is walked for nothing."""
    inside_icon = [a for a, _v in captured
                   if "/svg/" in a.xpath and "path" in a.xpath]
    assert not inside_icon, "descended into a picture: {}".format(
        [a.xpath for a in inside_icon][:3])


@LIVE
def test_geometry_in_a_diagram_draws_no_lines(captured):
    """Descending for the labels does not mean drawing the drawing.

    The diagram holds a <rect> and a <path> beside its text. Walking them is
    the cost; emitting them would be the defect.
    """
    geometry = [a for a, _v in captured
                if a.xpath.rstrip("0123456789[]").endswith(("rect", "path",
                                                            "circle"))]
    assert not geometry, [a.xpath for a in geometry][:3]


@LIVE
def test_the_prose_around_the_diagram_is_unaffected(captured):
    """Non-vacuity from the other side: the page still reads as a page."""
    values = {value for _address, value in captured}
    assert any("statement is written" in v for v in values)
    assert any("names a production" in v for v in values)
