"""G-235: the code property graph -- AST, CFG, DFG, CALLS, INHERITS -- by
the same addresses as the chunks, stored per file, resolved across files."""
import re

from domvec.cpg import build_cpg

canon = lambda xp: re.sub(r"\[1\](?=/|$)", "", xp)
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
    tags = {canon(t.xpath.rsplit("/name[", 1)[0]) for t in tag_source(A, root="r", rel_path="pkg/a.py") if "/name[" in t.xpath}
    assert {n["xpath"] for n in g["nodes"] if n["kind"] in ("class", "function")} == tags


def test_cfg_branches_loops_and_dfg_defs_to_uses():
    g = build_cpg(A, "code://r/a.py", "a.py")
    run = "/module/class/function"
    cfg = _edges(g, "CFG")
    assert (run, run + "/stmt", "entry") in cfg                       # y = x + 1
    assert (run + "/stmt[2]", run + "/stmt[2]/stmt", "true") in cfg   # if -> z = helper(y)
    assert (run + "/stmt[2]", run + "/stmt[2]/stmt[2]", "false") in cfg  # if -> z = 0
    assert (run + "/stmt[3]/stmt", run + "/stmt[3]", "loop") in cfg   # loop body -> header
    dfg = _edges(g, "DFG")
    assert (run, run + "/stmt", "x") in dfg                           # parameter x -> its use
    assert (run + "/stmt", run + "/stmt[2]", "y") in dfg              # y defined -> if y > 2
    calls = _edges(g, "CALLS")
    assert (run, "/module/class/function[2]", None) in [(a, b, None) for a, b, _ in calls]   # self.done


def test_stored_and_resolved_across_files_whichever_comes_first(tmp_path):
    with Workspace(tmp_path) as ws:
        ws.index_source(A, "a.py", root="r")             # its callee's file is not indexed yet
        before = ws.store.cpg_of(source_url("r", "a.py"))
        assert not [e for e in before["edges"] if e["kind"] in ("CALLS", "INHERITS") and e["dst_url"] != e["src_url"]]
        ws.index_source(B, "b.py", root="r")             # now it is: the pending edges resolve
        after = ws.store.cpg_of(source_url("r", "a.py"))
        cross = {(e["kind"], e["dst"].split("|")[1]) for e in after["edges"] if e["dst_url"] != e["src_url"]}
        assert ("CALLS", "/module/function") in cross            # helper
        assert ("INHERITS", "/module/class") in cross            # Base
        # Re-indexing b (its nodes deleted and recreated) keeps a's edges into it.
        ws.index_source(B, "b.py", root="r")
        again = ws.store.cpg_of(source_url("r", "a.py"))
        assert {(e["kind"], e["dst"].split("|")[1]) for e in again["edges"] if e["dst_url"] != e["src_url"]} == cross


def test_a_web_pages_python_block_is_graphed_below_its_pre(tmp_path):
    """G-233/G-235: a page's code sample joins the graph at its own address;
    a shell block does not; re-ingesting one block leaves the other's nodes.
    The chunks are built as the LIVE sensor delivers a code block -- one line
    at the `<pre>`, its text whole (the offline tagger folds a pre into the
    paragraph before it, a different instrument)."""
    from domvec.address import ContentAddress
    from domvec.markdown import MarkdownChunk, MarkdownLine
    url = "https://docs.example.org/tour"
    def line(xp, text):
        return MarkdownLine(depth=0, text=text, address=ContentAddress(url=url, xpath=xp, tag="text.code", accessor="text"))
    NL = chr(10)
    fence = lambda *rows: NL.join(["```", *rows, "```"])
    py = fence("from mylib import pipeline", "", "def run(text):", "    clf = pipeline('sentiment')", "    return clf(text)")
    sh = fence("pip install mylib", "mylib --version")
    loop = fence("for t in ['a', 'b']:", "    print(t)")
    chunks = [MarkdownChunk(url=url, xpath="/html/body/main", lines=[
        line("/html/body/main/p", "Use the pipeline:"), line("/html/body/main/pre", py),
        line("/html/body/main/pre[2]", sh), line("/html/body/main/pre[3]", loop)])]
    with Workspace(tmp_path) as ws:
        got = ws.web_code_cpg(url, chunks)
        assert got["blocks"] == 3 and got["python"] == 2, got           # the shell block is not Python
        rows = ws.store._rows("MATCH (n:CodeNode {url: $u}) RETURN n.xpath, n.kind, n.calls_out", {"u": url})
        fn = [(x, c) for x, k, c in rows if k == "function"]
        assert len(fn) == 1 and fn[0][0] == "/html/body/main/pre/module/function"
        assert "mylib.pipeline" in fn[0][1]                               # resolvable to the library
        before = {x for x, _k, _c in rows}
        # Only the loop block re-ingested: the pipeline block's nodes stay.
        ws.web_code_cpg(url, [MarkdownChunk(url=url, xpath="/html/body/main", lines=[line("/html/body/main/pre[3]", loop.replace("print(t)", "print(t.upper())"))])])
        after = {x for (x,) in ws.store._rows("MATCH (n:CodeNode {url: $u}) RETURN n.xpath", {"u": url})}
        assert "/html/body/main/pre/module/function" in after and before <= after
