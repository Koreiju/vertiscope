"""G-385: the chat cell's `/chat_stream` streams the CUDA model, token by token.

Always: the route's plumbing with the model stubbed -- each piece reaches the
client as its own chunk, and `engine`/planted `PLANT_CHAT_GPT4ALL` pick the
old GPT4All path. Live (`DOMVEC_LIVE=1`): the real Hermes GGUF on CUDA through
HTTP, time to first byte and the gap between pieces.
"""

import http.client
import json
import os
import time

import pytest

from domvec import chat_cuda
from domvec.obsidian import sidecar as sc


@pytest.fixture()
def server(tmp_path):
    from domvec.workspace import Workspace
    with Workspace(tmp_path / "ws") as ws:
        srv = sc.serve(ws, port=0, block=False, capture=True)
        try:
            yield srv.server_address[1]
        finally:
            srv.shutdown(); srv.server_close()
            sc.PLANT_CHAT_GPT4ALL[0] = False


def _stream(port, body):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=300)
    t0 = time.perf_counter()
    c.request("POST", "/chat_stream", body=json.dumps(body), headers={"Content-Type": "application/json"})
    r = c.getresponse()
    stamps, pieces = [], []
    while True:
        b = r.read1(4096)
        if not b:
            break
        stamps.append(time.perf_counter() - t0)
        pieces.append(b.decode("utf-8", "replace"))
    c.close()
    return r.status, pieces, stamps


def test_each_piece_arrives_as_it_is_made(server, monkeypatch):
    def slow(text, max_tokens=400):
        for p in ("one ", "two ", "three"):
            time.sleep(0.15)
            yield p
    monkeypatch.setattr(chat_cuda, "stream", slow)
    status, pieces, stamps = _stream(server, {"prompt": "hi"})
    assert status == 200 and "".join(pieces) == "one two three"
    assert len(pieces) == 3                                   # not buffered into one write
    assert stamps[1] - stamps[0] > 0.1 and stamps[2] - stamps[1] > 0.1


def test_engine_gpt4all_takes_the_old_path(server, monkeypatch):
    called = []
    monkeypatch.setattr(chat_cuda, "stream", lambda *a, **k: called.append(1) or iter(["x"]))
    # dry_ms: the route's own no-model turn, so the old path runs without loading GPT4All
    status, pieces, _ = _stream(server, {"prompt": "hi", "engine": "gpt4all", "dry_ms": 120})
    assert status == 200 and called == [] and set("".join(pieces)) == {"."}


def test_planted_flag_makes_gpt4all_the_default(server, monkeypatch):
    sc.PLANT_CHAT_GPT4ALL[0] = True
    called = []
    monkeypatch.setattr(chat_cuda, "stream", lambda *a, **k: called.append(1) or iter(["x"]))
    _stream(server, {"prompt": "hi", "dry_ms": 60})
    assert called == []


@pytest.mark.skipif(os.environ.get("DOMVEC_LIVE") != "1", reason="live: loads the 7B GGUF on CUDA")
def test_live_hermes_on_cuda_streams_in_real_time(server):
    _stream(server, {"prompt": "Say hello.", "max_tokens": 8})          # load + warm
    status, pieces, stamps = _stream(server, {"prompt": "Name three uses of a radix trie, one line each.",
                                              "max_tokens": 120})
    gaps = sorted(b - a for a, b in zip(stamps, stamps[1:]))
    assert status == 200 and len(pieces) > 20 and chat_cuda.loaded_on() == "cuda"
    assert stamps[0] < 1.0                                    # first byte within a second, warm
    assert gaps[int(0.5 * (len(gaps) - 1))] < 0.05            # median gap under 50 ms
    print(json.dumps({"first_byte_s": round(stamps[0], 3), "pieces": len(pieces),
                      "gap_p50_ms": round(gaps[len(gaps) // 2] * 1000, 1),
                      "gap_max_ms": round(gaps[-1] * 1000, 1)}))
