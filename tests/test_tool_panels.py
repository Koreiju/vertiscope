"""G-382: the kernel's tool panels as tool:// pages (domvec/tool_panels.py, POST /tool_panels).

Planted arms: a call the kernel lacks is refused before anything is stored;
the purge by prefix takes them all back out.
"""

import json
import urllib.request

import pytest

from domvec import graphstore as gs
from domvec import tool_panels as tp
from domvec import tool_surface as ts
from domvec.obsidian import purge_prefix as pp
from domvec.obsidian import sidecar as sc


def test_every_panel_line_is_a_call_the_kernel_has():
    panels = tp.render()
    assert set(panels) == {"search", "Database", "WebBrowser", "Agent", "Vault", "editor"}
    names = ts.kernel_names()
    for name, text in panels.items():
        block = text.split("```python\n", 1)[1].split("```", 1)[0]
        s = ts.parse("# " + name + "\n" + block, names)
        assert s.problems == [] and all(l.resolves for l in s.lines), (name, s.problems)
    assert "Database.search(query, k=5, where='')" in panels["Database"]


def test_planted_call_the_kernel_lacks_is_refused(monkeypatch):
    real = tp._calls
    monkeypatch.setattr(tp, "_calls", lambda: {**real(), "WebBrowser": real()["WebBrowser"] + [("WebBrowser.teleport(x)", "no such")]})
    with pytest.raises(ValueError, match="teleport"):
        tp.render()


def test_tool_pages_are_projectable():
    assert all(gs.projectable(tp.url_of(n)) for n in tp.render())


@pytest.fixture()
def server(tmp_path):
    from domvec.workspace import Workspace
    with Workspace(tmp_path / "ws") as ws:
        srv = sc.serve(ws, port=0, block=False, capture=True)
        try:
            yield "http://127.0.0.1:%d" % srv.server_address[1], ws
        finally:
            srv.shutdown(); srv.server_close()


def test_the_route_stores_them_and_the_purge_removes_them(server):
    base, ws = server
    req = urllib.request.Request(base + "/tool_panels", data=b"{}", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        got = json.load(r)
    urls = {p["url"] for p in got["panels"]}
    assert urls == {tp.url_of(n) for n in ("search", "Database", "WebBrowser", "Agent", "Vault", "editor")}
    assert all(p["chunks"] >= 1 for p in got["panels"])
    assert urls <= set(pp._get(base, "/pages")["urls"])
    # a search finds a tool panel by what it does -- the point of O.22
    hits = ws.search("read-only Cypher query over the store", k=10)
    assert any(str(getattr(h, "url", "")).startswith("tool://") for h in hits)
    out = pp.purge(base, ["tool://"])
    assert out["purged"] == 6 and out["left_under_prefixes"] == 0
