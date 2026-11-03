"""PLUGIN_GOAL 93-94: the code graph over concrete syntax trees, and its PageRank
(`domvec/codegraph.py`)."""

from pathlib import Path

from domvec.codegraph import CodeGraph


def _pkg(tmp_path: Path) -> Path:
    root = tmp_path / "pkg"
    root.mkdir()
    (root / "__init__.py").write_text("")
    (root / "base.py").write_text(
        "class Base:\n"
        "    def core(self):\n"
        "        return 1\n"
        "\n"
        "def helper():\n"
        "    return set()\n"            # a builtin: links nothing
    )
    (root / "use.py").write_text(
        "from .base import Base, helper\n"
        "\n"
        "class Child(Base):\n"
        "    def go(self):\n"
        "        self.step()\n"         # a method on the same class
        "        return helper()\n"
        "\n"
        "    def step(self):\n"
        "        return {}.items()\n"   # a builtin attribute: links nothing
    )
    return root


def test_definitions_and_their_kinds(tmp_path):
    g = CodeGraph(_pkg(tmp_path)).build()
    assert g.kind["pkg.base.Base"] == "class"
    assert g.kind["pkg.base.Base.core"] == "method"
    assert g.kind["pkg.base.helper"] == "function"
    assert g.kind["pkg.use"] == "module"


def test_edges_resolve_as_python_would(tmp_path):
    g = CodeGraph(_pkg(tmp_path)).build()
    e = set(g.edges)
    assert ("pkg.use.Child", "pkg.base.Base", "inherits") in e
    assert ("pkg.use.Child.go", "pkg.use.Child.step", "calls") in e
    assert ("pkg.use.Child.go", "pkg.base.helper", "calls") in e
    assert ("pkg.use", "pkg.base", "imports") in e            # a relative import, resolved
    assert not any(b.endswith(".set") or b.endswith(".items") for _, b, k in g.edges if k == "calls")


def test_pagerank_is_a_percentile(tmp_path):
    g = CodeGraph(_pkg(tmp_path)).build()
    assert all(0.0 <= v <= 1.0 for v in g.rank.values())
    # Called, inherited from and imported: the base outranks the leaf method.
    assert g.percentile("pkg.base.Base") > g.percentile("pkg.use.Child.step")


def test_code_urls_map_to_modules(tmp_path):
    g = CodeGraph(_pkg(tmp_path))
    assert g.module_of_url("code://repo/core/chunk_builder.py") == "pkg.core.chunk_builder"
    assert g.module_of_url("https://example.com") == ""


def test_the_cache_rereads_only_what_changed(tmp_path):
    root = _pkg(tmp_path)
    cache = tmp_path / "cg.json"
    CodeGraph(root, cache).build()
    g2 = CodeGraph(root, cache).build()
    assert g2.stats["reread"] == 0


def test_type_ranks_are_a_pagerank_over_kinds_and_the_plant_flattens_them(tmp_path):
    """G-317: the type graph's PageRank -- kinds weighted by the edges between
    their members; planted uniform, every kind 1."""
    from domvec import codegraph as cg
    (tmp_path / "m.py").write_text(
        "class A:\n    def f(self):\n        return g()\n\ndef g():\n    return 1\n\ndef h():\n    return g()\n",
        encoding="utf-8")
    g = cg.CodeGraph(tmp_path, None).build()
    r = g.type_ranks()
    assert set(r) == {"module", "class", "method", "function"}
    assert max(r.values()) == 1.0 and len(set(r.values())) > 1
    cg.PLANT_UNIFORM_TYPES[0] = True
    try:
        assert set(g.type_ranks().values()) == {1.0}
    finally:
        cg.PLANT_UNIFORM_TYPES[0] = False
