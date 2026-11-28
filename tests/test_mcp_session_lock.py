"""Tests for `domvec.obsidian.session_lock` & `DomvecMCP` single-instance concurrency (`G-455`)."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

from domvec.obsidian.mcp import DomvecMCP
from domvec.obsidian.session_lock import (
    SessionBusyError,
    call_with_lease,
    lock_status,
    run_contention_selftest,
    session_lease,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_two_process_contention_waits_cleanly_and_planted_arm_is_caught():
    clean = run_contention_selftest(plant_no_lock=False)
    assert clean["short_busy"] is True
    assert clean["short_holder_op"] == "peer-confirm"
    assert clean["overlapped_with_holder"] is False
    assert clean["resumed_waited_s"] >= 0.35
    assert clean["released_after"] is True

    # Non-vacuity arm: planted `no-session-lock` fails to block/serialize.
    planted = run_contention_selftest(plant_no_lock=True)
    assert planted["short_busy"] is False
    assert planted["overlapped_with_holder"] is True
    assert planted["resumed_waited_s"] == 0.0


def test_reentrant_in_same_thread_and_kernel_releases_on_killed_holder(tmp_path: Path):
    with session_lease("outer", detail="G-455", wait_s=1.0, lock_dir=tmp_path) as outer:
        assert outer["reentrant"] is False
        st = lock_status(tmp_path)
        assert st["busy"] is True and st["self_held"] is True and st["op"] == "outer"
        with session_lease("inner", wait_s=0.1, lock_dir=tmp_path) as inner:
            assert inner["reentrant"] is True
    assert lock_status(tmp_path)["busy"] is False

    # Spawn a subprocess holding the OS lock, then hard-kill it: Windows/POSIX
    # kernel must release byte 0 immediately so `lock_status` reports free.
    env = dict(os.environ, PYTHONPATH=str(REPO_ROOT))
    proc = subprocess.Popen(
        [sys.executable, "-m", "domvec.obsidian.session_lock",
         "--lock-dir", str(tmp_path), "--hold", "30", "--op", "crashed-peer"],
        cwd=str(REPO_ROOT),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        line = proc.stdout.readline()
        assert "holding" in line
        assert lock_status(tmp_path)["busy"] is True
        proc.kill()
        proc.wait(timeout=5.0)
        # Kernel closes handle table -> lock must immediately test free despite leftover .json!
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and lock_status(tmp_path)["busy"]:
            time.sleep(0.05)
        assert lock_status(tmp_path)["busy"] is False
        res = call_with_lease("after-crash", lambda: {"ok": True}, wait_s=0.2, lock_dir=tmp_path)
        assert res == {"ok": True}
    finally:
        if proc.poll() is None:
            proc.kill()


def test_mcp_serializes_mutating_tools_while_read_tools_stay_lock_free(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DOMVEC_LOCK_DIR", str(tmp_path))
    server = DomvecMCP()
    server.handlers["search"] = lambda a: {"query": a["query"], "hits": [], "count": 0}
    server.handlers["ui_act"] = lambda a: {"ok": True, "gesture": a["gesture"]}

    init_reply = server.handle({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-11-25", "clientInfo": {"name": "claude-code"}},
    })
    assert init_reply["result"]["protocolVersion"] == "2025-11-25"

    # Hold the shared lock in a sibling subprocess to simulate the other agent.
    env = dict(os.environ, PYTHONPATH=str(REPO_ROOT), DOMVEC_MCP_CLIENT="antigravity")
    holder = subprocess.Popen(
        [sys.executable, "-m", "domvec.obsidian.session_lock",
         "--lock-dir", str(tmp_path), "--hold", "1.2", "--op", "confirm", "--detail", "G-453"],
        cwd=str(REPO_ROOT),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        assert "holding" in holder.stdout.readline()

        # 1. Read-only `search` runs lock-free immediately while `confirm` holds the lock!
        t0 = time.monotonic()
        s_reply = server.handle({
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "search", "arguments": {"query": "patricia"}},
        })
        assert (time.monotonic() - t0) < 0.3
        assert json.loads(s_reply["result"]["content"][0]["text"])["query"] == "patricia"

        # 2. Mutating `ui_act` with short `session_wait_s` deliberately returns `busy: True`!
        b_reply = server.handle({
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "ui_act", "arguments": {"gesture": "open", "arg": "graph", "session_wait_s": 0.08}},
        })
        b_payload = json.loads(b_reply["result"]["content"][0]["text"])
        assert b_payload["busy"] is True
        assert b_payload["ok"] is False
        assert b_payload["session_lock"]["op"] == "confirm"

        # 3. Mutating `ui_act` with sufficient `session_wait_s` waits for peer and succeeds!
        ok_reply = server.handle({
            "jsonrpc": "2.0", "id": 4, "method": "tools/call",
            "params": {"name": "ui_act", "arguments": {"gesture": "open", "arg": "graph", "session_wait_s": 4.0}},
        })
        ok_payload = json.loads(ok_reply["result"]["content"][0]["text"])
        assert ok_payload["ok"] is True
        assert ok_payload["gesture"] == "open"
        assert ok_payload.get("waited_for_peer_s", 0) >= 0.1
    finally:
        if holder.poll() is None:
            holder.kill()
        holder.wait(timeout=4.0)
