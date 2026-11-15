"""One content, one drawn chunk, store-wide (2026-10-29).

The reader, on reopening the app: "I immediately see duplicate node chunks.
perhaps make something that fixes duplication everywhere at the db level."
`G-24` resolved byte-identical chunks within a page only; the same content on
two pages was drawn twice. Now the store keys every chunk by its markdown and
marks all but one LEAD per content (`dup_of`), on any page -- marked, not
merged: each chunk keeps its own anchors and addresses. Planted
`PLANT_PAGE_SCOPED_DEDUP`: the old, page-scoped verdict.
"""

from domvec import graphstore
from domvec.address import ContentAddress
from domvec.graphstore import GraphStore
from domvec.markdown import MarkdownChunk, MarkdownLine

A = "https://example.org/a"
B = "https://example.org/a?probe=1"
C = "https://example.net/other"


def _page(url, texts):
    chunks, addrs = [], []
    for i, text in enumerate(texts):
        xp = "/html/body/div[%d]" % (i + 1)
        a = ContentAddress(url=url, xpath=xp + "/text()[1]", tag="text.p", accessor="text")
        chunks.append(MarkdownChunk(url=url, xpath=xp, lines=[MarkdownLine(depth=0, text=text, address=a)]))
        addrs.append((a, text, ""))
    return chunks, addrs


def _write(store, url, texts):
    chunks, addrs = _page(url, texts)
    store.ingest(url, addrs, chunks)
    return {c.markdown: c.cid for c in chunks}


def _verdict(store):
    return {cid: (url, dup or "") for cid, url, dup in store._rows(
        "MATCH (c:Chunk) RETURN c.cid, c.url, c.dup_of")}


def _drawn(store):
    return sorted(cid for cid, (_u, dup) in _verdict(store).items() if not dup)


def test_the_same_content_on_two_pages_is_drawn_once(tmp_path):
    store = GraphStore(tmp_path / "s.kuzu")
    a = _write(store, A, ["A shared paragraph about tries", "Only on A"])
    b = _write(store, B, ["A shared paragraph about tries", "Only on B"])
    v = _verdict(store)
    shared_a, shared_b = a["A shared paragraph about tries"], b["A shared paragraph about tries"]
    assert v[shared_a][1] == "" and v[shared_b][1] == shared_a     # B's copy points at A's
    assert len(_drawn(store)) == 3
    assert store.duplicate_report()["extra_drawn"] == 0
    # Each chunk keeps its own node and its own anchor.
    assert store._rows("MATCH (c:Chunk {cid: $c})-[:Anchors]->(:Address) RETURN count(*)", {"c": shared_b})[0][0] == 1


def test_planted_page_scope_draws_it_twice(tmp_path):
    graphstore.PLANT_PAGE_SCOPED_DEDUP[0] = True
    try:
        store = GraphStore(tmp_path / "p.kuzu")
        _write(store, A, ["A shared paragraph about tries", "Only on A"])
        _write(store, B, ["A shared paragraph about tries", "Only on B"])
        assert len(_drawn(store)) == 4
        assert store.duplicate_report()["extra_drawn"] == 1
    finally:
        graphstore.PLANT_PAGE_SCOPED_DEDUP[0] = False


def test_the_lead_is_stable_and_a_copy_takes_over_when_it_goes(tmp_path):
    store = GraphStore(tmp_path / "s.kuzu")
    a = _write(store, A, ["Furniture", "Only on A"])
    b = _write(store, B, ["Furniture", "Only on B"])
    c = _write(store, C, ["Furniture", "Only on C"])
    lead = a["Furniture"]
    assert _verdict(store)[c["Furniture"]][1] == lead              # not re-elected by later writes
    store.dedup_changed.clear()
    store.purge_page(A)                                             # the lead's page goes
    v = _verdict(store)
    assert v[b["Furniture"]][1] == "" and v[c["Furniture"]][1] == b["Furniture"]
    assert b["Furniture"] in store.dedup_changed                   # the projector is told
    assert store.duplicate_report()["extra_drawn"] == 0


def test_a_lead_rewritten_hands_its_old_content_on(tmp_path):
    store = GraphStore(tmp_path / "s.kuzu")
    a = _write(store, A, ["Furniture", "Only on A"])
    b = _write(store, B, ["Furniture", "Only on B"])
    # A's first chunk now says something else (same address, new text).
    _write(store, A, ["Rewritten", "Only on A"])
    v = _verdict(store)
    assert v[b["Furniture"]][1] == "", "the copy must take the content over"
    assert store.duplicate_report()["extra_drawn"] == 0


def test_dedupe_store_backfills_and_is_idempotent(tmp_path):
    graphstore.PLANT_PAGE_SCOPED_DEDUP[0] = True       # a store written the old way
    try:
        store = GraphStore(tmp_path / "s.kuzu")
        _write(store, A, ["Furniture", "Shared twice", "Only on A"])
        _write(store, B, ["Furniture", "Shared twice", "Only on B"])
        store._execute("MATCH (c:Chunk) SET c.mdkey = ''")          # as before the column
    finally:
        graphstore.PLANT_PAGE_SCOPED_DEDUP[0] = False
    store._cindex = None
    first = store.dedupe_store()
    assert first["keyed"] == 6 and first["copies"] == 2 and first["flipped"] == 2
    assert store.duplicate_report()["extra_drawn"] == 0
    again = store.dedupe_store()
    assert again["keyed"] == 0 and again["rewritten"] == 0


def test_a_grouped_chunk_is_never_made_a_copy(tmp_path):
    store = GraphStore(tmp_path / "s.kuzu")
    a = _write(store, A, ["Furniture", "Only on A"])
    b = _write(store, B, ["Furniture", "Only on B"])
    store.set_groups(B, [[b["Furniture"], b["Only on B"]]])         # B's copy leads a group
    store._cindex = None
    store.dedupe_store()
    v = _verdict(store)
    assert v[b["Furniture"]][1] == "", "a group lead must stay drawn; its members speak through it"
    assert v[a["Furniture"]][1] == b["Furniture"], "and the plain chunk becomes its copy"


def test_joining_a_group_makes_the_member_lead_its_content(tmp_path):
    """A grouped chunk draws anyway, so it leads; the plain chunk that led
    before becomes its copy instead of a second drawing beside it."""
    store = GraphStore(tmp_path / "s.kuzu")
    a = _write(store, A, ["Furniture", "Only on A"])
    b = _write(store, B, ["Furniture", "Only on B"])
    assert _verdict(store)[b["Furniture"]][1] == a["Furniture"]
    store.set_groups(B, [[b["Furniture"], b["Only on B"]]])
    v = _verdict(store)
    assert v[b["Furniture"]][1] == "" and v[a["Furniture"]][1] == b["Furniture"]
    assert store.duplicate_report()["extra_drawn_plain"] == 0


def test_s4_a_one_chunk_delta_hashes_one_chunk_whatever_the_page(tmp_path):
    """`S-4`: deduplication inside the O(delta) budget. A page of N chunks,
    then a delta that rewrites ONE of them: the delta's dedup hashes 1, at
    N = 300 and N = 1,500 alike (and the 125-copies case keeps its verdict).
    Planted `PLANT_DEDUP_WHOLE_PAGE`: it re-hashes the whole page, N."""
    import time
    out = {}
    for n in (300, 1500):
        store = GraphStore(tmp_path / ("s%d.kuzu" % n))
        try:
            texts = ["chunk %d of the page" % i for i in range(n)] + ["Press Down Arrow"] * 125
            _write(store, A, texts)
            chunks, addrs = _page(A, texts)
            one = [c for c in chunks if c.markdown == "chunk 7 of the page"]
            for planted in (False, True):
                graphstore.PLANT_DEDUP_WHOLE_PAGE[0] = planted
                try:
                    h0 = store.dedup_stats.get("hashed", 0)
                    t0 = time.perf_counter()
                    store._assign_content(one)
                    out[(n, planted)] = (store.dedup_stats["hashed"] - h0, time.perf_counter() - t0)
                finally:
                    graphstore.PLANT_DEDUP_WHOLE_PAGE[0] = False
            leads = [cid for cid, (_u, dup) in _verdict(store).items() if not dup]
            assert len(leads) == n + 1          # 125 copies of one string: ONE lead
        finally:
            store.close()
    assert out[(300, False)][0] == 1 and out[(1500, False)][0] == 1
    assert out[(300, True)][0] == 300 + 125 + 1 and out[(1500, True)][0] == 1500 + 125 + 1


# --- a purged page's chunks leave the content index ---------------------------
#
# 2026-11-15, G-113's foreign-lead arm: a fixture page B, purged after each
# run, came back on the next run's B as the LEAD its copy was aliased to --
# a chunk the store no longer held, so the copy could never be drawn and the
# hover had no page to check the lead against.

D = "https://example.org/d"
E = "https://example.org/e"


def _held(store):
    return {cid for (cid,) in store._rows("MATCH (c:Chunk) RETURN c.cid")}


def test_no_copy_points_at_a_purged_chunk_after_both_pages_go_and_come_back(tmp_path):
    store = GraphStore(tmp_path / "s.kuzu")
    _write(store, D, ["The keeper's ledger, shared", "Only on D"])
    _write(store, E, ["The keeper's ledger, shared", "Only on E"])
    store.purge_page(D)
    store.purge_page(E)
    d2 = _write(store, D + "?2", ["The keeper's ledger, shared", "Only on D"])
    e2 = _write(store, E + "?2", ["The keeper's ledger, shared", "Only on E"])
    v, held = _verdict(store), _held(store)
    dangling = {cid: dup for cid, (_u, dup) in v.items() if dup and dup not in held}
    assert not dangling, "copies aliased to chunks the store no longer holds: %r" % dangling
    assert v[e2["The keeper's ledger, shared"]][1] == d2["The keeper's ledger, shared"]


def test_no_copy_points_at_a_purged_chunk_when_the_copy_page_goes_first(tmp_path):
    store = GraphStore(tmp_path / "s.kuzu")
    _write(store, D, ["The keeper's ledger, shared", "Only on D"])
    _write(store, E, ["The keeper's ledger, shared", "Only on E"])
    store.purge_page(E)                      # the COPY's page first
    e2 = _write(store, E + "?2", ["The keeper's ledger, shared", "Only on E"])
    v, held = _verdict(store), _held(store)
    dangling = {cid: dup for cid, (_u, dup) in v.items() if dup and dup not in held}
    assert not dangling, dangling
