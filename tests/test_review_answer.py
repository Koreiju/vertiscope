"""`answer(name)`: the reader's reply to a card's review (PLUGIN_GOAL 180; synthesis 1d)."""

import os
import pathlib

import pytest

from domvec.obsidian import kernel_objects as ko


@pytest.fixture
def vault(tmp_path):
    g = tmp_path / "domvec" / "graph"
    g.mkdir(parents=True)
    here = os.getcwd()
    ns = {}
    exec(ko.vault_boot(str(tmp_path), "domvec/graph/x.md"), ns)
    yield g, ns["answer"]
    os.chdir(here)


def _card(g, text):
    (g / "My card.md").write_text(text, encoding="utf-8")


def test_unanswered_is_none_and_the_written_answer_comes_back(vault):
    g, answer = vault
    _card(g, "body\n\n> [!question] review\n> ship it?\n> **answer:** \n")
    assert answer("my card") is None
    _card(g, "body\n\n> [!question] review\n> ship it?\n> **answer:** yes, with tests\n> and a plant\n")
    assert answer("my card") == "yes, with tests\nand a plant"


def test_the_last_review_is_the_one_answered(vault):
    g, answer = vault
    _card(g, "> [!question] review\n> first?\n> **answer:** old\n\n> [!question] review\n> second?\n> **answer:** \n")
    assert answer("My card") is None


def test_planted_no_slot_can_never_be_answered(vault):
    # A review written as before 180: no `**answer:**` line, so a reply typed
    # into the callout is indistinguishable from the question.
    g, answer = vault
    _card(g, "> [!question] review\n> ship it?\n> yes\n")
    assert answer("my card") is None


def test_no_such_card_is_refused(vault):
    _, answer = vault
    with pytest.raises(ValueError):
        answer("nothing by this name")
