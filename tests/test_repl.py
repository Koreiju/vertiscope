"""The interactive REPL, proved without a terminal and without a mouse.

The spec's own framing: everything except the physical click should be
provable. The split that makes it so is that :class:`ReplState` is a pure
state machine — a click is a `press` event followed by a `release` event, and
those can be constructed. What a real mouse contributes is the *bytes*, and
those are covered separately by decoding the exact escape sequences an xterm
sends.

So the boundary is:

* state machine        — proved here by synthetic events
* escape-sequence decode — proved here byte for byte
* physical device -> bytes — the terminal's job, and the one gap

`scripts/mouse_probe.py` closes that last gap with a real pointer when one is
available; it is not part of this suite because it needs a desktop.
"""

import json
import pathlib

import pytest

from vertiscope.address import ContentAddress
from vertiscope.markdown import MarkdownChunk, MarkdownLine, render_trie
from vertiscope.pipeline import run_pipeline
from vertiscope.repl.app import Repl
from vertiscope.repl.model import (
    Document,
    KeyEvent,
    MouseEvent,
    ReplState,
    Widget,
    WidgetKind,
    kind_for,
)
from vertiscope.repl.nav import NavResult, WebNav, classify_controls
from vertiscope.repl.terminal import decode, paint
from vertiscope.trie import AddressTrie

CORPUS = pathlib.Path(__file__).parent / "corpus"
MANIFEST = CORPUS / "manifest.json"


def _address(xpath="/html/body/a", tag="urls.external", accessor="href"):
    return ContentAddress("https://x.test/p", xpath, tag, accessor)


@pytest.fixture()
def state():
    doc = Document(title="demo", url="https://x.test/p", lines=[
        Widget(0, WidgetKind.TEXT, "Results"),
        Widget(1, WidgetKind.INPUT, "query", _address("/html/body/input"), depth=1),
        Widget(2, WidgetKind.CHECKBOX, "include archived",
               _address("/html/body/label"), depth=1),
        Widget(3, WidgetKind.LINK, "https://x.test/a",
               _address("/html/body/a[1]"), depth=1),
        Widget(4, WidgetKind.BUTTON, "Next page",
               _address("/html/body/button", "interactive.buttons", "text()"),
               depth=1),
    ] + [Widget(i, WidgetKind.TEXT, f"row {i}") for i in range(5, 40)])
    return ReplState(document=doc, rows=12, cols=60)


def _click(state, line, x=5):
    row = state.row_of(line)
    assert row is not None, f"line {line} is not visible"
    state.handle(MouseEvent("press", x, row))
    return state.handle(MouseEvent("release", x, row))


# --- clicking ---------------------------------------------------------------


def test_a_click_is_a_press_then_a_release(state):
    assert state.document.lines[2].checked is False
    _click(state, 2)
    assert state.document.lines[2].checked is True


def test_press_without_release_does_not_activate(state):
    row = state.row_of(2)
    state.handle(MouseEvent("press", 5, row))
    assert state.document.lines[2].checked is False
    assert state.document.lines[2].armed is True


def test_declicking_elsewhere_cancels(state):
    """Release off the pressed widget must not activate it.

    This is the gesture every user relies on to back out of a misclick, and
    collapsing press and release into one 'click' event would make it
    impossible to express.
    """
    press_row = state.row_of(2)
    state.handle(MouseEvent("press", 5, press_row))
    state.handle(MouseEvent("release", 5, press_row + 1))
    assert state.document.lines[2].checked is False
    assert state.document.lines[2].armed is False


def test_a_second_click_unchecks(state):
    _click(state, 2)
    _click(state, 2)
    assert state.document.lines[2].checked is False


def test_clicking_a_link_calls_the_activation_hook(state):
    seen = []
    state.on_activate = seen.append
    _click(state, 3)
    assert len(seen) == 1 and seen[0].kind is WidgetKind.LINK


def test_clicking_outside_the_body_hits_nothing(state):
    assert state.hit(5, 1) is None                 # header
    assert state.hit(5, state.rows) is None        # footer
    assert state.handle(MouseEvent("press", 5, 1)) is None


# --- cursor placement -------------------------------------------------------


def test_clicking_a_field_places_the_cursor(state):
    field = state.document.lines[1]
    field.value = "abcdefgh"
    row = state.row_of(1)
    # the field draws as "  [value]": two indent columns plus a bracket
    state.handle(MouseEvent("press", 2 * field.depth + 1 + 1 + 4, row))
    assert field.cursor == 4


def test_clicking_past_the_end_puts_the_cursor_at_the_end(state):
    field = state.document.lines[1]
    field.value = "abc"
    state.handle(MouseEvent("press", 50, state.row_of(1)))
    assert field.cursor == len(field.value)


def test_typing_inserts_at_the_cursor(state):
    field = state.document.lines[1]
    _click(state, 1)
    for char in "library":
        state.handle(KeyEvent(char))
    assert field.value == "library"
    state.handle(KeyEvent("left"))
    state.handle(KeyEvent("left"))
    state.handle(KeyEvent("X"))
    assert field.value == "libraXry"


def test_backspace_and_delete(state):
    field = state.document.lines[1]
    _click(state, 1)
    for char in "abc":
        state.handle(KeyEvent(char))
    state.handle(KeyEvent("backspace"))
    assert field.value == "ab"
    state.handle(KeyEvent("home"))
    state.handle(KeyEvent("delete"))
    assert field.value == "b"


def test_arrow_keys_edit_the_field_rather_than_scrolling(state):
    """A focused field owns the arrow keys; otherwise they scroll."""
    _click(state, 1)
    before = state.top
    state.handle(KeyEvent("left"))
    assert state.top == before

    state.focus = 0        # a text line does not take the arrows
    state.handle(KeyEvent("down"))
    assert state.top == before + 1


# --- scrolling --------------------------------------------------------------


def test_the_wheel_scrolls(state):
    state.handle(MouseEvent("wheel_down", 5, 5))
    assert state.top == 3
    state.handle(MouseEvent("wheel_up", 5, 5))
    assert state.top == 0


def test_scrolling_clamps_at_both_ends(state):
    state.handle(MouseEvent("wheel_up", 5, 5))
    assert state.top == 0
    for _ in range(100):
        state.handle(MouseEvent("wheel_down", 5, 5))
    assert state.top == state.max_top
    assert state.top + state.body_rows <= len(state.document) + state.body_rows


def test_hit_testing_follows_the_scroll(state):
    """The same screen row means a different line once scrolled."""
    row = state.header_rows + 1
    assert state.hit(5, row) == 0
    state.scroll(5)
    assert state.hit(5, row) == 5


def test_clicking_after_scrolling_hits_the_right_widget(state):
    state.scroll(3)
    line = state.hit(5, state.header_rows + 1)
    assert line == 3
    _click(state, 3, x=5)
    assert state.focus == 3


def test_scroll_to_line_brings_it_into_view(state):
    state.scroll_to_line(30)
    assert state.row_of(30) is not None


# --- focus ------------------------------------------------------------------


def test_tab_focus_visits_only_interactive_widgets(state):
    seen = []
    for _ in range(4):
        widget = state.focus_next()
        seen.append(widget.kind)
    assert WidgetKind.TEXT not in seen
    assert set(seen) == {WidgetKind.INPUT, WidgetKind.CHECKBOX,
                         WidgetKind.LINK, WidgetKind.BUTTON}


def test_keyboard_activation_matches_clicking(state):
    state.focus = 2
    state.handle(KeyEvent(" "))
    assert state.document.lines[2].checked is True


# --- buffers ----------------------------------------------------------------


def test_buffers_are_bounded(state):
    state.buffers.limit = 5
    for i in range(20):
        state.buffers.note(f"message {i}")
    assert len(state.buffers.log) == 5
    assert state.buffers.log[-1] == "message 19"


def test_buffers_do_not_repeat_consecutive_history(state):
    state.buffers.remember("search books")
    state.buffers.remember("search books")
    assert state.buffers.history == ["search books"]


def test_state_snapshot_reports_the_interaction(state):
    _click(state, 2)
    state.scroll(4)
    snap = state.snapshot()
    assert snap["checked"] == 1 and snap["top"] == 4 and snap["focus"] == 2


# --- escape sequence decoding ----------------------------------------------


@pytest.mark.parametrize("data,expected", [
    ("\x1b[<0;12;5M", MouseEvent("press", 12, 5, 0)),
    ("\x1b[<0;12;5m", MouseEvent("release", 12, 5, 0)),
    ("\x1b[<2;3;4M", MouseEvent("press", 3, 4, 2)),
    ("\x1b[<64;1;1M", MouseEvent("wheel_up", 1, 1, 0)),
    ("\x1b[<65;1;1M", MouseEvent("wheel_down", 1, 1, 0)),
    ("\x1b[<32;9;9M", MouseEvent("move", 9, 9, 0)),
])
def test_mouse_sequences_decode(data, expected):
    got = decode(data)
    assert len(got) == 1
    assert got[0].action == expected.action
    assert (got[0].x, got[0].y) == (expected.x, expected.y)


def test_sgr_encoding_handles_wide_terminals():
    """The reason for SGR over the original X10 encoding.

    X10 packs a coordinate into one byte as value+32, so it cannot express a
    column past 223 — on a wide terminal every click on the right of the
    screen would be mis-reported. SGR sends decimal digits.
    """
    got = decode("\x1b[<0;400;120M")
    assert (got[0].x, got[0].y) == (400, 120)


@pytest.mark.parametrize("data,key", [
    ("\x1b[A", "up"), ("\x1b[B", "down"), ("\x1b[C", "right"),
    ("\x1b[D", "left"), ("\x1b[5~", "pageup"), ("\x1b[6~", "pagedown"),
    ("\r", "enter"), ("\x7f", "backspace"), ("\t", "tab"),
])
def test_key_sequences_decode(data, key):
    assert [e.key for e in decode(data)] == [key]


def test_printable_characters_decode_as_themselves():
    assert [e.key for e in decode("abc")] == ["a", "b", "c"]


def test_unknown_escape_sequences_are_dropped_not_typed():
    """Leaking an unknown sequence's bytes would type garbage into a field."""
    events = decode("\x1b[999zq")
    assert [e.key for e in events] == ["q"]


def test_a_mixed_burst_decodes_in_order():
    """A fast wheel plus typing arrives as one read; order must survive."""
    events = decode("a\x1b[<64;1;1Mb\x1b[<0;3;4M")
    kinds = [type(e).__name__ for e in events]
    assert kinds == ["KeyEvent", "MouseEvent", "KeyEvent", "MouseEvent"]


# --- painting ---------------------------------------------------------------


def test_paint_is_the_right_shape(state):
    lines = paint(state, colour=False)
    assert len(lines) == state.rows
    assert "demo" in lines[0]
    assert f"/{len(state.document)}" in lines[0]


def test_paint_shows_checkbox_state(state):
    plain = paint(state, colour=False)
    assert any("[ ] include archived" in line for line in plain)
    _click(state, 2)
    assert any("[x] include archived" in line for line in paint(state, colour=False))


def test_paint_shows_the_cursor_in_a_focused_field(state):
    field = state.document.lines[1]
    _click(state, 1)
    field.value = "abc"
    field.cursor = 1
    assert any("[a|bc]" in line for line in paint(state, colour=False))


def test_paint_stays_ascii_encodable(state):
    """The Windows console defaults to cp1252 and a box-drawing cursor crashed it."""
    _click(state, 1)
    state.document.lines[1].value = "abc"
    for line in paint(state, colour=False):
        line.encode("cp1252")      # raises if it would crash a console


# --- widget kinds -----------------------------------------------------------


@pytest.mark.parametrize("tag,kind", [
    ("interactive.inputs", WidgetKind.INPUT),
    ("interactive.buttons", WidgetKind.BUTTON),
    ("urls.external", WidgetKind.LINK),
    ("media.images", WidgetKind.IMAGE),
    ("text.visible", WidgetKind.TEXT),
])
def test_the_content_tag_decides_the_widget(tag, kind):
    assert kind_for(_address(tag=tag)) is kind


# --- navigation -------------------------------------------------------------


def test_nav_reports_rather_than_raises_without_a_browser():
    nav = WebNav()
    for result in (nav.visit("https://x.test"), nav.scroll(), nav.back()):
        assert isinstance(result, NavResult) and result.ok is False
        assert "no browser" in result.detail


def test_enactment_is_not_dispatched_from_python():
    """`WebNav` no longer presses anything; the page's executor does.

    Selenium's selector engine stops at a shadow boundary, so dispatching
    from here could never reach a control inside a custom element -- and a
    dispatcher with less reach sitting beside one with more is worse than
    not having it, because it is the one that answers first. Both entry
    points now report that they moved rather than half-working.
    """
    class FakeDriver:
        current_url = "https://x.test/p"

        def find_element(self, by, value):        # pragma: no cover
            raise AssertionError("enactment must not resolve elements here")

        def execute_script(self, *a):             # pragma: no cover
            raise AssertionError("enactment must not script from here")

    nav = WebNav(FakeDriver())
    address = _address("/html/body/div[3]/a[2]")
    for result in (nav.click(address), nav.type_into(address, "q")):
        assert result.ok is False
        assert "Sensor.perform" in result.detail


def test_action_chain_encodes_the_composed_path():
    """An address round-trips to the [tag, ordinal, ...] the page resolves.

    Including the shadow boundary, which is the whole reason enactment moved
    into the page: `#shadow-root` is one more step here and a wall to any
    selector engine.
    """
    from vertiscope.sensing import Sensor

    plain = _address("/html/body/form/input[2]")
    assert Sensor.path_of(plain) == [
        "html", 1, "body", 1, "form", 1, "input", 2]

    shadowed = _address("/html/body/div[2]/#shadow-root/ul/li[3]/a/text()[1]")
    assert Sensor.path_of(shadowed) == [
        "html", 1, "body", 1, "div", 2, "#shadow-root", 1,
        "ul", 1, "li", 3, "a", 1, "#text", 1]

def test_controls_are_classified_from_labels_not_a_new_category():
    """Hand-written labels, landing in the buckets those words name.

    Kept, but demoted: this only checks that the words are spelled the same in
    the test and the implementation. It passed for the whole time the function
    was useless on real pages, because the real path never produces labels
    like these — see the tests below, which run the path instead.
    """
    pairs = [
        (_address("/html/body/nav/a[1]"), "Next page"),
        (_address("/html/body/nav/a[2]"), "Previous"),
        (_address("/html/body/form/input", "interactive.inputs"), "Search"),
        (_address("/html/body/aside/a"), "Filter by category"),
        (_address("/html/body/p"), "ordinary text"),
    ]
    roles = classify_controls(pairs)
    assert len(roles["pagination"]) == 2
    assert len(roles["search"]) == 1
    assert len(roles["filter"]) == 1


def _controls_of(html: str, url: str):
    """html -> pipeline -> trie -> markdown -> Document -> controls."""
    from vertiscope.markdown import render_trie
    from vertiscope.pipeline import run_pipeline
    from vertiscope.repl.model import Document
    from vertiscope.repl.nav import attach_context
    from vertiscope.trie import AddressTrie

    trie = AddressTrie.from_tagged(run_pipeline(html, url).tagged, url)
    document = Document.from_chunks(render_trie(trie, context_window=1200),
                                    url=url)
    # The same path `_cmd_controls` takes. Reading `document.lines` here
    # instead would test a listing production does not build.
    pairs = [(w.address, w.label) for w in document.controls()
             if w.address is not None]
    texts = [(w.address.xpath, w.label) for w in document.lines
             if w.address is not None and not w.interactive]
    return classify_controls(attach_context(pairs, texts))


PAGER_HTML = """
<html><body>
  <ul><li><a href="/a">Alpha</a></li><li><a href="/b">Beta</a></li></ul>
  <nav><ul class="pager">
    <li class="next"><a href="/page/2/">Next <span>&rarr;</span></a></li>
  </ul></nav>
</body></html>
"""


def test_a_pager_is_found_through_the_real_path():
    """The defect this replaced: the label handed to the classifier is a URL.

    A link's markdown rendering is `<href>`, so the classifier's input for
    every anchor was a path. The words it looks for live in the *text*, which
    the extractor attributes to the deepest element containing it — here the
    `li`, one level above the `a`. Joined by xpath, "Next →" reaches the
    classifier; unjoined, "/page/2/" does, and nothing matches.
    """
    roles = _controls_of(PAGER_HTML, "https://x.test/")
    labels = " ".join(context for _a, _l, context in roles["pagination"])
    assert "Next" in labels, f"pager not found; got {roles['pagination']}"
    assert len(roles["pagination"]) == 1


ASSET_HTML = """
<html><head>
  <link rel="stylesheet" href="/_next/static/chunks/main.css">
  <script src="/_next/static/chunks/app.js"></script>
</head><body><p>Nothing to page through.</p></body></html>
"""


def test_asset_urls_are_not_pagination():
    """A Next.js page reported eighty-four stylesheets as pagination.

    `"next" in "/_next/static/chunks/..."` is true, which is what a substring
    test over a URL buys. Matching whole words in the visible text does not.
    """
    roles = _controls_of(ASSET_HTML, "https://x.test/")
    assert roles["pagination"] == [], roles["pagination"]


NUMERIC_PAGER_HTML = """
<html><body><div class="paging">
  Total of 104 entries : <a href="/list?skip=0&amp;show=50">1-50</a>
  <a href="/list?skip=50&amp;show=50">51-100</a>
</div></body></html>
"""


def test_a_wordless_pager_is_found_by_its_target():
    """Some pagers have no words at all — only the href says what they do."""
    roles = _controls_of(NUMERIC_PAGER_HTML, "https://x.test/list")
    assert len(roles["pagination"]) == 2, roles["pagination"]


@pytest.mark.parametrize("label", [
    "home page", "About this page", "Page not found", "the next generation",
    "Read more about it", "back to top",
])
def test_ordinary_labels_containing_a_paging_word_are_not_pagers(label):
    """`page` was in both the direction set and the unit set.

    So "a direction word *and* a unit word" was satisfied by the single word
    `page`, and every label containing it classified as pagination — seen on
    a live page as three copies of "home page" before the rule had been used
    in anger.
    """
    from vertiscope.repl.nav import _is_pager

    assert not _is_pager(label)


def test_a_paging_parameter_on_someone_elses_listing_is_not_a_pager():
    """"The same listing at a different position" — the first half was missing.

    Hacker News's "past" links go to `hn.algolia.com/?query=…&page=0`: a
    paging parameter, on a different site's search results. Thirty-two story
    rows on one page classified as pagination because the check asked only
    "does this url page something".
    """
    from vertiscope.repl.nav import _is_paging_target

    here = "https://news.ycombinator.com/newest"
    assert _is_paging_target("?p=2", here, loose=True)
    assert _is_paging_target("/newest?p=3", here, loose=True)
    assert not _is_paging_target(
        "https://hn.algolia.com/?query=x&page=0", here)
    assert not _is_paging_target("https://other.test/list?page=2", here)


def test_a_slug_beginning_with_a_number_is_not_page_n():
    """`/p/25-years-of-blogitude` matched `/p/` plus digits."""
    from vertiscope.repl.nav import _is_paging_target

    assert not _is_paging_target(
        "https://instapundit.substack.com/p/25-years-of-blogitude")
    assert not _is_paging_target("https://x.test/page/2-things-i-learned")
    assert _is_paging_target("https://x.test/page/2/")
    assert _is_paging_target("https://x.test/catalogue/page-2.html")


def test_an_ambiguous_label_needs_a_paging_target_too():
    """"More" is Hacker News's pager and Associated Press's nav dropdown.

    Nothing in the label separates them, so the ambiguous words fire only
    when the target also looks like paging — on the same listing.
    """
    from vertiscope.address import ContentAddress
    from vertiscope.repl.nav import classify_controls

    def entry(url, href):
        return (ContentAddress(url=url, xpath="/html/body/a",
                               tag="urls.internal", accessor="href"),
                f"<{href}>", "More")

    hn = classify_controls([entry("https://news.ycombinator.com/newest",
                                  "?p=2")])
    ap = classify_controls([entry("https://apnews.com",
                                  "/hub/politics")])
    assert len(hn["pagination"]) == 1, "Hacker News's real pager was dropped"
    assert ap["pagination"] == [], "a nav dropdown classified as pagination"


@pytest.mark.parametrize("label", [
    "Todd Blanche is narrowly confirmed as attorney general",
    "type Transport struct { // Request. If the function returns",
    "a sort of thing",
    "filtering out the noise was the hard part of the project",
])
def test_prose_containing_a_filter_word_is_not_a_filter(label):
    """`any(word in text)` over a joined context matched paragraphs.

    One headline containing "narrowly" labelled 25 addresses as filters, and
    one Go doc comment containing "filter" labelled 134. The words are matched
    as whole short labels now, the same rule the pager words use.
    """
    from vertiscope.repl.nav import _is_filter

    assert not _is_filter(label)


@pytest.mark.parametrize("label", ["Filter", "sort by", "Refine search",
                                   "Sort · Filter · Narrow by"])
def test_a_real_filter_label_still_is_one(label):
    from vertiscope.repl.nav import _is_filter

    assert _is_filter(label)


def test_one_control_is_listed_once_not_once_per_address():
    """A link is several addresses: the anchor, its picture, its img.

    They nest and share a label, so a nav bar listed the same item eight
    times — Associated Press's front page reported 807 menu items. The
    outermost is kept, because that is the element a click should land on.
    """
    from vertiscope.address import ContentAddress
    from vertiscope.repl.nav import classify_controls

    def at(xpath):
        return ContentAddress(url="https://x.test/", xpath=xpath,
                              tag="urls.internal", accessor="href")

    entries = [
        (at("/html/body/nav/a"), "</next>", "Next"),
        (at("/html/body/nav/a/picture"), "</next>", "Next"),
        (at("/html/body/nav/a/picture/img"), "</next>", "Next"),
        (at("/html/body/footer/a"), "</next>", "Next"),   # a different control
    ]
    roles = classify_controls(entries)
    kept = [a.xpath for a, _l, _c in roles["pagination"]]
    assert kept == ["/html/body/nav/a", "/html/body/footer/a"], kept


def test_the_outermost_survives_whatever_order_they_arrive_in():
    from vertiscope.address import ContentAddress
    from vertiscope.repl.nav import classify_controls

    def at(xpath):
        return ContentAddress(url="https://x.test/", xpath=xpath,
                              tag="urls.internal", accessor="href")

    inner_first = [
        (at("/html/body/nav/a/img"), "</next>", "Next"),
        (at("/html/body/nav/a"), "</next>", "Next"),
    ]
    roles = classify_controls(inner_first)
    assert [a.xpath for a, _l, _c in roles["pagination"]] == \
        ["/html/body/nav/a"]


def test_a_permalink_is_not_a_pager():
    """`?p=123` is a WordPress permalink at least as often as page 123.

    The parameter list excludes the ambiguous spellings on purpose; this
    records that so re-adding `p` fails here rather than quietly widening
    what `controls` claims.
    """
    from vertiscope.repl.nav import _is_paging_target

    assert _is_paging_target("/list?page=3")
    assert _is_paging_target("/catalogue/page-2.html")
    assert _is_paging_target("/list?skip=50&show=50")
    assert not _is_paging_target("/?p=123")
    assert not _is_paging_target("/article?count=25")
    assert not _is_paging_target("javascript:void(0)")


class FakeBrowser:
    """A driver whose DOM changes when it is navigated.

    `execute_script` raises so `WebNav.html()` takes its `page_source`
    fallback — which is also what a driver that has lost its CDP connection
    does, so the fallback is worth exercising.
    """

    def __init__(self, pages, start):
        self.pages = pages
        self.current_url = start
        self.clicked = []
        self._dicts_sent = set()

    @property
    def page_source(self):
        return self.pages[self.current_url]

    def get(self, url):
        self.current_url = url

    def back(self):
        self.current_url = next(iter(self.pages))

    def execute_script(self, script, *args):
        """Speak the sensor's boundary contract, nothing more.

        Live rendering goes through the in-page sensor now, and there is no
        second path: parsing the DOM again on the Python side would be a
        second extraction implementation that can disagree with the first.
        So what a fake browser has to fake is the boundary — `boot` returns
        whether the handle took, `drain` returns one payload — and the REPL
        above it is exercised for real.
        """
        if "drain()" not in script:
            return True          # boot probe: the handle is installed
        # The dictionary is append-only *per sensor*, so its entries ship
        # once and every later drain sends none. Returning them again would
        # shift every interned id on this side after the first drain.
        handle = script.split("window['", 1)[-1].split("']", 1)[0]
        fresh = handle not in self._dicts_sent
        self._dicts_sent.add(handle)
        return _drain_payload(self.current_url, send_dict=fresh)

    def find_element(self, by, value):
        browser = self

        class Element:
            def click(self_inner):
                browser.clicked.append(value)
                browser.current_url = "https://x.test/two"

            def clear(self_inner):
                pass

            def send_keys(self_inner, keys):
                browser.current_url = "https://x.test/two"

        return Element()


PAGE_ONE = "<html><body><h1>Page One</h1><a href='/two'>Go</a></body></html>"
PAGE_TWO = "<html><body><h1>Page Two</h1><p>arrived</p></body></html>"

# One drain payload per page, in the sensor's own wire shape: an append-only
# string dictionary, and chunks whose lines are
# [depth, text, path, attrId, seq, taxonomyId, ruleId] with `path` a flat
# [tagId, ordinal, ...] run. Written out rather than generated so the
# contract this side decodes is visible in the test.
_DICT = ["body", "h1", "#text", "a", "p",
         "heading", "heading.tag", "link", "link.anchor",
         "paragraph", "text.visible", "href"]
_B, _H1, _TXT, _A, _P = 0, 1, 2, 3, 4
_HEAD, _HEADR, _LINK, _LINKR, _PARA, _PARAR, _HREF = 5, 6, 7, 8, 9, 10, 11


def _drain_payload(url, send_dict=True):
    if url.endswith("/two"):
        chunks = [{
            "id": 1, "path": [_B, 1], "digest": 222, "chars": 22,
            "lines": [
                [1, "Page Two", [_B, 1, _H1, 1, _TXT, 1], 0, 1, _HEAD, _HEADR],
                [1, "arrived", [_B, 1, _P, 1, _TXT, 1], 0, 1, _PARA, _PARAR],
            ],
        }]
    else:
        chunks = [{
            "id": 1, "path": [_B, 1], "digest": 111, "chars": 20,
            "lines": [
                [1, "Page One", [_B, 1, _H1, 1, _TXT, 1], 0, 1, _HEAD, _HEADR],
                [1, "/two", [_B, 1, _A, 1], _HREF, 0, _LINK, _LINKR],
                [1, "Go", [_B, 1, _A, 1, _TXT, 1], 0, 1, _LINK, _LINKR],
            ],
        }]
    return {"v": 1, "dict": list(_DICT) if send_dict else [],
            "chunks": chunks, "removed": [],
            "settled": True, "stats": {"errors": 0}}


def _live_repl():
    from vertiscope.repl.app import Repl
    from vertiscope.repl.nav import WebNav

    browser = FakeBrowser({"https://x.test/one": PAGE_ONE,
                           "https://x.test/two": PAGE_TWO},
                          "https://x.test/one")
    repl = Repl(nav=WebNav(browser))
    repl.render_live()
    return repl, browser


def test_a_live_repl_shows_the_page_it_is_on():
    repl, _browser = _live_repl()
    assert "Page One" in repl.render()


def test_navigating_live_re_renders_the_document():
    """The defect: every live action left the previous page on screen.

    `visit`, `back`, a click and a form submit each reported their result
    into the status line and touched nothing else, so the browser moved and
    the terminal did not. `WebNav.html()` — whose docstring is "the settled
    DOM, for re-running the pipeline after an action" — had no callers.
    """
    repl, _browser = _live_repl()
    repl.command("open https://x.test/two")
    rendered = repl.render()
    assert "Page Two" in rendered, rendered[:300]
    assert "Page One" not in rendered


def test_going_back_live_re_renders_too():
    repl, _browser = _live_repl()
    repl.command("open https://x.test/two")
    assert "Page Two" in repl.render()
    repl.command("back")
    assert "Page One" in repl.render()


def test_a_failed_navigation_keeps_the_current_document():
    """A dead action must not blank the screen it could not replace."""
    from vertiscope.repl.app import Repl
    from vertiscope.repl.nav import WebNav

    repl, browser = _live_repl()

    def explode(url):
        raise RuntimeError("connection refused")

    browser.get = explode
    repl.command("open https://x.test/two")
    assert "Page One" in repl.render()
    assert "connection refused" in repl.state.buffers.status


def test_an_offline_repl_is_unaffected():
    """No browser attached is the common case and must not raise."""
    from vertiscope.repl.app import Repl

    repl = Repl()
    assert repl.render_live() is False
    repl.command("back")
    assert repl.render_live(None) is False


@pytest.mark.parametrize("code,action", [
    (64, "wheel_up"), (65, "wheel_down"),
    (66, "none"), (67, "none"),          # horizontal wheel
    (68, "wheel_up"), (69, "wheel_down"),  # shift + wheel
])
def test_the_horizontal_wheel_does_not_scroll_the_document(code, action):
    """`up if (code & 3) == 0 else down` folded 66 and 67 onto scroll-down.

    A trackpad emits horizontal wheel ticks during any diagonal swipe, so the
    more sideways the gesture, the further the document scrolled down. There
    is nothing to pan here — lines are truncated, not scrolled sideways — so
    the tick is decoded and ignored rather than mistaken for a vertical one.
    """
    from vertiscope.repl.terminal import decode

    events = decode(f"\x1b[<{code};10;5M")
    assert len(events) == 1
    assert events[0].action == action


def test_a_horizontal_tick_leaves_the_viewport_alone():
    from vertiscope.repl.model import ReplState
    from vertiscope.repl.terminal import decode

    state = ReplState()
    state.document = Document.from_chunks([_chunk()], url="https://x.test/p")
    state.rows = 4
    before = state.top
    for event in decode("\x1b[<66;10;5M\x1b[<67;10;5M"):
        state.handle(event)
    assert state.top == before


def _input_widget(text="[ ] Quick search"):
    from vertiscope.markdown import MarkdownChunk, MarkdownLine
    from vertiscope.repl.model import Document

    address = _address("/html/body/form/input", "interactive.inputs", "text()")
    chunk = MarkdownChunk(url="https://x.test/", xpath="/html/body")
    chunk.lines = [MarkdownLine(0, text, address)]
    return Document.from_chunks([chunk], url="https://x.test/").lines[0]


def test_an_input_keeps_its_name_and_loses_its_brackets():
    """`[ ] Quick search` -> label "Quick search".

    The strip took `label[2:]` and then `rstrip("]")`, removing a bracket
    that is at the *front* of what is left. Every input in the REPL was
    labelled `] Quick search` and repainted as `[] Quick search]`.
    """
    widget = _input_widget()
    assert widget.kind is WidgetKind.INPUT
    assert widget.label == "Quick search"


def test_typing_into_a_field_does_not_erase_its_name():
    """`value or label` inside the brackets conflated two different things.

    An empty field displayed its name as though that were its contents, and
    the name vanished on the first keystroke — so a form with two fields
    filled in had nothing on screen saying which was which.
    """
    widget = _input_widget()
    assert "Quick search" in widget.render()
    widget.value = "einstein"
    rendered = widget.render()
    assert "einstein" in rendered and "Quick search" in rendered


def test_a_focused_field_keeps_its_name_too():
    from vertiscope.repl.terminal import _with_cursor

    widget = _input_widget()
    widget.value = "ein"
    widget.cursor = 3
    assert "Quick search" in _with_cursor(widget, colour=False)
    assert "Quick search" in _with_cursor(widget, colour=True)


@pytest.mark.parametrize("cut", [1, 2, 4, 7, 9])
def test_a_click_split_across_two_reads_is_still_one_click(cut):
    """Input arrives in whatever chunks the terminal hands over.

    `decode` is stateless, so `\\x1b[<0;10;5M` split after the fifth character
    decoded as the six keystrokes `;105M` — typed into whatever field had
    focus, which is exactly what the module docstring promises never happens.
    On a platform where `_drain` cannot batch (no `select` on a console
    handle) *every* sequence arrives one character at a time.
    """
    from vertiscope.repl.terminal import decode_stream

    whole = "\x1b[<0;10;5M"
    first, pending = decode_stream(whole[:cut])
    second, leftover = decode_stream(whole[cut:], pending)

    events = first + second
    assert leftover == ""
    assert len(events) == 1, [getattr(e, "action", None) for e in events]
    assert events[0].action == "press"
    assert (events[0].x, events[0].y) == (10, 5)


def test_a_lone_escape_fires_once_the_next_chunk_says_it_was_one():
    """The one genuine ambiguity, resolved by the next byte instead of a timer.

    A trailing ESC is the Escape key and the start of a sequence at the same
    time. It is held, because where the reader cannot batch that is exactly
    where every mouse sequence splits; and it is released as Escape as soon as
    the next chunk turns out not to continue it — with the following character
    intact, which merging the two would have eaten.
    """
    from vertiscope.repl.terminal import decode_stream

    events, pending = decode_stream("\x1b")
    assert events == [] and pending == "\x1b"

    events, pending = decode_stream("x", pending)
    assert [e.key for e in events] == ["escape", "x"]
    assert pending == ""


def test_an_escape_that_never_terminates_does_not_swallow_the_session():
    """A held tail is bounded, or one bad byte eats every keystroke after it."""
    from vertiscope.repl.terminal import decode_stream

    _events, pending = decode_stream("\x1b[" + "9" * 200)
    assert len(pending) < 200


def test_ordinary_typing_passes_through_the_stream_decoder():
    from vertiscope.repl.terminal import decode_stream

    events, pending = decode_stream("hello")
    assert "".join(e.key for e in events) == "hello"
    assert pending == ""


def test_the_repl_feed_carries_a_split_sequence_between_calls():
    """The state machine must see one click, not five keystrokes."""
    from vertiscope.repl.app import Repl

    repl = Repl()
    repl.state.document = Document.from_chunks([_chunk()], url="https://x.test/p")
    repl.state.rows, repl.state.cols = 10, 60

    whole = "\x1b[<0;3;2M"          # press on the first body line
    repl.feed(whole[:5])
    repl.feed(whole[5:])
    assert repl.state.focus == 0
    # No stray characters reached a field.
    assert all(not w.value for w in repl.state.document.lines)


def test_dropping_a_mark_is_not_silent():
    """Marks are kept on purpose; losing one to the bound must be visible.

    Truncating `history` and `trail` silently is right — they are logs. A
    mark is something the user chose to keep, so evicting the oldest is a
    small loss of their work, and an unannounced loss is the shape of most of
    the defects found in this codebase.
    """
    from vertiscope.address import ContentAddress
    from vertiscope.repl.model import Buffers

    buffers = Buffers(limit=3)
    for i in range(3):
        buffers.mark(ContentAddress(f"https://x.test/{i}", f"/html/body/p[{i}]",
                                    "text.visible", "text()"))
    assert "dropped" not in buffers.status

    buffers.mark(ContentAddress("https://x.test/4", "/html/body/p[4]",
                                "text.visible", "text()"))
    assert len(buffers.marks) == 3
    assert "dropped the oldest mark" in buffers.status
    assert "/html/body/p[0]" in buffers.status


@pytest.mark.parametrize("sequence,expected", [
    ("\x1b[A", ["up"]),          # normal cursor mode
    ("\x1bOA", ["up"]),          # application cursor mode
    ("\x1bOB", ["down"]),
    ("\x1bOF", ["end"]),
    ("\x1bOP", []),              # F1: unbound, and must not leak "P"
    ("\x1b[15~", []),            # F5: unbound CSI
    ("\x1bOAx", ["up", "x"]),    # the sequence ends where it ends
])
def test_an_unhandled_escape_does_not_leak_its_last_byte(sequence, expected):
    """The decoder's stated promise, applied to SS3 as well as CSI.

    `_skip_escape` walked a CSI sequence to its final byte but treated
    `ESC O A` as two characters, leaving the `A` to be emitted as printable
    text — so in application cursor mode an arrow key typed a literal letter
    into whatever field had focus. That is exactly the behaviour the module
    docstring says is worse than ignoring a key nobody bound.
    """
    from vertiscope.repl.terminal import decode

    assert [event.key for event in decode(sequence)] == expected


@pytest.mark.parametrize("depth", [0, 1, 3])
def test_a_click_places_the_cursor_where_the_column_says(depth):
    """Cursor placement, checked against the painted line rather than the maths.

    The offset the click path subtracts (`2*depth + 1`) and the offset the
    renderer introduces (indent, then the opening bracket) are written in two
    different modules. Asserting one against the other in a test would repeat
    whichever is wrong; this locates the field in the *painted* output and
    clicks a real column of it.
    """
    from vertiscope.markdown import MarkdownChunk, MarkdownLine
    from vertiscope.repl.model import Document, MouseEvent, ReplState
    from vertiscope.repl.terminal import paint

    address = _address("/html/body/form/input", "interactive.inputs", "text()")
    chunk = MarkdownChunk(url="https://x.test/", xpath="/html/body")
    chunk.lines = [MarkdownLine(depth, "[ ] Search", address)]

    state = ReplState()
    state.document = Document.from_chunks([chunk], url="https://x.test/")
    state.rows, state.cols = 10, 60
    widget = state.document.lines[0]
    widget.value = "telescope"

    painted = paint(state, colour=False)
    row = next(i for i, line in enumerate(painted) if "telescope" in line)
    column = painted[row].index("telescope")      # 0-based
    # Click the 'e' at index 4 of the value, in 1-based screen columns.
    state.handle(MouseEvent("press", column + 4 + 1, row + 1, 0))

    assert state.focus == 0
    assert widget.cursor == 4, painted[row]


class FakeStore:
    """Enough GraphStore to resolve an address and rebuild a page."""

    def __init__(self, chunk, addresses):
        self._chunk = chunk
        self._addresses = addresses

    def chunks(self, url=""):
        return [] if (url and url != self._chunk.url) else [self._chunk]

    def resolve_page(self, url):
        from vertiscope.graphstore import canonical_url

        if url == self._chunk.url:
            return url
        stored = canonical_url(self._chunk.url) or self._chunk.url
        return self._chunk.url if (canonical_url(url) or url) == stored else ""

    def addresses_of(self, cid):
        return self._addresses

    def address(self, aid):
        for address, value in self._addresses:
            if address.aid == aid:
                return address, value
        return None


def test_the_repl_opens_an_address_id(monkeypatch):
    """`where` prints an id; until now nothing accepted one back.

    Closing the loop inside the REPL matters more than it sounds: the id is
    the only handle that survives being copied out of a terminal, and the
    address is the one output type the whole pipeline produces.
    """
    from types import SimpleNamespace

    from vertiscope.repl.app import Repl

    chunk = _chunk("https://x.test/p")
    addresses = [(line.address, line.text) for line in chunk.lines]
    stored = SimpleNamespace(
        cid="c1", url=chunk.url, xpath=chunk.xpath, part=0,
        md="\n".join("  " * line.depth + line.text for line in chunk.lines))
    repl = Repl(store=FakeStore(stored, addresses))

    target = addresses[2][0]
    assert repl.command(f"open {target.aid}") is not False
    assert repl.state.focus is not None
    focused = repl.state.document.lines[repl.state.focus]
    assert focused.address is not None
    assert focused.address.aid == target.aid


def test_opening_an_unknown_id_does_not_pretend(monkeypatch):
    from types import SimpleNamespace

    from vertiscope.repl.app import Repl

    chunk = _chunk("https://x.test/p")
    addresses = [(line.address, line.text) for line in chunk.lines]
    stored = SimpleNamespace(
        cid="c1", url=chunk.url, xpath=chunk.xpath, part=0,
        md="\n".join(line.text for line in chunk.lines))
    repl = Repl(store=FakeStore(stored, addresses))
    assert repl._open_address("deadbeefdeadbeef") is False


def test_context_prefers_the_element_over_its_ancestors():
    """A wide ancestor must not label everything it contains.

    Without a preference the outermost text wins every descendant slot, and
    every link in a page footer gets the footer's first sentence as its name.
    """
    from vertiscope.address import ContentAddress
    from vertiscope.repl.nav import attach_context

    link = ContentAddress(url="https://x.test/", xpath="/html/body/div/a",
                          tag="urls.internal", accessor="href")
    entries = attach_context(
        [(link, "</b>")],
        [("/html/body", "the whole page"),
         ("/html/body/div/a", "Click me")],
    )
    assert entries[0][2] == "Click me"


# --- the app --------------------------------------------------------------


def _chunk(url="https://x.test/p"):
    chunk = MarkdownChunk(url=url, xpath="/html/body")
    chunk.lines = [
        MarkdownLine(0, "Heading", _address("/html/body/h1", "text.visible", "text()")),
        MarkdownLine(1, "<https://x.test/a>", _address("/html/body/a")),
        MarkdownLine(1, "( Submit )",
                     _address("/html/body/button", "interactive.buttons", "text()")),
    ]
    return chunk


def test_loading_chunks_builds_widgets():
    repl = Repl()
    repl.load_chunks([_chunk()])
    kinds = [w.kind for w in repl.state.document.lines]
    assert kinds == [WidgetKind.TEXT, WidgetKind.LINK, WidgetKind.BUTTON]


def test_button_labels_lose_their_rendering_marks():
    """The widget re-adds them from its own state, so it must not keep them."""
    repl = Repl()
    repl.load_chunks([_chunk()])
    button = repl.state.document.lines[2]
    assert button.label == "Submit"
    assert button.render().strip() == "( Submit )"


def test_unknown_commands_do_not_kill_the_repl():
    repl = Repl()
    assert repl.command("frobnicate the widget") is True
    assert "unknown command" in repl.state.buffers.status


def test_a_raising_command_does_not_kill_the_repl():
    repl = Repl()
    repl.load_chunks([_chunk()])
    assert repl.command("goto notanumber") is True
    assert repl.command("goto 9999") is True
    assert "out of range" in repl.state.buffers.status


def test_check_marks_the_address():
    repl = Repl()
    repl.load_chunks([_chunk()])
    repl.command("check 1")
    assert len(repl.state.buffers.marks) == 1
    assert repl.state.document.lines[1].checked is True


def test_find_scrolls_to_a_match():
    repl = Repl()
    repl.load_chunks([_chunk()])
    repl.command("find submit")
    assert repl.state.focus == 2


def test_quit_stops_the_loop():
    repl = Repl()
    assert repl.command("quit") is False
    assert repl.running is False


def test_feed_drives_the_state_from_raw_bytes():
    """The whole pointer path, end to end, from the bytes a terminal sends."""
    repl = Repl()
    repl.load_chunks([_chunk()])
    repl.state.rows, repl.state.cols = 10, 60
    row = repl.state.row_of(1)
    repl.feed(f"\x1b[<0;5;{row}M\x1b[<0;5;{row}m")
    assert repl.state.focus == 1


# --- against a real page ----------------------------------------------------


@pytest.mark.skipif(not MANIFEST.exists(), reason="frozen corpus absent")
def test_a_real_page_becomes_an_interactive_document():
    pages = [p for p in json.loads(MANIFEST.read_text())["pages"] if p.get("ok")]
    page = next((p for p in pages if p["slug"].startswith("books-toscrape")),
                pages[0])
    html = (CORPUS / f"{page['slug']}.html").read_text(
        encoding="utf-8", errors="replace")
    result = run_pipeline(html, page["url"], render=False)
    trie = AddressTrie.from_tagged(result.tagged, page["url"])
    chunks = render_trie(trie, context_window=1200)

    repl = Repl()
    repl.load_chunks(chunks, url=page["url"])
    state = repl.state
    assert len(state.document) > 100

    interactive = [w for w in state.document.lines if w.interactive]
    assert interactive, "a real page produced no interactive widget"
    for widget in interactive[:20]:
        assert widget.address is not None
        assert widget.address.xpath.startswith("/")

    # scroll the whole document and click whatever is under a fixed point
    clicked = 0
    while state.top < state.max_top:
        line = state.hit(5, state.header_rows + 1)
        if line is not None and state.document.lines[line].interactive:
            _click(state, line)
            clicked += 1
        state.scroll(state.body_rows)
    assert clicked > 0
    assert state.top == state.max_top


def test_a_heading_control_keeps_its_label_and_its_marker():
    """`##### ( Products )` — the strip tested a *leading* `( `.

    Adding the heading marker in front moved it, so every mark-strip in
    `from_chunks` stopped firing and the button's label became the whole
    rendered string, repainted as `( ##### ( Products ) )`. Exactly the class
    of the `] Quick search` input bug: a renderer changed without its parser.
    """
    from vertiscope.markdown import render_trie
    from vertiscope.pipeline import run_pipeline
    from vertiscope.repl.model import Document
    from vertiscope.trie import AddressTrie

    url = "https://x.test/"
    trie = AddressTrie.from_tagged(
        run_pipeline("<html><body><h5><button>Products</button></h5>"
                     "</body></html>", url).tagged, url)
    doc = Document.from_chunks(render_trie(trie, context_window=1200), url=url)
    button = next(w for w in doc.lines if w.kind is WidgetKind.BUTTON)

    assert button.label == "Products", button.label
    assert button.heading == "##### "
    assert button.render() == "##### ( Products )"


def test_an_ordinary_control_carries_no_heading_marker():
    from vertiscope.markdown import render_trie
    from vertiscope.pipeline import run_pipeline
    from vertiscope.repl.model import Document
    from vertiscope.trie import AddressTrie

    url = "https://x.test/"
    trie = AddressTrie.from_tagged(
        run_pipeline("<html><body><form><button>Send</button></form>"
                     "</body></html>", url).tagged, url)
    doc = Document.from_chunks(render_trie(trie, context_window=1200), url=url)
    button = next(w for w in doc.lines if w.kind is WidgetKind.BUTTON)
    # Indented, because the button sits inside the form: depth is
    # separate from the heading marker and both belong in `render`.
    assert button.heading == ""
    assert button.render().strip() == "( Send )"
