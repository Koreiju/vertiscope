"""A listbox draws as a listbox, and a control split over notes says where.

Two defects reported on one note -- `Gloucestershire Health and Care NHS
Foundation T-aaf4e4`, which is part of data.gov.uk's 1,511-option publisher
filter:

* the options each drew as `<input type="text" disabled placeholder="...">`,
  so a page with one dropdown produced a column of 1,509 fake text boxes;
* thirty notes held that one control and every one of them carried the same
  frontmatter xpath -- the chunk ROOT, which is the `<select>` -- so nothing
  in a note said which slice it was or where the rest went.

The second is not fixed by cutting differently. The content genuinely does
not fit a 512-token window, so it stays cut and the cut is made navigable.
"""

import pathlib
import sys
from dataclasses import dataclass
from typing import List

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from vertiscope.obsidian.export import _continuation, _series   # noqa: E402
from vertiscope.obsidian.htmlform import render_lines           # noqa: E402

URL = "https://s.test/"
SELECT = "/html/body/form/select"


def option(index: int, label: str) -> dict:
    key = "%s|%s/option[%d]|interactive.inputs|text()" % (URL, SELECT, index)
    return {"text": "[ ] %s" % label, "key": key, "cls": "field",
            "control": True}


# --- the listbox ------------------------------------------------------------

def test_consecutive_options_become_one_select():
    html = render_lines([option(1, "Alpha"), option(2, "Bravo"),
                         option(3, "Charlie")], base=URL)
    assert html.count("<select") == 1
    assert html.count("<option") == 3
    assert 'type="text"' not in html, "an option is not a text field"
    for label in ("Alpha", "Bravo", "Charlie"):
        assert ">%s</option>" % label in html


def test_every_option_keeps_its_own_address():
    """The gathering must not cost the thing addresses are for.

    `enact` presses an address. If the options were folded into one element
    with one address, pressing any of them would name the select and the
    reader could no longer choose.
    """
    html = render_lines([option(1, "Alpha"), option(2, "Bravo")], base=URL)
    assert "%s/option[1]|" % SELECT in html
    assert "%s/option[2]|" % SELECT in html


def test_the_select_claims_an_address_the_page_actually_has():
    """Why this is allowed where an invented `<ul>` is not.

    The module's standing rule is that a shared parent must not claim an
    address that is nobody's. An option's parent is not nobody: it is the
    `<select>` the page drew, at its own xpath.
    """
    html = render_lines([option(1, "Alpha"), option(2, "Bravo")], base=URL)
    assert 'data-vertiscope-address="%s|%s|interactive.inputs|text()"' % (URL, SELECT) \
        in html


def test_two_controls_draw_as_two():
    other = "/html/body/form/div/select"
    second = {"text": "[ ] Solo",
              "key": "%s|%s/option[1]|interactive.inputs|text()" % (URL, other),
              "cls": "field", "control": True}
    html = render_lines([option(1, "Alpha"), option(2, "Bravo"), second],
                        base=URL)
    assert html.count("<select") == 2


def test_a_plain_field_is_still_a_field():
    """Non-vacuity: the rule is scoped to options and touches nothing else."""
    field = {"text": "[ ] Search", "cls": "field", "control": True,
             "key": "%s|/html/body/input|interactive.inputs|text()" % URL}
    html = render_lines([field], base=URL)
    assert "<select" not in html
    assert 'type="text"' in html


def test_a_lone_option_still_draws_as_a_listbox():
    html = render_lines([option(1, "Only")], base=URL)
    assert html.count("<select") == 1 and html.count("<option") == 1


# --- the series -------------------------------------------------------------

@dataclass
class FakeChunk:
    cid: str
    url: str
    xpath: str
    part: int


def series_of(n: int) -> List[FakeChunk]:
    return [FakeChunk("cid%d" % i, URL, SELECT, i) for i in range(n)]


def test_parts_of_one_element_know_their_place():
    place = _series(series_of(30))
    assert place["cid0"] == (1, 30, "", "cid1")
    assert place["cid17"] == (18, 30, "cid16", "cid18")
    assert place["cid29"] == (30, 30, "cid28", "")


def test_a_chunk_that_is_not_split_gets_no_series():
    """A note with no continuation must not grow a line saying so."""
    assert _series(series_of(1)) == {}


def test_two_elements_are_two_series():
    chunks = series_of(2) + [FakeChunk("x0", URL, "/html/body/ul", 0),
                             FakeChunk("x1", URL, "/html/body/ul", 1)]
    place = _series(chunks)
    assert place["cid0"][1] == 2 and place["x0"][1] == 2
    assert place["cid0"][3] == "cid1" and place["x0"][3] == "x1"


def test_the_continuation_links_both_ways():
    names = {"cid16": "prev-note", "cid17": "this", "cid18": "next-note"}
    line = _continuation((18, 30, "cid16", "cid18"), names)
    assert "part 18 of 30" in line
    assert "[[prev-note|← part 17]]" in line
    assert "[[next-note|part 19 →]]" in line


def test_the_first_part_only_looks_forward():
    names = {"cid0": "first", "cid1": "second"}
    line = _continuation((1, 30, "", "cid1"), names)
    assert "← part" not in line
    assert "[[second|part 2 →]]" in line


def test_a_note_with_no_series_gets_no_line():
    assert _continuation(None, {}) == ""


def test_a_neighbour_that_was_not_exported_is_not_linked():
    """A wikilink to a note that does not exist is a dangling edge.

    The export's own board counts those, and inventing them here to make the
    chain look complete would be counting a failure as a feature.
    """
    line = _continuation((2, 3, "cid0", "cid2"), {"cid0": "first"})
    assert "[[first|← part 1]]" in line
    assert "part 3 →" not in line
