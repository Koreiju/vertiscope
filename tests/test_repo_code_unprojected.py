"""G-375: the repository's own code never reaches the projector.

PLUGIN_GOAL 166 a: "only code obtained from scans to their artifacts from the
browser are embedded in the projector. The codebase itself is removed entirely
from our 3D layout". The same page stored under a browser URL and under
`code://repo/`, `code://plugin/` and `code://pypi/` addresses: only the first is
drawable. Planted `PLANT_PROJECT_REPO_CODE` puts them back.
"""

import json
import pathlib

import pytest

from domvec import graphstore as gs
from domvec.workspace import Workspace

CORPUS = pathlib.Path(__file__).parent / "corpus"
MANIFEST = CORPUS / "manifest.json"
DIM = 768
REPO = ("code://repo/core/chunk_builder.py", "code://plugin/graph.ts", "code://pypi/urllib/parse.py")


def test_the_predicate():
    assert gs.projectable("https://github.com/x/y/blob/main/a.py")   # scanned code: projected
    assert gs.projectable("vault://notes/a.md")
    assert not any(gs.projectable(u) for u in REPO)
    gs.PLANT_PROJECT_REPO_CODE[0] = True
    try:
        assert all(gs.projectable(u) for u in REPO)
    finally:
        gs.PLANT_PROJECT_REPO_CODE[0] = False


@pytest.fixture()
def ws(tmp_path):
    if not MANIFEST.exists():
        pytest.skip("frozen corpus absent")
    pages = [p for p in json.loads(MANIFEST.read_text())["pages"] if p.get("ok")]
    page = next((p for p in pages if p["slug"].startswith("books-toscrape")), pages[0])
    html = (CORPUS / f"{page['slug']}.html").read_text(encoding="utf-8", errors="replace")
    with Workspace(tmp_path / "ws") as workspace:
        workspace.index_html(html, page["url"])
        for u in REPO:
            workspace.index_html(html.replace("<title>", "<title>%s " % u, 1), u)
        workspace.settle()
        # No embedder runs here, and identical pages dedup into one: give
        # every chunk its own vector and make it its own original.
        store = workspace.store
        cids = [r[0] for r in store._rows("MATCH (c:Chunk) RETURN c.cid")]
        for i, c in enumerate(cids):
            v = [0.0] * DIM
            v[i % DIM] = 1.0
            store._execute("MATCH (c:Chunk {cid: $c}) SET c.embedding = $v, c.dup_of = '', "
                           "c.group_of = '', c.group_n = 1", {"c": c, "v": v})
        yield workspace, page["url"]


def test_lead_and_page_vectors_hold_only_the_browser_page(ws):
    workspace, url = ws
    store = workspace.store
    assert {u for u in store._page_vectors_all()[0]} >= set(REPO)   # stored: the code view still reads them
    assert {u for _c, u, _v in store.lead_vectors()} == {url}
    assert set(store.page_vectors()[0]) == {url}


def test_planted_arm_projects_them_again(ws):
    workspace, url = ws
    gs.PLANT_PROJECT_REPO_CODE[0] = True
    try:
        assert {u for _c, u, _v in workspace.store.lead_vectors()} >= {url, *REPO}
    finally:
        gs.PLANT_PROJECT_REPO_CODE[0] = False
