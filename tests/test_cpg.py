"""G-235: the code property graph -- AST, CFG, DFG, CALLS, INHERITS -- by
the same addresses as the chunks, stored per file, resolved across files."""
import re

from vertiscope.cpg import build_cpg

canon = lambda xp: re.sub(r"\[1\](?=/|$)", "", xp)
from vertiscope.source import source_url, tag_source
from vertiscope.workspace import Workspace

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
    from vertiscope.address import ContentAddress
    from vertiscope.markdown import MarkdownChunk, MarkdownLine
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



def test_a_code_block_is_graphed_from_the_trie_value_not_its_markdown_line(tmp_path, monkeypatch):
    """A chunk's markdown line holds a code block on ONE line (lines zip
    one-to-one with addresses; a fenced block shifted every line after it --
    huggingface 2026-10-18, a sample filed under the next paragraph's and a
    button's addresses). The graph reads the trie's value, newlines kept.
    Offline (`ingest`) and the live capture's path (`ingest_chunks` with
    `raw_values`, as the sidecar calls it) both. Planted
    `_PLANT_CODE_FROM_LINE`: the one-line markdown, and nothing is graphed."""
    import vertiscope.workspace as wsmod
    from vertiscope.address import ContentAddress
    from vertiscope.markdown import MarkdownChunk, MarkdownLine
    NL = chr(10)
    html = ("<html><body><main><p>Use the pipeline here.</p><div><pre><code class='language-py'>"
            "<span>from</span> mylib <span>import</span> pipeline" + NL + "pipe = pipeline('x')" + NL
            + "def run(x):" + NL + "    return pipe(x)" + NL + "</code></pre></div><p>After.</p></main></body></html>")
    url = "https://docs.example.org/fenced"
    live = "https://docs.example.org/live"
    addr = ContentAddress(url=live, xpath="/html/body/div/pre", tag="code", accessor="text()[0]")
    raw = NL.join(["from mylib import pipeline", "def run(x):", "    return pipeline(x)"])
    flat = "`" + " ".join(raw.split()) + "`"
    got = {}
    for planted in (False, True):
        monkeypatch.setattr(wsmod, "_PLANT_CODE_FROM_LINE", planted)
        with Workspace(tmp_path / ("p" if planted else "c")) as ws:
            ws.index_html(html, url)
            off = (ws.last_web_cpg.get("python"), len(ws.store.cpg_of(url)["nodes"]))
            chunk = MarkdownChunk(url=live, xpath="/html/body/div", lines=[MarkdownLine(depth=0, text=flat, address=addr)])
            ws.ingest_chunks(live, [chunk], complete=False, raw_values=lambda a: raw if a == addr else None)
            on = (ws.last_web_cpg.get("python"), len(ws.store.cpg_of(live)["nodes"]))
            got[planted] = (off, on)
    assert got[False][0][0] == 1 and got[False][0][1] >= 3, got
    assert got[False][1][0] == 1 and got[False][1][1] >= 3, got
    assert got[True][0] == (0, 0) and got[True][1] == (0, 0), got


def test_a_modules_own_statements_are_graphed(monkeypatch):
    """A web sample is top-level code: its statements flow, define and use,
    and call from the MODULE node. Planted `_PLANT_NO_MODULE_STMTS`: only
    functions' statements, and the sample is an empty module."""
    import vertiscope.cpg as cpgmod
    NL = chr(10)
    src = NL.join(["from mylib import pipeline", "pipe = pipeline('sentiment')", "out = pipe('hi')", "print(out)", ""])
    got = {}
    for planted in (False, True):
        monkeypatch.setattr(cpgmod, "_PLANT_NO_MODULE_STMTS", planted)
        g = build_cpg(src, "https://ex.test/p", prefix="/html/body/pre", qname="web")
        mod = [n for n in g["nodes"] if n["kind"] == "module"][0]
        got[planted] = (sum(1 for n in g["nodes"] if n["kind"] == "stmt"),
                        {(e["var"]) for e in g["edges"] if e["kind"] == "DFG"},
                        sum(1 for e in g["edges"] if e["kind"] == "CFG"), mod["calls_out"])
    stmts, dfg, cfg, calls = got[False]
    assert stmts == 4 and {"pipe", "out", "pipeline"} <= dfg and cfg >= 3 and "mylib.pipeline" in calls, got
    assert got[True] == (0, set(), 0, []), got
