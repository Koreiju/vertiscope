"""G-375, the indexer half: the app no longer indexes this repository or an
installed package (`/package`). PLUGIN_GOAL 167 a: "Layout and indexer".
Planted `PLANT_PACKAGE_ROUTE`: the route indexes again -- the check must see
the module land in the store."""

import json
import urllib.error
import urllib.request

import pytest

from domvec.obsidian import sidecar as sc


def _post(port, body):
    req = urllib.request.Request("http://127.0.0.1:%d/package" % port, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


@pytest.fixture(params=[False, True], ids=["closed", "planted-open"])
def server(tmp_path, request):
    from domvec.workspace import Workspace
    sc.PLANT_PACKAGE_ROUTE[0] = request.param
    with Workspace(tmp_path / "ws") as ws:
        srv = sc.serve(ws, port=0, block=False, capture=True)
        try:
            yield request.param, srv.server_address[1], ws
        finally:
            srv.shutdown(); srv.server_close()
            sc.PLANT_PACKAGE_ROUTE[0] = False


def test_the_repository_is_not_indexed_from_the_app(server):
    planted, port, ws = server
    code, body = _post(port, {"repo": True, "limit": 1})
    repo_pages = [u for u in ws.store.page_urls() if u.startswith("code://repo/")]
    if planted:
        assert code == 200 and body.get("modules") == 1 and len(repo_pages) == 1, body
    else:
        assert code == 410 and "G-375" in body["error"] and repo_pages == []


def test_an_installed_package_is_not_indexed_either(server):
    planted, port, ws = server
    if planted:
        pytest.skip("the planted arm is proven on the repository above")
    code, body = _post(port, {"name": "json", "limit": 1})
    assert code == 410
    assert not [u for u in ws.store.page_urls() if u.startswith("code://pypi/")]
