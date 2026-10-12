"""PLUGIN_GOAL 108: chunk view's drawn places are kept on the chunks.

"i keep switching to 'chunk' view and re-fitting keeps re-running, but we
should be persisting these layouts to the entities in our database." The pane
relaxes a chunk's place once and stores it on the Chunk, with the fit point it
was relaxed from; the layout hands it back while the fit still puts the chunk
there, and drops it once the projector has moved the chunk. Planted
(`PLANT_NO_DRAWN`): stored places ignored.
"""

import threading
from types import SimpleNamespace

from domvec.address import ContentAddress
from domvec.graphstore import GraphStore
from domvec.markdown import MarkdownChunk, MarkdownLine
from domvec.obsidian import layout

URL = "https://example.org/drawn"


def _chunk(xpath, word):
    addr = ContentAddress(url=URL, xpath=xpath + "/p/text()[1]", tag="text.p", accessor="text")
    return MarkdownChunk(url=URL, xpath=xpath, lines=[MarkdownLine(depth=0, text=word, address=addr)])


class _Proj:
    def __init__(self, pos):
        self.lock = threading.Lock()
        self.pos = pos
        self.hsv = {}
        self.epoch, self.seq = 1, 1

    def status(self, _ws):
        return {"chunks_now": len(self.pos)}


def _setup(tmp_path):
    store = GraphStore(tmp_path / "g.kuzu")
    a, b = _chunk("/html/body/div[1]", "alpha"), _chunk("/html/body/div[2]", "beta")
    store.ingest(URL, [], [a, b], complete=False)
    return store, a, b


def test_drawn_place_round_trips_on_the_chunk(tmp_path):
    store, a, _b = _setup(tmp_path)
    assert store.save_drawn([(a.cid, [1, 2, 3, 0.5, 0.25, 0.125])]) == 1
    got = store._rows("MATCH (c:Chunk {cid: $c}) RETURN c.drawn", {"c": a.cid})[0][0]
    assert [round(v, 6) for v in got] == [1, 2, 3, 0.5, 0.25, 0.125]


def test_layout_hands_back_a_place_only_while_the_fit_is_unchanged(tmp_path):
    store, a, b = _setup(tmp_path)
    ws = SimpleNamespace(store=store)
    store.save_drawn([(a.cid, [9, 9, 9, 0.5, 0.5, 0.5]), (b.cid, [7, 7, 7, 0.1, 0.1, 0.1])])
    # a's fit is where it was drawn from; b's fit has moved since.
    proj = _Proj({a.cid: [0.5, 0.5, 0.5], b.cid: [0.9, 0.9, 0.9]})
    got = layout.projected_chunk_layout(ws, proj)
    by = {n["cid"]: n for n in got["nodes"]}
    assert by[a.cid]["drawn"] == [9, 9, 9]
    assert "drawn" not in by[b.cid]
    assert got["drawn_kept"] == 1 and got["drawn_stale"] == 1
    # Planted: stored places ignored -- every switch relaxes from the fit.
    layout.PLANT_NO_DRAWN[0] = True
    try:
        planted = layout.projected_chunk_layout(ws, proj)
        assert not any("drawn" in n for n in planted["nodes"])
    finally:
        layout.PLANT_NO_DRAWN[0] = False
