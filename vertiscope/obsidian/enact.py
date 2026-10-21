"""Drive the live page from an address in the vault.

The whole bridge up to here is read-only by construction: the sidecar has no
route that mutates anything, the MCP server exposes no tool that acts, and the
surface reports the address it WOULD press rather than pressing it. This is
the one module that acts, and it is built so that saying so stays true --
everything else keeps its property, and the write path is a door with a lock
rather than a capability that leaked in sideways.

Four gates, and each exists because the one before it is not enough.

**The server flag.** `serve(..., enact=True)`, off by default and set from the
command line. A plugin setting cannot be the gate: it is a client asserting
something about itself, and the client is a page renderer in an app the user
installs plugins into. The process that owns the browser decides.

**The refusal set.** `live._refuse_check`, mirrored from `sensor.js` and
tested against it. It raises rather than returning a no-op, for the reason
recorded there: "a model that cannot tell a refusal from a completed action
will believe it signed in." Sign-in, checkout, delete, publish, send, consent
-- the whole never-press list applies here exactly as it does in the REPL.

**The address, not a selector.** A caller names a `url:xpath:taxonomy:content`
address that the store already holds. It cannot hand over arbitrary
JavaScript, an arbitrary selector, or a url the workspace never scanned: the
address is looked up, and an address that is not in the store is refused. The
patricia trie is the vocabulary of what can be touched.

**Same page only, unless told otherwise.** Enacting navigates to the address's
own page if the browser is elsewhere, and that navigation is refusal-checked
too. It will not follow a redirect chain somewhere else and keep acting.
"""

from __future__ import annotations

from typing import Dict, Optional

#: Actions a caller may name. Deliberately small: this is the surface an
#: untrusted-ish caller reaches, and every entry is something the REPL already
#: does through a tested path.
ACTIONS = ("press", "type", "read")

#: What a PANEL may ask to have done to the page the reader is looking at, and
#: the in-page tick (`sensor.js` `perform`) each one becomes.
#:
#: `toggle` is a click on purpose: a checkbox's own activation behaviour sets
#: its state and fires `input`/`change` exactly as the reader's would, where
#: writing `.checked` and then clicking would toggle twice.
PLAN_KINDS = {"press": "click", "toggle": "click", "type": "type",
              "choose": "choose"}


class EnactError(RuntimeError):
    """Refused, unavailable, or not found -- never a silent failure."""


def enact(workspace,
          address_key: str,
          action: str = "press",
          text: Optional[str] = None,
          *,
          allow_navigation: bool = True) -> Dict:
    """Act on one addressed element of a live page, and say what happened.

    Returns a report rather than a page: the caller is a plugin in another
    process and cannot hold a `Node`. `url` is read back from the driver
    afterwards, so a press that navigated says where it landed.
    """
    if action not in ACTIONS:
        raise EnactError("unknown action %r; expected one of %s"
                         % (action, ", ".join(ACTIONS)))
    # Argument validation before anything is acquired. `type` without text was
    # checked after the driver was up and the page navigated to, so a caller
    # who simply forgot the text booted Firefox and loaded a page to be told
    # so. Nothing that can be decided from the request alone may have a side
    # effect.
    if action == "type" and text is None:
        raise EnactError("type needs text")

    from ..address import ContentAddress
    from .. import live

    try:
        address = ContentAddress.parse(address_key)
    except Exception as exc:                        # noqa: BLE001
        raise EnactError("unparseable address: %s" % exc) from exc

    # The address has to be one the store already holds. This is the gate that
    # stops a caller naming any xpath on any url: the workspace is the list of
    # places that can be touched, and it was built by scanning, not by asking.
    known = workspace.store.address(address.aid)
    if known is None:
        raise EnactError(
            "address is not in this workspace; only scanned pages can be "
            "enacted on")
    stored, value = known

    # Refuse BEFORE anything is touched.
    #
    # The stored address already carries what the refusal set reads -- the
    # page's own words for this element, and its destination -- so a
    # never-press action can be turned down without booting a browser, without
    # a network request, and without navigating. An earlier ordering acquired
    # the driver first and only then checked, which meant refusing a "Sign in"
    # button still opened Firefox and loaded the page it was on: the refusal
    # held, and the side effect it exists to prevent had already happened.
    #
    # Checked again below against the LIVE label, because the stored value can
    # be stale and the element under the xpath now may not be the element the
    # fold recorded.
    if action != "read":
        live._refuse_check(str(value or "")[:80],
                           value if stored.is_url else "")
        live._refuse_check("", address.url)

    driver = live._S.need_driver()
    here = ""
    try:
        here = driver.current_url or ""
    except Exception:                               # noqa: BLE001
        pass
    if not live.same_page(here, address.url):
        if not allow_navigation:
            raise EnactError("browser is on %s, not %s" % (here, address.url))
        live._refuse_check("", address.url)
        driver.get(address.url)
        import time as _t
        _t.sleep(1.2)
        live._S.fold(driver.current_url or address.url)

    node = live._S.cursor
    if node is None:
        raise EnactError("no fold for %s" % address.url)

    target = live.Node(_find(address.xpath))
    label = target.text() if hasattr(target, "text") else ""

    if action == "read":
        return _report(driver, address, "read", str(target.read()))

    # The refusal set again, now on what the page currently says. The stored
    # value can be stale, and the element under this xpath now may not be the
    # element the fold recorded.
    live._refuse_check(str(label)[:80], "")

    if action == "type":
        target.type(text)
        return _report(driver, address, "type", "typed %d chars" % len(text))

    target.press()
    return _report(driver, address, "press",
                   "followed the target" if live._S.clicked_via_href
                   else "clicked")


def _find(xpath: str):
    """The trie node at an xpath in the current fold.

    Looked up in the FOLD rather than by asking the driver directly, so that
    what is pressed is what the vault was shown. A selector resolved fresh
    against the live DOM can name an element the fold never had -- an overlay
    that appeared since, a consent wall -- and then the surface and the action
    are talking about two different pages.

    `live._find_by_xpath` is the REPL's own lookup, reused rather than
    reimplemented: it walks `_dom_children` and matches `_xpath_cache`, which
    is the spelling the fold actually stores, and a second implementation
    would drift from it exactly where the two disagree.
    """
    from .. import live

    spine = live._S.spine
    if spine is None:
        raise EnactError("no page is folded")
    found = live._find_by_xpath(live._page_root(spine.trie), xpath)
    if found is None:
        raise EnactError("xpath %s is not in the current fold" % xpath)
    return found


def _report(driver, address, did: str, detail: str) -> Dict:
    landed = ""
    try:
        landed = driver.current_url or ""
    except Exception:                               # noqa: BLE001
        pass
    return {"ok": True, "did": did, "detail": detail,
            "address": address.key(), "url": landed}


def plan(workspace, address_key: str, action: str = "press",
         text: Optional[str] = None) -> Dict:
    """Adjudicate one panel gesture and DRIVE NOTHING.

    The panel acts on the page in the browser CELL, which the reader is
    looking at -- not on the headless Firefox `enact` above drives. The cell
    belongs to the plugin process, so this process cannot press anything in
    it; what it can still own is the decision. A plugin setting is not a gate
    (see the module docstring), so the gates that did not need a driver are
    run HERE and the plugin gets back only what it is allowed to touch:

    1. the address parses and is one the trie holds (`store.address`) -- the
       trie is the vocabulary of what can be touched, so the xpath that comes
       back is the stored one and the caller cannot name another;
    2. the refusal set (`live._refuse_check`) on the stored label and href and
       on the page's own url, BEFORE the cell navigates anywhere;
    3. the action is one of `PLAN_KINDS`, and `type`/`choose` carry a value.

    The server flag (gate one) is the route's, as for `/enact`. The in-page
    half of the refusal set (`sensor.js` `refused`) is checked again at press
    time against what the element says NOW, which is what `enact` does with
    the live label.

    Refusals are `EnactError`, so the route answers 409 `{refused: true}` for
    both this and `enact`.
    """
    if action not in PLAN_KINDS:
        raise EnactError("unknown action %r; expected one of %s"
                         % (action, ", ".join(sorted(PLAN_KINDS))))
    if action in ("type", "choose") and text is None:
        raise EnactError("%s needs a value" % action)

    from ..address import ContentAddress
    from .. import live

    try:
        address = ContentAddress.parse(address_key)
    except Exception as exc:                        # noqa: BLE001
        raise EnactError("unparseable address: %s" % exc) from exc

    known = workspace.store.address(address.aid)
    if known is None:
        raise EnactError(
            "address is not in this workspace; only scanned pages can be "
            "enacted on")
    stored, value = known

    try:
        live._refuse_check(str(value or "")[:80],
                           value if stored.is_url else "")
        live._refuse_check("", address.url)
    except live.Refused as exc:
        raise EnactError(str(exc)) from exc

    return {"ok": True, "did": "plan", "action": action,
            "kind": PLAN_KINDS[action], "address": address.key(),
            "url": address.url, "xpath": address.xpath,
            "label": str(value or "")[:80]}
