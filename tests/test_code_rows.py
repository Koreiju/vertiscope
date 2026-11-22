"""G-378: a regular code artifact as typed rows, an edit written back losslessly.

Planted arm: PLANT_AST_UNPARSE writes back through ast.unparse -- comments and
formatting are lost, and the lossless assertions must fail on it.
"""

import pytest

from domvec import code_rows as cr

SRC = '''# the scanner's inputs
url: str = "https://duckduckgo.com"   # where it looks
depth = 3

class Hit:
    title: str = ""
    score: float = 0.0

def scan(query: str, k: int = depth) -> list:
    url = "local"          # a local of the same name: not the row
    return [query, url, k]

hits = scan(url, k=depth)
print(Hit.score, depth)
'''


def test_rows_read_names_types_values_and_reads():
    got = {r.name: r for r in cr.rows(SRC)}
    assert got["url"].type == "str" and got["url"].value == '"https://duckduckgo.com"'
    assert got["depth"].value == "3" and got["depth"].line == 3
    assert got["Hit"].kind == "class" and [c.name for c in got["Hit"].children] == ["title", "score"]
    assert got["scan"].kind == "function" and got["scan"].type == "list"
    assert [(p.name, p.type, p.value) for p in got["scan"].children] == [("query", "str", ""), ("k", "int", "depth")]
    assert got["hits"].reads == ["depth", "scan", "url"]


def test_set_value_touches_only_that_row():
    out = cr.set_value(SRC, "depth", "5")
    assert out == SRC.replace("depth = 3", "depth = 5")


def test_set_type_turns_a_plain_binding_into_a_typed_row():
    out = cr.set_type(SRC, "depth", "int")
    assert "depth: int = 3" in out and "# where it looks" in out


def test_rename_follows_reads_but_not_locals_attributes_or_keywords():
    out = cr.rename(SRC, "depth", "levels")
    assert "levels = 3" in out and "k: int = levels" in out and "scan(url, k=levels)" in out
    assert "print(Hit.score, levels)" in out
    out2 = cr.rename(SRC, "url", "site")
    assert 'site: str = "https://duckduckgo.com"   # where it looks' in out2
    assert 'url = "local"' in out2 and "return [query, url, k]" in out2      # the local kept
    assert "hits = scan(site, k=depth)" in out2


def test_refusals():
    with pytest.raises(KeyError):
        cr.set_value(SRC, "nowhere", "1")
    with pytest.raises(Exception):
        cr.set_value(SRC, "depth", "3 +")                # not an expression: nothing written
    with pytest.raises(ValueError):
        cr.rename(SRC, "depth", "url")                  # already a row


def test_planted_ast_unparse_loses_the_comments(monkeypatch):
    monkeypatch.setattr(cr, "PLANT_AST_UNPARSE", [True])
    out = cr.set_value(SRC, "depth", "5")
    assert "# where it looks" not in out and out != SRC.replace("depth = 3", "depth = 5")


def test_the_route_reads_rows_and_writes_an_edit_back(tmp_path):
    import json
    import urllib.error
    import urllib.request
    from domvec.obsidian import sidecar as sc
    from domvec.workspace import Workspace
    with Workspace(tmp_path / "ws") as ws:
        srv = sc.serve(ws, port=0, block=False)
        base = "http://127.0.0.1:%d/code_rows" % srv.server_address[1]

        def post(body):
            req = urllib.request.Request(base, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    return r.status, json.load(r)
            except urllib.error.HTTPError as e:
                return e.code, json.load(e)
        try:
            st, got = post({"source": SRC, "edit": {"op": "value", "name": "depth", "value": "7"}})
            st2, bad = post({"source": SRC, "edit": {"op": "value", "name": "nowhere", "value": "1"}})
        finally:
            srv.shutdown(); srv.server_close()
    assert st == 200 and got["source"] == SRC.replace("depth = 3", "depth = 7")
    assert any(r["name"] == "depth" and r["value"] == "7" for r in got["rows"])
    assert st2 == 400 and "nowhere" in bad["error"]
