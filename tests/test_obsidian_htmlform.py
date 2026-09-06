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

from domvec.obsidian.htmlform import _safe_url, chunk_html, render_lines


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
    assert 'data-domvec-address="control-address"' in html
    assert 'data-domvec-line="line-address"' in html


def test_a_line_with_one_address_does_not_repeat_it():
    html = render_lines([line("plain words", key="only")])
    assert 'data-domvec-address="only"' in html
    assert "data-domvec-line" not in html


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
                  "data-domvec-address", "data-domvec-line"}


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

    from domvec.obsidian import htmlform

    source = inspect.getsource(htmlform.chunk_html)
    assert "chunk_payload" in source, \
        "the HTML form must be built from the markdown form's own payload"


def test_a_chunk_the_store_does_not_have_is_none_not_an_empty_page(tmp_path):
    """An empty string and a missing chunk must not look the same."""
    from domvec.workspace import Workspace

    with Workspace(tmp_path / "ws") as ws:
        assert chunk_html(ws, "no-such-cid") is None

