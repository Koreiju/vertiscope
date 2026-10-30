"""G-13: the projector's queue waits as long as a drain costs.

"Re-projections over umaps can be batched in a queue at a latency that
adapts to match the time scaling of the umap updates." No window until a
drain has been measured; then the measured cost, capped; planted
`PLANT_FIXED_BATCH`, none. A hover's `prioritize` skips it, and every queued
item carries the time it was queued so its wait can be reported.
"""

from domvec.obsidian import projector as P


def test_window_on_by_default_but_shut_for_a_burst():
    p = P.ChunkProjector()
    p.cost_ms = 120.0
    assert P.ADAPTIVE_WINDOW[0] is True
    assert p.batch_window_s() == 0.0                # no arrivals seen: not a trickle


def test_window_follows_measured_cost(monkeypatch):
    monkeypatch.setattr(P, "ADAPTIVE_WINDOW", [True])
    p = P.ChunkProjector()
    assert p.batch_window_s() == 0.0                # nothing measured yet
    p.recent_sizes.extend([1, 2, 1])                # a trickle
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


def test_window_opens_for_a_trickle_and_stays_shut_for_a_burst(monkeypatch):
    """2026-10-30: the window adapts to the arrivals. A burst (a page's chunks
    from the embedder, 90 a drain measured) never waits; a trickle (a live
    page's mutations) gathers for one drain's cost. Planted
    `PLANT_WINDOW_ALWAYS`: the burst waits too, as measured on 2026-10-24."""
    monkeypatch.setattr(P, "ADAPTIVE_WINDOW", [True])
    p = P.ChunkProjector()
    p.cost_ms = 300.0
    for n in (90, 96, 88):
        p.enqueue(["b%d-%d" % (n, i) for i in range(n)])
        p._take_batch()
    assert not p.trickling() and p.batch_window_s() == 0.0
    for i in range(8):
        p.enqueue(["t%d" % i])
        p._take_batch()
    assert p.trickling() and abs(p.batch_window_s() - 0.3) < 1e-9
    assert p.batching_status()["trickling"] is True


def test_planted_window_regardless_of_arrivals(monkeypatch):
    monkeypatch.setattr(P, "ADAPTIVE_WINDOW", [True])
    monkeypatch.setattr(P, "PLANT_WINDOW_ALWAYS", [True])
    p = P.ChunkProjector()
    p.cost_ms = 300.0
    for n in (90, 96, 88):
        p.enqueue(["b%d-%d" % (n, i) for i in range(n)])
        p._take_batch()
    assert p.batch_window_s() > 0                   # the burst waits: the defect
