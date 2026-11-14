"""PLUGIN_GOAL 157: "I get like 4 to 5 different command lines spawning".

The rule under test is Windows': a console program started by a parent that
has NO console gets a new, visible console window. The plugin starts the
supervisor DETACHED (Node `detached: true` = DETACHED_PROCESS), so the chain
here is the same one: a detached parent that starts a console child through
`procs.hidden`. The census must count no window -- and, planted
(`DOMVEC_PLANT_CONSOLE_WINDOWS=1` drops the flag), must count one. A census
that cannot see the planted window is not measuring anything.
"""
import os
import subprocess
import sys
import time

import pytest

from domvec import procs

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="a Windows console rule")

# The parent: detached, no console -- it starts one console child that sleeps.
PARENT = (
    "import subprocess, sys, time\n"
    "from domvec.procs import hidden\n"
    "c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], **hidden())\n"
    "time.sleep(30)\n"
)


def _run(planted: bool) -> dict:
    env = dict(os.environ, PYTHONPATH=os.getcwd())
    env.pop("DOMVEC_PLANT_CONSOLE_WINDOWS", None)
    if planted:
        env["DOMVEC_PLANT_CONSOLE_WINDOWS"] = "1"
    p = subprocess.Popen([sys.executable, "-c", PARENT], env=env,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
    try:
        seen = {}
        deadline = time.time() + 12
        while time.time() < deadline:
            seen = procs.census(p.pid)
            kids = [t for t in seen.get("tree", []) if t["pid"] != p.pid and t["name"].lower().startswith("python")]
            if kids and (seen["visible_windows"] or not planted) and time.time() > deadline - 9:
                break
            time.sleep(0.5)
        return seen
    finally:
        subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], **procs.hidden(capture_output=True))


def test_hidden_sets_the_flag():
    assert procs.hidden()["creationflags"] & subprocess.CREATE_NO_WINDOW
    assert procs.hidden(creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)["creationflags"] & subprocess.CREATE_NEW_PROCESS_GROUP


def test_detached_chain_opens_no_window():
    got = _run(planted=False)
    assert "error" not in got, got
    assert got["visible_windows"] == 0, got["windows"]


def test_planted_chain_is_caught():
    got = _run(planted=True)
    assert got.get("planted") is False   # the census runs in THIS process, unplanted
    assert got["visible_windows"] >= 1, got
