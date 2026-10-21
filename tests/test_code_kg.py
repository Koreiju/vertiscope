"""PLUGIN_GOAL 186g: the compact code knowledge graph -- one triple per fact
of what code IS and DOES, at the CPG's own addresses."""
from vertiscope.code_kg import compact

NL = chr(10)
SRC = NL.join([
    "import os",
    "from mylib import pipeline as pl",
    "",
    "class Store(dict):",
    "    def get(self, key):",
    "        value = self.read(key)",
    "        if value is None:",
    "            value = os.environ.get(key)",
    "        return value",
    "",
    "    def read(self, key):",
    "        return None",
    "",
    "a = 1",
    "b = a",
    "pipe = pl('x')",
    "",
])


def _set(r):
    return {(t["s"], t["p"], t["o"], t["at"].split("|", 1)[1]) for t in r["triples"]}


def test_one_triple_per_fact_at_the_cpg_addresses():
    got = _set(compact(SRC, "code://r/m.py", "m.py"))
    assert ("b", "ASSIGNED_FROM", "a", "/module/stmt[4]") in got                 # a = b, one triple
    assert ("m", "IMPORTS", "mylib.pipeline", "/module/stmt[2]") in got           # an import, one triple
    assert ("m", "DEFINES", "pl", "/module/stmt[2]") in got
    assert ("pipe", "ASSIGNED_FROM", "pl", "/module/stmt[5]") in got
    assert ("m.Store", "INHERITS", "dict", "/module/class") in got
    assert ("m.Store.get", "CALLS", "m.Store.read", "/module/class/function") in got
    assert ("m", "CALLS", "mylib.pipeline", "/module") in got
    assert ("m.Store.get", "RETURNS", "value", "/module/class/function/stmt[3]") in got
    assert ("stmt[2]", "BRANCHES_ON", "value", "/module/class/function/stmt[2]") in got
    # A dotted chain is ONE name read, not three.
    reads = {o for s, p, o, at in got if s == "value" and p == "ASSIGNED_FROM"}
    assert "os.environ.get" in reads and "os" not in reads and "os.environ" not in reads


def test_each_assignment_cites_the_dataflow_it_summarises():
    r = compact(SRC, "code://r/m.py", "m.py")
    t = next(t for t in r["triples"] if (t["s"], t["p"], t["o"]) == ("b", "ASSIGNED_FROM", "a"))
    assert t["cpg"] == ["/module/stmt[3]->/module/stmt[4]"]


def test_non_vacuity_a_changed_module_changes_its_triples():
    """The graph follows the code: drop the import and rebind b, and exactly
    those facts move."""
    before = _set(compact(SRC, "code://r/m.py", "m.py"))
    src2 = SRC.replace("from mylib import pipeline as pl" + NL, "").replace("pipe = pl('x')", "pipe = 3").replace("b = a", "b = pipe")
    after = _set(compact(src2, "code://r/m.py", "m.py"))
    assert not any(p == "IMPORTS" and o == "mylib.pipeline" for s, p, o, at in after)
    assert any((s, p, o) == ("b", "ASSIGNED_FROM", "pipe") for s, p, o, at in after)
    assert not any((s, p, o) == ("b", "ASSIGNED_FROM", "a") for s, p, o, at in after)
    assert before != after


def test_a_web_code_block_is_addressed_below_its_pre():
    r = compact("x = 1" + NL + "y = x" + NL, "https://ex.test/p", prefix="/html/body/pre", qname="web")
    assert ("y", "ASSIGNED_FROM", "x", "/html/body/pre/module/stmt[2]") in _set(r)
