"""G-145 (2026-11-16): a saved picture never becomes a file Obsidian indexes.

The workspace store lives inside the vault, and Obsidian indexes every path
with no dot-prefixed segment. Measured live through `cdp.mjs --hover-sweep
--profile` at 65,131 nodes: each picture the hover fetched was saved as three
new vault files, each new file cost Obsidian a `reconcileFileCreation` over
280,907 cached files, and the sweep spent 5.5 s there in 150-350 ms long tasks.

Here: a new picture is written under a dot-prefixed directory, so no segment
of its path is one Obsidian indexes; a picture saved by the old code in
`media/` is still found, served and never written twice. Planted
`PLANT_MEDIA_IN_VAULT`: the picture lands at an indexed path.

Trie framing: none of this touches the trie. A picture is a peripheral keyed
by its url's hash, beside the chunk that names it.
"""
from pathlib import Path
from types import SimpleNamespace

import pytest

from domvec.obsidian import snapshots

URL = "http://a.test/okapi.png"


def _indexed(rel: Path) -> bool:
    """Whether Obsidian would index this vault-relative path."""
    return not any(part.startswith(".") for part in rel.parts)


@pytest.mark.parametrize("planted", [False, True])
def test_a_new_picture_is_written_where_obsidian_does_not_index(tmp_path, monkeypatch, planted):
    monkeypatch.setattr(snapshots, "PLANT_MEDIA_IN_VAULT", [planted])
    ws = SimpleNamespace(path=str(tmp_path / "build" / "store"))
    got = snapshots.save_media(ws, URL, b"\x89PNG....", "image/png")
    assert got["saved"] and not got.get("same")
    written = [p.relative_to(tmp_path) for p in tmp_path.rglob("*") if p.is_file()]
    assert len(written) == 2, written                    # the picture and its type
    assert all(_indexed(p) for p in written) is planted, written
    assert snapshots.load_media(ws, snapshots.media_key(URL)) == (b"\x89PNG....", "image/png")
    assert snapshots.has_media(ws, URL)


def test_a_picture_the_old_code_saved_is_still_read_and_not_saved_again(tmp_path):
    ws = SimpleNamespace(path=str(tmp_path))
    h = snapshots.media_key(URL)
    old = tmp_path / "media" / h[:2]
    old.mkdir(parents=True)
    (old / (h + ".bin")).write_bytes(b"OLD")
    (old / (h + ".ct")).write_text("image/png", encoding="utf-8")
    assert snapshots.has_media(ws, URL)
    assert snapshots.load_media(ws, h) == (b"OLD", "image/png")
    assert snapshots.save_media(ws, URL, b"NEW", "image/png")["same"]
    assert not (tmp_path / ".media").exists()


def test_an_unknown_key_is_none(tmp_path):
    ws = SimpleNamespace(path=str(tmp_path))
    assert snapshots.load_media(ws, "0" * 40) is None
    assert snapshots.load_media(ws, "../etc") is None


# --- page forms, the same way (G-145, live: 18 `snapshots/` creations in 36 s)

HTML = "<html><body><h1>Title</h1>" + "".join(
    "<p>para %d with enough words to chunk</p>" % i for i in range(40)) + "</body></html>"
PAGE = "http://a.test/p"


def _form(i):
    return {"html": "<div><p>para %d</p></div>" % i, "bg": "", "color": "", "font": "",
            "elements": 1, "found": 1, "url": PAGE, "at": 1}


@pytest.mark.parametrize("planted", [False, True])
def test_a_new_page_form_is_written_where_obsidian_does_not_index(tmp_path, monkeypatch, planted):
    from domvec.workspace import Workspace
    monkeypatch.setattr(snapshots, "PLANT_SNAPSHOTS_IN_VAULT", [planted])
    with Workspace(tmp_path / "ws") as ws:
        ws.index_html(HTML, PAGE)
        cids = [c for (c,) in ws.store._rows("MATCH (c:Chunk {url: $u}) RETURN c.cid", {"u": PAGE})]
        got = snapshots.save(ws, [{"cid": c, "snap": _form(i)} for i, c in enumerate(cids)])
        assert got["written"] == len(cids) >= 2
        blobs = [p.relative_to(tmp_path) for p in (tmp_path / "ws").rglob("*.json.gz")]
        assert len(blobs) == len(cids)
        assert all(_indexed(p) for p in blobs) is planted, blobs
        assert snapshots.load(ws, cids[0])["html"] == _form(0)["html"]
        assert len(snapshots.load_page_forms(ws, PAGE)) == len(cids)


def test_a_page_form_the_old_code_saved_is_still_read_and_not_written_again(tmp_path, monkeypatch):
    from domvec.workspace import Workspace
    with Workspace(tmp_path / "ws") as ws:
        ws.index_html(HTML, PAGE)
        cid = ws.store._rows("MATCH (c:Chunk {url: $u}) RETURN c.cid LIMIT 1", {"u": PAGE})[0][0]
        monkeypatch.setattr(snapshots, "PLANT_SNAPSHOTS_IN_VAULT", [True])     # the old code writes it
        assert snapshots.save(ws, [{"cid": cid, "snap": _form(0)}])["written"] == 1
        monkeypatch.setattr(snapshots, "PLANT_SNAPSHOTS_IN_VAULT", [False])
        assert snapshots.load(ws, cid)["html"] == _form(0)["html"]
        assert snapshots.save(ws, [{"cid": cid, "snap": _form(0)}])["same"] == 1
        assert not (tmp_path / "ws" / ".snapshots").exists()
