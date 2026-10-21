"""A store-wide hit has to say which page it came from.

`search` in the TUI is retrieval over every page ever folded, and it loads the
hits as the document. `load_chunks` takes the document's url from the FIRST
chunk alone, so the screen named one page while showing results drawn from
twenty, and no line said which belonged to which. A reader could not tell a
hit from the scan they just ran from a hit from something read a week ago.

That is the `Browser(query)` requirement from docs/CALLABLE_INTERFACE.md --
"provide the url as part of the chunk-object result header" -- applied to the
surface that already did the retrieving.

The three factors travel in the same header. One score cannot say why a thing
ranked: all-standing-no-text and all-text-no-standing are different answers to
the same question, and a reader deciding which hit to open wants the
difference.

No browser: `index_html` is the offline path into the same store and the same
index.
"""

import pytest

from vertiscope.repl.app import Repl
from vertiscope.workspace import Workspace

ALPHA = """<!doctype html><html><body>
<h1>Glacier mass balance</h1>
<p>Monthly solutions resolve basin-scale mass change from orbit.</p>
</body></html>"""

BETA = """<!doctype html><html><body>
<h1>Ice sheet gravimetry</h1>
<p>Basin-scale mass change is resolved by satellite gravimetry.</p>
</body></html>"""


@pytest.fixture
def repl(tmp_path):
    """A REPL over a store holding two pages, both matching the query."""
    with Workspace(tmp_path / "ws") as ws:
        ws.index_html(ALPHA, "https://alpha.test/mass-balance")
        ws.index_html(BETA, "https://beta.test/gravimetry")
        ws.flush_vectors()
        app = Repl()
        app.index = ws.index.build()
        app.store = ws.store
        yield app


def _lines(app):
    # Document lines are `Widget`s; their text is `label`.
    return [w.label for w in app.state.document.lines]


def test_every_hit_carries_its_own_url(repl):
    """The defect: one url on the status bar, hits from several pages."""
    repl._cmd_search(["mass", "change"])
    text = "\n".join(_lines(repl))
    assert "alpha.test/mass-balance" in text
    assert "beta.test/gravimetry" in text


def test_the_header_reports_the_three_factors(repl):
    repl._cmd_search(["mass", "change"])
    heads = [t for t in _lines(repl) if t.startswith("https://")]
    assert heads, _lines(repl)
    for head in heads:
        assert " r" in head and " l" in head and " s" in head


def test_the_note_counts_pages_as_well_as_hits(repl):
    """How many answers, and from how many places -- twenty hits off one page
    is a different result from twenty off twenty."""
    repl._cmd_search(["mass", "change"])
    # `status` is the last message; a skipped assertion holds nothing, and an
    # earlier draft of this test skipped itself by looking for the wrong
    # attribute.
    note = repl.state.buffers.status
    assert "hit(s)" in note, note
    assert "page(s)" in note, note


def test_the_content_sits_under_its_header(repl):
    """Indented one level below the url, so the grouping is visible rather
    than implied by adjacency."""
    repl._cmd_search(["mass", "change"])
    lines = repl.state.document.lines
    heads = [i for i, w in enumerate(lines)
             if w.label.startswith("https://")]
    assert heads
    first = heads[0]
    assert first + 1 < len(lines)
    assert lines[first + 1].depth > lines[first].depth


def test_a_query_matching_nothing_says_so(repl):
    """Non-vacuity: the header must not appear when there is nothing to head.
    A results view that always draws something cannot report an empty result.
    """
    before = list(_lines(repl))
    repl._cmd_search(["quantum", "chromodynamics", "lattice"])
    assert _lines(repl) == before or not any(
        t.startswith("https://") for t in _lines(repl))
