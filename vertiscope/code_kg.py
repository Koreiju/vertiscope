"""The compact code knowledge graph: what code IS and DOES, one triple per
fact (PLUGIN_GOAL 186g, 2026-10-18: "a compact knowledge graph that combines
from each original type to provide the true overall occam's-razor knowledge
graph of what the code both is and does. 'a = b' would be one triple. so
would be package imports"). Design: `docs/GRAPH_WORKBENCH_DESIGN.md` §3.

A VIEW of the code property graph (`vertiscope/cpg.py`), never a second store:
every triple carries the address it is read at -- the trie's own
`url|/module/.../stmt[n]`, the same the chunks, the CPG and `cpg_mutate`
use -- and, where one exists, the CPG edges it summarises (`cpg`). What the
address already says (containment, straight-line order) is not repeated as
a triple; what it cannot say is:

  DEFINES        a scope defines a name (def, class, assignment target, import alias)
  ASSIGNED_FROM  a = b                      one triple per name read on the right
  IMPORTS        a scope imports a qualified name
  CALLS          a function (or the module) calls a qualified name
  INHERITS       a class has a base
  TAKES          a function's parameter
  RETURNS        a name a function returns
  BRANCHES_ON    a name a branch or loop tests
"""

from __future__ import annotations

import ast
from typing import Dict, List

from .cpg import build_cpg
from .cpg_mutate import _index

PREDICATES = ("DEFINES", "ASSIGNED_FROM", "IMPORTS", "CALLS", "INHERITS", "TAKES", "RETURNS", "BRANCHES_ON")


def _dotted(e) -> str:
    """`os.environ.get` for an attribute chain ending in a name, else ""."""
    parts = []
    while isinstance(e, ast.Attribute):
        parts.append(e.attr)
        e = e.value
    if isinstance(e, ast.Name):
        return ".".join([e.id] + parts[::-1])
    return ""


def _names(node, ctx) -> List[str]:
    """The names a node reads (or writes), each a whole dotted chain once:
    `os.environ.get(key)` reads `os.environ.get` and `key`, not also `os`
    and `os.environ`."""
    out: List[str] = []

    def visit(n):
        if isinstance(n, ast.Attribute):
            d = _dotted(n)
            if d:
                if isinstance(n.ctx, ctx):
                    out.append(d)
                return                                # the chain is one name
        if isinstance(n, ast.Name):
            if isinstance(n.ctx, ctx):
                out.append(n.id)
            return
        for c in ast.iter_child_nodes(n):
            visit(c)

    visit(node)
    return list(dict.fromkeys(out))


def _scope_of(xp: str) -> str:
    """The function, class or module an address sits in."""
    parts = xp.split("/")
    for i in range(len(parts) - 1, 0, -1):
        step = parts[i].split("[")[0]
        if step in ("function", "class", "module"):
            return "/".join(parts[: i + 1])
    return xp


def compact(text: str, url: str, rel_path: str = "", prefix: str = "", qname: str = "") -> Dict:
    """Triples for one module's source. Returns {url, triples, counts}."""
    g = build_cpg(text, url, rel_path, prefix=prefix, qname=qname)
    tree = ast.parse(text)
    idx = _index(tree)
    if prefix:
        idx = {prefix + xp: n for xp, n in idx.items()}
    key = lambda xp: "%s|%s" % (url, xp)
    by_key = {n["key"]: n for n in g["nodes"]}
    # DFG edges by their USE statement and variable, for citations.
    dfg_into: Dict[tuple, List[str]] = {}
    for e in g["edges"]:
        if e["kind"] == "DFG":
            dfg_into.setdefault((e["dst"], e["var"]), []).append("%s->%s" % (e["src"].split("|", 1)[1], e["dst"].split("|", 1)[1]))
    triples: List[Dict] = []

    def add(s, p, o, xp, line, cpg=None):
        triples.append({"s": s, "p": p, "o": o, "at": key(xp), "line": int(line or 0), "cpg": cpg or []})

    name_of = lambda xp: (by_key.get(key(xp)) or {}).get("qname") or (by_key.get(key(xp)) or {}).get("name") or xp

    for xp, node in idx.items():
        scope = _scope_of(xp)
        sname = name_of(scope)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            parent = _scope_of(xp.rsplit("/", 1)[0])
            add(name_of(parent), "DEFINES", node.name, xp, node.lineno)
            if isinstance(node, ast.ClassDef):
                # Every base as written -- a builtin or an unresolved one too;
                # the CPG's INHERITS edge (in-file) is cited where it exists.
                for b in node.bases:
                    bq = _dotted(b) or ast.unparse(b)
                    add(name_of(xp), "INHERITS", bq, xp, node.lineno)
                continue
            for a in node.args.posonlyargs + node.args.args + node.args.kwonlyargs:
                add(name_of(xp), "TAKES", a.arg, xp, node.lineno)
            continue
        if isinstance(node, ast.Module):
            continue
        line = getattr(node, "lineno", 0)
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            base = getattr(node, "module", None) or ""
            for al in node.names:
                q = (base + "." + al.name) if base else al.name
                add(sname, "IMPORTS", q, xp, line)
                add(sname, "DEFINES", (al.asname or al.name).split(".")[0], xp, line)
            continue
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = node.value
            lhs = [n for t in targets for n in _names(t, ast.Store)]
            rhs = _names(value, ast.Load) if value is not None else []
            if isinstance(node, ast.AugAssign):
                rhs = list(dict.fromkeys(lhs + rhs))
            for a in lhs:
                add(sname, "DEFINES", a, xp, line)
                for b in rhs:
                    add(a, "ASSIGNED_FROM", b, xp, line, dfg_into.get((key(xp), b.split(".")[0]), []))
            continue
        if isinstance(node, ast.Return) and node.value is not None:
            for b in _names(node.value, ast.Load):
                add(sname, "RETURNS", b, xp, line)
            continue
        if isinstance(node, (ast.If, ast.While)):
            for b in _names(node.test, ast.Load):
                add(xp.rsplit("/", 1)[-1], "BRANCHES_ON", b, xp, line)
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            for b in _names(node.iter, ast.Load):
                add(xp.rsplit("/", 1)[-1], "BRANCHES_ON", b, xp, line)
            for a in _names(node.target, ast.Store):
                add(sname, "DEFINES", a, xp, line)

    # CALLS and INHERITS as the CPG resolved them: in-file edges, and the
    # qualified names it left for other files (`calls_out`, `bases_out`).
    for e in g["edges"]:
        if e["kind"] == "CALLS":
            s, d = by_key.get(e["src"]), by_key.get(e["dst"])
            if s and d:
                add(s.get("qname") or s["name"], e["kind"], d.get("qname") or d["name"], s["xpath"], e.get("line") or s["line"],
                    ["%s->%s" % (s["xpath"], d["xpath"])])
    for n in g["nodes"]:
        for q in n.get("calls_out") or []:
            add(n.get("qname") or n["name"], "CALLS", q, n["xpath"], n["line"])

    counts = {p: sum(1 for t in triples if t["p"] == p) for p in PREDICATES}
    return {"url": url, "triples": triples, "counts": counts}
