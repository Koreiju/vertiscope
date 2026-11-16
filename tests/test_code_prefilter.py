"""R-6: package retrieval applies a vector-centroid pre-filter, then ranks
within the kept partitions -- inside the ONE search, not beside it.

Five code partitions (four packages and the repo), each about one topic, and a
web page. A query near one topic keeps the nearest partitions' code and masks
the rest; the web page is never masked. Planted (`code_partitions = 0`): no
pre-filter, every partition's code ranked.
"""

import numpy as np
import pytest

from domvec.search import SearchDiagnostics
from domvec.workspace import Workspace

TOPICS = ["astronomy", "cooking", "guitar", "finance", "weather", "gardening"]


class _TopicEmbedder:
    """One dimension per topic word: a text points along the topics it names."""
    dim = 768

    def embed_texts(self, texts, **_kw):
        out = np.full((len(texts), self.dim), 1e-3, dtype=np.float32)
        for i, t in enumerate(texts):
            low = (t or "").lower()
            for d, w in enumerate(TOPICS):
                if w in low:
                    out[i, d] = 1.0
        return out

    def embed_query(self, query):
        return self.embed_texts([query])[0]


def _module(topic, n):
    return ('"""The %s module %d: everything about %s, %s and more %s."""\n\n'
            'def run():\n    """Do the %s thing."""\n    return %d\n') % (topic, n, topic, topic, topic, topic, n)


@pytest.fixture()
def ws(tmp_path):
    with Workspace(tmp_path / "ws", embedder=_TopicEmbedder()) as got:
        for i, (root, topic) in enumerate([("pypi/stars", "astronomy"), ("pypi/kitchen", "cooking"),
                                           ("pypi/strings", "guitar"), ("pypi/money", "finance"),
                                           ("repo", "weather")]):
            for n in range(3):
                got.index_source(_module(topic, n), "pkg/m%d.py" % n, root=root)
        got.index_html("<html><body><p>A web page about guitar and gardening.</p></body></html>",
                       "https://example.org/web")
        got.flush_vectors() if hasattr(got, "flush_vectors") else None
        yield got


def _roots(hits):
    return {h.url.split("/pkg/")[0] for h in hits if h.url.startswith("code://")}


def test_the_query_ranks_code_only_within_its_nearest_partitions(ws):
    diag = SearchDiagnostics()
    ws.index.code_partitions = 1
    hits = ws.search("guitar", k=50, diagnostics=diag)
    assert diag.code_partitions and diag.code_partitions["total"] == 5
    assert diag.code_partitions["kept_names"] == ["code://pypi/strings"]
    assert _roots(hits) <= {"code://pypi/strings"}
    assert diag.code_partitions["rows_masked"] > 0


def test_web_rows_are_never_masked(ws):
    ws.index.code_partitions = 1
    hits = ws.search("gardening guitar", k=50)
    assert any(h.url == "https://example.org/web" for h in hits)


def test_planted_no_prefilter_ranks_every_partition(ws):
    ws.index.code_partitions = 0          # planted
    diag = SearchDiagnostics()
    hits = ws.search("guitar astronomy cooking finance weather", k=50, diagnostics=diag)
    assert diag.code_partitions is None
    assert len(_roots(hits)) >= 3


@pytest.mark.parametrize("planted", [False, True])
def test_the_root_holding_the_word_is_kept(ws, planted, monkeypatch):
    """Live 2026-11-15: an identifier's own file was masked because its
    root's centroid was not among the 3 nearest. A word only one root holds
    keeps that root; planted `PLANT_PREFILTER_IGNORES_LEXICAL`: masked."""
    ws.index_source('"""Cooking module."""\n\ndef zanthoxylum():\n    """zanthoxylum peppercorn."""\n', "pkg/zx.py",
                    root="pypi/kitchen")
    ws.flush_vectors()
    ws._index = None
    monkeypatch.setattr(type(ws.index), "PLANT_PREFILTER_IGNORES_LEXICAL", [planted])
    ws.index.code_partitions = 1
    diag = SearchDiagnostics()
    hits = ws.search("guitar zanthoxylum", k=50, diagnostics=diag)
    kitchen = [h for h in hits if h.url.startswith("code://pypi/kitchen/")]
    if planted:
        assert not kitchen and diag.code_partitions["kept_names"] == ["code://pypi/strings"], diag.code_partitions
    else:
        assert any(h.url.endswith("/zx.py") for h in kitchen), (diag.code_partitions, [h.url for h in hits])
        assert diag.code_partitions["kept_by_word"] == "code://pypi/kitchen"
