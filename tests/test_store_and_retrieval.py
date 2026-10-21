"""Store persistence and ranked retrieval."""

from vertiscope.ingest import ingest
from vertiscope.pipeline import run_pipeline
from vertiscope.retrieve import Retriever
from vertiscope.store import Store

URL = "https://riverside.example/catalog"


def _ingest(store, html, url=URL):
    return ingest(store, run_pipeline(html, url))


def test_cold_start_on_empty_index(store):
    """A fresh install has no vocab.json; reading stats must not explode.

    Regression: Store.tfidf used to call load() on top of the constructor's
    own load, bypassing its FileNotFoundError guard.
    """
    stats = store.stats()
    assert stats["indexed_rows"] == 0
    assert stats["pages"] == 0
    assert store.search("anything") == []


def test_ingest_writes_records_and_index(store, catalog_html):
    report = _ingest(store, catalog_html)
    assert report.instances_written > 0
    assert report.rows_indexed > 0
    stats = store.stats()
    assert stats["pages"] == 1
    assert stats["instances"] == report.instances_written
    assert stats["indexed_rows"] == report.rows_indexed
    assert stats["vocab_size"] > 0


def test_ingest_is_idempotent(store, catalog_html):
    first = _ingest(store, catalog_html)
    before = store.stats()["instances"]
    second = _ingest(store, catalog_html)
    after = store.stats()["instances"]
    assert after == before, "re-scraping the same page duplicated rows"
    assert second.instances_written == first.instances_written


def test_retrieval_ranks_the_right_card_first(store, catalog_html):
    _ingest(store, catalog_html)
    hits = Retriever(store).search("echelle spectrograph resolving power", k=5)
    assert hits, "no hits for a query with exact term matches"
    assert "echelle" in hits[0].text.lower()
    assert hits[0].rank == 1
    assert hits[0].score > 0
    # ranks must be dense and ordered
    assert [h.rank for h in hits] == list(range(1, len(hits) + 1))
    assert all(
        a.score >= b.score for a, b in zip(hits, hits[1:])
    ), "hits are not sorted by score"


def test_retrieval_hydrates_full_records(store, catalog_html):
    _ingest(store, catalog_html)
    hit = Retriever(store).search("polarimeter", k=1)[0]
    assert hit.record is not None
    assert hit.record.html_raw, "html_raw not persisted"
    assert hit.record.url == URL
    assert store.get_instance(hit.instance_id) is not None


def test_url_filter(store, catalog_html):
    _ingest(store, catalog_html, url=URL)
    _ingest(store, catalog_html.replace("Echelle", "Grating"), url="https://other.example/x")
    both = Retriever(store).search("spectrograph", k=20)
    assert len({h.url for h in both}) == 2
    only = Retriever(store).search("spectrograph", k=20, urls=[URL])
    assert {h.url for h in only} == {URL}


def test_empty_query_returns_nothing(store, catalog_html):
    _ingest(store, catalog_html)
    assert Retriever(store).search("   ") == []


def test_purge_url_clears_both_stores(store, catalog_html):
    """claim: PROP-14.2

    PROP-14.2: multiset sum is cancellative, hence embeds in a group, hence a
    document-frequency aggregate admits *exact* removal. This asserts the
    consequence at the store level — after purging a URL the index returns
    nothing for terms only that URL carried, with no residue.
    """
    _ingest(store, catalog_html)
    assert store.stats()["instances"] > 0
    removed = store.purge_url(URL)
    assert removed > 0
    stats = store.stats()
    assert stats["instances"] == 0
    assert stats["pages"] == 0
    assert store.search("echelle") == [], "index still returns purged rows"


def test_purge_all(store, catalog_html):
    _ingest(store, catalog_html)
    store.purge_all()
    stats = store.stats()
    assert stats["instances"] == 0
    assert stats["indexed_rows"] == 0


def test_index_survives_reopen(cfg, catalog_html):
    with Store(cfg) as st:
        _ingest(st, catalog_html)
        expected = st.stats()["indexed_rows"]
    with Store(cfg) as st2:
        assert st2.stats()["indexed_rows"] == expected
        assert st2.search("echelle", k=1), "index did not survive reopen"
