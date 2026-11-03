"""An earlier content of a position is kept, not overwritten (G-253).

The reader (PLUGIN_GOAL 128): "object permanence on chunk streaming and
latency both; store". A chunk's id is its position, so a feed rewriting an
element in place overwrote the stored content while the view kept it -- on
bandcamp 95 of 170 grey nodes were such earlier contents, never placeable.
A VERSION keeps it, keyed by position AND content, under the page's marked
url so no positional read of the page sees it. Planted `PLANT_NO_VERSIONS`:
the overwrite, as before.
"""

from domvec import graphstore
from domvec.address import ContentAddress
from domvec.graphstore import GraphStore, VERSION_SUFFIX, page_of
from domvec.invariants import g1_every_chunk_belongs_to_a_page
from domvec.markdown import MarkdownChunk, MarkdownLine

A = "https://example.org/feed"


def _page(url, texts):
    chunks, addrs = [], []
    for i, text in enumerate(texts):
        xp = "/html/body/div[%d]" % (i + 1)
        a = ContentAddress(url=url, xpath=xp + "/text()[1]", tag="text.p", accessor="text")
        chunks.append(MarkdownChunk(url=url, xpath=xp, lines=[MarkdownLine(depth=0, text=text, address=a)]))
        addrs.append((a, text, text))
    return chunks, addrs


def _write(store, texts, complete=True):
    chunks, addrs = _page(A, texts)
    counts = store.ingest(A, addrs, chunks, complete=complete)
    return [c.cid for c in chunks], counts


def _versions(store):
    return {cid: (md, of, url, dup or "") for cid, md, of, url, dup in store._rows(
        "MATCH (v:Chunk)-[:VersionOf]->(c:Chunk) RETURN v.cid, v.md, c.cid, v.url, v.dup_of")}


def test_an_in_place_rewrite_keeps_the_earlier_content(tmp_path):
    store = GraphStore(tmp_path / "s.kuzu")
    (slot, other), _ = _write(store, ["Album one by Artist", "Static footer"])
    (slot2, _o), counts = _write(store, ["Album two by Someone", "Static footer"], complete=False)
    assert slot2 == slot                                         # same position, same id
    v = _versions(store)
    assert counts["versions_written"] == 1 and list(counts["version_of"].values()) == [slot]
    (vid, (md, of, url, dup)), = v.items()
    assert md.strip().endswith("Album one by Artist") and of == slot and dup == ""
    assert url == A + VERSION_SUFFIX and page_of(url) == A
    # The current chunk holds the new content; the version draws no element.
    assert "Album two" in store._rows("MATCH (c:Chunk {cid: $c}) RETURN c.md", {"c": slot})[0][0]
    assert store._rows("MATCH (c:Chunk {cid: $c})-[:Anchors]->() RETURN count(*)", {"c": vid})[0][0] == 0
    # No positional read of the page sees it -- and a COMPLETE rewrite of the
    # page (reconcile drops what the page lacks) leaves it.
    assert store.chunk_count(A) == 2
    _write(store, ["Album two by Someone", "Static footer"])
    assert vid in _versions(store)
    assert g1_every_chunk_belongs_to_a_page(store) == []


def test_planted_overwrite_keeps_nothing(tmp_path):
    graphstore.PLANT_NO_VERSIONS[0] = True
    try:
        store = GraphStore(tmp_path / "p.kuzu")
        _write(store, ["Album one by Artist"])
        _write(store, ["Album two by Someone"], complete=False)
        assert _versions(store) == {}
    finally:
        graphstore.PLANT_NO_VERSIONS[0] = False


def test_an_unchanged_write_reads_no_bodies_and_writes_none(tmp_path):
    store = GraphStore(tmp_path / "u.kuzu")
    _write(store, ["Album one by Artist", "Static footer"])
    _cids, counts = _write(store, ["Album one by Artist", "Static footer"], complete=False)
    assert "versions_written" not in counts and _versions(store) == {}


def test_content_seen_again_is_the_same_version_and_the_current_chunk_leads(tmp_path):
    store = GraphStore(tmp_path / "d.kuzu")
    for text in ["Album one", "Album two", "Album one", "Album two", "Album one"]:
        (slot,), _ = _write(store, [text], complete=False)
    v = _versions(store)
    assert sorted(md.strip() for md, *_ in v.values()) == ["Album one", "Album two"]
    # "Album one" is current again: its version is the current chunk's copy,
    # never a second drawing of it.
    one = next(cid for cid, (md, *_r) in v.items() if md.strip() == "Album one")
    assert v[one][3] == slot
    assert store._rows("MATCH (c:Chunk {cid: $c}) RETURN c.dup_of", {"c": slot})[0][0] in ("", None)


def test_versions_per_position_are_capped_newest_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(graphstore, "VERSIONS_PER_POSITION", 3)
    store = GraphStore(tmp_path / "c.kuzu")
    for i in range(7):
        _write(store, ["Ticker reads %d" % i], complete=False)
    kept = sorted(md.strip() for md, *_ in _versions(store).values())
    assert kept == ["Ticker reads 3", "Ticker reads 4", "Ticker reads 5"]
    assert store.version_stats["capped"] == 3


def test_placement_reads_a_version_as_its_page_and_purge_takes_it(tmp_path):
    store = GraphStore(tmp_path / "x.kuzu")
    _write(store, ["Album one by Artist"])
    _write(store, ["Album two by Someone"], complete=False)
    vid, = _versions(store)
    (cid, chunk, _vec), = store.chunks_for_placement([vid])
    assert cid == vid and chunk.url == A
    store.purge_page(A)
    assert store._rows("MATCH (c:Chunk) RETURN count(c)")[0][0] == 0


def test_the_diffs_read_is_reused_and_the_vector_is_left_to_the_embedder(tmp_path):
    store = GraphStore(tmp_path / "e.kuzu")
    chunks, addrs = _page(A, ["Album one by Artist"])
    vec = [0.0] * graphstore.EMBED_DIM
    vec[3] = 1.0
    store.ingest(A, addrs, chunks, embeddings={chunks[0].cid: vec})
    new, addrs2 = _page(A, ["Album two by Someone"])
    # The caller's diff already holds what the store has: handed over, the
    # write keeps the version from it.
    counts = store.ingest(A, addrs2, new, complete=False, held_md={new[0].cid: chunks[0].markdown})
    vid, = counts["version_of"]
    # No vector written on the capture path (an embedding SET was 1.5 s of
    # it live): the whole markdown and the PAGE url go back for the embedder.
    assert store._rows("MATCH (c:Chunk {cid: $c}) RETURN c.embedding", {"c": vid})[0][0] is None
    md, url = counts["version_text"][vid]
    assert md == chunks[0].markdown and url == A
    assert {"ms_versions_merge", "ms_versions_link", "ms_versions_held"} <= set(counts)
