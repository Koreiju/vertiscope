"""Reusing detections for unchanged subtrees.

The correctness bar is absolute and simple: **a reused pass must produce
exactly what a full pass would**. A faster tagger that returns slightly
different detections is not an optimisation, it is a corruption that only
shows up later, in an index nobody can explain.

So every test here compares against re-tagging from scratch, on the same
input, including values — not just counts, which would pass while the wrong
subtree's content was spliced in.
"""

import json
import pathlib
import re

import pytest

from vertiscope.core.content_tagger import ContentTagger
from vertiscope.core.shadow_html_parser import ShadowDOM

CORPUS = pathlib.Path(__file__).parent / "corpus"
MANIFEST = CORPUS / "manifest.json"


def stamp(html: str) -> str:
    """Add subtree digests the way the serializer does.

    **Content-derived**, computed over the element's own outer HTML, which is
    the contract the reuse mechanism rests on: equal digest must mean equal
    subtree. An earlier version of this helper hashed the opening tag and a
    counter, so two documents differing in their text got identical digests —
    and the reuse spliced in the *previous* document's detections while every
    count matched. That is the failure mode this whole file exists to catch,
    and it caught the helper first.
    """
    import hashlib

    from vertiscope.capture import _element_end

    out = []
    pos = 0
    for match in re.finditer(r"<(div|ul|li|section|article|main|nav|p|a|span|h1|h2|h3)(?=[\s>])",
                             html):
        end = _element_end(html, match.start(), match.group(1))
        if end <= match.start():
            continue
        digest = hashlib.sha1(html[match.start():end].encode()).hexdigest()[:8]
        insert = match.end()
        out.append(html[pos:insert])
        out.append(f' data-vertiscope-hash="{digest}"')
        pos = insert
    out.append(html[pos:])
    return "".join(out)


def detections(tagged):
    """Full comparison key: position, kind, provenance *and* value."""
    return sorted((t.xpath, t.category, t.subcategory, t.accessor, t.value)
                  for t in tagged.all_tags)


PAGE = stamp("""
<html><head><title>t</title></head><body>
<main>
  <section id="a"><h1>Alpha</h1><p>first paragraph</p>
    <ul><li><a href="/one">one</a></li><li><a href="/two">two</a></li></ul></section>
  <section id="b"><h2>Beta</h2><p title="labelled">second</p>
    <img src="/x.png" alt="a picture"></section>
</main></body></html>
""")


# --- correctness -------------------------------------------------------------


def test_a_reused_pass_equals_a_full_pass():
    cache = ContentTagger(ShadowDOM(PAGE)).reuse_cache()
    cold = ContentTagger(ShadowDOM(PAGE)).tag()
    tagger = ContentTagger(ShadowDOM(PAGE), reuse=cache)
    warm = tagger.tag()

    assert tagger.reuse_stats["subtrees"] > 0, "nothing was reused; test is vacuous"
    assert detections(warm) == detections(cold)


def test_walk_positions_survive_reuse():
    """Sibling order is not recoverable from the addresses (PROP-11.3.1).

    The reused subtree's nodes are still *visited*, only not examined, so
    doc_pos must come out complete — otherwise the trie silently falls back
    to label order for exactly the regions that did not change.
    """
    cache = ContentTagger(ShadowDOM(PAGE)).reuse_cache()
    cold = ContentTagger(ShadowDOM(PAGE)).tag()
    warm = ContentTagger(ShadowDOM(PAGE), reuse=cache).tag()

    assert set(warm.doc_pos) == set(cold.doc_pos)
    order_cold = sorted(cold.doc_pos, key=cold.doc_pos.get)
    order_warm = sorted(warm.doc_pos, key=warm.doc_pos.get)
    assert order_warm == order_cold


def test_category_buckets_are_repopulated():
    """all_tags is not the only output; the per-category lists feed the chunker."""
    cache = ContentTagger(ShadowDOM(PAGE)).reuse_cache()
    cold = ContentTagger(ShadowDOM(PAGE)).tag()
    warm = ContentTagger(ShadowDOM(PAGE), reuse=cache).tag()
    assert warm.all_content_xpaths() == cold.all_content_xpaths()


def test_a_changed_subtree_is_re_examined():
    """Reuse must not survive a change, or the index goes stale silently."""
    changed = PAGE.replace("first paragraph", "COMPLETELY DIFFERENT TEXT")
    changed = stamp(re.sub(r'\s*data-vertiscope-hash="[^"]*"', "", changed))

    cache = ContentTagger(ShadowDOM(PAGE)).reuse_cache()
    warm = ContentTagger(ShadowDOM(changed), reuse=cache).tag()
    cold = ContentTagger(ShadowDOM(changed)).tag()

    assert detections(warm) == detections(cold)
    assert any("COMPLETELY DIFFERENT TEXT" in t.value for t in warm.all_tags)


def test_reuse_is_keyed_on_position_as_well_as_content():
    """A subtree that moved has the same content and different addresses.

    Keying on the digest alone would splice in detections pointing at where
    the content used to be — a wrong answer that looks entirely plausible.
    """
    tagger = ContentTagger(ShadowDOM(PAGE))
    cache = tagger.reuse_cache()
    assert cache, "no cache to test with"
    for (xpath, _digest), tags in cache.items():
        for entry in tags:
            assert entry.xpath == xpath or entry.xpath.startswith(xpath.rstrip("/") + "/"), (
                f"cache entry for {xpath} holds a detection at {entry.xpath}"
            )


def test_an_empty_cache_changes_nothing():
    cold = ContentTagger(ShadowDOM(PAGE)).tag()
    warm = ContentTagger(ShadowDOM(PAGE), reuse={}).tag()
    assert detections(warm) == detections(cold)


def test_a_stale_cache_entry_is_simply_not_matched():
    """A digest that no longer occurs must be ignored, not spliced anywhere."""
    bogus = {("/html/body/main/section", "deadbeef"): []}
    cold = ContentTagger(ShadowDOM(PAGE)).tag()
    tagger = ContentTagger(ShadowDOM(PAGE), reuse=bogus)
    warm = tagger.tag()
    assert tagger.reuse_stats["subtrees"] == 0
    assert detections(warm) == detections(cold)


# --- the contract the reuse rests on ----------------------------------------


def test_the_serializer_hashes_everything_the_tagger_reads():
    """The soundness condition, checked against the two source files.

    Reuse is only sound if the digest changes whenever anything the extractor
    reads changes. The first serializer hashed fifteen hand-picked attributes
    while the extractor read `style`, `cite`, `longdesc`, `formaction` and
    every JSON-bearing `data-*`, so a subtree whose only change was in one of
    those hashed equal and the stale detections were spliced back in.

    Rather than restate the list in a third place, this asserts the shape of
    the fix: the hasher works by *exclusion*, and its skip list does not
    exclude anything the tagger treats as content.
    """
    root = pathlib.Path(__file__).parent.parent
    js = (root / "vertiscope" / "core" / "js" / "deep_serialize.js").read_text(
        encoding="utf-8")

    assert "SKIP_ATTRS" in js and "skipAttr(" in js, (
        "the hasher no longer works by exclusion; a hand-picked allowlist "
        "cannot be kept in step with what the extractor reads"
    )
    assert "IDENT_ATTRS" not in js, "the allowlist came back"

    from vertiscope.core import content_tagger as ct

    # Anything the tagger reads as content must not be skipped by the hasher.
    reads = set(ct._TEXT_ATTRS) | set(ct._META_TEXT_ATTRS) | set(ct._URL_BEARING_ATTRS)
    reads |= {"srcset", "style", "content"}
    skipped = set(re.findall(r"'([a-z-]+)':\s*1", js))
    leaked = reads & skipped
    assert not leaked, f"the hasher ignores attributes the tagger reads: {leaked}"


# --- the digest attribute is machinery, not content -------------------------


def test_the_hash_attribute_is_never_tagged_as_content():
    """Otherwise hex digests enter the index — and worse, the index would
    change on every pass for pages that had not changed at all."""
    tagged = ContentTagger(ShadowDOM(PAGE)).tag()
    for entry in tagged.all_tags:
        assert "vertiscope" not in entry.accessor
        assert not re.fullmatch(r"[0-9a-f]{8}", entry.value or "")


# --- against real pages ------------------------------------------------------


def _pages(limit=6):
    if not MANIFEST.exists():
        return []
    pages = [p for p in json.loads(MANIFEST.read_text())["pages"] if p.get("ok")]
    return [p for p in pages if (CORPUS / f"{p['slug']}.html").exists()][:limit]


@pytest.mark.parametrize("page", _pages() or [None])
def test_real_pages_reuse_without_changing_the_result(page):
    if page is None:
        pytest.skip("frozen corpus absent")
    html = stamp((CORPUS / f"{page['slug']}.html").read_text(
        encoding="utf-8", errors="replace"))

    cache = ContentTagger(ShadowDOM(html)).reuse_cache()
    cold = ContentTagger(ShadowDOM(html)).tag()
    tagger = ContentTagger(ShadowDOM(html), reuse=cache)
    warm = tagger.tag()

    assert detections(warm) == detections(cold), page["slug"]
    assert tagger.reuse_stats["subtrees"] > 0, f"{page['slug']}: no reuse fired"
    assert set(warm.doc_pos) == set(cold.doc_pos), page["slug"]


@pytest.mark.parametrize("page", _pages(3) or [None])
def test_reuse_covers_most_of_a_real_page(page):
    """A cache that matches only leaves would be correct and pointless."""
    if page is None:
        pytest.skip("frozen corpus absent")
    html = stamp((CORPUS / f"{page['slug']}.html").read_text(
        encoding="utf-8", errors="replace"))
    cache = ContentTagger(ShadowDOM(html)).reuse_cache()
    tagger = ContentTagger(ShadowDOM(html), reuse=cache)
    tagged = tagger.tag()

    reused = tagger.reuse_stats["tags_reused"]
    assert reused > len(tagged.all_tags) * 0.5, (
        f"{page['slug']}: only {reused} of {len(tagged.all_tags)} tags reused"
    )
