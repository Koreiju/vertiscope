"""A cooperative GPU gate: background CUDA work yields while a model streams (G-385; PLUGIN_GOAL 171 c).

"ensure the models can stream continuously on CUDA unblocked by other GPU
processes." Measured (`build_analytics/agent_stream.json`, 2026-11-21): a 7B
Q4 model streams at 56.2 tok/s on an idle RTX 4070 Laptop GPU and at 19.8
tok/s while a second process embeds on CUDA -- the GPU time-slices between
processes, and the embedder takes two thirds of it. Windows' per-process GPU
priority is a system setting, not ours to change; so the embedder yields
instead.

Across processes with the standard library only: a streaming model keeps a
heartbeat file fresh (`streaming()`); GPU work calls `wait_while_streaming()`
before each batch and sleeps while the heartbeat is fresh -- bounded by
`max_wait_s`, so a scan's vectors are delayed, never starved. A crashed
streamer's heartbeat goes stale in `STALE_S` and releases the gate on its own.

Planted `PLANT_NO_GATE`: the embedder never waits.
"""

from __future__ import annotations

import os
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path

GATE = Path(os.environ.get("DOMVEC_GPU_GATE") or Path(tempfile.gettempdir()) / "domvec-gpu-stream.beat")
BEAT_S = 0.2
STALE_S = 1.0
PLANT_NO_GATE = [False]
STATS = {"waits": 0, "waited_s": 0.0, "gave_up": 0}


def streaming_now() -> bool:
    try:
        return time.time() - GATE.stat().st_mtime < STALE_S
    except OSError:
        return False


@contextmanager
def streaming():
    """Hold the gate for as long as the block runs (a model streaming)."""
    stop = threading.Event()

    def beat():
        while not stop.is_set():
            try:
                GATE.touch()
            except OSError:
                pass
            stop.wait(BEAT_S)

    t = threading.Thread(target=beat, name="domvec-gpu-gate", daemon=True)
    GATE.touch()
    t.start()
    try:
        yield
    finally:
        stop.set()
        t.join(1.0)
        try:
            GATE.unlink()
        except OSError:
            pass


def wait_while_streaming(max_wait_s: float = 30.0, poll_s: float = 0.05) -> float:
    """Sleep while a model streams; seconds waited. Bounded: never starves."""
    if PLANT_NO_GATE[0] or not streaming_now():
        return 0.0
    t0 = time.monotonic()
    while streaming_now():
        if time.monotonic() - t0 >= max_wait_s:
            STATS["gave_up"] += 1
            break
        time.sleep(poll_s)
    waited = time.monotonic() - t0
    STATS["waits"] += 1
    STATS["waited_s"] += waited
    return waited
