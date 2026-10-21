"""The harness's own metrics, including the ones that exist to catch it lying.

`drift` scores the repaired trie against a fresh map of the same page. Two
things can make that score meaningless without making it look wrong, and both
happened before they were measured:

* **The gesture did nothing.** `www.w3schools.com/html/html_forms.asp` scored
  0 stale on a run whose deletion removed a `DIV` holding no addresses, and 9
  stale on the next run of the same gesture. The first was not a pass. Five
  pages in one corpus arm were in that state, and the arm's headline read 115
  of 117 instead of 110 of 112.
* **The page moved by itself.** Ad-sync iframes on one page, a price ticker on
  another. Residue that the sensor never caused.

`footprint` answers the first and `floor` plus the `_net` figures answer the
second. Both are measurements about the measurement, so both need tests that
fail when they stop discriminating -- a vacuity detector that cannot detect
vacuity is worse than none, because it certifies.

These are pure functions over maps, so none of this needs a browser.
"""

import pytest

from vertiscope.analytics.drift import _score
from vertiscope.analytics.stability import _diff


class _Address:
    def __init__(self, key):
        self._key = key

    def key(self):
        return self._key


class _Leaf:
    def __init__(self, key, value):
        self.address = _Address(key) if key is not None else None
        self.value = value


class _Trie:
    """Just enough of an AddressTrie for `_score`: leaves with addresses."""

    def __init__(self, mapping):
        self._leaves = [_Leaf(k, v) for k, v in mapping.items()]

    def leaves(self):
        return self._leaves


def score(mine, theirs, before=None, unstable=frozenset()):
    return _score(_Trie(mine), _Trie(theirs), before=before, unstable=unstable)


# --- footprint: did the gesture ask the trie anything? ----------------------


def test_a_gesture_that_changed_nothing_has_no_footprint():
    """The signal that a page could not have failed."""
    page = {"a": "1", "b": "2"}
    assert score(page, page, before=page)["footprint"] == 0


def test_a_deletion_footprint_counts_the_addresses_that_left():
    before = {"a": "1", "b": "2", "c": "3"}
    after = {"a": "1", "b": "2"}
    assert score(after, after, before=before)["footprint"] == 1


def test_an_edit_has_a_footprint_although_no_address_moved():
    """The case a count difference gets wrong.

    `edit` changes a value and no addresses at all, so `len(before)` and
    `len(after)` agree by design. Measured by count, every edit in the corpus
    would have been discarded as a gesture that did nothing.
    """
    before = {"a": "1", "b": "2"}
    after = {"a": "1", "b": "CHANGED"}
    assert len(before) == len(after)            # the naive measure sees zero
    assert score(after, after, before=before)["footprint"] == 1


def test_a_relocation_has_a_footprint_although_the_count_is_equal():
    """The other case a count difference gets wrong.

    One sibling moving to the end of its group changes which addresses exist
    without changing how many.
    """
    before = {"ol/li": "x", "ol/li[2]": "y"}
    after = {"ol/li": "y", "ol/li[2]": "x"}
    assert len(before) == len(after)
    # Both addresses hold the other's content now: two value changes.
    assert score(after, after, before=before)["footprint"] == 2


def test_footprint_is_absent_rather_than_zero_when_it_was_not_measured():
    """A missing measurement must not read as `nothing happened`."""
    assert score({"a": "1"}, {"a": "1"})["footprint"] is None


# --- floor: did the page move by itself? ------------------------------------


def test_a_residue_at_an_address_the_page_moved_is_discounted():
    mine = {"a": "1", "/html/iframe[2]": "beacon-one"}
    theirs = {"a": "1"}
    out = score(mine, theirs, unstable={"/html/iframe[2]"})
    assert out["fp"] == 1                 # the raw score still reports it
    assert out["fp_net"] == 0             # ...and the net score does not


def test_a_residue_where_the_page_held_still_is_not_discounted():
    """The whole point: the floor is subtracted by name, not by size.

    A page can move eight addresses and still have a real defect at a ninth.
    Comparing a residue count against a floor count would forgive it.
    """
    moving = {f"/html/iframe[{i}]" for i in range(8)}
    mine = {"a": "1", "stable/defect": "left over"}
    theirs = {"a": "1"}
    out = score(mine, theirs, unstable=moving)
    assert out["floor"] == 8
    assert out["fp"] == 1 and out["fp_net"] == 1


def test_a_lost_address_is_discounted_only_if_the_page_moved_it():
    theirs = {"a": "1", "b": "2"}
    mine = {"a": "1"}
    assert score(mine, theirs, unstable={"b"})["fn_net"] == 0
    assert score(mine, theirs, unstable=frozenset())["fn_net"] == 1


def test_a_wrong_value_at_a_moving_address_is_discounted():
    mine = {"tick": "10.10"}
    theirs = {"tick": "10.42"}
    out = score(mine, theirs, unstable={"tick"})
    assert out["value_wrong"] == 1 and out["value_wrong_net"] == 0


def test_with_nothing_moving_the_net_score_is_the_raw_score():
    """Non-vacuity from the other side: the discount must be able to do
    nothing, or it is subtracting something it should not."""
    mine = {"a": "1", "b": "wrong", "stale": "x"}
    theirs = {"a": "1", "b": "right", "lost": "y"}
    out = score(mine, theirs)
    assert (out["fp"], out["fn"], out["value_wrong"]) == \
           (out["fp_net"], out["fn_net"], out["value_wrong_net"])


# --- the floor measurement itself -------------------------------------------


def test_a_page_that_holds_still_has_no_floor():
    page = {"a": "1", "b": "2"}
    assert _diff(page, page)["floor"] == 0


def test_address_churn_and_value_churn_are_counted_apart():
    """They are different page behaviours -- an iframe appearing is not a
    ticker changing -- and one number would hide which."""
    first = {"a": "1", "gone": "x"}
    second = {"a": "CHANGED", "new": "y"}
    out = _diff(first, second)
    assert out["address_churn"] == 2      # `gone` left, `new` arrived
    assert out["value_churn"] == 1        # `a` changed
    assert out["floor"] == 3


def test_the_floor_says_where_the_motion_is():
    """Twice the location was the entire answer, so a floor without one
    invites the assumption that motion is spread evenly over the page."""
    first = {"/html/iframe": "beacon", "p": "text"}
    second = {"/html/iframe[2]": "beacon", "p": "text"}
    assert _diff(first, second)["iframe_share"] == 2


@pytest.mark.parametrize("second,expected", [
    ({"a": "1"}, 0),
    ({"a": "2"}, 1),
    ({}, 1),
    ({"a": "1", "b": "2"}, 1),
])
def test_the_floor_moves_with_the_page(second, expected):
    """A floor that cannot rise is a floor that certifies every page as
    still, which is exactly the failure it exists to prevent."""
    assert _diff({"a": "1"}, second)["floor"] == expected
