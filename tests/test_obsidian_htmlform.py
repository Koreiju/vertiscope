"""The distilled HTML form: real widgets, real addresses, nothing executable.

The markdown form and this one are two renderings of one payload, so most of
what could go wrong is not "does it draw a button" -- it will -- but whether
the two forms can disagree, and whether a page can get something through here
that it could not get through markdown. Markdown is inert; HTML is not, and
this HTML is inserted into a note in the reader's own app by a code-block
processor that does no sanitising of its own. So the escaping tests are the
point of this module and the widget tests are the easy half.
"""

import re

import pytest

from vertiscope.obsidian.htmlform import _safe_url, chunk_html, render_lines


def line(text, **kw):
    entry = {"text": text, "key": "u|x|text.visible|text()", "cls": "text"}
    entry.update(kw)
    return entry


# --- the widgets markdown cannot have ---------------------------------------


def test_a_button_line_becomes_a_button_element():
    """The whole reason this form exists beside the markdown one."""
    html = render_lines([line("( Add to basket )", cls="button",
                              control=True, control_key="ck")])
    assert "<button" in html
    assert ">Add to basket<" in html
    # The mark itself must not survive into the label: the element IS the
    # affordance now, and printing the parentheses too says it twice.
    assert "( Add to basket )" not in html


def test_a_field_line_becomes_an_input_with_the_label_as_placeholder():
    html = render_lines([line("[ ] Search books", cls="field", control=True)])
    assert '<input type="text"' in html
    assert 'placeholder="Search books"' in html


def test_a_checked_box_is_a_checkbox_and_not_a_text_field():
    html = render_lines([line("[x] Include out of stock", cls="check")])
    assert '<input type="checkbox" checked' in html
    assert 'type="text"' not in html


def test_a_form_line_becomes_a_fieldset_outside_a_paragraph():
    """`<fieldset>` inside `<p>` is not nesting, it is a parser recovery.

    The parser closes the paragraph at the opening tag and opens a fresh one
    after the close, so the element's siblings end up somewhere other than
    where this module put them, and the nesting divs then unwind against a
    tree nobody wrote.
    """
    html = render_lines([line("=== search ===", cls="group")])
    assert "<fieldset" in html
    assert not re.search(r"<p[^>]*>\s*<fieldset", html)


def test_a_control_the_render_drew_no_mark_for_still_gets_a_widget():
    """The carried-affordance case: taxonomy says control, the line does not."""
    html = render_lines([line("Disable MathJax", cls="button",
                              control=True, control_key="ck")])
    assert "<button" in html and "dv-carried" in html


# --- the address, which is what makes any of it actionable ------------------


def test_every_element_carries_the_address_a_press_should_name():
    """`control_key` when there is one, and the line's own address beside it.

    An anchor's `interactive.links` address is suppressed by the render, so
    the LINE is stored under a `urls.*` address and enacting on that names
    the wrong thing. Both are emitted because the two answer different
    questions -- what to press, and where the line lives.
    """
    html = render_lines([line("( Buy )", cls="button", control=True,
                              key="line-address", control_key="control-address")])
    assert 'data-vertiscope-address="control-address"' in html
    assert 'data-vertiscope-line="line-address"' in html


def test_a_line_with_one_address_does_not_repeat_it():
    html = render_lines([line("plain words", key="only")])
    assert 'data-vertiscope-address="only"' in html
    assert "data-vertiscope-line" not in html


# --- media ------------------------------------------------------------------


def test_an_image_line_becomes_a_figure_with_its_caption():
    html = render_lines([line("![A Light in the Attic](media/cache/x.jpg)",
                              cls="image")])
    assert "<figure" in html and "<img" in html
    assert 'src="media/cache/x.jpg"' in html
    assert "A Light in the Attic" in html
    # No referrer: fetching a page's assets from a vault already tells the
    # host the page was read again; it must not also say which page it was
    # read from.
    assert 'referrerpolicy="no-referrer"' in html


def test_an_image_with_no_source_still_says_what_it_was():
    """A picture the distiller found but could not locate is not nothing."""
    html = render_lines([line("![A Book]", cls="image")])
    assert "<figure" in html and "<img" not in html
    assert "A Book" in html


# --- the page is untrusted --------------------------------------------------


@pytest.mark.parametrize("hostile", [
    "javascript:alert(1)",
    "JaVaScRiPt:alert(1)",
    "data:text/html,<script>alert(1)</script>",
    "vbscript:msgbox",
])
def test_an_executable_scheme_never_becomes_an_href(hostile):
    """Refused, and the words kept.

    Dropping the whole line would lose content the page really showed. The
    reader sees what it said and is not handed something to click.
    """
    assert _safe_url(hostile) == ""
    html = render_lines([line("[click me](%s)" % hostile, cls="link")])
    assert "href" not in html
    assert "click me" in html


def test_a_scheme_hidden_behind_a_control_character_is_still_refused():
    """`java&#9;script:` is a scheme to a browser and not to a prefix test."""
    assert _safe_url("java\tscript:alert(1)") == ""
    assert _safe_url("java\nscript:alert(1)") == ""


def test_ordinary_targets_survive():
    """A refusal set that refuses everything is a broken renderer, not a safe
    one -- and nothing downstream could tell the two apart."""
    for good in ("https://books.test/a", "http://books.test/a",
                 "mailto:a@b.test", "catalogue/x.html", "/page/2/",
                 "//cdn.test/a.png"):
        assert _safe_url(good) == good


#: Everything this module is allowed to emit. Asserted against the PARSED
#: output rather than against the string, because the string test is the one
#: that reads right and proves nothing: `onerror` appearing in
#: `&lt;img src=x onerror=alert(1)&gt;` is escaped text a reader sees, not an
#: attribute a browser runs, and a substring search cannot tell those apart.
#: What matters is which elements and attributes actually exist in the tree.
_ALLOWED_TAGS = {"div", "p", "span", "a", "h1", "h2", "h3", "h4", "h5", "h6",
                 "ul", "li", "button", "label", "input", "fieldset", "legend",
                 "figure", "figcaption", "img"}
_ALLOWED_ATTRS = {"class", "href", "rel", "type", "disabled", "checked",
                  "placeholder", "src", "alt", "loading", "referrerpolicy",
                  "data-vertiscope-address", "data-vertiscope-line",
                  # Addresses whose line was folded into this element -- see
                  # _fold_repeats. Listed so the whitelist stays the whole
                  # truth rather than the part the fixtures happen to reach.
                  "data-vertiscope-also", "data-vertiscope-shape"}


def _parsed(html):
    """Every (tag, attrs) the browser would actually build."""
    from html.parser import HTMLParser

    found = []

    class Reader(HTMLParser):
        def handle_starttag(self, tag, attrs):
            found.append((tag, [k for k, _v in attrs]))

    Reader().feed(html)
    return found


def test_nothing_outside_the_whitelist_is_ever_emitted():
    """The one property that makes this safe to put in a note.

    Driven with page text that is trying to open elements: script tags in a
    line's words, an event handler in an address, a quote where an attribute
    ends.
    """
    html = render_lines([
        line("<script>alert(1)</script>", key='"><script>x</script>'),
        line("<img src=x onerror=alert(1)>"),
        line("words", key='a" onmouseover="alert(1)'),
        line("[go](javascript:alert(1))", cls="link"),
        line("( <b>press</b> )", cls="button", control=True),
    ])
    for tag, attrs in _parsed(html):
        assert tag in _ALLOWED_TAGS, "emitted <%s>" % tag
        for attr in attrs:
            assert attr in _ALLOWED_ATTRS, "emitted %s= on <%s>" % (attr, tag)


def test_the_words_survive_escaping_rather_than_being_dropped():
    """Escaped, not deleted: the reader still sees what the page said."""
    html = render_lines([line("<script>alert(1)</script>")])
    assert "&lt;script&gt;" in html


# --- structure --------------------------------------------------------------


def test_nesting_follows_the_indentation_and_always_closes():
    html = render_lines([line("top"), line("  one"), line("    two"),
                         line("back")])
    assert html.count('<div class="dv-n">') == html.count("</div>")


def test_a_heading_line_becomes_a_heading():
    assert "<h3" in render_lines([line("### Products")])


def test_a_control_inside_a_heading_keeps_both():
    """`##### ( Products )` is a heading AND a button.

    The heading mark comes off first for this reason, and it is the trap
    `surface.ts::words` records: strip the control mark first and the leading
    `#####` is still there, so no control test fires and the label reads
    `##### ( Products )`.
    """
    html = render_lines([line("##### ( Products )", cls="button",
                              control=True, control_key="ck")])
    assert "<h5" in html and "<button" in html
    assert ">Products<" in html


def test_the_two_forms_read_the_same_payload():
    """Not a second extractor.

    If this ever grew its own alignment of lines to addresses, a chunk could
    say one thing in markdown and another in HTML, and nothing downstream
    would be able to tell which was the distillation.
    """
    import inspect

    from vertiscope.obsidian import htmlform

    source = inspect.getsource(htmlform.chunk_html)
    assert "chunk_payload" in source, \
        "the HTML form must be built from the markdown form's own payload"


def test_a_chunk_the_store_does_not_have_is_none_not_an_empty_page(tmp_path):
    """An empty string and a missing chunk must not look the same."""
    from vertiscope.workspace import Workspace

    with Workspace(tmp_path / "ws") as ws:
        assert chunk_html(ws, "no-such-cid") is None



# --- relative urls resolve against the PAGE, not against the vault -------------

def test_a_relative_image_resolves_against_the_page():
    """Verified as a real failure in the running app before this existed.

    The distiller writes what the page wrote, which is usually relative. A
    surface resolving that itself resolves against the document IT lives in,
    and in Obsidian that is `app://obsidian.md` -- so a note asked the app for
    a picture it does not have. 1 of 11 images loaded; the ten failures all
    pointed at `app://obsidian.md/...`.
    """
    html = render_lines(
        [line("![Tamas](user_avatar/tamas/25949_2.png)", cls="image")],
        base="https://discourse.julialang.org/latest")
    assert 'src="https://discourse.julialang.org/user_avatar/tamas/25949_2.png"' \
        in html, html


def test_a_relative_link_resolves_against_the_page():
    html = render_lines([line("[Meta](/c/meta/3)", cls="link")],
                        base="https://discourse.julialang.org/latest")
    assert 'href="https://discourse.julialang.org/c/meta/3"' in html, html


def test_an_absolute_url_is_left_alone():
    html = render_lines([line("![x](https://cdn.test/a.png)", cls="image")],
                        base="https://elsewhere.test/p")
    assert 'src="https://cdn.test/a.png"' in html


def test_absolutising_does_not_smuggle_a_scheme_past_the_refusal():
    """`_safe_url` runs first, so there is nothing left to resolve.

    Worth asserting rather than assuming: joining a refused value against a
    base is exactly how a sanitiser gets bypassed when the order is wrong.
    """
    html = render_lines([line("[go](javascript:alert(1))", cls="link")],
                        base="https://ok.test/")
    assert "javascript:" not in html
    assert "href" not in html


def test_a_billboard_and_its_chunk_name_the_same_file():
    """The 3D node's picture and the picture inside the chunk must agree.

    They are absolutised in two modules against the same base, and if those
    ever diverged a node would billboard a file the chunk cannot show.
    """
    from vertiscope.obsidian.layout import _first_image

    base = "https://discourse.julialang.org/latest"
    md = "![Tamas](user_avatar/tamas/25949_2.png)"
    node = _first_image(md, base)
    html = render_lines([line(md, cls="image")], base=base)
    assert node is not None
    assert 'src="%s"' % node["src"] in html, (node, html)


# --- cohesive structures ------------------------------------------------------

def test_a_picture_with_words_beside_it_is_drawn_as_a_card():
    """"Localized enough ... to render them as their intended cohesive
    structures."

    A result row is a picture and a title and a snippet and a button that
    belong together; drawn as four stacked lines, the one thing the page's
    layout was saying is lost. The group is classified only once its contents
    are known, which is why the builder holds a tree rather than a string of
    open and close tags.
    """
    html = render_lines([
        line("Results"),
        line("  ![Cover of a book](https://x.test/c.jpg)", cls="image"),
        line("  ### A Light in the Attic"),
        line("  ( Add to basket )", cls="button", control=True),
    ], base="https://x.test/")
    assert "dv-card" in html, html


def test_a_run_of_paragraphs_is_not_a_card():
    """Non-vacuity. A rule that fires on everything says nothing."""
    html = render_lines([
        line("Article"),
        line("  first paragraph of prose"),
        line("  second paragraph of prose"),
    ])
    assert "dv-card" not in html


def test_two_pictures_in_one_group_are_not_a_card():
    """A gallery is a gallery. A card is one picture with words beside it.

    Distinct keys, and they matter: the default `line()` helper gives every
    line one address, and two pictures at one element are the same picture.
    `_one_picture_per_element` folds them, quite correctly, and the fixture
    then tests nothing it means to.
    """
    html = render_lines([
        line("Gallery", key="u|/html/body/h2|text.visible|text()"),
        line("  ![one](https://x.test/1.jpg)", cls="image",
             key="u|/html/body/img[1]|media.images|src"),
        line("  ![two](https://x.test/2.jpg)", cls="image",
             key="u|/html/body/img[2]|media.images|src"),
    ], base="https://x.test/")
    assert "dv-card" not in html


def test_the_nesting_still_closes_with_the_tree_builder():
    html = render_lines([line("a"), line("  b"), line("    c"), line("d")])
    assert html.count("<div") == html.count("</div>")


# --- one element, one picture -------------------------------------------------

def _img(text, accessor, **kw):
    key = ("https://s.test/p|/html/body/article/img|media.images|%s" % accessor)
    return line(text, key=key, cls="image", **kw)


def test_an_element_with_two_media_addresses_draws_one_picture():
    """The renderer keeps both addresses; HTML must not draw both.

    An `<img>` yields its `src` and a `text()` whose value falls back to the
    element's tag name, and `_dedupe` keeps both on purpose -- a url or media
    address vanishing is the one thing that guard exists to prevent. Markdown
    pays a line for it because a line is all markdown has. HTML pays a
    picture: the placeholder draws as a grey tile beside the photograph, so
    the reader sees the same image twice, once broken.
    """
    html = render_lines([
        _img("![A Book]", "text()"),
        _img("![A Book](media/c.jpg)", "src"),
    ], base="https://s.test/p")
    assert html.count("<figure") == 1, html
    assert "dv-fig-off" not in html, "the placeholder was drawn as well"
    assert "<img" in html


def test_the_dropped_address_is_still_reachable():
    """Dropping a line must not drop an address.

    Every address in a chunk has to be reachable from the rendered DOM, or
    the HTML form quietly holds less than the markdown one and the two stop
    being the same distillation.
    """
    html = render_lines([
        _img("![A Book]", "text()"),
        _img("![A Book](media/c.jpg)", "src"),
    ], base="https://s.test/p")
    assert "data-vertiscope-also" in html
    assert "media.images|text()" in html


def test_a_picture_with_no_real_source_anywhere_still_draws():
    """The placeholder is only dropped when the SAME element has a located one."""
    html = render_lines([_img("![A Book]", "text()")], base="https://s.test/p")
    assert "<figure" in html and "dv-fig-off" in html
    assert "A Book" in html


def test_two_different_elements_keep_their_own_pictures():
    """Collapsing is per element, never across a gallery."""
    a = line("![one](https://x.test/1.jpg)", cls="image",
             key="https://x.test/|/html/body/img[1]|media.images|src")
    b = line("![two](https://x.test/2.jpg)", cls="image",
             key="https://x.test/|/html/body/img[2]|media.images|src")
    html = render_lines([a, b], base="https://x.test/")
    assert html.count("<figure") == 2


def test_collapsing_lets_the_card_form():
    """The two-figure group was why a result row was not recognised as a card.

    Verified in the running app before this was written: a books.toscrape
    result drew two figures for one `<img>`, so `_is_card` saw two pictures
    and drew the row as stacked lines.
    """
    html = render_lines([
        line("Results"),
        _img("  ![A Book]", "text()"),
        _img("  ![A Book](media/c.jpg)", "src"),
        line("  ### A Book"),
        line("  ( Add to basket )", cls="button", control=True),
    ], base="https://s.test/p")
    assert "dv-card" in html, html


# --- chrome that carries no structure -----------------------------------------

def test_a_chain_of_single_child_wrappers_collapses():
    """A page nests five divs to centre a header; each one drew a border.

    Every level here costs a border, an indent and a margin, and a wrapper
    with one child expresses no branching -- the indent stands for a
    distinction that does not exist. `markdown.py::_level_page` already does
    this on the markdown side; the HTML form was not, which is most of why
    the panel read as loose.
    """
    html = render_lines([
        line("        buried text"),
    ])
    assert html.count('class="dv-n"') <= 1, html


def test_collapsing_keeps_real_nesting():
    """Deeper stays deeper, siblings stay level. Only empty chains go."""
    html = render_lines([
        line("top"),
        line("  branch a"),
        line("  branch b"),
        line("    under b"),
    ])
    # Two children under one level is a real branch and must survive.
    assert 'class="dv-n"' in html
    assert html.count("<div") == html.count("</div>")
    assert "branch a" in html and "under b" in html


def test_a_card_is_never_drawn_inside_a_card():
    """Two borders and two paddings around one record.

    The inner group is usually the picture and its caption and the outer is
    the whole row, so both satisfy `_is_card`. Verified in the running app:
    two `dv-card` elements, the second nested in the first.
    """
    html = render_lines([
        line("Results"),
        line("  ![A Book](https://s.test/c.jpg)", cls="image"),
        line("    caption words"),
        line("  ### A Book"),
        line("  ( Add to basket )", cls="button", control=True),
    ], base="https://s.test/")
    assert html.count("dv-card") == 1, html


# --- one thing, drawn once ----------------------------------------------------

def _at(xpath, accessor, text, **kw):
    key = "https://s.test/q|%s|%s|%s" % (xpath, kw.pop("tag", "text.visible"),
                                         accessor)
    return line(text, key=key, **kw)


#: One books.toscrape product card, exactly as `chunk_payload` reports it.
#: Eleven lines, seven distinct, the title on five of them -- each a real
#: address at a different height of one chain.
CARD = [
    _at("/a/ol/li/article/div[1]/a/img", "text()",
        "    ![1,000 Places to See Before You Die]", tag="media.images",
        cls="image"),
    _at("/a/ol/li/article/div[1]/a/img", "src",
        "    ![1,000 Places to See Before You Die](../../media/c.jpg)",
        tag="media.images", cls="image"),
    _at("/a/ol/li/article/div[1]/a/img", "alt",
        "    1,000 Places to See Before You Die", tag="text.accessible"),
    _at("/a/ol/li/article/div[1]/a", "href",
        "  <../../1000-places_1/index.html>", tag="urls.internal"),
    _at("/a/ol/li/article/div[1]", "text()",
        "1,000 Places to See Before You Die"),
    _at("/a/ol/li/article/h3/a", "title",
        "  ### 1,000 Places to See Before You Die", tag="text.accessible"),
    _at("/a/ol/li/article/h3", "text()",
        "### [1,000 Places to See ...](../../1000-places_1/index.html)"),
    _at("/a/ol/li/article/div[2]/p[1]", "text()", "  £26.08"),
    _at("/a/ol/li/article/div[2]/p[2]", "text()", "  In stock"),
    _at("/a/ol/li/article/div[2]/form/button", "text()",
        "    ( Add to basket )", tag="interactive.buttons", cls="button",
        control=True),
    _at("/a/ol/li/article/div[2]/form", "text()", "  === form ===",
        tag="interactive.forms", cls="group"),
]


def _folded(lines):
    from vertiscope.obsidian.htmlform import _fold_repeats, _one_picture_per_element

    return _fold_repeats(_one_picture_per_element(lines))


def test_a_card_draws_each_thing_once():
    """The panel showed a product's title five times.

    Every one is a real address -- the image's alt, the picture's caption, the
    wrapping div's visible text, the anchor's `title`, and the heading that
    links to it -- and markdown has to spend a line on each because a line is
    all markdown has. HTML can hang several addresses on one element.
    """
    out = _folded(CARD)
    titles = [l for l in out
              if "1,000 places" in l["text"].lower()]
    assert len(titles) == 2, [l["text"] for l in titles]
    # The picture, and the heading. Nothing else.
    assert any(t["text"].strip().startswith("![") for t in titles)
    assert any(t["text"].strip().startswith("###") for t in titles)


def test_the_heading_keeps_its_destination():
    """The bug this caught: the linked title was the copy that got folded.

    `_rank` tested `_LINK` against text that still had its `###` on the
    front, so a heading that links scored as a bare heading, tied with the
    same title drawn from the anchor's `title` attribute, and lost the tie.
    The card's product name stopped linking to the product. Same trap as
    `surface.ts::words` and `_element`: a leading mark hides the one behind it.
    """
    out = _folded(CARD)
    heading = next(l for l in out if l["text"].strip().startswith("###"))
    assert "](" in heading["text"], heading["text"]
    assert "1000-places_1/index.html" in heading["text"]


def test_the_fuller_wording_survives_the_fold():
    """A shortened label and its full form are one thing.

    The heading is kept because it carries a destination; there is no reason
    to keep its truncation as well when the same element chain spelled the
    title out.
    """
    out = _folded(CARD)
    heading = next(l for l in out if l["text"].strip().startswith("###"))
    assert "1,000 Places to See Before You Die" in heading["text"]
    assert "..." not in heading["text"]


def test_the_label_keeps_the_page_casing():
    """`_words` lowercases to compare; a label must not be built from it."""
    out = _folded(CARD)
    heading = next(l for l in out if l["text"].strip().startswith("###"))
    assert "1,000 Places to See Before You Die" in heading["text"]
    assert "1,000 places to see" not in heading["text"]


def test_a_bare_url_folds_into_the_link_that_goes_there():
    """Two lines naming one destination inside one record are one link.

    Not chain-scoped, and deliberately: a card writes its href on the image's
    anchor and again on the heading's, which are siblings. A url is an
    identity, and the record rule made a chunk a single record, so "inside
    one chunk" is a tight enough scope for that to hold.
    """
    out = _folded(CARD)
    bare = [l for l in out if l["text"].strip().startswith("<")]
    assert not bare, [l["text"] for l in bare]


def test_no_address_is_lost_when_lines_are_folded():
    """The invariant that keeps both forms the same distillation.

    A folded line's address rides on the survivor. If it did not, the HTML
    form would quietly hold less than the markdown one.
    """
    out = _folded(CARD)
    before = {l["key"] for l in CARD if l.get("key")}
    after = set()
    for l in out:
        if l.get("key"):
            after.add(l["key"])
        after.update((l.get("also") or "").split())
    assert before <= after, before - after


def test_the_same_words_at_unrelated_elements_are_two_things():
    """Non-vacuity, and the guard that stops the fold eating real content.

    Two people with one name are two people. Folding is along an ancestor
    chain, where the two lines are one thing described from two heights.
    """
    lines = [
        _at("/a/ul/li[1]/span", "text()", "Alex Chen"),
        _at("/a/ul/li[2]/span", "text()", "Alex Chen"),
    ]
    assert len(_folded(lines)) == 2
