"""One insertion costs one change, and no identity is destroyed by a shift.

The central claim of the design, at the write side of the patricia trie.
`AddressTrie.apply` is the live path's only mutator, and a positional address
means a node arriving at the head of a list re-points every sibling below it.
Re-anchoring by content is what turns that into one arrival plus N moves
instead of N+1 edits, and `uid` is what survives it.

No browser: the trie takes addressed units as data, so the property is
testable directly. The live path is measured by `vertiscope.analytics.delta`.
"""

import pytest

from vertiscope.address import ContentAddress
from vertiscope.trie import AddressTrie

URL = "https://x.test/"


def addr(xpath: str) -> ContentAddress:
    return ContentAddress(URL, xpath, "item", "text()[1]|text.visible")


def a_list(n: int, start: int = 1):
    return [(addr(f"/html/body/ul/li[{i + start}]/text()[1]"), f"ITEM-{i}")
            for i in range(n)]


def shift_by_one(units):
    """The same content, every address moved down one ordinal."""
    return [(addr(f"/html/body/ul/li[{i + 2}]/text()[1]"), value)
            for i, (_a, value) in enumerate(units)]


@pytest.mark.parametrize("n", [10, 100, 400])
def test_one_insertion_is_one_change_at_every_size(n):
    """claim: cost tracks the edit, not the document it lands in."""
    trie = AddressTrie()
    base = a_list(n)
    trie.apply(base)

    head = [(addr("/html/body/ul/li[1]/text()[1]"), "INSERTED")]
    delta = trie.apply(head + shift_by_one(base))

    assert delta.size == 1, (
        f"one <li> into a {n}-item list reported {delta.size} genuine "
        f"changes; N+1 is the failure this re-anchor exists to prevent")
    assert len(delta.moved) == n


@pytest.mark.parametrize("n", [10, 100, 400])
def test_a_shift_destroys_no_identity(n):
    trie = AddressTrie()
    base = a_list(n)
    trie.apply(base)
    before = {leaf.uid for leaf in trie.leaves()}

    head = [(addr("/html/body/ul/li[1]/text()[1]"), "INSERTED")]
    trie.apply(head + shift_by_one(base))
    after = {leaf.uid for leaf in trie.leaves()}

    assert before <= after, f"{len(before - after)} of {n} uids did not survive"


@pytest.mark.parametrize("n", [10, 100, 400])
def test_a_stale_removal_does_not_undo_the_reanchor(n):
    """claim: `units` is authoritative for what exists now.

    Chunk ids are keyed on position, so an insertion at the head retires the
    id of every chunk below it and the fold reports N removals for one
    arrival -- naming the layout that just stopped being true. Those same
    addresses are in `units`, holding the shifted content and already carrying
    their previous leaves' uids, so applying the removals afterwards deletes
    the identities the re-anchor just preserved.

    Measured on the live path before the fix: one <li> into a 400-item list
    reported a delta of 401 and lost 399 uids. Suppressing the removal list
    alone brought the same drain to a delta of 1 and lost none.
    """
    trie = AddressTrie()
    base = a_list(n)
    trie.apply(base)
    before = {leaf.uid for leaf in trie.leaves()}

    head = [(addr("/html/body/ul/li[1]/text()[1]"), "INSERTED")]
    # Exactly what the sensor sends: the old positions, all of them.
    stale = [a for a, _v in base]
    delta = trie.apply(head + shift_by_one(base), removed=stale)
    after = {leaf.uid for leaf in trie.leaves()}

    assert delta.size == 1, (
        f"the stale removal list re-inflated the delta to {delta.size}")
    assert not (before - after), (
        f"{len(before - after)} of {n} uids destroyed by removals this same "
        f"drain contradicts")
    assert sum(1 for _ in trie.leaves()) == n + 1


def test_a_real_removal_is_still_applied():
    """Non-vacuity: the guard must not disable removal.

    Without this the fix is indistinguishable from deleting the removal loop,
    and a page whose content genuinely leaves would render it forever.
    """
    trie = AddressTrie()
    base = a_list(3)
    trie.apply(base)
    assert sum(1 for _ in trie.leaves()) == 3

    gone = base[2][0]
    delta = trie.apply(base[:2], removed=[gone])
    assert len(delta.removed) == 1
    assert sum(1 for _ in trie.leaves()) == 2
