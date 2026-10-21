"""The running plugin draws what the chunk projector computed.

The defect this pins was not a wrong number; it was a disconnection: the
pipeline measured a projector while the pane drew positions from three other
places. So every assertion here compares the LIVE pane against the LIVE
projector, through the plugin that is loaded (reloaded first), and the
comparison is exact -- a pane that recomputes anything cannot pass it.

Needs VERTISCOPE_LIVE=1, the sidecar and Obsidian with the graph pane.
"""

import json
import math
import os
import time
import urllib.request

import pytest

LIVE = os.environ.get("VERTISCOPE_LIVE") == "1"
pytestmark = pytest.mark.skipif(not LIVE, reason="needs VERTISCOPE_LIVE=1, the "
                                "sidecar and Obsidian")

SIDECAR = "http://127.0.0.1:8788"
PAGE = "https://en.wikipedia.org/wiki/Ternary_search_tree"


def _get(path):
    with urllib.request.urlopen(SIDECAR + path, timeout=60) as r:
        return json.load(r)


@pytest.fixture(scope="module")
def live():
    from vertiscope.obsidian.live import Live
    got = Live()
    got.reload_plugin()
    assert (got.act("open", "graph").get("result") or {}).get("opened") == "graph"
    time.sleep(4)
    # A reload leaves nothing open, which would let the position check skip
    # itself. Browse a stored page so the pane has chunks to be checked.
    got.act("navigate", PAGE)
    time.sleep(15)
    got.act("open", "graph")
    time.sleep(4)
    return got


def _pane(live):
    return live.json_eval("""JSON.stringify((()=>{
      const v = app.workspace.getLeavesOfType('vertiscope-graph-view')[0].view;
      const d = v.graph.graphData();
      return {epoch: v.projEpoch, seq: v.projSeq,
        nodes: d.nodes.map(n => ({id: n.id, level: n.level, url: n.url,
                                  fit: [n.fitX, n.fitY, n.fitZ], room: n.room || 0}))};
    })())""")


def test_the_layout_comes_from_the_projector():
    got = _get("/layout?dims=3")
    assert got.get("source") == "projector", got.get("source")
    status = _get("/projector")
    assert got.get("epoch") == status["epoch"]


def test_every_drawable_chunk_is_projected():
    """Against the drawable set NOW, once the stream has drained -- the
    count at the fit is stale the moment a merge retires a member."""
    deadline = time.time() + 60
    status = _get("/projector?drawable=1")
    while status.get("queue") and time.time() < deadline:
        time.sleep(2)
        status = _get("/projector?drawable=1")
    if "drawable_now" not in status:
        pytest.skip("the loaded sidecar predates ?drawable=1")
    assert status["queue"] == 0, "the stream did not drain in 60 s"
    assert status["drawable_unprojected"] == 0, status
    assert status["projected_not_drawable"] == 0, status
    assert status["projected"] == status["drawable_now"]


def test_the_pane_draws_the_projectors_positions_exactly(live):
    pane = _pane(live)
    status = _get("/projector")
    assert pane["epoch"] == status["epoch"], "the pane is on a different fit"
    chunks = [n for n in pane["nodes"] if n["level"] == "chunk"]
    pages = [n for n in pane["nodes"] if n["level"] == "page"]
    assert pages, "no page nodes drawn"
    layout = _get("/layout?dims=3")
    page_pos = {n["cid"]: n["pos"] for n in layout["nodes"]}
    worst_page = max(math.dist(n["fit"], page_pos[n["id"]]) for n in pages
                     if n["id"] in page_pos)
    assert worst_page < 1e-3, "a page is drawn off the projector's position"
    if not chunks:
        pytest.skip("no chunk nodes open in the pane")
    placed = _get("/layout?dims=3&level=chunk")
    pos = {n["cid"]: n["pos"] for n in placed["nodes"]}
    off = [math.dist(n["fit"], pos[n["id"]]) for n in chunks if n["id"] in pos]
    assert off and max(off) < 1e-3, "chunks drawn off the projector: %s" % max(off)
    # And none carries the old local territory that overrode the fit.
    assert not [n for n in chunks if n["room"]], "chunks still carry a local room"
