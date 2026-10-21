"""`<link>` is metadata, and the trie is not where metadata goes.

`<link>` is *metadata content* by the HTML spec. Its href is a machine
reference -- a stylesheet, a canonical url, a category -- and no reader sees
one. Wikipedia's Parsoid output puts 377 of them in the **body** of a single
article, `rel="mw:PageProp/Category"`, every one of zero area, and capturing
their hrefs put 377 addresses per page into the trie that nobody can reach.

Across the corpus that was most of 4,083 invented capture addresses: capture
precision 98.90% -> 99.69%, markdown 99.06% -> 99.88%, and on the worst page
714 invented down to 2.

This is the `<svg>` case in reverse. Folding the svg **lost** a page's
content; capturing `<link>` **gained** noise. Both ask the same question --
is this something the page shows a reader -- and the sensor answered it wrong
in opposite directions, so both halves are asserted here: the metadata stays
out, and everything that carries an href for a reader stays in.

A rule that only removed things would pass the first assertion and destroy
the page.

    VERTISCOPE_LIVE=1 python -m pytest tests/test_link_metadata.py -q
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
FIXTURE = ROOT / "tests" / "fixtures" / "link_metadata.html"
URI = FIXTURE.resolve().as_uri()

LIVE = pytest.mark.skipif(
    not os.environ.get("VERTISCOPE_LIVE"),
    reason="needs a real browser; set VERTISCOPE_LIVE=1")


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
def test_no_link_element_reaches_the_trie(captured):
    at_link = [a.xpath for a, _v in captured
               if a.xpath.rstrip("0123456789[]").endswith("link")]
    assert not at_link, "metadata captured as content: {}".format(at_link[:3])


@LIVE
def test_not_even_one_buried_in_the_body(captured):
    """The Parsoid shape: a <link> inside a <span> inside a list item."""
    values = {v for _a, v in captured}
    assert "#cite_ref-buried" not in values


@LIVE
def test_a_category_href_is_not_content(captured):
    values = {v for _a, v in captured}
    assert not any(v.startswith("./Category:") for v in values)


@LIVE
def test_the_head_stylesheet_and_canonical_stay_out(captured):
    values = {v for _a, v in captured}
    assert "/style/main.css" not in values
    assert "https://example.test/canonical-target" not in values


# --- and the half that keeps this from deleting the page ---------------------


@LIVE
def test_an_anchors_href_is_still_captured(captured):
    """The guard. A rule that only removed things would pass every test above
    and take the page's links with it."""
    values = {v for _a, v in captured}
    assert "/real/destination" in values


@LIVE
def test_the_anchor_is_still_drawn_as_a_link(captured):
    """Not merely present: presented as something a reader can follow."""
    tags = {a.tag for a, v in captured if v == "/real/destination"}
    assert "link" in tags


@LIVE
def test_the_prose_is_untouched(captured):
    values = {v for _a, v in captured}
    assert any("prose a reader can see" in v for v in values)
    assert any("real link" in v for v in values)
