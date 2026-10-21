"""The sidecar's stall watchdog dumps every thread's stack when a request has
been in flight too long (2026-10-19: two silent stalls, no CPU, no log).
Non-vacuous: with no stalled request it writes nothing."""
import threading
import time

import vertiscope.obsidian.sidecar as sc


def _one_pass(tmp_path, monkeypatch, inflight):
    calls = {"n": 0}

    def sleep_once(_s):
        calls["n"] += 1
        if calls["n"] > 1:
            raise SystemExit
    monkeypatch.setattr(sc.time, "sleep", sleep_once)
    monkeypatch.setattr(sc, "_INFLIGHT", inflight)
    monkeypatch.setattr(sc, "_STALL_DUMPED", [0.0])
    try:
        sc._stall_watchdog(str(tmp_path), stall_s=5, every_s=0)
    except SystemExit:
        pass
    import faulthandler
    faulthandler.cancel_dump_traceback_later()
    p = tmp_path / "stacks.log"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def test_a_stalled_request_dumps_every_thread(tmp_path, monkeypatch):
    out = _one_pass(tmp_path, monkeypatch, {1: (time.time() - 60, "GET /sensor HTTP/1.1")})
    assert "GET /sensor" in out and "in flight" in out
    assert "Thread 0x" in out or "Current thread" in out


def test_nothing_stalled_writes_nothing(tmp_path, monkeypatch):
    assert _one_pass(tmp_path, monkeypatch, {1: (time.time(), "GET /health HTTP/1.1")}) == ""
