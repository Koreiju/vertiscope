"""The trie holds what the page presents to a reader, and not the bookkeeping.

Five separate over-captures were found in one session, each on a different
real page, each by diffing a trie against ground truth and reading the values:

* `<link>` in the body -- 377 Parsoid category references on one Wikipedia
  article, zero area, machine-only;
* `input[type=hidden]` -- 422 on one openlibrary page, each drawing a
  placeholder line claiming there was a control to interact with;
* `role="presentation"` -- 155 on one eurostat page, a value that is the word
  "presentation", from an attribute whose entire meaning is *this element has
  no semantics*;
* `data-mw` and its kind -- 106 on one es.wikipedia page, urls mined out of a
  serialized template payload while the citation's real link sat a few nodes
  away;
* and the opposite error, `<svg>` folded whole -- 2,447 `<text>` elements and
  14,037 characters of SQL grammar on sqlite.org that never reached the trie
  at all.

They are one principle, stated once: **the trie holds an address per thing the
page presents to a reader.** Machine bookkeeping does not belong in that
address space, and content a reader can see must not be folded out of it.

Finding them one at a time took most of a day. This fixture carries every form
on one page, so a regression in any of them fails a single test -- and so the
principle is written down somewhere executable rather than only in five commit
messages.

Both halves are asserted throughout. A rule that only removed things would
pass every exclusion here and quietly gut the page, which is why each
exclusion is paired with the reader-visible content nearest to it.

    VERTISCOPE_LIVE=1 python -m pytest tests/test_metadata_family.py -q
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
FIXTURE = ROOT / "tests" / "fixtures" / "metadata_family.html"
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


def values(captured):
    return {v for _a, v in captured}


def paths(captured):
    return {a.xpath for a, _v in captured}


# --- what must stay out ------------------------------------------------------


@LIVE
def test_a_body_link_is_not_content(captured):
    assert "./Category:Machine_only" not in values(captured)


@LIVE
def test_a_head_stylesheet_is_not_content(captured):
    assert "/head/stylesheet.css" not in values(captured)


@LIVE
def test_a_hidden_input_claims_no_control(captured):
    """Its *value* may be captured -- a hidden field's content is content.
    What must not appear is the placeholder asserting a control is there."""
    at_hidden = [a for a, _v in captured
                 if a.xpath.endswith("/input") and "@control" in (a.accessor or "")]
    assert not at_hidden


@LIVE
def test_a_presentational_role_is_not_a_value(captured):
    assert "presentation" not in values(captured)


@LIVE
def test_a_serialized_payloads_urls_are_not_mined(captured):
    assert not any("payload.test" in v for v in values(captured))


@LIVE
def test_an_icon_is_still_one_picture(captured):
    inside = [p for p in paths(captured) if "svg" in p and "path" in p]
    assert not inside, inside[:3]


# --- and what must stay in ---------------------------------------------------
#
# Paired deliberately. A rule that only removed things would pass every test
# above and take the page with it.


@LIVE
def test_the_prose_survives(captured):
    assert any("Readable prose" in v for v in values(captured))


@LIVE
def test_a_real_field_survives(captured):
    assert "a real field" in values(captured)


@LIVE
def test_a_real_link_survives(captured):
    assert "/reader/destination" in values(captured)
    assert "link" in {a.tag for a, v in captured if v == "/reader/destination"}


@LIVE
def test_text_inside_a_presentational_wrapper_survives(captured):
    """`role="presentation"` describes the element, not its contents."""
    assert any("Decorative wrapper text" in v for v in values(captured))


@LIVE
def test_the_citation_text_survives_its_payload_attribute(captured):
    assert any("Citation text a reader sees" in v for v in values(captured))


@LIVE
def test_a_diagrams_label_reaches_the_trie(captured):
    assert "GRAMMAR-LABEL" in values(captured)


@LIVE
def test_the_diagram_is_still_named(captured):
    assert "a named diagram" in values(captured)
