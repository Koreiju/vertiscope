"""Black-box containment, unfoldable recursively (PLUGIN_GOAL 80, 2026-11-01:
"adaptive black-box recursively unfoldable containment on references, good for
unnesting complex and high-level code modules"; mortegon UR M.3: "when these
tokens are right clicked ... they compile the next level of recursive syntax
tree").

A `{ref}` naming a code artifact -- `code://repo/core/chunk_builder.py`, or one
of its definitions, `code://repo/core/chunk_builder.py#ChunkBuilder.build` -- is
a BLACK BOX: unfolded, it shows its rank-1 contents only, each again a `{ref}`
that unfolds the same way. A module's rank 1 is its top-level classes and
functions; a class's, its methods; a function's, its signature and the first
line of its docstring (a leaf: nothing below it is a definition).

The address is Python's own tree, as `domvec/source.py` addresses a source
file (the module path, then the qualified name).
"""
import ast
from typing import Dict, List, Optional

#: Planted (item 80): the box opens flat -- every definition at once, no ranks.
PLANT_FLAT = [False]

_DEF = (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


def _defs(body) -> List[ast.AST]:
    return [n for n in body if isinstance(n, _DEF)]


def _find(tree: ast.Module, qual: str) -> Optional[ast.AST]:
    node: ast.AST = tree
    for part in [p for p in qual.split(".") if p]:
        nxt = next((d for d in _defs(getattr(node, "body", [])) if d.name == part), None)
        if nxt is None:
            return None
        node = nxt
    return node


def _sig(fn) -> str:
    try:
        return fn.name + "(" + ast.unparse(fn.args) + ")"
    except Exception:                               # noqa: BLE001
        return fn.name + "(...)"


def unfold(url: str, source: str) -> Optional[Dict]:
    """The box at `url` (a `code://` module, `#qualname` for a definition in
    it): `{kind, qual, lines}` -- its rank-1 contents, each a `{ref}` line."""
    base, _, qual = url.partition("#")
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    node = _find(tree, qual) if qual else tree
    if node is None:
        return None
    kind = "module" if node is tree else ("class" if isinstance(node, ast.ClassDef) else "function")
    tab = "\t"
    lines: List[str] = []
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        lines.append("signature" + tab + _sig(node))
        doc = ast.get_docstring(node) or ""
        if doc:
            lines.append("doc" + tab + doc.strip().splitlines()[0][:120])
    if PLANT_FLAT[0]:
        kids = [n for n in ast.walk(node) if isinstance(n, _DEF) and n is not node]
    else:
        kids = _defs(getattr(node, "body", []))
    for d in kids:
        q = d.name if PLANT_FLAT[0] else (qual + "." if qual else "") + d.name
        what = "class" if isinstance(d, ast.ClassDef) else "def"
        lines.append("%s %s%s{%s#%s}" % (what, d.name, tab, base, q))
    return {"kind": kind, "qual": qual, "lines": lines}
