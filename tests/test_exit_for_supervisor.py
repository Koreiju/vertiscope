"""The sidecar leaves for its supervisor with the code it means (75/76),
by `TerminateProcess` on Windows -- `ExitProcess` hung in a DLL's detach
routine with CUDA loaded (2026-10-19). Both arms must exit with the code;
what the fix changes is that no detach routine runs, which a child that
registers an atexit-style DLL hook cannot portably show, so the arm that
CAN fail here is the code itself and the flush before it."""
import subprocess
import sys

CHILD = ("import sys; sys.path.insert(0, %r); "
         "from vertiscope.obsidian.sidecar import _exit_for_supervisor; "
         "print('before', flush=False); sys.stdout.write('unflushed'); "
         "_exit_for_supervisor(76)")


def _run(env_extra=None):
    import os
    env = dict(os.environ, **(env_extra or {}))
    import pathlib
    root = str(pathlib.Path(__file__).resolve().parents[1])
    return subprocess.run([sys.executable, "-c", CHILD % root], capture_output=True, text=True, env=env, timeout=120)


def test_exits_with_the_supervisors_code_and_flushes():
    r = _run()
    assert r.returncode == 76, (r.returncode, r.stderr[-400:])
    assert "unflushed" in r.stdout, r.stdout


def test_planted_os_exit_still_exits_76():
    r = _run({"VERTISCOPE_PLANT_EXIT_PROCESS": "1"})
    assert r.returncode == 76
