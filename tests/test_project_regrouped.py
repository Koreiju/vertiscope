"""A re-cluster re-queues what it CHANGED for re-projection (G-13, 2026-10-30).

The sidecar re-queued every chunk of a page after each re-cluster, and a live
page is re-clustered after every quiet gap: drains of 60-129 chunks for a feed
adding two. Now: a chunk whose group changed, the leads on both sides, a chunk
not placed yet, one placed that the page lost. Planted
`PLANT_PROJECT_WHOLE_PAGE`: the whole page again.
"""

from domvec.obsidian import projector as P
from domvec.obsidian import sidecar as S


class _Store:
    def __init__(self, rows):
        self.rows = rows

    def _rows(self, q, params):
        return list(self.rows)


class _Workspace:
    def __init__(self, rows):
        self.store = _Store(rows)


def _setup(monkeypatch, rows):
    p = P.ChunkProjector()
    url = "https://t.test/feed"
    for cid in ["a", "b", "c", "d", "old"]:
        p.pos[cid] = [0.0, 0.0, 0.0]
        p.by_url.setdefault(url, set()).add(cid)
    monkeypatch.setattr(P, "projector", lambda: p)
    monkeypatch.setattr(S, "_project_dedup", lambda ws: 0)
    return p, url, _Workspace(rows)


def test_only_the_change_is_queued(monkeypatch):
    before = {"a": "", "b": "", "c": "", "d": "", "old": ""}
    # After: c joined a's group, "new" arrived, "old" is gone.
    rows = [("a", ""), ("b", ""), ("c", "a"), ("d", ""), ("new", "")]
    p, url, ws = _setup(monkeypatch, rows)
    n = S._project_regrouped(ws, url, before)
    assert set(p.queue) == {"a", "c", "new", "old"} and n == 4     # b and d untouched
    st = p.batching_status()
    assert st["regroups"] == 1 and st["regroup_queued"] == 4 and st["regroup_page_chunks"] == 5


def test_nothing_changed_queues_nothing(monkeypatch):
    rows = [("a", ""), ("b", ""), ("c", ""), ("d", ""), ("old", "")]
    p, url, ws = _setup(monkeypatch, rows)
    assert S._project_regrouped(ws, url, dict(rows)) == 0 and not p.queue


def test_planted_whole_page(monkeypatch):
    rows = [("a", ""), ("b", ""), ("c", ""), ("d", ""), ("old", "")]
    p, url, ws = _setup(monkeypatch, rows)
    monkeypatch.setattr(S, "PLANT_PROJECT_WHOLE_PAGE", [True])
    S._project_regrouped(ws, url, dict(rows))
    assert set(p.queue) == {"a", "b", "c", "d", "old"}               # the defect: all of it
