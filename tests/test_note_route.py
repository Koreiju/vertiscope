"""G-7: a vault note into the store through `/note`, its links page links.

A note a reader wrote a retrieval link into is indexed as a page
(`vault://<vault>/<path>`), relinked, and its link to another page comes back
as a page link -- the edge the 3D graph draws. Gated as a capture: refused
when capture is off, and from anything but the plugin when the sidecar takes
the plugin's captures only (`D-39`).
"""
import json
import urllib.error
import urllib.request

import pytest

from domvec.obsidian import sidecar as sc
from domvec.workspace import Workspace


def _post(base, body, plugin=True):
    headers = {"Content-Type": "application/json"}
    if plugin:
        headers["X-Domvec-Client"] = "obsidian-plugin"
    req = urllib.request.Request(base + "/note", data=json.dumps(body).encode(), method="POST", headers=headers)
    return json.load(urllib.request.urlopen(req, timeout=60))


def test_a_note_s_link_becomes_a_page_link(tmp_path):
    with Workspace(tmp_path) as ws:
        srv = sc.serve(ws, port=0, block=False, capture=True, plugin_captures_only=True)
        base = "http://127.0.0.1:%d" % srv.server_address[1]
        try:
            _post(base, {"path": "notes/Lattice.md", "text": "# Lattice\n\nProse about lattices.\n", "vault": "v"})
            got = _post(base, {"path": "notes/Spindle.md", "vault": "v",
                               "text": "# Spindle\n\nSee [the lattice](Lattice.md) for more.\n"})
            assert got["url"] == "vault://v/notes/Spindle.md" and got["chunks"] >= 1
            assert "vault://v/notes/Lattice.md" in got["links"], got
            # Not from the plugin: refused, nothing written.
            with pytest.raises(urllib.error.HTTPError) as e:
                _post(base, {"path": "notes/Other.md", "text": "# Other\n", "vault": "v"}, plugin=False)
            assert e.value.code == 403
        finally:
            srv.shutdown()


def test_refused_when_capture_is_off(tmp_path):
    with Workspace(tmp_path) as ws:
        srv = sc.serve(ws, port=0, block=False, capture=False)
        base = "http://127.0.0.1:%d" % srv.server_address[1]
        try:
            with pytest.raises(urllib.error.HTTPError) as e:
                _post(base, {"path": "a.md", "text": "# A\n", "vault": "v"})
            assert e.value.code == 403
        finally:
            srv.shutdown()
