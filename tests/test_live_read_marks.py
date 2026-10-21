"""The arrow from a line of markdown back to the element that drew it.

`read()` is the join between the two halves the interface kept apart: the
page's words, which `text()` gave, and the page's controls, which `acts()`
gave. A reader who saw `[ ] Search` in the text had to run a second listing
and match it back by label -- which fails exactly where it matters, since a
page with eight `( More )` buttons has eight identical labels.

These tests hold the join to three promises:

* the mark on a line names the same control `act(n)` returns,
* the numbering is READING order, so "the third thing you can see" and
  `act(3)` are one thing,
* an affordance the fold found by `role=`, `contenteditable` or an `on*`
  handler is as reachable as one it found by tag name.

The fourth is the seam underneath all of them: a trie node spells the first
of its kind `/p/a` and the address spells it `/p/a[1]`, and every comparison
between the object model and the markdown crosses that.
"""

import sys

import pytest

import vertiscope.live as L
from vertiscope.core.content_tagger import ContentTagger
from vertiscope.core.shadow_html_parser import ShadowDOM
from vertiscope.markdown import render_trie
from vertiscope.trie import AddressTrie


def load(html):
    """A page in hand, with no browser: the fold, the render and the cursor."""
    tagged = ContentTagger(ShadowDOM(html)).tag()
    trie = AddressTrie.from_tagged(tagged, "https://x.test/p")
    L._S.spine = type("_Spine", (), {"trie": trie})()
    L._S.url = "https://x.test/p"
    L._S._chunks = render_trie(trie, context_window=1200)
    L._S.driver = None
    root = L.Node(L._page_root(trie))
    L._S.cursor = root._t
    return root


def find(node, want):
    if node.xpath == want:
        return node
    for kid in node.children():
        hit = find(kid, want)
        if hit is not None:
            return hit
    return None


LINKS = ("<html><body>"
         "<p>See the <a href='/rates'>retreat rates</a> and"
         " <a href='/mass'>mass balance</a>.</p>"
         "<div><a href='/two'>two</a><div><a href='/three'>three</a></div></div>"
         "<a href='/four'>four</a>"
         "</body></html>")


# --- document order ---------------------------------------------------------

def test_acts_is_document_order_not_breadth_first():
    """`four` is the last link on the page and must be listed last.

    The walk was breadth first while its docstring said document order, so a
    control's depth decided its position: `four` came second, ahead of two
    links that precede it in the page. `act(n)` is a promise about position,
    and it was false for every page whose controls sit at more than one
    depth -- which is every real page.
    """
    root = load(LINKS)
    seen = [n.xpath.replace("/html/body", "") for n in root.acts()]
    assert seen == ["/p/a", "/p/a[2]", "/div/a", "/div/div/a", "/a"]


# --- the seam ---------------------------------------------------------------

def test_canon_makes_one_spelling_per_position():
    assert L._canon("/html/body/p/a") == "/html[1]/body[1]/p[1]/a[1]"
    assert L._canon("/html/body/p/a[2]") == "/html[1]/body[1]/p[1]/a[2]"
    assert L._canon("/p/a") == L._canon("/p/a[1]")


def test_under_is_ancestry_not_substring():
    assert L._under("/html/body/nav/a", "/html/body/nav")
    assert L._under("/html/body/nav", "/html/body/nav")
    # `nav` is not under `na`, and no amount of startswith knows that.
    assert not L._under("/html/body/nav", "/html/body/na")
    # A sibling is not a descendant, however the two are spelled.
    assert not L._under("/html/body/p[2]", "/html/body/p")


def test_text_does_not_answer_for_a_sibling():
    """The bug the seam caused, held down by name.

    `"/div/p[2]".startswith("/div/p")` is true, so asking the first paragraph
    what it said returned the second one as well -- with nothing in the
    answer to say it had.
    """
    root = load("<html><body><div><p>FIRST para</p><p>SECOND para</p></div>"
                "<ul><li>alpha</li><li>beta</li></ul></body></html>")
    assert find(root, "/html/body/div/p").text() == "FIRST para"
    assert find(root, "/html/body/ul/li").text() == "- alpha"


# --- the marks --------------------------------------------------------------

def test_every_drawn_control_is_marked_including_the_first_of_its_kind():
    root = load(LINKS)
    reading = root.read()
    assert reading.controls == 5
    # Before the two spellings were reconciled the first link on the page --
    # and the first input, and the first button -- carried no mark at all.
    assert reading.unmarked == 0
    assert "act(0)" in reading.body


def test_a_mark_names_the_control_act_returns():
    root = load(LINKS)
    body = root.read().body
    for n, node in enumerate(root.acts()):
        if "act(%d)" % n not in body:
            continue
        assert L.act(n).xpath == node.xpath


def test_a_control_is_marked_once_however_many_addresses_drew_it():
    root = load(LINKS)
    body = root.read().body
    for n in range(root.read().controls):
        assert body.count("act(%d)" % n) <= 1


def test_read_leaves_the_markdown_a_markdown():
    """A handle is trailing text. Structure, headings and control forms stay."""
    root = load("<html><body><h1>Title</h1><p>words</p>"
                "<form><input type='search' placeholder='Search'></form>"
                "</body></html>")
    body = root.read().body
    assert "# Title" in body
    assert "words" in body
    assert "[ ] Search" in body
    for line in body.splitlines():
        if "act(" in line:
            assert line.split("act(")[0].rstrip(), "a mark is never a whole line"


def test_reading_reports_what_it_could_not_mark():
    root = load(LINKS)
    reading = root.read()
    assert "%d controls" % reading.controls in repr(reading)
    assert str(reading) == reading.body


# --- affordances the tag whitelist cannot express ---------------------------

@pytest.mark.parametrize("html,xpath", [
    ("<html><body><div role='button'>Load more</div></body></html>",
     "/html/body/div"),
    ("<html><body><span onclick='go()'>Go</span></body></html>",
     "/html/body/span"),
    ("<html><body><p contenteditable='true'>type here</p></body></html>",
     "/html/body/p"),
])
def test_the_fold_decides_what_is_actionable_not_a_tag_list(html, xpath):
    """A `div` the markdown draws as a button must be pressable.

    The tagger marks a control from four routes -- the tag, `role=`,
    `contenteditable`, and any `on*` handler. `acts()` asked a whitelist of
    eight tag names, so a reader could see an affordance in the text and find
    nothing in the listing to press it with.
    """
    root = load(html)
    assert [n.xpath for n in root.acts()] == [xpath]
    assert L.Node(root.acts()[0]._t).interactive()


# --- pages with no single root element --------------------------------------

FRAGMENT = ("<meta charset='utf-8'>"
            "<ul><li><a href='/one'>one</a></li></ul>"
            "<footer><a href='/two'>two</a><a href='/three'>three</a></footer>")


def test_a_page_with_no_document_element_is_not_reduced_to_its_first_tag():
    """`Page("https://danluu.com")` opened onto a `<meta>` tag.

    Hand-written and very old html often has no single root: danluu.com's top
    level is `/meta /meta[2] /ul /footer /script`, rfc2616 is 60-odd bare
    `<pre>` blocks, and info.cern.ch has `/header` beside `/body`. The walk
    took the FIRST child carrying an xpath as the document element, so on
    those three pages it visited one node and the whole page was invisible to
    the object model -- 1,884 of the corpus's 1,885 unreachable affordances,
    and every word of text with them.
    """
    root = load(FRAGMENT)
    assert root.xpath in ("", "/")
    reached = {n.xpath for n in root.acts()}
    assert reached == {"/ul/li/a", "/footer/a", "/footer/a[2]"}


def test_a_rootless_page_still_reads_and_marks():
    root = load(FRAGMENT)
    reading = root.read()
    assert reading.controls == 3
    assert reading.unmarked == 0
    assert "one" in reading.body


def test_a_well_formed_page_still_descends_to_its_document_element():
    root = load("<html><body><a href='/x'>x</a></body></html>")
    assert root.xpath == "/html"


# --- labels are the page's words, never the fold's bookkeeping --------------

def test_a_label_is_never_the_element_name():
    """Hacker News listed its `<body>` as "img a a a a a a a a a new | past".

    The tagger records a control's existence as the tag name -- `'a'` at the
    `<a>`, `'img'` at the `<img>` -- because for those the element IS the
    finding. The guard against printing that skipped accessors beginning `@`,
    which is how the SENSOR spells its synthetic annotations; the tagger
    spells the same thing with an empty accessor, which the trie normalises
    to `text()`. So on the snapshot path every one of them passed the
    reader-facing-text test, and all 228 of that page's links labelled
    themselves `'a'`.
    """
    root = load("<html><body><nav><a href='/n'>News</a>"
                "<a href='/j'>Jobs</a></nav>"
                "<p>Words the page shows.</p></body></html>")
    body = [k for k in root.children() if k.tag == "body"][0]
    label = L._label_of(body._t)
    assert label
    assert "a a" not in label
    assert label.split()[0] not in ("a", "img", "input", "button")


def test_echoes_its_element_compares_against_the_address_own_step():
    class _A:
        def __init__(self, xpath):
            self.xpath = xpath
    assert L._echoes_its_element(_A("/html/body/p/a[1]"), "a")
    assert L._echoes_its_element(_A("/html/body/img"), "img")
    # A short alphabetic word is not bookkeeping. `markdown._is_tag_name`
    # would delete all three of these, which is why it is not used here.
    assert not L._echoes_its_element(_A("/html/body/p/a[1]"), "Search")
    assert not L._echoes_its_element(_A("/html/body/p/a[1]"), "Home")
    assert not L._echoes_its_element(_A("/html/body/p/a[1]"), "News")


def test_the_acts_listing_shows_what_the_markdown_shows():
    """One derivation, two views.

    A control's label in the listing is the line the render drew for it, so
    `[ ] Search` and `( Go )` read the same in both places. Taken from the
    fold alone they read `'input'` and `'button'`.
    """
    root = load("<html><body><form>"
                "<input type='search' placeholder='Search'>"
                "<button>Go</button></form></body></html>")
    shown = repr(root)
    assert "'[ ] Search'" in shown
    assert "'( Go )'" in shown
