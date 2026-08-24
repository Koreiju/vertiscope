"""The third phase: frequency matrix, PageRank, graph store, triple product.

The property tying these together is **row alignment**: one integer indexes a
chunk's frequency vector, its PageRank score and its semantic vector. If that
slips, every score is computed against the wrong chunk and nothing raises —
the results just quietly stop meaning anything. Most of what follows is
checking that it cannot slip.
"""

import json
import pathlib
import tempfile

import numpy as np
import pytest

from domvec.address import ContentAddress
from domvec.graphstore import GraphStore, canonical_url
from domvec.markdown import render_trie
from domvec.pipeline import run_pipeline
from domvec.search import SearchDiagnostics, ThreeFormIndex
from domvec.trie import AddressTrie
from domvec.vectors import EmbeddingMatrix, FreqMatrix, pagerank, tokens

CORPUS = pathlib.Path(__file__).parent / "corpus"
MANIFEST = CORPUS / "manifest.json"


# --- frequency --------------------------------------------------------------


def test_bigrams_come_with_their_unigrams():
    """claim: THEORY Prop. 13.3 — the coherence condition on the tokenizer."""
    got = tokens("web scraping tools")
    assert "web scraping" in got and "web" in got and "scraping" in got


def test_url_query_strings_are_not_indexed_as_words():
    """Machine parameters are not vocabulary.

    Expanding query strings put `ctx_ver` and tracking-widget parameters into
    the index and let link-soup outrank prose — measured on the corpus, the
    top hit for a content query was a citation's COinS blob.
    """
    got = tokens("see https://example.com/wiki/Web_scraping?ctx_ver=Z39.88-2004")
    assert "wiki" in got and "web" in got and "scraping" in got
    assert "ctx_ver" not in got and "z39" not in got


def test_document_frequency_is_derived_not_stored():
    """claim: THEORY Prop. 14.6 — df is determined by the corpus."""
    fm = FreqMatrix()
    fm.add("a", "alpha beta")
    first = fm.document_frequency().copy()
    fm.add("b", "alpha gamma")
    second = fm.document_frequency()
    alpha = fm.vocab["alpha"]
    assert second[alpha] == 2 and first[alpha] == 1


def test_rows_are_stable_across_updates():
    """A row handed out once must stay valid — it is the alignment key."""
    fm = FreqMatrix()
    row = fm.add("a", "first text")
    fm.add("b", "second text")
    assert fm.add("a", "rewritten entirely different words") == row
    assert fm.row_of("a") == row


def test_similarity_is_a_cosine():
    fm = FreqMatrix()
    fm.add("same", "telescope astronomy")
    fm.add("other", "bicycle repair")
    sims = fm.similarities("telescope astronomy")
    assert sims[0] > 0.9 and sims[1] == 0.0


def test_freq_matrix_round_trips_and_stays_appendable(tmp_path):
    """Load must restore the per-row counts, not only the matrix.

    Restoring only the matrix left the count list empty, so the first `add`
    after a load rebuilt from nothing and silently discarded the whole corpus.
    """
    fm = FreqMatrix()
    fm.add("a", "telescope astronomy")
    fm.add("b", "bicycle repair")
    fm.save(tmp_path)

    back = FreqMatrix.load(tmp_path)
    assert np.allclose(back.similarities("telescope"), fm.similarities("telescope"))
    back.add("c", "more astronomy")
    assert back.shape[0] == 3
    assert back.similarities("telescope")[0] > 0


# --- rank -------------------------------------------------------------------


def test_pagerank_is_a_distribution():
    ranks = pagerank(5, [(0, 1), (1, 2), (2, 0), (3, 0)])
    assert ranks.shape == (5,)
    assert abs(float(ranks.sum()) - 1.0) < 1e-5
    assert (ranks > 0).all()


def test_dangling_nodes_do_not_leak_mass():
    """A node with no outgoing edge is most content; dropping its mass would
    rescale every score by how complete the crawl happens to be."""
    ranks = pagerank(4, [(0, 1), (0, 2), (0, 3)])
    assert abs(float(ranks.sum()) - 1.0) < 1e-5


def test_pagerank_prefers_the_linked_to():
    ranks = pagerank(3, [(0, 2), (1, 2)])
    assert ranks[2] > ranks[0] and ranks[2] > ranks[1]


def test_pagerank_of_an_edgeless_graph_is_uniform():
    ranks = pagerank(4, [])
    assert np.allclose(ranks, 0.25)


# --- embeddings -------------------------------------------------------------


def test_embeddings_are_stored_normalised():
    em = EmbeddingMatrix(dim=3)
    em.set("a", np.array([3.0, 0.0, 0.0]))
    assert np.allclose(em.matrix[0], [1.0, 0.0, 0.0])
    assert float(em.similarities(np.array([2.0, 0.0, 0.0]))[0]) == pytest.approx(1.0)


def test_unembedded_rows_score_zero_not_nan():
    em = EmbeddingMatrix(dim=3)
    em.set("a", np.zeros(3))
    sims = em.similarities(np.array([1.0, 0.0, 0.0]))
    assert not np.isnan(sims).any() and float(sims[0]) == 0.0


# --- the graph store --------------------------------------------------------


def test_canonical_url_drops_the_fragment():
    assert canonical_url("a.html#top", "https://h.test/x/") == "https://h.test/x/a.html"
    assert canonical_url("mailto:x@y.z") == ""


@pytest.fixture(scope="module")
def scanned_page():
    if not MANIFEST.exists():
        pytest.skip("frozen corpus absent")
    pages = [p for p in json.loads(MANIFEST.read_text())["pages"] if p.get("ok")]
    page = next((p for p in pages if p["slug"].startswith("books-toscrape")), pages[0])
    html = (CORPUS / f"{page['slug']}.html").read_text(
        encoding="utf-8", errors="replace")
    result = run_pipeline(html, page["url"], render=False)
    trie = AddressTrie.from_tagged(result.tagged, page["url"])
    chunks = render_trie(trie, context_window=1200)
    addresses = [(n.address, n.value, n.content_hash)
                 for n in trie.leaves() if n.address is not None]
    return page["url"], trie, chunks, addresses


@pytest.fixture()
def built(tmp_path, scanned_page):
    url, trie, chunks, addresses = scanned_page
    freq = FreqMatrix()
    rows = {c.cid: freq.add(c.cid, c.markdown) for c in chunks}
    store = GraphStore(tmp_path / "g.kuzu")
    store.ingest(url, addresses, chunks, rows=rows, root_hash=trie.root_hash)
    yield url, trie, chunks, addresses, freq, store
    store.close()


def test_address_reaches_its_chunk_and_embedding(built):
    """The navigational requirement the store exists to satisfy."""
    _url, _trie, chunks, _addresses, _freq, store = built
    anchored = next(c for c in chunks if c.lines)
    aid = anchored.lines[0].address.aid

    chunk = store.chunk_for_address(aid)
    assert chunk is not None and chunk.cid == anchored.cid
    assert len(store.embedding(chunk.cid)) == 768


def test_addresses_of_a_chunk_come_back_in_line_order(built):
    _url, _trie, chunks, _addresses, _freq, store = built
    target = next(c for c in chunks if len(c.lines) > 2)
    got = store.addresses_of(target.cid)
    assert [a.key() for a, _ in got] == target.anchors


def test_stored_addresses_parse_back(built):
    _url, _trie, chunks, _addresses, _freq, store = built
    target = next(c for c in chunks if c.lines)
    for address, _value in store.addresses_of(target.cid):
        assert isinstance(address, ContentAddress)
        assert ContentAddress.parse(address.key()) == address


def test_ingest_is_idempotent(built):
    url, trie, chunks, addresses, freq, store = built
    before = store.stats()
    rows = {c.cid: freq.row_of(c.cid) for c in chunks}
    store.ingest(url, addresses, chunks, rows=rows)
    assert store.stats() == before


def test_containment_links_the_nearest_enclosing_chunk_only(built):
    """Linking every ancestor would make PageRank count wrapper divs."""
    _url, _trie, _chunks, _addresses, _freq, store = built
    targets = [b for _a, b in store.edges()]
    assert len(targets) == len(set(targets)), "a chunk has two parents"


def test_purge_removes_the_page(built):
    url, _trie, chunks, _addresses, _freq, store = built
    assert store.stats()["chunks"] == len(chunks)
    store.purge_page(url)
    assert store.stats()["chunks"] == 0
    assert store.stats()["addresses"] == 0


# --- the triple product -----------------------------------------------------


def test_search_aligns_rows_across_all_three_factors(built):
    _url, _trie, chunks, _addresses, freq, store = built
    index = ThreeFormIndex(store, freq).build()
    assert index.ranks.shape[0] == len(freq.rows)

    hits = index.search("books", k=5)
    for hit in hits:
        row = freq.row_of(hit.cid)
        assert row is not None
        assert hit.rank == pytest.approx(float(index.ranks[row]), rel=1e-5)


def test_semantic_absence_is_reported_not_faked(built):
    """Quiet degradation is the anti-pattern: two factors must not pass as three."""
    _url, _trie, _chunks, _addresses, freq, store = built
    diag = SearchDiagnostics()
    ThreeFormIndex(store, freq).build().search("books", k=3, diagnostics=diag)
    assert diag.semantic_available is False


def test_the_lexical_factor_keeps_its_veto(built):
    """The strict product must return nothing for a query nothing contains."""
    _url, _trie, _chunks, _addresses, freq, store = built
    diag = SearchDiagnostics()
    hits = ThreeFormIndex(store, freq).build().search(
        "quaternion holomorphic sheaf cohomology", k=5, diagnostics=diag)
    assert hits == []
    assert diag.zeroed_by_lexical == diag.candidates


def test_floor_softens_the_veto_only_when_asked(built):
    _url, _trie, _chunks, _addresses, freq, store = built
    index = ThreeFormIndex(store, freq).build()
    strict = index.search("zzzznotpresent", k=5)
    softened = index.search("zzzznotpresent", k=5, floor=1e-6)
    assert strict == []
    assert len(softened) > 0


def test_duplicate_content_collapses_without_embeddings(built):
    """Dedup at retrieval keys on the text, per the no-embeddings constraint."""
    _url, _trie, _chunks, _addresses, freq, store = built
    index = ThreeFormIndex(store, freq).build()
    hits = index.search("books", k=10)
    bodies = [h.markdown for h in hits]
    assert len(bodies) == len(set(bodies))


def test_the_collapse_decision_is_the_same_with_embeddings_present(built):
    """The binding constraint is that dedup *cannot* use embeddings.

    The test above passes whether or not it does — it only checks that the
    hits come back distinct, which a semantic collapse would also achieve. So
    it verifies the outcome and not the constraint.

    This runs the same query twice over the same corpus, once with vectors
    loaded and once without, and asserts the collapse counts match. The
    vectors are degenerate on purpose — see `_Degenerate` — so that a
    collapse consulting them would merge everything, which is the only way
    the two policies differ observably. Verified by mutation: keying the
    collapse on the embedding fails here.
    """
    import numpy as np

    from domvec.search import SearchDiagnostics
    from domvec.vectors import EmbeddingMatrix

    _url, _trie, chunks, _addresses, freq, store = built

    class _Degenerate:
        """Every text maps to the *same* vector.

        A hash-of-the-text embedder was tried first and proved nothing: it
        makes the vector a function of the exact string, so an
        embedding-keyed collapse and a text-keyed one agree on every input,
        and mutating the implementation to consult vectors left the test
        passing. Collapsing the whole vector space to a point is what
        separates the two policies — under it, a collapse that reads a vector
        merges every hit into one, and a collapse that reads the text merges
        only the genuine duplicates.
        """

        def _vec(self, _text):
            return np.ones(768, dtype=np.float32)

        def embed_texts(self, texts, **_kw):
            return np.stack([self._vec(t) for t in texts])

        def embed_query(self, query):
            return self._vec(query)

    plain_diag = SearchDiagnostics()
    plain = ThreeFormIndex(store, freq).build().search(
        "books", k=10, diagnostics=plain_diag, floor=1e-9)

    embedder = _Degenerate()
    matrix = EmbeddingMatrix()
    for chunk in chunks:
        matrix.set(chunk.cid, embedder._vec(chunk.markdown))
    vector_diag = SearchDiagnostics()
    ThreeFormIndex(store, freq, matrix, embedder=embedder).build().search(
        "books", k=10, diagnostics=vector_diag, floor=1e-9)

    assert vector_diag.semantic_available, "the second run had no vectors"
    assert not plain_diag.semantic_available
    assert vector_diag.collapsed == plain_diag.collapsed, (
        f"adding vectors changed how many duplicates collapsed "
        f"({plain_diag.collapsed} -> {vector_diag.collapsed}); the dedup "
        f"decision is reading an embedding"
    )
    assert plain, "no hits, so the comparison proves nothing"


@pytest.mark.parametrize("module", ["markdown.py", "trie.py"])
def test_deduplication_can_reach_neither_a_vector_nor_the_dom(module):
    """Structural, for the two constraints stated as *cannot*, not *does not*.

    Deduplication must not be computed with embeddings, and must not need
    direct DOM access — the second is what lets a scanned page be re-deduped
    from the stored markdown, offline, long after the browser is gone.

    Behavioural tests can say a path *does not* currently do those things.
    Only the absence of the capability says it *cannot*, and that is the
    claim being made. `markdown.py` holds `_dedupe` (token-multiset
    subsumption over strings) and `trie.py` holds the content hashes that
    filter its candidates; neither may mention either concept.
    """
    import pathlib

    source = (pathlib.Path(__file__).resolve().parent.parent
              / "domvec" / module).read_text(encoding="utf-8")
    for banned in ("import numpy", "embedding", "Embedding", "embed_"):
        assert banned not in source, (
            f"{module} mentions {banned!r}; deduplication must not be able to "
            f"reach a vector")
    for banned in ("ShadowDOM", "selenium", "webdriver", "BeautifulSoup",
                   "html_raw"):
        assert banned not in source, (
            f"{module} mentions {banned!r}; deduplication must work from the "
            f"stored markdown, with no live document")


def test_hits_navigate_back_to_addresses(built):
    _url, _trie, _chunks, _addresses, freq, store = built
    index = ThreeFormIndex(store, freq).build()
    hits = index.search("books", k=3)
    assert hits
    for hit in hits:
        addresses = index.addresses_for(hit.cid)
        assert addresses, f"hit {hit.cid} anchors nothing"
        for address, _value in addresses:
            assert address.xpath.startswith("/")
