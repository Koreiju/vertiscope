"""The composed tree, at the points where it is not ``childNodes``.

``test_shadow_dom.py`` establishes that the boundary is crossed. That is a
different question from whether what comes back across it is in the shape the
browser draws, and slots decide that one: a light child of a shadow host is
rendered where the ``<slot>`` that claims it sits inside the shadow root, not
where it is written, and a slot with something assigned to it does not render
its own children.

The fold walked ``shadowRoot.childNodes`` followed by ``node.childNodes``,
which is neither tree. Measured on ``tests/fixtures/composed_slots.html``
before the fix, against a reference flatten in the same page:

    rendered: HEAD-BEFORE TITLE-SLOTTED TITLE-SECOND HEAD-AFTER BODY-BEFORE
              DEFAULT-FIRST DEFAULT-SECOND BODY-AFTER EMPTY-FALLBACK
    folded:   HEAD-BEFORE TITLE-FALLBACK HEAD-AFTER BODY-BEFORE
              DEFAULT-FALLBACK BODY-AFTER EMPTY-FALLBACK TITLE-SLOTTED
              DEFAULT-FIRST TITLE-SECOND DEFAULT-SECOND

— every filled slot's fallback emitted although no reader can see it, and
every slotted node emitted below the whole shadow subtree, so a card's title
read out underneath its own footer. The markdown is ordered text; an ordering
this wrong is not a cosmetic defect.

Two layers of check, because the interesting one needs a browser:

* the source-level clause (``invariants.c1_composed_walks_resolve_slots``)
  runs everywhere and guards against the walk being quietly simplified again;
* the live tests drive the real sensor over a ``file://`` fixture and compare
  it against a reference flatten computed in the same page. They need Firefox,
  so they are gated on ``VERTISCOPE_LIVE=1`` and share ONE browser for the module.

    VERTISCOPE_LIVE=1 python -m pytest tests/test_composed_tree.py -q
"""

import os
import pathlib
import re
import time

import pytest

from vertiscope import invariants as inv

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "composed_slots.html"
BULK = ROOT / "tests" / "fixtures" / "composed_slots_bulk.html"

LIVE = pytest.mark.skipif(
    not os.environ.get("VERTISCOPE_LIVE"),
    reason="needs a real browser; set VERTISCOPE_LIVE=1")

# What the page draws, in the order it draws it. Written out here rather than
# only derived in-page, so that a reference walk which is itself wrong cannot
# quietly agree with a fold that is wrong the same way.
RENDERED = [
    "MARK-PAGE-TITLE",
    # the host: header, then section, then footer, with the light children
    # appearing at the slots that claim them
    "MARK-HEAD-BEFORE",
    "MARK-TITLE-SLOTTED",     # <span slot="title">
    "MARK-TITLE-SECOND",      # <em slot="title">, second into the same slot
    "MARK-HEAD-AFTER",
    "MARK-BODY-BEFORE",
    "MARK-DEFAULT-FIRST",     # <p>, into the unnamed slot
    "MARK-DEFAULT-SECOND",
    "MARK-BODY-AFTER",
    "MARK-EMPTY-FALLBACK",    # slot name="nobody": nothing assigned, so this
    # three shadow roots deep
    "MARK-DEPTH-1",
    "MARK-DEPTH-2",
    "MARK-DEPTH-3",
    # declarative shadow DOM, attached by the parser
    "MARK-DSD-SHADOW",
    "MARK-DSD-SLOTTED",
    "MARK-LIGHT-TAIL",
]

# Present in the page and NOT rendered: the fallback of a slot that is filled.
NEVER_RENDERED = [
    "MARK-TITLE-FALLBACK",
    "MARK-DEFAULT-FALLBACK",
    "MARK-DSD-FALLBACK",
    "MARK-CLOSED-UNREACHABLE",   # inside a closed root: unreachable by design
]

# A reference flatten, computed in the page, against which the fold is
# compared. Deliberately the textbook one — resolve the slot, prefer assigned
# nodes over fallback, descend a host through its shadow root only.
_REFERENCE_JS = r"""
var out = [];
function walk(node) {
  var kids;
  if (node.nodeType === 1 && node.shadowRoot) kids = node.shadowRoot.childNodes;
  else if (node.nodeType === 1 && node.tagName === 'SLOT') {
    var an = node.assignedNodes({flatten: true});
    kids = (an && an.length) ? an : node.childNodes;
  } else kids = node.childNodes;
  for (var i = 0; i < kids.length; i++) {
    var n = kids[i];
    if (n.nodeType === 3) {
      var t = (n.nodeValue || '').trim();
      if (t) out.push(t);
      continue;
    }
    if (n.nodeType !== 1) continue;
    if ({SCRIPT: 1, STYLE: 1, NOSCRIPT: 1, TEMPLATE: 1, HEAD: 1}[n.tagName]) continue;
    walk(n);
  }
}
walk(document.documentElement);
return out;
"""


# Every MARK- text node's element, found through shadow roots, and the
# address a hover on that element reports.
_HOVER_JS = r"""
var h = window['%s'], out = {};
function walk(root) {
  var w = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
  var n = w.currentNode;
  while (n) {
    if (n.nodeType === 3) {
      var t = (n.nodeValue || '').trim();
      if (t.indexOf('MARK-') === 0 && n.parentNode && n.parentNode.nodeType === 1) out[t] = h.hoverAddress(n.parentNode);
    } else if (n.shadowRoot) walk(n.shadowRoot);
    n = w.nextNode();
  }
}
walk(document.documentElement);
return out;
"""


def _marks(units):
    """The marker text of every unit, in the order the sensor emitted it."""
    return [(value or "").strip() for _address, value in units
            if (value or "").strip().startswith("MARK-")]


def _address_of(units, marker):
    for address, value in units:
        if (value or "").strip() == marker:
            return address.xpath
    return None


# --- the source-level clause -------------------------------------------------


def test_the_two_composed_walks_resolve_slots():
    """claim: CONTENT_EXTRACTION_RULES 8.4, and the reason there are two.

    The fold reads the page and the coverage walk audits the fold. They are
    separate code, and if they are wrong in the same way the audit reports a
    clean bill for a page neither of them read.
    """
    violations = inv.c1_composed_walks_resolve_slots()
    assert not violations, "; ".join(violations)


def test_the_clause_can_fail():
    """Or the test above proves nothing.

    The walk it rejects is the one that was there: children are ``childNodes``
    and a slot is an ordinary element.
    """
    simple = {"sensor.js/composedKids":
              "function composedKids(node) {\n"
              "    return node.childNodes;\n"
              "  }\n"}
    violations = inv.c1_composed_walks_resolve_slots(simple)
    assert any("slot assignment" in v for v in violations), violations


def test_the_fixture_holds_every_marker_the_tests_name():
    """The expectations above and the page below must not drift apart.

    A marker renamed in the fixture and not here would make the live tests
    assert over an empty list, which passes.
    """
    assert FIXTURE.exists(), f"fixture missing: {FIXTURE}"
    page = FIXTURE.read_text(encoding="utf-8")
    for marker in RENDERED + NEVER_RENDERED:
        assert marker in page, f"{marker} is not in the fixture any more"


# --- the live fold -----------------------------------------------------------


@pytest.fixture(scope="module")
def sensed():
    """One browser, one page, two drains. Every live claim reads from this.

    Module-scoped and driven through ``browser_session``, which quits in a
    ``finally``: a test module that leaks a Firefox per assertion is how a
    machine ends up with two hundred of them.
    """
    from vertiscope.browser import browser_session
    from vertiscope.config import load_config
    from vertiscope.sensing import Sensor

    url = FIXTURE.as_uri()
    with browser_session(load_config(), headless=True) as driver:
        driver.get(url)
        time.sleep(1.0)                      # custom elements upgrade
        reference = [t for t in driver.execute_script(_REFERENCE_JS)
                     if t.startswith("MARK-")]
        sensor = Sensor(driver, url, budget=400)
        sensor.boot()
        time.sleep(0.6)
        first = sensor.drain(0)

        # Resolved before anything is moved: these addresses describe the page
        # as it was at the first drain, and checking them against a page that
        # has since reordered measures the wrong thing.
        resolved = {}
        for address, value in first.units:
            text = (value or "").strip()
            if text.startswith("MARK-"):
                resolved[text] = driver.execute_script(
                    "return window['%s'].resolve(arguments[0]);" % sensor.handle,
                    _as_path(address.xpath))

        # The address a HOVER on each marker's element reports, held against
        # the fold's address for it -- and again with the light-DOM walk
        # planted, which must disagree somewhere (the fixture slots things).
        hover = {}
        for planted in (False, True):
            driver.execute_script("window['%s'].plants.lightpath = arguments[0];" % sensor.handle, planted)
            got = driver.execute_script(_HOVER_JS % sensor.handle)
            hover["planted" if planted else "clean"] = dict(got or {})
        driver.execute_script("window['%s'].plants.lightpath = false;" % sensor.handle)

        # The one mutation no MutationObserver reports: a node changes the
        # slot it is assigned to without moving in the light DOM.
        driver.execute_script("window.reassign();")
        time.sleep(0.6)
        second = sensor.drain(1)
        after = [t for t in driver.execute_script(_REFERENCE_JS)
                 if t.startswith("MARK-")]

        yield {"url": url, "reference": reference, "first": first, "hover": hover,
               "second": second, "after": after, "resolved": resolved}


def _as_path(xpath):
    """``/html/body/x/text()[1]`` -> the ``[tag, ordinal, ...]`` the handle takes.

    The sensor emits paths in that form and spells them as an xpath for the
    receiver; resolving one means spelling it back. Doing it here rather than
    exporting a second decoder keeps the test honest about the address being
    the thing that resolves, not a private handle held alongside it.
    """
    out = []
    for step in xpath.strip("/").split("/"):
        if step == "#shadow-root":
            out.extend(["#shadow-root", 1])
            continue
        ordinal = 1
        if step.endswith("]"):
            step, _, tail = step.partition("[")
            ordinal = int(tail[:-1])
        out.extend(["#text" if step == "text()" else step, ordinal])
    return out


@LIVE
def test_the_fold_reads_the_page_in_the_order_it_is_drawn(sensed):
    """claim: the composed tree is the tree the renderer composes.

    Checked against both a reference flatten computed in the page and the
    order written down in this module, because a reference walk can be wrong
    in the same way the fold is.
    """
    assert sensed["reference"] == RENDERED, (
        "the reference flatten disagrees with the expected render order — "
        "the fixture changed, or the reference walk is wrong")
    assert _marks(sensed["first"].units) == RENDERED


@LIVE
def test_a_filled_slot_does_not_contribute_its_fallback(sensed):
    """Fallback content is what renders when nothing is assigned. Emitting it
    anyway puts text in the index that no reader can ever have seen."""
    emitted = _marks(sensed["first"].units)
    for phantom in NEVER_RENDERED:
        assert phantom not in emitted, (
            f"{phantom} was emitted; it is not on the rendered page")


@LIVE
def test_an_empty_slot_does_contribute_its_fallback(sensed):
    """The other half, and the half a naive fix drops: a slot with nothing
    assigned renders its own children, and they are real content."""
    assert "MARK-EMPTY-FALLBACK" in _marks(sensed["first"].units)
    assert _address_of(sensed["first"].units, "MARK-EMPTY-FALLBACK") == (
        "/html/body/slot-host/#shadow-root/footer/slot/text()[1]")


@LIVE
def test_named_and_default_slots_claim_different_children(sensed):
    """A named slot takes only what names it; the unnamed slot takes the rest.

    Read off the addresses, not the order, so this fails distinguishably from
    the ordering test above.
    """
    units = sensed["first"].units
    head = "/html/body/slot-host/#shadow-root/header/slot/"
    body = "/html/body/slot-host/#shadow-root/section/slot/"
    assert _address_of(units, "MARK-TITLE-SLOTTED") == head + "span/text()[1]"
    assert _address_of(units, "MARK-TITLE-SECOND") == head + "em/text()[1]"
    assert _address_of(units, "MARK-DEFAULT-FIRST") == body + "p/text()[1]"
    assert _address_of(units, "MARK-DEFAULT-SECOND") == body + "p[2]/text()[1]"


@LIVE
def test_several_nodes_in_one_slot_keep_their_order(sensed):
    """Two children assigned to the same named slot render in the order they
    are written, interleaved with nothing."""
    emitted = _marks(sensed["first"].units)
    assert (emitted.index("MARK-TITLE-SLOTTED") + 1
            == emitted.index("MARK-TITLE-SECOND"))
    assert (emitted.index("MARK-DEFAULT-FIRST") + 1
            == emitted.index("MARK-DEFAULT-SECOND"))


@LIVE
def test_nested_shadow_roots_keep_their_own_ordinals(sensed):
    """claim: THEORY Def. 11.4 — the boundary is one more letter, at any depth.

    Each level puts a light ``<div>`` next to a shadow ``<div>``; one shared
    ordinal namespace would show up as ``div[2]`` somewhere down this chain.
    """
    units = sensed["first"].units
    root = "/html/body/depth-one/#shadow-root/"
    assert _address_of(units, "MARK-DEPTH-1") == root + "div/text()[1]"
    assert _address_of(units, "MARK-DEPTH-2") == (
        root + "depth-two/#shadow-root/div/text()[1]")
    assert _address_of(units, "MARK-DEPTH-3") == (
        root + "depth-two/#shadow-root/depth-three/#shadow-root/div/text()[1]")


@LIVE
def test_a_declarative_shadow_root_is_an_ordinary_shadow_root(sensed):
    """``TEMPLATE`` is in ``SKIP_TAGS``, which would be a hole if a declarative
    shadow root were still a template by the time the fold runs.

    It is not: the parser attaches it and removes the template, so what the
    fold sees is a plain ``shadowRoot`` and skipping ``<template>`` costs
    nothing. This says so out loud, because the reasoning is not obvious from
    either the skip list or the markup.
    """
    units = sensed["first"].units
    assert _address_of(units, "MARK-DSD-SHADOW") == (
        "/html/body/dsd-host/#shadow-root/div/text()[1]")
    # and its slot behaves like any other
    assert _address_of(units, "MARK-DSD-SLOTTED") == (
        "/html/body/dsd-host/#shadow-root/slot/span/text()[1]")


@LIVE
def test_a_closed_root_is_reported_rather_than_read_as_empty(sensed):
    """claim: CONTENT_EXTRACTION_RULES 8.4 — a hard boundary, not a gap.

    Reaching into a closed root means patching ``attachShadow``, which is
    detectable and is exactly what the privacy posture rules out. So the
    requirement is not to read it; it is for the count to say we could not,
    because a component we cannot see into and a component with nothing in it
    are otherwise the same number.
    """
    assert "MARK-CLOSED-UNREACHABLE" not in _marks(sensed["first"].units)
    opaque = sensed["first"].stats.get("closedRoots")
    assert opaque is not None, "the sensor does not report opaque hosts at all"
    assert opaque >= 1, (
        "the closed-shadow host on the page was counted as an ordinary empty "
        "element")


@LIVE
def test_every_composed_address_resolves_back_to_its_node(sensed):
    """An address that no walk can follow is a dead address, and the REPL
    enacts controls by following them. Slotted content is the case that would
    break it: its address goes *through* the slot, and a resolver reading
    ``childNodes`` finds nothing there."""
    unresolved = [m for m, ok in sensed["resolved"].items() if not ok]
    assert not unresolved, f"addresses that do not resolve: {unresolved}"


def _element_of(xpath):
    """A text unit's xpath without its `text()` step: its element."""
    return re.sub(r"/text\(\)(\[\d+\])?$", "", xpath or "")


@LIVE
def test_a_hover_names_the_address_the_fold_gave(sensed):
    """One element, one address. A hover that walks the light DOM names a
    slotted element by a path the trie never held (archive.org's search
    tiles, 2026-10-18), and every hover there resolved to a neighbour."""
    clean = sensed["hover"]["clean"]
    rendered = [(m, _element_of(_address_of(sensed["first"].units, m)))
                for m in _marks(sensed["first"].units)]
    assert rendered, "no markers emitted"
    wrong = [(m, a, clean.get(m)) for m, a in rendered if clean.get(m) != a]
    assert not wrong, f"hover address differs from the fold's: {wrong[:3]}"


@LIVE
def test_the_hover_address_check_can_fail(sensed):
    """Planted: the light-DOM walk. The fixture slots content, so it must
    name at least one marker differently."""
    planted = sensed["hover"]["planted"]
    rendered = [(m, _element_of(_address_of(sensed["first"].units, m)))
                for m in _marks(sensed["first"].units)]
    assert any(planted.get(m) != a for m, a in rendered), "the planted walk agreed everywhere"


@LIVE
def test_slot_reassignment_is_seen_at_all(sensed):
    """Nothing moves in the light DOM when a node changes slots, so there is
    no mutation record for it. Before ``slotchange`` was listened for, the
    fold drained *nothing* on a page whose reading order had just changed —
    strictly worse than either a move or a rebuild."""
    assert sensed["after"] != RENDERED, "the page did not actually reorder"
    assert _marks(sensed["second"].units) == sensed["after"]


@LIVE
def test_slot_reassignment_costs_a_move_not_a_rebuild(sensed):
    """claim: OBJECT_MODEL — a leaf that keeps its value has not moved, it has
    stayed; one that keeps its value at a new address has moved, and keeps its
    uid.

    The reassignment relocates one node and shifts the ordinal of one more.
    Anything that reports those as new content has spent the delta claim: the
    store would re-embed text it already holds.
    """
    from vertiscope.stream import StreamingScan

    scan = StreamingScan(sensed["url"], context_window=400)
    scan.absorb(sensed["first"].units, 0,
                removed=sensed["first"].removed_addresses)
    update = scan.absorb(sensed["second"].units, 1,
                         removed=sensed["second"].removed_addresses)
    delta = update.delta
    assert delta.moved, "a slot reassignment produced no moves at all"
    assert not delta.added, (
        f"content that only changed slots was reported as new: "
        f"{[a.xpath for a in delta.added]}")
    assert not delta.changed, (
        f"content that only changed slots was reported as edited: "
        f"{[a.xpath for a in delta.changed]}")
# --- the same move, on a subtree big enough to be its own chunk --------------


@pytest.fixture(scope="module")
def moved_in_bulk():
    """One browser, one page, a reassignment of a whole section.

    Deliberately a *large* block and a small budget, because that is a
    different path: a node that fits inside its parent's chunk is re-emitted
    whenever the parent is, and its new address rides along. A subtree the
    walk descends past is gated on its own digest instead — and a digest says
    what a subtree holds, not where it is.
    """
    from vertiscope.browser import browser_session
    from vertiscope.config import load_config
    from vertiscope.sensing import Sensor
    from vertiscope.stream import StreamingScan

    url = BULK.as_uri()
    with browser_session(load_config(), headless=True) as driver:
        driver.get(url)
        time.sleep(1.0)
        sensor = Sensor(driver, url, budget=200)
        sensor.boot()
        time.sleep(0.7)
        first = sensor.drain(0)
        driver.execute_script("window.promote();")
        time.sleep(0.8)
        second = sensor.drain(1)

    # The receiver as production runs it (`workspace.py`, `sidecar.py`):
    # units, removals AND moves. An unchanged block that changed slots
    # travels as a MOVE -- its content is not re-sent -- and a fixture that
    # dropped the moves kept the old addresses and failed this file's claim
    # against a sensor that had done its job (2026-10-18).
    scan = StreamingScan(url, context_window=200)
    scan.absorb(first.units, 0, removed=first.removed_addresses, moved=first.moved_addresses)
    scan.absorb(second.units, 1, removed=second.removed_addresses, moved=second.moved_addresses)
    # Planted: the receiver without moves, as the fixture was.
    blind = StreamingScan(url, context_window=200)
    blind.absorb(first.units, 0, removed=first.removed_addresses)
    blind.absorb(second.units, 1, removed=second.removed_addresses)
    yield {"first": first, "second": second, "trie": scan.trie, "blind": blind.trie}


@LIVE
def test_a_large_moved_subtree_is_re_addressed(moved_in_bulk):
    """claim: the store never holds an address the page does not draw.

    The gate compared digests alone, and a subtree that moves keeps its
    digest exactly, so its chunk was suppressed. Measured before the fix:
    both addresses for the moved block still said ``/main/slot/...`` while
    the page drew it under ``/header/slot/...``, and nothing anywhere
    reported a change. Stale beats missing only in the sense that it is
    harder to notice.
    """
    leaves = {node.address.xpath: (node.value or "").strip()
              for node in moved_in_bulk["trie"].leaves()}
    movable = {x: v for x, v in leaves.items() if v.startswith("BULK-MOVABLE")}
    assert movable, "the moved block is not in the trie at all"
    stale = [x for x in movable if "/main/" in x]
    assert not stale, f"addresses the page no longer draws: {stale}"
    assert all("/header/slot/" in x for x in movable), movable


@LIVE
def test_the_one_step_rule_alone_keeps_the_old_addresses():
    """Planted `_PLANT_ONE_STEP_MOVES`: moves decoded by the re-index rule
    alone, which refuses a re-parented chunk (main -> header). The moved
    block's old addresses survive, so the re-address check can fail."""
    import vertiscope.sensing as S
    from vertiscope.browser import browser_session
    from vertiscope.config import load_config
    from vertiscope.sensing import Sensor
    from vertiscope.stream import StreamingScan
    url = BULK.as_uri()
    S._PLANT_ONE_STEP_MOVES[0] = True
    try:
        with browser_session(load_config(), headless=True) as driver:
            driver.get(url)
            time.sleep(1.0)
            sensor = Sensor(driver, url, budget=200)
            sensor.boot()
            time.sleep(0.7)
            first = sensor.drain(0)
            driver.execute_script("window.promote();")
            time.sleep(0.8)
            second = sensor.drain(1)
    finally:
        S._PLANT_ONE_STEP_MOVES[0] = False
    scan = StreamingScan(url, context_window=200)
    scan.absorb(first.units, 0, removed=first.removed_addresses, moved=first.moved_addresses)
    scan.absorb(second.units, 1, removed=second.removed_addresses, moved=second.moved_addresses)
    leaves = {n.address.xpath: (n.value or "").strip() for n in scan.trie.leaves()}
    assert not any(v.startswith("BULK-MOVABLE") and "/header/" in x for x, v in leaves.items()),         "the one-step rule re-addressed the re-parented block: this arm cannot fail"


@LIVE
def test_without_the_moves_the_trie_keeps_the_old_addresses(moved_in_bulk):
    """Planted: the receiver that ignores moves. The moved block's old
    addresses survive -- so the check above can fail."""
    leaves = {node.address.xpath: (node.value or "").strip()
              for node in moved_in_bulk["blind"].leaves()}
    stale = [x for x, v in leaves.items() if v.startswith("BULK-MOVABLE") and "/main/" in x]
    assert stale, "the blind receiver re-addressed the block too: the check cannot fail"


@LIVE
def test_the_move_is_reported_at_all(moved_in_bulk):
    """The gate suppressing it looked exactly like a quiet page."""
    second = moved_in_bulk["second"]
    assert second.units, "a whole section changed slots and the drain was empty"
