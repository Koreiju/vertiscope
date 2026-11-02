"""The code graph web (PLUGIN_GOAL 93-95; RESERVOIR_DESIGN 11.4).

"perhaps here is where some additional retrieval structures like pagerank on a
global library ast and so on may be the right extension of graph
representations to our retrieval schemes situated within their syntaxes and
structures of abstraction that are both named string subtypes and adjacency
based graph structures. we might extend the ast to include perhaps cst's
(https://pypi.org/project/libcst/) too/instead" (2026-11-01).

A graph over the repository's Python, read through libcst's CONCRETE syntax
tree (comments and layout kept; installed on the reader's approval, PLUGIN_GOAL
102), the stdlib AST when a file will not parse that way:

* nodes -- every definition, by its dotted qualified name: modules
  (``domvec.search``), classes (``domvec.search.ThreeFormIndex``), functions
  and methods (``domvec.search.ThreeFormIndex.search``);
* edges -- ``contains`` (module -> class -> method), ``inherits`` (class ->
  base), ``calls`` (function -> a called name that is a definition here),
  ``imports`` (module -> module); names resolved within the repository, by
  their last segment when the import path is not followed (a call graph over
  NAMED STRING SUBTYPES joined to the ADJACENCY of the tree);
* PageRank over it -- a definition is central when central definitions call,
  inherit from, contain or import it.

Cached per file by its modification time: a rebuild re-reads only what changed.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

#: Method names every builtin container or string has: a call `x.items()`
#: says nothing about WHICH definition it reaches, and linking it to the one
#: repo method that happens to share the name ranked `items`, `set`, `values`
#: first (measured 2026-11-02). Such attribute calls link nothing.
BUILTIN_ATTRS = set()
for _t in (dict, list, str, set, bytes, object, tuple, int, float, frozenset):
    BUILTIN_ATTRS.update(n for n in dir(_t) if not n.startswith("__"))
BUILTIN_ATTRS.update({"open", "read", "write", "close", "get", "run", "start", "stop", "send", "load", "dump", "dumps", "loads"})
import builtins as _builtins
#: A plain call to a builtin (`set(...)`, `len(...)`) reaches no definition here.
BUILTIN_NAMES = set(dir(_builtins))


def _call_key(func_is_attr: bool, receiver: str, name: str) -> str:
    """How a call is kept: `self.x` for a method on the same class, the bare
    name for a plain call, nothing for a library attribute or a builtin."""
    if func_is_attr:
        return ("self." + name) if receiver in ("self", "cls") else ""
    return "" if name in BUILTIN_NAMES else name


def _module_name(root: Path, path: Path) -> str:
    rel = path.relative_to(root).with_suffix("")
    parts = list(rel.parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join([root.name] + parts) if parts else root.name


def _read_cst(src: str):
    """(definitions, imports) from libcst: definitions as (qual, kind, bases,
    calls), qual relative to the module."""
    import libcst as cst

    tree = cst.parse_module(src)
    defs: List[Tuple[str, str, List[str], List[str]]] = []
    imports: List[str] = []

    def name_of(expr) -> str:
        if isinstance(expr, cst.Name):
            return expr.value
        if isinstance(expr, cst.Attribute):
            return expr.attr.value
        return ""

    class Calls(cst.CSTVisitor):
        def __init__(self) -> None:
            self.names: List[str] = []

        def visit_Call(self, node: cst.Call) -> None:
            n = name_of(node.func)
            attr = isinstance(node.func, cst.Attribute)
            k = _call_key(attr, name_of(node.func.value) if attr else "", n) if n else ""
            if k:
                self.names.append(k)

    def walk(body, prefix: str) -> None:
        for st in body:
            if isinstance(st, cst.ClassDef):
                q = prefix + st.name.value
                bases = [name_of(a.value) for a in st.bases if name_of(a.value)]
                defs.append((q, "class", bases, []))
                walk(st.body.body, q + ".")
            elif isinstance(st, cst.FunctionDef):
                q = prefix + st.name.value
                v = Calls()
                st.body.visit(v)
                defs.append((q, "method" if "." in q else "function", [], v.names))
                walk(st.body.body if hasattr(st.body, "body") else [], q + ".")
            elif isinstance(st, cst.SimpleStatementLine):
                for small in st.body:
                    if isinstance(small, cst.Import):
                        for a in small.names:
                            imports.append(cst.Module([]).code_for_node(a.name))
                    elif isinstance(small, cst.ImportFrom):
                        dots = "." * len(small.relative)
                        mod = cst.Module([]).code_for_node(small.module) if small.module is not None else ""
                        imports.append(dots + mod)
            elif hasattr(st, "body") and hasattr(st.body, "body"):
                walk(st.body.body, prefix)            # if / try / with: their defs count

    walk(tree.body, "")
    return defs, imports


def _read_ast(src: str):
    """The same, from the stdlib AST (a file libcst will not parse)."""
    tree = ast.parse(src)
    defs: List[Tuple[str, str, List[str], List[str]]] = []
    imports: List[str] = []

    def nm(e) -> str:
        return e.id if isinstance(e, ast.Name) else (e.attr if isinstance(e, ast.Attribute) else "")

    def walk(body, prefix: str) -> None:
        for st in body:
            if isinstance(st, ast.ClassDef):
                q = prefix + st.name
                defs.append((q, "class", [nm(b) for b in st.bases if nm(b)], []))
                walk(st.body, q + ".")
            elif isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef)):
                q = prefix + st.name
                calls = [k for k in (_call_key(isinstance(n.func, ast.Attribute),
                                               nm(n.func.value) if isinstance(n.func, ast.Attribute) else "",
                                               nm(n.func))
                                     for n in ast.walk(st) if isinstance(n, ast.Call) and nm(n.func)) if k]
                defs.append((q, "method" if "." in q else "function", [], calls))
                walk(st.body, q + ".")
            elif isinstance(st, ast.Import):
                imports.extend(a.name for a in st.names)
            elif isinstance(st, ast.ImportFrom):
                imports.append("." * (st.level or 0) + (st.module or ""))

    walk(tree.body, "")
    return defs, imports


class CodeGraph:
    """The repository's definitions, their links, their PageRank."""

    def __init__(self, root: Path, cache: Optional[Path] = None) -> None:
        self.root = Path(root)
        self.cache = cache
        self.kind: Dict[str, str] = {}
        self.edges: List[Tuple[str, str, str]] = []
        self.rank: Dict[str, float] = {}
        self.stats = {"files": 0, "reread": 0, "cst": 0, "ast": 0, "failed": 0, "nodes": 0, "edges": 0}

    def build(self) -> "CodeGraph":
        cached = {}
        if self.cache and self.cache.exists():
            try:
                cached = json.loads(self.cache.read_text(encoding="utf-8"))
            except Exception:                           # noqa: BLE001 -- rebuilt
                cached = {}
        files = {}
        for path in sorted(self.root.rglob("*.py")):
            if any(p in ("__pycache__", "node_modules") for p in path.parts):
                continue
            key = str(path.relative_to(self.root))
            mtime = path.stat().st_mtime
            hit = cached.get(key)
            if hit and hit.get("mtime") == mtime:
                files[key] = hit
                continue
            self.stats["reread"] += 1
            src = path.read_text(encoding="utf-8", errors="replace")
            try:
                defs, imports = _read_cst(src)
                self.stats["cst"] += 1
            except Exception:                           # noqa: BLE001 -- the AST then
                try:
                    defs, imports = _read_ast(src)
                    self.stats["ast"] += 1
                except SyntaxError:
                    self.stats["failed"] += 1
                    continue
            files[key] = {"mtime": mtime, "module": _module_name(self.root, path), "defs": defs, "imports": imports}
        self.stats["files"] = len(files)
        if self.cache:
            try:
                self.cache.write_text(json.dumps(files), encoding="utf-8")
            except OSError:
                pass
        # Nodes and the name index (a name's last segment -> its definitions).
        by_last: Dict[str, List[str]] = {}
        modules = {f["module"] for f in files.values()}
        for f in files.values():
            m = f["module"]
            self.kind[m] = "module"
            for q, kind, _, _ in f["defs"]:
                full = m + "." + q
                self.kind[full] = kind
                by_last.setdefault(q.rsplit(".", 1)[-1], []).append(full)
        for f in files.values():
            m = f["module"]
            for q, kind, bases, calls in f["defs"]:
                full = m + "." + q
                parent = full.rsplit(".", 1)[0]
                self.edges.append((parent, full, "contains"))
                for b in bases:
                    for t in by_last.get(b, [])[:3]:
                        if self.kind.get(t) == "class":
                            self.edges.append((full, t, "inherits"))
                for c in set(calls):
                    if c.startswith("self."):
                        # A method on the same class (the method's parent).
                        t = parent + "." + c[5:]
                        targets = [t] if t in self.kind else []
                    else:
                        same = [t for t in by_last.get(c, []) if t.startswith(m + ".") and t.count(".") == m.count(".") + 1]
                        targets = same or by_last.get(c, [])
                    if 0 < len(targets) <= 3:          # an ambiguous common name links nothing
                        for t in targets:
                            if t != full:
                                self.edges.append((full, t, "calls"))
            for imp in f["imports"]:
                if imp.startswith("."):
                    # Relative to the importing module's package.
                    dots = len(imp) - len(imp.lstrip("."))
                    pkg = m.split(".")
                    is_pkg = any(k.endswith("__init__.py") and v is f for k, v in files.items())
                    base = pkg if is_pkg else pkg[:-1]
                    base = base[: len(base) - (dots - 1)] if dots > 1 else base
                    rest = imp.lstrip(".")
                    imp = ".".join(base + ([rest] if rest else []))
                if imp in modules and imp != m:
                    self.edges.append((m, imp, "imports"))
        self.stats["nodes"] = len(self.kind)
        self.stats["edges"] = len(self.edges)
        self._pagerank()
        return self

    def _pagerank(self, d: float = 0.85, iters: int = 60) -> None:
        names = list(self.kind)
        at = {n: i for i, n in enumerate(names)}
        n = len(names)
        if not n:
            return
        out_deg = np.zeros(n)
        src, dst = [], []
        for a, b, _ in self.edges:
            if a in at and b in at:
                src.append(at[a]); dst.append(at[b]); out_deg[at[a]] += 1
        src_a, dst_a = np.array(src, dtype=np.int64), np.array(dst, dtype=np.int64)
        r = np.full(n, 1.0 / n)
        for _ in range(iters):
            nxt = np.full(n, (1 - d) / n)
            if len(src_a):
                np.add.at(nxt, dst_a, d * r[src_a] / np.maximum(out_deg[src_a], 1))
            nxt += d * r[out_deg == 0].sum() / n        # dangling definitions
            r = nxt
        order = np.argsort(np.argsort(r))
        pct = order / max(1, n - 1)
        self.rank = {names[i]: float(pct[i]) for i in range(n)}

    def percentile(self, name: str) -> float:
        return self.rank.get(name, 0.0)

    def module_of_url(self, url: str) -> str:
        """`code://repo/core/chunk_builder.py` -> `domvec.core.chunk_builder`."""
        if not url.startswith("code://repo/"):
            return ""
        rel = url[len("code://repo/"):].split("#", 1)[0]
        rel = rel[:-3] if rel.endswith(".py") else rel
        rel = rel[:-9] if rel.endswith("/__init__") else rel
        return ".".join([self.root.name] + [p for p in rel.split("/") if p])

    def neighbours(self, name: str) -> List[Tuple[str, str]]:
        return [(b, k) for a, b, k in self.edges if a == name] + [(a, k) for a, b, k in self.edges if b == name]
