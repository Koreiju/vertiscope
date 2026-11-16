"""D-2 on the LIVE capture path: the stream renders at the store's key level.

Read off the working store's `/health` (2026-11-16): 29,227 anchors were still
four-part, and Radix_tree -- the page the browser cell was capturing -- held
634 of 634. `Workspace` rendered at the store's level; the sidecar's
`StreamingScan` never asked, so every live capture wrote four-part keys into
a five-part store. Planted `PLANT_STREAM_NO_MD_LEVEL`: as before.
"""
import pytest

import domvec.stream as stream
from domvec.address import ContentAddress
from domvec.stream import StreamingScan

PAGE = ("<html><body><main><h1>Radix tree</h1><p>A radix tree stores shared prefixes once.</p>"
        "<ul><li>insert a key</li><li>look a key up</li><li>delete a key</li></ul></main></body></html>")


def _keys(chunks):
    out = []
    for c in chunks:
        for a in c.anchors:
            out.append(a if isinstance(a, str) else a.key())
    return out


@pytest.mark.parametrize("planted", [False, True])
def test_the_live_stream_writes_anchors_at_the_stores_level(monkeypatch, planted):
    monkeypatch.setattr(stream, "PLANT_STREAM_NO_MD_LEVEL", [planted])
    scan = StreamingScan("https://radix.test/", md_level=True)
    update = scan.push(PAGE)
    chunks = getattr(update, "all_chunks", None) or scan.dirty_chunks(update)
    keys = _keys(chunks)
    assert keys, chunks
    five = [k for k in keys if ContentAddress.parse(k).md]
    if planted:
        assert not five, keys[:3]
    else:
        assert len(five) == len(keys), [k for k in keys if not ContentAddress.parse(k).md][:3]


def test_a_store_without_the_level_keeps_four_part_keys():
    scan = StreamingScan("https://radix.test/", md_level=False)
    update = scan.push(PAGE)
    chunks = getattr(update, "all_chunks", None) or scan.dirty_chunks(update)
    assert all(not ContentAddress.parse(k).md for k in _keys(chunks))
