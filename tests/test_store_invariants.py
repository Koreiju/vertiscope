"""Representation invariants for the address-trie stores, and their adequacy.

Two halves, in one file because they are only meaningful together:

* the clauses **hold** on a real workspace;
* each clause **can fail** — a mutation that breaks it is reported, and the
  clauses that fire are exactly the ones whose state was touched.

The second half is the one that carries weight. Eleven clauses reporting "ok"
says nothing until something has shown they are capable of saying otherwise;
this is the same argument `test_invariant_adequacy.py` makes for the older
store's five clauses, applied to the newer ones.
"""

import json
import pathlib

import pytest

from vertiscope import invariants as inv
from vertiscope.workspace import Workspace

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
        url, html = _html()
        workspace.index_html(html, url)
        yield workspace


def _fired(report):
    return {name for name, violations in report.items() if violations}


# --- the invariant holds -----------------------------------------------------


def test_every_clause_holds_after_an_ingest(ws):
    report = inv.check_workspace(ws)
    assert _fired(report) == set(), report


def test_every_clause_holds_after_two_pages(tmp_path):
    with Workspace(tmp_path / "ws") as workspace:
        for prefix in ("books-toscrape", "quotes-toscrape"):
            url, html = _html(prefix)
            workspace.index_html(html, url)
        assert _fired(inv.check_workspace(workspace)) == set()


def test_every_clause_holds_after_reopening(tmp_path):
    url, html = _html()
    with Workspace(tmp_path / "ws") as workspace:
        workspace.index_html(html, url)
    with Workspace(tmp_path / "ws") as workspace:
        assert _fired(inv.check_workspace(workspace)) == set()


def test_every_clause_holds_after_a_purge(ws):
    url = ws.pages()[0]
    ws.purge(url)
    assert _fired(inv.check_workspace(ws)) == set()


# --- the frequency matrix's clauses can fail --------------------------------


def test_f1_fires_when_the_row_index_disagrees(ws):
    ws.freq._row_of[ws.freq.rows[0]] = 999
    assert _fired(inv.check_freq(ws.freq)) == {"F-1"}


def test_f1_fires_on_a_repeated_identifier(ws):
    ws.freq.rows[1] = ws.freq.rows[0]
    assert "F-1" in _fired(inv.check_freq(ws.freq))


def test_f2_fires_when_a_row_loses_its_counts(ws):
    ws.freq._counts.pop()
    assert _fired(inv.check_freq(ws.freq)) == {"F-2"}


def test_f3_fires_on_a_gap_in_the_vocabulary(ws):
    """A gap leaves a column idf still divides by."""
    term = next(iter(ws.freq.vocab))
    ws.freq.vocab[term] = len(ws.freq.vocab) + 50
    assert "F-3" in _fired(inv.check_freq(ws.freq))


def test_f3_fires_when_two_terms_share_a_column(ws):
    terms = list(ws.freq.vocab)
    ws.freq.vocab[terms[1]] = ws.freq.vocab[terms[0]]
    assert "F-3" in _fired(inv.check_freq(ws.freq))


def test_f4_fires_on_a_column_outside_the_vocabulary(ws):
    ws.freq._counts[0][10 ** 6] = 1
    assert "F-4" in _fired(inv.check_freq(ws.freq))


def test_f5_fires_on_stale_document_frequency(ws):
    """df is derived; a stale cache silently rescales every idf."""
    df = ws.freq.document_frequency()
    df[0] = df[0] + 17
    assert _fired(inv.check_freq(ws.freq)) == {"F-5"}


def test_f5_is_silent_when_nothing_is_cached(ws):
    ws.freq._df = None
    assert "F-5" not in _fired(inv.check_freq(ws.freq))


# --- the graph's clauses can fail -------------------------------------------


def test_g1_fires_on_an_orphaned_chunk(ws):
    ws.store.conn.execute(
        "MERGE (c:Chunk {cid: 'orphan'}) SET c.url = 'x', c.xpath = '/', "
        "c.part = 0, c.md = '', c.chars = 0, c.line_count = 0, c.row = -1")
    assert "G-1" in _fired(inv.check_graph(ws.store))


def test_g3_fires_when_two_chunks_claim_a_row(ws):
    """The row is the join key across all three vector factors."""
    cids = [c.cid for c in ws.store.chunks()][:2]
    ws.store.conn.execute(
        "MATCH (c:Chunk {cid: $cid}) SET c.row = 0", {"cid": cids[0]})
    ws.store.conn.execute(
        "MATCH (c:Chunk {cid: $cid}) SET c.row = 0", {"cid": cids[1]})
    assert "G-3" in _fired(inv.check_graph(ws.store))


def test_g4_fires_when_an_address_contradicts_its_key(ws):
    aid = ws.store._rows("MATCH (a:Address) RETURN a.aid LIMIT 1")[0][0]
    ws.store.conn.execute(
        "MATCH (a:Address {aid: $aid}) SET a.xpath = '/html/elsewhere'",
        {"aid": aid})
    assert "G-4" in _fired(inv.check_graph(ws.store))


def test_g4_fires_when_the_identifier_is_not_the_digest(ws):
    aid = ws.store._rows("MATCH (a:Address) RETURN a.aid LIMIT 1")[0][0]
    ws.store.conn.execute(
        "MATCH (a:Address {aid: $aid}) SET a.akey = $key",
        {"aid": aid, "key": "https://other.test|/html/a|urls.external|href"})
    assert "G-4" in _fired(inv.check_graph(ws.store))


# --- the coupling can fail ---------------------------------------------------


def test_w1_fires_when_the_matrix_loses_a_chunk(ws):
    """A chunk with no row is unrankable, and nothing else notices."""
    victim = ws.freq.rows[0]
    del ws.freq._row_of[victim]
    ws.freq.rows[0] = "ghost"
    fired = _fired(inv.check_workspace(ws))
    assert "W-1" in fired


def test_w2_fires_when_the_stored_row_drifts(ws):
    cid = ws.store.chunks()[0].cid
    ws.store.conn.execute(
        "MATCH (c:Chunk {cid: $cid}) SET c.row = 4242", {"cid": cid})
    assert "W-2" in _fired(inv.check_workspace(ws))


def test_a_workspace_mutation_fires_only_the_clauses_that_read_it(ws):
    """Requiring the *exact* set catches a clause that fires on everything.

    A predicate that reports a violation for any perturbation is as useless as
    one that never reports, and both look identical from a green suite.
    """
    cid = ws.store.chunks()[0].cid
    ws.store.conn.execute(
        "MATCH (c:Chunk {cid: $cid}) SET c.row = 4242", {"cid": cid})
    assert _fired(inv.check_workspace(ws)) == {"W-2"}, (
        "a stored-row drift should implicate the coupling and nothing else"
    )


# --- what the coupling invariant found ---------------------------------------


def test_purging_retires_the_frequency_rows(ws):
    """The bug W-1 caught on its first run.

    `purge` dropped a page's chunks from the graph and left its rows in the
    frequency matrix, so `idf` went on counting documents that no longer
    existed — every score shifted slightly and nothing failed.
    """
    url = ws.pages()[0]
    before = ws.freq.live_rows
    assert before > 0

    ws.purge(url)
    assert ws.freq.live_rows == 0, "rows outlived the chunks they describe"
    assert _fired(inv.check_workspace(ws)) == set()


def test_document_frequency_forgets_a_purged_page(tmp_path):
    """The consequence, stated as a number rather than as a shape."""
    with Workspace(tmp_path / "ws") as workspace:
        url1, html1 = _html("books-toscrape")
        url2, html2 = _html("quotes-toscrape")
        workspace.index_html(html1, url1)
        workspace.index_html(html2, url2)

        term = next(t for t, _c in workspace.freq.vocab.items() if t == "the")
        column = workspace.freq.vocab[term]
        before = float(workspace.freq.document_frequency()[column])

        workspace.purge(url1)
        after = float(workspace.freq.document_frequency()[column])
        assert after < before, (
            f"df for {term!r} stayed at {before} after purging a page holding it"
        )


def test_rows_are_not_renumbered_by_a_purge(tmp_path):
    """Retirement must not move the rows that survive.

    The row is the key aligning the frequency matrix, the embedding matrix and
    the PageRank vector. Compacting on delete would renumber everything after
    the hole and silently re-point the other two.
    """
    with Workspace(tmp_path / "ws") as workspace:
        url1, html1 = _html("books-toscrape")
        url2, html2 = _html("quotes-toscrape")
        workspace.index_html(html1, url1)
        workspace.index_html(html2, url2)

        kept = {c.cid: workspace.freq.row_of(c.cid)
                for c in workspace.store.chunks(url2)}
        workspace.purge(url1)
        for cid, row in kept.items():
            assert workspace.freq.row_of(cid) == row, f"{cid} was renumbered"


def test_a_retired_row_scores_zero(tmp_path):
    with Workspace(tmp_path / "ws") as workspace:
        url, html = _html()
        workspace.index_html(html, url)
        cid = workspace.store.chunks()[0].cid
        row = workspace.freq.row_of(cid)

        workspace.freq.remove(cid)
        sims = workspace.freq.similarities("books")
        assert float(sims[row]) == 0.0


def test_re_adding_a_retired_chunk_revives_its_row(tmp_path):
    with Workspace(tmp_path / "ws") as workspace:
        url, html = _html()
        workspace.index_html(html, url)
        cid = workspace.store.chunks()[0].cid
        row = workspace.freq.row_of(cid)

        workspace.freq.remove(cid)
        assert workspace.freq.row_of(cid) is None
        assert workspace.freq.add(cid, "fresh text about books") == row
        assert _fired(inv.check_freq(workspace.freq)) == set()


def test_retired_rows_are_reclaimed_not_leaked(tmp_path):
    """Purge-and-rescan is the normal cycle; it must not grow the matrix.

    Without reclamation every cycle appends fresh rows and leaves the old
    ones behind, so a workspace kept up to date grows without bound and every
    matrix operation pays for rows that describe nothing.
    """
    url, html = _html()
    with Workspace(tmp_path / "ws") as workspace:
        workspace.index_html(html, url)
        first = len(workspace.freq.rows)

        for _ in range(3):
            workspace.purge(url)
            workspace.index_html(html, url)

        assert len(workspace.freq.rows) == first, (
            f"three purge/rescan cycles grew the matrix from {first} to "
            f"{len(workspace.freq.rows)} rows"
        )
        assert _fired(inv.check_workspace(workspace)) == set()


def test_the_free_list_survives_a_reopen(tmp_path):
    """Otherwise the leak returns the moment the workspace is closed."""
    url1, html1 = _html("books-toscrape")
    url2, html2 = _html("quotes-toscrape")
    with Workspace(tmp_path / "ws") as workspace:
        workspace.index_html(html1, url1)
        workspace.index_html(html2, url2)
        workspace.purge(url1)
        retired = len(workspace.freq.rows) - workspace.freq.live_rows
        assert retired > 0

    with Workspace(tmp_path / "ws") as workspace:
        assert len(workspace.freq._free) == retired
        before = len(workspace.freq.rows)
        workspace.index_html(html1, url1)
        assert len(workspace.freq.rows) <= before
        assert _fired(inv.check_workspace(workspace)) == set()


# --- re-scanning a page that lost content ------------------------------------


def _catalogue(items):
    lis = "".join(f"<li><a href='/i/{i}'>ITEM-{i}-TEXT</a></li>" for i in items)
    return (f"<html><body><main><h1>Catalogue</h1>"
            f"<ul>{lis}</ul></main></body></html>")


SHRINK_URL = "https://shrink.test/p"


def test_anchors_stay_aligned_with_lines_when_a_page_shrinks(tmp_path):
    """The bug: MERGE added anchors and never removed them.

    A chunk that shrank from 21 lines to 7 kept all 21 anchors. Both
    `MarkdownChunk.from_json` and the REPL pair lines with anchors *by
    position*, so every line was attributed to the wrong address — the
    address-to-document link pointing at the wrong element, silently.
    """
    with Workspace(tmp_path / "ws", context_window=200) as workspace:
        workspace.index_html(_catalogue(range(30)), SHRINK_URL)
        workspace.index_html(_catalogue(range(3)), SHRINK_URL)

        for chunk in workspace.store.chunks(SHRINK_URL):
            lines = chunk.md.split("\n")
            anchors = workspace.store.addresses_of(chunk.cid)
            assert len(anchors) == len(lines), (
                f"{chunk.cid}: {len(lines)} line(s) but {len(anchors)} anchor(s)"
            )


def test_chunks_that_vanish_are_removed(tmp_path):
    with Workspace(tmp_path / "ws", context_window=200) as workspace:
        workspace.index_html(_catalogue(range(30)), SHRINK_URL)
        many = workspace.stats()["chunks"]
        workspace.index_html(_catalogue(range(3)), SHRINK_URL)
        few = workspace.stats()["chunks"]
        assert few < many, f"chunks stayed at {few} after the page shrank"


def test_addresses_that_vanish_are_removed(tmp_path):
    with Workspace(tmp_path / "ws", context_window=200) as workspace:
        workspace.index_html(_catalogue(range(30)), SHRINK_URL)
        many = workspace.stats()["addresses"]
        workspace.index_html(_catalogue(range(3)), SHRINK_URL)
        few = workspace.stats()["addresses"]
        assert few < many // 2, (
            f"addresses only fell from {many} to {few} for a page that lost 90%"
        )


def test_removed_content_is_no_longer_retrievable(tmp_path):
    """The visible consequence: search must not return what is gone."""
    with Workspace(tmp_path / "ws", context_window=200) as workspace:
        workspace.index_html(_catalogue(range(30)), SHRINK_URL)
        workspace.index_html(_catalogue(range(3)), SHRINK_URL)

        stale = [h for h in workspace.search("ITEM", k=30)
                 if any(f"ITEM-{i}-" in h.markdown for i in range(3, 30))]
        assert not stale, f"{len(stale)} hit(s) returned removed content"


def test_the_frequency_matrix_retires_vanished_chunks(tmp_path):
    """Otherwise idf keeps counting chunks the page no longer produces."""
    with Workspace(tmp_path / "ws", context_window=200) as workspace:
        workspace.index_html(_catalogue(range(30)), SHRINK_URL)
        many = workspace.freq.live_rows
        workspace.index_html(_catalogue(range(3)), SHRINK_URL)
        assert workspace.freq.live_rows < many


def test_the_invariant_holds_after_a_shrink(tmp_path):
    with Workspace(tmp_path / "ws", context_window=200) as workspace:
        workspace.index_html(_catalogue(range(30)), SHRINK_URL)
        workspace.index_html(_catalogue(range(3)), SHRINK_URL)
        assert _fired(inv.check_workspace(workspace)) == set()


def test_a_page_that_grows_again_recovers(tmp_path):
    """Reconciliation must not be one-way."""
    with Workspace(tmp_path / "ws", context_window=200) as workspace:
        workspace.index_html(_catalogue(range(30)), SHRINK_URL)
        workspace.index_html(_catalogue(range(3)), SHRINK_URL)
        workspace.index_html(_catalogue(range(30)), SHRINK_URL)

        assert workspace.search("ITEM-27-TEXT", k=5), "restored content is missing"
        assert _fired(inv.check_workspace(workspace)) == set()
        for chunk in workspace.store.chunks(SHRINK_URL):
            assert len(workspace.store.addresses_of(chunk.cid)) == \
                len(chunk.md.split("\n"))


def test_reindexing_an_unchanged_page_removes_nothing(tmp_path):
    """Reconciliation must not churn a page that did not change."""
    with Workspace(tmp_path / "ws", context_window=200) as workspace:
        workspace.index_html(_catalogue(range(30)), SHRINK_URL)
        before = workspace.stats()
        workspace.index_html(_catalogue(range(30)), SHRINK_URL)
        after = workspace.stats()
        assert after["chunks"] == before["chunks"]
        assert after["addresses"] == before["addresses"]
        assert after["freq_rows"] == before["freq_rows"]


def test_one_page_shrinking_does_not_disturb_another(tmp_path):
    """`_reconcile` is scoped to a url; a shared corpus must survive it."""
    other = "https://other.test/p"
    with Workspace(tmp_path / "ws", context_window=200) as workspace:
        workspace.index_html(_catalogue(range(20)), SHRINK_URL)
        workspace.index_html(_catalogue(range(20)), other)
        kept = {c.cid for c in workspace.store.chunks(other)}

        workspace.index_html(_catalogue(range(2)), SHRINK_URL)
        assert {c.cid for c in workspace.store.chunks(other)} == kept
        assert workspace.search("ITEM-15-TEXT", k=5), "the other page lost content"
        assert _fired(inv.check_workspace(workspace)) == set()


def test_retired_rows_never_surface_even_with_a_floor(tmp_path):
    """`--floor` softens every factor, including a tombstone's.

    A retired row scores zero on the lexical factor, which hides it only while
    the product is strict. Under a floor it came back as a hit with an empty
    cid, empty url and empty markdown — a phantom produced by the very option
    a user reaches for when they are getting too few answers.
    """
    with Workspace(tmp_path / "ws", context_window=200) as workspace:
        workspace.index_html(_catalogue(range(30)), SHRINK_URL)
        workspace.index_html(_catalogue(range(2)), SHRINK_URL)
        assert workspace.freq.live_rows < len(workspace.freq.rows), (
            "no rows were retired; the test cannot exercise the case"
        )

        hits = workspace.search("anything at all", k=20, floor=1e-6)
        phantom = [h for h in hits if not h.markdown.strip() or not h.cid]
        assert not phantom, f"{len(phantom)} phantom hit(s): {phantom[:2]}"


def test_a_floor_still_returns_real_chunks(tmp_path):
    """Masking tombstones must not mask everything."""
    with Workspace(tmp_path / "ws", context_window=200) as workspace:
        workspace.index_html(_catalogue(range(10)), SHRINK_URL)
        hits = workspace.search("zzzznotpresent", k=5, floor=1e-6)
        assert hits, "the floor stopped softening the veto"
        assert all(h.cid and h.markdown for h in hits)


def test_from_json_refuses_a_misaligned_chunk():
    """Loud beats silent: `zip` would misattribute rather than fail."""
    from vertiscope.markdown import MarkdownChunk

    with pytest.raises(ValueError, match="anchor"):
        MarkdownChunk.from_json({
            "cid": "x", "url": "u", "xpath": "/", "part": 0,
            "md": "one\ntwo", "anchors": ["u|/a|text.visible|text()"],
        })
