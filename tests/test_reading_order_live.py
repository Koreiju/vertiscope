"""Reading order on the *live* path, which had no order check at all.

`test_reading_order.py` covers the snapshot path, and covers it well: it
found the re-keying defect that drew the first item of every repeated group
at the bottom of its group. Every one of its measurements goes through
`StreamingScan.push`, which tags the html and supplies a walk-position map.

The sensor path supplies no map, and nobody had ever asked what it does
without one. The answer was label grouping: `insert` gave a node's children
a position by *label group* -- every text child, then every anchor child --
which is right for siblings sharing a label and wrong for a parent whose
children alternate. A sentence with a link in it is exactly that parent.

    page    Physics studies [matter] and [energy] across space and time.
    trie    "Physics studies" / "and" / "across" / "and time."
            then [matter] / [energy] / "space"

The two paths are meant to produce the same chunks. On
tests/fixtures/mixed_inline.html they produced different sentences, and the
one that ships was the wrong one.

Nothing could see it. Coverage compares address sets, dedup compares values,
drift compares a sensor against a sensor; sequence appears in none of them.
It surfaced through the address-free recall check, which counted `에너지나` on
ko.wikipedia as unseen -- that run exists only when a link's text and the
text node following it are adjacent, so a reordering is precisely the defect
it shows up as. 352 such words on zh.wikipedia, 198 on ko, all present in the
trie and all in the wrong place.

The fix is to observe the order instead of deriving it: the fold walks the
DOM recursively and `sensing._decode` hands the units over in that order, so
`insert` stamps each newly met node with the next value of a counter.

    VERTISCOPE_LIVE=1 python -m pytest tests/test_reading_order_live.py -q
"""

import os
import pathlib
import time

import pytest

from vertiscope.address import ContentAddress
from vertiscope.trie import AddressTrie

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "mixed_inline.html"
URI = FIXTURE.resolve().as_uri()

LIVE = pytest.mark.skipif(
    not os.environ.get("VERTISCOPE_LIVE"),
    reason="needs a real browser; set VERTISCOPE_LIVE=1")

URL = "https://x.test/p"


def addr(xpath, accessor="text()[0]|text.visible"):
    return ContentAddress(URL, xpath, "paragraph", accessor)


#: A paragraph whose children alternate: text, link, text, link, text. Given
#: in the order the page draws them, which is the order the fold delivers.
SENTENCE = [
    ("/html/body/p/text()[1]", "Physics studies"),
    ("/html/body/p/a/text()[1]", "matter"),
    ("/html/body/p/text()[2]", "and"),
    ("/html/body/p/a[2]/text()[1]", "energy"),
    ("/html/body/p/text()[3]", "across space and time."),
]


# --- the defect, with no browser needed --------------------------------------


def test_alternating_children_come_back_in_the_order_they_arrived():
    """Label grouping emitted all three text nodes and then both links."""
    trie = AddressTrie()
    for xpath, value in SENTENCE:
        trie.insert(addr(xpath), value)
    assert [leaf.value for leaf in trie.leaves()] == [v for _x, v in SENTENCE]


def test_a_later_repair_does_not_reorder_what_did_not_change():
    """Only a node's *first* arrival fixes its position. Re-offering a value
    is what every drain does, and if that re-stamped the counter a page would
    reorder itself simply by being watched."""
    trie = AddressTrie()
    for xpath, value in SENTENCE:
        trie.insert(addr(xpath), value)
    trie.insert(addr(SENTENCE[0][0]), "Physics studies")   # unchanged re-offer
    trie.insert(addr(SENTENCE[2][0]), "und")               # an edit
    assert [leaf.value for leaf in trie.leaves()] == [
        "Physics studies", "matter", "und", "energy", "across space and time."]


def test_same_label_siblings_are_still_in_index_order():
    """The property the old derivation did get right, kept. `_seg_key` used
    to order these numerically so `li[10]` followed `li[2]`; arrival order
    has to agree, or the fix trades one inversion for another."""
    trie = AddressTrie()
    for n in range(1, 13):
        trie.insert(addr("/html/body/ul/li[%d]/text()[1]" % n), "item %d" % n)
    assert [leaf.value for leaf in trie.leaves()] == [
        "item %d" % n for n in range(1, 13)]


def test_a_supplied_map_still_wins():
    """Arrival order is the fallback, not a replacement. The snapshot path
    observes the walk directly and must keep doing so -- it is the path
    `test_reading_order.py` measures."""
    trie = AddressTrie()
    positions = {"/html/body/p/b": 0, "/html/body/p/a": 1}
    trie.insert(addr("/html/body/p/a/text()[1]"), "second", doc_pos=positions)
    trie.insert(addr("/html/body/p/b/text()[1]"), "first", doc_pos=positions)
    assert [leaf.value for leaf in trie.leaves()] == ["first", "second"]


def test_the_order_can_still_be_wrong():
    """Non-vacuity. Arrival order records what it is given, so a caller that
    delivers out of order is reported out of order rather than tidied -- the
    check has to be able to fail or it measures nothing."""
    trie = AddressTrie()
    for xpath, value in reversed(SENTENCE):
        trie.insert(addr(xpath), value)
    assert [leaf.value for leaf in trie.leaves()] != [v for _x, v in SENTENCE]


# --- and against a real page -------------------------------------------------


@LIVE
def test_the_sentence_survives_the_round_trip():
    from vertiscope.analytics.drift import _settle
    from vertiscope.browser import browser_session
    from vertiscope.config import load_config
    from vertiscope.markdown import render_trie
    from vertiscope.sensing import Sensor
    from vertiscope.stream import StreamingScan

    with browser_session(load_config()) as driver:
        driver.get(URI)
        time.sleep(0.9)
        sensor = Sensor(driver, URI, budget=1200)
        sensor.boot()
        time.sleep(0.5)
        spine = StreamingScan(URI, context_window=1200)
        _settle(sensor, spine)
        out = render_trie(spine.trie)
        chunks = out[0] if isinstance(out, tuple) else out
        lines = [getattr(ln, "text", str(ln))
                 for c in chunks for ln in c.lines]

    body = " ".join(lines)
    # Sequence, not mere presence: each word after the one before it.
    for earlier, later in zip(
            ["Physics studies", "matter", "and", "energy", "across"],
            ["matter", "and", "energy", "across", "and time."]):
        assert body.index(earlier) < body.index(later), (earlier, later, body)
