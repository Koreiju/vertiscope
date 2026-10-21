"""A sidecar that restarted under an open page refuses what it cannot decode
(2026-10-11). The page's sensor had sent its dictionary to the process that
died and now sends only additions; decoded against an empty one, ids landed
on the wrong segments and /header/tr[2]/b/small/i[88] reached the store for a
Wikipedia table row. Refused with `resync`, the plugin asks the sensor to send
everything again. Planted: `_PLANT_NO_RESYNC` decodes it anyway."""

import json
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from vertiscope.obsidian import sidecar as sc

PAYLOAD = json.loads((Path(__file__).parent / "fixtures" / "sensor_payload_small.json").read_text(encoding="utf-8"))
URL = PAYLOAD["url"]


@pytest.fixture()
def server(tmp_path):
    from vertiscope.workspace import Workspace
    with Workspace(tmp_path / "ws") as ws:
        srv = sc.serve(ws, port=0, block=False, capture=True)
        try:
            yield srv.server_address[1]
        finally:
            srv.shutdown(); srv.server_close()
            sc._capture_sessions.clear()


def _capture(port, payload):
    req = urllib.request.Request("http://127.0.0.1:%d/capture" % port,
                                 data=json.dumps({"url": URL, "payload": payload}).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


def _stale():
    # What a sensor sends after the sidecar restarted: none of its dictionary
    # (already sent to the old process), its full size still reported.
    return dict(PAYLOAD, dict=[], shapes=[])


def test_a_whole_dictionary_is_decoded(server):
    code, body = _capture(server, PAYLOAD)
    assert code == 200 and not body.get("error"), body


def test_a_dictionary_the_session_cannot_complete_is_refused_with_resync(server):
    code, body = _capture(server, _stale())
    assert code == 409 and body.get("resync") is True, body
    # After the sensor resyncs (its whole dictionary again), it is decoded.
    code, body = _capture(server, PAYLOAD)
    assert code == 200, body


def test_planted_no_resync_decodes_the_stale_payload(server, monkeypatch):
    monkeypatch.setattr(sc, "_PLANT_NO_RESYNC", [True])
    code, body = _capture(server, _stale())
    assert code == 200
