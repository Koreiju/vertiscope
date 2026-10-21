"""The `spoken` measure, and the two ways it was wrong before it was right.

A measure that reports a number nobody can act on is worse than no measure,
because it looks like coverage. This one reported 94.51% and then 56.54%
before it reported anything true, and both wrong numbers came from the
comparison rather than from the render. So the tests here are mostly about
the comparison: same tokenisation on both sides, the right scope, and enough
teeth to catch the defect it exists for.
"""

from vertiscope.analytics.spoken import _is_reader_text, _words_of, score_page
from vertiscope.core.content_tagger import ContentTagger
from vertiscope.core.shadow_html_parser import ShadowDOM
from vertiscope.markdown import render_trie
from vertiscope.trie import AddressTrie


def _measure(html, window=900):
    trie = AddressTrie.from_tagged(
        ContentTagger(ShadowDOM(html)).tag(), "https://x.test/")
    return score_page(trie, render_trie(trie, context_window=window))


# --- teeth ---------------------------------------------------------------------

def test_a_page_whose_words_all_reach_the_output_is_clean():
    html = ("<html><body><a>Disable MathJax</a><p>other words here</p>"
            "<button>Add to basket</button></body></html>")
    report = _measure(html)
    assert report["captured"] > 0, "nothing was measured at all"
    assert report["mute"] == 0, \
        "false positives: %s" % report["examples"]


def test_words_that_never_reach_the_output_are_counted():
    """The measure has to be able to fail, or it is decoration.

    Simulated by scoring a trie against chunks that do not contain its
    content, which is exactly the state the render was in for
    `<a>Disable MathJax</a>` before `alone` was fixed: addresses all
    accounted for, words absent.
    """
    trie = AddressTrie.from_tagged(
        ContentTagger(ShadowDOM(
            "<html><body><p>quarantined phrase here</p></body></html>")).tag(),
        "https://x.test/")
    other = AddressTrie.from_tagged(
        ContentTagger(ShadowDOM(
            "<html><body><p>entirely different content</p></body></html>")).tag(),
        "https://x.test/")
    report = score_page(trie, render_trie(other, context_window=900))
    assert report["mute"] >= 1, "a page saying none of the words scored clean"
    assert report["examples"][0]["missing"], "no missing word was named"


# --- the comparison ------------------------------------------------------------

def test_a_link_the_render_draws_is_not_called_mute():
    """Tokenisation has to match on both sides.

    `_visible_words` strips a link's target and leaves `[sports]` with the
    brackets attached, so a whitespace split yields `[sports]` while the
    value yields `sports`. Every drawn link scored as mute -- 1,932 over six
    pages, the largest category, all plainly visible in the output.
    """
    report = _measure(
        "<html><body><p>See <a href='/hub/sports'>Sports</a> today.</p>"
        "</body></html>")
    assert report["mute"] == 0, \
        "a drawn link was called mute: %s" % report["examples"]


def test_words_may_be_said_by_an_ancestor_line():
    """The render folds a child's words into a sentence, deliberately.

    Asking for a contiguous match tested line layout rather than content
    survival: arxiv's author list was called mute with all twenty-five of its
    tokens present.
    """
    report = _measure(
        "<html><body><p>Read <a href='/a'>the next page</a> and "
        "<a href='/b'>another</a> now.</p></body></html>")
    assert report["mute"] == 0, \
        "folded words were called mute: %s" % report["examples"]


def test_a_bare_url_value_is_not_treated_as_words():
    """A destination is not a reading.

    An anchor with no words carries its href as the value, and the render
    draws it as a target -- so looking for it among the visible words finds
    nothing and every such value scored as a loss.
    """
    assert _words_of("https://doi.org/10.48550/arXiv.1706.03762") == []
    assert _words_of("//cdn.example.com/x.png") == []
    assert _words_of("mailto:someone@example.com") == []
    assert _words_of("Disable MathJax")


# --- the scope ------------------------------------------------------------------

def test_machine_data_is_out_of_scope():
    """Counting it measured the render doing its job and called it loss.

    With metadata and json included, mute read 4,324 over six pages and its
    top examples were a viewport declaration and a mime type.
    """
    from vertiscope.address import ContentAddress

    def address(tag, category):
        return ContentAddress(url="https://x.test/", xpath="/html/body/p",
                              tag=tag, accessor="text()")

    assert _is_reader_text(address("text.visible", "text"))
    assert _is_reader_text(address("interactive.links", "interactive"))
    assert not _is_reader_text(address("text.metadata", "text"))
    assert not _is_reader_text(address("json_data.ld_json", "json_data"))
    assert not _is_reader_text(address("text.attributes", "text"))


def test_a_selector_value_is_not_measured_as_words():
    """`content_tagger` emits two kinds of interactive detection.

    Three carry the element's words -- inputs, buttons and anchors all pass
    `_own_name`/`_own_label`. The rest pass a selector: `f'{tag}[role=...]'`,
    `f'{tag}[contenteditable]'`, `f'{tag}[{attr}]'`. A selector's words are
    never on the page, so scoring one against the rendered text is arithmetic
    rather than measurement.

    It read `interactive.inputs|role` at 1,479 mute of 1,618 -- 91% -- and
    made inputs look like the worst class in the corpus, when the real input
    labels (`interactive.inputs|text()`) are 7 mute of 3,577.
    """
    from vertiscope.address import ContentAddress
    from vertiscope.analytics.spoken import _describes_rather_than_reads

    def address(accessor):
        return ContentAddress(url="https://x.test/", xpath="/html/body/a",
                              tag="interactive.inputs", accessor=accessor)

    assert _describes_rather_than_reads(address("role"), "a[role=menuitem]")
    assert _describes_rather_than_reads(address("contenteditable"),
                                        "div[contenteditable]")
    assert _describes_rather_than_reads(address("onclick"), "div[onclick]")
    assert _describes_rather_than_reads(address("data-wfh-interactive"), "div")
    # The element's own name is a description too, whatever carried it.
    assert _describes_rather_than_reads(address(""), "a")
    # Real words are not.
    assert not _describes_rather_than_reads(address(""), "Add to basket")


def test_role_detections_do_not_dominate_a_clean_page():
    """The end-to-end shape of the same bug.

    A page whose every word is drawn must score clean even when its controls
    are found by `role`, which is how a great many modern pages mark them.
    """
    html = ("<html><body>"
            "<div role='menuitem'>Open settings</div>"
            "<div role='textbox' contenteditable='true'>Type here</div>"
            "<span onclick='go()'>Run it</span>"
            "</body></html>")
    report = _measure(html)
    assert report["mute"] == 0, \
        "role/handler detections scored as loss: %s" % report["examples"]
