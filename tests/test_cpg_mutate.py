"""G-236: a graph mutation compiled back to source as a unified diff."""
import pytest

from vertiscope.cpg import build_cpg
from vertiscope.cpg_mutate import MutationError, mutate
from vertiscope.source import source_url
from vertiscope.workspace import Workspace

SRC = '''"""Module."""
import os


# a comment that must survive
class Store(object):
    """A store."""

    def get(self, key):
        value = self.read(key)
        if value is None:
            value = os.environ.get(key)
        return value

    def read(self, key):
        return None


def helper():
    return 1
'''


def _kinds(text, url="code://r/m.py"):
    g = build_cpg(text, url, "m.py")
    return {(e["kind"], e["src"].split("|")[1], e["dst"].split("|")[1]) for e in g["edges"] if e["kind"] in ("CALLS", "INHERITS")}


def test_modify_name_and_docstring_keep_comments():
    got = mutate(SRC, [{"op": "MODIFY_PROPERTY", "xpath": "/module/class/function[2]", "property": "name", "value": "fetch"},
                       {"op": "MODIFY_PROPERTY", "xpath": "/module/function", "property": "docstring", "value": "Return one."}], "m.py")
    assert "def fetch(self, key):" in got["text"] and '"""Return one."""' in got["text"]
    assert "# a comment that must survive" in got["text"]
    assert got["diff"].startswith("--- a/m.py") and "-    def read(self, key):" in got["diff"] and "+    def fetch(self, key):" in got["diff"]


def test_add_and_delete_a_call_edge_round_trip_through_the_graph():
    before = _kinds(SRC)
    assert ("CALLS", "/module/class/function", "/module/class/function[2]") in before      # get -> read (self.read)
    added = mutate(SRC, [{"op": "ADD_EDGE", "kind": "CALLS", "src": "/module/class/function", "call": "helper()"}], "m.py")
    assert ("CALLS", "/module/class/function", "/module/function") in _kinds(added["text"])
    assert added["text"].index("helper()") < added["text"].index("return value")             # before the final return
    removed = mutate(added["text"], [{"op": "DELETE_EDGE", "kind": "CALLS", "src": "/module/class/function", "name": "helper"}], "m.py")
    assert removed["text"] == SRC


def test_inherits_add_and_delete():
    got = mutate(SRC, [{"op": "DELETE_EDGE", "kind": "INHERITS", "src": "/module/class", "base": "object"}], "m.py")
    assert "class Store:" in got["text"]
    back = mutate(got["text"], [{"op": "ADD_EDGE", "kind": "INHERITS", "src": "/module/class", "base": "dict"}], "m.py")
    assert "class Store(dict):" in back["text"]


def test_add_node_delete_node_and_statement_code():
    got = mutate(SRC, [{"op": "ADD_NODE", "parent": "/module/class", "after": "/module/class/function[2]",
                        "code": "def size(self):\n    return 0\n"}], "m.py")
    assert "    def size(self):\n        return 0" in got["text"]
    gone = mutate(got["text"], [{"op": "DELETE_NODE", "xpath": "/module/class/function[3]"}], "m.py")
    assert "def size" not in gone["text"]
    code = mutate(SRC, [{"op": "MODIFY_PROPERTY", "xpath": "/module/class/function/stmt", "property": "code",
                         "value": "value = self.read(key.lower())"}], "m.py")
    assert "value = self.read(key.lower())" in code["text"]


def test_non_vacuity_a_mutation_that_breaks_the_module_is_refused():
    with pytest.raises(MutationError):
        mutate(SRC, [{"op": "MODIFY_PROPERTY", "xpath": "/module/function/stmt", "property": "code", "value": "return ("}], "m.py")
    with pytest.raises(MutationError):
        mutate(SRC, [{"op": "DELETE_NODE", "xpath": "/module/function[9]"}], "m.py")


def test_applied_and_reingested_the_store_graph_follows(tmp_path):
    with Workspace(tmp_path) as ws:
        ws.index_source(SRC, "m.py", root="r")
        url = source_url("r", "m.py")
        new = mutate(SRC, [{"op": "ADD_EDGE", "kind": "CALLS", "src": "/module/class/function", "call": "helper()"}], "m.py")
        ws.index_source(new["text"], "m.py", root="r")
        edges = {(e["kind"], e["src"].split("|")[1], e["dst"].split("|")[1]) for e in ws.store.cpg_of(url)["edges"]}
        assert ("CALLS", "/module/class/function", "/module/function") in edges
