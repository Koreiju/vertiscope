"""G-235: the code property graph -- AST, CFG, DFG, CALLS, INHERITS -- by
the same addresses as the chunks, stored per file, resolved across files."""
from domvec.cpg import build_cpg
from domvec.source import source_url, tag_source
from domvec.workspace import Workspace

A = '''"""Module a."""
from b import helper, Base


class Thing(Base):
    def run(self, x):
        y = x + 1
        if y > 2:
            z = helper(y)
        else:
            z = 0
        for i in range(z):
            y = y + i
        return self.done(y)

    def done(self, v):
        return v


def top():
    return Thing().run(3)
'''
B = '''def helper(n):
    return n * 2


class Base:
    pass
'''


def _edges(g, kind):
    return [(e["src"].split("|")[1], e["dst"].split("|")[1], e.get("label") or e.get("var")) for e in g["edges"] if e["kind"] == kind]


def test_symbols_are_the_chunks_addresses():
    url = source_url("r", "pkg/a.py")
    g = build_cpg(A, url, "pkg/a.py")
    tags = {t.xpath.rsplit("/name[", 1)[0] for t in tag_source(A, root="r", rel_path="pkg/a.py") if "/name[" in t.xpath}
    assert {n["xpath"] for n in g["nodes"] if n["kind"] in ("class", "function")} == tags


def test_cfg_branches_loops_and_dfg_defs_to_uses():
    g = build_cpg(A, "code://r/a.py", "a.py")
    run = "/module[1]/class[1]/function[1]"
    cfg = _edges(g, "CFG")
    assert (run, run + "/stmt[1]", "entry") in cfg                       # y = x + 1
    assert (run + "/stmt[2]", run + "/stmt[2]/stmt[1]", "true") in cfg   # if -> z = helper(y)
    assert (run + "/stmt[2]", run + "/stmt[2]/stmt[2]", "false") in cfg  # if -> z = 0
    assert (run + "/stmt[3]/stmt[1]", run + "/stmt[3]", "loop") in cfg   # loop body -> header
    dfg = _edges(g, "DFG")
    assert (run, run + "/stmt[1]", "x") in dfg                           # parameter x -> its use
    assert (run + "/stmt[1]", run + "/stmt[2]", "y") in dfg              # y defined -> if y > 2
    calls = _edges(g, "CALLS")
    assert (run, "/module[1]/class[1]/function[2]", None) in [(a, b, None) for a, b, _ in calls]   # self.done


def test_stored_and_resolved_across_files_whichever_comes_first(tmp_path):
    with Workspace(tmp_path) as ws:
        ws.index_source(A, "a.py", root="r")             # its callee's file is not indexed yet
        before = ws.store.cpg_of(source_url("r", "a.py"))
        assert not [e for e in before["edges"] if e["kind"] in ("CALLS", "INHERITS") and e["dst_url"] != e["src_url"]]
        ws.index_source(B, "b.py", root="r")             # now it is: the pending edges resolve
        after = ws.store.cpg_of(source_url("r", "a.py"))
        cross = {(e["kind"], e["dst"].split("|")[1]) for e in after["edges"] if e["dst_url"] != e["src_url"]}
        assert ("CALLS", "/module[1]/function[1]") in cross            # helper
        assert ("INHERITS", "/module[1]/class[1]") in cross            # Base
        # Re-indexing b (its nodes deleted and recreated) keeps a's edges into it.
        ws.index_source(B, "b.py", root="r")
        again = ws.store.cpg_of(source_url("r", "a.py"))
        assert {(e["kind"], e["dst"].split("|")[1]) for e in again["edges"] if e["dst_url"] != e["src_url"]} == cross
