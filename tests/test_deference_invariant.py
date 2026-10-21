"""One invariant, enforced rather than remembered.

A DEFERENCE rule is one where a unit stands down because another will speak
for it: the text is dropped because a control will draw it, the href is
hidden because the anchor says the words, the suppressed link draws itself
only when nothing else is there.

Such a rule must be asked of the units that SURVIVE `_dedupe`, never of the
units that were collected. Three defects in one session came from asking one
too early, and each time the answer was written down as a comment, and each
time the next instance appeared anyway:

* `alone` counted collected units, so `<a>Disable MathJax</a>` drew nothing.
* `consumed` did too, so `<button aria-label="Move Main menu to sidebar">`
  drew nothing.
* the url branch had it first, and its comment is where the rule was written:
  "taken from `kept`, not from `units`".

`_draw_lines` takes `kept` and nothing else, so the wrong version cannot be
written. These tests keep it that way.
"""

import ast
import inspect

import pytest

import vertiscope.markdown as markdown
from vertiscope.core.content_tagger import ContentTagger
from vertiscope.core.shadow_html_parser import ShadowDOM
from vertiscope.markdown import render_trie
from vertiscope.trie import AddressTrie


def _render(html, window=900):
    trie = AddressTrie.from_tagged(
        ContentTagger(ShadowDOM(html)).tag(), "https://x.test/")
    return [ln for chunk in render_trie(trie, context_window=window)
            for ln in chunk.lines if ln.text.strip()]


# --- the structural half --------------------------------------------------------

def _function(name):
    tree = ast.parse(inspect.getsource(markdown))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError("%s is gone -- if it was renamed, this test has to "
                         "follow it, not be deleted" % name)


def test_the_post_dedupe_phase_cannot_see_the_collected_units():
    """The constraint, stated as code rather than as a comment.

    Every deference rule lives in `_draw_lines`, and `_draw_lines` receives
    only `kept`. If a future edit passes `units` in to make some rule easier,
    that rule becomes writeable again and this fails.
    """
    node = _function("_draw_lines")
    params = [a.arg for a in node.args.args + node.args.kwonlyargs]
    assert "units" not in params, \
        "`units` was passed into the post-dedupe phase: %s" % params

    referenced = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
    for forbidden in ("units", "units_at"):
        assert forbidden not in referenced, \
            "`%s` is read inside `_draw_lines`" % forbidden


def test_the_deference_rules_are_all_in_one_place():
    """`consumed` is the deference set; it must not be built anywhere else.

    Two versions of it in two scopes is how the last defect survived a fix to
    the first one.
    """
    source = inspect.getsource(markdown)
    outside = [ln for ln in source.splitlines()
               if ln.strip().startswith(("consumed =", "consumed |=",
                                         "consumed -=", "consuming ="))]
    node = _function("_draw_lines")
    inside = [ln for ln in ast.get_source_segment(
        source, node).splitlines()
        if ln.strip().startswith(("consumed =", "consumed |="))]
    assert len(outside) == len(inside), (
        "a deference set is built outside `_draw_lines`:\n  %s"
        % "\n  ".join(outside))


# --- the behavioural half --------------------------------------------------------

DEFERRED = {
    "control consumes its text":
        "<html><body><button>Add to basket</button><p>filler</p></body></html>",
    "aria-label subsumes the control":
        "<html><body><button aria-label='Move Main menu to sidebar'>"
        "move to sidebar</button><p>filler</p></body></html>",
    "anchor with no href":
        "<html><body><a>Disable MathJax</a><p>filler</p></body></html>",
    "anchor whose words are its own":
        "<html><body><p>See <a href='/n'>next page</a> now.</p></body></html>",
    "control wrapping a control":
        "<html><body><button><span>Menu</span></button><p>filler</p>"
        "</body></html>",
}


@pytest.mark.parametrize("name,html", sorted(DEFERRED.items()))
def test_every_deference_shape_still_says_its_words(name, html):
    """Whichever unit is dropped, exactly one has to remain.

    `_dedupe`'s docstring states it; this checks it on each shape where two
    rules could both defer. The failure mode is silent: the element simply
    has no line, and every address is still accounted for in some bucket.
    """
    drawn = " | ".join(ln.text for ln in _render(html))
    words = {"add", "sidebar", "mathjax", "next", "menu"}
    said = [w for w in words if w in drawn.lower()]
    assert said, "%s: the element drew nothing at all -- %r" % (name, drawn)
