"""`/page_spread`: is one page's cloud collapsed, and is the cause its inputs or its fit?

G-94 (2026-11-15) found Radix_tree's 40 chunks and its page row placed within
0.045 units of one point, and 6 of 49 sampled pages below 0.5 against a
median of 4.2. Two causes look the same on screen and differ in what to fix:
the page's VECTORS are (near-)identical -- a fallback embedding, a capture of
one repeated block -- or the vectors are distinct and the FIT put them on one
point. The route reports both sides, and each case below is planted so that
the reading it must give cannot be the reading of the clean case.
"""
import json
import threading
import urllib.request

import numpy as np

from domvec.obsidian import projector as pj
from domvec.obsidian import sidecar as sc
from domvec.workspace import Workspace


class _Proj:
    def __init__(self, url, vecs, pos, page_pos):
        self.lock = threading.RLock()
        self.by_url = {url: set(vecs)}
        self.vec = dict(vecs)
        self.pos = dict(pos)
        self.page_pos = {url: page_pos}
        self.projection = object()


def _ask(base, url):
    req = urllib.request.Request(base + "/page_spread", data=json.dumps({"url": url}).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=30))


def _serve_with(tmp_path, monkeypatch, proj):
    monkeypatch.setattr(pj, "projector", lambda: proj)
    ws = Workspace(tmp_path)
    srv = sc.serve(ws, port=0, block=False, capture=False)
    return ws, srv, "http://127.0.0.1:%d" % srv.server_address[1]


def _case(tmp_path, monkeypatch, vecs, pos, page_pos):
    url = "https://example.test/page"
    ws, srv, base = _serve_with(tmp_path, monkeypatch, _Proj(url, vecs, pos, page_pos))
    try:
        return _ask(base, url)
    finally:
        srv.shutdown()
        ws.close()


def _distinct(n, dim=32, seed=0):
    g = np.random.default_rng(seed)
    return {"c%02d" % i: g.normal(size=dim).astype(np.float32).tolist() for i in range(n)}


def test_a_healthy_page_reads_spread(tmp_path, monkeypatch):
    vecs = _distinct(12)
    g = np.random.default_rng(1)
    pos = {c: (g.normal(size=3) * 5.0).tolist() for c in vecs}
    got = _case(tmp_path, monkeypatch, vecs, pos, [0.0, 0.0, 0.0])
    assert got["with_vector"] == 12 and got["distinct_vectors"] == 12, got
    assert got["cos_mean"] < 0.5, got
    assert got["pos_spread"] > 2.0, got


def test_planted_fit_collapse_reads_distinct_inputs_and_no_spread(tmp_path, monkeypatch):
    # Distinct vectors, every position within a few hundredths of one point:
    # the FIT collapsed, not the inputs.
    vecs = _distinct(12)
    g = np.random.default_rng(2)
    pos = {c: (np.array([-121.0, -207.3, 163.0]) + g.normal(size=3) * 0.02).tolist() for c in vecs}
    got = _case(tmp_path, monkeypatch, vecs, pos, [-121.0, -207.4, 163.1])
    assert got["distinct_vectors"] == 12 and got["cos_mean"] < 0.5, got
    assert got["pos_spread"] < 0.1, got
    assert got["page_to_centroid"] < 0.5, got


def test_planted_input_collapse_reads_one_vector(tmp_path, monkeypatch):
    # Every chunk carries the same vector (a fallback embedding): the inputs
    # collapsed, whatever the fit then does with them.
    one = _distinct(1)["c00"]
    vecs = {"c%02d" % i: list(one) for i in range(12)}
    pos = {c: [0.0, 0.0, 0.0] for c in vecs}
    got = _case(tmp_path, monkeypatch, vecs, pos, [0.0, 0.0, 0.0])
    assert got["distinct_vectors"] == 1 and got["cos_mean"] > 0.999, got
    assert got["pos_spread"] < 1e-6, got


def test_zero_vectors_are_counted(tmp_path, monkeypatch):
    vecs = _distinct(6)
    vecs.update({"z%d" % i: [0.0] * 32 for i in range(3)})
    got = _case(tmp_path, monkeypatch, vecs, {}, None)
    assert got["zero_vectors"] == 3 and got["with_pos"] == 0 and got["page_pos"] is None, got
