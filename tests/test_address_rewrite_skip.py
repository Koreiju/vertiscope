"""The address skip is a function of `content_hash` and nothing else.

`ingest` will not rewrite an address whose `content_hash` already matches
what the store holds. That is a real saving -- an unchanged page used to cost
as much as a new one -- but the write it skips sets six more columns:

    SET a.akey, a.url, a.xpath, a.tag, a.accessor, a.value

So any of those going missing is invisible to the guard, and re-scanning the
page can never repair it, because the content has not moved. This is
`CLAUDE.md` 5c -- *a cached verdict must name what it is a function of* --
applied to a row rather than to a classification.

Measured in the live corpus before these tests were written: **29 of 74
sampled pages had 100% blank `akey`** and the rest had 0%, all-or-nothing per
page, and 118,180 of 331,242 addresses corpus-wide. A blank `akey` cannot be
parsed back, so `addresses_of` drops the row and every line of every chunk on
that page comes back with `key: ""` -- no handle on the page, no affordances,
and nothing for `resolve_address` to resolve.
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


def _blank_akeys(store, url):
    rows = store._rows(
        "MATCH (a:Address {url: $u}) RETURN a.akey", {"u": url})
    return sum(1 for (akey,) in rows if not akey), len(rows)


def test_a_fresh_ingest_writes_every_akey(tmp_path):
    """The non-vacuity arm: on a store the current code wrote, akey is there.

    Without this the repair test below could pass on a corpus that never had
    the column, and prove nothing about the guard.
    """
    with Workspace(tmp_path / "ws") as ws:
        url, html = _html()
        ws.index_html(html, url)
        blank, total = _blank_akeys(ws.store, url)
        assert total > 0, "no addresses at all -- the fixture is wrong"
        assert blank == 0, f"{blank} of {total} addresses written with no akey"


def test_a_re_ingest_of_the_same_page_restores_a_blank_akey(tmp_path):
    """The defect, stated as the behaviour that had to change.

    A row whose `content_hash` was current used to be skipped whole, which
    made a blank `akey` permanent: the page could be re-scanned forever and
    the column stayed empty, because the content genuinely had not moved.
    Before the guard learned to read `akey`, this failed with **505 of 505**
    addresses still blank after re-ingesting the identical page.
    """
    with Workspace(tmp_path / "ws") as ws:
        url, html = _html()
        ws.index_html(html, url)
        ws.store._execute(
            "MATCH (a:Address {url: $u}) SET a.akey = ''", {"u": url})
        blank, total = _blank_akeys(ws.store, url)
        assert blank == total and total > 0, "the plant did not take"

        ws.index_html(html, url)                    # the identical page again

        blank_after, total_after = _blank_akeys(ws.store, url)
        assert total_after == total, "the re-ingest changed the address set"
        assert blank_after == 0, (
            f"{blank_after} of {total_after} addresses still have no akey "
            "after a re-ingest -- the content_hash guard skipped a write "
            "that sets six other columns")


def test_a_page_with_blank_akeys_serves_lines_with_no_key(tmp_path):
    """Why it matters, measured at the surface a reader meets.

    This is the failure D-26 reported from the live store, reproduced from
    the cause rather than observed: blank the akeys and every line of every
    chunk loses its handle on the page.
    """
    from vertiscope.obsidian.sidecar import chunk_payload

    with Workspace(tmp_path / "ws") as ws:
        url, html = _html()
        ws.index_html(html, url)
        cid = next(c.cid for c in ws.store.chunks(url))

        before = chunk_payload(ws, cid)
        keyed_before = sum(1 for ln in before["lines"] if ln.get("key"))
        assert keyed_before > 0, "no line was keyed even before the plant"

        ws.store._execute(
            "MATCH (a:Address {url: $u}) SET a.akey = ''", {"u": url})
        after = chunk_payload(ws, cid)
        keyed_after = sum(1 for ln in after["lines"] if ln.get("key"))
        assert keyed_after == 0, "the plant did not reach the payload"
        assert len(after["lines"]) == len(before["lines"])


def test_the_repair_rebuilds_a_key_that_parses_back_to_the_same_address(
        tmp_path):
    """The repair is exact, not approximate.

    `akey` is derived from four columns that are still on the row, so the
    rebuilt key must parse back to the address the store already describes --
    not merely to something non-empty. Checked against every repaired row.
    """
    from vertiscope.address import ContentAddress

    with Workspace(tmp_path / "ws") as ws:
        url, html = _html()
        ws.index_html(html, url)
        truth = {aid: akey for aid, akey in ws.store._rows(
            "MATCH (a:Address {url: $u}) RETURN a.aid, a.akey", {"u": url})}
        assert truth and all(truth.values())

        ws.store._execute(
            "MATCH (a:Address {url: $u}) SET a.akey = ''", {"u": url})
        report = ws.store.repair_blank_keys()
        assert report["blank"] == len(truth), report
        assert report["repaired"] == len(truth), report
        assert report["unrepairable"] == 0, report

        rebuilt = {aid: akey for aid, akey in ws.store._rows(
            "MATCH (a:Address {url: $u}) RETURN a.aid, a.akey", {"u": url})}
        assert rebuilt == truth, "the rebuilt key is not the original"
        for akey in rebuilt.values():
            ContentAddress.parse(akey)              # raises if it will not


def test_the_repair_is_idempotent_and_touches_nothing_that_is_whole(tmp_path):
    with Workspace(tmp_path / "ws") as ws:
        url, html = _html()
        ws.index_html(html, url)
        before = dict(ws.store._rows(
            "MATCH (a:Address {url: $u}) RETURN a.aid, a.akey", {"u": url}))
        report = ws.store.repair_blank_keys()
        assert report == {"blank": 0, "repaired": 0, "unrepairable": 0}
        after = dict(ws.store._rows(
            "MATCH (a:Address {url: $u}) RETURN a.aid, a.akey", {"u": url}))
        assert after == before
