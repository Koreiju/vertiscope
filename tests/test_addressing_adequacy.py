"""Do the addressing checks have teeth?

`test_address_trie.py` reports zero collisions, zero mis-ordered parents and
zero unaccounted units. A zero is ambiguous: it means either the property
holds or the check cannot see a violation. These tests break each property on
purpose and require the corresponding check to say so.

Mutation testing scoped to the addressing claims — it measures the tests, not
the code.

One test here is an accusation rather than a check. `test_..._was_vacuous`
records that the original completeness assertion compared a set against
itself, and pins the stronger property that replaced it.
"""

import json
import pathlib

import pytest

from vertiscope.address import ContentAddress, address_of, addresses_of, collisions
from vertiscope.core.content_tagger import ContentTag
from vertiscope.markdown import RenderReport, _SUPPRESSED_TAGS, render_trie
from vertiscope.pipeline import run_pipeline
from vertiscope.trie import AddressTrie, content_hash, diff

CORPUS = pathlib.Path(__file__).parent / "corpus"
MANIFEST = CORPUS / "manifest.json"
URL = "https://x.test/p"


def _page(slug_prefix: str = ""):
    if not MANIFEST.exists():
        pytest.skip("frozen corpus absent")
    pages = [p for p in json.loads(MANIFEST.read_text())["pages"] if p.get("ok")]
    if slug_prefix:
        pages = [p for p in pages if p["slug"].startswith(slug_prefix)] or pages
    for p in pages:
        f = CORPUS / f"{p['slug']}.html"
        if f.exists():
            return p, f.read_text(encoding="utf-8", errors="replace")
    pytest.skip("no corpus page available")


@pytest.fixture(scope="module")
def scanned():
    p, html = _page("books-toscrape")
    return p["url"], run_pipeline(html, p["url"], render=False)


# --- A1: does the collision check fire? ------------------------------------


def test_collision_check_fires_when_the_sub_address_is_removed():
    """Strip the intrinsic sub-address and uniqueness must break.
    claim: DEF-10.1.1, REM-10.2.2

    This is the repair from ERRATA A19 run backwards. If removing it left the
    collision count at zero the audit's zero would mean nothing.

    Scanned across the corpus rather than on one page, because most pages do
    not exercise a multi-valued accessor at all — the first page tried here
    (books-toscrape) has none, which is itself worth knowing: a single-page
    mutation test would have reported "cannot fire" and been wrong.
    """
    if not MANIFEST.exists():
        pytest.skip("frozen corpus absent")
    pages = [p for p in json.loads(MANIFEST.read_text())["pages"] if p.get("ok")]

    fired = []
    for p in pages:
        f = CORPUS / f"{p['slug']}.html"
        if not f.exists():
            continue
        tags = run_pipeline(
            f.read_text(encoding="utf-8", errors="replace"), p["url"], render=False
        ).tagged.all_tags
        assert collisions(tags, p["url"]) == [], f"{p['slug']}: address is not a key"
        stripped = [
            ContentTag(xpath=t.xpath, category=t.category, subcategory=t.subcategory,
                       value=t.value, source_attr=t.source_attr, sub="")
            for t in tags
        ]
        n = len(collisions(stripped, p["url"]))
        if n:
            fired.append((p["slug"], n))
        if len(fired) >= 3:
            break

    assert fired, (
        "removing the sub-address produced no collisions anywhere in the "
        "corpus — the check cannot see the failure it exists to catch"
    )


def test_collision_check_fires_on_a_planted_duplicate():
    """A pair sharing an address but not a value must be reported. claim: PROP-10.2.1"""
    tags = [
        ContentTag("/html/body/img", "urls", "external", "a.jpg", "srcset", "[0]"),
        ContentTag("/html/body/img", "urls", "external", "b.jpg", "srcset", "[0]"),
    ]
    found = collisions(tags, URL)
    assert len(found) == 1
    assert sorted(found[0][1]) == ["a.jpg", "b.jpg"]


def test_collision_check_ignores_an_exact_duplicate():
    """Two identical detections are one fact reported twice, not a collision."""
    tag = ContentTag("/html/body/img", "urls", "external", "a.jpg", "src", "")
    assert collisions([tag, tag], URL) == []


# --- A2: the completeness check that wasn't --------------------------------


def test_the_original_completeness_check_was_vacuous(scanned):
    """The first version of this claim compared a set with itself.

    It read::

        detected = {address_of(t, url).key() for t in tags}
        produced = {a.key() for a in addresses_of(tags, url)}
        assert produced == detected

    but `addresses_of` *is* that comprehension plus a sort, so the equality
    held by construction and would have survived any bug in the address map —
    including one that mapped every detection to the same address. This
    demonstrates that: a deliberately degenerate address function passes the
    old form.
    """
    url, result = scanned
    tags = result.tagged.all_tags

    def degenerate(_tag, _url):
        return ContentAddress(url=_url, xpath="/", tag="text.visible", accessor="x")

    detected = {degenerate(t, url).key() for t in tags}
    produced = {degenerate(t, url).key() for t in tags}
    assert produced == detected          # the old assertion, still passing
    assert len(detected) == 1            # while collapsing the entire page


def test_completeness_is_a_round_trip_through_the_trie(scanned):
    """The property worth asserting: the trie preserves the detection set.

    Not "the address function equals itself" but "what went into the trie
    comes back out" — address *and* value, without the DOM. That is what
    deduplicating and rendering off the trie alone actually depends on.
    """
    url, result = scanned
    tags = result.tagged.all_tags
    trie = AddressTrie.from_tagged(result.tagged, url)

    # exact-duplicate detections collapse losslessly; keep the last value seen,
    # which is what insert() does
    expected = {}
    for t in tags:
        expected[address_of(t, url).key()] = t.value

    recovered = {
        leaf.address.key(): leaf.value
        for leaf in trie.leaves()
        if leaf.address is not None
    }
    assert recovered == expected


def test_round_trip_check_fires_when_the_trie_drops_a_leaf(scanned):
    """And the round trip must notice a loss — otherwise it is vacuous too."""
    url, result = scanned
    trie = AddressTrie.from_tagged(result.tagged, url)
    expected = {address_of(t, url).key() for t in result.tagged.all_tags}

    victim = next(iter(trie.root.leaves()))
    victim.address = None

    recovered = {
        leaf.address.key() for leaf in trie.leaves() if leaf.address is not None
    }
    assert recovered != expected


# --- A3: does the order check fire? ----------------------------------------


def test_order_check_fires_when_walk_positions_are_scrambled(scanned):
    """Reverse the walk positions; the trie order must stop matching the DOM.

    The audit reports 0 of 13,786 parents mis-ordered. That number is only
    meaningful if a wrong ordering would have been counted, and the previous
    ordering scheme — which was wrong on 15.9% of parents — is exactly the
    kind of thing this has to catch.
    """
    from vertiscope.address import url_steps
    from vertiscope.core.shadow_html_parser import get_absolute_xpath

    url, result = scanned
    truth = {}
    stack = [result.dom.root]
    while stack:
        node = stack.pop()
        kids = [k for k in node.get_children(include_shadow=True)
                if k.tag and not k.tag.startswith("#")]
        if kids:
            truth[get_absolute_xpath(node)] = [get_absolute_xpath(k) for k in kids]
        stack.extend(kids)

    url_n = len(url_steps(url))

    def misordered(trie):
        bad = [0]

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
                        bad[0] += 1
            for k in kids:
                walk(k, path + [k.segment])

        walk(trie.root, [])
        return bad[0]

    good = AddressTrie.from_tagged(result.tagged, url)
    assert misordered(good) == 0

    top = max(result.tagged.doc_pos.values())
    flipped = {k: top - v for k, v in result.tagged.doc_pos.items()}
    bad = AddressTrie.from_tags(result.tagged.all_tags, url, flipped)
    assert misordered(bad) > 0, (
        "reversing every walk position changed no parent's order — the check "
        "is not reading the order it claims to check"
    )


# --- the render accounting -------------------------------------------------


def test_render_accounting_fires_when_a_unit_is_dropped(scanned):
    """`unaccounted == 0` must be capable of being nonzero."""
    url, result = scanned
    trie = AddressTrie.from_tagged(result.tagged, url)

    report = RenderReport()
    chunks = render_trie(trie, context_window=1200, report=report)
    assert report.unaccounted == 0

    # Drop a rendered line without telling the report: the identity must break.
    victim = next(c for c in chunks if c.lines)
    from vertiscope.markdown import _fill_report
    victim.lines.pop()
    broken = RenderReport()
    _fill_report(trie, chunks, broken)
    assert broken.unaccounted != 0 or broken.deduped > report.deduped, (
        "a dropped line left the accounting balanced — it cannot detect loss"
    )


def test_suppressed_units_are_a_deliberate_choice_not_a_leak(scanned):
    """Everything suppressed must be in the declared set, nothing else.

    Suppression is the one bucket where "accounted for" could hide a bug: a
    renderer that silently returned None for an unhandled kind would land here
    and balance the books. Requiring the tags to match the declared set means
    a new suppression has to be declared.
    """
    url, result = scanned
    trie = AddressTrie.from_tagged(result.tagged, url)
    report = RenderReport()
    chunks = render_trie(trie, context_window=1200, report=report)

    # `covered`, not `anchors`.
    #
    # This asks whether an address was ACCOUNTED FOR. `anchors` is one key per
    # line by contract -- positional, so the jsonl round-trip and the REPL can
    # zip it against `lines` -- and a line that put a sentence's inline markup
    # back together accounts for every address folded into it. `covered` is
    # the set that says so, and its own docstring records the same failure:
    # counting only the first "made those look lost", and the answer then
    # moved with the context window (589 of them between 1200 and 200).
    #
    # Measured with the prose fold in place: 3,139 url/media units sit outside
    # `anchors` and 2,575 of them are in `covered`. Asking with `anchors` made
    # this test depend on which line a link's markup happened to land on,
    # which is the renderer's business and not what this test is about.
    #
    # It keeps its teeth: silently dropping `media` -- 41 units in the
    # fixture -- still fails it.
    emitted = {k for c in chunks for k in c.covered}
    kept_by_node: dict = {}
    for chunk in chunks:
        for line in chunk.lines:
            kept_by_node.setdefault(line.address.xpath, set()).add(
                (line.address.category, line.text)
            )

    unexplained = []
    for leaf in trie.leaves():
        addr = leaf.address
        if addr is None or addr.key() in emitted or not (leaf.value or "").strip():
            continue
        if addr.tag in _SUPPRESSED_TAGS:
            continue
        if addr.category not in ("urls", "media", "json_data"):
            continue        # text loss is subsumption, checked separately
        # A dropped url or media unit must be an exact duplicate of one kept
        # at the *same element*. Anything else is a genuine loss of a link.
        value = " ".join(leaf.value.split())
        kept = kept_by_node.get(addr.xpath, set())
        if not any(value in text for _cat, text in kept):
            unexplained.append((str(addr)[:90], value[:60]))

    assert not unexplained, (
        f"{len(unexplained)} url/media unit(s) vanished with no duplicate kept "
        f"at the same element; first: {unexplained[:2]}"
    )


# --- the delta ------------------------------------------------------------


def test_delta_reports_a_change_it_should_not_miss(scanned):
    """A Merkle diff that returned "no change" for everything would also
    show `visited == 1`, which is the number the O(delta) claim rests on."""
    url, result = scanned
    a = AddressTrie.from_tagged(result.tagged, url)
    b = AddressTrie.from_tagged(result.tagged, url)
    assert diff(a, b).size == 0

    leaf = list(b.leaves())[0]
    leaf.value = "MUTATED"
    leaf.content_hash = content_hash("MUTATED")
    b._dirty = True
    d = diff(a, b)
    assert d.size == 1 and d.visited > 1, (
        "a changed leaf was pruned away — the diff prunes on something other "
        "than content"
    )
