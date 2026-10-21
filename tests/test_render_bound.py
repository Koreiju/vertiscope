"""Can a subtree's size be decided without rendering it?

This is the question standing between the projection and O(delta). After the
render memo, a redraw is nearly free but an edit still costs about half a
page, and the reason is precise: the ancestors of an edited leaf reach the
page root, and the descent asks each ancestor whether its subtree fits the
context window -- a question answered by rendering the subtree. At the root
that is the page.

If the answer could come from the children the descent has already rendered
(mostly memo hits), the residual would go. So: is

    parent_chars  <=  own_chars + sum(child_chars) + n_groups - 1

an upper bound on what the parent renders to?

The arithmetic says it should be *exactly* tight, for three reasons that are
properties of the renderer rather than accidents:

* Depth is absolute. `_collect` measures from the chunk root, and
  `_render_node` offsets by ``-(node.depth - url_depth)`` to cancel it, so a
  line sits at the same indentation whether it was reached from the parent or
  from the child. Without that cancellation a line would cost two more
  characters per level and the bound would fail everywhere.
* `chars` is ``len("\\n".join(lines))``: joining k groups holding L lines in
  total costs ``sum(line lengths) + L - 1``, while the groups rendered apart
  cost ``sum(line lengths) + L - k``. The difference is ``k - 1``, which is
  the slack term.
* Dedup and suppression only ever *remove*.

And it holds -- except in one place, which these tests exist to hold on to.

**Heading labels inherit downward.** `_collect` carries a heading label into
child elements, so a heading whose words live in child elements ("<h3><div>
Technology</div><span>The backlash</span></h3>", which is how the Guardian
writes headlines) draws those words *as a heading* from the parent and as
plain text from the child. The marker is characters the children never paid
for, and the bound fails by exactly that much.

An upper bound proves "this fits". What would let the descent skip the root's
render is the other direction -- "this overflows" -- and that needs a *lower*
bound. There is one, and it is structural rather than lucky:

**Every rendering decision is scoped to a single element.** `_dedupe` groups
units by ``addr.xpath`` and only ever compares within a group; the control
that consumes its own label is keyed the same way; suppression reads the
unit's own tag. Two units in different subtrees are never compared, so nothing
in one child can delete anything in another, and a child's surviving lines are
exactly its lines inside the parent's render. Hence ``child_chars <=
parent_chars`` for every child, and the largest child is a floor.

Measured across 101 interior nodes -- the fixture pages plus cases built to
break it (sibling restatement, a long child beside a short one, a button label
repeated by a sibling span) -- with no violation.

Put together, the parent's size is bracketed by its children, from both sides,
with two correction terms: heading inheritance adds, and `_join_inline`
merging a run across a child boundary removes a little. That is what the next
attempt at the residual should build on, and it is why these tests exist.
"""

import pytest

import vertiscope.markdown as M
from vertiscope.stream import StreamingScan

WINDOW = 1200


def _interior_nodes(html, url="https://bound.test/page"):
    """Yield (xpath, parent_chars, bound) for every node with element kids."""
    scan = StreamingScan(url)
    trie = scan.push(html, passno=0).trie
    steps = M.url_steps(url)
    page = trie.node_at(steps)
    assert page is not None
    M._annotate_xpaths(page, steps, url)
    url_depth = len(steps)

    out = []

    def walk(node):
        kids = [c for c in node.ordered_children()
                if not c.is_leaf and not M._is_terminal_pair(c)]
        if not kids:
            return
        _parent, parent_chars = M._render_sized(node, url, url_depth)
        own = M._own_units_chunk(node, url, url_depth)
        total = own[1] if own else 0
        groups = 1 if own else 0
        for child in kids:
            _chunk, child_chars = M._render_sized(child, url, url_depth)
            total += child_chars
            groups += 1
        out.append((getattr(node, "_xpath_cache", "?"), parent_chars,
                    total + max(groups - 1, 0)))
        for child in kids:
            walk(child)

    walk(page)
    return out


def _rows(n):
    return "".join(
        "<li><h4>Item {}</h4><p>body text for row {}</p>"
        '<a href="https://example.test/{}">open</a></li>'.format(i, i, i)
        for i in range(n)
    )


SOUND_CASES = {
    "flat list":
        "<html><body><main><ul>" + _rows(12) + "</ul></main></body></html>",
    "anchors with text children":
        "<html><body><main><div>"
        "<a href='https://e.test/x'>the link words</a>"
        "<a href='https://e.test/y'>more link words</a></div></main></body></html>",
    "controls consuming their labels":
        "<html><body><main><div><button>Add to basket</button>"
        "<button>Remove</button></div></main></body></html>",
    "text restated down a containment chain":
        "<html><body><main><div><div><div><p>Acme Corporation</p></div>"
        "<span>Acme Corporation</span></div></main></body></html>",
    "blockquote around code":
        "<html><body><main><blockquote><p>quoted words</p>"
        "<pre><code>x = 1</code></pre></blockquote></main></body></html>",
    "table":
        "<html><body><main><table><tr><th>a</th><th>b</th></tr>"
        "<tr><td>1</td><td>2</td></tr></table></main></body></html>",
    "deeply wrapped single child":
        "<html><body><main><div><div><div><div><p>one paragraph</p>"
        "</div></div></div></div></main></body></html>",
}


@pytest.mark.parametrize("name", sorted(SOUND_CASES))
def test_children_bound_the_parent_off_the_heading_path(name):
    """The bound holds wherever no heading label inherits downward."""
    rows = _interior_nodes(SOUND_CASES[name])
    assert rows, name
    for xpath, parent_chars, bound in rows:
        assert parent_chars <= bound, (
            "{}: {} renders to {} against a bound of {}".format(
                name, xpath, parent_chars, bound))


HEADING_CASES = {
    "heading wrapping elements":
        "<html><body><main><h3><div>Technology</div>"
        "<span>The backlash begins</span></h3>"
        "<p>ordinary body text</p></main></body></html>",
    "heading nesting deep":
        "<html><body><main><h2><section><div>"
        "<span>deep heading words here</span>"
        "</div></section></h2></main></body></html>",
}


@pytest.mark.parametrize("name", sorted(HEADING_CASES))
def test_heading_inheritance_breaks_the_bound(name):
    """The counterexample, asserted rather than assumed.

    This is a non-vacuity test for the claim above: if a later change to
    `_collect` stopped carrying heading labels into child elements, the bound
    would become universal and this test would fail -- which is the correct
    outcome, because the reason for the exception would be gone. It must not
    be deleted quietly; the headings it protects were 124 of the Guardian's
    181, and they were arriving as ordinary text before the label carried
    down.
    """
    rows = _interior_nodes(HEADING_CASES[name])
    violations = [r for r in rows if r[1] > r[2]]
    assert violations, (
        "expected the heading node to exceed the bound, got {}".format(rows))
    for xpath, parent_chars, bound in violations:
        assert parent_chars > bound
        # The excess is a marker on a line, not a whole extra rendering.
        assert parent_chars - bound < 40, (xpath, parent_chars, bound)


def test_the_bound_is_tight_where_it_holds():
    """Not merely an upper bound: on a plain list it is reached exactly.

    A bound with slack in it would be a weaker claim and would leave room for
    a page that fits to be split anyway. This says the arithmetic above is the
    whole story where headings do not interfere.
    """
    rows = _interior_nodes(
        "<html><body><main><ul>" + _rows(8) + "</ul></main></body></html>")
    assert rows
    exact = [r for r in rows if r[1] == r[2]]
    assert exact, "the bound is never reached, so it is not the right bound"


LOWER_BOUND_CASES = dict(SOUND_CASES, **HEADING_CASES)
LOWER_BOUND_CASES.update({
    "sibling restatement":
        "<html><body><main><div>"
        "<p>Acme Corporation annual report</p>"
        "<span>Acme Corporation annual report</span>"
        "</div></main></body></html>",
    "restatement across a containment boundary":
        "<html><body><main><div><div><p>Acme Corporation</p></div>"
        "<span>Acme Corporation</span></div></main></body></html>",
    "one long child beside a short one":
        "<html><body><main><div><section><p>" + ("word " * 200) +
        "</p></section><span>x</span></div></main></body></html>",
    "button label repeated by a sibling":
        "<html><body><main><div><button>Add to basket</button>"
        "<span>Add to basket</span></div></main></body></html>",
})


@pytest.mark.parametrize("name", sorted(LOWER_BOUND_CASES))
def test_the_largest_child_is_a_floor_on_the_parent(name):
    """The direction that would let the descent skip an ancestor's render.

    Structural, not lucky: `_dedupe` groups by ``addr.xpath`` and compares
    only within a group, and the control-consumes-its-label rule is keyed the
    same way. Nothing in one child can delete anything in another, so a
    child's lines survive into the parent unchanged.

    The cases include ones built to break it -- the same sentence on two
    siblings, the same sentence across a containment boundary, a button label
    restated by a sibling span. If a future change makes suppression
    cross-element, this is where it shows up, and it will show up as a
    *correctness* problem in the parent rather than only as a bound failure.
    """
    url = "https://bound.test/page"
    scan = StreamingScan(url)
    trie = scan.push(LOWER_BOUND_CASES[name], passno=0).trie
    steps = M.url_steps(url)
    page = trie.node_at(steps)
    assert page is not None
    M._annotate_xpaths(page, steps, url)
    url_depth = len(steps)

    checked = 0

    def walk(node):
        nonlocal checked
        kids = [c for c in node.ordered_children()
                if not c.is_leaf and not M._is_terminal_pair(c)]
        if not kids:
            return
        _parent, parent_chars = M._render_sized(node, url, url_depth)
        for child in kids:
            _chunk, child_chars = M._render_sized(child, url, url_depth)
            assert child_chars <= parent_chars, (
                "{}: child {} renders to {} inside a parent of {}".format(
                    name, getattr(child, "_xpath_cache", "?"),
                    child_chars, parent_chars))
            checked += 1
        for child in kids:
            walk(child)

    walk(page)
    assert checked, name


def test_dedupe_is_element_scoped():
    """The property the floor rests on, asserted directly.

    Two units carrying the same words at two different elements must both
    survive. If this ever stops holding, the floor above stops holding with
    it, and so does the reason `_dedupe` gives for its own scope: the same
    text on two elements is two facts about two places.
    """
    same = "Acme Corporation annual report"
    units = [
        (M.ContentAddress("u", "/html/body/p[1]", "text", "text()[1]"),
         same, ""),
        (M.ContentAddress("u", "/html/body/p[2]", "text", "text()[1]"),
         same, ""),
    ]
    assert len(M._dedupe(units)) == 2

    # ...and the same words twice at *one* element collapse, which is what the
    # rule is for. Without this half the test above would pass on a dedup that
    # does nothing at all.
    one_element = [
        (M.ContentAddress("u", "/html/body/p[1]", "text", "aria-label"),
         same, ""),
        (M.ContentAddress("u", "/html/body/p[1]", "text", "text()[1]"),
         same + " for 2026", ""),
    ]
    assert len(M._dedupe(one_element)) == 1


# --- the bound must not change what is drawn --------------------------------


def _render_all(html, url, window):
    from vertiscope.markdown import render_trie

    scan = StreamingScan(url, context_window=window)
    return [(c.cid, c.xpath, c.part, c.markdown)
            for c in render_trie(scan.push(html, passno=0).trie,
                                 context_window=window)]


def _generated(seed):
    """Page shapes chosen to stress the descent, not to look like the web.

    Deep wrapper chains (where the ancestor fit test used to cost the most),
    headings whose words live in child elements (the one case that breaks the
    *upper* bound), a single element holding hundreds of paragraphs (the RFC
    shape that made the window stop meaning anything), tables, and ordinary
    article structure.
    """
    import random

    rng = random.Random(seed)
    words = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta"]

    def txt(k):
        return " ".join(rng.choice(words) for _ in range(k))

    kind = seed % 6
    if kind == 0:
        rows = "".join(
            "<li><h3>Item {}</h3><p>{}</p>"
            "<a href='https://e.test/{}'>open</a></li>".format(i, txt(8), i)
            for i in range(rng.randint(3, 40)))
        return "<html><body><main><ul>{}</ul></main></body></html>".format(rows)
    if kind == 1:
        return ("<html><body><main>" + "".join(
            "<h3><div>{}</div><span>{}</span></h3><p>{}</p>".format(
                txt(2), txt(5), txt(20))
            for _ in range(rng.randint(2, 15))) + "</main></body></html>")
    if kind == 2:
        return ("<html><body><main><pre>" + "".join(
            "<p>{}</p>".format(txt(30)) for _ in range(rng.randint(5, 50)))
            + "</pre></main></body></html>")
    if kind == 3:
        deep = "<p>{}</p>".format(txt(40))
        for _ in range(rng.randint(2, 12)):
            deep = "<div>{}</div>".format(deep)
        return "<html><body><main>{}</main></body></html>".format(deep)
    if kind == 4:
        return ("<html><body><main><table>" + "".join(
            "<tr>" + "".join("<td>{}</td>".format(txt(4))
                             for _ in range(rng.randint(2, 6))) + "</tr>"
            for _ in range(rng.randint(2, 20))) + "</table></main></body></html>")
    return ("<html><body><header><h1>{}</h1></header><main>".format(txt(3))
            + "".join(
                "<section><h2>{}</h2>".format(txt(3)) + "".join(
                    "<p>{}</p>".format(txt(rng.randint(1, 60)))
                    for _ in range(rng.randint(1, 8))) + "</section>"
                for _ in range(rng.randint(1, 10)))
            + "</main><footer><p>{}</p></footer></body></html>".format(txt(5)))


@pytest.mark.parametrize("window", [120, 400, 1200, 4000])
def test_skipping_the_fit_test_does_not_change_the_render(monkeypatch, window):
    """The bound decides *when to ask*, never *what the answer is*.

    `_certainly_overflows` lets the descent skip an ancestor's own render when
    its children already exceed the window. That is a claim about cost, and it
    must be invisible in the output: this renders every page twice, once with
    the bound live and once with it disabled, and compares chunk for chunk.

    Disabling it reproduces the descent as it behaved before the bound
    existed, so this is the A/B against the previous algorithm, kept as a test
    because the previous algorithm is no longer in the tree to diff against.
    It was run once directly, over 300 generated pages at four windows --
    58,776 chunk renderings, byte-identical.
    """
    import vertiscope.markdown as md

    for seed in range(40):
        html = _generated(seed)
        url = "https://ab.test/p{}".format(seed)
        with_bound = _render_all(html, url, window)
        monkeypatch.setattr(md, "_certainly_overflows", lambda *_a: False)
        without = _render_all(html, url, window)
        monkeypatch.undo()
        assert with_bound == without, "seed {} at window {}".format(seed, window)


def test_the_bound_actually_fires():
    """Non-vacuity: a bound that never triggers would pass the test above."""
    from vertiscope.markdown import RenderMemo, render_trie

    html = _generated(0)
    scan = StreamingScan("https://ab.test/fires")
    memo = RenderMemo()
    render_trie(scan.push(html, passno=0).trie, context_window=120, memo=memo)
    assert memo.skipped_fit_tests > 0


def test_probing_a_child_does_not_render_it():
    """`_size_of` proves an overflow without drawing anything.

    The bound alone was not enough. `_descend` measures its children before
    deciding about itself, and measuring meant *rendering* -- so on the path
    from an edited leaf to the page root, the same stale subtree was drawn
    once per level. Profiled at five whole-page `_collect` walks to redraw a
    1,600-row page after a one-word edit, which was the whole remaining cost.

    Asserted by counting `_collect` calls, because a timing would pass on a
    slow machine and fail on a fast one, and because the claim is about work
    done rather than time taken.
    """
    from vertiscope.markdown import RenderMemo, render_trie
    import vertiscope.markdown as md

    def page(n, edit=None):
        def body(i):
            return "EDITED" if i == edit else "body text for row {}".format(i)
        rows = "".join(
            "<li><h3>Item {}</h3><p>{}</p>"
            "<a href='https://e.test/{}'>open</a></li>".format(i, body(i), i)
            for i in range(n))
        return ("<html><body><header><h1>C</h1></header>"
                "<main><ul>{}</ul></main></body></html>".format(rows))

    n = 400
    scan = StreamingScan("https://probe.test/page")
    memo = RenderMemo()
    render_trie(scan.push(page(n), passno=0).trie, context_window=1200,
                memo=memo)

    calls = {"n": 0, "nodes": 0}
    real = md._collect

    def counting(node, url_depth):
        calls["n"] += 1
        out = real(node, url_depth)
        calls["nodes"] += len(out)
        return out

    md._collect = counting
    try:
        render_trie(scan.push(page(n, edit=n // 2), passno=1).trie,
                    context_window=1200, memo=memo)
    finally:
        md._collect = real

    # The edited row and its own small subtree, and nothing resembling the
    # page. A whole-page walk would put ~n units through a single call.
    assert calls["nodes"] < n, (
        "{} units collected over {} calls for a one-word edit on {} rows"
        .format(calls["nodes"], calls["n"], n))
