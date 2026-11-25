"""G-409: node definitions from a live namespace, with ports (spec 13d')."""
import io
from contextlib import redirect_stdout

from domvec import nodedefs

CELL = '''
from typing import Literal
from collections import OrderedDict
def scan(url: str, k: int = 8, mode: Literal["fast", "deep"] = "fast", driver: object = None) -> list:
    """Scan a page."""
    return []
def guess(n=3, thing=None):
    return n
class Box:
    """A box."""
    def __init__(self, size: float = 1.0, inner: dict = None): self.size = size
    def area(self) -> float: return self.size ** 2
    def _hidden(self): pass
'''


def run(src):
    ns = {"__name__": "__main__"}
    exec(compile(CELL, "<cell>", "exec"), ns, ns)
    out = io.StringIO()
    with redirect_stdout(out):
        exec(compile(src, "<cell>", "exec"), ns, ns)
    assert "__domvec_defs" not in ns
    return nodedefs.parse({"ok": True, "stdout": out.getvalue()})["defs"]


def test_ports_follow_the_rule():
    d = {x["name"]: x for x in run(nodedefs.SRC)}
    assert set(d) == {"scan", "guess", "Box"}          # OrderedDict, Literal imported: not definitions
    ins = {p["name"]: p for p in d["scan"]["inputs"]}
    assert ins["url"]["kind"] == "socket" and ins["k"] == {"name": "k", "type": "int", "default": 8, "kind": "widget"}
    assert ins["mode"]["kind"] == "choice" and ins["mode"]["options"] == ["fast", "deep"]
    assert ins["driver"]["kind"] == "socket"
    assert d["scan"]["output"]["type"] == "list" and d["scan"]["doc"] == "Scan a page."
    g = {p["name"]: p for p in d["guess"]["inputs"]}
    assert g["n"]["kind"] == "widget" and g["n"]["type"] == "int" and g["thing"]["kind"] == "socket"
    assert d["guess"]["output"]["type"] is None                     # inferred by wiring
    assert [p["name"] for p in d["Box"]["inputs"]] == ["size", "inner"]
    assert [o["name"] for o in d["Box"]["outputs"]] == ["area"] and d["Box"]["outputs"][0]["type"] == "float"


def test_planted_all_sockets_is_caught():
    src = nodedefs.SRC.replace('d["kind"] = "widget" if', 'd["kind"] = "socket" if')
    d = {x["name"]: x for x in run(src)}
    assert {p["name"]: p for p in d["scan"]["inputs"]}["k"]["kind"] == "socket"   # the defect shows


def test_kernel_error_reported():
    assert nodedefs.parse({"ok": False, "error": "boom"})["error"] == "boom"


def test_boot_names_are_not_the_notes():
    ns = {"__name__": "__main__"}
    exec(compile("def search(q, k=8): pass", "<cell>", "exec"), ns, ns)
    ns["_domvec_boot"] = {k: id(v) for k, v in ns.items()}
    exec(compile(CELL, "<cell>", "exec"), ns, ns)
    out = io.StringIO()
    with redirect_stdout(out):
        exec(compile(nodedefs.SRC, "<cell>", "exec"), ns, ns)
    names = {d["name"] for d in nodedefs.parse({"ok": True, "stdout": out.getvalue()})["defs"]}
    assert "search" not in names and "scan" in names
