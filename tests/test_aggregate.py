"""`G-26`..`G-33`: merging what is the same thing said differently.

The arm that matters in every one of these is the one that asserts the method
CANNOT find what is not there. A clustering will always return clusters; the
question is whether they are the page's or the algorithm's.
"""

import numpy as np
import pytest

from vertiscope import aggregate
from vertiscope.aggregate import (MIN_CHUNKS, Group, aggregate_page,
                              lca_distance, nearest_neighbour_distances,
                              radius_for, verify_with_lexical)


def _blobs(groups: int, per: int, dims: int = 16, spread: float = 0.01,
           seed: int = 0, loners: int = 24):
    """`groups` tight clusters of `per` points, PLUS isolated points.

    The loners are not decoration. A page made of nothing but tight clusters
    does not occur and cannot be reasoned about: every chunk is equally close
    to something, so there is no "unusually close for this page" to find, and
    a relative criterion correctly declines it -- which is what the first
    version of these tests was actually reporting. Real pages are a few
    repeated shapes among a majority of one-off content, which is what this
    now builds. Loners are labelled -1, so a test can assert they were left
    out of every group.
    """
    rng = np.random.default_rng(seed)
    centres = rng.normal(size=(groups, dims))
    centres /= np.linalg.norm(centres, axis=1, keepdims=True)
    rows, truth = [], []
    for g in range(groups):
        for _ in range(per):
            point = centres[g] + rng.normal(scale=spread, size=dims)
            rows.append(point / np.linalg.norm(point))
            truth.append(g)
    for _ in range(loners):
        point = rng.normal(size=dims)
        rows.append(point / np.linalg.norm(point))
        truth.append(-1)
    return np.asarray(rows, dtype=np.float32), truth


def _page(rows, md="some words here"):
    cids = ["c%03d" % i for i in range(len(rows))]
    return cids, rows, [md] * len(rows)


# --- the radius is the page's, not a constant --------------------------------


def test_the_radius_scales_with_the_page():
    """A tight page gets a narrow radius and a loose one a wide radius.

    This is the whole argument for not using a constant: a reference table of
    near-identical rows and a blog post of unrelated paragraphs cannot share
    a threshold, and one that merges sensibly on either destroys the other.
    """
    tight, _ = _blobs(4, 8, spread=0.005, seed=1, loners=0)
    loose, _ = _blobs(4, 8, spread=0.20, seed=1, loners=0)
    eps_tight, max_tight, _ = radius_for(nearest_neighbour_distances(tight))
    eps_loose, max_loose, _ = radius_for(nearest_neighbour_distances(loose))
    assert max_loose > max_tight, "the loose page is not actually looser"
    assert eps_loose > eps_tight, "the radius did not follow the page"


def test_the_radius_is_the_stated_fraction():
    """Stated in the docstring, so asserted rather than trusted."""
    rows, _ = _blobs(3, 10, seed=2, loners=0)
    nn = nearest_neighbour_distances(rows)
    eps, nn_max, _ = radius_for(nn)
    assert nn_max == pytest.approx(float(nn.max()))
    assert eps == pytest.approx(aggregate.EPS_FRACTION * nn_max)


# --- it finds what is there ---------------------------------------------------


def test_planted_clusters_are_found():
    rows, truth = _blobs(5, 6, spread=0.01, seed=3)
    cids, vectors, mds = _page(rows)
    out = aggregate_page(cids, vectors, mds, "https://test/planted")
    assert not out.skipped, out.skipped
    assert out.groups, "found nothing in five tight clusters"
    # Every group's members should come from ONE planted cluster.
    index = {cid: i for i, cid in enumerate(cids)}
    for group in out.groups:
        labels = {truth[index[c]] for c in group.members}
        assert len(labels) == 1, \
            "a group mixed planted clusters %s" % sorted(labels)


# --- and cannot find what is not ---------------------------------------------


def test_structureless_points_yield_nothing():
    """The null arm, as a test.

    Points with no cluster structure must produce no groups. Without this the
    suite would accept a method that merges on any page at all -- and the
    first null arm written for this DID pass while measuring nothing, because
    it shuffled whole vectors between chunks and left the point cloud
    identical. DBSCAN clusters points; it has never been told a cid.
    """
    rng = np.random.default_rng(7)
    rows = rng.normal(size=(120, 16)).astype(np.float32)
    rows /= np.linalg.norm(rows, axis=1, keepdims=True)
    cids, vectors, mds = _page(rows)
    out = aggregate_page(cids, vectors, mds, "https://test/noise")
    assert not out.groups, \
        "%d groups found in structureless points" % len(out.groups)


def test_shuffling_within_a_dimension_destroys_the_clusters():
    """The null arm applied to a page that really does have clusters.

    Keeps every coordinate's marginal distribution and destroys the
    correlations between them, so the page keeps its spread and loses its
    structure. If this still found groups, the method would be reading the
    shape of the cloud rather than the content of the page.
    """
    rows, _ = _blobs(5, 8, spread=0.01, seed=4)
    real = aggregate_page(*_page(rows), url="https://test/real")
    assert real.groups, "the real arm found nothing to compare against"

    scrambled = np.array(rows, copy=True)
    rng = np.random.default_rng(0)
    for column in range(scrambled.shape[1]):
        rng.shuffle(scrambled[:, column])
    null = aggregate_page(*_page(scrambled), url="https://test/null")
    assert len(null.groups) < len(real.groups) / 4, \
        "null found %d groups against real's %d" % (len(null.groups),
                                                    len(real.groups))


# --- the gate -----------------------------------------------------------------


def test_a_small_page_is_left_alone():
    rows, _ = _blobs(2, 4, seed=5, loners=2)
    out = aggregate_page(*_page(rows), url="https://test/small")
    assert out.skipped, "a page under the gate was clustered anyway"
    assert out.singletons == len(rows), "chunks went missing at the gate"
    assert not out.groups


def test_the_gate_is_a_real_boundary():
    """Non-vacuity for the gate: the same shape passes it when big enough.

    Without this, a gate set absurdly high would make every test above pass
    by never clustering anything.
    """
    small = aggregate_page(*_page(_blobs(2, 3, seed=6, loners=2)[0]),
                           url="u")
    big = aggregate_page(*_page(_blobs(3, MIN_CHUNKS, seed=6)[0]), url="u")
    assert small.skipped and not big.skipped
    assert big.groups, "the gate is not the thing stopping the small page"


# --- merged chunks stay inside the window ------------------------------------


def test_a_group_never_exceeds_the_merge_window():
    """A cluster is a claim that chunks belong together, not that they fit."""
    rows, _ = _blobs(2, 20, spread=0.005, seed=8, loners=30)
    cids = ["c%03d" % i for i in range(len(rows))]
    # Each chunk has to be well UNDER the window, or every run is a single
    # chunk and the cap is never exercised -- which is what the first version
    # of this test actually asserted: 60 words is about 180 tokens against a
    # window of 128, so no two chunks could ever share a run and the test
    # failed reporting "nothing merged" about a correct refusal.
    md = " ".join("word%d" % i for i in range(16))
    out = aggregate_page(cids, rows, [md] * len(rows), "https://test/big",
                         window=128)
    assert out.groups, "nothing merged, so the cap is untested"
    for group in out.groups:
        assert group.tokens <= 128, \
            "a merged chunk is %d tokens against a window of 128" % group.tokens


def test_members_keep_document_order():
    rows, _ = _blobs(3, 8, spread=0.005, seed=9)
    cids, vectors, mds = _page(rows)
    order = {cid: i for i, cid in enumerate(cids)}
    out = aggregate_page(cids, vectors, mds, "https://test/order")
    assert out.groups
    for group in out.groups:
        positions = [order[c] for c in group.members]
        assert positions == sorted(positions), \
            "a merged chunk would read out of order: %s" % positions
        assert group.lead == group.members[0]


# --- the lexical second opinion ----------------------------------------------


def test_lexical_verification_flags_a_vocabulary_mismatch():
    group = Group(lead="a", members=["a", "b"], tokens=10)
    lexical = {"a": np.array([1.0, 0.0, 0.0], dtype=np.float32),
               "b": np.array([0.0, 1.0, 0.0], dtype=np.float32)}
    assert verify_with_lexical(group, lexical) is not None


def test_lexical_verification_passes_a_real_overlap():
    """Non-vacuity: a checker that flagged everything would pass the test
    above and be worthless."""
    group = Group(lead="a", members=["a", "b"], tokens=10)
    lexical = {"a": np.array([1.0, 0.9, 0.1], dtype=np.float32),
               "b": np.array([0.9, 1.0, 0.2], dtype=np.float32)}
    assert verify_with_lexical(group, lexical) is None


# --- the structural metric ----------------------------------------------------


def test_lca_distance_reads_the_tree():
    siblings = lca_distance("/html/body/table/tr[1]/td[1]",
                            "/html/body/table/tr[1]/td[2]")
    cousins = lca_distance("/html/body/table/tr[1]/td[1]",
                           "/html/body/footer/div/p")
    assert siblings < cousins, "siblings are not nearer than cousins"
    assert lca_distance("/html/body/p", "/html/body/p") == 0.0
    assert lca_distance("", "") == 0.0


# --- the structure gate -------------------------------------------------------


def test_a_page_with_no_low_tail_is_declined():
    """Noise must be declined, and the RADIUS alone does not decline it.

    120 random points on a sphere have nn_max 0.578 against a median of
    0.399, so a radius of 0.35 x max is 0.202 and two pairs fell inside it --
    two merges, found in noise, by a criterion that looked principled. The
    gate reads the SHAPE instead: a page with clusters has closest pairs far
    closer than its typical pair, and noise does not.
    """
    rng = np.random.default_rng(7)
    rows = rng.normal(size=(120, 16)).astype(np.float32)
    rows /= np.linalg.norm(rows, axis=1, keepdims=True)
    out = aggregate_page(*_page(rows), url="https://test/noise")
    assert out.skipped, "noise was clustered: %d groups" % len(out.groups)
    assert out.structure_ratio > aggregate.STRUCTURE_RATIO


def test_a_page_with_a_low_tail_is_accepted():
    """Non-vacuity for the gate: one that declined everything would pass the
    test above and make every other test in this file meaningless."""
    rows, _ = _blobs(4, 6, spread=0.01, seed=11)
    out = aggregate_page(*_page(rows), url="https://test/structured")
    assert not out.skipped, out.skipped
    assert out.structure_ratio < aggregate.STRUCTURE_RATIO
    assert out.groups


# --- the merge layer is the PICTURE, not the retrieval unit -------------------


def test_a_group_is_placed_by_what_it_says_not_by_its_first_member():
    """`G-27`: the projector shows aggregated vectors; retrieval keeps 256.

    A lead is still a 256-token chunk with its own vector, and that is what a
    hit resolves to. The group's vector is a SECOND quantity, of the assembled
    text, and it exists because a node standing for eight chunks placed at its
    first member's coordinates is not where the thing it draws belongs.

    One column for both would have made the projector and the retriever
    disagree about what a lead is, silently, in a way no view would show.
    """
    import numpy as np

    from vertiscope.graphstore import EMBED_DIM, GraphStore
    import tempfile, shutil, pathlib

    tmp = tempfile.mkdtemp()
    try:
        store = GraphStore(pathlib.Path(tmp) / "g.kuzu")
        store.conn.execute(
            "CREATE (c:Chunk {cid: 'lead', url: 'u', xpath: '/x', part: 0, "
            "md: 'text', chars: 4, line_count: 1, row: 0})")
        own = [0.0] * EMBED_DIM
        own[0] = 1.0
        store.conn.execute(
            "MATCH (c:Chunk {cid: 'lead'}) SET c.embedding = $v", {"v": own})
        merged = [0.0] * EMBED_DIM
        merged[1] = 1.0
        store.set_group_embedding("lead", merged)

        assert store.embedding("lead")[0] == pytest.approx(1.0), \
            "the group vector overwrote the chunk's own"
        assert store.embedding("lead")[1] == pytest.approx(0.0)
        got = store.group_embedding("lead")
        assert got[1] == pytest.approx(1.0), "the group vector did not stick"
        assert got[0] == pytest.approx(0.0)
        store.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_the_merge_window_is_counted_in_link_free_tokens():
    """512 of TEXT, not of addressing.

    A merged chunk full of `[label](https://very/long/target)` would otherwise
    fit the window on a count that is more than half machine addresses --
    which is the defect `tokens.budget` exists to end, reappearing one stage
    later.
    """
    from vertiscope import tokens
    from vertiscope.aggregate import MERGE_WINDOW

    linky = "[a](https://example.com/a/very/long/path/indeed) " * 40
    assert tokens.count(linky) > MERGE_WINDOW, "the fixture is not long enough"
    assert tokens.budget(linky) < MERGE_WINDOW, \
        "budget is counting the targets"

    cids = ["c%03d" % i for i in range(60)]
    rows, _ = _blobs(2, 15, spread=0.005, seed=12, loners=30)
    out = aggregate_page(cids[:len(rows)], rows, [linky] * len(rows),
                         "https://test/links", window=MERGE_WINDOW)
    for group in out.groups:
        assert group.tokens <= MERGE_WINDOW


# --- G-30: the wiring, not just the function ---------------------------------


def test_the_pipeline_actually_asks_for_the_lexical_second_opinion():
    """`verify_with_lexical` had unit coverage and NO CALLER.

    The PRD's own verdict said so: "exists and looks for the opposite
    signal... not yet wired into the pipeline, so no merge has been checked
    by it." A function with tests and no caller passes every suite there is
    and does nothing, which is the shape `spherical.from_ball` was in too.

    Both arms here, because either alone is vacuous: a group whose members
    share no vocabulary must be flagged, and one whose members share plenty
    must not be. A verifier that flagged everything would satisfy the first.
    """
    import pathlib
    import shutil
    import tempfile

    from vertiscope.aggregate import Aggregation, Group
    from vertiscope.workspace import Workspace

    tmp = tempfile.mkdtemp()
    try:
        with Workspace(pathlib.Path(tmp) / "ws") as ws:
            # Long enough to chunk APART. Three short paragraphs came back
            # as one chunk -- correctly, they fit the window -- and the test
            # then had one row to compare against itself.
            physics = ("quantum chromodynamics gluon hadron lattice "
                       "renormalisation " * 40)
            baking = ("sourdough bakery flour yeast proving basket "
                      "fermentation " * 40)
            more_physics = ("quantum chromodynamics gluon hadron "
                            "confinement lattice " * 40)
            ws.index_html(
                "<html><body>"
                "<div><p>" + physics + "</p></div>"
                "<div><p>" + baking + "</p></div>"
                "<div><p>" + more_physics + "</p></div>"
                "</body></html>",
                "https://fixture.test/lexical")
            chunks = [c for c in ws.store.chunks("https://fixture.test/lexical")
                      if ws.freq.row_of(c.cid) is not None]
            by_text = {}
            for c in chunks:
                md = c.md or ""
                if "sourdough" in md:
                    by_text.setdefault("sourdough", c.cid)
                elif "confinement" in md:
                    by_text.setdefault("confinement", c.cid)
                elif "chromodynamics" in md:
                    by_text.setdefault("chromodynamics", c.cid)
            if len(by_text) < 3:
                import pytest
                pytest.skip("the fixture did not chunk into three parts")

            # THE WIRING, asserted on the SOURCE, and that is a weaker
            # claim than it looks -- said plainly rather than dressed up.
            #
            # Calling the method directly tests the method: with `aggregate`'s
            # call to it deleted, the two behavioural arms below still
            # passed. The obvious fix, a spy on a real `aggregate()` run,
            # cannot reach the call either -- this workspace has no embedder,
            # so the page has no vectors, so aggregation returns `skipped`
            # before it gets there. Standing up an embedder for one assertion
            # would make a fast test slow and flaky.
            #
            # So: the call exists, checked in the source, and the corpus run
            # recorded in the PRD is what says it fires -- 19 pages, 748
            # groups, 14 flagged.
            import inspect

            assert "_lexically_verify" in inspect.getsource(type(ws).aggregate),                 "aggregate() does not ask for the lexical second opinion"

            # Disjoint vocabulary: physics merged with baking.
            wrong = Aggregation(url="https://fixture.test/lexical")
            wrong.groups = [Group(lead=by_text["chromodynamics"],
                                  members=[by_text["chromodynamics"],
                                           by_text["sourdough"]],
                                  tokens=20)]
            ws._lexically_verify(wrong)
            assert wrong.lexical_warnings, \
                "physics merged with baking drew no lexical doubt"

            # Shared vocabulary: two physics sentences.
            right = Aggregation(url="https://fixture.test/lexical")
            right.groups = [Group(lead=by_text["chromodynamics"],
                                  members=[by_text["chromodynamics"],
                                           by_text["confinement"]],
                                  tokens=20)]
            ws._lexically_verify(right)
            assert not right.lexical_warnings, \
                "two sentences sharing four terms were doubted: %r" % (
                    right.lexical_warnings,)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
