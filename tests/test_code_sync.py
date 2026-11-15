"""The codebase reaches the store as it is on disk, in O(delta).

2026-11-14: 18 of 145 `domvec/` modules had no chunk in the store (the chat
backend among them) because a module was indexed only when saved through the
plugin. `_sync_code` hashes every module, re-indexes the missing or changed
ones, and leaves the rest; planted (`PLANT_NO_CODE_SYNC`) nothing is indexed.
"""
from pathlib import Path

import domvec.obsidian.sidecar as sc


class FakeWorkspace:
    def __init__(self, path):
        self.path = str(path)
        self.read_only = False
        self.indexed = []

    def index_source(self, text, rel, root="repo"):
        self.indexed.append(rel)


def _run(monkeypatch, tmp_path, ws):
    monkeypatch.setattr(sc, "_project_page", lambda w, u: None)
    monkeypatch.setattr(sc, "_yield_to_foreground", lambda *a, **k: 0.0)
    return sc._sync_code(ws)


def test_first_pass_indexes_every_module_then_only_the_delta(monkeypatch, tmp_path):
    ws = FakeWorkspace(tmp_path)
    first = _run(monkeypatch, tmp_path, ws)
    n = first["files"]
    assert n > 100 and first["indexed"] == n and first["unchanged"] == 0
    assert "chat.py" in ws.indexed and "obsidian/front.py" in ws.indexed
    ws.indexed.clear()
    second = _run(monkeypatch, tmp_path, ws)
    assert second["indexed"] == 0 and second["unchanged"] == n
    # One module changes on disk (the ledger is what was last indexed): only it.
    import json
    led = tmp_path / "code_index.json"
    d = json.loads(led.read_text())
    d["code://repo/chat.py"] = "stale"
    d["code://repo/no_longer_here.py"] = "x"
    led.write_text(json.dumps(d))
    third = _run(monkeypatch, tmp_path, ws)
    assert ws.indexed == ["chat.py"] and third["indexed"] == 1 and third["gone"] == 1


def test_planted_no_sync_indexes_nothing(monkeypatch, tmp_path):
    ws = FakeWorkspace(tmp_path)
    sc.PLANT_NO_CODE_SYNC[0] = True
    try:
        got = _run(monkeypatch, tmp_path, ws)
    finally:
        sc.PLANT_NO_CODE_SYNC[0] = False
    assert got["planted"] is True and got["indexed"] == 0 and ws.indexed == []
