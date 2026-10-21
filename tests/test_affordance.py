"""What the REPL offers to interact with, against what the page can be.

The coverage arrows score addresses. This scores affordances, and the two come
apart exactly where it matters: `page->wireframe` reports a false positive only
for an *invented address*, so a `<div>` drawn as a button passes it. The path
is real; only the affordance is a fiction.

Every test here is about the matcher, because the matcher is where this
measurement has gone wrong every time so far -- three times, each producing a
confident and false accusation against the sensor:

* matching by path equality reported **2,005 invented affordances**. Ground
  truth marks the `<a>`; the sensor addresses the `<span>` holding the link's
  words. Both right, comparison wrong.
* crediting only the *nearest* ancestor control reported **54 unreachable
  disclosures** on a page where the sensor had classed all 100 lines under
  those summaries as `button`. Controls nest.
* the remaining figure was inflated by ground truth lacking `AREA`, which
  charged an image map's 254 clickable regions to the renderer.

None of those were visible in the totals; each looked like a defect until the
samples were read. So the assertions below plant the situations rather than
checking that clean input stays clean.
"""

import io
import pathlib
import re

from vertiscope.analytics.affordance import (INTERACTIVE_KINDS, score_affordance)

ROOT = pathlib.Path(__file__).resolve().parent.parent


class _Unit:
    def __init__(self, xpath, kind, drawn=True):
        self.xpath = xpath
        self.kind = kind
        # A real `PageUnit` carries this, and the score reads it: an
        # affordance the page does not lay out is not one the REPL is
        # answerable for. The fakes here omitted it at first, which is why
        # these tests passed while modelling a unit the code could not accept.
        self.drawn = drawn


class _Truth:
    def __init__(self, units):
        self.units = [_Unit(*u) for u in units]


class _Address:
    def __init__(self, xpath, tag):
        self.xpath = xpath
        self.tag = tag


def drawn(*pairs):
    return [(_Address(p, t), "") for p, t in pairs]


# --- the mirrored constant ---------------------------------------------------


def test_the_interactive_kinds_match_the_sensor():
    """The Python copy of `INTERACTIVE_KIND` against the JavaScript original.

    The list lives in `sensor.js` and is mirrored here because the measurement
    is in Python. A silent drift would not fail anything: the score would just
    quietly start answering a different question.
    """
    js = io.open(ROOT / "vertiscope" / "core" / "js" / "sensor.js",
                 encoding="utf-8").read()
    match = re.search(r"var INTERACTIVE_KIND = \{([^}]*)\}", js)
    assert match, "INTERACTIVE_KIND is no longer declared in sensor.js"
    assert set(re.findall(r'"(\w+)"', match.group(1))) == set(INTERACTIVE_KINDS)


# --- what a phantom is -------------------------------------------------------


def test_a_control_the_page_does_not_have_is_a_phantom():
    """The error the coverage arrows cannot see: a real path, a fake class."""
    truth = _Truth([("/html/body/div", "text")])
    out = score_affordance(truth, drawn(("/html/body/div", "button")))
    assert out["phantom"] == 1 and out["tp"] == 0


def test_a_control_drawn_as_prose_is_missed_not_phantom():
    truth = _Truth([("/html/body/button", "control")])
    out = score_affordance(truth, drawn(("/html/body/button", "text")))
    assert out["missed"] == 1 and out["phantom"] == 0


def test_the_two_errors_are_never_merged():
    """They have different costs and one figure would average them away."""
    truth = _Truth([("/html/body/button", "control"),
                    ("/html/body/p", "text")])
    out = score_affordance(truth, drawn(("/html/body/button", "text"),
                                        ("/html/body/p", "button")))
    assert (out["missed"], out["phantom"]) == (1, 1)


# --- matching by containment, not equality -----------------------------------


def test_a_link_addressed_at_its_text_is_not_invented():
    """The 2,005-phantom bug, in one case.

    Ground truth marks the `<a>`. The sensor addresses the `<span>` holding
    the words, which inherits the link class, because a reader sees one link
    drawn once wherever its text sits.
    """
    truth = _Truth([("/html/body/a", "link")])
    out = score_affordance(
        truth, drawn(("/html/body/a/span/text()[1]", "link")))
    assert out["phantom"] == 0 and out["tp"] == 1


def test_every_nested_control_is_credited_not_only_the_innermost():
    """The 54-disclosure bug.

    `<details>` and `<summary>` are both controls, and the disclosure's
    affordance *is* the summary: a reader who can act on the summary can open
    the details. Crediting only the nearest left every details uncovered.
    """
    truth = _Truth([("/html/body/details", "control"),
                    ("/html/body/details/summary", "control")])
    out = score_affordance(
        truth, drawn(("/html/body/details/summary/span/text()[1]", "button")))
    assert out["missed"] == 0
    assert out["tp"] == 2


def test_containment_does_not_reach_across_branches():
    """The guard, or containment credits anything for anything."""
    truth = _Truth([("/html/body/nav/a", "link")])
    out = score_affordance(truth, drawn(("/html/body/footer/p", "button")))
    assert out["phantom"] == 1 and out["missed"] == 1


def test_a_control_inside_a_control_still_needs_something_drawn():
    """Nesting credits ancestors of a *drawn* line, not ancestors in general."""
    truth = _Truth([("/html/body/details", "control"),
                    ("/html/body/details/summary", "control")])
    out = score_affordance(truth, drawn(("/html/body/p/text()[1]", "text")))
    assert out["missed"] == 2 and out["tp"] == 0


# --- the figures it reports --------------------------------------------------


def test_precision_is_about_what_the_repl_offers():
    truth = _Truth([("/html/body/a", "link"), ("/html/body/p", "text")])
    out = score_affordance(truth, drawn(("/html/body/a", "link"),
                                        ("/html/body/p", "button")))
    assert out["precision"] == 0.5      # one of two offered is real
    assert out["recall"] == 1.0         # the page's one control is presented


def test_a_page_with_no_controls_scores_one_rather_than_zero():
    """No affordances offered and none invented is perfect, not undefined."""
    truth = _Truth([("/html/body/p", "text")])
    out = score_affordance(truth, drawn(("/html/body/p", "text")))
    assert out["precision"] == 1.0 and out["recall"] == 1.0
    assert out["phantom"] == 0 and out["missed"] == 0


# --- what the page does not lay out ------------------------------------------


def test_a_control_the_page_does_not_draw_is_not_the_repls_to_present():
    """Options behind a closed dropdown.

    Ground truth descends into a collapsed `<select>` and marks its options
    undrawn, and `OPTION` is a control tag. Counted, 1,788 of them across the
    corpus became affordances the page "has" and the missed figure went 279 to
    2,066 -- for a REPL correctly declining to offer choices behind a dropdown
    the reader has not opened.
    """
    truth = _Truth([("/html/body/select", "control", True),
                    ("/html/body/select/option", "control", False),
                    ("/html/body/select/option[2]", "control", False)])
    out = score_affordance(truth, drawn(("/html/body/select", "choice")))
    assert out["missed"] == 0
    assert out["tp"] == 1


def test_an_undrawn_control_is_not_a_phantom_either():
    """Symmetry: excluded from the denominator, not moved to the other error."""
    truth = _Truth([("/html/body/select/option", "control", False)])
    out = score_affordance(truth, drawn(("/html/body/p", "text")))
    assert (out["missed"], out["phantom"], out["tp"]) == (0, 0, 0)


def test_presenting_an_undrawn_control_is_not_inventing_one():
    """The case that broke the corpus and that none of the above catches.

    Filtering the phantom denominator to *drawn* controls made every REPL line
    for a real-but-undrawn control a fiction: phantoms went from 8 to 8,701
    across the corpus, every one of them a control the page genuinely has --
    a link inside a collapsed section, an option in a dropdown.

    So the two errors take different denominators, because they ask different
    questions. A phantom is scored against every control the page has, drawn
    or not: did the REPL invent this? A miss is scored against what the page
    lays out: was the reader denied something they could have reached.

    Every test above passed through the version that got this wrong, which is
    what a missing case looks like from the inside.
    """
    truth = _Truth([("/html/body/nav/a", "link", False)])
    out = score_affordance(truth, drawn(("/html/body/nav/a", "link")))
    assert out["phantom"] == 0, "a real control drawn is not an invention"
    assert out["missed"] == 0, "and not a miss either -- it was not reachable"


def test_the_two_denominators_do_not_collapse_into_one():
    """One page, both errors, each judged on its own denominator.

    A genuine fiction beside a real-but-undrawn control: the first must be a
    phantom, the second must be neither, and a drawn control the REPL ignores
    must still be a miss. No single filter produces all three.
    """
    truth = _Truth([("/html/body/nav/a", "link", False),      # real, hidden
                    ("/html/body/main/button", "control", True),  # reachable
                    ("/html/body/main/p", "text", True)])
    out = score_affordance(truth, drawn(
        ("/html/body/nav/a", "link"),            # fine: real control
        ("/html/body/main/p", "button"),         # fiction: not a control
        ("/html/body/main/button", "text")))     # miss: drawn, not offered
    assert out["phantom"] == 1
    assert out["missed"] == 1
    assert out["recall"] == 0.0                  # of what was reachable, none

# --- capture is not presentation ---------------------------------------------


def test_an_affordance_the_renderer_omits_is_missed():
    """The distinction the measure was not making.

    `measure_affordance` passed `spine.trie.leaves()` as its `drawn`
    argument, so it asked whether the fold *captured* the affordance while
    the report read "...the REPL presents". On ja.wikipedia that scored
    recall 1.0 on a page whose visible `カテゴリ` link has no rendered line at
    its anchor or at any ancestor -- the fold held it and the projection
    dropped it, and a reader acts on the projection.

    Scored over what the render actually emits, the same affordance is
    missed, which is the answer the goal's question wants.
    """
    truth = _Truth([("/html/body/div/a", "link", True)])
    held = drawn(("/html/body/div/a", "link"))
    assert score_affordance(truth, held)["missed"] == 0
    assert score_affordance(truth, [])["missed"] == 1


def test_presentation_still_credits_a_nested_drawing():
    """The containment tolerance is unchanged: the renderer addresses a
    link's words at the span holding them, and that is still the same link."""
    truth = _Truth([("/html/body/div/a", "link", True)])
    presented = drawn(("/html/body/div/a/span", "link"))
    assert score_affordance(truth, presented)["missed"] == 0
