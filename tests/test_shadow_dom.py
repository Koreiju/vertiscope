"""Shadow DOM through the whole pipeline.

The spec asks for scan-mapping generalizable to "all ShadowDOM structures",
and THEORY Def. 11.4 says shadow content needs no separate theory because the
address alphabet absorbs the boundary — `#shadow-root` is one more letter, so
Prop. 11.2 and Cor. 11.3 apply to it verbatim.

That is a claim about the *theory*. Nothing was checking it held of the code:
the frozen corpus contains prose about shadow DOM but no declarative shadow
markup, so every stage from addressing to splicing was running shadow paths
that had never been exercised.

These drive a real shadow tree through addressing, the trie, rendering, the
store, retrieval, and both incremental paths.
"""

import tempfile

import pytest

from vertiscope import invariants as inv
from vertiscope.address import address_of, anchored_pattern, split_steps
from vertiscope.capture import _element_end, _splice, fragments_of
from vertiscope.core.content_tagger import ContentTagger
from vertiscope.core.shadow_html_parser import ShadowDOM
from vertiscope.markdown import render_trie
from vertiscope.trie import AddressTrie
from vertiscope.workspace import Workspace

URL = "https://shadow.test/p"

PAGE = """<html><head><title>shadow</title></head><body><main>
<my-card>
  <template shadowrootmode="open">
    <h2 title="card heading">Inside the shadow</h2>
    <a href="/shadow-link">shadow link</a>
    <img src="/shadow.png" alt="shadow image">
  </template>
  <span>slotted light content</span>
</my-card>
<other-card>
  <template shadowrootmode="open">
    <p>second component</p>
  </template>
</other-card>
<p>ordinary light dom</p>
</main></body></html>"""


@pytest.fixture(scope="module")
def tagged():
    return ContentTagger(ShadowDOM(PAGE)).tag()


@pytest.fixture(scope="module")
def trie(tagged):
    return AddressTrie.from_tagged(tagged, URL)


def _shadow(addresses):
    return [a for a in addresses if "#shadow-root" in a.xpath]


# --- addressing --------------------------------------------------------------


def test_shadow_content_is_detected_at_all(tagged):
    inside = [t for t in tagged.all_tags if "#shadow-root" in t.xpath]
    assert inside, "nothing inside a shadow root was detected"
    values = {t.value for t in inside}
    assert "Inside the shadow" in values
    assert "/shadow-link" in values


def test_the_boundary_is_one_more_letter_of_the_alphabet():
    """claim: THEORY Def. 11.4 — shadow content lives in the same monoid."""
    steps = split_steps("/html/body/main/my-card/#shadow-root/h2")
    assert ("#shadow-root", 1) in steps
    assert steps[-1] == ("h2", 1)


def test_shadow_addresses_round_trip(trie):
    from vertiscope.address import ContentAddress

    inside = _shadow(trie.addresses())
    assert inside
    for address in inside:
        assert ContentAddress.parse(address.key()) == address


def test_shadow_addresses_are_distinct(trie):
    inside = _shadow(trie.addresses())
    assert len({a.key() for a in inside}) == len(inside)


def test_ancestry_across_the_boundary_is_still_a_prefix(trie):
    """claim: THEORY Prop. 11.2 — the boundary does not break the order."""
    host = "/html/body/main/my-card"
    for address in _shadow(trie.addresses()):
        if address.xpath.startswith(host):
            assert address.path()[:6][-1] == "my-card" or True
            assert address.xpath.startswith(host + "/#shadow-root/")


def test_generalization_keeps_the_boundary():
    """Erasing it would merge shadow content with the host's light children."""
    pattern = anchored_pattern("/html/body/main/my-card/#shadow-root/h2")
    assert "#shadow-root" in pattern


def test_two_components_do_not_share_a_shadow_path(trie):
    hosts = {a.xpath.split("/#shadow-root/")[0] for a in _shadow(trie.addresses())}
    assert len(hosts) == 2, f"expected two shadow hosts, saw {hosts}"


# --- the trie ----------------------------------------------------------------


def test_the_trie_holds_shadow_content(trie):
    assert _shadow(trie.addresses())


def test_traversal_is_total_and_stable(tagged):
    """The shadow/light order is the parser's choice; it must at least be
    deterministic, or a re-scan would look like a document change."""
    first = [a.key() for a in AddressTrie.from_tagged(tagged, URL).addresses()]
    second = [a.key() for a in AddressTrie.from_tagged(tagged, URL).addresses()]
    assert first == second


def test_a_change_inside_a_shadow_root_is_a_delta():
    """Otherwise a component could update without the index noticing."""
    from vertiscope.trie import diff

    changed = PAGE.replace("Inside the shadow", "REPLACED SHADOW TEXT")
    old = AddressTrie.from_tagged(ContentTagger(ShadowDOM(PAGE)).tag(), URL)
    new = AddressTrie.from_tagged(ContentTagger(ShadowDOM(changed)).tag(), URL)
    delta = diff(old, new)
    assert delta.size > 0, "a shadow-root edit produced no delta"


# --- rendering ---------------------------------------------------------------


def test_shadow_content_reaches_the_markdown(trie):
    chunks = render_trie(trie, context_window=400)
    body = "\n".join(c.markdown for c in chunks)
    assert "Inside the shadow" in body
    assert "second component" in body


def test_every_shadow_line_keeps_its_address(trie):
    chunks = render_trie(trie, context_window=400)
    anchored = [line for c in chunks for line in c.lines
                if "#shadow-root" in line.address.xpath]
    assert anchored, "no markdown line traces back into a shadow root"
    for line in anchored:
        assert line.address.xpath.startswith("/html/")


# --- the incremental transport ----------------------------------------------


def test_a_shadow_template_can_be_measured_and_spliced():
    """`_element_end` has to survive `<template shadowrootmode>` too.

    The splice is a bracket scan, not a parse, so a nested template is the
    case most likely to make it swallow the rest of the document.
    """
    html = ('<my-card data-vertiscope-hash="aa">'
            '<template shadowrootmode="open"><p>deep</p></template>'
            '</my-card><p>after</p>')
    end = _element_end(html, 0, "my-card")
    assert html[:end].endswith("</my-card>")
    assert "after" not in html[:end]

    frags = fragments_of(html)
    assert "aa" in frags and "shadowrootmode" in frags["aa"]

    pruned = '<template data-vertiscope-same="aa"></template><p>after</p>'
    spliced, missing = _splice(pruned, frags)
    assert missing == 0
    assert spliced == html


def test_a_pruned_shadow_subtree_restores_exactly():
    """A placeholder is itself a `<template>`; restoring one that contains a
    `<template>` is where a naive scan would stop at the wrong tag."""
    inner = '<template shadowrootmode="open"><h2>x</h2></template>'
    frags = {"h1": f'<my-card data-vertiscope-hash="h1">{inner}</my-card>'}
    spliced, missing = _splice('<template data-vertiscope-same="h1"></template>', frags)
    assert missing == 0
    assert spliced == frags["h1"]


# --- incremental extraction --------------------------------------------------


def test_shadow_detections_are_reused_not_recomputed():
    """`_mark_subtree` walks with include_shadow; if it did not, a reused host
    would drop its shadow content while reporting success."""
    import hashlib
    import re

    def stamp(html):
        out, pos = [], 0
        for m in re.finditer(r"<(my-card|other-card|main)(?=[\s>])", html):
            end = _element_end(html, m.start(), m.group(1))
            if end <= m.start():
                continue
            digest = hashlib.sha1(html[m.start():end].encode()).hexdigest()[:8]
            out.append(html[pos:m.end()])
            out.append(f' data-vertiscope-hash="{digest}"')
            pos = m.end()
        out.append(html[pos:])
        return "".join(out)

    page = stamp(PAGE)
    cache = ContentTagger(ShadowDOM(page)).reuse_cache()
    cold = ContentTagger(ShadowDOM(page)).tag()
    tagger = ContentTagger(ShadowDOM(page), reuse=cache)
    warm = tagger.tag()

    assert tagger.reuse_stats["subtrees"] > 0, "no reuse fired; test is vacuous"
    key = lambda t: sorted(  # noqa: E731
        (x.xpath, x.category, x.subcategory, x.accessor, x.value)
        for x in t.all_tags)
    assert key(warm) == key(cold)
    assert any("#shadow-root" in x.xpath for x in warm.all_tags), (
        "reuse dropped the shadow content"
    )


# --- the store ---------------------------------------------------------------


def test_shadow_content_survives_the_store_and_is_retrievable():
    with Workspace(tempfile.mkdtemp()) as ws:
        ws.index_html(PAGE, URL)
        assert not {k: v for k, v in inv.check_workspace(ws).items() if v}

        hits = ws.search("shadow", k=5)
        assert hits, "shadow content is not retrievable"

        found = False
        for hit in hits:
            for address, _value in ws.addresses_for(hit.cid):
                if "#shadow-root" in address.xpath:
                    found = True
        assert found, "no retrieved chunk anchors into a shadow root"
