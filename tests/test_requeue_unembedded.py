"""Stored chunks with text and no vector are queued again mid-session (Workspace.requeue_unembedded).

Seen 2026-11-22 on the-fit: 508 such rows while the embed queue held 56. The
digest gate is the thing that refuses them -- it remembers a cid's text as
embedded -- so the leak is planted here exactly that way: the gate holds the
chunk's digest and the store row holds no vector. Planted PLANT_NO_REQUEUE
leaves it stuck.
"""

from types import SimpleNamespace

from domvec import workspace as ws
from domvec.vectors import VectorQueue


class _Store:
    def __init__(self, rows):
        self.rows = rows

    def _rows(self, q, params=None):
        assert "embedding IS NULL" in q
        return list(self.rows)[: params["n"]]


def _ws(rows):
    q = VectorQueue()
    self = SimpleNamespace(store=_Store(rows), vectors=q, embedder=object())
    return self, q


ROWS = [("c1", "a paragraph about tries", "https://ex.org/a"),
        ("c2", "older text", "https://ex.org/a#~v"),
        ("c3", "already waiting", "vault://note.md")]


def test_stuck_rows_are_queued_past_a_stale_digest(monkeypatch):
    monkeypatch.setattr(ws, "PLANT_NO_REQUEUE", [False])
    self, q = _ws(ROWS)
    # The leak: the gate says c1 was embedded, so a re-push is refused.
    q.seed([("c1", "a paragraph about tries", "https://ex.org/a")])
    assert not q.push("c1", "a paragraph about tries", url="https://ex.org/a")
    q.push("c3", "already waiting", url="vault://note.md")
    got = ws.Workspace.requeue_unembedded(self)
    assert got["found"] == 3 and got["queued_already"] == 1
    assert got["had_digest"] == 1 and got["versions"] == 1
    assert got["requeued"] == 2 and set(q.pending) == {"c1", "c2", "c3"}
    assert got["by_scheme"] == {"https": 2}


def test_nothing_stuck_is_a_no_op(monkeypatch):
    monkeypatch.setattr(ws, "PLANT_NO_REQUEUE", [False])
    self, q = _ws([])
    got = ws.Workspace.requeue_unembedded(self)
    assert got["found"] == 0 and not q.pending


def test_planted_no_requeue_leaves_them_stuck(monkeypatch):
    monkeypatch.setattr(ws, "PLANT_NO_REQUEUE", [True])
    self, q = _ws(ROWS)
    got = ws.Workspace.requeue_unembedded(self)
    assert got["requeued"] == 0 and not q.pending
