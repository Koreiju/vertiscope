"""Run at full speed: opt this process out of Windows power throttling.

Measured 2026-11-15 on the reader's machine (i9-14900HX: 8 performance and
16 efficiency cores, Windows 11): a fixed pure-Python loop took 53-60 ms an
iteration for the first ~3 s of a process's life and 140-230 ms after it,
for as long as it kept running -- Windows' power throttling ("EcoQoS")
moving a sustained background process onto the efficiency cores and slowing
its clock. The sidecar is exactly that process: long-lived, CPU-bound in
Python, and never the foreground window. Every phase it times -- the
markdown render, the chunker, tf-idf, the store's JSON -- was being read at
roughly a third of the machine's speed, and moved by 3.5x partway through a
measurement (an edit's render read 50 ms twice, then 150-180 ms for the rest
of the run).

`SetProcessInformation(ProcessPowerThrottling)` with the execution-speed
bit controlled and cleared is the process's own declaration that it wants
high QoS -- the API Microsoft documents for exactly this, set on itself,
not a system setting. With it the same loop held 51-56 ms for 10 s.

Planted: `DOMVEC_PLANT_THROTTLED=1` leaves the process as Windows chose.
"""
from __future__ import annotations

import os
import sys
from typing import Dict, Optional

_PROCESS_POWER_THROTTLING = 4            # PROCESS_INFORMATION_CLASS
_THROTTLE_EXECUTION_SPEED = 0x1
_VERSION = 1

#: What the last call did, for `/health` and the analytics artifacts.
STATE: Dict[str, Optional[object]] = {"asked": False, "opted_out": None, "planted": False, "error": None}


def _api():
    import ctypes
    from ctypes import wintypes

    class _State(ctypes.Structure):
        _fields_ = [("Version", wintypes.ULONG), ("ControlMask", wintypes.ULONG),
                    ("StateMask", wintypes.ULONG)]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.SetProcessInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    k32.SetProcessInformation.restype = wintypes.BOOL
    k32.GetProcessInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    k32.GetProcessInformation.restype = wintypes.BOOL
    return ctypes, k32, _State


def throttling_state() -> Optional[Dict[str, int]]:
    """The process's power-throttling state as the OS reports it, or None
    off Windows. `control` with the execution-speed bit set and `state`
    without it means opted out."""
    if sys.platform != "win32":
        return None
    try:
        ctypes, k32, _State = _api()
        s = _State(_VERSION, 0, 0)
        if not k32.GetProcessInformation(k32.GetCurrentProcess(), _PROCESS_POWER_THROTTLING,
                                         ctypes.byref(s), ctypes.sizeof(s)):
            return {"error": ctypes.get_last_error()}
        return {"control": int(s.ControlMask), "state": int(s.StateMask)}
    except Exception as exc:                        # noqa: BLE001
        return {"error": str(exc)[:120]}


def full_speed() -> bool:
    """Opt the calling process out of execution-speed throttling. True when
    the OS accepted it; False off Windows, when planted, or on refusal.
    Never raises."""
    STATE["asked"] = True
    if os.environ.get("DOMVEC_PLANT_THROTTLED") == "1":
        STATE.update(planted=True, opted_out=False)
        return False
    if sys.platform != "win32":
        STATE.update(opted_out=False)
        return False
    try:
        ctypes, k32, _State = _api()
        s = _State(_VERSION, _THROTTLE_EXECUTION_SPEED, 0)
        ok = bool(k32.SetProcessInformation(k32.GetCurrentProcess(), _PROCESS_POWER_THROTTLING,
                                            ctypes.byref(s), ctypes.sizeof(s)))
        STATE.update(opted_out=ok, error=None if ok else ctypes.get_last_error())
        return ok
    except Exception as exc:                        # noqa: BLE001
        STATE.update(opted_out=False, error=str(exc)[:120])
        return False
