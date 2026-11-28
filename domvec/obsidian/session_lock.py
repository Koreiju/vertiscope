"""Cross-process concurrency lease for the shared single-instance Obsidian & sidecar harness.

Two MCP server processes (e.g. Antigravity and Claude Code) and CLI build/check
commands share ONE running Obsidian renderer (CDP :9222) and ONE domvec sidecar
because running duplicate Electron + CUDA/UMAP instances exhausts memory.

Design invariants:
1. **Strictly harness-internal (zero freehand/markdown coupling)**:
   All concurrency state lives in `<repo>/.domvec/mcp_session.lock` (1-byte OS
   kernel lock via `msvcrt.locking` on Windows / `fcntl.flock` on POSIX) and
   `<repo>/.domvec/mcp_session.json` (process/operation metadata). Neither
   Obsidian's vault indexer nor any freehand handoff markdown file is read or
   written by this module.
2. **Crash-proof kernel release & Windows mandatory-lock safety**:
   Keeping the 1-byte locked `.lock` file separate from `.json` avoids Windows
   `Errno 13` mandatory byte-range read failures while guaranteeing the OS
   kernel releases `.lock` instantaneously if a holder process crashes or is
   killed (`TerminateProcess` / `SIGKILL`).
3. **Wait-then-deliberate-return**:
   Contending interactive/mutating calls wait up to `wait_s` for the active
   holder to finish and proceed seamlessly once free (`waited_for_peer_s`); if
   still busy after `wait_s`, they deliberately return a structured
   `{"ok": False, "busy": True, "session_lock": ..., "retry_after_s": ...}`
   payload so the waiting agent can continue offline work and retry cleanly.
"""

from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Callable, Dict, Iterator, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_LOCK_DIR = REPO_ROOT / ".domvec"

_PROC_LOCK = threading.RLock()
_STATE_BY_DIR: Dict[str, Dict[str, Any]] = {}
_CLIENT_NAME: Optional[str] = None


class SessionBusyError(RuntimeError):
    """Raised when the shared Obsidian/sidecar session stays busy past `wait_s`."""

    def __init__(self, payload: Dict[str, Any]) -> None:
        super().__init__(payload.get("hint") or "shared session busy")
        self.payload = payload


def set_client_name(name: Optional[str]) -> None:
    """Record the MCP client's self-reported name from JSON-RPC `initialize`."""
    global _CLIENT_NAME
    cleaned = (name or "").strip()
    if cleaned:
        _CLIENT_NAME = cleaned[:64]


def detect_client_name() -> str:
    """Identify this harness process solely from runtime RPC/process facts."""
    if _CLIENT_NAME:
        return _CLIENT_NAME
    env_name = (os.environ.get("DOMVEC_MCP_CLIENT") or "").strip()
    if env_name:
        return env_name[:64]
    try:
        import psutil
        chain = []
        cur = psutil.Process(os.getpid())
        for _ in range(5):
            cur = cur.parent()
            if cur is None:
                break
            nm = (cur.name() or "").lower()
            cmd = " ".join(cur.cmdline() or []).lower()
            if "antigravity" in nm or "antigravity" in cmd or "gemini" in cmd:
                return f"antigravity(pid={os.getpid()})"
            if "claude" in nm or "claude" in cmd:
                return f"claude(pid={os.getpid()})"
            chain.append(nm)
        if chain:
            return f"{chain[0]}(pid={os.getpid()})"
    except Exception:                               # noqa: BLE001
        pass
    return f"pid-{os.getpid()}"


def _resolve_dir(lock_dir: Optional[Path | str] = None) -> Path:
    raw = lock_dir or os.environ.get("DOMVEC_LOCK_DIR") or DEFAULT_LOCK_DIR
    p = Path(raw).resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


def _paths(lock_dir: Optional[Path | str] = None) -> tuple[Path, Path, str]:
    d = _resolve_dir(lock_dir)
    return (d / "mcp_session.lock", d / "mcp_session.json", str(d))


def _os_try_lock(fd: int) -> bool:
    try:
        if sys.platform == "win32":
            import msvcrt
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _os_unlock(fd: int) -> None:
    try:
        if sys.platform == "win32":
            import msvcrt
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        pass


def _open_lock_fd(lock_path: Path) -> int:
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o666)
    try:
        if os.fstat(fd).st_size == 0:
            os.write(fd, b"\0")
    except OSError:
        pass
    return fd


def _read_meta(meta_path: Path) -> Dict[str, Any]:
    try:
        if meta_path.exists():
            data = json.loads(meta_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:                               # noqa: BLE001
        pass
    return {}


def _write_meta(meta_path: Path, payload: Dict[str, Any]) -> None:
    tmp = meta_path.with_name(f"{meta_path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    text = json.dumps(payload, indent=2)
    try:
        tmp.write_text(text, encoding="utf-8")
        for _ in range(5):
            try:
                os.replace(str(tmp), str(meta_path))
                return
            except PermissionError:
                time.sleep(0.02)
        meta_path.write_text(text, encoding="utf-8")
    except Exception:                               # noqa: BLE001
        pass
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


def lock_status(lock_dir: Optional[Path | str] = None) -> Dict[str, Any]:
    """Non-blocking snapshot of the shared MCP session lock."""
    lock_path, meta_path, key = _paths(lock_dir)
    now = time.time()
    with _PROC_LOCK:
        st = _STATE_BY_DIR.get(key)
        if st and st.get("depth", 0) > 0:
            meta = dict(st.get("meta") or _read_meta(meta_path))
            acq = float(meta.get("acquired_at") or now)
            return {
                "busy": True,
                "self_held": True,
                "holder_pid": os.getpid(),
                "client": meta.get("client") or detect_client_name(),
                "op": meta.get("op") or "active",
                "detail": meta.get("detail") or "",
                "elapsed_s": round(max(0.0, now - acq), 2),
            }

        # Probe the OS kernel lock without holding it so crashed processes
        # whose `.json` remained on disk never masquerade as `busy: True`.
        fd: Optional[int] = None
        try:
            fd = _open_lock_fd(lock_path)
            if _os_try_lock(fd):
                _os_unlock(fd)
                return {"busy": False, "self_held": False, "holder": None}
        except OSError:
            pass
        finally:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass

    meta = _read_meta(meta_path)
    acq = float(meta.get("acquired_at") or now)
    return {
        "busy": True,
        "self_held": False,
        "holder_pid": meta.get("pid"),
        "client": meta.get("client") or "peer",
        "op": meta.get("op") or "active",
        "detail": meta.get("detail") or "",
        "elapsed_s": round(max(0.0, now - acq), 2),
    }


def busy_payload(op: str, waited_s: float, status: Dict[str, Any], retry_after_s: int = 10) -> Dict[str, Any]:
    """Structured deliberate-return payload when the shared instance is busy."""
    return {
        "ok": False,
        "busy": True,
        "op": op,
        "waited_s": round(waited_s, 2),
        "retry_after_s": retry_after_s,
        "session_lock": status,
        "hint": (
            "Shared Obsidian/sidecar session is currently held by another MCP harness "
            f"({status.get('client')} running {status.get('op')}); continue offline "
            "edits/unit tests or poll live_health and retry once session_lock.busy is false."
        ),
    }


def _planted_no_lock(explicit: bool = False) -> bool:
    return explicit or os.environ.get("DOMVEC_PLANT_NO_SESSION_LOCK") in ("1", "true", "yes")


def default_wait_s(fallback: float = 90.0) -> float:
    raw = os.environ.get("DOMVEC_SESSION_WAIT_S")
    if raw is not None:
        try:
            return max(0.0, float(raw))
        except ValueError:
            pass
    return fallback


@contextmanager
def session_lease(
    op: str,
    detail: str = "",
    *,
    wait_s: Optional[float] = None,
    lock_dir: Optional[Path | str] = None,
    plant_no_lock: bool = False,
) -> Iterator[Dict[str, Any]]:
    """Acquire the cross-process session lease, waiting up to `wait_s`."""
    if _planted_no_lock(plant_no_lock):
        yield {"waited_s": 0.0, "reentrant": False, "planted_no_lock": True}
        return

    budget = default_wait_s(90.0) if wait_s is None else max(0.0, float(wait_s))
    lock_path, meta_path, key = _paths(lock_dir)
    t0 = time.monotonic()

    # Fast check for same-process re-entrancy (`verify` -> `reload_plugin` -> `act`).
    with _PROC_LOCK:
        existing = _STATE_BY_DIR.get(key)
        if existing and existing.get("depth", 0) > 0 and existing.get("thread") == threading.get_ident():
            existing["depth"] += 1
            reentrant = True
        else:
            reentrant = False

    if reentrant:
        try:
            yield {"waited_s": 0.0, "reentrant": True, "planted_no_lock": False}
        finally:
            with _PROC_LOCK:
                st = _STATE_BY_DIR.get(key)
                if st:
                    st["depth"] = max(0, int(st.get("depth", 1)) - 1)
        return

    deadline = t0 + budget
    acquired_fd: Optional[int] = None
    while True:
        with _PROC_LOCK:
            existing = _STATE_BY_DIR.get(key)
            if existing is None or existing.get("depth", 0) == 0:
                fd = _open_lock_fd(lock_path)
                if _os_try_lock(fd):
                    now = time.time()
                    meta = {
                        "pid": os.getpid(),
                        "ppid": os.getppid(),
                        "client": detect_client_name(),
                        "op": op,
                        "detail": str(detail or "")[:160],
                        "acquired_at": now,
                    }
                    _write_meta(meta_path, meta)
                    _STATE_BY_DIR[key] = {
                        "fd": fd,
                        "depth": 1,
                        "thread": threading.get_ident(),
                        "meta": meta,
                    }
                    acquired_fd = fd
                    break
                try:
                    os.close(fd)
                except OSError:
                    pass

        waited = time.monotonic() - t0
        if time.monotonic() >= deadline:
            st = lock_status(lock_dir)
            if not st.get("busy"):
                # Holder released right between probe and status check; try once more.
                deadline = time.monotonic() + 0.05
                continue
            raise SessionBusyError(busy_payload(op, waited, st))
        sleep_s = min(0.35 + random.uniform(0.0, 0.12), max(0.02, deadline - time.monotonic()))
        time.sleep(sleep_s)

    waited_total = round(max(0.0, time.monotonic() - t0), 3)
    lease_info = {"waited_s": waited_total, "reentrant": False, "planted_no_lock": False}
    try:
        yield lease_info
    finally:
        with _PROC_LOCK:
            st = _STATE_BY_DIR.get(key)
            if st:
                st["depth"] = max(0, int(st.get("depth", 1)) - 1)
                if st["depth"] == 0:
                    _STATE_BY_DIR.pop(key, None)
                    fd_to_close = st.get("fd", acquired_fd)
                    try:
                        _write_meta(meta_path, {"busy": False, "released_at": time.time(), "last_op": op})
                    except Exception:               # noqa: BLE001
                        pass
                    if fd_to_close is not None:
                        _os_unlock(fd_to_close)
                        try:
                            os.close(fd_to_close)
                        except OSError:
                            pass


def call_with_lease(
    op: str,
    fn: Callable[[], Any],
    *,
    detail: str = "",
    wait_s: Optional[float] = None,
    lock_dir: Optional[Path | str] = None,
) -> Any:
    """Run `fn()` inside `session_lease`, returning `busy_payload` on timeout."""
    try:
        with session_lease(op, detail=detail, wait_s=wait_s, lock_dir=lock_dir) as lease:
            out = fn()
            if isinstance(out, dict) and lease.get("waited_s", 0.0) >= 0.05 and "waited_for_peer_s" not in out:
                out = dict(out, waited_for_peer_s=lease["waited_s"])
            return out
    except SessionBusyError as exc:
        return exc.payload


def run_contention_selftest(*, plant_no_lock: bool = False) -> Dict[str, Any]:
    """Two-process OS lock contention proof (clean vs planted `no-session-lock`)."""
    with tempfile.TemporaryDirectory(prefix="domvec_lock_check_") as tmp:
        env = dict(os.environ)
        env["PYTHONPATH"] = str(REPO_ROOT)
        env["DOMVEC_MCP_CLIENT"] = "peer-holder"
        if plant_no_lock:
            env["DOMVEC_PLANT_NO_SESSION_LOCK"] = "1"
        else:
            env.pop("DOMVEC_PLANT_NO_SESSION_LOCK", None)

        holder = subprocess.Popen(
            [sys.executable, "-m", "domvec.obsidian.session_lock",
             "--lock-dir", tmp, "--hold", "1.1", "--op", "peer-confirm"],
            cwd=str(REPO_ROOT),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        try:
            # Wait until holder signals it holds the lock (or 0.25s in planted mode).
            deadline = time.monotonic() + 4.0
            while time.monotonic() < deadline:
                st = lock_status(tmp)
                if st.get("busy") or plant_no_lock:
                    if plant_no_lock:
                        time.sleep(0.25)
                    break
                if holder.poll() is not None:
                    break
                time.sleep(0.04)

            # 1. Short wait budget -> must deliberately return `busy: True` (unless planted).
            try:
                with session_lease("contender-probe", wait_s=0.12, lock_dir=tmp, plant_no_lock=plant_no_lock):
                    short_res = {"ok": True, "busy": False}
            except SessionBusyError as exc:
                short_res = exc.payload

            # 2. Sufficient wait budget -> must wait for peer to finish and then succeed cleanly.
            t_wait = time.monotonic()
            with session_lease("contender-resume", wait_s=4.0, lock_dir=tmp, plant_no_lock=plant_no_lock) as lease:
                holder_still_running_during_lease = (holder.poll() is None)
                resumed_waited_s = lease["waited_s"]
            elapsed_resume_s = round(time.monotonic() - t_wait, 3)
        finally:
            try:
                holder.wait(timeout=4.0)
            except subprocess.TimeoutExpired:
                holder.kill()

        after_status = lock_status(tmp)
        return {
            "planted": bool(plant_no_lock),
            "short_busy": bool(short_res.get("busy")),
            "short_holder_op": (short_res.get("session_lock") or {}).get("op"),
            "resumed_waited_s": resumed_waited_s,
            "elapsed_resume_s": elapsed_resume_s,
            "overlapped_with_holder": bool(holder_still_running_during_lease),
            "released_after": not bool(after_status.get("busy")),
        }


def main(argv: Optional[list[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m domvec.obsidian.session_lock",
        description="Coordinate exclusive operations (builds, reloads, checks) on the shared Obsidian/sidecar session.",
    )
    parser.add_argument("--lock-dir", default=None, help="Override lock directory (default: .domvec)")
    parser.add_argument("--status", action="store_true", help="Print live lock status JSON and exit")
    parser.add_argument("--selftest", action="store_true", help="Run two-process contention selftest")
    parser.add_argument("--plant-no-lock", action="store_true", help="Planted broken arm for selftest")
    parser.add_argument("--hold", type=float, default=0.0, help="Hold the lock for N seconds (for testing)")
    parser.add_argument("--op", default="cli", help="Operation name recorded in lock metadata")
    parser.add_argument("--detail", default="", help="Optional operation detail")
    parser.add_argument("--wait", type=float, default=120.0, help="Seconds to wait before returning busy (default: 120)")
    parser.add_argument("cmd", nargs=argparse.REMAINDER, help="Command after `--` to execute while holding the lease")
    args = parser.parse_args(argv)

    if args.status:
        print(json.dumps(lock_status(args.lock_dir), indent=2))
        return 0
    if args.selftest:
        print(json.dumps(run_contention_selftest(plant_no_lock=args.plant_no_lock), indent=2))
        return 0

    cmd = list(args.cmd or [])
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]

    try:
        with session_lease(args.op, detail=args.detail or " ".join(cmd)[:120],
                           wait_s=args.wait, lock_dir=args.lock_dir,
                           plant_no_lock=args.plant_no_lock) as lease:
            if args.hold > 0:
                sys.stdout.write(json.dumps({"holding": args.hold, "op": args.op, **lease}) + "\n")
                sys.stdout.flush()
                time.sleep(args.hold)
            if cmd:
                proc = subprocess.run(cmd)
                return int(proc.returncode)
            return 0
    except SessionBusyError as exc:
        sys.stderr.write(json.dumps(exc.payload, indent=2) + "\n")
        return 75


if __name__ == "__main__":
    sys.exit(main())
