"""G-376/G-377: the spec's tool surfaces checked against the kernel (domvec/tool_surface.py)."""

from pathlib import Path

from domvec import tool_surface as ts

SPEC = (Path(__file__).resolve().parent.parent / "docs" / "COMPUTATION_GRAPH_EDITOR_SPEC.md").read_text(encoding="utf-8")


def one(block: str):
    return ts.parse(block, ts.kernel_names())


def test_the_kernel_names_are_read_from_its_bootstrap():
    k = ts.kernel_names()
    assert {"search", "Database", "WebBrowser", "Agent", "Vault"} <= set(k)
    assert {"go", "chunks", "url", "title"} <= k["WebBrowser"]
    assert {"read", "write", "ls", "glob", "here"} <= k["Vault"]


def test_the_specs_surfaces_are_well_formed_and_counted():
    found = ts.surfaces(SPEC)
    assert [s.problems for s in found] == [[]] * len(found)
    c = ts.count(found)
    assert (c["surfaces"], c["exists"], c["new"]) == (6, 10, 14)


def test_clean_surface():
    s = one("# t\nsearch('x', k=3)  # exists: ranked\nWebBrowser.url  # exists: shown\nfocus(cid)  # new: fly\n")
    assert s.problems == [] and [l.resolves for l in s.lines] == [True, True, False]


def test_planted_exists_claim_on_a_missing_call():
    s = one("# t\nWebBrowser.teleport(1)  # exists: no such thing\n")
    assert any("claims `exists`" in p for p in s.problems)


def test_planted_new_claim_on_a_call_that_exists():
    s = one("# t\nVault.read('a.md')  # new: but it is there\n")
    assert any("claims `new`" in p for p in s.problems)


def test_planted_missing_comment_and_missing_claim():
    s = one("# t\nsearch('x')\nsearch('y')  # ranked\n")
    assert any("no comment" in p for p in s.problems)
    assert any("does not say" in p for p in s.problems)


def test_a_hash_inside_a_string_is_not_the_comment():
    s = one("# t\nsearch('#tag')  # exists: a tag query\n")
    assert s.problems == [] and s.lines[0].code == "search('#tag')"


def test_planted_two_statements_and_an_assignment():
    s = one("# t\nx = search('a')  # exists: bound\n")
    assert any("single call" in p for p in s.problems)


def test_planted_too_long():
    s = one("# t\n" + "search('x')  # exists: again\n" * 30)
    assert any("over the" in p for p in s.problems)
