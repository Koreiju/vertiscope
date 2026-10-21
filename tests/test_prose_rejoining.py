"""A page's prose must read as prose, not as a serialised tree.

Reported from a live duckduckgo session, of the rendered document: "more
HTML rendering and less JSON-ifying", and "not a fan of all the duplicate
fields". Measured on that page: 451 lines, of which 129 were surplus
repeats, 18 were an ARIA role drawn as a line of text, and 19 were fragments
of something a reader sees as one thing -- `0`, `/` and `500` on three
lines, being a character counter.

Three causes, none of them the same:

1. `_join_inline` required a text node to sit INSIDE an inline element, so
   `<p>text <b>bold</b> more</p>` rejoined the bold run and left the
   paragraph's own two fragments apart. The guard was standing in for
   document order -- it stopped a run joining across an intervening block --
   and since order is observed rather than derived, adjacency does that job.

2. `/` passed `_looks_like_url` on its prefix alone, and `_join_inline`
   refuses to join a url to prose. A prefix now has to lead somewhere.
   (The counter itself still does not join -- see the test below for why
   that limit exists and what it protects.)

3. The sensor emitted `@role` as a content unit. A role is the author naming
   what an element IS, which the fold already reads to compute RENDER_CLASS;
   emitted again it becomes a line of the document reading `navigation`.
   The exclusion for `presentation`/`none` was written for two values and
   the argument never depended on which value it was.

What is NOT fixed here, and is the larger half: a paragraph interrupted by a
link still renders as text / link / text on three lines, because a link
breaks the run by design. Inlining `[label](url)` into the sentence is the
BROWSER_PIVOT §5 change and is not attempted in this file.
"""

from vertiscope.address import ContentAddress
from vertiscope.markdown import _join_inline, _looks_like_url

URL = "https://x.test/p"


def units(xpath, values, tag="paragraph", depth=3):
    out = []
    for n, value in enumerate(values, start=1):
        address = ContentAddress(URL, "%s/text()[%d]" % (xpath, n), tag,
                                 "text()[%d]|text.visible/generic" % (n - 1))
        out.append((address, value, "text", depth))
    return out


def joined(rows):
    return [v for _a, v, _l, _d in _join_inline(rows)]


# --- a block's own text children ---------------------------------------------


def test_a_sentence_split_by_inline_markup_reads_as_one_sentence():
    """`<p>This data is <b>crucial</b> for tracking</p>`. The paragraph's own
    two fragments used to stay apart because only text INSIDE an inline
    element could join."""
    rows = units("/html/body/p", ["This data is"])
    rows += units("/html/body/p/b", ["crucial"])
    rows += [(ContentAddress(URL, "/html/body/p/text()[2]", "paragraph",
                             "text()[1]|text.visible/generic"),
              "for tracking", "text", 3)]
    assert joined(rows) == ["This data is crucial for tracking"]


def test_paragraphs_of_a_text_document_stay_apart():
    """The limit of the rule, and the reason it has one.

    A text/plain file addresses every paragraph as a direct text child of one
    `<pre>`, with no markup between. Joining those merged sixty paragraphs
    into a single line at EVERY window setting -- the context-window
    hyperparameter, which is the knob this project exists to offer, stopped
    affecting that shape of document at all.

    So a block's own text children join only inside a flow that also holds
    inline markup. A sentence is interleaved; a document is not.
    """
    rows = units("/html/body/pre",
                 ["Paragraph one, long enough to matter.",
                  "Paragraph two, also its own thought.",
                  "Paragraph three."])
    assert len(joined(rows)) == 3


def test_a_counter_of_bare_text_nodes_is_not_joined():
    """Stated as a limit rather than a fix.

    duckduckgo writes its character counter as `0`, `/`, `500` -- three text
    nodes of one `<div>` with no element between them -- and a reader sees
    `0/500`. It stays three lines, because the rule that keeps sixty
    paragraphs apart cannot tell this apart from them: both are bare text
    children of one block. Splitting the two needs something this level does
    not have, so the counter is a known cost of protecting the window.
    """
    rows = units("/html/body/div", ["0", "/", "500"])
    assert joined(rows) == ["0", "/", "500"]


def test_separate_blocks_do_not_join():
    """The guard that was removed existed for this. Document order is what
    replaces it: content of an intervening block lands between these two and
    breaks the run by having a different flow owner."""
    rows = (units("/html/body/p", ["first paragraph"])
            + units("/html/body/p[2]", ["second paragraph"]))
    assert joined(rows) == ["first paragraph", "second paragraph"]


def test_a_link_still_stays_its_own_line():
    """Joining is for prose. A link is an affordance and keeps its identity;
    inlining it into the sentence is a separate, larger change."""
    rows = units("/html/body/p", ["read the"], tag="paragraph")
    rows += units("/html/body/p", ["docs"], tag="link")
    assert joined(rows) == ["read the", "docs"]


# --- what counts as a target -------------------------------------------------


def test_a_lone_separator_is_not_a_url():
    for value in ("/", "#", "?"):
        assert not _looks_like_url(value), value


def test_a_prefix_that_leads_somewhere_still_is():
    for value in ("/docs", "#section", "?q=1", "https://x.test",
                  "mailto:a@b.test"):
        assert _looks_like_url(value), value


def test_a_url_is_still_never_joined_to_prose():
    """Non-vacuity: loosening the test must not start folding targets into
    sentences."""
    rows = units("/html/body/p", ["see"])
    rows += units("/html/body/p/b", ["/docs/install"])
    rows += [(ContentAddress(URL, "/html/body/p/text()[2]", "paragraph",
                             "text()[1]|text.visible/generic"),
              "for more", "text", 3)]
    assert "/docs/install" in joined(rows)
    assert joined(rows) != ["see /docs/install for more"]
