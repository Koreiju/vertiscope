"""PLUGIN_GOAL 62/63': a slate is a Python module written as a markdown tree."""

from domvec.slate_module import check, compile_module, identifier

T = "\t"
COCKPIT = "\n".join(["---", "domvec: slate", "---", "ego", T + "view" + T + "ego", T + "throttle" + T + "55",
                     T + "keys" + T + "{keys}", T + "plan" + T + "{results}", T + "search",
                     T + T + "query" + T, T + T + "k" + T + "8", T + T + "results" + T + "{results}"])


def kinds(text, known=()):
    return [(d.line, d.kind, d.message.split(" ")[0]) for d in check(text, known)]


def test_the_cockpits_triple_results_is_an_error():
    # `plan {results}`: nothing at module scope is called results;
    # `results {results}`: a name defined as itself.
    got = check(COCKPIT, known={"keys"})
    msgs = [(d.line, d.kind, d.message) for d in got]
    assert [(l, k) for l, k, _ in msgs] == [(7, "NameError"), (11, "NameError")]
    assert "not defined" in msgs[0][2] and "defined as itself" in msgs[1][2]


def test_a_dotted_reference_resolves():
    fixed = COCKPIT.replace("plan" + T + "{results}", "plan" + T + "{search.results}").replace("results" + T + "{results}", "results")
    assert check(fixed, known={"keys"}) == []


def test_the_same_name_twice_in_one_namespace():
    text = "m\n" + T + "a" + T + "1\n" + T + "a" + T + "2\n" + T + "g\n" + T + T + "a" + T + "3"
    got = check(text)
    assert [(d.line, d.kind) for d in got] == [(2, "SyntaxError")]      # g/a is another namespace


def test_scopes_reach_outward_and_python_cells_define_names():
    text = "\n".join(["m", T + "rate" + T + "0.5", T + "inner", T + T + "uses" + T + "{rate}", T + T + "df" + T + "{frame}",
                      "", "```python", "frame = 3", "```"])
    assert check(text) == []
    assert [d.kind for d in check(text.replace("frame = 3", "other = 3"))] == ["NameError"]


def test_a_circular_definition():
    text = "m\n" + T + "a" + T + "{b}\n" + T + "b" + T + "{a}"
    assert any("circular" in d.message for d in check(text))


def test_compiled_module_runs_with_bindings_in_dependency_order():
    text = "\n".join(["ego", T + "plan" + T + "{search.results}", T + "label" + T + "k is {search.k}", T + "search",
                      T + T + "k" + T + "8", T + T + "on" + T + "true", T + T + "results" + T + "{hits}", T + "items",
                      T + T + "- a", T + T + "- b"])
    src = compile_module(text)
    ns = {"hits": [1, 2]}
    exec(src, ns)
    ego = ns["ego"]
    assert ego.search.k == 8 and ego.search.on is True and ego.plan == [1, 2]
    assert ego.label == "k is 8" and ego.items == ["a", "b"]


def test_names_with_spaces_are_identifiers():
    assert identifier("flight plan") == "flight_plan" and identifier("class") == "class_" and identifier("2d") == "_2d"


def test_a_markdown_note_holds_trees_among_its_prose():
    from domvec.slate_module import trees_of
    note = "\n".join(["# Notebook", "", "Some prose about the run.", "", "params", T + "rate" + T + "0.5", T + "rate" + T + "0.7",
                      "", "- a list item", "", "```python", "x = 1", "```"])
    trees = trees_of(note)
    assert trees.split("\n")[2] == "" and trees.split("\n")[4] == "params"
    assert [(d.line, d.kind) for d in check(trees)] == [(6, "SyntaxError")]


def test_an_outside_name_not_yet_defined_waits_instead_of_failing():
    src = compile_module("params\n" + T + "rate" + T + "0.5\n" + T + "steps" + T + "{n}")
    ns = {}
    exec(src, ns)                                   # before the cell that defines n
    assert ns["params"].rate == 0.5 and not hasattr(ns["params"], "steps")
    ns["n"] = 3
    exec(src, ns)                                   # after it
    assert ns["params"].steps == 3
