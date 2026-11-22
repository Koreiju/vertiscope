"""The hierarchical rank (PLUGIN_GOAL 177e step 2), each claim with its arm."""

import numpy as np

from domvec import hierank, search
from domvec.vectors import pagerank


def test_levels_host_and_registrable_domain():
    assert hierank.host_of("https://en.wikipedia.org/wiki/Trie") == "en.wikipedia.org"
    assert hierank.registrable("en.wikipedia.org") == "wikipedia.org"
    assert hierank.registrable("www.bbc.co.uk") == "bbc.co.uk"
    assert hierank.registrable("example.com") == "example.com"
    # planted by the live store: two Ontario registrants are two domains.
    assert hierank.registrable("www.city.on.ca") == "city.on.ca"
    assert hierank.registrable("www.abc.de") == "abc.de"
    # Non-web pages share one host node per scheme, never one each.
    assert hierank.host_of("vault://notes/a.md") == hierank.host_of("vault://b.md") == "vault:"


def test_weighted_pagerank_reduces_to_plain_with_unit_weights():
    edges = [(0, 1), (1, 2), (2, 0), (2, 1)]
    a = pagerank(3, edges)
    b = pagerank(3, edges, weights=[1, 1, 1, 1])
    assert np.allclose(a, b)
    # ...and a weight moves mass: 2's mass now goes almost all to 0.
    c = pagerank(3, edges, weights=[1, 1, 9, 1])
    assert c[0] > a[0]


def test_chunks_of_one_page_share_its_rank_so_depth_cannot_enter():
    pr = hierank.page_ranks(["https://a.org/x", "https://b.org/y"], [("https://a.org/x", "https://b.org/y")])
    rows = ["https://a.org/x"] * 5 + ["https://b.org/y"] * 3
    r = hierank.chunk_ranks(rows, pr)
    assert len(set(r[:5].tolist())) == 1 and len(set(r[5:].tolist())) == 1
    assert r[5] > r[0]                     # the linked-to page outranks the linker


def test_host_level_carries_rank_to_siblings():
    # A link INTO one page of a host lifts that host's other page too, through
    # the up/down links; with no host level it would not.
    pages = ["https://h.org/a", "https://h.org/b", "https://x.org/1", "https://y.org/2"]
    links = [("https://x.org/1", "https://h.org/a"), ("https://y.org/2", "https://h.org/a")]
    pr = hierank.page_ranks(pages, links)
    assert pr["https://h.org/b"] > pr["https://y.org/2"]
    # planted: no hierarchy (W_UP = W_DOWN = 0) -- the sibling gets nothing.
    old = hierank.W_UP, hierank.W_DOWN
    try:
        hierank.W_UP = hierank.W_DOWN = 0.0
        flat = hierank.page_ranks(pages, links)
    finally:
        hierank.W_UP, hierank.W_DOWN = old
    assert flat["https://h.org/b"] <= flat["https://y.org/2"] + 1e-9


def _unit(m):
    m = np.asarray(m, dtype=np.float64)
    return m / np.linalg.norm(m, axis=1, keepdims=True)


def test_dual_similarity_needs_both_forms_to_agree():
    urls = ["a", "b", "c"]
    # a~b agree on vocabulary AND meaning; a~c agree on meaning only.
    lex = _unit([[1, 0, 0], [1, 0.1, 0], [0, 0, 1]])
    sem = _unit([[1, 0], [1, 0.1], [1, 0.05]])
    edges = {(a, b) for a, b, _ in hierank.dual_similar(urls, lex, sem, k=1)}
    assert ("a", "b") in edges and ("a", "c") not in edges


def test_audit_tells_layout_similarity_from_dual_similarity():
    # Pages whose layout positions are UNRELATED to their content: the planted
    # layout edges must score far below the dual ones. A measure that gave
    # both the same number could not detect the 177 confusion.
    rng = np.random.default_rng(3)
    n = 40
    topic = np.repeat(np.eye(4), 10, axis=0)
    lex = _unit(topic + 0.05 * rng.random((n, 4)))
    sem = _unit(np.hstack([topic, 0.05 * rng.random((n, 2))]))
    urls = ["p%d" % i for i in range(n)]
    dual = hierank.similarity_audit(urls, lex, sem, hierank.dual_similar(urls, lex, sem))
    lay = hierank.similarity_audit(urls, lex, sem, hierank.layout_similar(urls, rng.random((n, 3))))
    assert dual["mean_dual"] > 0.9
    assert lay["mean_dual"] < 0.5 * dual["mean_dual"]
    assert abs(lay["mean_dual"] - lay["random_pair_mean_dual"]) < 0.2


def test_percentile_ties_share_one_value_and_planted_row_order_does_not():
    v = np.array([0.1, 0.1, 0.1, 0.1, 0.5])
    p = search._percentile(v)
    assert len(set(p[:4].tolist())) == 1 and p[4] == 1.0
    search.PLANT_PERCENTILE_ROW_ORDER[0] = True
    try:
        q = search._percentile(v)
    finally:
        search.PLANT_PERCENTILE_ROW_ORDER[0] = False
    assert len(set(q[:4].tolist())) == 4    # the old tie-break: row order


def test_a_kept_version_takes_its_pages_rank():
    pages = ["https://a.org/x", "https://a.org/x#~v", "https://b.org/y"]
    pr = hierank.page_ranks(pages, [("https://b.org/y", "https://a.org/x")])
    assert "https://a.org/x#~v" not in pr and len(pr) == 2
    r = hierank.chunk_ranks(["https://a.org/x", "https://a.org/x#~v"], pr)
    assert r[0] == r[1]
    hierank.PLANT_VERSIONS_AS_PAGES[0] = True
    try:
        planted = hierank.page_ranks(pages, [("https://b.org/y", "https://a.org/x")])
    finally:
        hierank.PLANT_VERSIONS_AS_PAGES[0] = False
    assert len(planted) == 3
