"""The anchor's affordance has to reach the line a reader sees.

The affordance is CARRIED, in `inline`, never promoted into `line.address`:
that slot is the one thing the store persists per line, and the crawl reads
it back to build its frontier. See
`test_the_address_slot_is_left_exactly_as_the_render_chose_it`.

`interactive.links` is in `_SUPPRESSED_TAGS` for a good rendering reason: an
anchor also yields its href and its words, so drawing its control unit too
would print `[a]` beside them. But `_render_unit` suppressed by returning
None, and a unit that draws no line leaves no address -- so suppressing the
RENDERING silently discarded the ADDRESS, the only thing that says a line is
pressable.

Measured over the 136-page corpus before the fix: 71,866 `interactive.links`
addresses made, 7,325 surviving anywhere in the output. 89.8% lost, against
0.2% of inputs and 0.1% of forms, which have no competing unit to be
suppressed in favour of. Anchors are 88% of every affordance on the corpus.
"""

from vertiscope.core.content_tagger import ContentTagger
from vertiscope.core.shadow_html_parser import ShadowDOM
from vertiscope.markdown import render_trie
from vertiscope.trie import AddressTrie


def _render(html, window=900):
    trie = AddressTrie.from_tagged(
        ContentTagger(ShadowDOM(html)).tag(), "https://x.test/")
    return [ln for chunk in render_trie(trie, context_window=window)
            for ln in chunk.lines if ln.text.strip()]


def _all_addresses(line):
    return (line.address,) + tuple(line.inline) + tuple(line.absorbed)


SOLO = "<html><body><a href='/solo.html'>Solo link</a></body></html>"
PROSE = ("<html><body><p>See <a href='/next.html'>the next page</a> and "
         "<a href='/other.html'>another</a> now.</p></body></html>")
#: One document with both shapes, so the anchor is a sibling of the paragraph
#: rather than folded into the body. Concatenating the two constants above
#: nests a second `<html>` inside the first and the anchor collapses again.
MIXED = ("<html><body><p>See <a href='/next.html'>the next page</a> and "
         "<a href='/other.html'>another</a> now.</p>"
         "<a href='/solo.html'>Solo link</a></body></html>")


def test_the_affordance_is_reachable_from_the_line_that_draws_it():
    """The property that actually matters, in either shape.

    Whether the control lands in the address slot or in `inline` depends on
    whose element the line is addressed to, and that is a rendering detail: a
    page with nothing but an anchor collapses into its body, so the line is
    the BODY's and the anchor rides inline. A consumer asking "can this line
    be pressed" must not have to know which happened.
    """
    for html in (SOLO, PROSE, MIXED):
        lines = [ln for ln in _render(html) if "link" in ln.text.lower()
                 or "page" in ln.text.lower()]
        assert lines, "the anchor was not drawn at all"
        assert any(a.is_control for ln in lines for a in _all_addresses(ln)), \
            "no line carries the anchor's affordance: %r" % html[:60]


def test_the_address_slot_is_left_exactly_as_the_render_chose_it():
    """The crawl depends on this, and it is not obvious.

    `line.address` is the only address the store persists per line -- the
    `Anchors` edge is one per line by contract -- and `Workspace.links_from`
    reads it back to build the crawl frontier, because "a link is a `urls.*`
    address, which the trie already holds" and there is no second extractor.

    An earlier version of this pass promoted the control into that slot when
    the line was the anchor. It read well, and it pushed the anchor's
    `urls.internal` address out of the store: a page full of anchors produced
    an empty frontier, and `test_links_come_from_the_stored_addresses` failed.
    So the affordance goes to `inline` and the slot is never touched.
    """
    solo = [ln for ln in _render(MIXED) if "Solo link" in ln.text]
    assert solo, "the solo anchor was not drawn"
    assert solo[0].address.is_url, \
        "the anchor's line lost the url address the crawl frontier reads"


def test_the_affordance_never_displaces_a_url_anywhere():
    """Stated as a property over a whole page, not one line.

    Every url address the render put on a line before this pass must still be
    on that line after it, or some page's frontier silently shortens.
    """
    for html in (SOLO, PROSE, MIXED):
        for line in _render(html):
            urls = [a for a in _all_addresses(line) if a.is_url]
            assert len(urls) == len({a.key() for a in urls}), \
                "a url address was duplicated onto a line"
        assert any(a.is_url for ln in _render(html)
                   for a in _all_addresses(ln)), \
            "a page with anchors kept no url address at all: %r" % html[:50]


def test_the_url_stays_reachable_from_the_anchor_line():
    """`graphstore._link_hyperlinks` reads `line.address` and `line.inline`.

    A url that fell out of both would take its link edge with it, trading the
    affordance for the graph. The pass only appends, so this holds by
    construction -- asserted because "only appends" is a property of the code
    that a later edit can quietly stop honouring.
    """
    line = [ln for ln in _render(SOLO) if "Solo link" in ln.text][0]
    assert any(a.is_url for a in _all_addresses(line)), \
        "the anchor's href stopped being reachable from its line"


def test_anchors_folded_into_prose_ride_inline():
    """A sentence has one address slot and can hold several anchors.

    Promoting one of them would have to pick a link and silently drop the
    rest, so folded anchors go to `inline` -- which is already defined as the
    addresses a line merged and a reader can act on there.
    """
    line = [ln for ln in _render(PROSE) if "next page" in ln.text][0]
    controls = [a for a in _all_addresses(line) if a.is_control]
    assert len(controls) == 2, \
        "expected both folded anchors to be reachable, got %d" % len(controls)
    assert sum(1 for a in _all_addresses(line) if a.is_url) == 2, \
        "both destinations must stay reachable too"


def test_a_control_address_is_never_claimed_twice():
    """One element, one line: `anchors` is one key per line.

    Claiming an element on every line that mentions it would repeat the same
    control key down the chunk and make the positional contract meaningless.
    """
    lines = _render(MIXED)
    keys = [a.key() for ln in lines for a in _all_addresses(ln)
            if a.is_control]
    assert len(keys) == len(set(keys)), "a control was claimed by two lines"


def test_the_window_does_not_change_what_is_reachable():
    """The pass is trie-derived, so it must not move with the chunker.

    The same correction the prose fold and the collapse-naming both needed:
    a pass whose result depends on how the descent happened to cut is not a
    property of the document. `_render_sized` runs speculatively at every
    level, which is what makes render-time collection unsafe.
    """
    inner = PROSE.split("<body>")[1].split("</body>")[0]
    html = MIXED.replace("</body></html>", inner * 3 + "</body></html>")
    wide = {a.key() for ln in _render(html, 4000) for a in _all_addresses(ln)}
    narrow = {a.key() for ln in _render(html, 200) for a in _all_addresses(ln)}
    assert wide == narrow, \
        "reachable addresses differ by window: %d vs %d" % (len(wide), len(narrow))


NO_HREF = ("<html><body><a>Disable MathJax</a>"
           "<p>other words here</p></body></html>")


def test_an_anchor_with_no_href_still_says_its_words():
    """Content loss, not merely a missing affordance.

    `_dedupe`'s exact-tie branch keeps the `interactive.links` unit and drops
    the `text.visible` one carrying the same string. `_render_unit` then
    suppresses `interactive.links` unless it is `alone` -- and `alone` was
    asked of the units COLLECTED rather than the units that SURVIVED, so the
    lone remaining unit looked accompanied and suppressed itself. Neither
    drew, and the page's words disappeared: not unpressable, gone.

    `<a>` with no href is the exact case the `alone` escape was written for
    (arxiv's `Disable MathJax`), which is what makes this worth pinning.
    """
    texts = [ln.text for ln in _render(NO_HREF)]
    assert any("Disable MathJax" in t for t in texts), \
        "the anchor's words are absent from the render: %r" % texts


def test_that_anchor_is_also_an_affordance():
    """And having said its words, it must be pressable."""
    lines = [ln for ln in _render(NO_HREF) if "Disable MathJax" in ln.text]
    assert lines, "the anchor was not drawn"
    assert any(a.is_control for a in _all_addresses(lines[0])), \
        "the drawn anchor carries no affordance address"


def test_the_repl_lists_every_drawn_control():
    """The object model facade is the consumer this has to reach.

    `Document.controls()` walks line-owning widgets and `line.inline` alike,
    so a control the render carries reaches the terminal listing. Asserted
    against the REPL rather than the render because the render being right
    is not the same as the REPL seeing it -- `_KIND_BY_TAG` records a version
    where the page drew its controls and the REPL read them as prose.
    """
    from vertiscope.repl.model import Document

    html = ("<html><body><p>Read <a href='/n.html'>the next page</a> now.</p>"
            "<a>Disable MathJax</a>"
            "<span onclick='go()'>Expand all</span>"
            "<button>Add to basket</button>"
            "<input placeholder='Search books'></body></html>")
    trie = AddressTrie.from_tagged(
        ContentTagger(ShadowDOM(html)).tag(), "https://x.test/")
    doc = Document.from_chunks(render_trie(trie, context_window=1500),
                              url="https://x.test/")
    labels = " | ".join(w.label for w in doc.controls())
    for expected in ("next page", "Disable MathJax", "Expand all",
                     "Add to basket", "Search books"):
        assert expected in labels, \
            "%r missing from the REPL controls listing: %s" % (expected, labels)


DOUBLE = ("<html><body><button onclick='go()'>Go Back</button>"
          "<p>other words</p></body></html>")


def test_one_element_does_not_say_the_same_thing_twice():
    """`<button onclick>` is two detections and one control.

    `interactive.buttons` is valued by `_own_name` and
    `interactive.event_handlers` by `button[onclick]`. They share no tokens,
    so `_dedupe` keeps both -- correctly, on what a value comparison can see.
    The duplication appears only when `_render_unit` draws BOTH from
    `text_at[owner]`, and numpy's docs printed `( Go Back )` twice. 208 lines
    over the corpus, 203 of them this pair.
    """
    drawn = [ln.text for ln in _render(DOUBLE) if "Go Back" in ln.text]
    assert len(drawn) == 1, "the same control drew %d lines: %r" % (
        len(drawn), drawn)


def test_the_dropped_duplicate_keeps_its_address():
    """Suppressing a rendering is not licence to discard an address.

    The `onclick` half of that button is what makes it pressable on the live
    path, so the second detection rides on the surviving line's `inline` --
    the same lesson `_carry_affordance` records for suppressed anchors.
    """
    line = [ln for ln in _render(DOUBLE) if "Go Back" in ln.text][0]
    tags = {a.tag for a in _all_addresses(line)}
    assert "interactive.event_handlers" in tags, \
        "the handler address was dropped with the duplicate line: %s" % tags


ARIA_SUPERSET = ("<html><body>"
                 "<button aria-label='Move Main menu to sidebar'>move to sidebar"
                 "</button><p>filler text</p></body></html>")


def test_a_control_that_did_not_survive_cannot_consume_its_text():
    """Wikimedia's sidebar toggle drew nothing at all.

    Three units at one element: the button (`move to sidebar`), the visible
    text (the same string), and the `aria-label` (`Move Main menu to
    sidebar`, a superset of both). `_dedupe` keeps the aria-label and drops
    the other two -- correctly, it is the fullest spelling.

    But `consumed` was built from the units COLLECTED, so it still said "a
    control will speak for this element" and the surviving aria-label was
    skipped in deference to a button that no longer existed. A page showing
    `move to sidebar`, `hide` and `Cookie Settings` said none of them.

    Third instance of the same trap in one function: `alone` had it, and the
    url branch already records "taken from `kept`, not from `units`".
    """
    texts = " | ".join(ln.text for ln in _render(ARIA_SUPERSET))
    assert "sidebar" in texts.lower(), \
        "the element drew nothing: %r" % texts


def test_the_consumed_rule_still_prevents_its_own_duplication():
    """The rule exists for `( Add to basket ) / Add to basket`.

    Loosening it must not bring that back: a button whose words are its own
    text draws exactly one line.
    """
    lines = [ln.text for ln in
             _render("<html><body><button>Add to basket</button>"
                     "<p>filler text</p></body></html>")]
    said = [t for t in lines if "Add to basket" in t]
    assert len(said) == 1, "the control and its text both drew: %r" % said


def _controls(html, window=900):
    from vertiscope.repl.model import Document
    trie = AddressTrie.from_tagged(
        ContentTagger(ShadowDOM(html)).tag(), "https://x.test/")
    doc = Document.from_chunks(render_trie(trie, context_window=window),
                              url="https://x.test/")
    return doc.controls()


def test_a_control_the_render_addressed_as_prose_is_still_pressable():
    """Visible and inert is worse than absent -- this module says so.

    Wikimedia's `<button aria-label="Move Main menu to sidebar">` draws as
    `text.accessible`, because the aria-label subsumes the button's own words.
    The words reach the page and the affordance did not reach the REPL.
    """
    controls = _controls(ARIA_SUPERSET)
    assert [w.kind.name for w in controls] == ["BUTTON"], \
        "expected one pressable button, got %s" % [
            (w.kind.name, w.label) for w in controls]


def test_carrying_an_affordance_never_doubles_one():
    """The widening must not claim two affordances where the page has one.

    A sentence with two links carries both their url addresses AND both their
    `interactive.links` ones; the spans cover those elements already. A
    `<button onclick>` is addressed as a button and carries its handler.
    Neither may list twice.
    """
    for html, expected in (
        ("<html><body><p>See <a href='/n'>next page</a> and "
         "<a href='/o'>another</a> now.</p></body></html>", 2),
        ("<html><body><button onclick='go()'>Go Back</button>"
         "<p>filler</p></body></html>", 1),
        ("<html><body><button>Add to basket</button>"
         "<p>filler</p></body></html>", 1),
    ):
        controls = _controls(html)
        assert len(controls) == expected, \
            "%d controls for %r: %s" % (len(controls), html[:40],
                                        [(w.kind.name, w.label) for w in controls])


def test_every_listed_control_is_addressed_once():
    """One (line, address) pair per control, corpus-shaped page."""
    html = ("<html><body>"
            "<p>See <a href='/n'>next page</a> now.</p>"
            "<button aria-label='Move Main menu to sidebar'>move to sidebar</button>"
            "<button onclick='go()'>Go Back</button>"
            "<input placeholder='Search books'>"
            "<a>Disable MathJax</a></body></html>")
    seen = [(w.line, w.address.key() if w.address else "")
            for w in _controls(html, window=1500)]
    assert len(seen) == len(set(seen)), "a control was listed twice: %s" % seen
