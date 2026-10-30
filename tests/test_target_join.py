"""A target never joins prose (`M-10`, found 2026-10-30 on archive.org).

`_looks_like_url("/")` is False by design -- a "0 / 500" counter's middle
text node is a separator -- and `_join_inline` judged join-ability by that
value alone, so an anchor whose href is "/" (archive.org's home link, title
"Go home") joined its title into `[/ Go home](/ Go home)`: label and target
both wrong, the link unreachable. A unit on a target accessor never joins.
"""

import domvec.markdown as M
from domvec.address import ContentAddress
from domvec.trie import AddressTrie

U = "https://t.test/p"


def _render(units):
    t = AddressTrie()
    for xpath, tag, acc, value in units:
        t.insert(ContentAddress(U, xpath, tag, acc), value)
    return [c.markdown for c in M.render_trie(t, context_window=256)]


HOME = [("/html/body/nav/div/a", "link", "href|link.anchor/link", "/"),
        ("/html/body/nav/div/a", "link", "title|link.anchor/link", "Go home")]


def test_a_root_href_keeps_its_target_and_its_label():
    assert _render(HOME) == ["[Go home](/)"]


def test_planted_target_joining_prose_breaks_the_link():
    M.PLANT_TARGET_JOINS_PROSE = True
    try:
        assert _render(HOME) == ["[/ Go home](/ Go home)"]
    finally:
        M.PLANT_TARGET_JOINS_PROSE = False


def test_a_counters_separator_text_still_joins_its_neighbours():
    p = "/html/body/div/span"
    out = _render([(p + "/text()[1]", "text", "text()[0]", "0"), (p + "/b/text()[1]", "text", "text()[0]", "/"),
                   (p + "/text()[2]", "text", "text()[0]", "500")])
    assert any("0 / 500" in md for md in out), out


TAB = [("/html/body/div/a", "button", "href|link.anchor/tab", "https://web.archive.org/web/*/radio drama"),
       ("/html/body/div/a", "button", "aria-label|link.anchor/tab", "Web Sites")]


def test_a_tab_anchor_is_one_line_with_its_destination():
    assert _render(TAB) == ["[Web Sites](https://web.archive.org/web/*/radio drama)"]


def test_planted_control_href_keeps_its_own_line():
    M.PLANT_CONTROL_HREF_OWN_LINE = True
    try:
        assert _render(TAB) == ["( https://web.archive.org/web/*/radio drama )\n( Web Sites )"]
    finally:
        M.PLANT_CONTROL_HREF_OWN_LINE = False


def test_an_image_input_does_not_take_its_picture_as_a_destination():
    out = _render([("/html/body/form/input", "button", "src|control.button/image", "/i/go.png"),
                   ("/html/body/form/input", "button", "aria-label|control.button/image", "Search")])
    assert not any("](/i/go.png)" in md for md in out), out
