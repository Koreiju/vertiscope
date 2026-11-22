"""The repository-page purge (G-375; PLUGIN_GOAL 169, 2) through a real sidecar.

Planted `PLANT_SUBSTRING`: matching by substring takes a browser page whose
URL merely mentions `code://repo/` -- the check must see it go."""

import json
import pathlib

import pytest

from domvec.obsidian import purge_prefix as pp
from domvec.obsidian import sidecar as sc

CORPUS = pathlib.Path(__file__).parent / "corpus"
MANIFEST = CORPUS / "manifest.json"
BROWSER = "https://example.org/?ref=code://repo/x.py"     # mentions the prefix, is not under it
REPO = ["code://repo/a.py", "code://plugin/b.ts"]


@pytest.fixture()
def server(tmp_path):
    if not MANIFEST.exists():
        pytest.skip("frozen corpus absent")
    pages = [p for p in json.loads(MANIFEST.read_text())["pages"] if p.get("ok")]
    html = (CORPUS / f"{pages[0]['slug']}.html").read_text(encoding="utf-8", errors="replace")
    from domvec.workspace import Workspace
    with Workspace(tmp_path / "ws") as ws:
        for u in [BROWSER, *REPO]:
            ws.index_html(html, u)
        ws.settle()
        srv = sc.serve(ws, port=0, block=False, capture=True)
        try:
            yield "http://127.0.0.1:%d" % srv.server_address[1]
        finally:
            srv.shutdown(); srv.server_close()
            pp.PLANT_SUBSTRING[0] = False


def _urls(base):
    return set(pp._get(base, "/pages")["urls"])


def test_dry_run_counts_and_deletes_nothing(server):
    got = pp.purge(server, ["code://repo/", "code://plugin/"], dry_run=True)
    assert got["matched"] == 2 and got["by_prefix"] == {"code://repo/": 1, "code://plugin/": 1}
    assert _urls(server) >= {BROWSER, *REPO}


def test_purge_takes_the_repository_pages_and_keeps_the_browser_page(server):
    got = pp.purge(server, ["code://repo/", "code://plugin/"])
    assert got["purged"] == 2 and got["left_under_prefixes"] == 0 and got["failed_n"] == 0
    assert got["chunks_removed"] > 0
    assert _urls(server) == {BROWSER}


def test_planted_substring_takes_the_browser_page_too(server):
    pp.PLANT_SUBSTRING[0] = True
    pp.purge(server, ["code://repo/", "code://plugin/"])
    assert BROWSER not in _urls(server)       # the defect, caught
