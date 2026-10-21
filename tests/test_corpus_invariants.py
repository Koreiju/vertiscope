"""Properties of the whole store, rather than of one page.

These are the rows that are claims about the CORPUS -- one vocabulary, one
database, one trie -- and they are asserted here rather than in the live
pane because the pane cannot see any of them. A projector showing a correct
picture says nothing about whether tf-idf was fitted per page or globally.
"""

import pathlib
import shutil
import tempfile

import pytest

from vertiscope.workspace import Workspace

PAGE_A = ("<html><body><p>alpha beta gamma spindle lattice vortex</p>"
          "</body></html>")
PAGE_B = ("<html><body><p>delta epsilon zeta spindle bakery proving</p>"
          "</body></html>")
SOURCE = ('"""A module about spindles."""\n\n\n'
          'def spin(n):\n    """Turn it."""\n    return n\n')


@pytest.fixture()
def ws():
    tmp = tempfile.mkdtemp()
    try:
        with Workspace(pathlib.Path(tmp) / "ws") as got:
            yield got
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_tfidf_is_global_to_the_corpus_not_per_page(ws):
    """`S-6`. One vocabulary over everything, not one per document.

    The distinction is not cosmetic: idf is what makes a common word cheap
    and a rare one informative, and idf computed per page has no corpus to
    be rare IN. A word appearing once on each of two pages would score as
    maximally distinctive on both.
    """
    ws.index_html(PAGE_A, "https://a.test/one")
    before = ws.freq.shape[1]
    ws.index_html(PAGE_B, "https://b.test/two")
    after = ws.freq.shape[1]

    # One matrix, growing as the corpus does.
    assert after > before, "the second page added no vocabulary"
    assert ws.freq.shape[0] >= 2, "each page did not get its own row"

    # The shared term is ONE column, not one per page. (The vocabulary holds
    # bigrams too, so the unigram is the thing to count: `spindle`
    # legitimately also appears inside `gamma spindle` and `spindle bakery`.)
    vocab = list(ws.freq.vocab)
    assert vocab.count("spindle") == 1, vocab.count("spindle")

    # The arm that makes this non-vacuous: a term private to ONE page is
    # still in the shared vocabulary the OTHER page's row is scored against.
    # Per-page fitting is exactly what would make this false.
    assert "bakery" in vocab, "a term from page B is missing"
    assert "lattice" in vocab, "a term from page A is missing"


def test_vectors_and_graph_links_live_in_one_database(ws):
    """`T-7`. Semantic vectors and hard links, same store."""
    # A corpus that actually has a link to find: B exists, and A points at
    # it. `LinksTo` only lands when the target page is in the store, so a
    # corpus of unlinked pages would prove nothing in either direction.
    ws.index_html(PAGE_B, "https://b.test/two")
    ws.index_html(
        '<html><body><p>alpha beta gamma spindle lattice vortex '
        '<a href="https://b.test/two">onward</a></p></body></html>',
        "https://a.test/one")
    ws.store.relink()

    links = ws.store._rows(
        "MATCH ()-[r:LinksTo]->() RETURN count(r)")[0][0]
    assert links > 0, "the anchor produced no edge"

    # An embedder is not what this row is about, so the vector is written
    # directly. The claim under test is that the SAME database holds it.
    cid = ws.store._rows(
        "MATCH (c:Chunk)-[:LinksTo]->(:Page) RETURN c.cid LIMIT 1")[0][0]
    ws.store._batch(
        "UNWIND $rows AS r MATCH (c:Chunk {cid: r.cid}) "
        "SET c.embedding = r.emb",
        [{"cid": cid, "emb": [0.5] * 768}])

    # **One query reaching both.** Were the vectors and the hard links in
    # separate stores, this traversal could not be written at all -- which
    # is the strongest form the row can be asserted in.
    got = ws.store._rows(
        "MATCH (c:Chunk)-[:LinksTo]->(p:Page) "
        "WHERE c.embedding IS NOT NULL "
        "RETURN c.cid, p.url, c.embedding[1]")
    assert got, "no chunk carries both a vector and an edge"
    assert got[0][1] == "https://b.test/two", got[0]
    assert abs(got[0][2] - 0.5) < 1e-6, got[0]


def test_an_installed_package_is_partitioned_by_package(ws):
    """`T-6`. Per-package partitioning, with the main DB holding it.

    The url IS the partition: `code://pypi/<name>/...`. Nothing separate has
    to be maintained, which is the point of defining the addressing to look
    like a page's.
    """
    ws.index_source(SOURCE, "spin.py", root="pypi/alpha")
    ws.index_source(SOURCE, "spin.py", root="pypi/beta")
    urls = {c.url for c in ws.store.chunks()}
    assert "code://pypi/alpha/spin.py" in urls, urls
    assert "code://pypi/beta/spin.py" in urls, urls
    # Same file, two packages, two addresses -- not one collapsed entry.
    assert len({u for u in urls if u.startswith("code://pypi/")}) == 2


def test_an_intermediate_trie_path_is_a_drawable_linkage(ws):
    """`T-4`. Intermediate paths reflected as intermediate node linkages.

    `layout.unfold` emits a `path:` node for a branch standing in for
    several chunks, and the hub star joins them -- which is what `G-6`
    draws. Asserted here on the SHAPE the trie produces, since the drawing
    is confirmed live and this is the half testable without a pane.
    """
    ws.index_html(
        "<html><body>"
        "<div><section><p>" + ("alpha beta gamma " * 60) + "</p>"
        "<p>" + ("delta epsilon zeta " * 60) + "</p></section></div>"
        "</body></html>",
        "https://a.test/deep")
    xpaths = [c.xpath for c in ws.store.chunks("https://a.test/deep")]
    assert xpaths, "no chunks"
    depths = {len([s for s in x.split("/") if s]) for x in xpaths}
    assert max(depths) >= 2, xpaths


# --------------------------------------------------------------------------
# `S-5`: the queue between the distilled markdown and the embedder.
#
# The existing `VectorQueue` tests cover reuse and the digest gate. Neither
# touches what this row actually claims -- that vectorisation does not run
# per delta, and that it leaves in chunk-BATCHES. The discriminator for both
# is the number of times the embedder is CALLED, which nothing was counting.
# --------------------------------------------------------------------------

class _CountingEmbedder:
    """Records every call and its width."""

    def __init__(self, dim=8):
        self.dim = dim
        self.calls = []

    def embed_texts(self, texts):
        import numpy as np
        self.calls.append(len(texts))
        return np.stack([
            np.full(self.dim, (abs(hash(t)) % 997) / 997.0, dtype=np.float32)
            for t in texts
        ])


def test_a_chunk_rewritten_between_flushes_is_embedded_once():
    """`S-5`, first half: vectorisation may not run per delta.

    A scrolling feed rewriting one header on every frame is the case this
    exists for. Cost must follow *settled* change, not churn.
    """
    from vertiscope.vectors import VectorQueue

    q = VectorQueue()
    embedder = _CountingEmbedder()
    for i in range(20):
        q.push("cid-a", "the header, revision %d" % i)
    out = q.flush(embedder)

    assert len(out) == 1, out.keys()
    assert sum(embedder.calls) == 1, \
        "20 rewrites cost %d embeddings" % sum(embedder.calls)

    # Non-vacuity: 20 DISTINCT chunks must cost 20, or the assert above is
    # measuring the flush rather than the coalescing.
    q2, e2 = VectorQueue(), _CountingEmbedder()
    for i in range(20):
        q2.push("cid-%d" % i, "the header, revision %d" % i)
    q2.flush(e2)
    assert sum(e2.calls) == 20, sum(e2.calls)


def test_the_queue_leaves_in_batches_not_one_call_per_chunk():
    """`S-5`, second half: chunk-batches.

    Asserted on the WIDTH of each call. A queue that embedded one chunk per
    call would satisfy every other test in this file and still be the thing
    the row forbids.
    """
    from vertiscope.vectors import VectorQueue

    q = VectorQueue(batch=16)
    embedder = _CountingEmbedder()
    for i in range(40):
        q.push("cid-%d" % i, "chunk number %d, quite distinct" % i)
    q.flush(embedder)

    assert embedder.calls == [16, 16, 8], embedder.calls
    assert max(embedder.calls) <= 16, "a batch exceeded its width"
    assert len(embedder.calls) == 3, \
        "40 chunks at 16 took %d calls" % len(embedder.calls)


# --------------------------------------------------------------------------
# `S-11`: the verification pass, and the arm that keeps it honest.
# --------------------------------------------------------------------------

def test_the_window_pass_separates_a_leaf_from_an_uncut_chunk(ws, tmp_path):
    """`S-11`. Two denominators, because there are two questions.

    The row says the window is a target rather than a ceiling and that a
    single indivisible unit may exceed it. So a one-line chunk over the
    window is the record rule working, and a multi-line one is a cut that
    did not happen. One number over both populations would either excuse
    the second or condemn the first.
    """
    from vertiscope.analytics.window import measure_window

    ws.index_html(PAGE_A, "https://a.test/one")
    root = ws.path
    ws.close()

    report = measure_window(str(root), window=256, plant=True)

    # The planted record is multi-line, so it must land in the CUTTABLE
    # bucket -- the one that is supposed to be empty.
    assert report["plant_caught"] is True, report
    assert report["plant_cost"] > 256, report["plant_cost"]
    assert report["chunks"]["divisible"]["over"] >= 1, report["chunks"]

    # And without the planting, the same pass over the same store must not
    # report that over. A check that cannot fail is not measuring.
    clean = measure_window(str(root), window=256, plant=False)
    assert clean["chunks"]["divisible"]["over"] \
        < report["chunks"]["divisible"]["over"], (clean, report)
    assert "plant_caught" not in clean


def test_the_window_pass_scores_merge_groups_not_only_chunks(ws, tmp_path):
    """`S-11`. The stage that had never been checked.

    A merge group's assembled markdown is a NEW string, longer than any
    member by construction, and it is what a reader is shown and what
    re-vectorisation embeds. A pass that scored only the chunks would
    report a window holding while the string that reaches a model does not.
    """
    from vertiscope.analytics.window import measure_window

    ws.index_html(PAGE_A, "https://a.test/one")
    root = ws.path
    ws.close()

    report = measure_window(str(root), window=256)
    assert "groups" in report, report.keys()
    # The population is reported even when it is empty, so a store with no
    # groups reads as "nothing to score" rather than silently as a pass.
    assert set(report["groups"]) >= {"n", "over", "pct_over", "max"}


# --------------------------------------------------------------------------
# `D-22`: a layout key must name the corpus, not measure it.
# --------------------------------------------------------------------------

def test_two_different_corpora_do_not_share_a_layout_key(ws):
    """A count is not an identity.

    The layout cache and the persisted fit were keyed on `chunk_count()`.
    Delete one page and add another of the same size and the count is
    unchanged while the corpus is not -- so a stored fit comes back for
    documents it never saw. Measured live before the fix: a served page
    layout still carried nodes for purged fixture pages, and unfolding one
    of its pages anchored 643 units away against a ball of radius 90.
    """
    ws.index_html(PAGE_A, "https://a.test/one")
    ws.index_html(PAGE_B, "https://b.test/two")
    before_count = ws.store.chunk_count()
    before_print = ws.store.corpus_fingerprint()

    # Swap one page for a different one of the same chunk count.
    ws.store.purge_page("https://b.test/two")
    ws.index_html(PAGE_B, "https://c.test/three")

    assert ws.store.chunk_count() == before_count, \
        "the arm needs the COUNT to be unchanged, or it proves nothing"
    assert ws.store.corpus_fingerprint() != before_print, \
        "two different corpora share a fingerprint"


def test_the_fingerprint_is_stable_for_an_unchanged_corpus(ws):
    """The other direction: it must not churn, or nothing is ever cached.

    A fingerprint that changed on every call would invalidate the fit on
    every request and turn a 95-second chunk-level layout into something
    paid per page load. Non-vacuity for the test above.
    """
    ws.index_html(PAGE_A, "https://a.test/one")
    ws.index_html(PAGE_B, "https://b.test/two")
    first = ws.store.corpus_fingerprint()
    assert ws.store.corpus_fingerprint() == first
    assert ws.store.corpus_fingerprint() == first

    # And it MOVES when a page's own chunk count changes, not only when
    # pages come and go.
    ws.index_html(
        "<html><body>" + "<p>alpha beta gamma delta epsilon</p>" * 80
        + "</body></html>", "https://a.test/one")
    assert ws.store.corpus_fingerprint() != first
