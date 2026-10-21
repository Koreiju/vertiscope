"""A settled page is durable: the store folds its write-ahead log in (D-48,
2026-10-07: a native crash set aside a ~17 MB WAL unreplayable)."""

from pathlib import Path

from vertiscope.workspace import Workspace

HTML = "<html><body><h1>Title</h1>" + "".join("<p>para %d with enough words to chunk</p>" % i for i in range(60)) + "</body></html>"


def _wal(ws) -> int:
    p = Path(str(ws.store.path) + ".wal")
    return p.stat().st_size if p.exists() else 0


def test_a_checkpoint_empties_the_wal(tmp_path):
    with Workspace(tmp_path) as ws:
        ws.index_html(HTML, "http://a.test/p")
        before = _wal(ws)
        ms = ws.store.checkpoint()
        assert isinstance(ms, float)
        assert _wal(ws) < max(1, before), (before, _wal(ws))


def test_planted_without_a_checkpoint_the_wal_holds_the_writes(tmp_path):
    with Workspace(tmp_path) as ws:
        ws.index_html(HTML, "http://a.test/p")
        assert _wal(ws) > 0
