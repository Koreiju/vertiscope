"""One `<img>` is one line (D-8).

An image element yields two detections -- `src` and `alt` -- and that is correct
at the index: `ContentTag`'s key makes the accessor part of what is addressed.
The fault was in the projection, which drew each as its own line, so a page that
gave a perfectly good alt still reached a reader as a bare url.

The shape here is the LIVE SENSOR's, not the offline tagger's, and the
difference is the whole reason the defect exists. At one `<img>`:

    offline tagger   media.images / src     text.accessible / alt
    live sensor      image / src|media…     image / alt|media…

The offline path tags the alt as TEXT, which the existing element-scoped dedupe
absorbs. The live path tags it as an IMAGE, so `_RENDER["image"]` drew a second
`![...]`. Measured: 365 of 835 media-bearing chunks in a live-scanned store
carried such a pair; a fresh scan of the same site after the fix carries 0.

So these construct the live spelling directly. A fixture through `index_html`
cannot reproduce it, and a test that used one would pass against the bug.
"""

from vertiscope.address import ContentAddress
from vertiscope.markdown import MarkdownLine, _join_media


IMG = "/html/body/table/tbody/tr[91]/td[3]/div/a/span/img"


def _line(text, xpath=IMG, accessor="src|media.tag/img"):
    return MarkdownLine(0, text, ContentAddress(
        url="https://shop.test", xpath=xpath, tag="image", accessor=accessor))


def test_the_url_and_its_alt_become_one_line():
    """The pair as it was actually observed, from coinmarketcap's row 91."""
    out = _join_media([
        _line("![](https://s2.coinmarketcap.com/static/img/coins/64x64/34466.png)"),
        _line("![PENGU logo](https://s2.coinmarketcap.com/static/img/coins/64x64/34466.png)",
              accessor="alt|media.tag/img"),
    ])
    assert len(out) == 1, [l.text for l in out]
    assert out[0].text == \
        "![PENGU logo](https://s2.coinmarketcap.com/static/img/coins/64x64/34466.png)"


def test_the_surviving_address_is_the_one_carrying_the_url():
    """The url is the media's identity -- what `is_url` reports, what a `target`
    is read from, what a reader clicks. The alt is a caption of it."""
    out = _join_media([
        _line("![](https://x/a.png)"),
        _line("![a picture](https://x/a.png)", accessor="alt|media.tag/img"),
    ])
    assert out[0].address.accessor == "src|media.tag/img"


def test_the_merged_address_is_reported_as_inline_not_absorbed():
    """The distinction is not bookkeeping; it decides whether the render is
    honest about itself.

    `MarkdownLine` defines `absorbed` as an address whose *"words are not
    separately visible"* and `inline` as one *"MERGED — its words are visibly in
    this line and a reader can act on it there"*. The alt's words ARE in the
    merged line, which reads `![a picture](https://x/a.png)`.

    And `covered` — what the render DREW — counts `inline` and not `absorbed`,
    which is what `test_suppressed_units_are_a_deliberate_choice_not_a_leak`
    asks with. Filing this as absorbed made 20 units read as vanished while
    their text was on screen the whole time, and that guard caught it.
    """
    out = _join_media([
        _line("![](https://x/a.png)"),
        _line("![a picture](https://x/a.png)", accessor="alt|media.tag/img"),
    ])
    assert [a.accessor for a in out[0].inline] == ["alt|media.tag/img"]
    assert out[0].absorbed == ()


def test_two_different_elements_do_not_merge():
    """Scoped to one ELEMENT, for the reason `_dedupe` records: a chunk-scoped
    version 'collapsed every card in a grid sharing a placeholder image down to
    one, taking each card's address with it'."""
    out = _join_media([
        _line("![](https://x/a.png)", xpath=IMG + "/a"),
        _line("![b](https://x/b.png)", xpath=IMG + "/b"),
    ])
    assert len(out) == 2, [l.text for l in out]


def test_two_different_urls_at_one_element_do_not_merge():
    """A `<picture>` with its sources is not one picture drawn twice, and
    keeping only one would drop a file the page might actually serve."""
    out = _join_media([
        _line("![](https://x/small.png)"),
        _line("![hero](https://x/large.png)", accessor="srcset[1]|media.tag/img"),
    ])
    assert len(out) == 2, [l.text for l in out]


def test_a_media_line_with_no_url_anywhere_is_left_alone():
    """`![alt]` with nothing to point at is not half of a pair; merging two of
    them would invent a link."""
    out = _join_media([
        _line("![]"),
        _line("![caption]", accessor="alt|media.tag/img"),
    ])
    assert len(out) == 2, [l.text for l in out]


def test_a_lone_image_is_untouched():
    out = _join_media([_line("![solo](https://x/a.png)")])
    assert len(out) == 1 and out[0].text == "![solo](https://x/a.png)"
