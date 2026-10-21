"""The arbiter that decides whether a control arrived with its name.

`reach.py` shipped with no tests and two bugs, found by printing the cases
that changed verdict and reading them. Both were in the arbiter rather than
in the code it grades, and both moved the reported figure by tens of points
on the same unchanged render:

    37.08%   whole text, first 40 characters      -- too harsh
    65.61%   candidates, matched against the line -- too generous
    54.66%   candidates, destinations stripped    -- both corrected

A measure with no tests grades everything else in the project and nothing
grades it. These are the two mistakes, named, so neither can come back
quietly.
"""

import pytest

from vertiscope.analytics.reach import (_labels_by_xpath, _MIN_LABEL,
                                    _visible_words, score_page)
from vertiscope.core.content_tagger import ContentTagger
from vertiscope.core.shadow_html_parser import ShadowDOM
from vertiscope.markdown import render_trie
from vertiscope.trie import AddressTrie


def fold(html):
    dom = ShadowDOM(html)
    trie = AddressTrie.from_tagged(ContentTagger(dom).tag(), "https://x.test/p")
    return dom, trie, render_trie(trie, context_window=1200)


# --- a target is not something a reader can read ----------------------------

def test_a_bare_target_line_shows_no_words():
    """AP's `<https://apnews.com/hub/tennis>` scored as labelled.

    The candidate `Tennis` matched because the word is in the path. The line
    says nothing to a reader. Slugs are built from labels, so this is
    systematic rather than a coincidence, and it flattered exactly the
    bare-target lines the column exists to count.
    """
    assert _visible_words("<https://apnews.com/hub/tennis>") == ""


def test_a_link_keeps_its_words_and_loses_its_destination():
    assert _visible_words("[home page](/)") == "[home page]"
    assert _visible_words(
        "[Western Europe sets a record](https://x/west-europe-record)"
    ) == "[western europe sets a record]"


def test_a_sentence_with_a_link_folded_in_keeps_the_sentence():
    assert _visible_words("See the [retreat rates](/rates) and more.") == (
        "see the [retreat rates] and more.")


# --- a control has more than one true name ----------------------------------

def test_an_image_caption_does_not_hide_the_headline():
    """The too-harsh bug, by name.

    `get_text(recursive=True)` walks `iter_all()` and folds in `alt` for
    childless nodes, so an anchor wrapping a photo and a headline answered
    with the caption. Comparing the first 40 characters of THAT against the
    drawn line scored a correctly-labelled link as unlabelled -- about 2,000
    cases, every one reporting the render as worse than it is.
    """
    _dom, _trie, _chunks = fold(
        "<html><body><a href='/story'><img alt='People walk on a sandbar'>"
        "<h2>Western Europe sets new temperature record</h2></a></body></html>")
    labels = _labels_by_xpath(ShadowDOM(
        "<html><body><a href='/story'><img alt='People walk on a sandbar'>"
        "<h2>Western Europe sets new temperature record</h2></a></body></html>"))
    names = labels.get("/html[1]/body[1]/a[1]") or []
    joined = " | ".join(names)
    assert "People walk on a sandbar" in joined, "the caption is still offered"
    assert any("Western Europe sets new temperature record" in n
               for n in names), "the headline must be offered too"


def test_an_aria_label_is_a_name_even_when_the_words_are_a_picture():
    labels = _labels_by_xpath(ShadowDOM(
        "<html><body><a href='/' aria-label='home page'>"
        "<img alt='AP Logo'></a></body></html>"))
    names = labels.get("/html[1]/body[1]/a[1]") or []
    assert any("home page" in n for n in names)


def test_a_candidate_too_short_to_mean_anything_is_not_a_name():
    """`_MIN_LABEL` exists because "AP" appears inside hundreds of lines."""
    labels = _labels_by_xpath(ShadowDOM(
        "<html><body><a href='/x' title='ab'>ab</a></body></html>"))
    names = labels.get("/html[1]/body[1]/a[1]") or []
    assert all(len(n) >= _MIN_LABEL for n in names[1:]), names


# --- the columns ------------------------------------------------------------

def test_a_control_with_no_text_anywhere_is_excused_not_counted():
    """`<a name="chap01">` is an affordance a reader cannot be shown."""
    dom, trie, chunks = fold(
        "<html><body><p>words here</p><a name='chap01'></a></body></html>")
    row = score_page(trie, chunks, dom)
    assert row["empty"] >= 1
    assert row["collapsed"] == 0


def test_a_drawn_control_reports_whether_it_carried_its_name():
    dom, trie, chunks = fold(
        "<html><body><div><p>a block child</p>"
        "<a href='/target'>Glacial Retreat Calculator</a></div></body></html>")
    row = score_page(trie, chunks, dom)
    assert row["labelled"] >= 1
    assert row["unlabelled"] == 0


def test_the_counts_do_not_exceed_what_was_captured():
    dom, trie, chunks = fold(
        "<html><body><nav><a href='/a'>Alpha</a><a href='/b'>Beta</a></nav>"
        "<form><input type='search' placeholder='Search'>"
        "<button>Go</button></form></body></html>")
    row = score_page(trie, chunks, dom)
    for key in ("drawn", "reachable", "markable"):
        assert row[key] <= row["captured"], key
    assert row["empty"] + row["collapsed"] <= row["captured"]
    assert row["labelled"] + row["unlabelled"] <= row["drawn"]


def test_reachable_is_not_divided_by_the_drawable_denominator():
    """A label-less anchor is as reachable as any other.

    Dividing `reachable` by the drawable set printed 101.72%, which is the
    shape of a denominator applied to the wrong column.
    """
    from vertiscope.analytics.reach import render_reach_table

    dom, trie, chunks = fold(
        "<html><body><p>text</p><a name='x'></a>"
        "<a href='/y'>Yes</a></body></html>")
    table = render_reach_table({"rows": [score_page(trie, chunks, dom)]})
    for line in table.splitlines():
        if "reachable from acts()" in line:
            assert "of drawable" not in line
            break
    else:
        pytest.fail("no reachable row in the table")
