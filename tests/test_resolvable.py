"""The one oracle that shares no assumption with the fold, and its own bugs.

`drift` compares a sensor against a second sensor: self-consistency, and a
systematic mis-reading present in both is invisible to it. The affine arrows
compare against `groundtruth`, a separate implementation that deliberately
shares the *addressing convention*, because two maps that address differently
cannot be compared at all -- and an error in the convention itself is
invisible to both tiers. One was: ground truth counted only non-empty text
children when assigning `text()[n]`, so both maps were internally consistent
and both wrong about where a text node lives.

`document.evaluate` is the third tier. The page resolves an address or it does
not, and nothing the fold and the walk share can influence the answer.

Being independent does not make the checker correct. This one was wrong four
times in one sitting, each time making the map look broken, each caught by
reading samples before a number was reported:

    619 of 1,581 mismatched   an href compared against the element's text
     69 synthetic             @control treated as content the page holds
     37 unresolvable          <svg> and <math>: real, but outside the
                              namespace plain xpath can reach
     40 mismatched            a whole value against a truncated window

All four are planted below, and the last three tests make sure the check can
still fail -- a verdict that forgave everything would pass the first seven.
"""

from vertiscope.analytics.resolvable import _attribute_of, _is_foreign, verdict


# --- where an address says its value lives -----------------------------------


def test_an_attribute_accessor_names_its_attribute():
    assert _attribute_of("href|link.anchor/link") == "href"


def test_a_text_accessor_names_no_attribute():
    assert _attribute_of("text()[0]|text.visible/generic") == ""


def test_a_match_inside_an_attribute_still_names_the_attribute():
    """`data-mw@496` is one url found at an offset inside one attribute."""
    assert _attribute_of("data-mw@496|text.visible/generic") == "data-mw"


def test_a_synthetic_annotation_names_nothing_resolvable():
    assert _attribute_of("@control|search.queryform/searchbox") == "@"


def test_a_foreign_step_is_recognised_anywhere_in_the_path():
    assert _is_foreign("/html/body/svg/text/text()[1]")
    assert _is_foreign("/html/body/p/math/mrow/mn[2]/text()[1]")
    assert not _is_foreign("/html/body/div/p/text()[1]")


# --- the four ways this check has been wrong ---------------------------------


def test_an_href_is_not_compared_against_element_text():
    """The 619-mismatch bug: the address resolved to exactly the right
    element, and the value simply lives in an attribute of it."""
    assert verdict("href", "resolved", "https://x.test/a",
                   "https://x.test/a", "/html/body/a") == "resolved"


def test_a_synthetic_annotation_is_never_a_mismatch():
    """`@control` carries the sensor's own classification. Nothing in the
    page corresponds to it, so it is not evidence in either direction."""
    assert verdict("@", "resolved", "button", "",
                   "/html/body/form/input") == "synthetic"


def test_a_foreign_namespace_node_is_not_a_wrong_address():
    """An <svg> or <math> node is real, and plain xpath cannot reach it.
    That is a fact about the address scheme, not a defect in the address."""
    assert verdict("", "unresolvable", "GRAMMAR", "",
                   "/html/body/svg/text/text()[1]") == "foreign"


def test_a_long_value_is_compared_by_prefix():
    """The page's side arrives truncated. Wikipedia's COinS metadata agreed
    for every character either side could show and was called a mismatch."""
    want = "ctx_ver=Z39.88-2004&" + ("x" * 500)
    assert verdict("title", "resolved", want, want[:400],
                   "/html/body/span") == "resolved"


# --- and it must still be able to fail ---------------------------------------


def test_a_genuinely_different_value_is_a_mismatch():
    assert verdict("href", "resolved", "https://a.test",
                   "https://b.test", "/html/body/a") == "mismatched"


def test_an_address_naming_nothing_outside_a_foreign_subtree_is_reported():
    """Or the foreign bucket forgives everything and measures nothing."""
    assert verdict("", "unresolvable", "x", "",
                   "/html/body/div/gone") == "unresolvable"


def test_an_empty_value_resolves_rather_than_mismatching():
    """Nothing recorded is nothing to contradict."""
    assert verdict("", "resolved", "", "anything",
                   "/html/body/p") == "resolved"
