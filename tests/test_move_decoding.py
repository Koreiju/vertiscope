"""A shifted address must name a node the page actually has.

When a node is inserted, every sibling after it keeps its content and changes
its address. The fold reports that as a *move* rather than as N edits, and the
receiver rebuilds the affected addresses by substituting the moved node's new
path for its old one. If that substitution is wrong the rebuilt addresses point
at nothing: the trie writes content at paths the document does not contain,
and because the DOM removed nothing, nothing removes the originals either. The
trie then grows while the page stays the same size — which no coverage or dedup
number can see, since every address that *is* there is still correct.

Three defects, all invisible to the flat-list fixture and all visible on the
first real page:

* **The root was cut back one step too far.** The old root came from the common
  prefix of the chunk's addresses, truncated to the last "/" unconditionally.
  That is right when the shared prefix stops mid-step ("li[1]" against
  "li[12]") and wrong when it is already a whole step — which happens whenever
  a chunk has a unit addressed at its own root, an href or an aria-label on the
  element itself. quotes.toscrape.com went from 176 leaves to 317 for one
  inserted node, and every sampled new path matched zero nodes in the DOM.
* **The old root was taken at the wrong depth.** The move entry names the node
  that moved; a chunk's addresses hang off whatever is inside it. On
  books.toscrape.com the entry named the `li` and the addresses hung off the
  `article` within, so substituting one root for the other dropped the
  `article` step: 60 of 60 sampled paths matched nothing.
* **An address in another branch was rewritten onto the moved node.** Deriving
  the old root from the address makes it a prefix of that address by
  construction, so a `startswith` guard can never fail. This one was caught by
  a test rather than by a page, which is the only reason it is in this list
  instead of in a later one.

After all three: 0 of 60 sampled new paths missing from the DOM on
quotes.toscrape.com, books.toscrape.com and news.ycombinator.com, and books'
genuine-change count for one inserted node went from 191 to 1.
"""

import pytest

from domvec.address import ContentAddress
from domvec.sensing import _shifted_xpath, _step_tag


# --- what a move is --------------------------------------------------------


def test_a_unit_on_the_moved_node_itself_lands_on_the_new_node():
    """The case the unconditional prefix cut got wrong."""
    assert _shifted_xpath("/html/body/div/div[2]/div/div",
                          "/html/body/div/div[2]/div/div[2]") == \
        "/html/body/div/div[2]/div/div[2]"


def test_everything_below_the_moved_step_is_carried_through():
    assert _shifted_xpath("/html/body/div/div[2]/div/div/span[2]/a/text()[1]",
                          "/html/body/div/div[2]/div/div[2]") == \
        "/html/body/div/div[2]/div/div[2]/span[2]/a/text()[1]"


def test_the_step_between_the_moved_node_and_the_unit_is_kept():
    """books.toscrape.com: the entry names the `li`, units hang off the
    `article` inside it."""
    assert _shifted_xpath("/html/body/section/ol/li/article/h3/a/text()[1]",
                          "/html/body/section/ol/li[2]") == \
        "/html/body/section/ol/li[2]/article/h3/a/text()[1]"


@pytest.mark.parametrize("depth_of_unit", [1, 2, 5])
def test_the_shift_is_one_step_whatever_the_unit_hangs_off(depth_of_unit):
    tail = "/".join("wrap{}".format(i) for i in range(depth_of_unit))
    assert _shifted_xpath("/html/body/ol/li/{}/text()[1]".format(tail),
                          "/html/body/ol/li[7]") == \
        "/html/body/ol/li[7]/{}/text()[1]".format(tail)


# --- what a move is not ----------------------------------------------------


def test_an_address_in_another_branch_is_left_alone():
    """Without this guard the address is rewritten onto the moved node.

    The old root is derived from the address, so it is always a prefix of it
    and `startswith` is vacuous. What makes an address "inside the moved node"
    is that its prefix at that depth differs from the new root in the ordinal
    alone.
    """
    assert _shifted_xpath("/html/body/footer/p/text()[1]",
                          "/html/body/section/ol/li[2]") is None


def test_an_address_shallower_than_the_moved_node_is_left_alone():
    assert _shifted_xpath("/html/body", "/html/body/section/ol/li[2]") is None


def test_a_different_element_at_the_same_place_is_left_alone():
    """Same parent, same depth, different tag: not one element re-indexed."""
    assert _shifted_xpath("/html/body/section/ol/div/x",
                          "/html/body/section/ol/li[2]") is None


def test_an_address_already_at_the_new_root_is_not_shifted_again():
    assert _shifted_xpath("/html/body/ol/li[2]", "/html/body/ol/li[2]") is None
    assert _shifted_xpath("/html/body/ol/li[2]/span",
                          "/html/body/ol/li[2]") is None


def test_the_first_sibling_carries_no_ordinal():
    """`li` and `li[2]` are the same element at two ordinals.

    The trie writes the first of a group without its index, so a shift from
    first position has an unindexed old step. If `_step_tag` did not strip the
    ordinal this comparison would fail and the move would be dropped.
    """
    assert _step_tag("li") == "li"
    assert _step_tag("li[12]") == "li"
    assert _shifted_xpath("/html/body/ol/li/span",
                          "/html/body/ol/li[2]") == "/html/body/ol/li[2]/span"


# --- the address it builds -------------------------------------------------


def test_only_the_xpath_moves():
    before = ContentAddress("https://x.test/p", "/html/body/ol/li/h3/a",
                            "link", "href")
    shifted = ContentAddress(before.url,
                             _shifted_xpath(before.xpath, "/html/body/ol/li[3]"),
                             before.tag, before.accessor)
    assert shifted.xpath == "/html/body/ol/li[3]/h3/a"
    assert (shifted.url, shifted.tag, shifted.accessor) == \
        (before.url, before.tag, before.accessor)


def test_a_rebuilt_address_is_a_well_formed_path():
    """No doubled separators, no empty steps -- the shapes a bad splice makes."""
    for tail in ("", "/span", "/article/h3/a/text()[1]"):
        out = _shifted_xpath("/html/body/ol/li" + tail, "/html/body/ol/li[4]")
        assert out is not None
        assert "//" not in out
        assert out.startswith("/html/body/ol/li[4]")
        assert all(step for step in out.split("/")[1:])
