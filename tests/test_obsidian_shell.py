"""The command terminal: a session per pane, and the things it refuses.

`NOTEBOOK_PANEL_DESIGN` §6 step 6, whose bar is *a separate pane gives a pwsh
prompt; discovery lists installed kernels*.

The shape mirrors `test_obsidian_kernel.py` because the mechanism does, and the
interesting tests are the same two kinds: the session boundary (per PANE here,
per note there), and the ways it can go wrong quietly.

One difference is worth stating. This is a command RUNNER, not a pty, so the
tests assert that it refuses what it cannot do rather than pretending. A
terminal that hangs for two minutes on `vim` and then reports a timeout has told
the reader nothing they can act on.
"""

import json
import urllib.error
import urllib.request

import pytest

from vertiscope.obsidian.shell import ShellPool, interpreters, needs_a_terminal
from vertiscope.obsidian.sidecar import serve


@pytest.fixture()
def ws(tmp_path):
    from vertiscope.workspace import Workspace
    with Workspace(tmp_path / "ws") as workspace:
        workspace.index_html("<html><body><p>a page</p></body></html>",
                             "https://shop.test")
        yield workspace


@pytest.fixture()
def pool():
    """Closed however the test ends: a leaked shell is a leaked OS process."""
    p = ShellPool(timeout=30.0, max_shells=2)
    try:
        yield p
    finally:
        p.shutdown()


#: Retry a dropped LOOPBACK connection, and nothing else.
#:
#: Under a full suite running beside a sidecar and a live browser these
#: failed with `ConnectionAbortedError: [WinError 10053]` -- the connection
#: aborted by the host, not by the server. The subject of these tests is a
#: permission decision, not the reliability of a socket, and a flake here
#: trains a reader to scroll past red.
#:
#: What it does NOT hide: an HTTP status. A 403 is returned, not retried, so
#: every assertion about a refusal still has to hold.
def _with_retry(call, attempts=3):
    import time
    last = None
    for attempt in range(attempts):
        try:
            return call()
        except urllib.error.HTTPError:
            raise                       # a status is an answer, not a failure
        except (ConnectionError, OSError) as exc:
            last = exc
            time.sleep(0.25 * (attempt + 1))
    raise last


def _post(port, body, path="/shell"):
    req = urllib.request.Request(
        "http://127.0.0.1:%d%s" % (port, path), method="POST",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    try:
        return 200, json.load(_with_retry(
            lambda: urllib.request.urlopen(req, timeout=60)))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode())


def _get(port, path):
    return json.load(_with_retry(
        lambda: urllib.request.urlopen(
            "http://127.0.0.1:%d%s" % (port, path), timeout=30)))


#: **Port 0, so the OS picks.** These bound 8821..8834 by hand, and a
#: fixed port is a shared resource: two of them failed in a full run
#: while passing in isolation, because a sidecar was restarting beside
#: the suite. A flaky test is worse than a missing one -- it trains a
#: reader to scroll past red. `serve` returns the server, and
#: `server.server_address[1]` is the port it actually got.
def _port(server):
    return server.server_address[1]


def _stop(server):
    server.shutdown()
    for attr in ("kernel_pool", "shell_pool"):
        p = getattr(server, attr, None)
        if p is not None:
            p.shutdown()
    server.server_close()


def _a_shell_exists():
    return bool(interpreters()["shells"])


needs_shell = pytest.mark.skipif(
    not _a_shell_exists(),
    reason="no shell on PATH; there is nothing for a terminal to drive")


# --- discovery --------------------------------------------------------------


def test_discovery_reports_this_machine_not_a_fixed_list():
    """`P-N2`'s switch is populated from what is installed.

    A hardcoded list is wrong on every machine but the author's, and wrong
    SILENTLY: it offers a shell that is not there and fails at the first
    command.
    """
    found = interpreters()
    assert found["python"], "the interpreter running this is always available"
    assert found["python"][0]["runnable"] is True
    # Every reported shell resolves to a real path -- that is what `shutil.which`
    # is for, and it is the difference between discovery and a guess.
    for shell in found["shells"]:
        assert shell["path"], shell


def test_jupyter_kernels_are_reported_but_not_claimed_runnable():
    """Honest in both directions.

    `P-N2` names Jupyter kernels, so a reader should see what is installed. But
    this sidecar drives a subprocess, not the Jupyter protocol, and marking them
    runnable would be exactly the claim `P-N1` is still `Partial` for.
    """
    for kernel in interpreters()["jupyter_kernels"]:
        assert kernel["runnable"] is False, kernel


# --- the session ------------------------------------------------------------


@needs_shell
def test_state_persists_between_commands_in_one_pane(pool):
    """The whole reason for a persistent process rather than one run per command.

    `cd` is the visible case; an activated virtualenv and exported variables are
    the ones that hurt to lose.
    """
    first = pool.run("p1", "cd C:/Windows" if _is_windows() else "cd /tmp")
    assert first["ok"], first
    where = pool.run("p1", "(Get-Location).Path" if _is_windows() else "pwd")
    assert where["ok"], where
    assert "Windows" in where["output"] or "tmp" in where["output"], where


@needs_shell
def test_two_panes_do_not_share_a_session(pool):
    """The pane is the boundary, as the note is the kernel's.

    The non-vacuity partner of the test above: one shared shell would pass that
    one and fail this, and a shell per COMMAND would fail that and pass this.
    """
    pool.run("p1", "cd C:/Windows" if _is_windows() else "cd /tmp")
    other = pool.run("p2", "(Get-Location).Path" if _is_windows() else "pwd")
    assert other["ok"], other
    assert "Windows" not in other["output"], other


def _is_windows():
    import os
    return os.name == "nt"


@needs_shell
def test_a_command_that_fails_still_returns_its_output(pool):
    """A non-zero exit is not a broken terminal.

    The shell stays up and the error text is what the reader needs; treating it
    as a dead session would throw away their working directory over a typo.
    """
    reply = pool.run("p1", "thiscommanddoesnotexist")
    assert reply["ok"], reply          # the SHELL ran; the command did not
    assert reply["output"], "the shell's complaint is the useful part"
    after = pool.run("p1", "echo still-here")
    assert after["ok"] and "still-here" in after["output"]


# --- what it refuses --------------------------------------------------------


def test_a_tui_program_is_named_before_it_is_run():
    assert needs_a_terminal("vim notes.txt") == "vim"
    assert needs_a_terminal("HTOP") == "htop"
    assert needs_a_terminal("git status") == ""
    assert needs_a_terminal("") == ""


@needs_shell
def test_refusing_a_tui_program_does_not_cost_the_session(pool):
    """A refusal is not a death, and the first version got this wrong.

    `ShellError` was raised from inside `run()`, the pool treats every
    `ShellError` as a dead shell, and asking for `vim` silently threw away a
    session with the reader's `cd` in it. The check moved to the pool, before
    the command reaches a shell.
    """
    pool.run("p1", "cd C:/Windows" if _is_windows() else "cd /tmp")
    before = pool.run("p1", "(Get-Location).Path" if _is_windows() else "pwd")
    refused = pool.run("p1", "vim notes.txt")
    assert refused["ok"] is False and refused.get("refused") is True, refused
    after = pool.run("p1", "(Get-Location).Path" if _is_windows() else "pwd")
    assert after["output"] == before["output"], (before, after)


# --- the gate ---------------------------------------------------------------


def test_the_terminal_is_off_unless_the_server_was_asked_for_a_kernel(ws):
    """One flag for both, and the reason is not laziness.

    A second flag would imply a distinction that does not exist: a Python kernel
    can already call `subprocess.run`, so a reader who enabled it has shell
    access whether or not a terminal pane exists. A permission that looks
    meaningful and is not is worse than no permission at all.
    """
    server = serve(ws, port=0, block=False)
    try:
        code, body = _post(_port(server), {"pane": "p1", "command": "echo hi"})
        assert code == 403
        assert body["error"] == "shell is off"
        assert "--kernel" in body["detail"]
    finally:
        _stop(server)


@needs_shell
def test_the_kernel_flag_opens_the_terminal_too(ws):
    server = serve(ws, port=0, block=False, kernel=True)
    try:
        ok, body = _post(_port(server), {"pane": "p1", "command": "echo hello-terminal"})
        assert ok == 200 and body["ok"], body
        assert "hello-terminal" in body["output"], body
    finally:
        _stop(server)


def test_the_pane_is_required_because_it_is_the_boundary(ws):
    server = serve(ws, port=0, block=False, kernel=True)
    try:
        code, body = _post(_port(server), {"command": "echo hi"})
        assert code == 400 and body["error"] == "missing pane"
    finally:
        _stop(server)


def test_interpreters_answer_even_when_the_kernel_is_off(ws):
    """A panel should be able to say what WOULD be available.

    Gating discovery behind the flag would make an off kernel and an empty
    machine look the same from the pane.
    """
    server = serve(ws, port=0, block=False)
    try:
        found = _get(_port(server), "/interpreters")
        assert found["python"], found
    finally:
        _stop(server)
