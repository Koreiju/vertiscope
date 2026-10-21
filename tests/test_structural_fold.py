"""Structural redundancy drawn once (`D-4`, `M-8`: "full deduplication of
repeat substrings that are essentially structural redundancies of the web
pages themselves"), and data never folded. Every folded address stays on the
line that speaks for it."""

from vertiscope.address import ContentAddress
from vertiscope.markdown import MarkdownLine, _fold_structural

U = "https://t.test/p"


def L(xpath, text, tag="text", acc="text()[0]"):
    return MarkdownLine(depth=0, text=text, address=ContentAddress(U, xpath, tag, acc))


def test_a_full_stop_cut_off_its_reference_rejoins_it():
    out = _fold_structural([L("/ol/li[3]/span[2]/text()[1]", "- Bodmer 1990, p. 12"),
                            L("/ol/li[3]/span[2]/text()[2]", "- .")])
    assert [l.text for l in out] == ["- Bodmer 1990, p. 12."]
    assert out[0].inline[0].xpath.endswith("text()[2]")


def test_a_link_and_its_own_icon_are_one_line():
    out = _fold_structural([L("/td[4]/span[3]/a", "[Edit this on Wikidata](https://www.wikidata.org/wiki/Q1)", "link", "href"),
                            L("/td[4]/span[3]/a/img", "![Edit this on Wikidata](//thumb/x.png)", "image", "src")])
    assert len(out) == 1 and out[0].inline[0].xpath.endswith("/a/img")


def test_a_sortable_headers_label_is_drawn_once():
    out = _fold_structural([L("/table/thead/tr/th", "Sort ascending", "cell", "title"),
                            L("/table/thead/tr/th/text()[1]", "Browser"),
                            L("/table/thead/tr/th[2]", "Sort ascending", "cell", "title"),
                            L("/table/thead/tr/th[2]/text()[1]", "Engine")])
    assert [l.text for l in out] == ["Sort ascending", "Browser", "Engine"]
    assert out[0].inline[0].xpath.endswith("th[2]")


def test_data_is_never_folded():
    # A feature table's "?" means unknown; a data cell's own line is its value;
    # a repeated "Yes" is two facts.
    lines = [L("/table/tbody/tr[2]/td[2]/text()[1]", "Yes"), L("/table/tbody/tr[2]/td[3]/text()[1]", "?"),
             L("/table/tbody/tr[3]/td[2]", "Yes", "cell", "title"), L("/table/tbody/tr[4]/td[2]", "Yes", "cell", "title")]
    assert [l.text for l in _fold_structural(lines)] == ["Yes", "?", "Yes", "Yes"]


def test_a_link_whose_icon_says_something_else_keeps_both():
    out = _fold_structural([L("/p/a", "[Okapi](https://x/Okapi)", "link", "href"),
                            L("/p/a/img", "![An okapi at the zoo](//x/o.jpg)", "image", "src")])
    assert len(out) == 2


def test_an_empty_picture_is_not_punctuation():
    out = _fold_structural([L("/div/button", "( More )", "button", "text()[0]"),
                            L("/div/video", "![]", "media.video", "text()[0]")])
    assert [l.text for l in out] == ["( More )", "![]"]
