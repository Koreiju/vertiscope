"""G-385: the cooperative GPU gate (domvec/gpu_gate.py). No GPU needed.

Planted `PLANT_NO_GATE`: the waiter never waits while a stream holds the gate."""

import threading
import time

import pytest

from domvec import gpu_gate as gg


@pytest.fixture(autouse=True)
def private_gate(tmp_path, monkeypatch):
    monkeypatch.setattr(gg, "GATE", tmp_path / "beat")
    yield
    gg.PLANT_NO_GATE[0] = False


def test_no_stream_no_wait():
    assert not gg.streaming_now() and gg.wait_while_streaming() == 0.0


def test_the_waiter_waits_for_the_stream_to_end():
    def stream():
        with gg.streaming():
            time.sleep(0.6)
    t = threading.Thread(target=stream)
    t.start()
    time.sleep(0.1)
    waited = gg.wait_while_streaming()
    t.join()
    assert 0.3 < waited < 1.5 and not gg.streaming_now()


def test_the_wait_is_bounded():
    with gg.streaming():
        waited = gg.wait_while_streaming(max_wait_s=0.3)
    assert 0.25 < waited < 0.8


def test_a_dead_streamers_heartbeat_goes_stale():
    gg.GATE.touch()                        # a streamer that crashed without cleaning up
    assert gg.streaming_now()
    time.sleep(gg.STALE_S + 0.1)
    assert not gg.streaming_now() and gg.wait_while_streaming() == 0.0


def test_planted_no_gate_does_not_wait():
    gg.PLANT_NO_GATE[0] = True
    with gg.streaming():
        assert gg.wait_while_streaming() == 0.0
