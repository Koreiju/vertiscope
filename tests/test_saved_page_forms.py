"""A scanned chunk's page form is saved and renders with the page gone
(2026-10-10: "I should also never see the notification that something that we
have already chunked and tracked is inaccessible"). Planted: a chunk whose
form was never saved reads back nothing -- the banner's case."""

from vertiscope.obsidian import snapshots
from vertiscope.workspace import Workspace

HTML = "<html><body><h1>Title</h1>" + "".join(
    "<p>para %d with enough words to chunk</p>" % i for i in range(40)) + "</body></html>"
URL = "http://a.test/p"


def _snap(i):
    return {"html": "<div style='color:red'><p>para %d</p><img src='http://a.test/i%d.png'></div>" % (i, i),
            "bg": "rgb(0,0,0)", "color": "rgb(255,0,0)", "font": "16px serif",
            "elements": 3, "found": 1, "url": URL, "at": 1}


def test_saved_forms_round_trip_and_are_mapped_in_the_graph(tmp_path):
    with Workspace(tmp_path) as ws:
        ws.index_html(HTML, URL)
        cids = [c for (c,) in ws.store._rows("MATCH (c:Chunk {url: $u}) RETURN c.cid", {"u": URL})]
        assert len(cids) >= 2
        got = snapshots.save(ws, [{"cid": c, "snap": _snap(i)} for i, c in enumerate(cids)])
        assert got["mapped"] == len(cids) and got["written"] == len(cids)
        back = snapshots.load(ws, cids[0])
        assert back["html"] == _snap(0)["html"] and back["color"] == "rgb(255,0,0)"
        assert snapshots.coverage(ws, URL) == {"url": URL, "chunks": len(cids), "saved": len(cids)}
        again = snapshots.save(ws, [{"cid": cids[0], "snap": _snap(0)}])
        assert again["same"] == 1 and again["written"] == 0


def test_planted_never_saved_reads_back_nothing(tmp_path):
    with Workspace(tmp_path) as ws:
        ws.index_html(HTML, URL)
        cid = ws.store._rows("MATCH (c:Chunk {url: $u}) RETURN c.cid LIMIT 1", {"u": URL})[0][0]
        assert snapshots.load(ws, cid) is None
        assert snapshots.save(ws, [{"cid": cid, "snap": {"html": ""}}])["skipped"] == 1


def test_a_saved_form_draws_its_saved_pictures_from_the_sidecar(tmp_path):
    """"Even media" (2026-10-10): with the connection down the form still
    draws its pictures. Planted: a picture never saved stays remote."""
    with Workspace(tmp_path) as ws:
        ws.index_html(HTML, URL)
        cid = ws.store._rows("MATCH (c:Chunk {url: $u}) RETURN c.cid LIMIT 1", {"u": URL})[0][0]
        snap = _snap(0)
        snapshots.save(ws, [{"cid": cid, "snap": snap}])
        assert snapshots.media_urls(snap["html"]) == ["http://a.test/i0.png"]
        before = snapshots.localize(ws, snapshots.load(ws, cid), "http://127.0.0.1:8788")
        assert before["media"] == {"local": 0, "remote": 1}           # planted: not saved
        got = snapshots.save_media(ws, "http://a.test/i0.png", b"\x89PNG....", "image/png")
        assert got["saved"]
        after = snapshots.localize(ws, snapshots.load(ws, cid), "http://127.0.0.1:8788")
        assert after["media"] == {"local": 1, "remote": 0}
        assert "http://127.0.0.1:8788/media/" + snapshots.media_key("http://a.test/i0.png") in after["html"]
        data, ct = snapshots.load_media(ws, snapshots.media_key("http://a.test/i0.png"))
        assert data == b"\x89PNG...." and ct == "image/png"
        assert not snapshots.save_media(ws, "http://a.test/x", b"<html>", "text/html")["saved"]
