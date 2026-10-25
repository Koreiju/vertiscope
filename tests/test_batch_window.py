"""G-13: the projector's queue waits as long as a drain costs.

"Re-projections over umaps can be batched in a queue at a latency that
adapts to match the time scaling of the umap updates." No window until a
drain has been measured; then the measured cost, capped; planted
`PLANT_FIXED_BATCH`, none. A hover's `prioritize` skips it, and every queued
item carries the time it was queued so its wait can be reported.
"""

from domvec.obsidian import projector as P


def test_window_off_by_default_measured_too_slow():
    p = P.ChunkProjector()
    p.cost_ms = 120.0
    assert p.batch_window_s() == 0.0                # off: it cost latency for no batching


def test_window_follows_measured_cost(monkeypatch):
    monkeypatch.setattr(P, "ADAPTIVE_WINDOW", [True])
    p = P.ChunkProjector()
    assert p.batch_window_s() == 0.0                # nothing measured yet
    p.cost_ms = 120.0
    assert abs(p.batch_window_s() - 0.12) < 1e-9
    p.cost_ms = 5000.0
    assert p.batch_window_s() == P.WINDOW_CAP_S     # a dear drain waits no longer than the cap
    P.PLANT_FIXED_BATCH[0] = True
    try:
        assert p.batch_window_s() == 0.0
    finally:
        P.PLANT_FIXED_BATCH[0] = False


def test_queue_times_and_hover_urgency():
    p = P.ChunkProjector()
    assert p.enqueue(["a", "b"]) == 2
    assert all(isinstance(t, float) for t in p.queue.values())
    p.prioritize(["b"])
    assert list(p.queue)[0] == "b" and p.urgent
    batch = p._take_batch()
    assert batch == ["b", "a"] and not p.queue
    assert len(p.window_stats["waits_ms"]) == 2
    st = p.batching_status()
    assert st["waits"] == 2 and st["fixed"] is False
