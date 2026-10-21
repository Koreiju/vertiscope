"""A repeated structure is one chunk per record, not one chunk per windowful.

The goal states the acceptance criterion directly: "our chunking should be such
that, for example, we get search results as singular chunks."

The context window alone cannot deliver that, and this is the point the rule
exists to make. The window is a *cap*: the merge fills it with whatever
adjacent siblings fit, so at 512 tokens five hundred-token results become one
chunk and at 128 one result gets split. Either way the boundary lands where
the arithmetic ran out rather than where the page changed subject, and a
retrieval hit then points at "the third through seventh results" -- which is
not a thing anyone was looking for.

What makes a search result a unit is not its size. It is that the page repeats
a shape.

The two failure directions are equally real and this module holds both: a rule
too loose splits every nav bar into eight chunks (measured: the median chunk
went to 47 tokens over the corpus), and a rule too tight stops firing on the
results it exists for.
"""

import re

import pytest

import vertiscope.markdown as md
from vertiscope import tokens
from vertiscope.markdown import DEFAULT_CONTEXT_WINDOW, render_trie
from vertiscope.pipeline import run_pipeline
from vertiscope.trie import AddressTrie

URL = "https://res.test/q"

#: Eight menu items. A repeated composite shape -- `<li><a>` passes every
#: structural test a search result passes -- and not a record: nobody
#: retrieves one.
NAV = ("<nav><ul>"
       + "".join("<li><a href='/s/%d'>Section %d</a></li>" % (i, i)
                 for i in range(8))
       + "</ul></nav>")

#: Ten results, each about ninety tokens: a link, a heading, a thumbnail, a
#: snippet, a source and a button. This is the shape the rule is for.
RESULTS = "".join(
    "<li class='result'><article>"
    "<a href='/r/%d'><h3>Result number %d about libraries</h3></a>"
    "<img src='/thumb/%d.jpg' alt='Cover of result %d'>"
    "<p>A snippet of the result, long enough to read as a sentence and to "
    "carry the words a search would have matched on, number %d.</p>"
    "<span class='meta'>archive.org</span>"
    "<button type='button'>Save %d</button>"
    "</article></li>" % (i, i, i, i, i, i)
    for i in range(10))

#: Ten paragraphs. A repeated tag, and NOT a record -- prose must keep
#: merging, or every paragraph gets its own chunk and each one's context is
#: buried.
PROSE = "".join(
    "<p>A paragraph of ordinary article prose, number %d, which must keep "
    "merging with its neighbours because a paragraph is not a record and "
    "splitting them would bury each one's context.</p>" % i
    for i in range(10))

PAGE = ("<html><body>%s<main><h1>Search results</h1><ol>%s</ol>"
        "<section>%s</section></main></body></html>" % (NAV, RESULTS, PROSE))


def _chunks(window=DEFAULT_CONTEXT_WINDOW):
    result = run_pipeline(PAGE, URL, render=False)
    trie = AddressTrie.from_tagged(result.tagged, URL)
    return render_trie(trie, context_window=window)


def _results_in(chunk):
    return set(re.findall(r"Result number (\d+)", chunk.markdown))


def test_one_search_result_is_one_chunk():
    """The criterion, stated as the goal states it."""
    holding = [c for c in _chunks() if _results_in(c)]
    assert holding, "no chunk held a result at all"
    for chunk in holding:
        found = _results_in(chunk)
        assert len(found) == 1, (
            "a chunk held results %s; a hit on it points at a span of the "
            "list rather than at a result" % sorted(found))
    assert len({next(iter(_results_in(c))) for c in holding}) == 10, \
        "not every result got a chunk"


def test_the_window_alone_would_not_have_done_it():
    """Non-vacuity, and the reason the rule exists rather than a smaller window.

    With the rule off, the merge packs whatever fits: the same ten results
    come out as a couple of chunks holding five each. Shrinking the window
    instead does not fix this -- it moves the boundary, it does not put it
    where the page changes subject -- and it would split the prose too.
    """
    off = 10 ** 9
    original = md.RECORD_MIN
    md.RECORD_MIN = off
    try:
        packed = [c for c in _chunks() if _results_in(c)]
    finally:
        md.RECORD_MIN = original
    assert max(len(_results_in(c)) for c in packed) > 1, \
        "the merge did not pack results, so this test proves nothing"


def test_a_nav_bar_is_not_a_record_set():
    """`<li><a>Home</a></li>` is a repeated composite shape and not a record.

    Structure alone cannot separate them; size can. Without
    `RECORD_MIN_FILL` the rule fired on every menu in the corpus and took the
    median chunk from 308 tokens to 47.
    """
    menu = [c for c in _chunks() if re.search(r"Section \d", c.markdown)]
    assert len(menu) == 1, (
        "the nav split into %d chunks; a menu item is not a retrievable unit"
        % len(menu))


def test_prose_keeps_merging():
    """A run of `<p>` is a repeated tag. It must not become ten chunks."""
    prose = [c for c in _chunks() if "ordinary article prose" in c.markdown]
    assert len(prose) <= 2, \
        "prose split into %d chunks" % len(prose)


def test_a_record_still_respects_the_window():
    """The rule changes where a chunk ENDS, never that the cap applies.

    A record larger than the window is still split; otherwise "one chunk per
    record" would quietly become a licence to emit a chunk of any size.
    """
    big = ("<html><body><ol>"
           + "".join("<li><article><h3>Row %d</h3><p>%s</p></article></li>"
                     % (i, " ".join("word%d" % k for k in range(400)))
                     for i in range(4))
           + "</ol></body></html>")
    result = run_pipeline(big, URL, render=False)
    trie = AddressTrie.from_tagged(result.tagged, URL)
    window = 128
    for chunk in render_trie(trie, context_window=window):
        if len(chunk.lines) > 1:
            assert tokens.count(chunk.markdown) <= window, \
                "a record was emitted over the window without being split"


@pytest.mark.parametrize("window", [128, 256, 512, 700])
def test_the_split_does_not_move_with_the_window(window):
    """A record is a record across the whole range of useful windows.

    This is the claim that makes the boundary a property of the PAGE rather
    than of the hyperparameter. The window still decides how much non-record
    content rides along, so only the results are asserted.

    The range has a real top and it is stated rather than hidden. The rule
    fires at the node whose children are the records, and the descent only
    reaches that node if its ancestors did not fit the window first. So the
    honest boundary is: **one chunk per record holds whenever the record
    set's ancestors do not fit the window** -- which on any page bigger than
    the window is always. A window larger than the page returning the page is
    not a failure of this rule.

    The top of the range is **measured, and it moved**. It used to read "this
    fixture's `<main>` is about a thousand tokens, so at 1024 `<main>` is
    emitted whole". `<main>` renders to 844 tokens and spends **714** of the
    window, because the fixture is built from `href='/r/N'` links and the
    budget stopped counting link targets. So the ceiling came down from above
    1024 to between 700 and 768, and measured across the range the split holds
    at 128/256/512/700 and collapses to one chunk at 768. Nothing about the
    rule changed; the fixture simply got smaller in the unit that decides.
    """
    holding = [c for c in _chunks(window) if _results_in(c)]
    assert len(holding) == 10, \
        "window %d gave %d result chunks" % (window, len(holding))
    for chunk in holding:
        assert len(_results_in(chunk)) == 1


def test_the_guarantee_ends_where_the_page_fits_the_window():
    """The boundary above, asserted rather than left as a docstring.

    A limit nobody tests is a limit that quietly moves. If a change ever makes
    the rule reach through a fitting ancestor, this fails and the docstring
    above has to be rewritten -- which is the point.
    """
    whole = _chunks(10 ** 6)
    assert len(whole) == 1, "the fixture no longer fits one chunk at any size"
    assert tokens.count(whole[0].markdown) < 2048, \
        "fixture grew past the window used below"
    swallowed = [c for c in _chunks(2048) if _results_in(c)]
    assert len(swallowed) == 1, \
        "a window larger than the page unexpectedly split it"
