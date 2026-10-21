"""The write path, and the four gates that keep it shut.

Everything else in the bridge is read-only by construction: no GET route
mutates anything, the MCP server exposes no tool that acts, and the surface
reports the address it WOULD press. This is the one module that acts, so the
tests are about refusing, not about driving. Driving needs a browser; refusing
must not.
"""

import json
import pathlib
import tempfile
import urllib.error
import urllib.request

import pytest

from vertiscope.obsidian.enact import ACTIONS, EnactError, enact
from vertiscope.obsidian.sidecar import serve


PAGE = ("<html><body><h1>Shop</h1>"
        "<p>a paragraph of ordinary words</p>"
        "<a href='/help.html'>Read the help</a>"
        "<a href='/accounts/login'>Sign in</a>"
        "</body></html>")


@pytest.fixture()
def ws(tmp_path):
    from vertiscope.workspace import Workspace
    with Workspace(tmp_path / "ws") as workspace:
        workspace.index_html(PAGE, "https://shop.test")
        yield workspace


#: Port 0, so the OS picks, and a retry for a dropped LOOPBACK connection.
#:
#: Both for the reason the other two sidecar test files carry them: a fixed
#: port is a shared resource, and under a full suite running beside a sidecar
#: and a live browser these failed with `ConnectionAbortedError: [WinError
#: 10053]` -- aborted by the host, not answered by the server.
#:
#: This file was missed when the other two were fixed, because it passes its
#: port POSITIONALLY: a grep for `port=88NN` does not see `_serve(ws, 8811)`.
#:
#: What the retry does NOT hide is an HTTP status. A 403 is returned rather
#: than retried, so every assertion about a refusal still has to hold.
def _port(server):
    return server.server_address[1]


def _with_retry(call, attempts=3):
    import time
    last = None
    for attempt in range(attempts):
        try:
            return call()
        except urllib.error.HTTPError:
            raise
        except (ConnectionError, OSError) as exc:
            last = exc
            time.sleep(0.25 * (attempt + 1))
    raise last


def _health(server, timeout=10):
    return json.load(_with_retry(lambda: urllib.request.urlopen(
        "http://127.0.0.1:%d/health" % _port(server), timeout=timeout)))


def _post(port, body):
    req = urllib.request.Request(
        "http://127.0.0.1:%d/enact" % port, method="POST",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    try:
        return 200, json.load(_with_retry(
            lambda: urllib.request.urlopen(req, timeout=15)))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode())


def _serve(ws, port, **kw):
    return serve(ws, port=port, block=False, **kw)


# --- gate one: the server flag ---------------------------------------------------

def test_enact_is_off_unless_the_server_was_asked_for_it(ws):
    """A plugin setting cannot be the gate.

    That is a client asserting something about itself, and the client is a
    page renderer inside an app the user installs plugins into. The process
    that owns the browser decides.
    """
    server = _serve(ws, 0)
    try:
        health = _health(server)
        assert health["enact"] is False
        code, body = _post(_port(server), {"address": "anything"})
        assert code == 403
        # Named, not a bare 403: a caller that cannot tell "off" from "failed"
        # will retry forever.
        assert "enact is off" in body["error"]
        assert "--enact" in body["detail"]
    finally:
        server.shutdown(); server.server_close()


def test_the_flag_is_advertised_so_a_surface_can_stay_read_only(ws):
    """Otherwise the plugin offers a button that 403s."""
    server = _serve(ws, 0, enact=True)
    try:
        health = _health(server)
        assert health["enact"] is True
    finally:
        server.shutdown(); server.server_close()


# --- gate two: the address must be one the store holds ---------------------------

def test_an_address_the_workspace_never_scanned_is_refused(ws):
    """The trie is the vocabulary of what can be touched.

    A caller cannot hand over an arbitrary selector or an arbitrary url: the
    address is looked up, and the workspace was built by scanning.
    """
    with pytest.raises(EnactError):
        enact(ws, "not-an-address-key")


def test_a_well_formed_address_that_is_not_stored_is_refused(ws):
    from vertiscope.address import ContentAddress

    stranger = ContentAddress(url="https://elsewhere.test/",
                              xpath="/html/body/a", tag="urls.internal",
                              accessor="href")
    with pytest.raises(EnactError) as caught:
        enact(ws, stranger.key())
    assert "not in this workspace" in str(caught.value)


# --- gate three: the refusal set, without booting a browser ----------------------

def _address_of(ws, phrase):
    for chunk in ws.store.chunks("https://shop.test"):
        for address, value in ws.store.addresses_of(chunk.cid):
            if phrase.lower() in (value or "").lower():
                return address
    return None


def test_a_never_visit_target_is_refused_before_any_browser_opens(ws):
    """Refusing must not have the side effect it exists to prevent.

    An earlier ordering acquired the driver first and checked second, so
    refusing a sign-in link still opened Firefox and loaded the page it was
    on: the refusal held, and the harm it exists to prevent had already
    happened. There is no browser here, so a regression FAILS rather than
    passing slowly.
    Matched on the HREF, not the label. `addresses_of` is the positional
    anchor list -- one address per line -- and an anchor's words are not in
    it; `/accounts/login` is exactly what `_NEVER_HREF` is written for. The
    first version of this test looked for the label "sign in", found nothing,
    and skipped, which is a safety test that reports success by not running.
    """
    from vertiscope.live import Refused

    address = _address_of(ws, "/accounts/login")
    assert address is not None, "the fixture must yield a sign-in href"
    with pytest.raises((Refused, EnactError)) as caught:
        enact(ws, address.key())
    assert "never-visit" in str(caught.value) or \
           "never-press" in str(caught.value), str(caught.value)


def test_an_ordinary_target_is_not_refused(ws, monkeypatch):
    """The refusal set must not be so broad that nothing is actionable.

    A suite that only ever sees refusals cannot tell a working gate from one
    stuck shut. `/help.html` has to get PAST the refusal and stop at the next
    step.

    The driver is stubbed to raise rather than left to fail on its own: the
    honest version of this test launched Firefox, waited for it to fail to
    resolve a fake host, and took seven seconds to assert one boolean. What
    is being tested is the ORDER of two checks, and that needs no browser.
    """
    from vertiscope import live

    reached = {}

    def no_driver():
        reached["past_refusal"] = True
        raise RuntimeError("no driver in this test")

    monkeypatch.setattr(live._S, "need_driver", no_driver)

    address = _address_of(ws, "/help.html")
    assert address is not None
    with pytest.raises(Exception):
        enact(ws, address.key())
    assert reached.get("past_refusal"), \
        "an ordinary link was refused before the driver was ever asked for"


# --- the surface of the thing ----------------------------------------------------

def test_the_action_list_is_small_and_closed(ws):
    assert set(ACTIONS) == {"press", "type", "read"}
    with pytest.raises(EnactError):
        enact(ws, "x", "execute_script")


def test_type_without_text_is_refused(ws):
    address = _address_of(ws, "ordinary words")
    if address is None:
        pytest.skip("no text address in the fixture")
    with pytest.raises(EnactError) as caught:
        enact(ws, address.key(), "type")
    assert "needs text" in str(caught.value)


# --- the panel's road: plan, adjudicated here, carried out in the cell -----------
#
# A panel gesture acts on the page in the browser CELL, which this process
# cannot press anything in. `plan` keeps the gates that need no driver and
# drives nothing, so every one of these runs without a browser -- and a
# regression that booted one would fail loudly rather than slowly.

def _no_driver(monkeypatch):
    from vertiscope import live

    def boom():
        raise AssertionError("a plan must not acquire a driver")

    monkeypatch.setattr(live._S, "need_driver", boom)


def test_plan_hands_back_the_stored_xpath_and_drives_nothing(ws, monkeypatch):
    """The ordinary link gets PAST every gate -- the gate is not stuck shut."""
    from vertiscope.obsidian.enact import plan

    _no_driver(monkeypatch)
    address = _address_of(ws, "/help.html")
    assert address is not None
    got = plan(ws, address.key(), "press")
    assert got["ok"] and got["kind"] == "click"
    # What comes back is the TRIE's xpath and url, not anything the caller said.
    assert got["xpath"] == address.xpath and got["url"] == address.url


def test_plan_refuses_a_never_visit_target_before_the_cell_moves(ws, monkeypatch):
    """The planted defect is caught: the sign-in href is refused, and by name."""
    from vertiscope.obsidian.enact import plan

    _no_driver(monkeypatch)
    address = _address_of(ws, "/accounts/login")
    assert address is not None, "the fixture must yield a sign-in href"
    with pytest.raises(EnactError) as caught:
        plan(ws, address.key(), "press")
    assert "never-visit" in str(caught.value) or \
           "never-press" in str(caught.value), str(caught.value)


def test_plan_refuses_an_address_the_trie_does_not_hold(ws):
    from vertiscope.address import ContentAddress
    from vertiscope.obsidian.enact import plan

    stranger = ContentAddress(url="https://shop.test/", xpath="/html/body/a[9]",
                              tag="urls.internal", accessor="href")
    with pytest.raises(EnactError) as caught:
        plan(ws, stranger.key(), "press")
    assert "not in this workspace" in str(caught.value)


def test_plan_vocabulary_is_closed_and_values_are_required(ws):
    from vertiscope.obsidian.enact import PLAN_KINDS, plan

    assert set(PLAN_KINDS) == {"press", "toggle", "type", "choose"}
    address = _address_of(ws, "/help.html")
    with pytest.raises(EnactError):
        plan(ws, address.key(), "execute_script")
    for needs in ("type", "choose"):
        with pytest.raises(EnactError) as caught:
            plan(ws, address.key(), needs)
        assert "needs a value" in str(caught.value)


def test_plan_route_is_behind_the_same_flag_and_answers_409_for_a_refusal(ws):
    address = _address_of(ws, "/accounts/login")
    ok_address = _address_of(ws, "/help.html")
    off = _serve(ws, 0)
    try:
        code, body = _post(_port(off), {"mode": "plan", "address": ok_address.key()})
        assert code == 403 and "enact is off" in body["error"]
    finally:
        off.shutdown(); off.server_close()
    on = _serve(ws, 0, enact=True)
    try:
        code, body = _post(_port(on), {"mode": "plan", "address": ok_address.key()})
        assert code == 200 and body["xpath"] == ok_address.xpath
        code, body = _post(_port(on), {"mode": "plan", "address": address.key()})
        assert code == 409 and body["refused"] is True
    finally:
        on.shutdown(); on.server_close()
