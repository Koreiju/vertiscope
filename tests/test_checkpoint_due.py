"""The WAL is folded in while the reader is away, polls or not (2026-10-11:
249 MB unfolded through 2.8 idle hours, because the plugin's background polls
counted as activity). Planted: the old rule never folds under polling."""

from vertiscope.obsidian import sidecar as sc

MB = 1 << 20


def test_ceiling_always_and_small_wal_never():
    assert sc._checkpoint_due(300 * MB, 1000.0, 999.0, 999.9)
    assert not sc._checkpoint_due(1 * MB, 10_000.0, 0.0, 0.0)


def test_an_idle_reader_with_polling_gets_a_fold():
    now = 100_000.0
    # Last write 30 minutes ago; the plugin polled 3 s ago.
    assert sc._checkpoint_due(50 * MB, now, now - 1800, now - 3)
    # Polled a moment ago: still due -- the open pane polls about once a second.
    assert sc._checkpoint_due(50 * MB, now, now - 1800, now - 0.2)
    # The reader is browsing (a write a minute ago): never mid-session.
    assert not sc._checkpoint_due(50 * MB, now, now - 60, now - 3)


def test_planted_request_quiet_never_folds_under_polling(monkeypatch):
    monkeypatch.setattr(sc, "_PLANT_REQUEST_QUIET", [True])
    now = 100_000.0
    assert not sc._checkpoint_due(50 * MB, now, now - 1800, now - 3)
    # It still folds in a true silence.
    assert sc._checkpoint_due(50 * MB, now, now - 1800, now - 200)
