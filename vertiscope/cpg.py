"""The code property graph of a Python file (G-235, PLUGIN_GOAL 164: the AST
"and the two others that accompany" it -- control flow and program
dependence -- with calls and inheritance).

**The AST is the address.** A function is `code://<root>/<path.py>` at
`/module/class/function[2]` -- the xpath `source.tag_source` gives it, in the
trie's canonical spelling (a first child has no `[1]`) (the same walk, the same per-parent ordinals), so a CPG node and the chunk
a reader opens for it are one address. Below a function the address
continues by the code's own syntax: its statements in source order,
`.../function[2]/stmt[3]`, nested blocks counted in the same depth-first
order the CFG walks them.

**What it adds, as typed edges between those addresses** (one store table,
`Cpg`, with a `kind` -- each kind drawn and toggled on its own, `G-241`):

  AST       a scope contains its members (module -> class -> function ->
            statement); the containment the address already spells
  CFG       statement order inside a function: `next`, an `if`'s `true` and
            `false` branches, a loop's `loop` edge back to its header
  DFG       a statement that DEFINES a name -> a later statement that USES
            it (`var` names it); a parameter's definition is the function
  CALLS     a function -> the function or class it calls (`line`)
  INHERITS  a class -> its base class

A call or base in another file is kept as its qualified name
(`calls_out`, `bases_out`) and resolved against whatever the store holds --
now, and again whenever that file is indexed -- the same rule a hyperlink
follows: an edge exists when both ends are pages we hold.

**Not a type-checker.** Callees resolve by name: a local function, an
imported name, `self.method` within its class, `module.attr` for an imported
module. Anything dynamic stays unresolved and is counted, never guessed.
"""

from __future__ import annotations

import ast
from typing import Dict, List, Optional, Tuple

KINDS = ("AST", "CFG", "DFG", "CALLS", "INHERITS")
#: Planted (G-235): the module's own statements are not graphed -- only
#: functions' -- as before 2026-10-18, when a web sample (`pipe =
#: pipeline(...)`, all top level) graphed to an empty module.
_PLANT_NO_MODULE_STMTS = False


def module_qname(rel_path: str) -> str:
    """`vertiscope/source.py` -> `vertiscope.source`; a package's `__init__` -> the package."""
    p = str(rel_path).replace("\\", "/")
    if p.endswith(".py"):
        p = p[:-3]
    parts = [x for x in p.split("/") if x]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


class _Counter:
    """Per-parent, per-kind ordinals, spelled as the TRIE spells an address:
    a first child carries no `[1]` (`/module/class/function[2]`), which is
    the form the chunks are stored under -- so a code node and its chunk are
    one address, not two spellings of it."""

    def __init__(self) -> None:
        self.c: Dict[Tuple[str, str], int] = {}

    def step(self, name: str, parent: str) -> str:
        k = (parent, name)
        self.c[k] = self.c.get(k, 0) + 1
        n = self.c[k]
        return "%s/%s" % (parent, name) if n == 1 else "%s/%s[%d]" % (parent, name, n)


_BLOCKS = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith, ast.Try)


def _names(node, ctx) -> List[str]:
    return sorted({n.id for n in ast.walk(node) if isinstance(n, ast.Name) and isinstance(n.ctx, ctx)})


def _header(node) -> ast.AST:
    """What a compound statement itself evaluates (its test/iter), not its body."""
    if isinstance(node, ast.If) or isinstance(node, ast.While):
        return node.test
    if isinstance(node, (ast.For, ast.AsyncFor)):
        return ast.Tuple(elts=[node.target, node.iter], ctx=ast.Load())
    if isinstance(node, (ast.With, ast.AsyncWith)):
        return ast.Tuple(elts=[i.context_expr for i in node.items], ctx=ast.Load())
    return node


def build_cpg(text: str, url: str, rel_path: str = "", prefix: str = "", qname: str = "") -> Dict:
    """Nodes and edges of one file's CPG. Edges to nodes in THIS file are
    resolved; calls and bases elsewhere are left as qualified names.

    `prefix` puts the module BELOW an address: a web page's code block is
    `<page url>|<the pre's xpath>/module/...` (G-233 -- "addressed below the
    `pre` by its own syntax, as `code://` files are"). `qname` names its
    module when no path does."""
    tree = ast.parse(text)
    mod_q = qname or module_qname(rel_path)
    count = _Counter()
    nodes: List[Dict] = []
    edges: List[Dict] = []
    key = lambda xp: "%s|%s" % (url, xp)

    def node(xp, kind, name, qname, line, end, **extra) -> str:
        nodes.append({"key": key(xp), "url": url, "xpath": xp, "kind": kind, "name": name,
                      "qname": qname, "line": int(line), "end_line": int(end),
                      "calls_out": extra.get("calls_out", []), "bases_out": extra.get("bases_out", [])})
        return key(xp)

    def edge(kind, a, b, **props) -> None:
        edges.append({"kind": kind, "src": a, "dst": b, "var": props.get("var", ""), "line": int(props.get("line", 0)),
                      "label": props.get("label", "")})

    module_xp = count.step("module", prefix)
    module_key = node(module_xp, "module", mod_q.rsplit(".", 1)[-1] if mod_q else "", mod_q, 1, len(text.splitlines()) or 1)

    # Imported names: local alias -> qualified name.
    imported: Dict[str, str] = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                imported[(a.asname or a.name).split(".")[0]] = a.name if a.asname else a.name.split(".")[0]
        elif isinstance(n, ast.ImportFrom):
            base = n.module or ""
            if n.level:
                pkg = mod_q.split(".")
                pkg = pkg[: max(0, len(pkg) - n.level)] if not rel_path.endswith("__init__.py") else pkg[: max(0, len(pkg) - n.level + 1)]
                base = ".".join([*pkg, base] if base else pkg)
            for a in n.names:
                if a.name != "*":
                    imported[a.asname or a.name] = (base + "." + a.name) if base else a.name

    # Symbols, in tag_source's walk order (so the xpaths agree).
    symbols: List[Tuple[ast.AST, str, str, Optional[str]]] = []   # (node, xpath, qname, enclosing class qname)

    def walk(scope, parent_xp, parent_q, parent_key, cls_q):
        for child in getattr(scope, "body", []):
            if isinstance(child, ast.ClassDef):
                kind = "class"
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                kind = "function"
            else:
                continue
            xp = count.step(kind, parent_xp)
            q = "%s.%s" % (parent_q, child.name) if parent_q else child.name
            k = node(xp, kind, child.name, q, child.lineno, getattr(child, "end_lineno", child.lineno))
            edge("AST", parent_key, k)
            symbols.append((child, xp, q, cls_q))
            walk(child, xp, q, k, q if kind == "class" else cls_q)

    walk(tree, module_xp, mod_q, module_key, None)
    local = {q: "%s|%s" % (url, xp) for (_n, xp, q, _c) in symbols}
    by_short = {}
    for (_n, _xp, q, _c) in symbols:
        by_short.setdefault(q.rsplit(".", 1)[-1], q)

    def resolve(expr, cls_q) -> Optional[str]:
        """A callee or base expression -> its qualified name, or None."""
        if isinstance(expr, ast.Name):
            n = expr.id
            if mod_q and ("%s.%s" % (mod_q, n)) in local:
                return "%s.%s" % (mod_q, n)
            if n in imported:
                return imported[n]
            return None
        if isinstance(expr, ast.Attribute):
            if isinstance(expr.value, ast.Name) and expr.value.id in ("self", "cls") and cls_q:
                return "%s.%s" % (cls_q, expr.attr)
            if isinstance(expr.value, ast.Name) and expr.value.id in imported:
                return "%s.%s" % (imported[expr.value.id], expr.attr)
        return None

    unresolved = 0
    # The MODULE is a scope too: its top-level statements are numbered, flow
    # and call like a function's, from the module node -- a web page's sample
    # is mostly top level (G-233/G-235, 2026-10-18).
    scopes = list(symbols)
    if not _PLANT_NO_MODULE_STMTS:
        scopes.append((tree, module_xp, mod_q or "", None))
    for fn, fxp, fq, cls_q in scopes:
        fkey = module_key if fn is tree else local[fq]
        if isinstance(fn, ast.ClassDef):
            outs = []
            for b in fn.bases:
                bq = resolve(b, None)
                if bq and bq in local:
                    edge("INHERITS", fkey, local[bq])
                elif bq:
                    outs.append(bq)
            if outs:
                next(x for x in nodes if x["key"] == fkey)["bases_out"] = outs
            continue
        # Statements (CFG nodes) of this function, depth-first.
        stmt_keys: Dict[int, str] = {}
        order: List[ast.stmt] = []

        def number(body, parent_xp, parent_key):
            for s in body:
                if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    continue                     # its own symbol
                xp = count.step("stmt", parent_xp)
                k = node(xp, "stmt", type(s).__name__, "", s.lineno, getattr(s, "end_lineno", s.lineno))
                edge("AST", parent_key, k)
                stmt_keys[id(s)] = k
                order.append(s)
                for field in ("body", "orelse", "finalbody"):
                    number(getattr(s, field, []) or [], xp, k)
                for h in getattr(s, "handlers", []) or []:
                    number(h.body, xp, k)

        number(fn.body, fxp, fkey)

        def first(body) -> Optional[str]:
            for s in body:
                if id(s) in stmt_keys:
                    return stmt_keys[id(s)]
            return None

        def flow(body, after: Optional[str], loop_head: Optional[str] = None):
            """CFG edges for a statement list; `after` is where it falls through to."""
            items = [s for s in body if id(s) in stmt_keys]
            for i, s in enumerate(items):
                k = stmt_keys[id(s)]
                nxt = stmt_keys[id(items[i + 1])] if i + 1 < len(items) else after
                if isinstance(s, (ast.Return, ast.Raise)):
                    continue
                if isinstance(s, (ast.Break,)):
                    if after:
                        pass                     # leaves the loop: handled by the loop's false edge
                    continue
                if isinstance(s, ast.Continue):
                    if loop_head:
                        edge("CFG", k, loop_head, label="loop")
                    continue
                if isinstance(s, ast.If):
                    t, f = first(s.body), first(s.orelse)
                    if t: edge("CFG", k, t, label="true")
                    if f: edge("CFG", k, f, label="false")
                    elif nxt: edge("CFG", k, nxt, label="false")
                    flow(s.body, nxt, loop_head); flow(s.orelse, nxt, loop_head)
                elif isinstance(s, (ast.For, ast.AsyncFor, ast.While)):
                    t = first(s.body)
                    if t: edge("CFG", k, t, label="true")
                    if nxt: edge("CFG", k, nxt, label="false")
                    flow(s.body, k, k)           # the body's end goes back to the header
                    flow(s.orelse, nxt, loop_head)
                elif isinstance(s, (ast.With, ast.AsyncWith, ast.Try)):
                    t = first(s.body)
                    if t: edge("CFG", k, t, label="next")
                    flow(s.body, nxt if not getattr(s, "finalbody", None) else first(s.finalbody) or nxt, loop_head)
                    for h in getattr(s, "handlers", []) or []:
                        hf = first(h.body)
                        if hf: edge("CFG", k, hf, label="except")
                        flow(h.body, nxt, loop_head)
                    flow(getattr(s, "orelse", []) or [], nxt, loop_head)
                    flow(getattr(s, "finalbody", []) or [], nxt, loop_head)
                elif nxt:
                    edge("CFG", k, nxt, label="loop" if nxt == loop_head else "next")

        entry = first(fn.body)
        if entry:
            edge("CFG", fkey, entry, label="entry")
        flow(fn.body, None)

        # DFG: each use from the latest preceding definition (document order),
        # a parameter's from the function itself.
        params = set()
        if fn is not tree:
            params = {a.arg for a in (fn.args.posonlyargs + fn.args.args + fn.args.kwonlyargs)}
            if fn.args.vararg: params.add(fn.args.vararg.arg)
            if fn.args.kwarg: params.add(fn.args.kwarg.arg)
        last_def: Dict[str, str] = {p: fkey for p in params}
        for s in order:
            k = stmt_keys[id(s)]
            h = _header(s) if isinstance(s, _BLOCKS) else s
            for v in _names(h, ast.Load):
                if v in last_def and last_def[v] != k:
                    edge("DFG", last_def[v], k, var=v)
            for v in _names(h, ast.Store):
                last_def[v] = k
            if isinstance(s, (ast.For, ast.AsyncFor)):
                for v in _names(s.target, ast.Store):
                    last_def[v] = k
            if isinstance(s, (ast.Import, ast.ImportFrom)):     # an import defines its names
                for al in s.names:
                    if al.name != "*":
                        last_def[(al.asname or al.name).split(".")[0]] = k

        # CALLS, from the function (the node a reader opens), with the line.
        outs = []
        seen = set()
        # The module's calls are its own statements', not its functions'.
        walked = ast.walk(fn) if fn is not tree else (x for s in order for x in ast.walk(s))
        for n in walked:
            if not isinstance(n, ast.Call):
                continue
            q = resolve(n.func, cls_q)
            if not q:
                unresolved += 1
                continue
            if q in local and (fkey, local[q]) not in seen:
                seen.add((fkey, local[q]))
                edge("CALLS", fkey, local[q], line=n.lineno)
            elif q not in local:
                outs.append(q)
        if outs:
            next(x for x in nodes if x["key"] == fkey)["calls_out"] = sorted(set(outs))

    stats = {k: sum(1 for e in edges if e["kind"] == k) for k in KINDS}
    stats.update(nodes=len(nodes), unresolved_calls=unresolved,
                 calls_elsewhere=sum(len(n["calls_out"]) for n in nodes),
                 bases_elsewhere=sum(len(n["bases_out"]) for n in nodes))
    return {"url": url, "module": mod_q, "nodes": nodes, "edges": edges, "stats": stats}
