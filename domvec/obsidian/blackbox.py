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
import re
from pathlib import Path
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


#: Planted (item 100): the box opens untyped -- no `name: Type` rows.
PLANT_UNTYPED = [False]


def _un(node) -> str:
    try:
        return ast.unparse(node) if node is not None else ""
    except Exception:                               # noqa: BLE001
        return ""


def _params(fn):
    """(name, annotation, default) per parameter, in order."""
    a = fn.args
    pos = list(a.posonlyargs) + list(a.args)
    defaults = [None] * (len(pos) - len(a.defaults)) + list(a.defaults)
    out = [(p.arg, _un(p.annotation), _un(d) if d is not None else "") for p, d in zip(pos, defaults)]
    if a.vararg:
        out.append(("*" + a.vararg.arg, _un(a.vararg.annotation), ""))
    for p, d in zip(a.kwonlyargs, a.kw_defaults):
        out.append((p.arg, _un(p.annotation), _un(d) if d is not None else ""))
    if a.kwarg:
        out.append(("**" + a.kwarg.arg, _un(a.kwarg.annotation), ""))
    return out


def _sig(fn) -> str:
    try:
        return fn.name + "(" + ast.unparse(fn.args) + ")"
    except Exception:                               # noqa: BLE001
        return fn.name + "(...)"


#: Planted (item 112): a module's imports are not boxes -- the unnesting stops
#: at the module's own definitions, as before.
PLANT_NO_IMPORTS = [False]

_REPO = Path(__file__).resolve().parents[1]


def _module_of(url: str) -> str:
    """The dotted module a `code://` url addresses ('' when it is not one)."""
    if url.startswith("code://repo/"):
        rel = url[len("code://repo/"):]
        return "domvec." + re.sub(r"(/__init__)?\.py$", "", rel).replace("/", ".")
    if url.startswith("code://pypi/"):
        rel = url[len("code://pypi/"):]
        return re.sub(r"(/__init__)?\.py$", "", rel).replace("/", ".")
    return ""


def _is_package(url: str) -> bool:
    return url.endswith("/__init__.py")


def module_url(name: str) -> Optional[str]:
    """Where a dotted module's SOURCE is, as a box address -- found the way
    Python would find it, without importing it (an import runs the package):
    the top-level spec, then the package's own directories down. `None` for a
    compiled base module, which has no source to unnest."""
    if not name:
        return None
    parts = name.split(".")
    if parts[0] == "domvec":
        rel = Path(*parts[1:]) if len(parts) > 1 else Path()
        for cand in (_REPO / rel / "__init__.py", _REPO / (str(rel) + ".py")):
            if cand.is_file():
                return "code://repo/" + cand.relative_to(_REPO).as_posix()
        return None
    import importlib.util
    try:
        spec = importlib.util.find_spec(parts[0])
    except (ImportError, ValueError):
        return None
    if spec is None or not spec.origin or not spec.origin.endswith(".py"):
        return None
    origin = Path(spec.origin)
    if spec.submodule_search_locations:
        pkg = origin.parent
        root = pkg.parent
        here = pkg
        for p in parts[1:]:
            if (here / p / "__init__.py").is_file():
                here = here / p
            elif (here / (p + ".py")).is_file():
                return "code://pypi/" + (here / (p + ".py")).relative_to(root).as_posix()
            else:
                return None
        return "code://pypi/" + (here / "__init__.py").relative_to(root).as_posix()
    return "code://pypi/" + origin.name if len(parts) == 1 else None


def _resolve_from(base_url: str, level: int, module: str) -> str:
    """`from .x import y` in the module at `base_url`: the absolute name."""
    if not level:
        return module or ""
    me = _module_of(base_url).split(".")
    pkg = me if _is_package(base_url) else me[:-1]
    up = pkg[:len(pkg) - (level - 1)] if level > 1 else pkg
    return ".".join([*up, module] if module else up)


def _import_rows(tree: ast.Module, base_url: str) -> List[str]:
    """One row per import: the imported name, and the box it unnests to --
    a module's, or a definition's inside it -- or `(compiled)` for a base
    module with no source (the bottom of the unnesting)."""
    tab = "\t"
    rows: List[str] = []
    seen = set()
    for st in tree.body:
        if isinstance(st, ast.Import):
            for a in st.names:
                if a.name in seen:
                    continue
                seen.add(a.name)
                u = module_url(a.name)
                rows.append("import %s%s%s" % (a.name, tab, "{" + u + "}" if u else "(compiled)"))
        elif isinstance(st, ast.ImportFrom):
            mod = _resolve_from(base_url, st.level or 0, st.module or "")
            for a in st.names:
                if a.name == "*":
                    continue
                key = mod + ":" + a.name
                if key in seen:
                    continue
                seen.add(key)
                sub = module_url(mod + "." + a.name) if mod else None
                if sub:
                    rows.append("from %s import %s%s{%s}" % (mod, a.name, tab, sub))
                    continue
                u = module_url(mod)
                rows.append("from %s import %s%s%s" % (mod, a.name, tab, "{" + u + "#" + a.name + "}" if u else "(compiled)"))
    return rows


def unfold_source(base: str, source: str) -> Optional[Dict]:
    """A few lines that are no module on disk -- a notebook cell (item 112's
    "mini-artifacts from a few lines"): its imports as boxes, its definitions
    as typed rows."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    lines: List[str] = []
    if not PLANT_NO_IMPORTS[0]:
        lines.extend(_import_rows(tree, base))
    for d in _defs(tree.body):
        if isinstance(d, ast.ClassDef):
            lines.append("class %s%s%s" % (d.name, chr(9), ", ".join("super: " + (_un(b) or "?") for b in d.bases)))
        else:
            lines.append("def %s%s%s -> %s" % (d.name, chr(9), _sig(d), _un(d.returns) or "?"))
    return {"kind": "cell", "qual": "", "lines": lines}


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
    # A MODULE's imports are boxes too (item 112): each unnests into the
    # library module it names, whose imports unnest the same way, down to the
    # compiled base modules that have no source.
    if node is tree and not PLANT_NO_IMPORTS[0]:
        lines.extend(_import_rows(tree, base))
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        lines.append("signature" + tab + _sig(node))
        # The TYPED panel form (mortegon DM 9.6.1, M.3; PLUGIN_GOAL 100): one
        # row per input, `name: Type = default`, and the output's type --
        # annotations top-down; an unannotated slot says so (`?`), to be
        # inferred bottom-up from what flows through it (mortegon E.6, O.15).
        if not PLANT_UNTYPED[0]:
            for name, ann, default in _params(node):
                if name in ("self", "cls"):
                    continue
                lines.append("%s: %s%s" % (name, ann or "?", (" = " + default) if default else ""))
            lines.append("return: " + (_un(node.returns) or "?"))
        doc = ast.get_docstring(node) or ""
        if doc:
            lines.append("doc" + tab + doc.strip().splitlines()[0][:120])
    elif isinstance(node, ast.ClassDef) and not PLANT_UNTYPED[0]:
        for b in node.bases:
            lines.append("super: " + (_un(b) or "?"))
        for st in node.body:
            if isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name):
                lines.append("%s: %s%s" % (st.target.id, _un(st.annotation) or "?",
                                           (" = " + (_un(st.value) or "")[:40]) if st.value is not None else ""))
    if PLANT_FLAT[0]:
        kids = [n for n in ast.walk(node) if isinstance(n, _DEF) and n is not node]
    else:
        kids = _defs(getattr(node, "body", []))
    for d in kids:
        q = d.name if PLANT_FLAT[0] else (qual + "." if qual else "") + d.name
        what = "class" if isinstance(d, ast.ClassDef) else "def"
        lines.append("%s %s%s{%s#%s}" % (what, d.name, tab, base, q))
    return {"kind": kind, "qual": qual, "lines": lines}
