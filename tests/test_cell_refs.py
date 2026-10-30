"""G-279: a cell's `{ref}` inputs are resolved through the store and bound
into its kernel; every run is recorded as a forward map, inputs -> output.

Planted: an unresolvable name binds nothing (and says so), and a run with no
inputs records no `RunInput` -- the inverse map then finds nothing.
"""

from domvec.address import ContentAddress
from domvec.graphstore import GraphStore
from domvec.markdown import MarkdownChunk, MarkdownLine
from domvec.obsidian import refs as R

URL = "https://example.org/radix"


class _WS:
    def __init__(self, store):
        self.store = store

    def search(self, q, k=10):
        return []


def _store(tmp_path):
    store = GraphStore(tmp_path / "s.kuzu")
    chunks, addrs = [], []
    for i, text in enumerate(["A radix tree compresses chains.", "Each edge holds a string."]):
        xp = "/html/body/p[%d]" % (i + 1)
        a = ContentAddress(url=URL, xpath=xp + "/text()[1]", tag="text.p", accessor="text")
        chunks.append(MarkdownChunk(url=URL, xpath=xp, lines=[MarkdownLine(depth=0, text=text, address=a)]))
        addrs.append((a, text, ""))
    store.ingest(URL, addrs, chunks, title="Radix tree")
    return store, chunks


def test_var_names_follow_the_ref():
    assert R.var_name("Radix tree") == "radix_tree"
    assert R.var_name("chunk samples") == "chunk_samples"
    assert R.var_name("2024 report") == "_2024_report"


def test_a_page_title_resolves_and_binds_its_text(tmp_path):
    store, chunks = _store(tmp_path)
    got = R.bind(_WS(store), ["Radix tree", "nothing by that name"])
    assert got["bound"][0]["kind"] == "page" and got["bound"][0]["var"] == "radix_tree"
    assert "radix tree compresses" in got["prelude"] and got["prelude"].startswith("radix_tree = ")
    assert got["bound"][1]["kind"] == "unresolved"
    ns = {}
    exec(got["prelude"], ns)
    assert "Each edge holds" in ns["radix_tree"]
    assert {c for _n, c in got["inputs"]} == {c.cid for c in chunks}


def test_a_run_is_recorded_both_ways(tmp_path):
    store, chunks = _store(tmp_path)
    inputs = R.bind(_WS(store), ["Radix tree"])["inputs"]
    rid = store.record_run("notes/n.md", 4, "print(len(radix_tree))", inputs, True, "57")
    runs = store.runs_of("notes/n.md")
    assert runs[0]["rid"] == rid and runs[0]["output"] == "57"
    assert {i["cid"] for i in runs[0]["inputs"]} == {c.cid for c in chunks}
    inv = store.inverse_map(chunks[0].cid)
    assert inv and inv[0]["note"] == "notes/n.md" and inv[0]["as"] == "Radix tree"
    # Planted: a run with no inputs is invisible to the inverse map.
    store.record_run("notes/m.md", 1, "print(1)", [], True, "1")
    assert all(r["note"] != "notes/m.md" for r in store.inverse_map(chunks[0].cid))


def test_signal_edges_name_every_runs_inputs_newest_first(tmp_path):
    """G-292: the signal flow the 3D view draws is every run's input -> note edge."""
    from domvec.graphstore import GraphStore
    store = GraphStore(str(tmp_path / "s"))
    try:
        store._execute("CREATE (:Chunk {cid: 'c1', url: 'https://a/', md: 'a'})")
        store._execute("CREATE (:Chunk {cid: 'c2', url: 'https://b/', md: 'b'})")
        store.record_run("n1.md", 1, "x", [("a", "c1")], True, "1")
        store.record_run("n2.md", 3, "y", [("a", "c1"), ("b", "c2")], True, "2")
        got = store.signal_edges()
        assert {(e["note"], e["cid"]) for e in got} == {("n1.md", "c1"), ("n2.md", "c1"), ("n2.md", "c2")}
        assert got[0]["note"] == "n2.md"            # newest first
        assert store.signal_edges(1) and len(store.signal_edges(1)) == 1
    finally:
        store.close()


def test_rank1_of_a_slate_is_its_first_level_and_of_prose_its_first_lines():
    """G-278: internalizing a `{ref}` reveals the target's rank-1 lines only."""
    from domvec.obsidian.refs import rank1
    slate = "---\ndomvec: slate\n---\nego\n\tview\tego\n\tsearch\n\t\tquery\tradix\n\t\tk\t8\n\tthrottle\t25\n"
    assert rank1(slate) == ["view\tego", "search\t{search}", "throttle\t25"]
    prose = "# Radix tree\n\nA radix tree compresses chains.\n\n```python\nx = 1\n```\n\nSecond paragraph.\n"
    assert rank1(prose) == ["Radix tree", "A radix tree compresses chains.", "x = 1", "Second paragraph."][:2] + rank1(prose)[2:]
    assert rank1(prose)[:2] == ["Radix tree", "A radix tree compresses chains."]
    assert len(rank1("\n".join("line %d" % i for i in range(40)))) == 12
