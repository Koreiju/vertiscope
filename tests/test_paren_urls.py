"""Link and image destinations with balanced parentheses (2026-10-06).

"Numerous nodes are missing at least one of a full set of images" and "a
clicked panel not rendering": an allrecipes card's picture is a thumbor url,
``.../filters:no_upscale():max_bytes(150000):strip_icc():focal(...)/x.jpg``.
Every markdown reader here took the destination as ``[^)\\s]*`` -- up to the
FIRST ``)`` -- so the card's ``<img src>`` ended at ``no_upscale(``, the rest
of the url leaked into the caption as text, and the 3D node's picture was the
same broken url. Wikipedia titles (``Mercury_(planet)``) were cut the same way.
CommonMark allows balanced parentheses in a destination; so do these now.

The planted arm is the old pattern itself: it must truncate the same urls.
"""

import re

from vertiscope import markdown as md_mod
from vertiscope import tokens
from vertiscope.obsidian import htmlform, layout

THUMB = ("https://www.allrecipes.com/thmb/1z9r8ESIxhgEBj254lo5kRSeBPk=/282x188/"
         "filters:no_upscale():max_bytes(150000):strip_icc():focal(1777x2044:1779x2046)"
         ":format(webp)/16359-breakfast-sausage.jpg")
WIKI = "https://en.wikipedia.org/wiki/Mercury_(planet)"

OLD_MEDIA = re.compile(r"^!\[([^\]]*)\]\(([^)\s]*)\)\s*(.*)$")


def test_planted_the_old_pattern_truncates_a_thumbor_url():
    m = OLD_MEDIA.match("![a plate](%s)" % THUMB)
    assert m is None or m.group(2) != THUMB


def test_the_card_image_keeps_its_whole_source():
    m = htmlform._MEDIA.match("![a plate](%s)" % THUMB)
    assert m and m.group(2) == THUMB and m.group(3) == ""
    html = htmlform.render_lines([{"text": "![a plate](%s)" % THUMB, "key": "", "cls": "image"}],
                                 base="https://www.allrecipes.com/recipes/")
    assert 'src="%s"' % THUMB.replace("&", "&amp;") in html, html
    assert "max_bytes" not in html.split("src=")[0]
    assert "<figcaption>image :max_bytes" not in html


def test_a_wikipedia_title_link_keeps_its_parenthesis():
    m = htmlform._LINK.match("[Mercury](%s)" % WIKI)
    assert m and m.group(2) == WIKI and m.group(3) == ""


def test_the_3d_node_picture_is_the_whole_url():
    got = layout._first_image("![a plate](%s)" % THUMB, "https://www.allrecipes.com/recipes/")
    assert got and got.get("src") == THUMB, got


def test_the_model_text_drops_the_whole_target():
    out = tokens.for_model("see [Mercury](%s) and ![a plate](%s)" % (WIKI, THUMB))
    assert "planet" not in out and "max_bytes" not in out, out
    assert "Mercury" in out


def test_markdown_link_pattern_takes_the_whole_destination():
    m = md_mod._LINK_RE.search("[Mercury](%s) tail" % WIKI)
    assert m and m.group(2) == WIKI
