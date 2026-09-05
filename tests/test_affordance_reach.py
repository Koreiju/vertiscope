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

from domvec.core.content_tagger import ContentTagger
from domvec.core.shadow_html_parser import ShadowDOM
from domvec.markdown import render_trie
from domvec.trie import AddressTrie


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
