"""The affine-map metric, and proof that it can fail.

Every check here plants the defect it claims to catch. A coverage number that
cannot go down is not a measurement, and this repo has shipped four of those:
detection rates structurally incapable of being non-zero, a `forget` that
crashed when asked, a composed-tree walk that never composed, and a coverage
figure that mixed capture with projection. All four passed a green suite.

No browser: the scorer takes ground truth and rendered addresses as data, so
the arithmetic is testable without one. `tests/test_composed_tree.py` covers
the live side.
"""

from vertiscope.address import ContentAddress
from vertiscope.analytics.affine import score_arrow, score_dedup
from vertiscope.analytics.groundtruth import PageTruth, PageUnit

URL = "https://x.test/"


def addr(xpath: str, tag: str = "text") -> ContentAddress:
    return ContentAddress(URL, xpath, tag, "text()[1]|text.visible")


def truth(*units: PageUnit) -> PageTruth:
    return PageTruth(url=URL, units=list(units))


def unit(xpath: str, value: str = "words", *, kind: str = "text",
         drawn: bool = True, shadow: bool = False) -> PageUnit:
    return PageUnit(xpath=xpath, kind=kind, value=value, drawn=drawn,
                    shadow=shadow)


class TestSurjectivity:
    """Everything the page holds must reach the render."""

    def test_a_faithful_render_scores_perfectly(self):
        page = truth(unit("/html/body/p/text()[1]", "alpha"),
                     unit("/html/body/div/text()[1]", "beta"))
        score = score_arrow("t", page, [addr("/html/body/p/text()[1]"),
                                        addr("/html/body/div/text()[1]")])
        assert score.overall.recall == 1.0
        assert score.overall.fn == 0

    def test_a_dropped_unit_is_reported_as_loss(self):
        """The planted defect: `<img alt="">` vanishing from the render."""
        page = truth(unit("/html/body/p/text()[1]", "alpha"),
                     unit("/html/body/img", "/pic.svg", kind="media"))
        score = score_arrow("t", page, [addr("/html/body/p/text()[1]")])
        assert score.overall.fn == 1
        assert score.overall.recall == 0.5
        assert score.lost[0].kind == "media"

    def test_loss_is_reported_per_origin(self):
        """Shadow content failing at light content's rate is the finding."""
        page = truth(unit("/html/body/p/text()[1]", "light one"),
                     unit("/html/body/x/#shadow-root/p/text()[1]", "dark one",
                          shadow=True))
        score = score_arrow("t", page, [addr("/html/body/p/text()[1]")])
        assert score.by_origin["light"].recall == 1.0
        assert score.by_origin["shadow"].recall == 0.0


class TestInjectivity:
    """One page address, one rendered line."""

    def test_the_same_address_drawn_twice_is_duplication(self):
        page = truth(unit("/html/body/a/text()[1]", "click"))
        score = score_arrow("t", page, [addr("/html/body/a/text()[1]"),
                                        addr("/html/body/a/text()[1]")])
        assert score.overall.duplicated == 1
        assert score.overall.injectivity < 1.0

    def test_a_merge_is_not_duplication(self):
        """An anchor's href and its words are one line by design.

        Scored by owner alone this read as 56 duplications on a page with
        none, which is the map being a quotient rather than a bijection.
        """
        page = truth(unit("/html/body/a", "https://d.test/", kind="link"),
                     unit("/html/body/a/text()[1]", "click"))
        score = score_arrow("t", page, [addr("/html/body/a"),
                                        addr("/html/body/a/text()[1]")])
        assert score.overall.duplicated == 0
        assert score.overall.recall == 1.0


class TestInvention:
    """A rendered address the page does not contain."""

    def test_a_phantom_address_is_reported(self):
        """The planted defect: a filled slot emitting its fallback text."""
        page = truth(unit("/html/body/p/text()[1]", "alpha"))
        score = score_arrow("t", page, [addr("/html/body/p/text()[1]"),
                                        addr("/html/body/ghost/text()[1]")])
        assert score.overall.fp == 1
        assert score.overall.precision < 1.0


class TestDenominators:
    """The wireframe answers for what the page draws, and nothing else."""

    def test_hidden_content_omitted_from_a_drawing_is_a_correct_omission(self):
        page = truth(unit("/html/body/meta", "keywords", drawn=False))
        drawing = score_arrow("wire", page, [], denominator="drawn")
        assert drawing.overall.tn == 1
        assert drawing.overall.fn == 0
        assert drawing.overall.recall == 1.0

    def test_the_same_omission_is_a_loss_for_markdown(self):
        """Markdown indexes hidden content on purpose; the drawing must not.

        Same page, same render, opposite verdicts -- which is the point of
        the denominator being part of the metric's identity.
        """
        page = truth(unit("/html/body/meta", "keywords", drawn=False))
        semantic = score_arrow("md", page, [], denominator="all")
        assert semantic.overall.fn == 1
        assert semantic.overall.recall == 0.0


class TestDeduplication:
    """Redundancy is a lineage relation, and both errors are named."""

    def test_repeated_words_in_unrelated_places_are_not_redundant(self):
        """A page saying one true thing six times is not being redundant.

        Scored as equality of text this read as 64 failures on a page with
        none, and a renderer obeying it would have lost five of the six.
        """
        page = truth(unit("/html/body/div/a/text()[1]", "tag"),
                     unit("/html/body/div[2]/a/text()[1]", "tag"))
        score = score_dedup(page, [addr("/html/body/div/a/text()[1]"),
                                   addr("/html/body/div[2]/a/text()[1]")],
                            texts=["tag", "tag"])
        assert score.redundant_pairs == 0
        assert score.under_dedup == 0
        assert score.distinct_kept == 2

    def test_one_thing_spelled_twice_in_a_lineage_collapses(self):
        """A wrapper repeating its child's words is one thing, drawn once."""
        page = truth(unit("/html/body/span", "Save", kind="attr"),
                     unit("/html/body/span/text()[1]", "Save"))
        score = score_dedup(page, [addr("/html/body/span/text()[1]")],
                            texts=["Save"])
        assert score.collapsed == 1
        assert score.under_dedup == 0
        assert score.over_dedup == 0

    def test_both_spellings_drawn_is_under_dedup(self):
        """The planted defect: `[/tag/love/]` drawn beside `[love]`."""
        page = truth(unit("/html/body/span", "Save", kind="attr"),
                     unit("/html/body/span/text()[1]", "Save"))
        score = score_dedup(page, [addr("/html/body/span"),
                                   addr("/html/body/span/text()[1]")],
                            texts=["Save", "Save"])
        assert score.under_dedup == 1
        assert score.collapsed == 0

    def test_every_spelling_gone_is_over_dedup_not_success(self):
        """The dangerous direction, and the one a rate alone cannot see.

        A suppression rule once hid an href because "the anchor speaks" while
        consuming the words because "the link will draw them", and every
        search-result title on the page vanished. That must not score as
        excellent deduplication.
        """
        page = truth(unit("/html/body/span", "Save", kind="attr"),
                     unit("/html/body/span/text()[1]", "Save"))
        score = score_dedup(page, [], texts=[])
        assert score.over_dedup == 1
        assert score.collapsed == 0
        assert score.correctness < 1.0
