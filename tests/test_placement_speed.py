"""Placement: the read is batched without changing the answer, and warm.

Two fixes, each with the test that would have caught its absence.

**The read.** `place_into` asked the store two or three questions per cid;
on a 151-chunk page that was 337 ms of round trips. `chunks_for_placement`
answers for all of them, switching between one lookup per cid and one scan
at a measured crossover. A faster read is only a fix if it returns the SAME
answer, so the offline tests force each path and compare them field by
field -- including the group-embedding substitution, planted on purpose so
both paths are made to exercise it rather than trivially agreeing on chunks
that have no vector at all.

**The warmup.** UMAP's transform costs ~1.5 s on its first calls in a
process and ~3 ms after, and that cost used to land on the first reader
gesture after a restart. The live test asserts the sidecar paid it at
startup and that no capture since has paid it again.
"""

import json
import os
import pathlib

import pytest

from vertiscope.graphstore import GraphStore
from vertiscope.workspace import Workspace

CORPUS = pathlib.Path(__file__).parent / "corpus"
MANIFEST = CORPUS / "manifest.json"
LIVE = os.environ.get("VERTISCOPE_LIVE") == "1"
DIM = 768


def _html(prefix="books-toscrape"):
    if not MANIFEST.exists():
        pytest.skip("frozen corpus absent")
    pages = [p for p in json.loads(MANIFEST.read_text())["pages"] if p.get("ok")]
    page = next((p for p in pages if p["slug"].startswith(prefix)), pages[0])
    return page["url"], (CORPUS / f"{page['slug']}.html").read_text(
        encoding="utf-8", errors="replace")


def _both_paths(store, cids):
    saved = GraphStore._PLACEMENT_SCAN_AT
    try:
        GraphStore._PLACEMENT_SCAN_AT = 10 ** 9     # every cid looked up
        per_cid = store.chunks_for_placement(cids)
        GraphStore._PLACEMENT_SCAN_AT = 1           # one scan
        scan = store.chunks_for_placement(cids)
    finally:
        GraphStore._PLACEMENT_SCAN_AT = saved
    return per_cid, scan


def _norm(rows):
    out = []
    for cid, chunk, vector in rows:
        out.append((cid,
                    None if chunk is None else (
                        chunk.cid, chunk.url, chunk.xpath, chunk.part,
                        chunk.group_of, chunk.group_n, chunk.redundant),
                    None if vector is None else [round(float(x), 6) for x in vector]))
    return out


@pytest.fixture()
def ws(tmp_path):
    with Workspace(tmp_path / "ws") as workspace:
        url, html = _html()
        workspace.index_html(html, url)
        workspace.settle()
        yield workspace, url


def test_both_read_paths_return_the_same_chunks(ws):
    workspace, url = ws
    cids = [c.cid for c in workspace.store.chunks(url)]
    assert len(cids) >= 4, "fixture page too small to be a test"
    per_cid, scan = _both_paths(workspace.store, cids)
    assert _norm(per_cid) == _norm(scan)
    assert [r[0] for r in scan] == list(dict.fromkeys(cids)), "order not kept"


def test_both_read_paths_make_the_same_vector_choice(ws):
    """The planted arm: give chunks vectors, and one a GROUP vector.

    Without vectors every row's vector is None and the two paths agree
    trivially. So one chunk gets its own embedding only, and another is made
    a group lead with both an own and a group embedding -- which must be
    placed by the GROUP vector on both paths.
    """
    workspace, url = ws
    store = workspace.store
    cids = [c.cid for c in store.chunks(url)]
    plain, lead = cids[0], cids[1]
    own = [0.0] * DIM
    own[0] = 1.0
    group = [0.0] * DIM
    group[1] = 1.0
    store._execute("MATCH (c:Chunk {cid: $c}) SET c.embedding = $v",
                   {"c": plain, "v": own})
    store._execute("MATCH (c:Chunk {cid: $c}) SET c.embedding = $v, "
                   "c.group_embedding = $g, c.group_n = 3, c.group_of = $c",
                   {"c": lead, "v": own, "g": group})

    per_cid, scan = _both_paths(store, cids)
    assert _norm(per_cid) == _norm(scan)
    chosen = {cid: vec for cid, _chunk, vec in scan}
    assert chosen[plain] is not None and chosen[plain][0] == 1.0
    assert chosen[lead] is not None and chosen[lead][1] == 1.0, (
        "a group lead was placed by its own vector, not the group's")


def test_an_all_zero_group_vector_falls_back_on_both_paths(ws):
    """`group_embedding()` treats all-zeros as absent; the scan must too, or
    a lead with an unset group vector is placed at the origin."""
    workspace, url = ws
    store = workspace.store
    lead = [c.cid for c in store.chunks(url)][2]
    own = [0.0] * DIM
    own[5] = 1.0
    store._execute("MATCH (c:Chunk {cid: $c}) SET c.embedding = $v, "
                   "c.group_embedding = $g, c.group_n = 2, c.group_of = $c",
                   {"c": lead, "v": own, "g": [0.0] * DIM})
    per_cid, scan = _both_paths(store, [lead])
    assert _norm(per_cid) == _norm(scan)
    assert scan[0][2][5] == 1.0, "fell back to nothing instead of its own vector"


def test_unknown_cids_come_back_as_none_in_order(ws):
    workspace, url = ws
    real = [c.cid for c in workspace.store.chunks(url)][:2]
    ask = [real[0], "no-such-cid", real[1]]
    per_cid, scan = _both_paths(workspace.store, ask)
    assert _norm(per_cid) == _norm(scan)
    assert [r[0] for r in scan] == ask
    assert scan[1][1] is None and scan[1][2] is None


# --- the warmup, live -----------------------------------------------------------


@pytest.mark.skipif(not LIVE, reason="needs VERTISCOPE_LIVE=1 and the sidecar")
def test_the_sidecar_paid_the_warmup_so_no_capture_does():
    from vertiscope.obsidian.live import Live
    rings = Live().get("/profile")
    warm = rings.get("warmup") or []
    assert warm, "the sidecar never ran its placement warmup"
    assert warm[-1].get("warmed"), "warmup did not run: %s" % warm[-1]
    # Both routes that place: a capture placing its own chunks, and the
    # pane's placement queue asking `/place` for ones a capture could not.
    # Reading only the first missed the path doing most of the work.
    placing = [c for c in (rings.get("capture") or []) + (rings.get("place") or [])
               if c.get("place_ms_transform") is not None]
    if not placing:
        pytest.skip("nothing has been placed since the sidecar started")
    worst = max(c["place_ms_transform"] for c in placing)
    # Cold, the first transform was 1,542-1,829 ms; warm it is single or low
    # double digits. 500 ms separates them with room for a slow machine.
    assert worst < 500, (
        "a capture paid %.0f ms in the transform -- the warmup did not "
        "cover it" % worst)
