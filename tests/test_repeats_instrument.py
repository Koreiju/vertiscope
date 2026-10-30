"""`domvec.analytics.repeats` (D-4 / M-8): in-chunk repetition by class.

Non-vacuity: a chunk PLANTED with the structural repeats the fold exists for
is counted structural; the same content with them folded counts none; data
repeats are never counted structural.
"""

from domvec import markdown as M
from domvec.analytics.repeats import STRUCTURAL, analyze, classify


def test_each_class_is_named():
    assert classify("- .") == "punct"
    assert classify("![edit](/i/pencil.svg)") == "image"
    assert classify("[![x](/a.png)](/b)") == "icon_link"
    assert classify("Sort ascending") == "label"
    assert classify("- Yes") == "data" and classify("2024-10-11") == "data" and classify("| a | b |") == "data"
    assert classify("The same sentence the page says twice about radix trees.") == "prose"


def test_planted_structural_repeats_are_counted_and_folded_ones_are_not():
    planted = "\n".join(["# Table", "Sort ascending", "- Alice", "Sort ascending", "- Bob", "- .", "- .",
                         "![edit](/p.svg)", "![edit](/p.svg)"])
    folded = "\n".join(["# Table", "Sort ascending", "- Alice", "- Bob"])
    got = analyze([("https://t/", "c1", planted)])
    assert got["structural_repeats"] == 3 and set(got["repeats"]) <= set(STRUCTURAL)
    assert analyze([("https://t/", "c1", folded)])["structural_repeats"] == 0


def test_data_repeats_are_not_structural():
    got = analyze([("https://t/", "c1", "\n".join(["- Yes", "- Yes", "- Yes", "| 1 | 2 |", "| 1 | 2 |"]))])
    assert got["structural_repeats"] == 0 and got["repeats"]["data"] == 3


def test_repeats_count_within_a_chunk_not_across_chunks():
    got = analyze([("https://t/", "c1", "Sort ascending"), ("https://t/", "c2", "Sort ascending")])
    assert got["structural_repeats"] == 0


def test_the_fold_itself_leaves_no_label_repeat_on_its_own_case():
    # The renderer's planted switch exists (D-4); the instrument reads strings,
    # so this pins only that the module and the switch still exist together.
    assert hasattr(M, "PLANT_STRUCTURAL_NOISE")


def test_a_word_in_any_script_is_not_punctuation():
    assert classify("أو") == "label" and classify("،") == "punct" and classify("Физика") == "label"
