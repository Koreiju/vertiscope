"""A hovered chunk the projector finds without its vector is RETRIED, not
dropped (G-80, 2026-10-30): the hover's immediate drain can read the chunk
just before the embedder's vector lands, and the embedder had already handed
it over -- the hovered chunk reached the graph last. Planted
`PLANT_DROP_HOT_WAITING`: dropped like any other."""

from types import SimpleNamespace

from domvec.obsidian import projector as P


class _Store:
    def __init__(self):
        self.vec = {}

    def chunks_for_placement(self, cids):
        ch = lambda c: SimpleNamespace(redundant=False, group_of="", url="https://t/p")  # noqa: E731
        return [(c, ch(c), self.vec.get(c)) for c in cids]


def _proj():
    p = P.ChunkProjector()
    p.projection = SimpleNamespace(place=lambda a: (a[:, :3], None))
    p._pages = lambda projection, live, vec: ({}, {})
    return p, SimpleNamespace(store=_Store())


def test_a_hovered_chunk_without_its_vector_is_kept_for_retry():
    p, ws = _proj()
    p.enqueue(["cold", "hot"])
    p.prioritize(["hot"])
    p.drain(ws)
    assert "hot" in p.hot_retry and "cold" not in p.hot_retry
    assert p.hot_stats["kept"] == 1


def test_planted_drops_it():
    p, ws = _proj()
    P.PLANT_DROP_HOT_WAITING[0] = True
    try:
        p.enqueue(["hot"])
        p.prioritize(["hot"])
        p.drain(ws)
    finally:
        P.PLANT_DROP_HOT_WAITING[0] = False
    assert not p.hot_retry
