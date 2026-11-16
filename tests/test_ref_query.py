"""G-372 step 2: a search keyed by a chunk (`ref=<cid>`) -- "similar".

`docs/SEARCH_GRAPH_DESIGN.md` §4: the search node takes a cid as its query.
Lexical reads that chunk's stored frequency row, semantic its stored
embedding -- no tokenizing, no encoder call -- and everything after is the
same three-factor fuse (item 164: "All three factors").

Trie framing: read only. The ref is a trie address and every hit is one.

Planted `PLANT_REF_REENCODES`: the ref's terms go back through the encoder,
so the call count this search reports must be non-zero.
"""
import pytest

import domvec.search as S
from domvec.search import SearchDiagnostics
from domvec.workspace import Workspace

from test_content_share import _WordsEmbedder

PAGES = {
    "https://a.test/orchids": "Orchids need bright indirect light and orchid bark that drains fast.",
    "https://b.test/orchid-care": "Water an orchid weekly; orchid roots rot in wet bark and low light.",
    "https://c.test/engines": "A diesel engine compresses air until the fuel ignites without a spark.",
    "https://d.test/turbines": "Gas turbines compress air, burn fuel and spin a shaft; no spark plugs.",
}


class _Counting(_WordsEmbedder):
    def __init__(self):
        self.calls = 0

    def embed_query(self, query):
        self.calls += 1
        return super().embed_query(query)


@pytest.fixture()
def ws(tmp_path):
    emb = _Counting()
    with Workspace(tmp_path / "ws", embedder=emb) as w:
        for url, text in PAGES.items():
            w.index_html("<html><body><main><p>%s</p></main></body></html>" % text, url)
        w.flush_vectors()
        yield w, emb


def _cid_of(w, url):
    hits = [h for h in w.search(url.rsplit("/", 1)[1].split("-")[0], k=10) if h.url == url]
    assert hits, url
    return hits[0].cid


@pytest.mark.parametrize("planted", [False, True])
def test_a_ref_query_reads_stored_rows_and_calls_no_encoder(ws, monkeypatch, planted):
    w, emb = ws
    ref = _cid_of(w, "https://a.test/orchids")
    monkeypatch.setattr(S, "PLANT_REF_REENCODES", [planted])
    w.index._factor_memo = None
    before = emb.calls
    diag = SearchDiagnostics()
    hits = w.search("", k=4, ref=ref, diagnostics=diag)
    urls = [h.url for h in hits]
    assert diag.ref == ref
    assert diag.semantic_available
    if planted:
        assert diag.encoder_calls > 0 and emb.calls > before, (diag.encoder_calls, emb.calls)
    else:
        assert diag.encoder_calls == 0 and emb.calls == before, (diag.encoder_calls, emb.calls)
    # The ref first, its neighbour in meaning and words next; the engines last
    # or not at all (the lexical gate).
    assert hits[0].cid == ref, urls
    assert urls[1] == "https://b.test/orchid-care", urls
    assert "https://c.test/engines" not in urls[:2]


def test_similar_from_the_other_topic_finds_its_own_neighbour(ws):
    w, _ = ws
    ref = _cid_of(w, "https://d.test/turbines")
    urls = [h.url for h in w.search("", k=4, ref=ref)]
    assert urls[:2] == ["https://d.test/turbines", "https://c.test/engines"], urls


def test_an_unknown_ref_returns_nothing(ws):
    w, _ = ws
    diag = SearchDiagnostics()
    assert w.search("", k=4, ref="no-such-cid", diagnostics=diag) == []
    assert diag.encoder_calls == 0


def test_the_memo_does_not_serve_one_ref_for_another(ws):
    """The factor memo is keyed on the query; two refs with the same empty
    query string must not share it (CLAUDE.md 5c)."""
    w, _ = ws
    a = _cid_of(w, "https://a.test/orchids")
    d = _cid_of(w, "https://d.test/turbines")
    assert w.search("", k=1, ref=a)[0].cid == a
    assert w.search("", k=1, ref=d)[0].cid == d
