"""jev, the typed-decision role (G-237): one forward pass, each option scored
by its letter's log-probability at the first output position, calibrated.

The model is replaced by a fake whose first-position logits are SET, so what
is tested is the readout -- the letters, the calibration, the refusal -- and
the planted shift is caught because the answer it reads is the wrong one.
"""

import math

import pytest

from domvec import models


class FakeLlm:
    """Tokenizes a letter to its own id; the logits favour one letter."""

    def __init__(self, favour, vocab=200):
        self.favour, self.vocab, self.n_tokens, self.prompts = favour, vocab, 0, []

    def tokenize(self, b, add_bos=False, special=False):
        t = b.decode()
        if len(t) == 1:
            return [ord(t)]
        self.prompts.append(t)
        return [1] * 7

    def reset(self):
        self.n_tokens = 0

    def eval(self, toks):
        self.n_tokens = len(toks)

    def n_vocab(self):
        return self.vocab

    @property
    def _ctx(self):
        row = [0.0] * self.vocab
        row[ord(self.favour)] = 6.0
        row[0] = -1.0                       # a real row is never all one value
        return type("Ctx", (), {"get_logits": lambda _s: row})()


Q = {"route": {"type": "choice", "instructions": "Which completes the purchase?",
               "criteria": {"click_coupon": "type a coupon", "click_place_order": "click Place order", "go_back": None}}}


def test_the_favoured_letter_is_the_answer_and_the_prompt_is_the_publishers():
    llm = FakeLlm("B")
    res = models.run_jev("A checkout page.", Q, llm=llm)
    a = res.value["answers"]["route"]
    assert res.ok and a["choice"] == "click_place_order" and a["probabilities"]["click_place_order"] > 0.9
    p = llm.prompts[-1]
    assert "[A] click_coupon: type a coupon\n[B] click_place_order: click Place order\n[C] go_back: " in p
    assert p.endswith("Answer with the letter of the best option only.<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n")
    assert "assumed" in res.notes[0]


def test_planted_letter_shift_reads_the_wrong_answer():
    models.PLANT_JEV_LETTER_SHIFT[0] = True
    try:
        a = models.run_jev("A checkout page.", Q, llm=FakeLlm("B")).value["answers"]["route"]
    finally:
        models.PLANT_JEV_LETTER_SHIFT[0] = False
    assert a["choice"] == "click_coupon"


def test_noul_and_score_are_calibrated_to_their_types():
    n = models.run_jev("s", {"q": {"type": "noul", "instructions": "Is it?"}}, llm=FakeLlm("A")).value["answers"]["q"]
    # yes favoured by 6 nats, flattened by the slope 1.829: 1/(1+e^(-6/1.829))
    assert n["type"] == "noul" and abs(n["noul"] - 1 / (1 + math.exp(-6 / models.JEV_NOUL_T))) < 1e-3
    s = models.run_jev("s", {"u": {"type": "score", "instructions": "How urgent?", "criteria": ["low", "mid", "high"]}},
                       llm=FakeLlm("C")).value["answers"]["u"]
    assert s["type"] == "score" and s["score"] > 1.8 and set(s["legend"]) == {"0", "1", "2"}


def test_an_all_zero_logit_row_is_an_error_not_a_uniform_answer():
    # Run 94: llama-cpp-python left `scores` zero and every option read 1/3.
    class Zero(FakeLlm):
        @property
        def _ctx(self):
            return type("Ctx", (), {"get_logits": lambda _s: [0.0] * self.vocab})()
    with pytest.raises(RuntimeError, match="all zero"):
        models.run_jev("s", Q, llm=Zero("B"))


@pytest.mark.parametrize("q, says", [
    ({"type": "pick", "criteria": {"a": 1}}, "type is one of"),
    ({"type": "choice", "criteria": {}}, "criteria"),
    ({"type": "score", "criteria": ["only"]}, "two levels"),
    ({"type": "choice", "criteria": {str(i): "" for i in range(53)}}, "at most 52"),
])
def test_a_malformed_question_is_refused_by_name_without_loading(q, says):
    res = models.run_jev("s", {"bad": q}, llm=object())
    assert not res.ok and res.error.startswith("bad:") and says in res.error
