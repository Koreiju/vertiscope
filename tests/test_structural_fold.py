"""Structural redundancy drawn once (`D-4`, `M-8`: "full deduplication of
repeat substrings that are essentially structural redundancies of the web
pages themselves"), and data never folded. Every folded address stays on the
line that speaks for it."""

from domvec.address import ContentAddress
from domvec.markdown import MarkdownLine, _fold_structural

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


def test_a_separator_between_two_items_of_one_cell_folds():
    # A navbox: links and their "·" separators in ONE td (ar.wikipedia, 103 of
    # them on one page); an infobox's "Wikidata" + ":" + its id; an opening
    # quote before a song link. Same cell -> separator -> folded.
    cell = "/table/tbody/tr[2]/td[2]"
    out = _fold_structural([L(cell + "/ul/li[1]/a", "[Max Planck](https://x/Planck)", "link", "href"),
                            L(cell + "/ul/li[1]/text()[1]", "·"),
                            L(cell + "/ul/li[2]/a", "[Einstein](https://x/Einstein)", "link", "href"),
                            L(cell + "/ul/li[2]/text()[1]", "- \""),
                            L(cell + "/ul/li[3]/a", "[Give Us the Ballot](https://x/B)", "link", "href")])
    assert [l.text for l in out] == ["[Max Planck](https://x/Planck) ·", "[Einstein](https://x/Einstein) \"",
                                     "[Give Us the Ballot](https://x/B)"]
    assert out[0].inline[0].xpath.endswith("li[1]/text()[1]")


def test_a_cells_own_punctuation_value_is_kept_and_the_planted_rule_keeps_separators():
    import domvec.markdown as M
    # "–" as a whole cell (the line before is ANOTHER cell): a value, kept.
    lines = [L("/table/tbody/tr[2]/td[1]/text()[1]", "Firefox"), L("/table/tbody/tr[2]/td[2]/text()[1]", "–")]
    assert [l.text for l in _fold_structural(lines)] == ["Firefox", "–"]
    sep = [L("/table/tbody/tr[2]/td[2]/a", "[A](https://x/a)", "link", "href"), L("/table/tbody/tr[2]/td[2]/text()[1]", "·")]
    M.PLANT_CELL_PUNCT_KEPT = True
    try:
        assert len(_fold_structural(sep)) == 2
    finally:
        M.PLANT_CELL_PUNCT_KEPT = False
    assert len(_fold_structural(sep)) == 1


def test_an_arabic_comma_cut_off_its_text_rejoins_it():
    out = _fold_structural([L("/p/a", "[ماكس بلانك](https://x/P)", "link", "href"), L("/p/text()[2]", "- ،")])
    assert [l.text for l in out] == ["[ماكس بلانك](https://x/P)،"]
