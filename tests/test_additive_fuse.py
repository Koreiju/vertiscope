"""PLUGIN_GOAL 85: retrieval terms are additive, each normalized to 0..1 (`search._unit`,
`search._percentile`, `ADDITIVE_WEIGHTS`)."""

import numpy as np

from domvec.search import ADDITIVE_WEIGHTS, _percentile, _unit


def test_unit_puts_a_term_on_zero_to_one():
    u = _unit(np.array([0.0, 2.0, 4.0, -1.0]))
    assert u.tolist() == [0.0, 0.5, 1.0, 0.0]


def test_unit_of_nothing_is_zero_not_nan():
    assert _unit(np.zeros(3)).tolist() == [0.0, 0.0, 0.0]


def test_pagerank_by_position_not_magnitude():
    # PageRank values span orders of magnitude; their percentile does not.
    p = _percentile(np.array([1e-9, 1e-3, 1e-6]))
    assert p.tolist() == [0.0, 1.0, 0.5]


def test_weights_sum_to_one():
    assert abs(sum(ADDITIVE_WEIGHTS.values()) - 1.0) < 1e-9


def test_a_missing_term_costs_its_share_not_the_hit():
    # The point of adding: a chunk with no PageRank (a fresh page) and the best
    # text match is not zeroed, as the product zeroes it.
    w = ADDITIVE_WEIGHTS
    lex, sem, pr, con = _unit(np.array([1.0, 0.5])), _unit(np.array([0.9, 0.8])), np.array([0.0, 1.0]), np.array([1.0, 1.0])
    additive = w["lexical"] * lex + w["semantic"] * sem + w["pagerank"] * pr + w["content"] * con
    product = np.array([1.0, 0.5]) * np.array([0.9, 0.8]) * np.array([0.0, 1.0])
    assert additive[0] > additive[1]          # the better match leads
    assert product[0] == 0.0                   # the product vetoed it
