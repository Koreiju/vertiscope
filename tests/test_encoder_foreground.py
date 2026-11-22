"""An interactive encode waits at most one slice of the background batch (D-40).

`/project` (the chunks streaming into the 3D view, placed before the store
holds them) shared `_ENCODER_LOCK` with the background embedder, which held it
for a whole batch: 2026-11-22 one `/project` waited 682 s. A stand-in encoder
at 10 ms a text: a 64-text batch is ~0.64 s; a 16-text slice ~0.16 s.
Planted PLANT_ENCODER_BATCH_HOLD: the foreground waits out the batch.
"""

import threading
import time

import pytest

from domvec.obsidian import sidecar as sc


class _Queue:
    def __init__(self):
        self.back = []

    def requeue(self, items):
        self.back.extend(items)


class _Ws:
    def __init__(self, per_text=0.01, fail_at=None):
        self.per_text, self.fail_at, self.calls = per_text, fail_at, 0
        self.vectors = _Queue()

    def encode_taken(self, items):
        self.calls += 1
        if self.fail_at is not None and self.calls == self.fail_at:
            raise RuntimeError("encoder died")
        time.sleep(self.per_text * len(items))
        return {cid: [1.0] for cid, _md in items}


ITEMS = [("c%d" % i, "text %d" % i) for i in range(64)]


def _foreground_wait(planted, monkeypatch):
    monkeypatch.setattr(sc, "PLANT_ENCODER_BATCH_HOLD", [planted])
    ws = _Ws()
    out = {}
    bg = threading.Thread(target=lambda: out.update(sc._encode_sliced(ws, ITEMS)))
    bg.start()
    time.sleep(0.05)                                  # mid-slice / mid-batch
    t0 = time.perf_counter()
    with sc._foreground_encoder():
        waited = time.perf_counter() - t0
    bg.join(5)
    assert len(out) == 64                             # nothing lost either way
    return waited


def test_foreground_waits_one_slice_at_most(monkeypatch):
    waited = _foreground_wait(False, monkeypatch)
    assert waited < 0.30, waited


def test_planted_batch_hold_waits_out_the_batch(monkeypatch):
    waited = _foreground_wait(True, monkeypatch)
    assert waited > 0.45, waited


def test_failed_slice_requeues_the_rest(monkeypatch):
    monkeypatch.setattr(sc, "PLANT_ENCODER_BATCH_HOLD", [False])
    ws = _Ws(per_text=0.0, fail_at=2)
    with pytest.raises(RuntimeError):
        sc._encode_sliced(ws, ITEMS)
    # Slice 2 is requeued by VectorQueue.embed itself; slices 3 and 4 here.
    assert [c for c, _ in ws.vectors.back] == [c for c, _ in ITEMS[32:]]
