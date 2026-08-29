"""Content that moves keeps its identity, and vacates the address it left.

`TrieNode.uid` exists so that a positional address shifting does not destroy
what hangs off a leaf. `AddressTrie.apply` recovers a shift the fold did not
report by re-anchoring on content hash, bounded to the spans the drain touches
— which is what keeps that recovery proportional to the change.

Two consequences of that bound, both invisible on a flat list and both plainly
visible on the first real page:

* **A move between parents is outside its reach.** The old leaf lives under a
  span no incoming unit names, so its uid is never offered to the address that
  now holds its content. On news.ycombinator.com one inserted row read as 654
  genuine changes; the fold had reported the moves, and the receiver was not
  honouring them.
* **Nothing vacated the address the content left.** The DOM removed nothing,
  so the fold reports no removal, and the trie kept a stale copy at the old
  address while writing the content at the new one. quotes.toscrape.com went
  from 176 addresses to 209 for one inserted node, dropping none.

So a reported move is authoritative: the uid travels with the content and the
old address is vacated. Vacating is *not* counted as a removal — a move is not
an edit, and the address is already in `delta.moved`.

The subtlety that cost the last four identities: where the value arriving at an
address is the value already there — "by", "(about)", "Tags:", the strings that
repeat on every card in a list — the write is a no-op and the uid was dropped
on the floor while the source was vacated. Every uid is snapshotted before any
write, so handing it forward on a no-op is safe and the chain of identical
values passes identities along it.
"""

import pytest

from domvec.address import ContentAddress
from domvec.trie import AddressTrie


def _addr(xpath, url="https://move.test/p", tag="text", accessor="text()[1]"):
    return ContentAddress(url, xpath, tag, accessor)


def _card(index, body):
    """One card's worth of units: a repeated label and a distinct body."""
    at = "/html/body/main/div" if index == 1 else \
        "/html/body/main/div[{}]".format(index)
    return [
        (_addr(at + "/span/text()[1]"), "by"),          # repeats on every card
        (_addr(at + "/p/text()[1]"), body),             # distinct
    ]


def _build(bodies):
    trie = AddressTrie()
    units = []
    for i, body in enumerate(bodies, start=1):
        units.extend(_card(i, body))
    trie.apply(units)
    return trie


def _shift_by_one(bodies):
    """The address pairs a head insertion produces for `bodies`."""
    moved = []
    for i in range(len(bodies), 0, -1):
        old = "/html/body/main/div" if i == 1 else \
            "/html/body/main/div[{}]".format(i)
        new = "/html/body/main/div[{}]".format(i + 1)
        for tail in ("/span/text()[1]", "/p/text()[1]"):
            moved.append((_addr(old + tail), _addr(new + tail)))
    return moved


def _drain(trie, inserted, moved):
    """What `absorb` hands `apply`, mirrored exactly.

    The fold does not re-send content the receiver already holds, so a moved
    chunk arrives as address pairs with no values. `StreamingScan.absorb`
    rebuilds those units by reading the value sitting at the old address and
    re-offering it at the new one, and passes the pairs to `apply` as well --
    the units say what the page holds now, the pairs say which identities
    travel and which addresses are vacated. Passing one without the other is
    not a state the live path can produce, and a test that did so was testing
    a contract nobody implements.
    """
    units = [
        (_addr("/html/body/main/div/span/text()[1]"), "by"),
        (_addr("/html/body/main/div/p/text()[1]"), inserted),
    ]
    seen = {address.key() for address, _value in units}
    for old_address, new_address in moved:
        if new_address.key() in seen:
            continue
        node = trie.find(old_address)
        if node is None or node.value is None:
            continue
        units.append((new_address, node.value))
        seen.add(new_address.key())
    return units


# --- identity --------------------------------------------------------------


def test_a_reported_move_carries_the_uid_between_parents():
    """The content-hash re-anchor cannot see this; the report can."""
    trie = _build(["first body", "second body"])
    before = {leaf.value: leaf.uid for leaf in trie.leaves()}

    moved = _shift_by_one(["first body", "second body"])
    delta = trie.apply(_drain(trie, "new body", moved), moved=moved)

    after = {leaf.value: leaf.uid for leaf in trie.leaves()}
    assert after["first body"] == before["first body"]
    assert after["second body"] == before["second body"]
    assert delta.size == 1, "one card arriving is one change"


def test_no_identity_is_lost_when_the_value_repeats():
    """"by" arrives at an address that already says "by".

    The write is a no-op. Without handing the uid forward there, the source is
    vacated and its identity disappears -- four of them on
    quotes.toscrape.com, whose every card carries the same three labels.
    """
    bodies = ["a", "b", "c", "d"]
    trie = _build(bodies)
    before = {leaf.uid for leaf in trie.leaves()}

    moved = _shift_by_one(bodies)
    trie.apply(_drain(trie, "fresh", moved), moved=moved)

    after = {leaf.uid for leaf in trie.leaves()}
    assert not (before - after), "{} identities vanished".format(
        len(before - after))


def test_the_trie_does_not_grow_by_more_than_what_arrived():
    bodies = ["a", "b", "c", "d", "e"]
    trie = _build(bodies)
    before = len(trie)
    moved = _shift_by_one(bodies)
    trie.apply(_drain(trie, "fresh", moved), moved=moved)
    assert len(trie) == before + 2, (
        "one card of two units arrived; the trie went from {} to {}".format(
            before, len(trie)))


def test_the_vacated_address_is_gone():
    bodies = ["a", "b"]
    trie = _build(bodies)
    stale = _addr("/html/body/main/div[2]/p/text()[1]")
    assert trie.find(stale) is not None
    moved = _shift_by_one(bodies)
    trie.apply(_drain(trie, "fresh", moved), moved=moved)
    # "b" now lives at div[3]; nothing should still be answering at div[2]
    # with the old copy.
    node = trie.find(stale)
    assert node is not None and node.value == "a", (
        "div[2] should hold what div[1] held, not a stale 'b'")
    assert trie.find(_addr("/html/body/main/div[3]/p/text()[1]")).value == "b"


# --- what it must not do ---------------------------------------------------


def test_vacating_is_not_counted_as_a_removal():
    """A move is not an edit. Counting it twice would make one node arriving
    look like the page rewriting itself, which is the figure this mechanism
    exists to avoid."""
    bodies = ["a", "b", "c"]
    trie = _build(bodies)
    moved = _shift_by_one(bodies)
    delta = trie.apply(_drain(trie, "fresh", moved), moved=moved)
    assert delta.removed == []
    assert delta.size == 1
    assert delta.moved, "the shift should be reported as movement"


def test_an_address_the_drain_still_claims_is_not_vacated():
    """The ordinary case on a flat list: every vacated address is immediately
    reoccupied by its neighbour, so nothing is dropped at all."""
    bodies = ["a", "b"]
    trie = _build(bodies)
    moved = _shift_by_one(bodies)
    units = _drain(trie, "fresh", moved)
    before = len(trie)
    trie.apply(units, moved=moved)
    assert trie.find(_addr("/html/body/main/div[2]/p/text()[1]")) is not None
    assert len(trie) >= before


def test_a_move_from_an_address_the_trie_never_held_is_ignored():
    trie = _build(["a"])
    delta = trie.apply(
        [(_addr("/html/body/main/div/p/text()[1]"), "a")],
        moved=[(_addr("/nowhere/at/all/text()[1]"),
                _addr("/html/body/main/div/p/text()[1]"))])
    assert delta.size == 0


def test_moves_are_optional():
    """Every existing caller passes none, and must keep working."""
    trie = _build(["a", "b"])
    delta = trie.apply([(_addr("/html/body/main/div/p/text()[1]"), "changed")])
    assert delta.size == 1
