"""A page's kept versions can be removed and the page left (G-253, G-370).

2026-11-15: the search slate (`ego.md`) is rewritten by every search; each
rewrite kept its earlier text as a version (`#~v`). Written under the slate's
old one-chunk addressing, 31 of the top 40 live hits for `unionRect` were
the slate's own old queries. `Workspace.purge_versions` removes them from
every place they are recorded -- frequency rows, semantic rows, queue,
index, graph -- and leaves the page's current chunks.

Planted `PLANT_PURGE_VERSIONS_GRAPH_ONLY`: the graph rows go and the
frequency and semantic rows stay -- residue the route hides (it drops a hit
whose chunk is gone) but the index still scores and the vocabulary keeps.
"""
import pytest

from domvec import vault as V
from domvec.graphstore import VERSION_SUFFIX
from domvec.obsidian.sidecar import search_payload
from domvec.workspace import Workspace

from test_obsidian_layout import _StubEmbedder

SLATE = "---\ndomvec: slate\n---\nego\n\tsearch\n\t\tquery\t%s\n\t\tk\t8\n"


def _versions(w, url):
    return w.store.version_cids(url)


@pytest.mark.parametrize("planted", [False, True])
def test_old_slate_versions_are_purged_and_the_slate_stays(tmp_path, monkeypatch, planted):
    monkeypatch.setattr(V, "PLANT_SLATE_AS_PARAGRAPH", [True])        # the addressing they were written under
    monkeypatch.setattr(Workspace, "PLANT_PURGE_VERSIONS_GRAPH_ONLY", [planted])
    with Workspace(tmp_path / "ws", embedder=_StubEmbedder()) as w:
        w.index_html("<html><body><main><p>quasicrystal tilings of the plane</p></main></body></html>",
                     "https://tiles.test/")
        w.index_note(SLATE % "orchid pollen bees", "domvec/ego.md")
        w.index_note(SLATE % "basalt columns cooling", "domvec/ego.md")
        url = w.page_url("vault://vault/domvec/ego.md")
        # As the sidecar does (G-253): the kept versions go to the vector
        # queue, and the lexical backfill gives every stored chunk without a
        # row one -- which is how a version comes to be searchable at all.
        for vid in _versions(w, url):
            md = w.store._rows("MATCH (c:Chunk {cid: $c}) RETURN c.md", {"c": vid})[0][0]
            w.vectors.push(vid, md, url=url + VERSION_SUFFIX)
        w.flush_vectors()
        w.rebuild_lexical()
        w._index = None
        assert len(_versions(w, url)) >= 1
        before = [h["url"] for h in search_payload(w, "orchid pollen bees", 5, where="all")["hits"]]
        raw = [(h.url, round(h.lexical, 3)) for h in w.search("orchid pollen bees", k=5)]
        rows = {v: (v in set(w.freq.rows)) for v in _versions(w, url)}
        assert url + VERSION_SUFFIX in before, (before, raw, rows)
        current = w.store.chunk_count(url)

        vids = _versions(w, url)
        got = w.purge_versions(url)
        residue = {v for v in vids if w.freq.row_of(v) is not None
                   or (w.embeddings is not None and w.embeddings.row_of(v) is not None)}
        w._index = None                               # the next search reads the index as it now stands
        after = [h["url"] for h in search_payload(w, "orchid pollen bees", 5, where="all")["hits"]]
        assert got["versions_removed"] >= 1 and _versions(w, url) == []
        assert w.store.chunk_count(url) == current    # the page itself is untouched
        # The route never returns a chunk the store no longer holds, so the
        # reader sees no version in either arm. What the purge adds is that
        # nothing of them is LEFT: no frequency row, no semantic row.
        assert not any(u.endswith(VERSION_SUFFIX) for u in after), after
        if planted:
            assert residue, "the graph-only purge left no rows behind"
        else:
            assert not residue, residue
