"""G-416 (PLUGIN_GOAL 193 d): hits name their interface; a second query
embedding ranks the interface types. Planted: no ranking."""
from types import SimpleNamespace

from domvec.obsidian import sidecar as S


class _Emb:
    """Bag of words: a type's description scores by the words it shares."""
    def _v(self, t):
        words = ["browser", "page", "python", "kernel", "markdown", "tool", "module"]
        return [float(w in t.lower()) for w in words]

    def embed_texts(self, ts):
        return [self._v(t) for t in ts]

    def embed_query(self, q):
        return self._v(q)


def test_interface_of_each_scheme():
    assert S._interface_of("https://x.org/a", "/html/body") == "web chunk"
    assert S._interface_of("vault://v/n.md", "/section[1]/code[1]") == "code cell"
    assert S._interface_of("vault://v/n.md", "/section[1]/p[1]") == "note"
    assert S._interface_of("tool://kernel/Search", "") == "app tool"


def test_second_embedding_follows_the_query():
    ws = SimpleNamespace(embedder=_Emb())
    assert S._rank_interfaces(ws, "a python kernel")[0]["interface"] == "code cell"
    assert S._rank_interfaces(ws, "the browser page")[0]["interface"] == "web chunk"
    S.PLANT_NO_INTERFACE_RANK[0] = True
    try:
        assert S._rank_interfaces(ws, "a python kernel") == []
    finally:
        S.PLANT_NO_INTERFACE_RANK[0] = False
