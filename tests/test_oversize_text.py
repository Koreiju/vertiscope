"""A text node bigger than the budget is split, not dropped.

The chunker splits above the budget and merges below it, and both halves were
expressed in terms of *elements*: a node too big becomes several chunks by
recursing into its children. A text node has no children, so the recursion had
no base case and the node was never emitted at all.

Measured before the fix: 14 of 135 corpus pages, 129 reader-visible text
nodes, 326,820 characters unreachable. RFC 791 is one 94,887-character node
holding the whole document and the trie held none of it. Two adjacent arxiv
papers differed only in whether their abstract fitted -- 1,136 characters
captured, 1,789 gone.

It was worse than its share of the corpus suggests, because **the budget is
the knob the goal asks a reader to turn for a small context window**. The
failure got worse exactly as the reader asked for less: a 400-character window
lost every paragraph longer than 400 characters, silently.

Nothing that existed before could see it. The affine arrows compare against a
ground truth that walks the way the fold does; `drift` compares a sensor
against a sensor. Content *neither* side reaches is invisible to both. It took
the address-free recall check -- `innerText`, computed by layout -- to find it.

What the tests below hold, in order of what broke while writing the fix:

* the content is present at all (the original defect);
* every piece fits the budget (emitting the leaf whole recovered the text and
  left RFC 791 as one 94,887-character chunk, which is no more use to a small
  window than nothing was);
* the pieces have **distinct addresses** (the trie is keyed on address, and
  interning a single `text()@` for every piece let them overwrite each other:
  94,887 characters came back as two leaves instead of eighty);
* the pieces reassemble into the original;
* and a node that fits is still exactly one leaf, or the fix has started
  shredding ordinary paragraphs.

    VERTISCOPE_LIVE=1 python -m pytest tests/test_oversize_text.py -q
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
FIXTURE = ROOT / "tests" / "fixtures" / "oversize_text.html"
URI = FIXTURE.resolve().as_uri()

LIVE = pytest.mark.skipif(
    not os.environ.get("VERTISCOPE_LIVE"),
    reason="needs a real browser; set VERTISCOPE_LIVE=1")

#: Deliberately small, so the fixture's 2,315-character node splits into
#: several pieces rather than two. A budget a reader might actually choose for
#: a small model is this size or smaller, which is the case that used to lose
#: the most.
BUDGET = 300


@pytest.fixture(scope="module")
def captured():
    with browser_session(load_config()) as driver:
        driver.get(URI)
        time.sleep(0.9)
        sensor = Sensor(driver, URI, budget=BUDGET)
        sensor.boot()
        time.sleep(0.5)
        spine = StreamingScan(URI, context_window=BUDGET)
        for _ in range(6):
            snap = sensor.drain(1)
            spine.absorb(snap.units, snap.passno,
                         removed=snap.removed_addresses,
                         moved=snap.moved_addresses)
            if snap.settled and not snap.units:
                break
            time.sleep(0.2)
        yield [(leaf.address, leaf.value or "")
               for leaf in spine.trie.leaves() if leaf.address]


def long_pieces(captured):
    return [(a, v) for a, v in captured if "Paragraph token" in v]


# --- the defect itself -------------------------------------------------------


@LIVE
def test_the_oversize_node_reaches_the_trie_at_all(captured):
    assert long_pieces(captured), "a node larger than the budget vanished"


@LIVE
def test_its_first_and_last_words_are_both_present(captured):
    """Not merely a prefix. Emitting only what fits would pass the test above
    and still lose most of the paragraph."""
    text = " ".join(v for _a, v in long_pieces(captured))
    assert "Paragraph token 1 " in text
    assert "Paragraph token 25" in text


# --- and the budget it was supposed to respect -------------------------------


@LIVE
def test_no_piece_overruns_the_budget(captured):
    """Recovering the content by emitting one huge chunk is not the fix. A
    94,887-character chunk is no more use to a small window than nothing."""
    too_big = [len(v) for _a, v in long_pieces(captured) if len(v) > BUDGET]
    assert not too_big, too_big


@LIVE
def test_the_pieces_have_distinct_addresses(captured):
    """The trie is keyed on address. One interned `text()@` for every piece
    let them overwrite each other, and 94,887 characters came back as two
    leaves instead of eighty."""
    pieces = long_pieces(captured)
    keys = {(a.xpath, a.accessor) for a, _v in pieces}
    assert len(keys) == len(pieces)


@LIVE
def test_a_split_piece_carries_its_offset(captured):
    """The `@offset` form already existed -- `data-mw@496` names one match
    inside a longer attribute -- so the pieces reuse it rather than inventing
    a second scheme for the same idea."""
    accessors = [a.accessor or "" for a, _v in long_pieces(captured)]
    assert any("text()@" in acc for acc in accessors), accessors[:4]


@LIVE
def test_the_pieces_reassemble_into_the_original(captured):
    """Split at a space near the boundary, so a piece ends between words.
    Whitespace at the seams is the only thing allowed to differ."""
    joined = " ".join(v for _a, v in sorted(
        long_pieces(captured), key=lambda pair: len(pair[1]) and pair[0].accessor))
    for n in (1, 7, 13, 19, 25):
        assert "Paragraph token %d " % n in joined + " "


# --- the guard ---------------------------------------------------------------


@LIVE
def test_a_node_that_fits_is_still_one_leaf(captured):
    """Or the fix has started shredding ordinary paragraphs."""
    short = [v for _a, v in captured if "short paragraph that fits" in v]
    assert len(short) == 1, short
