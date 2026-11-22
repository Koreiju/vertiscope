"""G-380: marimo-style dataflow over a note's cells (domvec/dataflow.py).

Every rule has a planted arm (the defect must be caught) beside its clean arm.
"""

from domvec import dataflow as df


def note(*cells: str) -> str:
    return "\n\n".join("```python\n%s\n```" % c for c in cells)


def kinds(g):
    return sorted(p.kind for p in g.problems)


def test_defs_and_refs_of_one_cell():
    d, r = df.python_defs_refs("import os\nfrom a import b as c\nx = y + 1\ndef f(): return z\nclass K: pass\nfor i in w: pass")
    assert d == {"os", "c", "x", "f", "K", "i"}
    assert r == {"y", "z", "w"}


def test_underscore_names_are_cell_local():
    d, r = df.python_defs_refs("_tmp = 3\nx = _tmp + _other")
    assert d == {"x"} and r == set()


def test_builtins_and_comprehension_vars_are_not_refs():
    d, r = df.python_defs_refs("n = len([i * k for i in xs])")
    assert d == {"n"} and r == {"k", "xs"}


def test_global_assigned_in_a_function_is_a_def():
    d, _ = df.python_defs_refs("def f():\n    global g\n    g = 1")
    assert "g" in d
    # planted near-miss: a global only READ in a function is a ref, not a def
    d2, r2 = df.python_defs_refs("def f():\n    return g")
    assert "g" not in d2 and "g" in r2


def test_edges_follow_names_not_document_order():
    g = df.graph(note("y = x * 2", "x = 1", "print(y)"))
    assert g.edges[1] == {0} and g.edges[0] == {2}
    assert g.order() == [1, 0, 2]
    assert g.problems == []


def test_running_a_cell_stales_its_descendants_transitively():
    g = df.graph(note("a = 1", "b = a + 1", "c = b + 1", "d = 5"))
    assert g.descendants(0) == [1, 2]
    assert g.descendants(3) == []      # planted near-miss: an unrelated cell stales nothing


def test_one_definition_per_name():
    clean = df.graph(note("x = 1", "y = x"))
    planted = df.graph(note("x = 1", "x = 2"))
    assert clean.problems == []
    assert kinds(planted) == ["MultipleDefinitionError"]
    assert planted.problems[0].cells == [0, 1] and planted.problems[0].name == "x"


def test_rebinding_another_cells_name_is_a_redefinition_as_in_marimo():
    g = df.graph(note("x = 1", "x = x + 1"))
    assert kinds(g) == ["MultipleDefinitionError"]


def test_mutation_is_invisible_as_in_marimo():
    g = df.graph(note("xs = []", "xs.append(1)"))
    assert g.problems == [] and g.edges[0] == {1}
    assert g.cells[1].defs == set()


def test_a_cycle_is_an_error():
    clean = df.graph(note("a = 1", "b = a"))
    planted = df.graph(note("a = b", "b = a"))
    assert clean.problems == []
    assert kinds(planted) == ["CycleError"] and planted.problems[0].cells == [0, 1]


def test_a_syntax_error_is_reported_on_its_cell_only():
    g = df.graph(note("a = 1", "b = (", "c = a"))
    assert kinds(g) == ["SyntaxError"] and g.problems[0].cells == [1]
    assert g.edges[0] == {2}


def test_outside_names_are_kept_apart_from_known_kernel_objects():
    g = df.graph(note("r = search('x')", "w = mystery"), known={"search"})
    assert g.outside == {1: {"mystery"}}


SLATE_NOTE = """intro prose

params
\tk\t8
\tq\t{query}

```python
query = "cats"
hits = search(query, k=params.k)
```
"""


def test_a_slate_tree_is_a_cell_and_names_flow_both_ways():
    g = df.graph(SLATE_NOTE, known={"search"})
    kinds_ = [c.kind for c in g.cells]
    assert kinds_ == ["slate", "python"]
    slate, py = g.cells
    assert slate.defs == {"params"} and slate.refs == {"query"}
    assert py.defs == {"query", "hits"} and "params" in py.refs
    # markdown reads `query` from code; code reads `params` from markdown: a cycle,
    # caught as marimo would catch it between two code cells
    assert kinds(g) == ["CycleError"]


def test_a_slate_ref_resolved_inside_the_tree_is_not_a_ref():
    text = "params\n\tk\t8\n\tm\t{k}\n"
    g = df.graph(text)
    assert g.cells[0].refs == set() and g.problems == []


def test_graph_json_round_trips_the_shape():
    j = df.graph(note("a = 1", "b = a")).to_json()
    assert j["edges"] == {"0": [1]}
    assert j["cells"][1]["refs"] == ["a"]
