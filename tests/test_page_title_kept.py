"""A write that does not know a page's title must not erase it.

Every live drain reaches `ingest_chunks` with no title, and both page writes
did `SET p.title = $title` unconditionally -- so each drain blanked the title
the settle had stored. Measured in the running store: 121 of 130 pages had no
title, the graph labelled them with their urls, and a reachability probe that
asks each page for words from its title asked RFC 9110 for "https rfc-editor".
"""

import pathlib
import shutil
import tempfile

import pytest

from vertiscope.workspace import Workspace

PAGE = ("<html><body><div><p>"
        + ("alpha beta gamma delta epsilon zeta eta theta " * 40)
        + "</p></div></body></html>")
URL = "https://fixture.test/title-kept"


@pytest.fixture()
def ws_path():
    tmp = tempfile.mkdtemp()
    try:
        yield pathlib.Path(tmp) / "ws"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _title(ws):
    return dict(ws.store._rows("MATCH (p:Page) RETURN p.url, p.title")).get(URL)


def test_a_drain_without_a_title_keeps_the_stored_one(ws_path):
    with Workspace(ws_path) as ws:
        ws.index_html(PAGE, URL, title="The real title")
        ws.settle()
        assert _title(ws) == "The real title", "the plant did not take"
        chunks = list(ws.store.chunks(URL))
        # The drain path: a delta, and no title.
        ws.ingest_chunks(URL, [], complete=False)
        ws.settle()
        assert _title(ws) == "The real title", \
            "a write with no title erased the stored one"
        assert chunks, "the fixture stored no chunks"


def test_a_write_that_knows_the_title_still_updates_it(ws_path):
    """The other arm: keeping a title must not mean freezing it."""
    with Workspace(ws_path) as ws:
        ws.index_html(PAGE, URL, title="Old")
        ws.settle()
        ws.index_html(PAGE, URL, title="New")
        ws.settle()
        assert _title(ws) == "New"
