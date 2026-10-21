"""What the renderer reads out of the trie, and what it no longer re-derives.

The trie is the link structure; markdown is a projection read out of it. Three
of those reads walked the whole page on *every* render, whatever had changed,
and between them they were most of what an incremental render cost once the
fit tests were gone:

* ``AddressTrie.urls()`` visited every leaf to learn one string.
* ``_annotate_xpaths`` walked every element to cache an absolute xpath that
  `insert` had already computed while building the path.
* ``TrieNode.ordered_children()`` re-sorted, with a regex in the sort key,
  every time any walk asked any node for its children.

All three are now maintained by the write rather than derived by the read.
That is a claim about equality, not about speed, and these tests are the
equality: each maintained value is checked against the walk it replaced, on
real pages and on generated ones. If they ever disagree the renderer draws a
page from stale addresses, which is the kind of wrong answer that looks
completely normal.
"""

import glob
import io
import random

import pytest

import vertiscope.markdown as md
from vertiscope.address import ContentAddress, url_steps
from vertiscope.stream import StreamingScan
from vertiscope.trie import AddressTrie

FIXTURES = sorted(glob.glob("tests/fixtures/*.html"))


def _walk_urls(trie):
    """`urls()` as it was: every leaf, first arrival wins."""
    seen = []
    for leaf in trie.leaves():
        if leaf.address and leaf.address.url not in seen:
            seen.append(leaf.address.url)
    return seen


def _trie_of(html, url):
    return StreamingScan(url).push(html, passno=0).trie


# --- urls -------------------------------------------------------------------


@pytest.mark.parametrize("path", FIXTURES)
def test_urls_match_the_leaf_walk_on_fixtures(path):
    html = io.open(path, encoding="utf-8", errors="replace").read()
    trie = _trie_of(html, "file://" + path)
    assert trie.urls() == _walk_urls(trie)


def test_urls_match_the_leaf_walk_across_many_pages():
    """The case arrival order gets wrong, and the ordering fix exists for.

    A leaf walk meets one page's leaves together, so it groups the pages under
    an origin. Arrival order interleaves them when a scan visits two sites at
    once, which would reorder the chunks `render_trie` emits.
    """
    rng = random.Random(7)
    for trial in range(150):
        trie = AddressTrie()
        urls = ["https://{}.test/{}".format(rng.choice("abcde"),
                                            rng.choice(("one", "two", "three")))
                for _ in range(rng.randint(2, 6))]
        rng.shuffle(urls)
        for url in urls:
            for i in range(1, rng.randint(2, 4)):
                trie.insert(
                    ContentAddress(url, "/html/body/p[{}]".format(i),
                                   "text", "text()[1]"),
                    "hello {}".format(i))
        assert trie.urls() == _walk_urls(trie), trial


def test_a_url_leaves_when_its_last_leaf_does():
    """A stale entry would send `render_trie` after a page node that is gone."""
    trie = AddressTrie()
    keep = ContentAddress("https://a.test/x", "/html/body/p[1]", "text",
                          "text()[1]")
    drop = ContentAddress("https://b.test/y", "/html/body/p[1]", "text",
                          "text()[1]")
    trie.insert(keep, "one")
    trie.insert(drop, "two")
    assert trie.urls() == _walk_urls(trie)

    assert trie.remove(drop)
    assert trie.urls() == ["https://a.test/x"]
    assert trie.urls() == _walk_urls(trie)
    assert trie.node_at(url_steps("https://b.test/y")) is None


def test_a_url_stays_while_any_leaf_remains():
    trie = AddressTrie()
    url = "https://a.test/x"
    first = ContentAddress(url, "/html/body/p[1]", "text", "text()[1]")
    second = ContentAddress(url, "/html/body/p[2]", "text", "text()[1]")
    trie.insert(first, "one")
    trie.insert(second, "two")
    assert trie.remove(first)
    assert trie.urls() == [url]
    assert trie.urls() == _walk_urls(trie)


# --- xpaths -----------------------------------------------------------------


def _xpath_disagreements(trie, url):
    """Element nodes where the trie's cached xpath differs from the walk's."""
    steps = md.url_steps(url)
    page = trie.node_at(steps)
    if page is None:
        return []
    before = {id(n): n._xpath_cache for n in page.walk()}
    md._annotate_xpaths(page, steps, url)     # the reference implementation
    out = []
    for node in page.walk():
        if node.is_leaf or md._is_terminal_pair(node):
            continue
        if before[id(node)] != node._xpath_cache:
            out.append((node.segment, before[id(node)], node._xpath_cache))
    return out


@pytest.mark.parametrize("path", FIXTURES)
def test_insert_assigns_the_xpath_the_walk_would_have(path):
    html = io.open(path, encoding="utf-8", errors="replace").read()
    url = "file://" + path
    assert _xpath_disagreements(_trie_of(html, url), url) == []


def _shapes(seed):
    rng = random.Random(seed)
    words = ["alpha", "beta", "gamma", "delta"]

    def txt(k):
        return " ".join(rng.choice(words) for _ in range(k))

    kind = seed % 4
    if kind == 0:
        return "<html><body><main><ul>" + "".join(
            "<li><h3>Item {}</h3><p>{}</p></li>".format(i, txt(6))
            for i in range(rng.randint(2, 30))) + "</ul></main></body></html>"
    if kind == 1:
        deep = "<p>{}</p>".format(txt(10))
        for _ in range(rng.randint(2, 14)):
            deep = "<div>{}</div>".format(deep)
        return "<html><body><main>{}</main></body></html>".format(deep)
    if kind == 2:
        return "<html><body><main><table>" + "".join(
            "<tr>" + "".join("<td>{}</td>".format(txt(3))
                             for _ in range(rng.randint(2, 5))) + "</tr>"
            for _ in range(rng.randint(2, 12))) + "</table></main></body></html>"
    return ("<html><body><header><h1>{}</h1></header><main>".format(txt(2))
            + "".join("<section><h2>{}</h2><p>{}</p></section>".format(
                txt(2), txt(rng.randint(2, 20)))
                for _ in range(rng.randint(1, 10)))
            + "</main></body></html>")


def test_insert_assigns_the_right_xpath_on_generated_shapes():
    for seed in range(60):
        url = "https://xp.test/p{}".format(seed)
        bad = _xpath_disagreements(_trie_of(_shapes(seed), url), url)
        assert bad == [], (seed, bad[:3])


def test_xpaths_survive_an_edit_and_an_insertion():
    """Nodes persist across passes; the assignment must still be right.

    An insertion at the head re-points every address below it, which is the
    case where "the xpath belongs to the node" is easiest to get wrong.
    """
    def page(n, head=False, edit=None):
        rows = "".join(
            "<li><h3>Item {}</h3><p>{}</p></li>".format(
                i, "EDITED" if i == edit else "body {}".format(i))
            for i in range(-1 if head else 0, n))
        return "<html><body><main><ul>{}</ul></main></body></html>".format(rows)

    url = "https://xp.test/live"
    scan = StreamingScan(url)
    scan.push(page(20), passno=0)
    assert _xpath_disagreements(scan.trie, url) == []
    scan.push(page(20, edit=7), passno=1)
    assert _xpath_disagreements(scan.trie, url) == []
    scan.push(page(20, head=True), passno=2)
    assert _xpath_disagreements(scan.trie, url) == []


# --- child order ------------------------------------------------------------


def _unsorted_children(node):
    """`ordered_children()` as it was, with no cache."""
    from vertiscope.trie import _seg_key

    kids = list(node.children.values())
    kids.sort(key=lambda n: (n.doc_pos < 0, n.doc_pos,
                             n.label_order < 0, n.label_order,
                             _seg_key(n.segment)))
    return kids


@pytest.mark.parametrize("path", FIXTURES)
def test_cached_child_order_matches_the_sort(path):
    html = io.open(path, encoding="utf-8", errors="replace").read()
    trie = _trie_of(html, "file://" + path)
    checked = 0
    for node in trie.root.walk():
        assert node.ordered_children() == _unsorted_children(node)
        checked += 1
    assert checked


def test_child_order_cache_refreshes_when_children_arrive():
    """The count is the whole validity check, so it has to be exercised."""
    trie = AddressTrie()
    url = "https://ord.test/x"

    def addr(i):
        return ContentAddress(url, "/html/body/p[{}]".format(i), "text",
                              "text()[1]")

    # The first sibling is stored without its index -- `p`, not `p[1]` -- so
    # these compare against the uncached sort rather than against segment
    # text, which is the property under test anyway.
    trie.insert(addr(1), "one")
    page = trie.node_at(url_steps(url))
    body = page.ordered_children()[0].ordered_children()[0]
    assert len(body.ordered_children()) == 1
    assert body.ordered_children() == _unsorted_children(body)

    trie.insert(addr(2), "two")
    assert len(body.ordered_children()) == 2
    assert body.ordered_children() == _unsorted_children(body)

    assert trie.remove(addr(1))
    assert len(body.ordered_children()) == 1
    assert body.ordered_children() == _unsorted_children(body)


def test_ordered_children_does_not_hand_out_its_cache():
    """`walk` holds the result across yields; a shared list would let a caller
    corrupt the trie's own view of its order into a traversal that silently
    skips nodes."""
    trie = AddressTrie()
    url = "https://ord.test/y"
    for i in (1, 2, 3):
        trie.insert(ContentAddress(url, "/html/body/p[{}]".format(i), "text",
                                   "text()[1]"), "v")
    page = trie.node_at(url_steps(url))
    body = page.ordered_children()[0].ordered_children()[0]

    expected = _unsorted_children(body)
    first = body.ordered_children()
    first.pop()
    first.reverse()
    assert body.ordered_children() == expected
    assert len(body.ordered_children()) == 3
