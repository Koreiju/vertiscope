"""Only the plugin's browser cell writes the reader's store (`D-39`: probe
pages leaked into the working store and were drawn among the reader's).
Planted: a sidecar without the guard takes a probe's capture."""

import json
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from vertiscope.obsidian import sidecar as sc

PAYLOAD = json.loads((Path(__file__).parent / "fixtures" / "sensor_payload_small.json").read_text(encoding="utf-8"))


def _post(port, headers):
    req = urllib.request.Request("http://127.0.0.1:%d/capture" % port,
                                 data=json.dumps({"url": PAYLOAD["url"], "payload": PAYLOAD}).encode(),
                                 headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


@pytest.fixture(params=[True, False], ids=["guarded", "planted-unguarded"])
def server(tmp_path, request):
    from vertiscope.workspace import Workspace
    with Workspace(tmp_path / "ws") as ws:
        srv = sc.serve(ws, port=0, block=False, capture=True, plugin_captures_only=request.param)
        try:
            yield request.param, srv.server_address[1]
        finally:
            srv.shutdown(); srv.server_close()
            sc._capture_sessions.clear()


def test_a_probe_cannot_write_the_readers_store(server):
    guarded, port = server
    code, body = _post(port, {})
    if guarded:
        assert code == 403 and "D-39" in body.get("why", "")
    else:
        assert code == 200           # the leak, as it was


def test_the_plugin_still_captures(server):
    _guarded, port = server
    code, body = _post(port, {"X-Vertiscope-Client": "obsidian-plugin"})
    assert code == 200 and not body.get("error"), body


def test_the_preflight_lets_the_plugins_header_through(server):
    """The plugin runs on Obsidian's app origin, so its header triggers a CORS
    preflight. Without the header in Allow-Headers every capture failed with
    "Failed to fetch" (2026-10-11, live for nine minutes; urllib never sends a
    preflight, so the tests above could not see it)."""
    _guarded, port = server
    req = urllib.request.Request("http://127.0.0.1:%d/capture" % port, method="OPTIONS",
                                 headers={"Origin": "app://obsidian.md",
                                          "Access-Control-Request-Method": "POST",
                                          "Access-Control-Request-Headers": "content-type,x-vertiscope-client"})
    with urllib.request.urlopen(req, timeout=30) as r:
        allowed = r.headers.get("Access-Control-Allow-Headers", "").lower()
    assert "x-vertiscope-client" in allowed and "content-type" in allowed
