"""G-386: the editor's own calls in a kernel (domvec/obsidian/kernel_objects.py).

`create`, `link`, `invoke`, `commit`, `review` record asks; the sidecar drains
them after the cell (`DRAIN`, `parse_asks`) and the plugin carries them out on
the plane (`obsidian-plugin/src/editorcalls.ts`, live check G-386).

Planted arm: a kernel whose calls are not drained hands the plugin nothing.
"""

from domvec import tool_panels as tp
from domvec import tool_surface as ts
from domvec.obsidian import kernel_objects as ko


def _kernel():
    ns: dict = {}
    exec(ko.boot("http://127.0.0.1:0"), ns)
    return ns


def _drained(ns):
    return ko.parse_asks({"value": repr(eval(ko.DRAIN, ns))})


def test_each_call_records_one_ask_in_order():
    ns = _kernel()
    ns["create"]("a card", "x = 1", "notebook")
    ns["link"]("a card", "b")
    ns["invoke"]("b")
    ns["commit"]("sub", "a card", "b")
    ns["review"]("a card", "right?")
    got = _drained(ns)
    assert got == [{"create": {"name": "a card", "body": "x = 1", "kind": "notebook"}},
                   {"link": ["a card", "b"]}, {"invoke": "b"},
                   {"commit": {"name": "sub", "members": ["a card", "b"]}},
                   {"review": ["a card", "right?"]}]
    assert _drained(ns) == []                       # drained once


def test_planted_undrained_kernel_hands_over_nothing():
    ns = _kernel()
    ns["invoke"]("b")
    assert ko.parse_asks({"value": None}) == []     # what the plugin gets with no drain
    assert _drained(ns) == [{"invoke": "b"}]        # the ask was there to be had


def test_the_calls_are_on_the_tool_surface_and_a_panel():
    names = ts.kernel_names()
    for n in ("create", "link", "invoke", "commit", "review"):
        assert n in names and names[n] == set()
    panels = tp.render()
    assert "editor" in panels and "invoke(name)" in panels["editor"]
