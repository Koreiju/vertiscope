"""Content that moves keeps its identity.

`TrieNode.uid` exists so that a positional address shifting does not destroy
what hangs off a leaf. `AddressTrie.apply` recovers a shift the fold did not
report by re-anchoring on content hash, bounded to the spans the drain touches
— which is what keeps that recovery proportional to the change.

A move *between parents* is outside that bound: the old leaf lives under a span
no incoming unit names, so its uid is never offered to the address that now
holds its content. On news.ycombinator.com one inserted row read as 654 genuine
changes — the fold had reported the moves and the receiver was not honouring
them. A reported move is now authoritative and the uid travels with the
content, which takes that page to 1.

**What is deliberately not done here: vacating the address a move came from.**
I had that, and took it out. The reasoning for it was that the DOM removes
nothing on a shift, so the fold reports no removal, and the old address would
otherwise keep a stale copy — which is a real defect, and on a flat list the
rule is exactly right, because every vacated address is immediately reoccupied
by its neighbour. Four real pages agreed.

Arabic Wikipedia did not: 11,793 leaves, 151 list items, and one inserted node
made the trie *shrink* by 84 addresses and lose 85 identities. Of 60 addresses
the rule wanted to drop, **47 were still in the live DOM**. The premise was
that an address whose content moved away, and which this drain does not claim,
is empty; but the fold does not re-send content the receiver already holds, so
its silence about an address is the absence of evidence rather than evidence of
absence.

A stale address is a defect and is reported per page by
`analytics/live_delta.py`. Deleting content the page still has is a worse one,
and silent.

Note which tests here discriminate. The ones built from `_drain` re-state every
address, so nothing was ever vacated in them and they passed both with the rule
and without it — they were not testing what their names claimed. The case that
discriminates is a drain that says nothing about the source, which is the
ordinary case rather than a pathological one.
"""
import pytest

from vertiscope.address import ContentAddress
from vertiscope.trie import AddressTrie


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


def test_a_shift_leaves_every_address_holding_its_new_content():
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


def test_a_shift_is_not_counted_as_a_removal():
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


def test_a_shift_within_one_parent_reoccupies_what_it_leaves():
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


# --- an inferred move vacates its source too -------------------------------


def test_a_shift_the_fold_did_not_report_is_still_recognised():
    """The fold reports a move only when the chunk holding it is otherwise
    unchanged. Where the chunk changed -- which is the common case for the
    chunk the insertion lands in -- it re-sends the content as ordinary units
    and names no move at all.

    `apply` recognises those by content hash and carries their uids, and for a
    while that was all it did: the addresses they came from stayed behind
    holding stale copies. On lit.dev an insertion into a group of code blocks
    arrived as 185 units and no moves, and the trie gained 65 addresses while
    dropping none.
    """
    bodies = ["alpha body", "beta body", "gamma body"]
    trie = _build(bodies)
    before = len(trie)
    before_uids = {leaf.uid for leaf in trie.leaves()}

    # The whole span re-sent as units, shifted by one, with no move channel.
    units = [
        (_addr("/html/body/main/div/span/text()[1]"), "by"),
        (_addr("/html/body/main/div/p/text()[1]"), "fresh body"),
    ]
    for i, body in enumerate(bodies, start=1):
        at = "/html/body/main/div[{}]".format(i + 1)
        units.append((_addr(at + "/span/text()[1]"), "by"))
        units.append((_addr(at + "/p/text()[1]"), body))

    delta = trie.apply(units)          # note: no `moved`

    # Two, not one, and the difference is worth stating. The card carries a
    # distinct body and a label that every card repeats. Inference can only
    # match a value against a *displaced* one, and no "by" was displaced --
    # every other card still says "by" -- so the new card's label reads as an
    # arrival. A reported move hands that label forward along the chain and
    # the same insertion reads as one change. Inference recovers the shift; it
    # does not recover the accounting as tightly.
    assert delta.size == 2, delta.size
    assert len(trie) == before + 2, (
        "the trie went from {} to {} for one card".format(before, len(trie)))
    assert not (before_uids - {leaf.uid for leaf in trie.leaves()}), \
        "identities were lost to a shift the fold did not report"


def test_an_inferred_shift_reoccupies_what_it_leaves():
    """The flat-list case: the drain re-states every address, so nothing is
    vacated and the trie keeps its size."""
    bodies = ["a", "b"]
    trie = _build(bodies)
    units = []
    for i, body in enumerate(["fresh"] + bodies, start=1):
        at = "/html/body/main/div" if i == 1 else \
            "/html/body/main/div[{}]".format(i)
        units.append((_addr(at + "/span/text()[1]"), "by"))
        units.append((_addr(at + "/p/text()[1]"), body))
    trie.apply(units)
    for i, body in enumerate(["fresh"] + bodies, start=1):
        at = "/html/body/main/div" if i == 1 else \
            "/html/body/main/div[{}]".format(i)
        node = trie.find(_addr(at + "/p/text()[1]"))
        assert node is not None and node.value == body, at


# --- what silence from the fold does and does not mean ----------------------


def test_a_move_report_never_deletes_content_the_drain_did_not_replace():
    """The rule I had here, and had to take out.

    I made a reported move delete the address it came from: the DOM removes
    nothing on a shift, so the fold reports no removal, and the old address
    would otherwise keep a stale copy. On a flat list that is exactly right --
    every vacated address is immediately reoccupied -- and four real pages
    agreed.

    Arabic Wikipedia did not. 11,793 leaves, 151 list items, and one inserted
    node made the trie *shrink* by 84 addresses and lose 85 identities. Of 60
    addresses the rule wanted to drop, 47 were still in the live DOM.

    The premise was that an address whose content moved away, and which this
    drain does not claim, is empty. The fold does not re-send content the
    receiver already holds, so its silence is the absence of evidence rather
    than evidence of absence.

    This is the case that discriminates, and the reason the earlier tests here
    did not: their drains re-state every address, so nothing was ever vacated
    in them and they passed with the rule and without it.
    """
    trie = _build(["a", "b", "c"])
    before = len(trie)
    untouched = _addr("/html/body/main/div[3]/p/text()[1]")
    assert trie.find(untouched).value == "c"

    # One move reported, and a drain that says nothing about the source --
    # which is the ordinary case, not a pathological one.
    moved = [(_addr("/html/body/main/div[3]/p/text()[1]"),
              _addr("/html/body/main/div[9]/p/text()[1]"))]
    units = [(_addr("/html/body/main/div[9]/p/text()[1]"), "c")]
    trie.apply(units, moved=moved)

    node = trie.find(untouched)
    assert node is not None and node.value == "c", (
        "content the drain never contradicted was deleted")
    assert len(trie) >= before


def test_the_identity_still_travels_even_though_the_source_stays():
    """What survived the revert, and the part that was sound.

    Carrying the uid is independent of vacating, and it is what took
    news.ycombinator.com from 654 genuine changes for one inserted row to 1.
    """
    trie = _build(["a", "b"])
    source = _addr("/html/body/main/div[2]/p/text()[1]")
    uid = trie.find(source).uid
    assert uid

    destination = _addr("/html/body/main/div[7]/p/text()[1]")
    delta = trie.apply([(destination, "b")], moved=[(source, destination)])

    assert trie.find(destination).uid == uid
    assert destination in delta.moved
    assert delta.size == 0, "a move is not an edit"
