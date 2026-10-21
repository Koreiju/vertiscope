"""Pipeline behaviour: parse → tag → tree → trie → chunk → render."""

from collections import Counter

import pytest

from vertiscope.pipeline import run_pipeline

URL = "https://riverside.example/catalog"

CARD_PATTERN = "/html/body/main/section/article"


def test_pipeline_produces_chunks_and_instances(catalog_html):
    r = run_pipeline(catalog_html, URL)
    assert r.chunks, "no chunks produced"
    assert r.instances, "no instances rendered"
    assert r.url == URL
    assert r.trie.version.pattern_count > 0
    assert r.elapsed_ms > 0


def test_repeating_cards_collapse_to_one_pattern(catalog_html):
    """The four card nodes must be ONE pattern, FOUR instances.

    claim: PROP-12.3

    PROP-12.3 says a generalization map induces an equivalence on nodes, hence
    a quotient, on which the commutation count is well defined. This asserts
    that quotient concretely: four structurally-identical siblings fall in one
    class of size four, rather than four classes of size one. If it regresses,
    the quotient has collapsed and retrieval returns near-duplicate rows.
    """
    r = run_pipeline(catalog_html, URL)
    counts = Counter(i.pattern for i in r.instances)
    assert counts[CARD_PATTERN] == 4, counts.most_common(5)


def test_instances_carry_distinguishing_content(catalog_html):
    """Each card instance must render its OWN text, not a shared template."""
    r = run_pipeline(catalog_html, URL)
    card_texts = [
        i.rendered_text for i in r.instances if i.pattern == CARD_PATTERN
    ]
    assert len(card_texts) == 4
    blob = " ".join(card_texts)
    for token in ("Ritchey", "Echelle", "CMOS", "Polarimeter"):
        assert token.lower() in blob.lower(), f"{token} missing from card renders"
    # and they must differ from one another
    assert len(set(card_texts)) == 4


def test_instances_have_stable_ids_across_runs(catalog_html):
    """instance_id is content-keyed, so a re-scan must not mint new ids.

    Scope note (COR-22.5.5): this holds the generalization map **fixed**, so it
    measures *determinism*, not *persistence*. Stability across a revision of
    the map is a different invariance and is unobservable in any fixed-map
    experiment — see notes/observations/2026-08-09-identity-blast-radius.md,
    where correcting the map re-keys 65.4% of identifiers while this test
    continues to pass.
    """
    a = run_pipeline(catalog_html, URL)
    b = run_pipeline(catalog_html, URL)
    ids_a = sorted(i.instance_id(URL) for i in a.instances)
    ids_b = sorted(i.instance_id(URL) for i in b.instances)
    assert ids_a == ids_b


def test_extraction_trie_is_populated(catalog_html):
    """Without all_tags threaded in, extraction tries come back empty and
    every instance extracts {} — a silent failure upstream hit before."""
    r = run_pipeline(catalog_html, URL)
    assert any(c.extraction_trie for c in r.chunks)


def test_urls_and_media_are_captured(catalog_html):
    r = run_pipeline(catalog_html, URL)
    all_fields = " ".join(
        str(i.fields) for i in r.instances if i.pattern == CARD_PATTERN
    )
    assert "/instrument/" in all_fields, "anchor hrefs not extracted"
    assert ".jpg" in all_fields, "image srcs not extracted"


def test_signal_detection_finds_search_and_pagination(catalog_html):
    r = run_pipeline(catalog_html, URL, detect_signal_fields=True)
    assert r.search_fields, "search input not detected"
    assert r.pagination_fields, "pagination not detected"


def test_signal_detection_is_off_by_default(catalog_html):
    """It is the most expensive stage; nothing in the retrieval path needs it."""
    r = run_pipeline(catalog_html, URL)
    assert r.search_fields == []
    assert r.pagination_fields == []
    assert "signals" not in r.stage_ms


def test_empty_html_raises(catalog_html):
    with pytest.raises(ValueError):
        run_pipeline("   ", URL)


def test_render_can_be_disabled(catalog_html):
    r = run_pipeline(catalog_html, URL, render=False)
    assert r.chunks
    assert r.instances == []


# --- tail text, once ---------------------------------------------------------


def _texts(html, url="https://x.test/"):
    tagged = run_pipeline(html, url).tagged
    return {t.xpath: t.value for t in tagged.all_tags if t.category == "text"}


def test_an_elements_tail_is_extracted_once():
    """`get_text(recursive=True)` already includes the node's own tail.

    It walks `iter_all()`, which yields **self** first and appends each node's
    text *and* tail. The tagger appended `node.tail` again on top, so any
    element with a tail — any inline element followed by text, the ordinary
    shape of prose with links in it — had a whole clause duplicated:

        <h1>World Wide Web</h1>The W3 is a wide-area…
        -> 'World Wide Web The W3 is a wide-area The W3 is a wide-area'

    Measured over a 40-page random sample of the corpus: **18.5%** of
    text-bearing elements affected, inflating extracted text by 18.5%. It hit
    prose hardest — RFC 9110, Wikipedia articles, the WHATWG spec, Pride and
    Prejudice — which is where extraction quality matters most.
    """
    html = ("<html><body><h1>World Wide Web</h1>The W3 is a wide-area"
            "<a href='/w'>hypermedia</a> retrieval.</body></html>")
    texts = _texts(html)

    heading = texts.get("/html/body/h1", "")
    assert heading.count("The W3 is a wide-area") == 1, heading
    anchor = texts.get("/html/body/a", "")
    assert anchor.count("retrieval.") == 1, anchor


def test_no_text_detection_repeats_its_own_tail(catalog_html):
    """The general form, over the fixture: no value ends with a doubled run."""
    offenders = []
    for xpath, value in _texts(catalog_html, "https://x.test/c").items():
        words = value.split()
        for size in range(2, min(9, len(words) // 2 + 1)):
            if words[-size:] == words[-2 * size:-size]:
                offenders.append((xpath, value[:70]))
                break
    assert not offenders, offenders


def test_tail_text_still_reaches_the_element_it_follows():
    """Removing the duplicate must not remove the tail.

    Attributing an element's tail to that element is deliberate — it is why
    `<li class="next"><a>Next</a></li>` labels its pager — so the fix has to
    keep exactly one copy, not zero.
    """
    html = "<html><body><p><a href='/x'>Alpha</a> and then some words.</p></body></html>"
    texts = _texts(html)
    joined = " ".join(texts.values())
    assert "and then some words." in joined


# --- text/plain is a document too --------------------------------------------


PLAIN = """RFC:  791

                          INTERNET PROTOCOL

                    DARPA INTERNET PROGRAM


PREFACE

This document specifies the DoD Standard Internet Protocol.
"""


def test_a_document_with_no_markup_still_yields_content():
    """`text/plain` is served on the web; the corpus carries two RFCs as .txt.

    The tagger walks *elements*, so a document with none emitted nothing at
    all — RFC 791, 1,020 reference words, zero lines out — while holding all
    94,909 characters on the parse root the whole time.
    """
    tagged = run_pipeline(PLAIN, "https://www.ietf.org/rfc/rfc791.txt").tagged
    texts = [t for t in tagged.all_tags if t.category == "text"]
    assert texts, "a plain-text document produced no text at all"
    joined = " ".join(t.value for t in texts)
    assert "INTERNET PROTOCOL" in joined
    assert "DoD Standard Internet Protocol" in joined


def test_plain_text_is_addressed_where_a_browser_would_put_it():
    """Browsers wrap a text/plain response in `/html/body/pre`.

    Using that xpath is not an invention: it is what the live scan will find,
    so an address minted offline resolves online. Paragraphs carry their
    character offset as the intrinsic sub-address, the same `@<offset>` a
    stylesheet's several urls use, so a paragraph is individually addressable
    rather than the whole file being one indivisible chunk.
    """
    tagged = run_pipeline(PLAIN, "https://www.ietf.org/rfc/rfc791.txt").tagged
    texts = [t for t in tagged.all_tags if t.category == "text"]
    assert {t.xpath for t in texts} == {"/html/body/pre"}
    subs = [t.sub for t in texts]
    assert all(s.startswith("@") for s in subs), subs
    assert len(set(subs)) == len(subs), "two paragraphs share an address"
    assert len(texts) > 1, "the whole file collapsed into one address"


def test_prose_containing_angle_brackets_is_not_mistaken_for_markup():
    """RFC 8259 parsed as 18 elements named `douglas`, `iesg` and `http:`.

    `html.parser` makes an element out of any angle bracket, so 28KB of text
    came out as 18 lines of accidental markup — worse than nothing, because
    the output depended on whether the prose happened to look like a tag.
    Recognised HTML tag *names* are what separate a page from a text file.
    """
    text = ("Author: <Douglas Crockford>\n\nSee <http://example.com/spec> "
            "for the grammar, and <IESG> for the process.\n")
    tagged = run_pipeline(text, "https://x.test/rfc.txt").tagged
    texts = [t for t in tagged.all_tags if t.category == "text"]
    joined = " ".join(t.value for t in texts)
    assert "Douglas Crockford" in joined
    assert "for the grammar" in joined
    assert {t.xpath for t in texts} == {"/html/body/pre"}


def test_a_real_page_is_not_treated_as_plain_text(catalog_html):
    """The guard must not fire on anything with real markup in it."""
    tagged = run_pipeline(catalog_html, "https://x.test/c").tagged
    assert not any(t.xpath == "/html/body/pre" and t.sub.startswith("@")
                   for t in tagged.all_tags)


def test_a_link_wrapping_a_card_keeps_the_card_structure():
    """The whole-card-is-a-link pattern, which is most of the modern web.

    `has_block_children` inspected only the *direct* children, so an inline
    `<a>` wrapping block content made the entire subtree look text-like and
    the card was swallowed into one detection on the parent. Measured heading
    recall before and after:

        stackexchange.com/sites    3.7%  ->  100%   (189 headings, 6 lines out)
        bbc.com/news              12.5%  ->  100%
        cbc.ca/news               28.6%  ->  100%

    The words always survived — recall stayed at 98% — but the structure did
    not, and structure is what makes the markdown navigable.
    """
    html = ("<html><body><a href='/sf'><div class='card'>"
            "<div class='wrap'><h2>Server Fault</h2>"
            "<img src='/i.png'><p>Q&amp;A for sysadmins</p></div>"
            "</div></a></body></html>")
    texts = _texts(html)
    assert texts.get("/html/body/a/div/div/h2") == "Server Fault"
    assert texts.get("/html/body/a/div/div/p") == "Q&A for sysadmins"
    assert "/html/body" not in texts, "the card was swallowed by its ancestor"


def test_an_inline_only_subtree_is_still_one_detection():
    """The rule it descends *through*, not past: prose with links in it stays
    one line rather than shattering into a fragment per anchor."""
    html = ("<html><body><p>See <a href='/a'>Alpha</a> and "
            "<em>Beta</em> for more.</p></body></html>")
    texts = _texts(html)
    assert texts.get("/html/body/p") == "See Alpha and Beta for more."
    assert "/html/body/p/a" not in texts


def test_a_mime_type_is_not_a_url():
    """`content="text/html; charset=UTF-8"` yielded `urls.internal '/html;'`.

    The absolute-path branch of the url regex treated the `/` in a MIME type
    as a path root. Found from the other end: a four-page crawl of
    books.toscrape.com spent one of its pages fetching
    `https://books.toscrape.com/html`, which is nothing, because
    `canonical_url('/html;', base)` is a perfectly well-formed url.
    """
    html = ('<html><head><meta http-equiv="Content-Type" '
            'content="text/html; charset=UTF-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '</head><body><a href="/catalogue/page-2.html">Next</a></body></html>')
    tagged = run_pipeline(html, "https://x.test/").tagged
    urls = [t.value for t in tagged.all_tags if t.category == "urls"]
    assert "/catalogue/page-2.html" in urls
    assert not any(u.startswith("/html") for u in urls), urls
    assert not any(u.startswith("/json") or u.startswith("/css") for u in urls), urls


def test_a_non_breaking_space_stays_a_space():
    """`&nbsp;` is a space, and it was being deleted.

    U+00A0 sat in the zero-width set alongside U+200B and the BOM, so the
    words on either side fused: letterboxd.com's `Upgrade to remove\xa0ads`
    came out as `Upgrade to removeads`. Not merely untidy — "ads" stops being
    a term, so the line cannot be found by searching for it, and that page's
    word recall read 99.6% instead of 100%.

    Across the corpus, 250 word-joining occurrences on 25 of 136 pages —
    Russian Wikipedia alone had 82.
    """
    html = ("<html><body><h5>Upgrade to remove&nbsp;ads</h5>"
            "<p>10&nbsp;000 items</p></body></html>")
    texts = " ".join(_texts(html).values())
    assert "remove ads" in texts, texts
    assert "removeads" not in texts
    assert "10 000 items" in texts


def test_zero_width_characters_are_still_deleted():
    """The other four are genuinely invisible and must stay deleted."""
    html = "<html><body><p>we" + "​" + "ird" + "﻿" + " text</p></body></html>"
    texts = " ".join(_texts(html).values())
    assert "weird text" in texts, repr(texts)


# --- deep nesting -----------------------------------------------------------


@pytest.mark.parametrize("depth", [600, 1500, 4000])
def test_a_deeply_nested_document_does_not_blow_the_stack(depth):
    """Nesting is data, not a recursion budget.

    Found by the wide sweep 2026-08-15: five pages crashed with
    `RecursionError` inside `_collapse_node`, which recursed once per link of
    a single-child chain. All five were PDFs being parsed as markup, but the
    cause has nothing to do with PDFs — a plain tower of `<div>`s crashes the
    same way, measured between depth 600 (fine) and 1200 (crash), and deep
    wrapper chains are ordinary in real markup.

    A crash is the wrong answer under every possible policy about what to do
    with a PDF, so this is fixed rather than filed: chain-following is a loop,
    and only genuine branch points recurse.
    """
    html = ("<html><body>" + "<div>" * depth + "deep content here"
            + "</div>" * depth + "</body></html>")

    result = run_pipeline(html, "https://x.test/")

    # It must survive *and* still find the content at the bottom.
    assert any("deep content here" in str(getattr(tag, "value", ""))
               for tag in result.tagged.all_tags), \
        f"survived depth {depth} but lost the content at the bottom"


def test_collapsing_a_chain_iteratively_matches_the_recursive_reading():
    """The loop that replaced the recursion must not have changed the tree.

    Removing a stack bound is only worth anything if the answer is the same,
    and "it stopped crashing" is not evidence of that. This runs the original
    recursive collapse beside the current one over real corpus pages and
    compares the serialized trees. Measured 2026-08-15: identical on all of
    them.
    """
    from vertiscope.core.xpath_tree_builder import (
        XPathTreeBuilder, _segments_to_path_key, resolve_tree_xpaths)

    def recursive_collapse(node, accumulated, output):
        for child_seg, child_node in node.children.items():
            chain = accumulated + [child_seg]
            if len(child_node.children) == 1 and not child_node.is_content:
                recursive_collapse(child_node, chain, output)
            else:
                key = _segments_to_path_key(chain)
                subtree = {}
                if child_node.is_content:
                    subtree["_content"] = sorted(child_node.content_categories)
                subtree["_xpath"] = key
                if child_node.children:
                    recursive_collapse(child_node, [], subtree)
                output[key] = subtree

    import pathlib as _pathlib
    corpus = _pathlib.Path(__file__).parent / "corpus"
    pages = sorted(corpus.glob("*.html"))[:8] if corpus.exists() else []
    if not pages:
        pytest.skip("frozen corpus absent; run scripts/fetch_corpus.py")

    for path in pages:
        tagged = run_pipeline(
            path.read_text(encoding="utf-8", errors="replace"),
            f"https://{path.stem}/").tagged

        current = XPathTreeBuilder()
        current.add_tagged_content(tagged)

        legacy = XPathTreeBuilder()
        legacy.add_tagged_content(tagged)
        out = {}
        recursive_collapse(legacy._root, [], out)

        assert current.build() == resolve_tree_xpaths(out), \
            f"{path.stem}: the iterative collapse changed the tree"
