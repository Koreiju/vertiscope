"""The workspace: one object, three persistent stores, kept in step.

The graph, the frequency matrix and the JSONL each hold part of a page, and
the thing that can go wrong is drift — a chunk in the graph with no frequency
row, or a row index that points at a different chunk than it did. Every write
goes through one method precisely so that cannot happen, and these check it.
"""

import json
import pathlib

import pytest

from vertiscope.markdown import read_jsonl
from vertiscope.privacy import store_name
from vertiscope.workspace import Workspace, _slug

CORPUS = pathlib.Path(__file__).parent / "corpus"
MANIFEST = CORPUS / "manifest.json"


def _html(prefix="books-toscrape"):
    if not MANIFEST.exists():
        pytest.skip("frozen corpus absent")
    pages = [p for p in json.loads(MANIFEST.read_text())["pages"] if p.get("ok")]
    page = next((p for p in pages if p["slug"].startswith(prefix)), pages[0])
    return page["url"], (CORPUS / f"{page['slug']}.html").read_text(
        encoding="utf-8", errors="replace")


@pytest.fixture()
def ws(tmp_path):
    with Workspace(tmp_path / "ws") as workspace:
        yield workspace


# --- the write path ---------------------------------------------------------


def test_indexing_writes_all_three_stores(ws):
    url, html = _html()
    result = ws.index_html(html, url)

    assert result.addresses > 0 and result.chunks > 0
    stats = ws.stats()
    assert stats["chunks"] == result.chunks
    assert stats["freq_rows"] == result.chunks
    assert ws.mirror_path(url).exists()


def test_every_chunk_has_a_frequency_row(ws):
    """The drift that would make every score point at the wrong chunk."""
    url, html = _html()
    ws.index_html(html, url)
    for chunk in ws.store.chunks():
        assert ws.freq.row_of(chunk.cid) is not None, f"{chunk.cid} unindexed"
        assert chunk.row == ws.freq.row_of(chunk.cid), (
            f"{chunk.cid}: graph says row {chunk.row}, matrix says "
            f"{ws.freq.row_of(chunk.cid)}"
        )


def test_the_jsonl_matches_what_was_stored(ws):
    url, html = _html()
    ws.index_html(html, url)
    from_file = list(read_jsonl(ws.mirror_path(url)))
    from_graph = {c.cid: c for c in ws.store.chunks(url)}
    assert len(from_file) == len(from_graph)
    for chunk in from_file:
        assert chunk.cid in from_graph
        assert chunk.markdown == from_graph[chunk.cid].md


def test_reindexing_the_same_page_does_not_duplicate(ws):
    url, html = _html()
    ws.index_html(html, url)
    before = ws.stats()
    ws.index_html(html, url)
    after = ws.stats()
    assert after["chunks"] == before["chunks"]
    assert after["addresses"] == before["addresses"]
    assert after["freq_rows"] == before["freq_rows"]


def test_two_pages_share_one_vocabulary(ws):
    """The frequency matrix is corpus-wide; that is why it is not per-chunk."""
    url1, html1 = _html("books-toscrape")
    url2, html2 = _html("quotes-toscrape")
    ws.index_html(html1, url1)
    terms_one = ws.freq.shape[1]
    ws.index_html(html2, url2)
    assert ws.freq.shape[1] > terms_one
    assert ws.stats()["pages"] == 2


# --- the read path ----------------------------------------------------------


def test_search_returns_hits_that_resolve_to_addresses(ws):
    url, html = _html()
    ws.index_html(html, url)
    hits = ws.search("books", k=5)
    assert hits
    for hit in hits:
        addresses = ws.addresses_for(hit.cid)
        assert addresses
        for address, _value in addresses:
            assert address.url == url
            assert address.xpath.startswith("/")


def test_the_index_is_rebuilt_after_a_write(ws):
    """A stale PageRank would rank the corpus as it was before the last scan."""
    url1, html1 = _html("books-toscrape")
    ws.index_html(html1, url1)
    first = len(ws.index.ranks)

    url2, html2 = _html("quotes-toscrape")
    ws.index_html(html2, url2)
    assert len(ws.index.ranks) > first


def test_stats_report_every_store(ws):
    url, html = _html()
    ws.index_html(html, url)
    stats = ws.stats()
    for key in ("pages", "chunks", "addresses", "freq_rows", "freq_terms"):
        assert key in stats


# --- persistence ------------------------------------------------------------


def test_a_workspace_reopens_with_its_contents(tmp_path):
    url, html = _html()
    with Workspace(tmp_path / "ws") as first:
        first.index_html(html, url)
        expected = first.stats()

    with Workspace(tmp_path / "ws") as second:
        stats = second.stats()
        assert stats["chunks"] == expected["chunks"]
        assert stats["addresses"] == expected["addresses"]
        assert stats["freq_rows"] == expected["freq_rows"]
        assert second.search("books", k=3)


def test_reopening_and_adding_keeps_the_earlier_rows(tmp_path):
    """The failure mode when a matrix is restored without its counts."""
    url1, html1 = _html("books-toscrape")
    url2, html2 = _html("quotes-toscrape")
    with Workspace(tmp_path / "ws") as first:
        first.index_html(html1, url1)
        rows = first.stats()["freq_rows"]

    with Workspace(tmp_path / "ws") as second:
        second.index_html(html2, url2)
        assert second.stats()["freq_rows"] > rows
        assert second.search("books", k=3), "the first page became unfindable"


# --- deletes ----------------------------------------------------------------


def test_purging_a_page_removes_it_from_the_graph_and_disk(ws):
    url, html = _html()
    ws.index_html(html, url)
    assert ws.mirror_path(url).exists()

    ws.purge(url)
    assert ws.stats()["chunks"] == 0
    assert not ws.mirror_path(url).exists()


_PAGE = "<html><body><h1>Title</h1><p>Some words here.</p></body></html>"


# --- store names ------------------------------------------------------------
#
# The old scheme kept the url in the filename, which made `ls chunks/` a
# browsing history readable without opening anything. What replaced it has to
# stay filesystem-safe and collision-free -- the two properties the slug was
# there for -- while disclosing nothing.


def test_a_store_name_is_filesystem_safe():
    name = store_name("https://x.test/a/b?q=1&r=2#frag")
    assert "/" not in name and "?" not in name and "#" not in name


def test_long_urls_sharing_a_prefix_do_not_collide():
    """Truncation without a hash would map two pages to one file."""
    base = "https://x.test/" + "a" * 100
    assert store_name(base + "/one") != store_name(base + "/two")
    assert len(store_name(base + "/one")) <= 60


def test_a_store_name_discloses_no_part_of_the_url():
    """The name is the whole disclosure surface of a directory listing."""
    url = "https://en.wikipedia.org/wiki/Insomnia?utm_source=x"
    name = store_name(url)
    for fragment in ("wikipedia", "wiki", "Insomnia", "insomnia", "https",
                     "en", "org", "utm"):
        assert fragment not in name


def test_a_listing_of_the_chunk_directory_is_not_a_history(ws):
    """The whole of B3: what `ls` prints must not name what was read."""
    ws.index_html(_PAGE, "https://secret.example/very-private-topic")
    listing = " ".join(p.name for p in ws.chunks_dir.iterdir())
    assert listing
    for fragment in ("secret", "example", "private", "topic"):
        assert fragment not in listing.lower()


def test_a_page_is_stored_under_one_name_however_it_was_reached(ws):
    """Campaign tags must not split one page into two mirrors."""
    plain = "https://a.test/article"
    tagged = "https://a.test/article?utm_source=newsletter&fbclid=123abc"
    ws.index_html(_PAGE, plain)
    ws.index_html(_PAGE, tagged)
    assert len(list(ws.chunks_dir.glob("*.jsonl"))) == 1


def test_a_legacy_readable_mirror_is_renamed_on_open(tmp_path):
    """Existing workspaces are migrated, not left leaking.

    An opt-in would have left the readable names in place in exactly the
    workspaces that have a history in them.
    """
    from vertiscope.markdown import read_jsonl as _read

    path = tmp_path / "ws"
    url = "https://en.wikipedia.org/wiki/Insomnia"
    with Workspace(path) as ws:
        ws.index_html(_PAGE, url)
        digest = ws.mirror_path(url)
        legacy = ws.chunks_dir / f"{_slug(url)}.jsonl"
        digest.replace(legacy)          # put the old scheme back on disk

    assert legacy.exists()
    with Workspace(path) as ws:
        assert not legacy.exists()
        assert ws.mirror_path(url).exists()
        assert list(_read(ws.mirror_path(url)))


def test_migration_skips_a_file_it_cannot_read(tmp_path):
    """A junk file is left alone rather than taking the workspace down."""
    path = tmp_path / "ws"
    path.mkdir()
    (path / "chunks").mkdir()
    junk = path / "chunks" / "not-a-mirror.jsonl"
    junk.write_text("this is not json\n", encoding="utf-8")
    with Workspace(path) as ws:
        assert ws.chunks_dir.exists()
    assert junk.exists()


# --- semantic vectors -------------------------------------------------------


class _FakeEmbedder:
    """A deterministic stand-in for the nomic model.

    Real embeddings need a GPU and a multi-gigabyte GGUF, which would make
    this suite untestable in CI. What is under test here is the *wiring* —
    are vectors stored, reloaded, and backfilled when absent — and that is
    independent of what the numbers mean. The vectors are a hash of the text,
    so identical text embeds identically and different text does not.
    """

    dim = 768

    def __init__(self):
        self.calls = 0

    def embed_texts(self, texts, **_kw):
        import hashlib

        import numpy as np

        self.calls += 1
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, text in enumerate(texts):
            digest = hashlib.sha1(text.encode("utf-8")).digest()
            seed = int.from_bytes(digest[:8], "big")
            # Non-negative: a cosine of signed random vectors is negative half
            # the time, and the product ranking vetoes it, so whether a test
            # found ANY hit was a coin flip on the text's hash -- re-indenting
            # the markdown (R-K1) flipped both "books" chunks to negative.
            out[i] = np.abs(np.random.default_rng(seed).standard_normal(self.dim))
        return out

    def embed_query(self, query):
        return self.embed_texts([query])[0]


def test_vectors_are_stored_when_an_embedder_is_present(tmp_path):
    url, html = _html()
    with Workspace(tmp_path / "ws", embedder=_FakeEmbedder()) as ws:
        ws.index_html(html, url)
        for chunk in ws.store.chunks():
            vector = ws.store.embedding(chunk.cid)
            assert vector and any(vector), f"{chunk.cid} stored a zero vector"


def test_vectors_are_reloaded_into_a_reopened_workspace(tmp_path):
    """Stored but not loaded scores every row zero, which the product vetoes."""
    url, html = _html()
    with Workspace(tmp_path / "ws", embedder=_FakeEmbedder()) as ws:
        ws.index_html(html, url)

    with Workspace(tmp_path / "ws", embedder=_FakeEmbedder()) as ws:
        counts = ws._hydrate_embeddings()
        assert counts["loaded"] > 0
        assert counts["embedded"] == 0, "reloading should not recompute"


def test_semantic_backfills_a_workspace_indexed_without_it(tmp_path):
    """The bug this closes: asking for semantic search returned nothing.

    A workspace indexed with no embedder has all-zero vectors. Under the
    strict triple product a zero is a veto, so every candidate was rejected
    and the result was reported as an absence of matches rather than an
    absence of vectors.
    """
    url, html = _html()
    with Workspace(tmp_path / "ws") as ws:          # no embedder
        ws.index_html(html, url)
        chunks = len(ws.store.chunks())

    with Workspace(tmp_path / "ws", embedder=_FakeEmbedder()) as ws:
        counts = ws._hydrate_embeddings()
        assert counts["embedded"] == chunks
        assert ws.embeddings is not None
        assert ws.embeddings.matrix.any(), "backfill produced only zeros"


def test_a_backfill_is_persisted(tmp_path):
    """Paid once, not on every query."""
    url, html = _html()
    with Workspace(tmp_path / "ws") as ws:
        ws.index_html(html, url)

    with Workspace(tmp_path / "ws", embedder=_FakeEmbedder()) as ws:
        first = ws._hydrate_embeddings()

    with Workspace(tmp_path / "ws", embedder=_FakeEmbedder()) as ws:
        second = ws._hydrate_embeddings()

    assert first["embedded"] > 0
    assert second["embedded"] == 0, "the backfill was not written back"
    assert second["loaded"] == first["embedded"]


def test_all_three_factors_contribute_when_vectors_are_present(tmp_path):
    url, html = _html()
    with Workspace(tmp_path / "ws", embedder=_FakeEmbedder()) as ws:
        ws.index_html(html, url)
        hits = ws.search("books", k=5)
        assert hits
        assert any(h.semantic != 0.0 for h in hits), "the semantic factor is dead"
        assert all(h.rank > 0 for h in hits)


# --- crawling ---------------------------------------------------------------


def test_non_documents_are_kept_out_of_the_frontier():
    """The extractor is attribute-agnostic; the crawl frontier must not be.

    A stylesheet's href is a `urls.internal` address exactly like an anchor's,
    which is right for extraction and wrong for crawling: a six-page budget
    was spending two pages on main.css and bootstrap.min.css.
    """
    from vertiscope.workspace import _is_document

    for url in ("https://x.test/static/main.css",
                "https://x.test/app.js",
                "https://x.test/logo.svg",
                "https://x.test/report.pdf",
                "https://x.test/fonts/x.woff2"):
        assert not _is_document(url), url

    for url in ("https://x.test/",
                "https://x.test/tag/life/",
                "https://x.test/page/2",
                "https://x.test/article.html",
                "https://x.test/search?q=a.css"):
        assert _is_document(url), url


def test_links_come_from_the_stored_addresses(ws):
    """No second link extractor: the frontier is the trie's urls.* addresses."""
    url, html = _html()
    ws.index_html(html, url)
    links = ws.links_from(url, same_host=False)
    assert links, "a page full of anchors produced no frontier"
    assert all(not link.endswith(".css") for link in links)
    assert url not in links, "a page must not queue itself"


def test_same_host_filtering(ws):
    url, html = _html()
    ws.index_html(html, url)
    from urllib.parse import urlsplit
    host = urlsplit(url).netloc
    for link in ws.links_from(url, same_host=True):
        assert urlsplit(link).netloc == host


def test_link_edges_reach_the_graph(ws):
    """PageRank needs edges; without them the factor is near-uniform.

    Measured over the 54-page corpus there were six resolvable cross-page
    links in total, so the rank factor contributed nothing while appearing to.

    This used to assert ``links >= 0`` — "the mechanism exists and does not
    raise" — which is true of a function that returns without doing anything,
    and is how a url-matching defect that dropped three quarters of the
    resolvable edges went unnoticed. It now asserts an edge.
    """
    url1, html1 = _html("books-toscrape")
    url2, html2 = _html("books-toscrape-com-catalogue")
    ws.index_html(html1, url1)
    ws.index_html(html2, url2)
    # Re-index the first now that the second page exists, so its links resolve.
    ws.index_html(html1, url1)
    assert ws.stats()["links"] > 0, "no link edge was created between two " \
                                    "pages of the same site"
    assert len(ws.index.ranks) == ws.stats()["chunks"]


HOME = "<html><body><h1>Home</h1><p>the front page</p></body></html>"
SUB = ("<html><body><h1>Sub</h1>"
       "<a href='/'>Home</a> <a href='/other.html'>Other</a>"
       "</body></html>")


def test_a_link_resolves_to_a_page_stored_under_a_different_spelling(ws):
    """`https://a.test` on disk; `https://a.test/` out of `canonical_url`.

    A page is stored under the url it was scanned with, and link targets are
    canonicalised before use, so a bare-host url never matched the canonical
    form of itself. On a real twenty-page workspace five stored urls were in
    that state and three of the four same-host targets pointing at a scanned
    page were dropped — each one a missing PageRank contribution, on the
    factor whose whole job is to say which pages matter.
    """
    ws.index_html(HOME, "https://a.test")            # no trailing slash
    ws.index_html(SUB, "https://a.test/sub.html")

    edges = ws.store.edges()
    home_chunks = {c.cid for c in ws.store.chunks("https://a.test")}
    sub_chunks = {c.cid for c in ws.store.chunks("https://a.test/sub.html")}
    crossing = [(a, b) for a, b in edges
                if a in sub_chunks and b in home_chunks]
    assert crossing, (
        f"the sub page's link to '/' did not reach the home page stored as "
        f"'https://a.test'; edges={edges}")


def test_resolve_page_prefers_an_exact_match(ws):
    """A workspace holding both spellings must not collapse them.

    Pages are stored under the url they were scanned with — deliberately, see
    `Workspace.page_url` — so both spellings can coexist, and resolution must
    then be the identity rather than a guess.
    """
    ws.index_html(HOME, "https://a.test")
    ws.index_html(SUB, "https://a.test/")
    assert ws.store.resolve_page("https://a.test") == "https://a.test"
    assert ws.store.resolve_page("https://a.test/") == "https://a.test/"


def test_a_caller_may_use_either_spelling(ws):
    """`purge --url https://a.test/` must reach the page stored bare."""
    ws.index_html(HOME, "https://a.test")
    assert ws.stats()["chunks"] > 0
    assert ws.links_from("https://a.test/", same_host=False) == \
        ws.links_from("https://a.test", same_host=False)
    ws.purge("https://a.test/")
    assert ws.stats()["chunks"] == 0, "purge missed the page it was given"


def test_resolve_page_reports_a_page_it_does_not_have(ws):
    ws.index_html(HOME, "https://a.test")
    assert ws.store.resolve_page("https://b.test/") == ""
    assert ws.store.resolve_page("") == ""


def test_pagerank_covers_every_chunk(ws):
    url, html = _html()
    ws.index_html(html, url)
    ranks = ws.index.ranks
    assert len(ranks) == ws.stats()["freq_rows"]
    assert abs(float(ranks.sum()) - 1.0) < 1e-4


def test_a_crawl_does_not_spend_two_pages_on_one_document(ws, monkeypatch):
    """`/` and `/index.html` are one page for a crawl budget.

    A real four-page crawl of books.toscrape.com scanned
    `https://books.toscrape.com` and `https://books.toscrape.com/index.html`
    — the same document, byte for byte, 501 addresses and 20 chunks each —
    spending half its budget on one page. `canonical_url` does not collapse
    them because they are genuinely different urls; for a budget they are one.

    Dedup key only: the crawl still *stores* whatever url it scanned, so no
    address changes.
    """
    from vertiscope.graphstore import canonical_url

    _INDEX = ("/index.html", "/index.htm", "/index.php",
              "/default.html", "/default.htm", "/index.asp")

    def key_of(url):
        key = canonical_url(url) or url
        low = key.lower()
        for suffix in _INDEX:
            if low.endswith(suffix):
                return key[: -len(suffix)] + "/"
        return key

    same = {key_of(u) for u in (
        "https://books.toscrape.com",
        "https://books.toscrape.com/",
        "https://books.toscrape.com/index.html",
        "https://books.toscrape.com/INDEX.HTML",
    )}
    assert len(same) == 1, same

    # A file that merely ends in "index.html"-ish text is a different document,
    # and a query string makes it a different resource.
    assert key_of("https://x.test/notindex.html") != key_of("https://x.test/")
    assert key_of("https://x.test/a/index.html?page=2") != key_of("https://x.test/a/")
