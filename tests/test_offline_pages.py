"""The page for when there is no connection (`G-60`..`G-62`): saved as the
cell presented it, rebuilt from the scan trace, and the infill rule between
them -- a saved page that holds too little of the trace opens INFILLED: its
own layout kept, the traced chunks it lacks drawn into it. Planted: an infill
threshold of 0 (the thin page opens bare), and the first cut that threw the
saved page away for the trace."""

import email
import quopri

from vertiscope.obsidian import offline, snapshots
from vertiscope.workspace import Workspace

URL = "http://offline.test/okapi"
HTML = ("<html><body><h1>Okapi</h1>" + "".join(
    "<p>The okapi paragraph %d describes ossicones and stripes in detail</p>" % i for i in range(30))
    + "<p><img src='http://offline.test/okapi.jpg' alt='An okapi'></p></body></html>")


def _ws(tmp_path):
    ws = Workspace(tmp_path / "ws")
    ws.__enter__()
    ws.index_html(HTML, URL)
    return ws


def test_a_full_saved_page_opens_and_a_thin_one_is_infilled_from_the_trace(tmp_path):
    ws = _ws(tmp_path)
    try:
        assert offline.page_info(ws, URL)["opens"] == "traced"          # nothing saved yet
        full = " ".join("The okapi paragraph %d describes ossicones and stripes in detail" % i for i in range(30))
        assert offline.save_page(ws, URL, b"MIME-Version: 1.0\r\n...", "Okapi " + full)["saved"]
        info = offline.page_info(ws, URL)
        assert info["saved"] and info["coverage"] >= 0.9 and info["opens"] == "saved"
        assert offline.load_page(ws, URL).startswith(b"MIME-Version")
        # The page's source did not carry its layout: two words of it.
        offline.save_page(ws, URL, b"MIME-Version: 1.0\r\n...", "Okapi stripes")
        info = offline.page_info(ws, URL)
        assert info["coverage"] < 0.5 and info["opens"] == "infilled"
    finally:
        ws.__exit__(None, None, None)


def test_planted_no_infill_opens_the_thin_page(tmp_path, monkeypatch):
    ws = _ws(tmp_path)
    try:
        monkeypatch.setattr(offline, "INFILL_BELOW", 0.0)
        offline.save_page(ws, URL, b"MIME-Version: 1.0\r\n...", "Okapi stripes")
        assert offline.page_info(ws, URL)["opens"] == "saved"
    finally:
        ws.__exit__(None, None, None)


def test_the_trace_alone_draws_the_page_with_its_pictures(tmp_path):
    ws = _ws(tmp_path)
    try:
        snapshots.save_media(ws, "http://offline.test/okapi.jpg", b"\xff\xd8\xff\xe0JPEG", "image/jpeg")
        got = offline.reconstruct(ws, URL)
        html = got["html"]
        assert got["chunks"] >= 1 and got["markdown"] + got["forms"] == got["chunks"]
        assert "<h1>Okapi</h1>" in html and "ossicones" in html
        assert "data:image/jpeg;base64," in html            # renders with nothing reachable
        assert "http://offline.test/okapi.jpg" not in html.split("<body>")[1].split("dv-banner")[0]
    finally:
        ws.__exit__(None, None, None)


def test_the_routes_save_describe_and_serve_both_forms(tmp_path):
    """Through HTTP, as the plugin reaches them (a route's NameError is
    invisible to the module tests above)."""
    import base64, json, urllib.request, urllib.parse
    from vertiscope.obsidian import sidecar as sc
    ws = _ws(tmp_path)
    srv = sc.serve(ws, port=0, block=False)
    try:
        port = srv.server_address[1]
        q = urllib.parse.quote(URL, safe="")
        body = json.dumps({"mhtml_b64": base64.b64encode(b"MIME-Version: 1.0\r\n").decode(), "text": "Okapi stripes"}).encode()
        req = urllib.request.Request("http://127.0.0.1:%d/offline?url=%s" % (port, q), data=body,
                                     headers={"Content-Type": "application/json"})
        assert json.load(urllib.request.urlopen(req, timeout=60))["saved"]
        info = json.load(urllib.request.urlopen("http://127.0.0.1:%d/offline?url=%s" % (port, q), timeout=60))
        assert info["saved"] and info["opens"] == "infilled"    # two words: infilled from the trace
        inf = urllib.request.urlopen("http://127.0.0.1:%d/offline/infilled?url=%s" % (port, q), timeout=60).read()
        assert inf.startswith(b"MIME-Version")
        traced = urllib.request.urlopen("http://127.0.0.1:%d/offline/traced?url=%s" % (port, q), timeout=60)
        assert traced.headers["Content-Type"].startswith("text/html") and b"ossicones" in traced.read()
        # The store moves under these forms: never cached (a day-old traced
        # page opened in the cell, 2026-10-11).
        assert traced.headers["Cache-Control"] == "no-store"
        saved = urllib.request.urlopen("http://127.0.0.1:%d/offline/saved?url=%s" % (port, q), timeout=60).read()
        assert saved.startswith(b"MIME-Version")
    finally:
        srv.shutdown(); srv.server_close()
        ws.__exit__(None, None, None)


def _mhtml(body_html: str) -> bytes:
    """A page as Chromium serialises it: multipart/related, the document first,
    quoted-printable, CRLF; one picture after it."""
    qp = quopri.encodestring(body_html.encode("utf-8")).replace(b"\n", b"\r\n")
    return (b'From: <Saved by Blink>\r\nMIME-Version: 1.0\r\nContent-Type: multipart/related;\r\n'
            b'\ttype="text/html";\r\n\tboundary="----B----"\r\n\r\n\r\n'
            b'------B----\r\nContent-Type: text/html\r\nContent-Transfer-Encoding: quoted-printable\r\n'
            b'Content-Location: ' + URL.encode() + b'\r\n\r\n' + qp + b'\r\n'
            b'------B----\r\nContent-Type: image/png\r\nContent-Transfer-Encoding: base64\r\n'
            b'Content-Location: http://offline.test/p.png\r\n\r\niVBORw0KGgo=\r\n\r\n------B------\r\n')


def _parts(raw: bytes):
    return email.message_from_bytes(raw).get_payload()


def test_a_thin_saved_page_keeps_its_layout_and_gains_only_what_it_lacks(tmp_path):
    ws = _ws(tmp_path)
    try:
        # The saved page laid out the heading and its picture; the paragraphs
        # were behind a "show more" the page never opened.
        shown = "<html><body><h1>Okapi</h1><p><img alt='An okapi'></p></body></html>"
        raw = _mhtml(shown)
        offline.save_page(ws, URL, raw, "Okapi An okapi")
        info = offline.page_info(ws, URL)
        assert info["opens"] == "infilled", info
        got = offline.infill(ws, URL)
        assert got["placed"]
        parts, before = _parts(got["mhtml"]), _parts(raw)
        doc = parts[0].get_payload(decode=True).decode("utf-8")
        assert doc.startswith("<html><body><h1>Okapi</h1><p><img")   # its own layout, untouched
        assert "dv-infill" in doc and doc.index("dv-infill") < doc.index("</body>")
        added = doc[doc.index("dv-infill"):]
        assert got["added"] >= 1 and "infilled from the scan trace" in added
        assert "ossicones" in added and "ossicones" not in doc[:doc.index("dv-infill")]
        # Everything but the document is byte-for-byte as saved.
        assert len(parts) == len(before) == 2
        assert parts[1].get_payload(decode=True) == before[1].get_payload(decode=True)
    finally:
        ws.__exit__(None, None, None)


def test_a_whole_saved_page_gains_nothing(tmp_path):
    """Null arm: the same page saved whole has no chunk it lacks."""
    ws = _ws(tmp_path)
    try:
        full = " ".join("The okapi paragraph %d describes ossicones and stripes in detail" % i for i in range(30))
        offline.save_page(ws, URL, _mhtml("<html><body><p>%s</p></body></html>" % full), "Okapi An okapi " + full)
        assert offline.page_info(ws, URL)["opens"] == "saved"
        assert offline.infill(ws, URL)["added"] == 0
    finally:
        ws.__exit__(None, None, None)


def test_planted_replace_throws_the_saved_page_away(tmp_path, monkeypatch):
    ws = _ws(tmp_path)
    try:
        monkeypatch.setattr(offline, "PLANT_REPLACE_NOT_INFILL", True)
        offline.save_page(ws, URL, _mhtml("<html><body><p>Okapi stripes</p></body></html>"), "Okapi stripes")
        assert offline.page_info(ws, URL)["opens"] == "traced"
    finally:
        ws.__exit__(None, None, None)


_ERROR_PAGE = (b"From: <Saved by Blink>\r\nSnapshot-Content-Location: chrome-error://chromewebdata/\r\n"
               b"MIME-Version: 1.0\r\nContent-Type: multipart/related;\r\n\ttype=\"text/html\";\r\n"
               b"\tboundary=\"----E----\"\r\n\r\n\r\n------E----\r\nContent-Type: text/html\r\n\r\n"
               b"<html><body></body></html>\r\n------E------\r\n")


def test_chromiums_error_page_is_not_the_page(tmp_path):
    """A failed load serialised `chrome-error://` as Axolotl (744 bytes), and
    that opened as Axolotl. Refused when saved; ignored if already on disk."""
    ws = _ws(tmp_path)
    try:
        got = offline.save_page(ws, URL, _ERROR_PAGE, "")
        assert not got["saved"] and "chrome-error" in got["why"]
        # One written before the refusal existed: kept, never opened.
        root = tmp_path / "ws" / "offline_pages"
        root.mkdir(parents=True, exist_ok=True)
        (root / (offline.page_key(URL) + ".mhtml")).write_bytes(_ERROR_PAGE)
        (root / (offline.page_key(URL) + ".json")).write_text('{"url": "%s", "text": ""}' % URL)
        info = offline.page_info(ws, URL)
        assert info["opens"] == "traced" and not info["saved"] and info["rejected"].startswith("chrome-error")
        # A real page's snapshot location passes.
        assert offline.is_the_page(b"Snapshot-Content-Location: https://en.wikipedia.org/wiki/Okapi\r\n")
    finally:
        ws.__exit__(None, None, None)


def test_planted_any_snapshot_opens_the_error_page(tmp_path, monkeypatch):
    ws = _ws(tmp_path)
    try:
        monkeypatch.setattr(offline, "PLANT_ANY_SNAPSHOT", True)
        assert offline.save_page(ws, URL, _ERROR_PAGE, "")["saved"]
        assert offline.page_info(ws, URL)["opens"] == "infilled"
    finally:
        ws.__exit__(None, None, None)
