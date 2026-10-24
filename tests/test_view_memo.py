"""The chunk view's memos across a restart (`layout.save_view_memo` /
`load_view_memo`): kept for a page whose `scanned_at` is unchanged, dropped
for one rewritten since -- and the planted arm keeps nothing."""
import types

from domvec.obsidian import layout


class _Store:
    def __init__(self, stamps, chunks):
        self.stamps, self.chunks, self._tnodes = stamps, chunks, {}

    def _rows(self, q, params=None):
        if "p:Page" in q:
            return list(self.stamps.items())
        return list(self.chunks.items())

    def _tnode_memo(self):
        return self._tnodes


def _fresh():
    layout._CHUNK_FACTS.clear()
    layout._PAGE_EDGES.clear()


def test_kept_while_stamped_dropped_when_rewritten(tmp_path):
    _fresh()
    store = _Store({"u1": 1.0, "u2": 2.0}, {"c1": "u1", "c2": "u2"})
    ws = types.SimpleNamespace(store=store, path=tmp_path)
    store._tnodes.update({"u1": {"c1": ("html",)}, ("rows", "u1"): [("c1", "/html")],
                          "u2": {"c2": ("html",)}})
    layout._CHUNK_FACTS.update({"c1": ((10, 3), "t1", 4, None), "c2": ((20, 1), "t2", 5, None)})
    saved = layout.save_view_memo(ws)
    assert saved["pages"] == 2 and saved["facts"] == 2

    # A new process: empty memos, and u2 rewritten since the save.
    _fresh()
    store2 = _Store({"u1": 1.0, "u2": 9.0}, {"c1": "u1", "c2": "u2"})
    got = layout.load_view_memo(types.SimpleNamespace(store=store2, path=tmp_path))
    assert got == {"pages_kept": 1, "pages_stale": 1, "facts": 1}
    assert store2._tnodes == {"u1": {"c1": ("html",)}, ("rows", "u1"): [("c1", "/html")]}
    # The write counter is this process's: re-keyed to 0.
    assert layout._CHUNK_FACTS == {"c1": ((10, 0), "t1", 4, None)}


def test_planted_keeps_nothing(tmp_path):
    _fresh()
    store = _Store({"u1": 1.0}, {"c1": "u1"})
    ws = types.SimpleNamespace(store=store, path=tmp_path)
    store._tnodes["u1"] = {"c1": ("html",)}
    layout._CHUNK_FACTS["c1"] = ((10, 0), "t", 1, None)
    layout.save_view_memo(ws)
    _fresh()
    layout.PLANT_NO_VIEW_MEMO[0] = True
    try:
        store2 = _Store({"u1": 1.0}, {"c1": "u1"})
        assert layout.load_view_memo(types.SimpleNamespace(store=store2, path=tmp_path)) is None
        assert store2._tnodes == {} and layout._CHUNK_FACTS == {}
    finally:
        layout.PLANT_NO_VIEW_MEMO[0] = False
