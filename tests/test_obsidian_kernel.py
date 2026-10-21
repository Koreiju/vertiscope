"""The notebook kernel: per-note state, a gate, and a cell that will not stop.

`NOTEBOOK_PANEL_DESIGN` §6 step 3's "done when" is one sentence — *two cells
share a variable; two notes do not* — and that is the first two tests here.
Everything after them is about the ways this can go wrong quietly, because the
capability is the largest in the bridge: `enact` presses a button in a browser,
this runs arbitrary Python with the sidecar's own privileges.

So the gate gets the same treatment `test_obsidian_enact.py` gives its own: the
default is refusal, the refusal is NAMED, and the flag lives on the server.
"""

import json
import urllib.error
import urllib.request

import pytest

from vertiscope.obsidian.kernel import KernelPool
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
    """A pool with a short timeout, closed however the test ends.

    Not closing it leaks a Python interpreter per note into the test run, and a
    suite that leaks them gets slower for reasons nothing in the output explains.
    """
    p = KernelPool(timeout=6.0, max_kernels=2)
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


def _post(port, body, path="/kernel"):
    req = urllib.request.Request(
        "http://127.0.0.1:%d%s" % (port, path), method="POST",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    try:
        return 200, json.load(_with_retry(
            lambda: urllib.request.urlopen(req, timeout=30)))
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
    if getattr(server, "kernel_pool", None) is not None:
        server.kernel_pool.shutdown()
    server.server_close()


# --- step 3's actual bar ----------------------------------------------------


def test_two_cells_in_one_note_share_state(pool):
    assert pool.run("a.md", "x = 41")["ok"]
    reply = pool.run("a.md", "x + 1")
    assert reply["ok"], reply.get("error")
    assert reply["value"] == "42", reply


def test_two_notes_do_not_share_state(pool):
    """The isolation boundary is the NOTE.

    The non-vacuity partner of the test above: a pool that shared one namespace
    for everything would pass that one and fail this one, and a pool that made
    a fresh namespace per CELL would fail that one and pass this.
    """
    pool.run("a.md", "x = 41")
    reply = pool.run("b.md", "'x' in dir()")
    assert reply["ok"], reply.get("error")
    assert reply["value"] == "False", reply


# --- what a cell produces ---------------------------------------------------


def test_stdout_is_captured_and_a_trailing_expression_is_evaluated(pool):
    """Both, from one cell, because a notebook does both.

    `print` goes to `stdout`; a final expression becomes `value`, which is what
    makes `df.describe()` on the last line show something.
    """
    reply = pool.run("a.md", "print('hello')\n2 ** 10")
    assert reply["stdout"] == "hello\n", reply
    assert reply["value"] == "1024", reply


def test_a_statement_cell_reports_no_value(pool):
    """`None` is not a value worth showing.

    Every statement-like call returns it, and printing "None" after each one is
    noise a reader has to learn to ignore.
    """
    reply = pool.run("a.md", "y = 1")
    assert reply["ok"] and reply["value"] is None, reply


def test_an_error_is_reported_and_the_kernel_survives_it(pool):
    """A traceback must not cost the namespace.

    A kernel that died on every mistake would make a notebook unusable, and the
    variables built up before the mistake are exactly what the reader needs to
    debug it.
    """
    pool.run("a.md", "keep = 7")
    bad = pool.run("a.md", "1 / 0")
    assert not bad["ok"]
    assert "ZeroDivisionError" in bad["error"], bad
    after = pool.run("a.md", "keep")
    assert after["ok"] and after["value"] == "7", after


def test_a_cell_writing_to_the_real_stdout_does_not_kill_the_kernel(pool):
    """The reply shares stdout with the cell, so replies are MARKED.

    A cell that reaches past the redirect to `sys.__stdout__` emits an unmarked
    line. Unmarked lines are noise and are skipped; without that, this cell
    would be read as a malformed reply and the kernel would be declared dead.
    """
    reply = pool.run("a.md",
                     "import sys; sys.__stdout__.write('raw\\n'); 5")
    assert reply["ok"], reply.get("error")
    assert reply["value"] == "5", reply


# --- the ways it must fail ---------------------------------------------------


def test_a_runaway_cell_is_killed_and_says_the_state_is_gone(pool):
    """A blocking `readline` cannot enforce a deadline, so a watchdog does.

    The first version checked the clock between reads, and `while True: pass`
    produces exactly one read that never returns — it hung indefinitely with a
    2s timeout set. This asserts the kill happens AND that the loss of state is
    reported, because a silently-empty namespace reads as a bug in the note.
    """
    pool.run("n.md", "survivor = 1")
    reply = pool.run("n.md", "while True: pass")
    assert not reply["ok"]
    assert "TimeoutError" in reply["error"], reply
    assert "state lost" in reply.get("kernel", ""), reply
    # And the replacement really is fresh.
    after = pool.run("n.md", "'survivor' in dir()")
    assert after["value"] == "False", after


def test_the_least_recently_used_kernel_is_retired_by_name(pool):
    """The cap is what stops a vault of notes becoming a vault of interpreters.

    `evicted` names whose state went, because the reader whose variables just
    vanished is not the reader who caused it.
    """
    import time
    pool.run("a.md", "v = 1"); time.sleep(0.05)
    pool.run("b.md", "v = 2"); time.sleep(0.05)
    reply = pool.run("c.md", "v = 3")           # max_kernels is 2
    assert reply.get("evicted") == "a.md", reply
    live = {k["note"] for k in pool.status()["kernels"]}
    assert live == {"b.md", "c.md"}, live


def test_restart_drops_the_namespace(pool):
    pool.run("a.md", "gone = 1")
    assert pool.restart("a.md") is True
    assert pool.run("a.md", "'gone' in dir()")["value"] == "False"
    # A note with no kernel is not an error, it is nothing to do.
    assert pool.restart("never-opened.md") is False


# --- the gate ---------------------------------------------------------------


def test_the_kernel_is_off_unless_the_server_was_asked_for_it(ws):
    """The default, and the most important test in the file.

    Running code from a note is the largest capability here. A plugin setting
    cannot be the gate: that is a client asserting something about itself, and
    the client is a page renderer in an app the user installs plugins into.
    """
    server = serve(ws, port=0, block=False)
    try:
        assert _get(_port(server), "/health")["kernel"] is False
        code, body = _post(_port(server), {"note": "a.md", "code": "1 + 1"})
        assert code == 403
        # Named, not bare: a caller that cannot tell "off" from "failed" retries
        # forever, and the panel should draw the button unavailable, not broken.
        assert body["error"] == "kernel is off"
        assert "--kernel" in body["detail"]
    finally:
        _stop(server)


def test_health_advertises_the_kernel_when_it_is_on(ws):
    server = serve(ws, port=0, block=False, kernel=True, kernel_timeout=6)
    try:
        assert _get(_port(server), "/health")["kernel"] is True
        ok, body = _post(_port(server), {"note": "a.md", "code": "6 * 7"})
        assert ok == 200 and body["value"] == "42", body
    finally:
        _stop(server)


def test_enact_and_kernel_are_separate_permissions(ws):
    """One does not imply the other, in either direction.

    A reader who wanted a notebook did not thereby ask for a vault that can
    drive the web, and a reader who wanted click-through did not ask for code
    execution. Gating both on one flag would grant whichever they did not want.
    """
    server = serve(ws, port=0, block=False, kernel=True)
    try:
        health = _get(_port(server), "/health")
        assert health["kernel"] is True and health["enact"] is False
        # `enact` is still shut, on a server whose kernel is open.
        code, body = _post(_port(server), {"address": "x", "action": "press"},
                           path="/enact")
        assert code == 403 and body["error"] == "enact is off"
    finally:
        _stop(server)


def test_the_note_is_required_because_it_is_the_boundary(ws):
    """Defaulting it would put every cell in the vault in one namespace.

    That is the failure this design exists to prevent, and it would surface as a
    mysterious name collision between unrelated notes rather than as a missing
    field.
    """
    server = serve(ws, port=0, block=False, kernel=True)
    try:
        code, body = _post(_port(server), {"code": "1"})
        assert code == 400 and body["error"] == "missing note"
    finally:
        _stop(server)


def test_a_non_python_language_is_refused_by_name(ws):
    """Step 3 is python. Running python and calling it bash would be worse than
    refusing, because the reader would debug the wrong interpreter."""
    server = serve(ws, port=0, block=False, kernel=True)
    try:
        code, body = _post(_port(server), {"note": "a.md", "code": "echo hi",
                                  "lang": "bash"})
        assert code == 400 and "bash" in body["error"], body
    finally:
        _stop(server)
