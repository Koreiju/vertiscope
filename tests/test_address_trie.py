"""The addressing scheme and the universal trie.

Two claims are under test, and they are the two halves of what makes the
address usable as a primary key everywhere downstream:

**uniqueness** — no address carries two different values, so a store keyed on
addresses never merges distinct content;

**completeness** — every detection gets an address and every address comes
from a detection, so nothing is dropped and nothing is invented.

Both are asserted structurally on small inputs (where the reason is visible)
and measured over the 54-page corpus (where the reason might not hold).
"""

import json
import pathlib

import pytest

from vertiscope.address import (
    ContentAddress,
    address_of,
    addresses_of,
    anchored_pattern,
    collisions,
    relative_to,
    split_steps,
    url_steps,
)
from vertiscope.core.content_tagger import ContentTag
from vertiscope.pipeline import run_pipeline
from vertiscope.trie import AddressTrie, content_hash, diff, token_multiset

CORPUS = pathlib.Path(__file__).parent / "corpus"
MANIFEST = CORPUS / "manifest.json"


def _corpus_pages():
    if not MANIFEST.exists():
        return []
    pages = [p for p in json.loads(MANIFEST.read_text())["pages"] if p.get("ok")]
    return [p for p in pages if (CORPUS / f"{p['slug']}.html").exists()]


# --- the address key --------------------------------------------------------


def test_key_round_trips():
    a = ContentAddress("https://x.test/p", "/html/body/a[2]", "urls.external", "href")
    assert ContentAddress.parse(a.key()) == a


@pytest.mark.parametrize("hostile", ["a|b", "a%b", "a%7Cb", "a%25%7Cb", "|", "%"])
def test_key_is_injective_under_hostile_components(hostile):
    """The separator must not be forgeable out of component content.

    Without escaping, a url containing the separator would let one address
    impersonate another — the store would then hold one row for two facts,
    which is exactly the merge the key exists to prevent.
    """
    a = ContentAddress(f"https://x.test/{hostile}", "/html/a", "urls.external", hostile)
    b = ContentAddress("https://x.test/", f"/html/{hostile}", "urls.external", "href")
    assert ContentAddress.parse(a.key()) == a
    assert ContentAddress.parse(b.key()) == b
    assert a.key() != b.key()


def test_aid_is_derived_from_the_key():
    a = ContentAddress("https://x.test/", "/html/a", "urls.external", "href")
    assert a.aid == ContentAddress.parse(a.key()).aid
    assert len(a.aid) == 16


# --- generalization ---------------------------------------------------------


def test_landmark_anchoring_separates_regions():
    """claim: THEORY Prop. 12.4 — distinct anchors are never equivalent.

    Erasing all indices collapses a nav list into a body list; that collapse
    is why nav fragments outranked prose in retrieval.
    """
    nav = "/html/body/div[3]/nav[1]/ul[2]/li[7]/a[1]"
    body = "/html/body/div[3]/main[1]/div[2]/ul[1]/li[4]/a[1]"
    assert anchored_pattern(nav) != anchored_pattern(body)
    # and the retained prefix really is verbatim, indices included
    assert anchored_pattern("/html/body/div[3]/main[1]/ul[2]/li[7]").startswith(
        "/html/body/div[3]/main"
    )


def test_anchoring_degrades_to_full_erasure_without_landmarks():
    assert anchored_pattern("/html/body/div[2]/span[5]") == "/html/body/div/span"


def test_generalization_is_idempotent():
    """A pattern is a fixed point: generalizing it again must not move it."""
    for xp in (
        "/html/body/div[3]/nav[1]/ul[2]/li[7]/a[1]",
        "/html/body/div[2]/span[5]",
        "/html/body/main[1]/article[3]/p[2]",
    ):
        once = anchored_pattern(xp)
        assert anchored_pattern(once) == once


def test_relative_form_drops_the_instance_prefix():
    inst = "/html/body/main[1]/ul/li[4]"
    assert relative_to(inst + "/h3/a", inst) == "h3/a"
    assert relative_to("/html/body/other", inst) == "/html/body/other"


# --- ordering ---------------------------------------------------------------


def test_sibling_index_orders_numerically_not_lexicographically():
    xs = ["/a/div[10]", "/a/div[2]", "/a/div[1]"]
    assert [x for x in sorted(xs, key=split_steps)] == [
        "/a/div[1]",
        "/a/div[2]",
        "/a/div[10]",
    ]


def test_url_steps_lead_with_origin():
    assert url_steps("https://h.test/a/b?q=1") == ("https://h.test", "a", "b", "?q=1")


# --- the trie ---------------------------------------------------------------


def _tag(xpath, cat="text", sub="visible", value="v", attr="", subpos=""):
    return ContentTag(xpath=xpath, category=cat, subcategory=sub, value=value,
                      source_attr=attr, sub=subpos)


def test_trie_ancestry_is_a_prefix_test():
    """claim: THEORY Prop. 11.2 / Cor. 11.3."""
    url = "https://x.test/p"
    parent = address_of(_tag("/html/body/div[2]"), url)
    child = address_of(_tag("/html/body/div[2]/p[1]"), url)
    pp, cp = parent.path(), child.path()
    # the parent's *xpath* prefix, not its full path (which ends in tag+accessor)
    assert cp[: len(pp) - 2] == pp[: len(pp) - 2]


def test_trie_walk_is_document_order_across_labels():
    """An xpath index cannot order head before body. claim: PROP-11.3.1"""
    url = "https://x.test/p"
    trie = AddressTrie()
    for xp in ("/html/head/title", "/html/body/p[1]", "/html/body/p[2]"):
        trie.insert(address_of(_tag(xp), url), "t")
    assert [a.xpath for a in trie.addresses()] == [
        "/html/head/title",
        "/html/body/p[1]",
        "/html/body/p[2]",
    ]


def test_reinserting_an_address_overwrites_rather_than_duplicates():
    url = "https://x.test/p"
    trie = AddressTrie()
    a = address_of(_tag("/html/body/p", value="one"), url)
    trie.insert(a, "one")
    trie.insert(a, "two")
    assert len(trie) == 1
    assert trie.find(a).value == "two"


def test_token_multiset_keeps_multiplicity():
    """A set would equate 'buy buy buy' with 'buy' (THEORY Prop. 2.6.1)."""
    assert token_multiset("buy buy buy") != token_multiset("buy")
    assert content_hash("a b") == content_hash("b a")   # order is forgotten
    assert content_hash("a a") != content_hash("a")     # multiplicity is not


def test_content_hash_handles_non_latin_text():
    """An ASCII tokenizer maps every CJK string to the empty multiset."""
    assert content_hash("東京都") != content_hash("大阪市")
    assert content_hash("東京都") != content_hash("")


# --- delta ------------------------------------------------------------------


def _trie_of(pairs, url="https://x.test/p"):
    trie = AddressTrie()
    for xp, val in pairs:
        trie.insert(address_of(_tag(xp, value=val), url), val)
    trie.rehash()
    return trie


def test_diff_detects_add_remove_and_change():
    old = _trie_of([("/html/body/p[1]", "a"), ("/html/body/p[2]", "b")])
    new = _trie_of([("/html/body/p[1]", "a"), ("/html/body/p[2]", "CHANGED"),
                    ("/html/body/p[3]", "c")])
    d = diff(old, new)
    assert [a.xpath for a in d.added] == ["/html/body/p[3]"]
    assert [a.xpath for a in d.changed] == ["/html/body/p[2]"]
    assert d.removed == []

    back = diff(new, old)
    assert [a.xpath for a in back.removed] == ["/html/body/p[3]"]


def test_identical_tries_diff_in_one_comparison():
    """The Merkle pruning: an unchanged page of any size costs one compare."""
    t = _trie_of([(f"/html/body/p[{i}]", f"v{i}") for i in range(200)])
    d = diff(t, t)
    assert d.size == 0
    assert d.visited == 1


def test_unchanged_regions_cost_nothing_however_large():
    """The O(delta) claim, stated as what the Merkle pruning actually buys.

    The cost is *not* independent of page shape: when a node's subtree hash
    differs, every one of its children must be compared, so a change costs
    the fan-out along its own root path. What the pruning guarantees is that
    an untouched subtree costs **one comparison regardless of its size**.

    So: change one leaf, then add a thousand unrelated leaves under a single
    new sibling and change the same leaf again. The extra work must be the
    one comparison that rejects that sibling, not a thousand.
    """
    base = [(f"/html/body/main[1]/p[{i}]", f"v{i}") for i in range(5)]
    edit = [("/html/body/main[1]/p[4]", "CHANGED")]

    lean = diff(_trie_of(base), _trie_of(base[:-1] + edit))

    bulk = [(f"/html/body/aside[1]/div[{i}]/span", f"w{i}") for i in range(1000)]
    fat = diff(_trie_of(base + bulk), _trie_of(base[:-1] + edit + bulk))

    assert lean.size == fat.size == 1
    assert fat.visited - lean.visited == 1, (
        f"1000 untouched leaves under one sibling cost "
        f"{fat.visited - lean.visited} extra visits, expected 1"
    )


def test_diff_visits_a_small_fraction_of_a_real_page():
    """The same claim on real shape rather than synthetic shape."""
    pages = _corpus_pages()
    if not pages:
        pytest.skip("frozen corpus absent")
    p = pages[0]
    html = (CORPUS / f"{p['slug']}.html").read_text(encoding="utf-8", errors="replace")
    tags = run_pipeline(html, p["url"], render=False).tagged.all_tags

    old = AddressTrie.from_tags(tags, p["url"])
    new = AddressTrie.from_tags(tags, p["url"])
    leaf = list(new.leaves())[len(new) // 2]
    leaf.value = "CHANGED"
    leaf.content_hash = content_hash("CHANGED")
    new._dirty = True

    d = diff(old, new)
    total = int(old.stats()["nodes"])
    assert d.size == 1
    assert d.visited < total // 10, (
        f"visited {d.visited} of {total} nodes for a one-leaf change"
    )


# --- corpus: uniqueness and completeness -----------------------------------

PAGES = _corpus_pages()

pytestmark_corpus = pytest.mark.skipif(
    not PAGES, reason="frozen corpus absent; run scripts/fetch_corpus.py"
)


@pytest.fixture(scope="module")
def corpus_addressing():
    """Address every detection on every page. Reused by the tests below."""
    out = []
    for p in PAGES:
        html = (CORPUS / f"{p['slug']}.html").read_text(
            encoding="utf-8", errors="replace")
        result = run_pipeline(html, p["url"], render=False)
        tags = result.tagged.all_tags
        addrs = addresses_of(tags, p["url"])
        out.append({
            "page": p["slug"],
            "url": p["url"],
            "detections": len(tags),
            "addresses": len(addrs),
            "collisions": collisions(tags, p["url"]),
            "tags": tags,
            "tagged": result.tagged,
            "dom": result.dom,
        })
    return out


@pytestmark_corpus
def test_no_address_carries_two_values(corpus_addressing):
    """UNIQUENESS, measured. claim: PROP-10.2.1, COR-10.2.3

    A failure names the page and the address.

    THEORY Prop. 10.2 claims the four-component detection is already keyed by
    node and attribute. It is not: srcset holds a list, a stylesheet holds
    many urls, an ld+json script holds a whole document. The intrinsic
    sub-address restores the key, and this is the check that it did.
    """
    bad = [(m["page"], str(a), vs[:2])
           for m in corpus_addressing for a, vs in m["collisions"]]
    assert not bad, f"{len(bad)} colliding address(es); first: {bad[:2]}"


@pytestmark_corpus
def test_every_detection_is_addressable(corpus_addressing):
    """COMPLETENESS, direction one: nothing detected is dropped."""
    for m in corpus_addressing:
        addressed = {address_of(t, m["url"]).key() for t in m["tags"]}
        assert len(addressed) == m["addresses"], (
            f"{m['page']}: {m['detections']} detections produced "
            f"{len(addressed)} keys but {m['addresses']} addresses"
        )


@pytestmark_corpus
def test_every_address_resolves_to_a_detection(corpus_addressing):
    """COMPLETENESS, direction two: nothing is invented.

    Together with the previous test this makes the address map a bijection
    onto the deduplicated detection set — which is the precondition for
    deduplicating without touching the DOM.
    """
    for m in corpus_addressing:
        detected = {address_of(t, m["url"]).key() for t in m["tags"]}
        produced = {a.key() for a in addresses_of(m["tags"], m["url"])}
        assert produced == detected, (
            f"{m['page']}: {len(produced - detected)} invented, "
            f"{len(detected - produced)} lost"
        )


@pytestmark_corpus
def test_trie_holds_every_address_exactly_once(corpus_addressing):
    for m in corpus_addressing:
        trie = AddressTrie.from_tags(m["tags"], m["url"])
        assert len(trie) == m["addresses"], f"{m['page']}: leaf count differs"
        walked = trie.addresses()
        assert len(walked) == len(set(a.key() for a in walked))
        assert {a.key() for a in walked} == {a.key() for a in
                                             addresses_of(m["tags"], m["url"])}


@pytestmark_corpus
def test_trie_walk_is_a_preorder_traversal(corpus_addressing):
    """Descendants of a node are contiguous in the walk, and follow it.

    Not the same as "sorted by path": the walk is document order, which is
    deliberately not lexicographic — head precedes body. What a pre-order
    traversal does guarantee is that a subtree is never interleaved with
    anything outside it, which is what makes a walk resumable from a prefix
    and what lets a scroll-window map to a contiguous slice.
    """
    for m in corpus_addressing:
        trie = AddressTrie.from_tags(m["tags"], m["url"])
        # For every prefix, the walk positions carrying it must form one
        # unbroken range — that is exactly what "not interleaved" means.
        span: dict = {}
        for i, addr in enumerate(trie.addresses()):
            path = addr.path()
            for j in range(1, len(path) + 1):
                pre = path[:j]
                lo, hi, n = span.get(pre, (i, i, 0))
                span[pre] = (min(lo, i), max(hi, i), n + 1)
        for pre, (lo, hi, n) in span.items():
            assert hi - lo + 1 == n, (
                f"{m['page']}: subtree {pre[-3:]} occupies a broken range "
                f"[{lo},{hi}] holding {n} leaves — the walk interleaves subtrees"
            )


@pytestmark_corpus
def test_trie_walk_matches_dom_child_order(corpus_addressing):
    """ORDER FIDELITY, measured against the DOM's own child lists.
    claim: PROP-11.3.1, REM-11.3.2

    Ordered retrieval from the source is the reason the trie holds absolute
    xpaths, so "in document order" has to mean the document's order and not a
    convenient total order. An earlier version took sibling position from
    detection arrival — detections are sparse, so container elements inherited
    a descendant's position and 15.9% of multi-label parents came out wrong.
    Taking it from the scan's walk position fixed it; this is the check.
    """
    from vertiscope.address import url_steps
    from vertiscope.core.shadow_html_parser import get_absolute_xpath

    for m in corpus_addressing:
        trie = AddressTrie.from_tagged(m["tagged"], m["url"])

        truth = {}
        stack = [m["dom"].root]
        while stack:
            node = stack.pop()
            kids = [k for k in node.get_children(include_shadow=True)
                    if k.tag and not k.tag.startswith("#")]
            if kids:
                truth[get_absolute_xpath(node)] = [get_absolute_xpath(k) for k in kids]
            stack.extend(kids)

        url_n = len(url_steps(m["url"]))
        bad = []

        def walk(node, path):
            kids = node.ordered_children()
            if len(path) >= url_n and kids:
                want_all = truth.get("/" + "/".join(path[url_n:]))
                if want_all:
                    present = set(want_all)
                    got = ["/" + "/".join(path[url_n:] + [k.segment]) for k in kids]
                    got = [g for g in got if g in present]
                    want = [x for x in want_all if x in set(got)]
                    if want and got != want:
                        bad.append((want[:3], got[:3]))
            for k in kids:
                walk(k, path + [k.segment])

        walk(trie.root, [])
        assert not bad, f"{m['page']}: {len(bad)} parent(s) out of order; {bad[:1]}"


def test_delta_cost_tracks_the_trees_branching_not_the_page():
    """Merkle pruning skips *subtrees*, so branching is what buys locality.

    Measured over the corpus, one-leaf delta visits as a share of the trie:

        nested (> 2.2 nodes/leaf)   122 pages   median  2.82%
        flat   (< 1.5)                2 pages   median 100.00%

        27,534 leaves ->  110 nodes visited   (a 2.6 MB Wikipedia table)
           505 leaves ->  513                 (a text/plain RFC)

    The flat pages are `text/plain` documents, where every paragraph hangs off
    one element. They are also static, so the cost never arises outside a
    benchmark — but the claim "the work tracks the change, not the page size"
    is only true where there is a tree, and this pins the distinction rather
    than leaving the headline unqualified.
    """
    from vertiscope.markdown import render_trie  # noqa: F401  (import parity)

    nested = ("<html><body>" + "".join(
        f"<section><article><h2>H{i}</h2><p>Body number {i} with words.</p>"
        f"</article></section>" for i in range(40)) + "</body></html>")
    flat = "\n\n".join(f"Paragraph number {i} with several words in it."
                       for i in range(40))

    def shape(html, url):
        trie = AddressTrie.from_tagged(run_pipeline(html, url).tagged, url)
        stats = trie.stats()
        return int(stats["nodes"]), int(stats["leaves"])

    nodes_n, leaves_n = shape(nested, "https://x.test/n")
    nodes_f, leaves_f = shape(flat, "https://x.test/f.txt")

    per_leaf_nested = nodes_n / max(leaves_n, 1)
    per_leaf_flat = nodes_f / max(leaves_f, 1)
    assert per_leaf_flat < 1.5, per_leaf_flat
    assert per_leaf_nested > per_leaf_flat, (per_leaf_nested, per_leaf_flat)
