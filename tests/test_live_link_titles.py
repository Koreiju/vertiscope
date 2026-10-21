"""A link whose title is its own name still renders on the live path (`G-152`).

2026-10-11, Comparison_of_web_browsers: the live sensor files a link's href
under `link.anchor` -- category `link`, not `urls` -- so `_dedupe` compared the
url as prose; "https en wikipedia org wiki konqueror" is a strict superset of
the title "konqueror", and the title was dropped as subsumed by its own url.
With the text already joined into the title, the whole link vanished: 1,221 of
2,456 link lines on that one page. Planted: `PLANT_URL_AS_PROSE`.
"""

import vertiscope.markdown as md
from vertiscope.address import ContentAddress

URL = "https://en.wikipedia.org/wiki/Comparison_of_web_browsers"
A = "/html/body/main/table/tbody/tr[88]/th/a"


def _units():
    href = ContentAddress(URL, A, "link", "href|link.anchor/link")
    title = ContentAddress(URL, A, "link", "title|link.anchor/link")
    return [(href, "https://en.wikipedia.org/wiki/Konqueror", "a"),
            (title, "Konqueror Konqueror", "a")]


def test_a_live_href_never_subsumes_the_title_beside_it():
    kept = md._dedupe(_units())
    assert [a.accessor.split("|")[0] for a, _v, _l in kept] == ["href", "title"]


def test_planted_url_as_prose_drops_the_title(monkeypatch):
    monkeypatch.setattr(md, "PLANT_URL_AS_PROSE", True)
    kept = md._dedupe(_units())
    assert [a.accessor.split("|")[0] for a, _v, _l in kept] == ["href"]


def test_identical_words_join_as_one_spelling():
    title = ContentAddress(URL, A, "link", "title|link.anchor/link")
    text = ContentAddress(URL, A + "/text()[1]", "link", "text()[0]|link.anchor/link")
    joined = md._join_inline([(title, "Konqueror", "a", 12), (text, "Konqueror", "text()", 13)])
    assert [v for _a, v, _l, _d in joined] == ["Konqueror"]
    # Different words still join in full.
    other = md._join_inline([(title, "GNU General Public License", "a", 12), (text, "GPL-2.0-or-later", "text()", 13)])
    assert [v for _a, v, _l, _d in other] == ["GNU General Public License GPL-2.0-or-later"]
