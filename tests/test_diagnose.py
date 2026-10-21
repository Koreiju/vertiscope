"""The diagnostic must agree with the metric about what counts as invented.

Every capture class resolved today came from diffing one page's trie against
its ground truth. The diff was written ad hoc each time as a raw set
difference, and that is where it went wrong: `score_arrow` allows a match when
the address's owner is a truth owner or a truth ancestor, so a raw diff reports
differences the metric has already forgiven.

Used that way it produced 115 invented and 115 lost on one page, and an
account of roughly 230 corpus errors, for a change that moved the corpus
totals by nothing: 727 and 563 before and after.

So the tests here are about the split, not about finding anything. If
`charged` ever stops matching `score_arrow`'s test, the diagnostic is lying in
the same direction again.
"""

from vertiscope.analytics.diagnose import diff_addresses


class _Unit:
    def __init__(self, xpath, value="", kind="text", drawn=True):
        self.xpath = xpath
        self.value = value
        self.kind = kind
        self.drawn = drawn


def test_an_address_the_page_does_not_have_is_charged():
    out = diff_addresses({"/html/body/nowhere": "x"},
                         [_Unit("/html/body/p", "y")])
    assert out["counts"]["charged"] == 1
    assert out["counts"]["forgiven"] == 0


def test_a_text_child_of_a_known_owner_is_forgiven():
    """The tolerance `score_arrow` has and a raw diff does not.

    Truth addresses the element; the trie addresses its text. The page has
    the content, so this is a difference in where it was addressed.
    """
    out = diff_addresses({"/html/body/p/text()[3]": "x"},
                         [_Unit("/html/body/p/text()[1]", "x")])
    assert out["counts"]["charged"] == 0
    assert out["counts"]["forgiven"] == 1


def test_a_render_standing_one_level_up_is_forgiven():
    """An inline <svg> named by its title: truth addresses the title, the
    render addresses the picture. Counting that as a phantom once charged 19
    inventions for 19 logos correctly drawn."""
    out = diff_addresses({"/html/body/svg[4]": "Ford"},
                         [_Unit("/html/body/svg[4]/title/text()[1]", "Ford")])
    assert out["counts"]["charged"] == 0
    assert out["counts"]["forgiven"] == 1


def test_a_match_is_neither_charged_nor_forgiven():
    out = diff_addresses({"/html/body/p": "x"}, [_Unit("/html/body/p", "x")])
    assert out["counts"] == {"charged": 0, "forgiven": 0, "missing": 0}


def test_the_missing_side_is_kept_apart_from_both():
    """So no caller can sum them into one 'error' figure.

    That summing is how the same units came to be counted on both sides of
    the confusion matrix at once.
    """
    out = diff_addresses({}, [_Unit("/html/body/p", "x")])
    assert out["counts"] == {"charged": 0, "forgiven": 0, "missing": 1}


def test_forgiveness_does_not_reach_across_the_document():
    """The tolerance is ancestry, not proximity."""
    out = diff_addresses({"/html/body/footer/x": "v"},
                         [_Unit("/html/body/nav/a/text()[1]", "v")])
    assert out["counts"]["charged"] == 1
