"""The render memo must be invisible in the output and visible in the cost.

Two obligations, and they pull against each other. A cache that is wrong is
worse than no cache, because the page it draws is a page that does not exist;
a cache that never hits is a cost with no benefit and a false claim of
O(delta). Every test here is one or the other: byte-equality against the
uncached render, or a non-vacuity check that the hits are real.

The link back to the trie is ``TrieNode.exact_hash``. These tests exist to
hold the line that the projection reuses a subtree exactly when the trie says
that subtree is unchanged -- not when it says the *content* is unchanged,
which is a weaker claim that ``subtree_hash`` makes and that a renderer
cannot use.
"""

import random

import pytest

from vertiscope.markdown import RenderMemo, render_trie
from vertiscope.stream import StreamingScan


def _dump(chunks):
    """Everything about a render that anything downstream can observe."""
    return "\n@@@\n".join(
        "{}|{}|{}|{}\n{}".format(c.cid, c.url, c.xpath, c.part, c.markdown)
        for c in chunks
    )


def _page(items, title="Catalogue"):
    rows = "".join(
        '<li class="row"><h3>{}</h3><p>{}</p>'
        '<a href="https://example.test/{}">open {}</a></li>'.format(
            name, body, i, i)
        for i, (name, body) in enumerate(items)
    )
    return (
        "<html><body><header><h1>{}</h1></header>"
        "<main><ul>{}</ul></main>"
        "<footer><p>end of list</p></footer></body></html>"
    ).format(title, rows)


def _items(n, seed=0):
    rng = random.Random(seed)
    words = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta"]
    return [
        ("Item {}".format(i),
         " ".join(rng.choice(words) for _ in range(rng.randint(3, 9))))
        for i in range(n)
    ]


def _run(versions, window=1200):
    """Push each version; return the cached and uncached dump for each pass."""
    scan = StreamingScan("https://memo.test/page", context_window=window)
    memo = RenderMemo()
    out = []
    for passno, html in enumerate(versions):
        update = scan.push(html, passno=passno)
        cached = render_trie(update.trie, context_window=window, memo=memo)
        fresh = render_trie(update.trie, context_window=window)
        out.append((_dump(cached), _dump(fresh)))
    return out, memo


# --- equivalence ------------------------------------------------------------


def test_unchanged_page_renders_identically():
    html = _page(_items(30))
    passes, _memo = _run([html] * 3)
    for cached, fresh in passes:
        assert cached == fresh


def test_edited_text_renders_identically():
    items = _items(30)
    versions = [_page(items)]
    for k in (0, 7, 29):
        items = list(items)
        items[k] = (items[k][0], items[k][1] + " changed")
        versions.append(_page(items))
    passes, _memo = _run(versions)
    for cached, fresh in passes:
        assert cached == fresh


def test_word_order_edit_reaches_the_render():
    """The case ``subtree_hash`` cannot see.

    ``content_hash`` is a hash of the normalized token multiset, so
    "gamma beta" and "beta gamma" are the same content to the trie --
    deliberately, because that is what lets a moved paragraph keep its
    identity across a reformat. A memo keyed on it would serve the old word
    order forever. ``exact_hash`` is what makes this test pass, and reverting
    the key to ``subtree_hash`` is what makes it fail.
    """
    items = _items(20)
    before = _page(items)
    items[5] = (items[5][0], " ".join(reversed(items[5][1].split())))
    after = _page(items)
    assert before != after

    scan = StreamingScan("https://memo.test/page")
    memo = RenderMemo()
    a = _dump(render_trie(scan.push(before, passno=0).trie,
                          context_window=1200, memo=memo))
    b = _dump(render_trie(scan.push(after, passno=1).trie,
                          context_window=1200, memo=memo))
    fresh = _dump(render_trie(scan.trie, context_window=1200))
    assert b == fresh
    assert a != b, "a word-order edit must reach the render"


def test_insert_delete_reorder_render_identically():
    items = _items(40, seed=3)
    versions = [_page(items)]

    grown = list(items)
    grown.insert(0, ("Item head", "inserted at the head"))
    versions.append(_page(grown))

    shrunk = [it for i, it in enumerate(grown) if i != 12]
    versions.append(_page(shrunk))

    swapped = list(shrunk)
    swapped[3], swapped[4] = swapped[4], swapped[3]
    versions.append(_page(swapped))

    versions.append(_page(swapped, title="Renamed"))

    passes, _memo = _run(versions)
    for i, (cached, fresh) in enumerate(passes):
        assert cached == fresh, "pass {}".format(i)


@pytest.mark.parametrize("window", [200, 600, 1200, 4000])
def test_equivalence_holds_at_every_window(window):
    """The memo is keyed on the window because chunking depends on it."""
    items = _items(25, seed=9)
    versions = [_page(items)]
    items[4] = (items[4][0], items[4][1] * 6)     # push one row over a window
    versions.append(_page(items))
    passes, _memo = _run(versions, window=window)
    for cached, fresh in passes:
        assert cached == fresh


def test_random_mutations_render_identically():
    rng = random.Random(1234)
    items = _items(35, seed=11)
    versions = [_page(items)]
    for _ in range(12):
        items = list(items)
        op = rng.choice(("edit", "insert", "delete", "swap"))
        if op == "edit" and items:
            k = rng.randrange(len(items))
            items[k] = (items[k][0], items[k][1] + " " + rng.choice("xyz"))
        elif op == "insert":
            items.insert(rng.randrange(len(items) + 1),
                         ("New {}".format(rng.randrange(999)), "fresh body"))
        elif op == "delete" and len(items) > 2:
            del items[rng.randrange(len(items))]
        elif op == "swap" and len(items) > 2:
            i = rng.randrange(len(items) - 1)
            items[i], items[i + 1] = items[i + 1], items[i]
        versions.append(_page(items))
    passes, _memo = _run(versions)
    for i, (cached, fresh) in enumerate(passes):
        assert cached == fresh, "pass {}".format(i)


# --- non-vacuity ------------------------------------------------------------


def test_memo_actually_hits():
    """A cache that never hits would pass every equivalence test above."""
    html = _page(_items(60))
    _passes, memo = _run([html, html, html])
    assert memo.hits > 0
    assert memo.reused_lines > 0


def test_reuse_covers_most_of_an_edited_page():
    """One edited row must not cost a whole-page redraw.

    Measured as lines served from the memo against lines emitted. This is the
    property the whole change exists for, so it is asserted rather than
    reported.
    """
    items = _items(60, seed=21)
    before = _page(items)
    items[30] = (items[30][0], items[30][1] + " edited")
    after = _page(items)

    scan = StreamingScan("https://memo.test/page")
    memo = RenderMemo()
    render_trie(scan.push(before, passno=0).trie, context_window=1200,
                memo=memo)
    baseline = memo.reused_lines
    chunks = render_trie(scan.push(after, passno=1).trie,
                         context_window=1200, memo=memo)
    reused = memo.reused_lines - baseline
    emitted = sum(len(c.lines) for c in chunks)
    assert emitted > 100
    assert reused >= 0.5 * emitted, "reused {} of {}".format(reused, emitted)


def test_memo_does_not_grow_without_bound():
    """Two generations, rotated per render: a page cache does not accrete."""
    scan = StreamingScan("https://memo.test/page")
    memo = RenderMemo()
    sizes = []
    for passno in range(8):
        items = _items(30, seed=passno)
        render_trie(scan.push(_page(items), passno=passno).trie,
                    context_window=1200, memo=memo)
        sizes.append(memo.resident)
    assert max(sizes[3:]) <= 3 * min(sizes[3:]), sizes


def test_unkeyable_node_degrades_to_full_render():
    """A trie that never ran rehash has no hashes, and must still draw."""
    scan = StreamingScan("https://memo.test/page")
    update = scan.push(_page(_items(10)), passno=0)
    for node in update.trie.root.walk():
        node.exact_hash = 0
    memo = RenderMemo()
    cached = _dump(render_trie(update.trie, context_window=1200, memo=memo))
    fresh = _dump(render_trie(update.trie, context_window=1200))
    assert cached == fresh
    assert memo.hits == 0


# --- the id stability the memo was built on top of --------------------------


@pytest.mark.parametrize("window", [200, 400, 1200])
def test_part_is_a_property_of_the_group_not_of_position(window):
    """The precondition the memo needs: nothing in a chunk depends on where
    it was emitted.

    The descent used to number chunks by their global position, which gave an
    ordinal to chunks sharing their root with nobody -- so a chunk id was a
    function of everything emitted before it. A cached subtree cannot be
    spliced in at a new position while that is true.

    Asserted directly rather than through id churn: an insertion near the top
    of a page *should* rename the chunks below it under the old scheme, but
    over the fixture pages at these three windows it did not, so that test
    would not discriminate. This one does.
    """
    items = _items(50, seed=7)
    chunks = render_trie(
        StreamingScan("https://memo.test/page").push(_page(items),
                                                     passno=0).trie,
        context_window=window,
    )
    counts = {}
    for chunk in chunks:
        counts[(chunk.url, chunk.xpath)] = \
            counts.get((chunk.url, chunk.xpath), 0) + 1

    assert chunks
    for chunk in chunks:
        group = counts[(chunk.url, chunk.xpath)]
        assert 0 <= chunk.part < group, (
            "part {} out of range for a group of {}".format(chunk.part, group))
        if group == 1:
            assert chunk.part == 0, "a chunk alone at its root carries no ordinal"

    for key, group in counts.items():
        parts = sorted(c.part for c in chunks
                       if (c.url, c.xpath) == key)
        assert parts == list(range(group)), key


# --- the source-level clause behind all of the above ------------------------


def test_c3_holds_on_the_projections():
    from vertiscope import invariants as inv

    assert inv.c3_projections_key_on_exact_hash() == []


def test_c3_catches_a_projection_keyed_on_the_wrong_hash():
    """The planted defect: one word, and either name reads as plausible."""
    from vertiscope import invariants as inv

    planted = {"markdown.py": "    key = (xpath, node.subtree_hash)\n"
                              "    other = node.exact_hash\n"}
    violations = inv.c3_projections_key_on_exact_hash(planted)
    assert violations
    assert "subtree_hash" in violations[0]


def test_c3_is_not_vacuous_when_nothing_keys_on_anything():
    from vertiscope import invariants as inv

    violations = inv.c3_projections_key_on_exact_hash({"markdown.py": "pass\n"})
    assert violations
    assert "exact_hash" in violations[0]


def test_c3_allows_prose_about_the_distinction():
    """The two hashes have to be *explained* in the file that chooses between
    them, so a comment naming the wrong one is not a violation."""
    from vertiscope import invariants as inv

    allowed = {"markdown.py":
               "# not subtree_hash: that one is blind to word order\n"
               "    key = node.exact_hash\n"}
    assert inv.c3_projections_key_on_exact_hash(allowed) == []
