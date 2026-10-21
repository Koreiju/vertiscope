"""PLUGIN_GOAL 186k / 2026-10-18 ("prompt the user before applying a download
on-click"): the download route fetches NOTHING without the reader's
confirmation, and with it fetches to the kind's destination. Against a local
fixture server only."""
import http.server, json, threading, time, urllib.error, urllib.request
from pathlib import Path

import pytest

import vertiscope.obsidian.sidecar as sc
from vertiscope.workspace import Workspace

CSV = b"name,price\napple,1\npear,2\n"


@pytest.fixture()
def files():
    class H(http.server.BaseHTTPRequestHandler):
        def do_HEAD(self):
            self.send_response(200)
            self.send_header("Content-Length", str(len(CSV)))
            self.send_header("Content-Type", "text/csv")
            self.end_headers()

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", str(len(CSV)))
            self.end_headers()
            self.wfile.write(CSV)

        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield "http://127.0.0.1:%d" % srv.server_address[1]
    srv.shutdown()


def _post(base, path, body):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=10)


def test_head_reports_size_without_fetching(files):
    got = sc._file_head(files + "/prices.csv")
    assert got["size"] == len(CSV) and got["type"] == "text/csv"


def test_unconfirmed_is_refused_and_confirmed_lands_in_the_workspace(files, tmp_path):
    sc._DOWNLOADS.clear()
    with Workspace(tmp_path) as ws:
        srv = sc.serve(ws, port=0, block=False)
        base = "http://127.0.0.1:%d" % srv.server_address[1]
        try:
            href = files + "/prices.csv"
            # No confirmation: refused, nothing started, nothing on disk.
            with pytest.raises(urllib.error.HTTPError) as e:
                _post(base, "/download", {"href": href, "kind": "table", "name": "prices.csv"})
            assert e.value.code == 400
            assert href not in sc._DOWNLOADS
            assert not (Path(ws.path) / "downloads" / "prices.csv").exists()
            # Confirmed: fetched to the workspace's downloads/.
            _post(base, "/download", {"href": href, "kind": "table", "name": "prices.csv", "confirmed": True})
            for _ in range(50):
                st = json.load(urllib.request.urlopen(base + "/download_status?href=" + urllib.parse.quote(href, safe=""), timeout=10))
                if st.get("state") != "running":
                    break
                time.sleep(0.1)
            assert st["state"] == "done", st
            assert Path(st["path"]).read_bytes() == CSV
            assert Path(st["path"]).parent == Path(ws.path) / "downloads"
        finally:
            srv.shutdown()
