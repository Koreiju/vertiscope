"""The plugin's TypeScript is part of the codebase corpus (`code://plugin/`).

Retrieval, 2026-11-15: the reader searched `unionRect xpa` and rank 1 was a
DuckDuckGo "No more results" page -- an echo of the query. `unionRect` is a
function in `obsidian-plugin/src/pipelinebox.ts`, and no TypeScript was in
the corpus: `_sync_code` walked `domvec/` alone, for `.py` and `.js`. The
code that draws the panels the reader is looking at could not be found.

Planted `PLANT_NO_PLUGIN_SOURCE`: the package only, as before -- the search
must then miss it.
"""
from pathlib import Path

import pytest

import domvec.obsidian.sidecar as sc
from domvec.source import iter_sources, tag_source, PLUGIN_SUFFIXES
from domvec.workspace import Workspace

from test_obsidian_layout import _StubEmbedder

PLUGIN_SRC = Path(__file__).resolve().parents[1] / "obsidian-plugin" / "src"


class _Ws:
    def __init__(self, path):
        self.path = str(path)
        self.read_only = False
        self.indexed = []

    def prepare_source(self, text, rel, root="repo"):
        return {"rel": rel}

    def index_source(self, text, rel, root="repo", prepared=None):
        self.indexed.append((root, rel))


def _sync(monkeypatch, tmp_path, planted):
    monkeypatch.setattr(sc, "_project_page", lambda w, u: None)
    monkeypatch.setattr(sc, "_yield_to_foreground", lambda *a, **k: 0.0)
    monkeypatch.setattr(sc, "PLANT_NO_PLUGIN_SOURCE", [planted])
    # A lock of this test's own: a sidecar an earlier test started leaves its
    # `_code_sync_forever` thread running, and a pass that finds the lock
    # held returns `busy` having indexed nothing (the full suite, 2026-11-15).
    import threading
    monkeypatch.setattr(sc, "_CODE_SYNC_LOCK", threading.Lock())
    ws = _Ws(tmp_path)
    out = sc._sync_code(ws)
    assert not out.get("busy"), out
    return ws, out


def test_the_sync_walks_the_plugin_source_as_its_own_root(monkeypatch, tmp_path):
    ws, out = _sync(monkeypatch, tmp_path, False)
    plugin = sorted(rel for root, rel in ws.indexed if root == "plugin")
    assert "pipelinebox.ts" in plugin and "graph.ts" in plugin, plugin[:10]
    assert all(rel.endswith(".ts") for rel in plugin)
    assert len(plugin) == len(list(iter_sources(PLUGIN_SRC, PLUGIN_SUFFIXES)))
    # The package root is unchanged by it.
    assert ("repo", "chat.py") in ws.indexed
    assert not any(root == "repo" and rel.endswith(".ts") for root, rel in ws.indexed)


def test_planted_package_only_walks_no_typescript(monkeypatch, tmp_path):
    ws, out = _sync(monkeypatch, tmp_path, True)
    assert not any(root == "plugin" for root, _ in ws.indexed)
    assert ("repo", "chat.py") in ws.indexed


def test_typescript_is_read_as_comments_and_code_pieces():
    text = (PLUGIN_SRC / "pipelinebox.ts").read_text(encoding="utf-8")
    tags = tag_source(text, root="plugin", rel_path="pipelinebox.ts")
    code = [t.value for t in tags if t.subcategory == "code"]
    prose = [t.value for t in tags if t.subcategory == "visible"]
    assert any("unionRect" in v for v in code), len(code)
    assert prose, "no comments read"


@pytest.mark.parametrize("planted", [False, True])
def test_a_search_for_a_plugin_identifier_finds_its_file(tmp_path, monkeypatch, planted):
    text = (PLUGIN_SRC / "pipelinebox.ts").read_text(encoding="utf-8")
    with Workspace(tmp_path / "ws", embedder=_StubEmbedder()) as w:
        w.index_html("<html><body><main><p>unrelated page about orchids</p></main></body></html>",
                     "https://orchid.test/")
        if not planted:
            w.index_source(text, "pipelinebox.ts", root="plugin")
        w.flush_vectors()
        urls = [h.url for h in w.search("unionRect", k=5)]
    if planted:
        assert "code://plugin/pipelinebox.ts" not in urls, urls
    else:
        assert urls and urls[0] == "code://plugin/pipelinebox.ts", urls
