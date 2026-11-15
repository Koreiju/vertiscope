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

        self.prepared_unlocked = []
        self.locked_whole = []

    def prepare_source(self, text, rel, root="repo"):
        self.prepared_unlocked.append(sc._WORK_LOCK.holder is None)
        return {"rel": rel}

    def index_source(self, text, rel, root="repo", prepared=None):
        self.indexed.append(rel)
        if prepared is None:
            self.locked_whole.append(rel)


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


def test_the_parse_happens_before_the_lock_is_taken(monkeypatch, tmp_path):
    """2026-11-15: re-indexing an edited sidecar.py held the work lock 214 s;
    the parse and the code graph touch no store and are built before it."""
    ws = FakeWorkspace(tmp_path)
    _run(monkeypatch, tmp_path, ws)
    assert ws.prepared_unlocked and all(ws.prepared_unlocked)
    assert ws.locked_whole == []


def test_planted_the_whole_index_holds_the_lock(monkeypatch, tmp_path):
    ws = FakeWorkspace(tmp_path)
    sc.PLANT_CODE_SYNC_PREPARE_LOCKED[0] = True
    try:
        _run(monkeypatch, tmp_path, ws)
    finally:
        sc.PLANT_CODE_SYNC_PREPARE_LOCKED[0] = False
    assert ws.prepared_unlocked == [] and len(ws.locked_whole) == len(ws.indexed) > 100


def test_a_prepared_index_stores_what_an_unprepared_one_does(tmp_path):
    from domvec.workspace import Workspace
    text = Path(sc.__file__).resolve().parents[1].joinpath("chat.py").read_text(encoding="utf-8")
    got = []
    for name, prepared in (("a", False), ("b", True)):
        with Workspace(tmp_path / name) as ws:
            prep = ws.prepare_source(text, "chat.py") if prepared else None
            r = ws.index_source(text, "chat.py", prepared=prep)
            rows = sorted(ws.store._rows("MATCH (c:Chunk) RETURN c.cid", {}))
            got.append((r.addresses, r.chunks, r.lines, rows, {k: v for k, v in (ws.last_cpg or {}).items() if not k.startswith("ms")}))
            print(name, ws.last_source_ms)
    assert got[0] == got[1]
