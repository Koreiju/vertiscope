"""The xpath shape: a second dimension beside the address, never instead of it.

R-C4 asked whether the address itself could go index-agnostic -- "absolute
structure with agnostic array indices for multiple/repeat fields like menu
items, paragraphs, search results". The corpus answered that the premise is
right and the substitution is not:

    distinct addresses with indices   23,654
    distinct by shape                  2,831   (88.0% fewer)
    shapes covering >1 element          1,290
    of those, covering DIFFERENT content 1,022  (79.2%)

So four shapes in five cover elements that say different things. These tests
hold both halves: the shape groups what it should, and it is never allowed to
become the thing that identifies an element.
"""

import pytest

from vertiscope.address import ContentAddress


def at(xpath, tag="text.visible", accessor="text()", url="https://s.test/"):
    return ContentAddress(url=url, xpath=xpath, tag=tag, accessor=accessor)


# --- what it is for ---------------------------------------------------------

def test_repeats_of_one_template_share_a_shape():
    """The premise: a page's list is one template, drawn N times."""
    rows = [at("/html/body/ol/li[%d]/article/h3" % i) for i in range(1, 6)]
    assert len({r.shape for r in rows}) == 1
    assert rows[0].shape == "/html/body/ol/li/article/h3"


def test_the_shape_survives_an_inserted_sibling():
    """Why it is worth having at all.

    Inserting a row shifts the index of every row below it and changes none
    of their shapes -- so a shape is stable across re-scans where an address
    is not.
    """
    before = at("/html/body/ol/li[7]/a")
    after_insertion = at("/html/body/ol/li[8]/a")
    assert before.shape == after_insertion.shape
    assert before.xpath != after_insertion.xpath


def test_different_templates_do_not_collide():
    """Non-vacuity: a rule that maps everything to one string groups nothing."""
    assert at("/html/body/ol/li[1]/a").shape != at("/html/body/ul/li[1]/a").shape
    assert at("/html/body/ol/li[1]/a").shape != at("/html/body/ol/li[1]/p").shape


# --- what it must never become ----------------------------------------------

def test_the_shape_is_not_the_identity():
    """The measured reason: 79.2% of shared shapes hold different content.

    An address is a POINTER -- `enact` presses it, the REPL resolves it
    against a live DOM, the store keys chunks on it. Two siblings sharing a
    shape are two elements, and a shape cannot point at either.
    """
    a = at("/html/body/ol/li[11]/article/h3")
    b = at("/html/body/ol/li[12]/article/h3")
    assert a.shape == b.shape
    assert a.aid != b.aid
    assert a.key() != b.key()
    assert a != b


def test_the_shape_changes_no_stored_field():
    """Derived, never stored -- the rule `render_class` already follows.

    If the shape reached the xpath, every key would change and every row
    would have to migrate. It is computed on read instead.
    """
    address = at("/html/body/ol/li[11]/article/h3")
    assert address.xpath == "/html/body/ol/li[11]/article/h3"
    assert "shape" not in ContentAddress.__dataclass_fields__
    round_tripped = ContentAddress.parse(address.key())
    assert round_tripped == address
    assert round_tripped.shape == address.shape


def test_an_address_with_no_indices_is_its_own_shape():
    address = at("/html/body/main/p")
    assert address.shape == address.xpath


@pytest.mark.parametrize("xpath,expected", [
    ("/html/body/div[11]/a", "/html/body/div/a"),
    ("/html/body/div[1]/a[2]", "/html/body/div/a"),
    ("", ""),
])
def test_every_index_is_dropped_and_nothing_else_is(xpath, expected):
    """`div[11]` must not become `div1`: the whole bracket goes, or none."""
    assert at(xpath).shape == expected
