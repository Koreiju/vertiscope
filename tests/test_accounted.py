"""`covered` and `accounted` answer different questions, and the store agrees.

The chunker's cleanups kept colliding with `covered`: any change that draws
fewer redundant lines lowers it, because lowering it is what such a change
MEANS. Gating on it forbade the whole class.

The store never had that confusion. `graphstore` maps an address to a chunk
from `address`, then `inline`, then a third pass over `absorbed`, because
reading only the first two "left 37,452 addresses over the corpus with no
chunk at all, 8,167 of them urls, and an edge they could not hang on". So an
absorbed address has a chunk, hangs its edge, and is findable -- and reporting
it as uncovered says lost about something the system still holds.

These tests hold the two apart and tie `accounted` to what the store does.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from vertiscope.address import ContentAddress                   # noqa: E402
from vertiscope.markdown import MarkdownChunk, MarkdownLine     # noqa: E402

URL = "https://s.test/"


def at(xpath, tag="text.visible", accessor="text()"):
    return ContentAddress(url=URL, xpath=xpath, tag=tag, accessor=accessor)


def chunk(*lines):
    return MarkdownChunk(url=URL, xpath="/html/body", lines=list(lines))


def test_accounted_is_covered_plus_what_the_lines_speak_for():
    own, merged, folded = at("/a"), at("/a/b"), at("/a[@aria-label]")
    c = chunk(MarkdownLine(depth=0, text="words", address=own,
                           inline=(merged,), absorbed=(folded,)))
    assert set(c.covered) == {own.key(), merged.key()}
    assert set(c.accounted) == {own.key(), merged.key(), folded.key()}


def test_covered_never_exceeds_accounted():
    """The containment is the whole relationship: accounting is a superset."""
    c = chunk(
        MarkdownLine(depth=0, text="one", address=at("/a"),
                     inline=(at("/a/i"),), absorbed=(at("/a[@t]"),)),
        MarkdownLine(depth=1, text="two", address=at("/b")),
    )
    assert set(c.covered) <= set(c.accounted)


def test_a_line_that_speaks_for_nothing_leaves_them_equal():
    """Non-vacuity: the two only diverge where a collapse actually happened."""
    c = chunk(MarkdownLine(depth=0, text="plain", address=at("/a")))
    assert set(c.covered) == set(c.accounted)


def test_absorbed_alone_still_reaches_accounting():
    """The case the store's third pass exists for.

    A spelling dropped by the collapse -- an `aria-label` beside the text it
    duplicates -- draws no line of its own. It is not lost: the element IS in
    this chunk and only that spelling of it is not.
    """
    dropped = at("/a[@aria-label]", tag="text.accessible", accessor="aria-label")
    c = chunk(MarkdownLine(depth=0, text="Save", address=at("/a"),
                           absorbed=(dropped,)))
    assert dropped.key() not in set(c.covered)
    assert dropped.key() in set(c.accounted)


def test_the_two_answer_different_questions_about_one_element():
    """Both spellings name the same element; only one is drawn.

    This is why a cleanup may lower `covered` and must not lower `accounted`:
    the reader sees one line where there were two, and the system can still
    resolve both.
    """
    drawn = at("/html/body/button")
    spelling = at("/html/body/button", tag="text.accessible",
                  accessor="aria-label")
    c = chunk(MarkdownLine(depth=0, text="( Save )", address=drawn,
                           absorbed=(spelling,)))
    assert len(set(c.covered)) == 1
    assert len(set(c.accounted)) == 2
    assert {k.split("|")[1] for k in c.accounted} == {"/html/body/button"}
