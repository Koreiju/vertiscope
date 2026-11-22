"""rank_noise's structure measure, on a synthetic containment tree.

The live finding it backs (PLUGIN_GOAL 177e): PageRank over parent->child
`Contains` edges tracks DEPTH. These tests pin that the measure can see it,
that the planted reversal flips it, and that a random rewire erases it --
so a later "the depth bias is gone" cannot be a measure that stopped looking.
"""

import random

from domvec.analytics.rank_noise import depths, structure


def _tree(fan=3, levels=4):
    cids, edges, frontier = ["r"], [], ["r"]
    for _ in range(levels):
        nxt = []
        for p in frontier:
            for k in range(fan):
                c = "%s.%d" % (p, k)
                cids.append(c)
                edges.append((p, c))
                nxt.append(c)
        frontier = nxt
    return cids, edges


def _children(edges):
    out = {}
    for a, _ in edges:
        out[a] = out.get(a, 0) + 1
    return out


def test_depths_follow_containment():
    cids, edges = _tree(fan=2, levels=3)
    d = depths(cids, edges)
    assert d["r"] == 0 and d["r.0"] == 1 and d["r.1.0.1"] == 3


def test_clean_tree_rank_tracks_depth():
    cids, edges = _tree()
    s = structure(cids, edges, depths(cids, edges), _children(edges))
    assert s["spearman_rank_depth"] > 0.5
    assert s["top1pct_leaf_share"] == 1.0


def test_planted_reversal_flips_the_sign():
    cids, edges = _tree()
    d, ch = depths(cids, edges), _children(edges)
    s = structure(cids, [(b, a) for a, b in edges], d, ch)
    # -0.47 here: reversed, the 81 leaves have no in-edges and tie at the
    # minimum rank, which caps |rho|. The claim is the sign flip, with margin.
    assert s["spearman_rank_depth"] < -0.3
    assert s["top1pct_leaf_share"] == 0.0


def test_null_rewire_erases_it():
    # 364 nodes, five rewirings: one rewiring of 121 nodes read 0.201, inside
    # a single correlation's sampling error (~0.09) of zero.
    cids, edges = _tree(levels=5)
    d, ch = depths(cids, edges), _children(edges)
    rhos = []
    for seed in range(5):
        rnd = random.Random(seed)
        null = [(rnd.choice(cids), rnd.choice(cids)) for _ in edges]
        rhos.append(structure(cids, null, d, ch)["spearman_rank_depth"])
    assert abs(sum(rhos) / len(rhos)) < 0.1
