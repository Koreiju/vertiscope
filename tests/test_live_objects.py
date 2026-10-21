"""The callable interface, driven end to end against a real browser.

docs/CALLABLE_INTERFACE.md. The loop this holds is the one the design exists
for: open a page, descend into it, type into a field, press a link, have the
new page arrive without asking for it, and go back.

Two properties matter more than the mechanics and are asserted directly:

* **The object tree is the trie**, so nothing here names a node for what it is
  *for*. `form` is `form`; `ol` is `ol`. If a class named `Search` or `Result`
  ever appears, agnosticism has been lost and these tests should be the thing
  that notices.
* **A label is what a reader sees.** An anchor's own leaf is its href and its
  words live a level deeper, so labelling from the nearest leaf named every
  link after its target -- three list items reading "live_target.html" where
  the page says "Go to the target page". The TUI made this mistake once
  already.

    VERTISCOPE_LIVE=1 python -m pytest tests/test_live_objects.py -q
"""

import os
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
START = (ROOT / "tests" / "fixtures" / "live_start.html").resolve().as_uri()
TARGET_NAME = "live_target.html"

LIVE = pytest.mark.skipif(
    not os.environ.get("VERTISCOPE_LIVE"),
    reason="needs a real browser; set VERTISCOPE_LIVE=1")


@pytest.fixture
def session():
    """A browser for one test, given back however the test ends."""
    import vertiscope.live as live

    live.close()
    yield live
    live.close()


# --- reading ------------------------------------------------------------------


@LIVE
def test_a_page_opens_onto_its_document_element(session):
    out = repr(session.Page(START))
    assert "Page(" in out
    assert "body(1)" in out


@LIVE
def test_descending_shows_the_pages_own_structure(session):
    session.Page(START)
    out = repr(session.body(1))
    # The tags the page actually wrote, and no name for what they are for.
    assert "header(1)" in out
    assert "form(1)" in out
    assert "ol(1)" in out
    for invented in ("Search", "Result", "Nav", "Menu", "Card"):
        assert "%s(" % invented not in out, invented


@LIVE
def test_a_label_is_the_readers_words_not_the_target(session):
    """The href bug, planted. `live_target.html` is where the link goes;
    "Go to the target page" is what the page shows."""
    session.Page(START)
    session.body(1)
    out = repr(session.ol(1))
    assert "Go to the target page" in out
    assert TARGET_NAME not in out


@LIVE
def test_counts_are_counted_from_tags(session):
    session.Page(START)
    out = repr(session.body(1))
    assert "1button" in out and "1input" in out


@LIVE
def test_a_handle_is_a_slice_of_the_address(session):
    session.Page(START)
    session.body(1)
    node = session.ol(1)
    assert node.handle() == "ol(1)"
    assert node.where().endswith("/html/body/ol")


# --- moving about -------------------------------------------------------------


@LIVE
def test_up_returns_to_the_parent(session):
    session.Page(START)
    session.body(1)
    session.ol(1)
    session.li(1)
    out = repr(session.up())
    assert out.startswith("ol(1)")


@LIVE
def test_top_returns_to_the_document(session):
    session.Page(START)
    session.body(1)
    session.ol(1)
    assert "Page(" in repr(session.top())


# --- acting -------------------------------------------------------------------


@LIVE
def test_typing_into_a_field(session):
    session.Page(START)
    session.body(1)
    session.form(1)
    node = session.input(1) << "glacier retreat"
    assert node.handle() == "input(1)"


@LIVE
def test_pressing_a_link_loads_the_new_page_by_itself(session):
    """The whole point of the loop: no second call to say "now go and read
    what you just navigated to"."""
    session.Page(START)
    session.body(1)
    session.ol(1)
    session.li(1)
    out = repr(session.a(1)())
    assert TARGET_NAME in out
    assert "The target page" in out


@LIVE
def test_back_returns_and_refolds(session):
    session.Page(START)
    session.body(1)
    session.ol(1)
    session.li(1)
    session.a(1)()
    out = repr(session.back())
    assert "live_start.html" in out
    assert "form(1)" in repr(session.body(1))


# --- the safety rule reaches the objects, not only the module ------------------


@LIVE
def test_a_refused_target_is_not_visited(session):
    from vertiscope.live import Refused

    session.Page(START)
    with pytest.raises(Refused):
        session.Page("https://x.test/checkout")


# --- what the live site taught, which no fixture could ------------------------


@LIVE
def test_a_radio_is_not_written_into(session):
    """duckduckgo's first `<input>` in document order is
    `<input name="chip-select" type="radio">`, and its search box is a
    `<textarea>`. Sending the radio `clear()` produced a Marionette stack
    trace ending "Unable to clear element that cannot be edited" -- true, and
    no use to anyone deciding what to do next."""
    session.Page(START)
    session.body(1)
    radios = [n for n in session.acts("input")
              if n.where().endswith("input[2]")]
    assert radios, "the fixture's radio is missing from the listing"
    with pytest.raises(TypeError) as caught:
        radios[0].type("anything")
    assert "not writable" in str(caught.value)
    assert "press it instead" in str(caught.value)


@LIVE
def test_a_password_field_is_refused_not_merely_rejected(session):
    """A password field IS writable in the mechanical sense, which is exactly
    why refusing it cannot be left to the writability check. It raises
    `Refused`, the same class a sign-in label raises, so a caller handling
    safety handles both."""
    from vertiscope.live import Refused

    session.Page(START)
    session.body(1)
    fields = [n for n in session.acts("input") if "pw" in n.where()
              or n.where().endswith("form[2]/input")]
    assert fields, "the fixture's password field is missing"
    with pytest.raises(Refused):
        fields[0].type("hunter2")


@LIVE
def test_the_affordance_listing_is_complete(session):
    """It stopped at fourteen once, and the page's only `<textarea>` fell off
    the end -- so the listing said nothing was writable on a page with a
    search box in the middle of it. A truncated list that does not say it is
    truncated is a display telling a lie."""
    session.Page(START)
    session.body(1)
    every = session.acts()
    inputs = session.acts("input")
    assert len(inputs) >= 3, [n.where() for n in inputs]
    assert all(n.tag == "input" for n in inputs)
    assert len(every) >= len(inputs)


@LIVE
def test_a_flat_listing_is_addressed_by_position(session):
    """`button(1)` is an ordinal within its own parent, so a flat list of
    affordances repeats it -- duckduckgo's front page shows five separate
    `button(1)`. Position is the only unambiguous handle across such a
    list, and `.where()` still gives the real address."""
    session.Page(START)
    session.body(1)
    every = session.acts()
    assert session.act(0).where() == every[0].where()
    assert session.act(1).where() == every[1].where()


# --- pressing what a click cannot simply have --------------------------------

AWKWARD = (ROOT / "tests" / "fixtures" / "live_awkward.html").resolve().as_uri()


def _link(session, needle):
    for node in session.acts("a"):
        if needle in node.where() or needle in node._target():
            return node
    return None


@LIVE
def test_a_link_below_the_fold_is_scrolled_to_and_clicked(session):
    """A page that has not been scrolled has most of its links outside the
    viewport, and Marionette refuses to click what it cannot reach. Driving a
    live results page, the first candidate raised "could not be scrolled into
    view" and the caller got a stack trace where it wanted a page.

    The fold reads no layout; an actuator has to. Same split the scroller
    already makes.
    """
    session.Page(AWKWARD)
    session.body(1)
    far = session.acts("a")[-1]
    out = repr(far.press())
    assert TARGET_NAME in out, out[:200]
    assert not session._S.clicked_via_href, "it fell back instead of clicking"


@LIVE
def test_a_zero_sized_link_falls_back_to_its_target(session):
    """Still unreachable after scrolling: an overlay, a consent wall, or an
    anchor drawn at zero size -- which is how duckduckgo draws a promo link.

    A link's job is its destination and the click was only the means, so the
    target is followed and the fallback is recorded rather than hidden. It is
    recorded because "tries == 1" passed a check while the click was still
    failing, and a flag is what makes the difference observable.
    """
    session.Page(AWKWARD)
    session.body(1)
    zero = _link(session, "live_target")
    assert zero is not None
    out = repr(zero.press())
    assert TARGET_NAME in out, out[:200]
    assert session._S.clicked_via_href, "expected the fallback to be used"


@LIVE
def test_the_fallback_does_not_route_around_the_refusal(session):
    """The dangerous half. The fallback navigates directly, so it must ask
    the same question the click asked -- otherwise an unclickable `/checkout`
    link becomes a way to reach checkout that a clickable one is not."""
    from vertiscope.live import Refused

    session.Page(AWKWARD)
    session.body(1)
    danger = _link(session, "/checkout/")
    assert danger is not None, [n._target() for n in session.acts("a")]
    with pytest.raises(Refused):
        danger.press()


# --- a label is content, never the fold's own bookkeeping ---------------------


@LIVE
def test_a_control_with_no_words_is_not_labelled_with_its_tag(session):
    """Every `<input>` on every page used to label itself `'input'`.

    Its only leaf is `@control|search.queryform/textbox`, whose value is the
    tag name -- the fold's own classification, which `resolvable` already
    calls synthetic and scores neither right nor wrong. Falling back to it
    printed machine bookkeeping in the one column that tells a reader what a
    control is.

    An empty label is the honest answer for a control that says nothing.
    """
    session.Page(START)
    session.body(1)
    fields = session.acts("input")
    assert fields, "the fixture has inputs"
    import vertiscope.live as live

    for node in fields:
        label = live._label_of(node._t, 40)
        assert label.strip().lower() != "input", node.where()


@LIVE
def test_a_control_that_does_have_words_still_shows_them(session):
    """Non-vacuity: suppressing the annotation must not suppress real text.
    A `<button>Search</button>` says Search, and the fixture's labels say
    what they say."""
    session.Page(START)
    session.body(1)
    import vertiscope.live as live

    labels = {live._label_of(n._t, 40) for n in session.acts()}
    assert "Search" in labels, labels
    assert any("Search the fixtures" in x for x in labels), labels


# --- the cartesian view -------------------------------------------------------


@LIVE
def test_the_drawing_puts_things_where_the_page_puts_them(session):
    """The tree says what contains what; the drawing says what sits BESIDE
    what. They are different facts about one page, and the second is the one
    an indented listing cannot express -- a sidebar reads as a column here
    and as a deep branch there, and only one of those is what a reader sees.

    The fixture's `<label>` and `<button>` are siblings in one form, drawn on
    one row. In the tree they are two lines at the same depth, which says
    nothing about them being side by side.
    """
    session.Page(START)
    session.body(1)
    drawing = session.wire(64)
    assert len(drawing) > 0
    rows = [set(n.tag for n in drawing[i]) for i in range(len(drawing))]
    assert any({"label", "button"} <= row for row in rows), rows


@LIVE
def test_a_box_on_the_drawing_is_a_node(session):
    """A drawing you can only look at is a screenshot. Every box carries its
    address, so it can be read, pressed or asked where it is."""
    session.Page(START)
    session.body(1)
    drawing = session.wire(64)
    boxes = [n for row in range(len(drawing)) for n in drawing[row]]
    assert boxes
    for node in boxes:
        assert node.where().startswith("/html"), node.where()
        assert node.handle()


@LIVE
def test_pressing_a_box_from_the_drawing_navigates(session):
    """The whole point of the boxes being nodes."""
    session.Page(START)
    session.body(1)
    drawing = session.wire(64)
    links = [n for n in drawing.acts() if n.tag == "a"]
    assert links, "the fixture's links are missing from the drawing"
    out = repr(links[0].press())
    assert TARGET_NAME in out, out[:200]


@LIVE
def test_the_drawing_is_addressed_by_row(session):
    """`wire()[7]` is what is on row 7. The row number is the handle, which
    is what makes the picture usable rather than only readable."""
    session.Page(START)
    session.body(1)
    drawing = session.wire(64)
    assert "  0|" in repr(drawing)
    assert isinstance(drawing[0], list)
    assert len(drawing.rows) == len(drawing)


@LIVE
def test_a_node_with_nothing_drawn_gives_an_empty_drawing(session):
    """Rather than raising. A leaf with no rendered text is a legitimate
    thing to ask about."""
    session.Page(START)
    session.body(1)
    empty = [n for n in session.acts("input")]
    assert empty
    drawing = empty[0].wire(40)
    assert len(drawing) == 0
    assert drawing.acts() == []
