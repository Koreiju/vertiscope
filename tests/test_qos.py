"""The sidecar opts itself out of Windows power throttling (`domvec.qos`).

2026-11-15: a fixed loop ran 53-60 ms for ~3 s of a process's life and
140-230 ms after; opted out, 51-56 ms for 10 s. The non-vacuity arm reads the
state back from the OS: a planted process (`DOMVEC_PLANT_THROTTLED=1`) does
not report the execution-speed bit as controlled.
"""
import subprocess
import sys

import pytest

PROBE = ("import json; from domvec import qos; ok = qos.full_speed(); "
         "print(json.dumps({'ok': ok, 'os': qos.throttling_state()}))")


def _run(planted):
    import json, os
    env = dict(os.environ)
    if planted:
        env["DOMVEC_PLANT_THROTTLED"] = "1"
    else:
        env.pop("DOMVEC_PLANT_THROTTLED", None)
    out = subprocess.run([sys.executable, "-c", PROBE], capture_output=True, text=True, env=env, timeout=60)
    return json.loads(out.stdout.strip().splitlines()[-1])


@pytest.mark.skipif(sys.platform != "win32", reason="Windows power throttling")
def test_the_process_is_opted_out_as_the_os_reports_it():
    got = _run(False)
    assert got["ok"] is True
    assert got["os"]["control"] & 0x1 and not (got["os"]["state"] & 0x1)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows power throttling")
def test_planted_the_process_is_left_as_windows_chose():
    got = _run(True)
    assert got["ok"] is False
    assert not (got["os"].get("control", 0) & 0x1)
