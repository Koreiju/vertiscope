"""The write does only what has changed, and still ends in the right state.

Re-indexing a page that has not moved was costing as much as indexing it for
the first time: 5,841 of 5,841 anchors and 11,474 of 11,474 addresses were
deleted and rewritten to the values they already held. The write diffs now --
and a diff that is wrong is far worse than one that is slow, because the
anchors pair a chunk's markdown lines to its addresses BY POSITION and one
wrong ordinal misattributes every line after it.

So these assert the STATE, not the saving. The saving is measured in §M.15.
"""

import pathlib
import shutil
import tempfile

import pytest

from domvec.workspace import Workspace

CORPUS = pathlib.Path(__file__).parent / "corpus"
URL = "https://fixture.test/page"


def _fixture() -> str:
    for name in ("discourse-julialang-org-latest.html",
                 "books-toscrape-com.html"):
        path = CORPUS / name
        if path.exists():
            return path.read_text(encoding="utf-8", errors="replace")
    candidates = sorted(CORPUS.glob("*.html"))
    if not candidates:
        pytest.skip("no corpus fixture")
    return candidates[0].read_text(encoding="utf-8", errors="replace")


def _anchors(store, url):
    """(cid, aid, ord) for every anchor on the page."""
    return {(cid, aid, int(o)) for cid, aid, o in store._rows(
        "MATCH (c:Chunk {url: $u})-[e:Anchors]->(a:Address) "
        "RETURN c.cid, a.aid, e.ord", {"u": url})}


@pytest.fixture()
def workspace():
    tmp = tempfile.mkdtemp()
    try:
        with Workspace(pathlib.Path(tmp) / "ws") as ws:
            yield ws
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_reindexing_an_unchanged_page_leaves_the_same_anchors(workspace):
    """The state after two writes is the state after one.

    This is the property the diff could break and nothing else would notice:
    skipping a delete or a create leaves the store holding an edge set that
    no longer describes the page, and every consumer pairs lines to addresses
    by position from it.
    """
    html = _fixture()
    workspace.index_html(html, URL)
    once = _anchors(workspace.store, URL)
    assert once, "the fixture produced no anchors at all"

    workspace.index_html(html, URL)
    twice = _anchors(workspace.store, URL)
    assert twice == once, (
        "%d anchors differ after re-indexing an unchanged page"
        % len(once ^ twice))


def test_no_anchor_is_duplicated(workspace):
    """`CREATE` is only safe while the diff is right.

    The write creates rather than merges, on the strength of the delete
    having removed what it is about to write. If the diff ever stops covering
    a case, this is where it shows -- as two edges from one chunk to one
    address, which misattributes every line after the first.
    """
    html = _fixture()
    for _ in range(3):
        workspace.index_html(html, URL)
    pairs = [(cid, aid) for cid, aid, _o in _anchors(workspace.store, URL)]
    assert len(pairs) == len(set(pairs)), "an anchor was created twice"


def test_the_second_write_is_measurably_smaller(workspace):
    """The non-vacuity arm: the diff has to actually skip something.

    Without this the tests above pass on a write that still rewrites
    everything, which is exactly the state this change set out to leave.
    """
    html = _fixture()
    seen = []
    original = type(workspace.store).ingest

    def watched(self, url, addresses, chunks, **kw):
        counts = original(self, url, addresses, chunks, **kw)
        seen.append(dict(counts))
        return counts

    type(workspace.store).ingest = watched
    try:
        workspace.index_html(html, URL)
        first = seen[-1]
        seen.clear()
        workspace.index_html(html, URL)
        second = seen[-1]
    finally:
        type(workspace.store).ingest = original

    assert first.get("anchors", 0) > 0, "the first write anchored nothing"
    assert second.get("anchors_incoming", 0) > 0, "nothing arrived the second time"
    assert second.get("anchors_unchanged", 0) == second["anchors_incoming"], \
        "an unchanged page reported changed anchors"
    assert second.get("anchors", 0) == 0, \
        "the second write still created %d anchors" % second.get("anchors", 0)
    assert second.get("addresses_unchanged", 0) == \
        second.get("addresses_incoming", 0), \
        "an unchanged page reported changed addresses"


def test_a_changed_page_still_rewrites_what_moved(workspace):
    """And the other non-vacuity arm: a diff that skipped everything would
    pass every test above and lose the edit."""
    html = _fixture()
    workspace.index_html(html, URL)
    before = _anchors(workspace.store, URL)

    changed = html.replace("</body>",
                           "<p>a sentence this page did not have</p></body>", 1)
    assert changed != html, "the fixture has no </body> to edit"
    workspace.index_html(changed, URL)
    after = _anchors(workspace.store, URL)
    assert after != before, "an edited page produced identical anchors"


SMALL = ("<html><body><main><h2>Orchids</h2><p>Orchid pollen is carried by bees in spring.</p>"
         "<p>Basalt cools into columns.</p></main></body></html>")


@pytest.mark.parametrize("planted", [False, True])
def test_a_moved_value_rewrites_only_the_value_columns(workspace, monkeypatch, planted):
    """2026-11-15, the native store crash: SET of every string column on an
    address whose content moved grew the store 0.5-1.7 GB per checkpoint
    (`domvec.analytics.store_crash`, capture arm); the value alone did not
    (capture_value). An edited paragraph keeps its key, so only `value`,
    `content_hash` (and `md` at md-level) are written -- and the row read
    back is complete. Planted `PLANT_ADDRESS_FULL_SET`: every column, as before.
    """
    import domvec.graphstore as G
    monkeypatch.setattr(G, "PLANT_ADDRESS_FULL_SET", [planted])
    url = "https://orchid.test/"
    workspace.index_html(SMALL, url)
    statements = []
    seen = []
    original_batch = type(workspace.store)._batch
    original_ingest = type(workspace.store).ingest

    def batch(self, query, rows, *a, **kw):
        statements.append((query, [r.get("aid") for r in rows if isinstance(r, dict)]))
        return original_batch(self, query, rows, *a, **kw)

    def ingest(self, u, addresses, chunks, **kw):
        counts = original_ingest(self, u, addresses, chunks, **kw)
        seen.append(dict(counts))
        return counts

    monkeypatch.setattr(type(workspace.store), "_batch", batch)
    monkeypatch.setattr(type(workspace.store), "ingest", ingest)
    workspace.index_html(SMALL.replace("in spring", "in early spring"), url)
    counts = seen[-1]
    full = [aids for q, aids in statements if "MERGE (a:Address" in q and "a.xpath = r.xp" in q]
    value = [aids for q, aids in statements if "MERGE (a:Address" in q and "a.xpath = r.xp" not in q
             and "a.value = r.val" in q]
    full_aids = {a for aids in full for a in aids}
    value_aids = {a for aids in value for a in aids}
    if planted:
        assert counts.get("addresses_value_only", 0) == 0 and not value_aids, (counts, statements)
    else:
        # The edited address keeps its aid and takes the value-only write. (One
        # other address at that xpath has a value-dependent aid, so an edit
        # removes it and writes a NEW one -- in full, as a new row must be.)
        assert counts.get("addresses_value_only", 0) >= 1 and value_aids, (counts, statements)
        assert not (value_aids & full_aids), (value_aids, full_aids)
    # Either way the row is whole: key columns intact, the new value in place.
    rows = workspace.store._rows(
        "MATCH (a:Address) WHERE a.url = $u AND a.value CONTAINS 'early spring' "
        "RETURN a.akey, a.xpath, a.tag, a.url", {"u": url})
    assert rows and all(r[0] and r[1] and r[3] == url for r in rows), rows
