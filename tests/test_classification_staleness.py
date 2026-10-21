"""A link's class is not a function of its own subtree, and the cache assumed it was.

``numericFamily`` decides whether a link is a pager by walking four ancestors
up and counting the anchors it finds there. So a link's *address* -- the
accessor carries the verdict -- depends on a neighbourhood. Add or remove an
anchor anywhere in that scope and a link that did not itself change is
classified differently.

Nothing marked such a link dirty. It was never re-folded, and ``rec.tax`` is
cleared only at the top of a re-fold, so it kept the old verdict for the life
of the page. Deleting one ``<li>`` from a Wikipedia citation list dropped a
family below three and re-classified four surviving links from
``pagination.family`` to ``link.anchor``: the trie held four addresses the page
did not have and missed the four it did, on every drain thereafter.

That the fault was the cache and not the wire was settled by turning the gate
off. All 6,832 units were re-sent and the same four addresses were still
wrong, which rules out every explanation that lives in what gets transmitted.

Two changes, and one test here for each, because either alone leaves the page
wrong:

* the fold invalidates the verdicts in the scope of an anchor change, so the
  class is recomputed;
* the class is mixed into ``rec.digest``, so a recomputed class is a reason to
  redraw. Without this the re-fold produces the same digest -- the value did
  not change -- the gate skips the chunk, and the fresh verdict never leaves
  the page. This is rule 5b: two Merkles, and only the exact one may see the
  address. ``rec.content`` deliberately does not take the class, because
  matching content across a move must stay blind to role.

Neither change is sufficient alone: reverting either one makes *both* of the
first two tests fail, at the same assertion. A recomputed verdict that cannot
pass the gate and a gate that would pass a verdict nobody recomputed are the
same wrong map. Measured, not assumed -- each was reverted in turn against
this file, and each time the survivors kept the address they no longer had.

    VERTISCOPE_LIVE=1 python -m pytest tests/test_classification_staleness.py -q
"""

import os
import pathlib
import time

import pytest

from vertiscope.browser import browser_session
from vertiscope.config import load_config
from vertiscope.sensing import Sensor
from vertiscope.stream import StreamingScan

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "link_family.html"
URI = FIXTURE.resolve().as_uri()
DEEP = ROOT / "tests" / "fixtures" / "link_family_deep.html"
DEEP_URI = DEEP.resolve().as_uri()

LIVE = pytest.mark.skipif(
    not os.environ.get("VERTISCOPE_LIVE"),
    reason="needs a real browser; set VERTISCOPE_LIVE=1")

# Small enough that the three list items do not land in one chunk. The gate is
# per chunk root, so a test where the edited link and the re-classified link
# shared a chunk could not tell a redraw caused by the class from one caused
# by the neighbour's own edit.
BUDGET = 60


@pytest.fixture(scope="module")
def driver():
    with browser_session(load_config()) as handle:
        yield handle


def _drain_to_quiet(sensor, spine):
    for _ in range(6):
        snap = sensor.drain(101)
        spine.absorb(snap.units, snap.passno,
                     removed=snap.removed_addresses,
                     moved=snap.moved_addresses)
        if snap.settled and not snap.units:
            break
        time.sleep(0.25)
    return spine


def _settled(driver, uri=URI):
    """A sensor and a trie holding the whole fixture, quiescent."""
    driver.get("about:blank")
    driver.get(uri)
    time.sleep(0.8)
    sensor = Sensor(driver, uri, budget=BUDGET)
    sensor.boot()
    time.sleep(0.5)
    spine = _drain_to_quiet(sensor, StreamingScan(uri, context_window=BUDGET))
    return sensor, spine


def _truth(driver, uri=URI):
    """A second sensor, booted on the page as it stands and walked whole.

    The denominator. A map that agreed with a stale map because both were
    computed the same stale way would prove nothing, so this one has no
    history to be stale from.
    """
    other = Sensor(driver, uri, budget=BUDGET,
                   handle="__vertiscope_truth_%d__" % int(time.time() * 1000))
    other.boot()
    time.sleep(0.5)
    return _drain_to_quiet(other, StreamingScan(uri, context_window=BUDGET))


def _addresses(spine):
    return {leaf.address.key() for leaf in spine.trie.leaves() if leaf.address}


@LIVE
def test_the_survivors_are_reclassified_when_a_family_member_leaves(driver):
    """The Wikipedia case, in miniature: one link removed, two re-classified.

    Fails without the scoped invalidation -- the survivors are clean, so they
    are never re-folded and keep ``pagination.family`` for good.
    """
    sensor, spine = _settled(driver)
    before = _addresses(spine)
    assert before, "the fixture produced no addresses at all"

    driver.execute_script("document.getElementById('l1').parentNode.remove();")
    time.sleep(0.5)
    snap = sensor.drain(101)
    spine.absorb(snap.units, snap.passno,
                 removed=snap.removed_addresses, moved=snap.moved_addresses)

    assert _addresses(spine) == _addresses(_truth(driver))
    # ... and it did not pass because nothing happened.
    assert _addresses(spine) != before


@LIVE
def test_a_recomputed_class_is_a_reason_to_redraw(driver):
    """The verdict has to reach the trie, not merely be recomputed in the page.

    Fails without the class in ``rec.digest``: the survivors are invalidated
    and re-folded, their values are untouched so their digests are unchanged,
    the gate skips their chunks, and the page keeps the fresh verdict to
    itself.

    An href edit rather than a removal, so the survivors' chunks have no other
    reason to be re-sent: nothing was added or removed, and neither survivor
    was touched.
    """
    sensor, spine = _settled(driver)
    before = {leaf.address.key() for leaf in spine.trie.leaves()
              if leaf.address and "li[2]" in leaf.address.xpath}
    assert before, "the fixture's second list item produced no addresses"

    driver.execute_script(
        "document.getElementById('l1').setAttribute('href', '/other/9');")
    time.sleep(0.5)
    snap = sensor.drain(101)
    spine.absorb(snap.units, snap.passno,
                 removed=snap.removed_addresses, moved=snap.moved_addresses)

    redrawn = {addr.key() for addr, _v in snap.units if "li[2]" in addr.xpath}
    assert redrawn, "the untouched sibling was never redrawn"
    assert _addresses(spine) == _addresses(_truth(driver))


@LIVE
def test_a_change_with_no_anchor_in_it_does_not_run_the_scope_query(driver):
    """The guard, or the fix is a scope query on every mutation a page makes.

    ``numericFamily`` counts anchors, so only anchors entering or leaving can
    change a verdict. Inserting a paragraph is the case that must cost nothing.
    """
    sensor, _spine = _settled(driver)

    driver.execute_script(
        "var p = document.createElement('p');"
        "p.textContent = 'a paragraph, containing no links at all';"
        "document.getElementById('elsewhere').appendChild(p);")
    time.sleep(0.5)
    snap = sensor.drain(101)

    assert (snap.stats or {}).get("reclassified") == 0
    # The insertion still has to arrive, or this passes for the wrong reason:
    # a sensor that saw nothing also reclassifies nothing.
    assert any("paragraph, containing no links" in (value or "")
               for _addr, value in snap.units)


@LIVE
def test_the_class_is_not_in_the_move_tolerant_hash(driver):
    """Rule 5b from the other side.

    Content matching has to stay blind to role, or a re-classified node stops
    matching itself across a move. The exact digest sees the class; the
    content hash may not.
    """
    from vertiscope.trie import content_hash

    _sensor, spine = _settled(driver)
    leaves = [leaf for leaf in spine.trie.leaves()
              if leaf.address and leaf.value
              and "entry of the numeric family" in leaf.value]
    assert len(leaves) >= 2, "the fixture's link texts did not reach the trie"

    # The links are classified `pagination.family` here and `link.anchor` once
    # the family is broken, so their accessors differ between the two runs
    # while their values do not. The content hash has to be the same both
    # times, and it is the same because it is computed from the value alone.
    for leaf in leaves:
        assert leaf.content_hash == content_hash(leaf.value)

    driver.execute_script("document.getElementById('l1').parentNode.remove();")
    time.sleep(0.5)
    after = _truth(driver)
    survivors = {leaf.value: leaf.content_hash for leaf in after.trie.leaves()
                 if leaf.address and leaf.value}
    for leaf in leaves:
        if leaf.value in survivors:
            assert survivors[leaf.value] == leaf.content_hash


@LIVE
def test_a_link_whose_scope_reaches_past_the_change_is_reached(driver):
    """The residue the scoped invalidation left, built to the derivation.

    A link's scope is the node four levels above it, so ``#shallow`` -- two
    levels down -- has the whole document for a scope and counts all three
    members of the ``/item/#`` family. The two deep links are nested eight
    divs down, so their own scopes hold only each other and never make three.

    Remove one deep member and ``#shallow`` drops from three to two. It is
    re-classified while sitting in a branch that ``subtree(anc4(T))`` does not
    contain, which is exactly the set the derivation named:

        a link can change iff its scope is an ancestor-or-self of the
        mutation; a scope taken four levels above the *mutation* covers only
        those links at or below that depth.

    So this fails against the scoped version by construction, not by luck.
    """
    sensor, spine = _settled(driver, DEEP_URI)
    before = _addresses(spine)
    assert before, "the deep fixture produced no addresses at all"

    driver.execute_script("document.getElementById('deep3').parentNode.remove();")
    time.sleep(0.5)
    snap = sensor.drain(101)
    spine.absorb(snap.units, snap.passno,
                 removed=snap.removed_addresses, moved=snap.moved_addresses)

    truth = _truth(driver, DEEP_URI)
    assert _addresses(spine) == _addresses(truth)
    # The shallow link is the one under test, so its address has to be among
    # what changed -- otherwise this passes on the deep links alone.
    shallow = {key for key in _addresses(truth) if "/a" in key.split("|")[1]}
    assert shallow - before, "the shallow link's address did not change at all"


@LIVE
def test_an_anchor_from_another_family_leaves_this_one_alone(driver):
    """The mask filter, or the sweep is a re-fold of every anchor on the page.

    Membership is hrefs that differ only in their digits, so an anchor with a
    different mask changes no count anywhere. Marking the family dirty for it
    would be work with no verdict behind it -- which is what the scoped
    version did, reclassifying 1,198 links on one page to emit nothing.
    """
    sensor, _spine = _settled(driver, DEEP_URI)

    driver.execute_script(
        "var a = document.createElement('a');"
        "a.setAttribute('href', '/unrelated/7');"
        "a.textContent = 'a link belonging to no family here';"
        "document.getElementById('elsewhere').appendChild(a);")
    time.sleep(0.5)
    snap = sensor.drain(101)

    assert (snap.stats or {}).get("reclassified") == 0
    # Non-vacuity: the anchor did arrive, so the zero above is a filter doing
    # its job and not a sensor that saw nothing.
    assert any("belonging to no family" in (value or "")
               for _addr, value in snap.units)
