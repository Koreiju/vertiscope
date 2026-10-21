"""A listbox's own value is the option it shows, not every option it holds.

`_own_label` walks an element's descendants, which is right for a button
wrapping a span and wrong for a `<select>`: a listbox's descendants are its
OPTIONS, and the tagger already emits each one as its own detection at its
own xpath. Reading them as the select's label recorded the whole list a
second time, as one value.

The case that found it: data.gov.uk's publisher filter holds 1,511 options,
and its select's own value came out at 43,542 characters -- 7,745 tokens
against a 512-token window, fifteen times over, in a chunk whose single line
no reader can navigate, beside the same content already properly addressed.

The rule these hold is the browser's: a collapsed select paints the option
that is `selected`, and nothing when none is.
"""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from vertiscope import tokens                                   # noqa: E402
from vertiscope.core.content_tagger import ContentTagger        # noqa: E402
from vertiscope.core.shadow_html_parser import ShadowDOM        # noqa: E402
from vertiscope.markdown import DEFAULT_CONTEXT_WINDOW, render_trie  # noqa: E402
from vertiscope.trie import AddressTrie                         # noqa: E402

URL = "https://s.test/"


def _trie(body: str) -> AddressTrie:
    html = "<html><body>%s</body></html>" % body
    return AddressTrie.from_tagged(ContentTagger(ShadowDOM(html)).tag(), URL)


def _value_at(trie: AddressTrie, xpath: str, tag: str = "interactive.inputs"):
    for address in trie.addresses():
        if address.xpath == xpath and address.tag == tag:
            return trie.find(address).value
    return None


SELECT = "/html/body/select"


def test_a_selected_option_is_the_listbox_value():
    trie = _trie(
        "<select name=k>"
        "<option value=a>Alpha</option>"
        "<option value=b selected>Bravo</option>"
        "<option value=c>Charlie</option>"
        "</select>")
    assert _value_at(trie, SELECT) == "Bravo"


def test_an_unselected_listbox_names_itself_from_its_attributes():
    """No selection is no value, and the control is still named.

    Not the first option: a filter that opens on a blank row has made no
    choice, and naming it after the first entry reports a filter as applied
    when it is not.
    """
    trie = _trie(
        "<select name=k aria-label='Publisher'>"
        "<option value=''></option>"
        "<option value=a>Alpha</option>"
        "</select>")
    assert _value_at(trie, SELECT) == "Publisher"


def test_an_unnamed_unselected_listbox_falls_back_to_its_tag():
    """`[ ] select` -- the same last resort `<input>` already takes."""
    trie = _trie("<select name=k><option value=a>Alpha</option></select>")
    assert _value_at(trie, SELECT) == "select"


def test_every_option_keeps_its_own_address():
    """The half that makes dropping the aggregate safe.

    The options are not being discarded; they were always addressed
    individually, which is why the aggregate was a duplicate.
    """
    trie = _trie(
        "<select name=k>"
        "<option value=a>Alpha</option>"
        "<option value=b>Bravo</option>"
        "</select>")
    options = {a.xpath for a in trie.addresses() if "option" in (a.xpath or "")}
    assert options == {SELECT + "/option[1]", SELECT + "/option[2]"}
    assert _value_at(trie, SELECT + "/option[1]") == "Alpha"
    assert _value_at(trie, SELECT + "/option[2]") == "Bravo"


def test_a_button_still_takes_the_words_of_its_descendants():
    """Non-vacuity: the rule is scoped to listboxes and nothing else.

    `_own_label`'s descent is correct everywhere else, and a change that
    turned it off generally would unname every wrapped control on the web.
    """
    trie = _trie("<button><span>Menu</span></button>")
    assert _value_at(trie, "/html/body/button",
                     tag="interactive.buttons") == "Menu"


def test_a_long_option_list_no_longer_makes_an_oversized_chunk():
    """The user-visible symptom, at the scale that produced it.

    1,500 options of the shape data.gov.uk uses. Before the rule, the
    select's own line alone was fifteen times the window.
    """
    options = "".join("<option value='Body %d'>Body %d</option>" % (i, i)
                      for i in range(1, 1501))
    trie = _trie("<select name=publisher><option value=''></option>%s</select>"
                 % options)

    assert tokens.count(_value_at(trie, SELECT) or "") < 10

    chunks = render_trie(trie)
    worst = max(tokens.count(c.markdown) for c in chunks)
    # The cap is the LENIENT bound, not the window: a run may take the piece
    # that crosses the window while it stays under 1.5x (`markdown.LENIENCY`,
    # G-86 -- the user's rule of 2026-09-26).
    from vertiscope.markdown import LENIENCY
    assert worst <= LENIENCY * DEFAULT_CONTEXT_WINDOW, (
        "worst chunk %d tokens against a %d window (lenient to %gx)"
        % (worst, DEFAULT_CONTEXT_WINDOW, LENIENCY))

    # And the options are all still there, one addressed line each.
    drawn = {line.text.strip() for c in chunks for line in c.lines}
    assert "[ ] Body 1" in drawn and "[ ] Body 1500" in drawn


@pytest.mark.parametrize("tag", ["select", "datalist", "optgroup"])
def test_the_rule_covers_every_container_whose_children_are_options(tag):
    trie = _trie("<%s name=k><option value=a>Alpha</option>"
                 "<option value=b selected>Bravo</option></%s>" % (tag, tag))
    assert _value_at(trie, "/html/body/%s" % tag) == "Bravo"
