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

from vertiscope.workspace import Workspace

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
