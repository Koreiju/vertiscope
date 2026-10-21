"""The callable interface is model-driven, so it must refuse what the fold does.

`refused()` lives in `sensor.js` and gates the autonomous scroller: labels
matching sign-in, checkout, buy, delete; hrefs under `/accounts`, `/billing`;
any form holding a password, card, cvv, ssn or one-time-code field; any open
`<dialog>`, because a modal is a decision.

`vertiscope.live` is driven by a language model pressing things by name. That is
precisely the case the denylist was written for, and until this module existed
it was the case the denylist did not cover -- the JS rules were unreachable
from Python, where the pressing now happens.

So the patterns are mirrored, and mirrored patterns drift. `test_affordance`
already holds `INTERACTIVE_KIND` against its JavaScript original for the same
reason: a silent divergence would not fail anything, it would just quietly
start answering a different question. These tests hold the two copies
together and hold the refusal itself to raising rather than returning.
"""

import io
import pathlib
import re

import pytest

from vertiscope.live import Refused, _NEVER_HREF, _NEVER_LABEL, _refuse_check

ROOT = pathlib.Path(__file__).resolve().parent.parent
SENSOR = ROOT / "vertiscope" / "core" / "js" / "sensor.js"


def _js_pattern(name: str) -> str:
    """The regex source of a `var NAME = new RegExp(...)` in the sensor."""
    js = io.open(SENSOR, encoding="utf-8").read()
    at = js.index("var %s = new RegExp(" % name)
    depth, out, started = 0, [], False
    for ch in js[at:]:
        if ch == "(":
            depth += 1
            started = True
            if depth == 1:
                continue
        elif ch == ")":
            depth -= 1
            if depth == 0:
                break
        if started:
            out.append(ch)
    body = "".join(out)
    # The JS source is a concatenation of single-quoted string literals with a
    # trailing flags argument: `new RegExp('a' + 'b', 'i')`. The flags are a
    # quoted literal too, so taking every literal appended an `i` to the
    # pattern and both mirror tests failed on a difference that was the
    # test's own parsing.
    parts = re.findall(r"'((?:[^'\\]|\\.)*)'", body)
    if parts and re.fullmatch(r"[gimsuy]{1,4}", parts[-1]):
        parts = parts[:-1]
    return "".join(parts).replace("\\\\", "\\")


# --- the two copies must say the same thing ----------------------------------


def test_the_label_denylist_matches_the_sensor():
    assert _js_pattern("NEVER_LABEL") == _NEVER_LABEL.pattern


def test_the_href_denylist_matches_the_sensor():
    assert _js_pattern("NEVER_HREF") == _NEVER_HREF.pattern


# --- and it must actually refuse ---------------------------------------------


@pytest.mark.parametrize("label", [
    "Sign in", "sign up", "Log out", "Subscribe", "Checkout", "Buy now",
    "Add to cart", "Donate", "Delete", "Submit", "Install", "Download",
])
def test_a_dangerous_label_is_refused(label):
    with pytest.raises(Refused):
        _refuse_check(label, "")


@pytest.mark.parametrize("href", [
    "https://x.test/accounts/me", "https://x.test/checkout",
    "https://x.test/billing/", "https://x.test/p?signin=1",
])
def test_a_dangerous_target_is_refused(href):
    with pytest.raises(Refused):
        _refuse_check("", href)


def test_the_refusal_names_the_rule_that_matched():
    """A model that is told only "no" learns nothing and will try again."""
    with pytest.raises(Refused) as caught:
        _refuse_check("Sign in to continue", "")
    assert "sign in" in str(caught.value).lower()


def test_a_refusal_is_raised_and_not_returned():
    """Returning a falsy value would let a caller that ignores the result
    believe the press happened. It has to interrupt."""
    assert _refuse_check("Next page", "https://x.test/page/2") is None
    with pytest.raises(Refused):
        _refuse_check("Log in", "https://x.test/page/2")


# --- and it must not refuse everything ---------------------------------------


@pytest.mark.parametrize("label,href", [
    ("Next page", "https://x.test/results?page=2"),
    ("More results", "https://x.test/search?q=ice"),
    ("Search", "https://x.test/search"),
    ("Satellite gravimetry of ice-sheet mass change", "https://nasa.gov/grace"),
])
def test_ordinary_navigation_is_allowed(label, href):
    """Non-vacuity, and the failure this rule has had before: refusing every
    form and every submit button refused the pager on the most ordinary page
    there is. A denylist that stops the reader reading is not safe, it is
    broken."""
    assert _refuse_check(label, href) is None
