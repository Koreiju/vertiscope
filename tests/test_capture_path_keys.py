"""The live-capture path writes addresses too, and by a different door.

`index_html` is the corpus-runner path and it was the only one covered.
What the browser cell uses is `ingest_chunks` with a DELTA -- `complete`
false, `addresses` omitted so they are taken from the chunks' own line
anchors. Measured live while the new requirement checks were running, the
store's blank-key counters went from 0 back up to 124,176 addresses and
30,134 anchors, which no amount of repairing the store can explain: something
currently running was writing keyless rows.

These tests ask the delta path the same questions the full path was asked.
"""

import json
import pathlib

import pytest

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


def _render(ws, html, url):
    """The chunks a scan produces, which is what a delta carries."""
    from vertiscope.core.content_tagger import ContentTagger
    from vertiscope.core.shadow_html_parser import ShadowDOM
    from vertiscope.trie import AddressTrie
    from vertiscope.markdown import RenderReport

    tagged = ContentTagger(ShadowDOM(html)).tag()
    trie = AddressTrie.from_tagged(tagged, url)
    chunks, _counts = ws.ingest(url, trie, report=RenderReport(), title="")
    return chunks


def _blank(store):
    """Blank keys across the whole store, the way `/health` counts them."""
    rows = store._rows(
        "MATCH (a:Address) RETURN a.aid, a.akey, a.url, a.xpath")
    blank = [r for r in rows if not r[1]]
    return {
        "total": len(rows),
        "blank": len(blank),
        "blank_with_a_url": sum(1 for r in blank if r[2]),
        "blank_anchored": store._rows(
            "MATCH ()-[r:Anchors]->(a:Address) "
            "WHERE a.akey IS NULL OR a.akey = '' RETURN count(r)")[0][0],
    }


def test_a_delta_capture_writes_every_akey(tmp_path):
    """The path the browser cell actually uses.

    A delta re-ingests the chunks a scan produced, with `addresses` omitted
    so they come from the lines themselves. If that derivation loses the key,
    every line the reader is looking at loses its handle on the page while
    they browse -- which is the worst possible moment for it.
    """
    with Workspace(tmp_path / "ws") as ws:
        url, html = _html()
        ws.index_html(html, url)
        ws.settle()
        base = _blank(ws.store)
        assert base["blank"] == 0, base

        # **Rendered chunks, not stored ones.** A `StoredChunk` has no
        # `.lines`, and `ingest_chunks` derives its addresses from exactly
        # those -- so a delta must carry what the sensor produced.
        chunks = _render(ws, html, url)
        assert chunks, "nothing to re-ingest"

        # What a live capture does: some of those chunks again, as a delta.
        ws.ingest_chunks(url, chunks[: max(1, len(chunks) // 2)],
                         complete=False)
        ws.settle()
        after = _blank(ws.store)
        assert after["blank"] == 0, (
            "a delta capture wrote %d addresses with no key (%d of them with "
            "a url, %d anchors now point at one) -- the lines a reader is "
            "watching lose their handle on the page mid-scan"
            % (after["blank"], after["blank_with_a_url"],
               after["blank_anchored"]))


def test_a_delta_capture_does_not_strand_an_anchor(tmp_path):
    """Every anchor still points at an address that can be parsed back."""
    from vertiscope.address import ContentAddress

    with Workspace(tmp_path / "ws") as ws:
        url, html = _html()
        ws.index_html(html, url)
        ws.settle()
        chunks = _render(ws, html, url)
        ws.ingest_chunks(url, chunks[: max(1, len(chunks) // 2)],
                         complete=False)
        ws.settle()
        rows = ws.store._rows(
            "MATCH ()-[:Anchors]->(a:Address) RETURN DISTINCT a.akey")
        bad = []
        for (akey,) in rows:
            try:
                ContentAddress.parse(akey or "")
            except Exception:                       # noqa: BLE001
                bad.append(akey)
        assert not bad, "%d anchored addresses will not parse: %r" % (
            len(bad), bad[:3])
