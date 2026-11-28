"""Sidecar and workspace management controls for domvec and Obsidian.

Provides programmatic start, stop, restart, health check, vault setup, and
Obsidian launching with CDP debugging enabled.
"""

from __future__ import annotations

import json
import os
import subprocess

from ..procs import hidden
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Dict, List, Optional, Union

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# A kuzu store is only restarted with its WAL small or folded. The native
# crash `D-23` (0xC0000005, 2026-10-12) came during CHECKPOINT, and a hard
# kill with a large WAL pending is how an unreplayable one gets written.
WAL_LIMIT = 8 * 1024 * 1024


def wal_bytes(workspace: Union[str, Path]) -> int:
    wal = Path(workspace) / "graph.kuzu.wal"
    return wal.stat().st_size if wal.exists() else 0


def _configured_target(port: Optional[int] = None,
                       workspace: Optional[Union[str, Path]] = None) -> tuple[int, str]:
    """Resolve the active sidecar port and workspace from the vault's data.json when omitted."""
    cfg_port = 8788
    cfg_ws = "build/corpus123"
    try:
        cfg_path = REPO_ROOT / ".obsidian" / "plugins" / "domvec-bridge" / "data.json"
        if cfg_path.exists():
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            launch = cfg.get("sidecarLaunch") or {}
            argv = [str(a) for a in (launch.get("argv") or [])]
            active = str(cfg.get("activeWorkspace") or "")
            workspaces = cfg.get("workspaces") or {}
            if "--port" in argv:
                idx = argv.index("--port")
                if idx + 1 < len(argv) and argv[idx + 1].isdigit():
                    cfg_port = int(argv[idx + 1])
            elif cfg.get("sidecar"):
                import re
                m = re.search(r":(\d+)", str(cfg.get("sidecar")))
                if m:
                    cfg_port = int(m.group(1))
            if active and isinstance(workspaces, dict) and workspaces.get(active):
                cfg_ws = str(workspaces[active])
            elif launch.get("workspace"):
                cfg_ws = str(launch["workspace"])
    except Exception:                               # noqa: BLE001
        pass
    use_cfg_port = (not port) or (int(port) == 8788 and cfg_port != 8788 and not find_sidecars(8788))
    resolved_port = cfg_port if use_cfg_port else int(port)
    use_cfg_ws = (not workspace) or (str(workspace) == "build/corpus123" and cfg_ws != "build/corpus123" and resolved_port == cfg_port)
    resolved_ws = cfg_ws if use_cfg_ws else str(workspace)
    return (resolved_port, resolved_ws)


def _workspace_of(procs: List[Dict]) -> Optional[str]:
    """The --workspace a running sidecar was started with."""
    for info in procs:
        parts = info.get("cmdline", "").split()
        if "--workspace" in parts:
            i = parts.index("--workspace")
            if i + 1 < len(parts):
                return parts[i + 1]
    return None


def _health(port: int, timeout: float) -> Dict:
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/health" % port, timeout=timeout) as res:
            return json.loads(res.read().decode("utf-8"))
    except Exception as exc:                        # noqa: BLE001
        return {"error": str(exc)}


def find_sidecars(port: int = 8788) -> List[Dict]:
    """Find running python processes matching domvec.obsidian and the port."""
    import psutil

    results = []
    port_str = str(port)
    for p in psutil.process_iter(["pid", "ppid", "name", "cmdline", "create_time"]):
        try:
            cmd = p.info.get("cmdline") or []
            cmd_str = " ".join(cmd)
            # A PYTHON process running the module -- a shell whose command
            # line merely mentions it (this very tool's caller) is not one.
            name = (p.info.get("name") or "").lower()
            runs = any(cmd[i] == "-m" and i + 2 < len(cmd) and cmd[i + 1] == "domvec.obsidian"
                       and cmd[i + 2] in ("serve", "supervise") for i in range(len(cmd)))
            if name.startswith("python") and runs and port_str in cmd:
                results.append({
                    "pid": p.info["pid"],
                    "ppid": p.info["ppid"],
                    "name": p.info["name"],
                    "cmdline": cmd_str,
                    "created": p.info["create_time"],
                })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return results


def stop_sidecar(port: Optional[int] = None, timeout_s: float = 5.0, force: bool = False) -> Dict:
    """Stop any running sidecar and supervisor processes on the given port."""
    from .session_lock import call_with_lease
    if not force:
        return call_with_lease("sidecar_stop", lambda: _stop_sidecar_inner(port, timeout_s, force), wait_s=90.0)
    return _stop_sidecar_inner(port, timeout_s, force)


def _stop_sidecar_inner(port: Optional[int] = None, timeout_s: float = 5.0, force: bool = False) -> Dict:
    """Stop any running sidecar and supervisor processes on the given port.

    Asks `/shutdown?stop=1` first so the worker finishes its work lock, saves
    the projector, checkpoints its WAL and exits 0 (stopping the supervisor
    cleanly). Falls back to killing the process tree when `force` or when the
    worker is not answering HTTP; a hard kill is refused while the store's WAL
    is over `WAL_LIMIT` unless `force`.
    """
    import psutil

    port, _ = _configured_target(port, None)
    initial_procs = find_sidecars(port)
    procs = list(initial_procs)
    ws = _workspace_of(procs)
    # A checkpoint in progress: the WAL reads ~0 bytes DURING it, so the size
    # test alone let a restart kill the fold twice (2026-10-17). A sidecar whose
    # `/checkpointing` times out is treated as checkpointing; an HTTP 503
    # (worker starting/dead) or connection refused is not.
    if procs and not force:
        try:
            with urllib.request.urlopen("http://127.0.0.1:%d/checkpointing" % port, timeout=5.0) as res:
                cp = json.loads(res.read().decode("utf-8"))
        except urllib.error.HTTPError:
            cp = {"checkpointing": False}
        except Exception as exc:                    # noqa: BLE001
            timed_out = "timed out" in str(exc).lower() or isinstance(exc, TimeoutError)
            cp = {"checkpointing": timed_out, "why": str(exc)[:120]}
        if cp.get("checkpointing"):
            return {"ok": False, "refused": "a checkpoint is running; wait for it to finish", "detail": cp, "port": port}

    graceful = False
    if procs:
        try:
            req = urllib.request.Request("http://127.0.0.1:%d/shutdown?stop=1" % port, data=b"{}",
                                         headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=5.0) as res:
                graceful = (res.status == 200)
        except Exception:                           # noqa: BLE001
            graceful = False
        if graceful:
            g_deadline = time.time() + max(timeout_s, 10.0)
            while time.time() < g_deadline:
                procs = find_sidecars(port)
                if not procs:
                    return {
                        "ok": True,
                        "graceful": True,
                        "port": port,
                        "stopped_pids": [p["pid"] for p in initial_procs],
                        "remaining": 0,
                    }
                time.sleep(0.25)

    procs = find_sidecars(port)
    if procs and ws and not force and wal_bytes(ws) > WAL_LIMIT:
        return {"ok": False, "refused": "WAL is %.1f MB (limit %.0f MB); wait for the fold or pass force"
                % (wal_bytes(ws) / 1e6, WAL_LIMIT / 1e6), "workspace": ws, "port": port}
    stopped_pids = [p["pid"] for p in initial_procs if p["pid"] not in {x["pid"] for x in procs}]
    for info in procs:
        pid = info["pid"]
        try:
            p = psutil.Process(pid)
            # Kill children first (e.g. supervised child)
            for child in p.children(recursive=True):
                try:
                    child.kill()
                    stopped_pids.append(child.pid)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            p.kill()
            stopped_pids.append(pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if not find_sidecars(port):
            break
        time.sleep(0.3)

    return {
        "ok": len(find_sidecars(port)) == 0,
        "graceful": graceful,
        "port": port,
        "stopped_pids": list(set(stopped_pids)),
        "remaining": len(find_sidecars(port)),
    }


def start_sidecar(
    workspace: Optional[Union[str, Path]] = None,
    port: Optional[int] = None,
    *,
    semantic: bool = True,
    capture: bool = True,
    enact: bool = True,
    kernel: bool = True,
    supervise: bool = True,
    stop_existing: bool = False,
    force: bool = False,
    wait_s: float = 90.0,
) -> Dict:
    """Start a sidecar on the given workspace directory with requested powers.

    A healthy sidecar already on the port is LEFT RUNNING and reported, not
    killed, unless `stop_existing`: a start that kills the store mid-write is
    how an unreplayable WAL gets made. `wait_s` covers loading the encoder,
    which takes well over the old 25 s on a cold `--semantic` start.
    """
    port, ws_default = _configured_target(port, workspace)
    workspace = Path(ws_default).resolve()
    workspace.mkdir(parents=True, exist_ok=True)

    running = find_sidecars(port)
    if running and not stop_existing:
        return {"ok": "error" not in _health(port, 30.0), "already_running": True,
                "workspace": _workspace_of(running), "processes": running,
                "note": "left running; pass stop_existing to replace it"}
    # Only when REPLACING a running one: a sidecar that is down must open its
    # store, replaying whatever WAL it left -- refusing that kept it down.
    if running and not force and wal_bytes(workspace) > WAL_LIMIT:
        return {"ok": False, "refused": "WAL is %.1f MB (limit %.0f MB); wait for the fold or pass force"
                % (wal_bytes(workspace) / 1e6, WAL_LIMIT / 1e6)}
    if running:
        stopped = stop_sidecar(port, force=force)
        if not stopped.get("ok"):
            return {"ok": False, "stop": stopped}

    subcmd = "supervise" if supervise else "serve"
    cmd = [
        sys.executable,
        "-X", "faulthandler",
        "-m", "domvec.obsidian",
        subcmd,
        "--workspace", str(workspace),
        "--port", str(port),
    ]
    if semantic:
        cmd.append("--semantic")
    if capture:
        cmd.append("--capture")
    if enact:
        cmd.append("--enact")
    if kernel:
        cmd.append("--kernel")

    log_path = workspace / "sidecar.log"
    err_path = workspace / "sidecar.err.log"
    log_fh = open(log_path, "a", encoding="utf-8")
    err_fh = open(err_path, "a", encoding="utf-8")

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = str(REPO_ROOT)

    # stdin NUL: inheriting this MCP server's stdin -- a pipe it is always
    # blocked reading -- hung every child the supervisor started after its
    # first (`supervise._run_child`, 2026-10-25).
    proc = subprocess.Popen(
        cmd,
        cwd=str(REPO_ROOT),
        stdin=subprocess.DEVNULL,
        stdout=log_fh,
        stderr=err_fh,
        env=env,
        **hidden(creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0),
    )

    # Wait for /health (and if the front is serving, wait for its worker to be up)
    healthy = False
    exited = None
    start_t = time.time()
    while time.time() - start_t < wait_s:
        exited = proc.poll()
        if exited is not None:              # died on start: say so, do not wait out the clock
            break
        h = _health(port, 10.0)
        if "error" not in h and h.get("ok") and h.get("backend") not in ("starting", "dead"):
            healthy = True
            break
        time.sleep(1.0)
    log_fh.close()
    err_fh.close()

    powers = []
    if enact:
        powers.append("ENACT")
    if capture:
        powers.append("CAPTURE")
    if semantic:
        powers.append("SEMANTIC")
    if kernel:
        powers.append("KERNEL")

    return {
        "ok": healthy,
        "exit_code": exited,
        "pid": proc.pid,
        "workspace": str(workspace),
        "port": port,
        "url": f"http://127.0.0.1:{port}",
        "powers": powers,
        "supervise": supervise,
        "log_path": str(log_path),
    }


def sidecar_status(port: Optional[int] = None, url: str = "http://127.0.0.1:8788") -> Dict:
    """Return live status of the sidecar process and HTTP endpoint."""
    # /health recounts the store when its cache is stale, and that took over
    # 6 s on corpus123 -- the old 2 s timeout reported a healthy sidecar as
    # "timed out" (2026-10-17). A slow answer is "busy", not "down".
    port, _ = _configured_target(port, None)
    procs = find_sidecars(port)
    t0 = time.time()
    health_data = _health(port, 20.0)
    ws = _workspace_of(procs)
    # What the sidecar puts on the screen (PLUGIN_GOAL 157: "4 to 5 different
    # command lines"): its process tree and the visible windows it owns.
    from ..procs import census
    roots = [p["pid"] for p in procs if isinstance(p, dict) and p.get("pid")]
    tops = [r for r in roots if not any(r != o and r in [c["pid"] for c in census(o).get("tree", [])] for o in roots)]
    screen = [census(r) for r in tops]
    state = ("down" if not procs else
             "healthy" if "error" not in health_data else
             "busy" if "timed out" in health_data.get("error", "") else "unreachable")
    from .session_lock import lock_status
    return {
        "running": len(procs) > 0,
        "state": state,
        "health_s": round(time.time() - t0, 2),
        "processes": procs,
        "health": health_data,
        "workspace": ws,
        "wal_mb": round(wal_bytes(ws) / 1e6, 2) if ws else None,
        "session_lock": lock_status(),
        "screen": [{k: c.get(k) for k in ("root", "processes", "consoles", "visible_windows", "windows", "planted", "error")}
                   for c in screen],
        "url": "http://127.0.0.1:%d" % port,
        "port": port,
    }


def setup_vault(
    vault_path: Union[str, Path],
    sidecar_url: Optional[str] = None,
    *,
    register_in_obsidian: bool = True,
) -> Dict:
    """Set up a new or existing Obsidian vault with the domvec-bridge plugin."""
    import shutil

    vault_path = Path(vault_path).resolve()
    vault_path.mkdir(parents=True, exist_ok=True)

    obsidian_dir = vault_path / ".obsidian"
    obsidian_dir.mkdir(parents=True, exist_ok=True)

    # 1. community-plugins.json
    plugins_json = obsidian_dir / "community-plugins.json"
    enabled_plugins = ["domvec-bridge"]
    if plugins_json.exists():
        try:
            existing = json.loads(plugins_json.read_text(encoding="utf-8"))
            if isinstance(existing, list):
                enabled_plugins = list(dict.fromkeys(existing + ["domvec-bridge"]))
        except Exception:
            pass
    plugins_json.write_text(json.dumps(enabled_plugins, indent=2), encoding="utf-8")

    # 2. app.json
    app_json = obsidian_dir / "app.json"
    if not app_json.exists():
        app_json.write_text(json.dumps({"legacyEditor": False, "livePreview": True}, indent=2), encoding="utf-8")

    # 3. Deploy domvec-bridge plugin files
    plugin_dest = obsidian_dir / "plugins" / "domvec-bridge"
    plugin_dest.mkdir(parents=True, exist_ok=True)

    plugin_src = REPO_ROOT / ".obsidian" / "plugins" / "domvec-bridge"
    if not plugin_src.exists():
        plugin_src = REPO_ROOT / "obsidian-plugin"

    # The repo is itself a vault: there the source IS the destination, and
    # copy2 raises SameFileError.
    if plugin_src.resolve() != plugin_dest.resolve():
        for fname in ["manifest.json", "main.js", "styles.css"]:
            src_file = plugin_src / fname
            if src_file.exists():
                shutil.copy2(src_file, plugin_dest / fname)

    # 4. Plugin settings (data.json): defaults fill only what is MISSING.
    # Writing them whole reset the reader's own choices (`showBoxes`) on
    # every launch.
    data_json = plugin_dest / "data.json"
    settings = {
        "interactiveByDefault": True,
        "loadRemoteMedia": True,
        "retrievalLimit": 8,
        "saveOffline": True,
        "showBoxes": False,
        "webSearch": True,
    }
    if data_json.exists():
        try:
            settings.update(json.loads(data_json.read_text(encoding="utf-8")))
        except Exception:                           # noqa: BLE001
            pass
    if sidecar_url:
        settings["sidecar"] = sidecar_url
    else:
        launch_argv = [str(a) for a in ((settings.get("sidecarLaunch") or {}).get("argv") or [])]
        if "--port" in launch_argv and launch_argv.index("--port") + 1 < len(launch_argv):
            p_str = launch_argv[launch_argv.index("--port") + 1]
            if p_str.isdigit():
                settings["sidecar"] = f"http://127.0.0.1:{p_str}"
        if not settings.get("sidecar"):
            settings["sidecar"] = "http://127.0.0.1:8788"
    data_json.write_text(json.dumps(settings, indent=2), encoding="utf-8")

    # 5. Register in %APPDATA%/obsidian/obsidian.json
    registered_id = None
    if register_in_obsidian and sys.platform == "win32":
        obs_config = Path(os.environ.get("APPDATA", "")) / "obsidian" / "obsidian.json"
        if obs_config.exists():
            try:
                obs_data = json.loads(obs_config.read_text(encoding="utf-8"))
                vaults = obs_data.get("vaults", {})
                norm_target = str(vault_path)
                found = None
                for vid, vinfo in vaults.items():
                    if Path(vinfo.get("path", "")).resolve() == vault_path:
                        found = vid
                        break
                now_ts = int(time.time() * 1000)
                if not found:
                    import hashlib
                    found = hashlib.md5(norm_target.encode("utf-8")).hexdigest()[:16]
                    vaults[found] = {"path": norm_target, "ts": now_ts}
                else:
                    vaults[found]["ts"] = now_ts

                # Set new vault as open, unmark others
                for vid in vaults:
                    vaults[vid]["open"] = (vid == found)

                obs_data["vaults"] = vaults
                obs_config.write_text(json.dumps(obs_data), encoding="utf-8")
                registered_id = found
            except Exception as exc:
                print(f"Warning: could not update obsidian.json: {exc}", file=sys.stderr)

    return {
        "ok": True,
        "vault_path": str(vault_path),
        "plugin_installed": (plugin_dest / "main.js").exists(),
        "registered_id": registered_id,
        "sidecar_url": sidecar_url,
    }


def close_obsidian(*, force: bool = False) -> Dict:
    """Kill any running Obsidian processes cleanly and remove stale lockfiles."""
    if not force:
        from .session_lock import call_with_lease
        return call_with_lease("obsidian_close", _close_obsidian_inner, wait_s=90.0)
    return _close_obsidian_inner()


def _close_obsidian_inner() -> Dict:
    import psutil
    killed = []

    def alive() -> bool:
        return any("obsidian" in (p.info.get("name") or "").lower()
                   for p in psutil.process_iter(["name"]))

    # Ask first: a plain taskkill sends WM_CLOSE, and Obsidian then saves its
    # workspace (pane layout, open leaves). /F straight away lost it.
    graceful = False
    if sys.platform == "win32" and alive():
        subprocess.run(["taskkill", "/IM", "Obsidian.exe"], **hidden(capture_output=True, stdin=subprocess.DEVNULL))
        deadline = time.time() + 10.0
        while time.time() < deadline and alive():
            time.sleep(0.5)
        graceful = not alive()
        if not graceful:
            subprocess.run(["taskkill", "/F", "/IM", "Obsidian.exe", "/T"], **hidden(capture_output=True, stdin=subprocess.DEVNULL))

    for p in psutil.process_iter(["pid", "name"]):
        try:
            if "obsidian" in (p.info.get("name") or "").lower():
                p.kill()
                killed.append(p.info["pid"])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    time.sleep(0.5)

    # Clean stale lockfiles in %APPDATA%/obsidian that block Obsidian from re-launching
    removed_locks = []
    appdata = Path(os.environ.get("APPDATA", "")) / "obsidian"
    if appdata.exists():
        for f in appdata.glob("*lock*"):
            try:
                f.unlink()
                removed_locks.append(str(f))
            except Exception:
                pass

    return {"ok": not alive(), "graceful": graceful, "killed_pids": list(set(killed)),
            "removed_locks": removed_locks}


def launch_obsidian(
    vault_path: Optional[Union[str, Path]] = None,
    cdp_port: int = 9222,
    *,
    close_existing: bool = False,
    force: bool = False,
) -> Dict:
    """Launch Obsidian with remote debugging and background unthrottling.

    Reuses an already-running CDP-enabled Obsidian instance unless `force=True`,
    so even legacy callers passing `close_existing=True` never kill a healthy
    shared session (`G-455`); `close_existing` only restarts an Obsidian that
    was launched *without* `--remote-debugging-port`.
    """
    def cdp_up() -> bool:
        try:
            with urllib.request.urlopen("http://127.0.0.1:%d/json/version" % cdp_port, timeout=1.0) as res:
                return res.status == 200
        except Exception:                           # noqa: BLE001
            return False

    # If CDP is already answering on `cdp_port`, the unthrottling + debug flags
    # are already active: share the single running instance (`G-455`).
    if not force and cdp_up():
        return {"ok": True, "already_running": True, "shared_instance": True,
                "cdp_port": cdp_port, "cdp_alive": True}
    if close_existing or force:
        closed = close_obsidian()
        if closed.get("busy"):
            return closed

    if vault_path:
        setup_vault(vault_path, register_in_obsidian=True)

    exe_path = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Obsidian" / "Obsidian.exe"
    if not exe_path.exists():
        return {"ok": False, "error": f"Obsidian.exe not found at {exe_path}"}

    log_path = REPO_ROOT / "build" / "obsidian_chromium.log"
    log_fh = open(log_path, "a", encoding="utf-8")

    cmd = [
        str(exe_path),
        f"--remote-debugging-port={cdp_port}",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
        "--disable-background-timer-throttling",
        "--enable-logging=stderr",
        "--log-level=0",
    ]

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=log_fh,
        stderr=log_fh,
        **hidden(creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0),
    )

    # Verify CDP answers. The renderer answering is not the layout being
    # ready: a vault the size of this repo indexes for a while first, and a
    # pane probe in that window sees no panes (2026-10-17).
    cdp_alive = False
    deadline = time.time() + 20.0
    while time.time() < deadline and not cdp_alive:
        cdp_alive = cdp_up()
        if not cdp_alive:
            time.sleep(0.5)
    log_fh.close()

    return {
        "ok": cdp_alive,
        "pid": proc.pid,
        "cdp_port": cdp_port,
        "cdp_alive": cdp_alive,
        "next": "wait for app.workspace.layoutReady before probing panes",
        "log_path": str(log_path),
    }


def open_workspace(
    workspace: Union[str, Path],
    vault_path: Union[str, Path],
    port: int = 8788,
    cdp_port: int = 9222,
    *,
    launch_app: bool = True,
    close_existing_obsidian: bool = True,
) -> Dict:
    """One-shot command: prepare vault, launch sidecar with full feature set, and open Obsidian."""
    vault_res = setup_vault(vault_path, sidecar_url=f"http://127.0.0.1:{port}", register_in_obsidian=True)
    sidecar_res = start_sidecar(workspace, port=port, semantic=True, capture=True, enact=True, kernel=True, supervise=True)

    obs_res = None
    if launch_app:
        obs_res = launch_obsidian(vault_path=vault_path, cdp_port=cdp_port, close_existing=close_existing_obsidian)

    return {
        "ok": sidecar_res.get("ok", False) and (not launch_app or obs_res.get("ok", False)),
        "workspace": sidecar_res,
        "vault": vault_res,
        "obsidian": obs_res,
    }
