"""A change to code expressed as a mutation of its property graph, compiled
back to source as a unified diff (G-236, PLUGIN_GOAL 165: "ADD_NODE /
ADD_EDGE / DELETE_* / MODIFY_PROPERTY, compiled back to source with `ast` and
`difflib`, compile-checked, and applied as a unified diff").

Every mutation names its target by the CPG's own address -- the trie's
canonical xpath of a module, class, function or statement
(`/module/class/function[2]/stmt[3]`, `vertiscope/cpg.py`) -- so a change is
stated in the same terms the graph, the chunks and the 3D view use.

Ops:
  ADD_NODE         {parent, code, after?}      code inserted into a scope's
                                               body (after a sibling, or at
                                               its end)
  DELETE_NODE      {xpath}                     a class, function or statement
                                               removed (a body left empty
                                               gets `pass`)
  MODIFY_PROPERTY  {xpath, property, value}    `name` (def/class renamed),
                                               `docstring` (set or replaced),
                                               `code` (a statement replaced)
  ADD_EDGE         {kind: CALLS, src, call}    a call statement appended to a
                                               function (before a final
                                               `return`)
                   {kind: INHERITS, src, base} a base added to a class
  DELETE_EDGE      {kind: CALLS, src, name}    expression statements in `src`
                                               calling `name` removed
                   {kind: INHERITS, src, base} a base removed

Edits are made on the source LINES at the nodes' positions, never by
regenerating the module with `ast.unparse`, so comments and formatting
outside the edit survive. The result must compile; it is returned with its
unified diff, and nothing is written here (`apply` is the caller's).
"""

from __future__ import annotations

import ast
import difflib
import textwrap
from typing import Dict, List, Optional, Tuple


class MutationError(ValueError):
    pass


def _index(tree: ast.Module) -> Dict[str, ast.AST]:
    """xpath -> node, by the walk `cpg.build_cpg` numbers with (canonical)."""
    counts: Dict[Tuple[str, str], int] = {}

    def step(name: str, parent: str) -> str:
        k = (parent, name)
        counts[k] = counts.get(k, 0) + 1
        n = counts[k]
        return "%s/%s" % (parent, name) if n == 1 else "%s/%s[%d]" % (parent, name, n)

    out: Dict[str, ast.AST] = {}
    mod = step("module", "")
    out[mod] = tree
    symbols = []

    def walk(scope, parent_xp):
        for child in getattr(scope, "body", []):
            if isinstance(child, ast.ClassDef):
                kind = "class"
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                kind = "function"
            else:
                continue
            xp = step(kind, parent_xp)
            out[xp] = child
            symbols.append((child, xp))
            walk(child, xp)

    walk(tree, mod)

    def number(body, parent_xp):
        for s in body:
            if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            xp = step("stmt", parent_xp)
            out[xp] = s
            for field in ("body", "orelse", "finalbody"):
                number(getattr(s, field, []) or [], xp)
            for h in getattr(s, "handlers", []) or []:
                number(h.body, xp)

    for node, xp in symbols:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            number(node.body, xp)
    number(tree.body, mod)                    # the module's own statements, numbered last (as `build_cpg`)
    return out


def _span(node) -> Tuple[int, int]:
    """0-based first and last line of a node, decorators included."""
    first = min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])]) - 1
    return first, node.end_lineno - 1


def _indent_of(lines: List[str], row: int) -> str:
    line = lines[row]
    return line[: len(line) - len(line.lstrip())]


def _body_indent(lines: List[str], scope) -> str:
    body = [b for b in getattr(scope, "body", [])]
    if body:
        return _indent_of(lines, body[0].lineno - 1)
    return _indent_of(lines, scope.lineno - 1) + "    "


def _block(code: str, indent: str) -> List[str]:
    code = textwrap.dedent(code).strip("\n")
    return [(indent + l) if l.strip() else "" for l in code.split("\n")]


def mutate(text: str, mutations: List[Dict], rel_path: str = "module.py") -> Dict:
    """Apply `mutations` in order; return {text, diff, applied}. Raises
    MutationError on an unknown address or op, or if the result does not
    compile."""
    cur = text
    applied = []
    for m in mutations:
        cur = _apply_one(cur, m)
        applied.append(m.get("op"))
    try:
        compile(cur, rel_path, "exec")
    except SyntaxError as exc:
        raise MutationError("the mutated module does not compile: %s (line %s)" % (exc.msg, exc.lineno))
    diff = "".join(difflib.unified_diff(text.splitlines(True), cur.splitlines(True),
                                        fromfile="a/" + rel_path, tofile="b/" + rel_path))
    return {"text": cur, "diff": diff, "applied": applied, "changed": cur != text}


def _apply_one(text: str, m: Dict) -> str:
    tree = ast.parse(text)
    idx = _index(tree)
    lines = text.split("\n")
    op = m.get("op")

    def node(xp):
        n = idx.get(xp)
        if n is None:
            raise MutationError("no node at %s" % xp)
        return n

    if op == "ADD_NODE":
        scope = node(m["parent"])
        if m.get("after"):
            sib = node(m["after"])
            row = _span(sib)[1] + 1
            indent = _indent_of(lines, sib.lineno - 1)
        else:
            indent = _body_indent(lines, scope)
            row = (scope.end_lineno if scope is not tree else len(lines))
        block = _block(m["code"], indent)
        if indent == "" and row > 0 and lines[row - 1].strip():
            block = [""] + block
        return "\n".join(lines[:row] + block + lines[row:])

    if op == "DELETE_NODE":
        n = node(m["xpath"])
        if n is tree:
            raise MutationError("the module itself is not deleted by a mutation")
        a, b = _span(n)
        parent = next((p for p in ast.walk(tree) for f in ("body", "orelse", "finalbody")
                       if n in (getattr(p, f, None) or [])), None)
        out = lines[:a] + lines[b + 1:]
        siblings = [s for f in ("body", "orelse", "finalbody") for s in (getattr(parent, f, None) or []) if n in (getattr(parent, f, None) or [])]
        if parent is not None and len(siblings) == 1 and parent is not tree:
            out = lines[:a] + [_indent_of(lines, n.lineno - 1) + "pass"] + lines[b + 1:]
        return "\n".join(out)

    if op == "MODIFY_PROPERTY":
        n = node(m["xpath"]); prop = m.get("property"); val = m.get("value", "")
        if prop == "name":
            if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                raise MutationError("only a def or class has a name")
            row = n.lineno - 1
            kw = "class" if isinstance(n, ast.ClassDef) else ("async def" if isinstance(n, ast.AsyncFunctionDef) else "def")
            old = "%s %s" % (kw, n.name)
            if old not in lines[row]:
                raise MutationError("cannot find %r on line %d" % (old, row + 1))
            lines[row] = lines[row].replace(old, "%s %s" % (kw, val), 1)
            return "\n".join(lines)
        if prop == "docstring":
            if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
                raise MutationError("only a module, class or def has a docstring")
            body = n.body
            indent = _body_indent(lines, n) if n is not tree else ""
            new = _block('"""%s"""' % val.replace('"""', '\\"\\"\\"'), indent)
            if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) \
                    and isinstance(body[0].value.value, str):
                a, b = body[0].lineno - 1, body[0].end_lineno - 1
                return "\n".join(lines[:a] + new + lines[b + 1:])
            row = (body[0].lineno - 1) if body else len(lines)
            return "\n".join(lines[:row] + new + lines[row:])
        if prop == "code":
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
                raise MutationError("`code` replaces a statement; a scope is changed by its statements")
            a, b = _span(n)
            return "\n".join(lines[:a] + _block(val, _indent_of(lines, n.lineno - 1)) + lines[b + 1:])
        raise MutationError("unknown property %r" % prop)

    if op in ("ADD_EDGE", "DELETE_EDGE"):
        kind = m.get("kind")
        src = node(m["src"])
        if kind == "CALLS":
            if not isinstance(src, (ast.FunctionDef, ast.AsyncFunctionDef)):
                raise MutationError("a CALLS edge leaves a function")
            if op == "ADD_EDGE":
                body = src.body
                last = body[-1]
                indent = _indent_of(lines, last.lineno - 1)
                call = m["call"].strip()
                if isinstance(last, ast.Return):
                    row = _span(last)[0]
                else:
                    row = _span(last)[1] + 1
                return "\n".join(lines[:row] + [indent + call] + lines[row:])
            name = m["name"]
            doomed = []
            for s in ast.walk(src):
                if isinstance(s, ast.Expr) and isinstance(s.value, ast.Call):
                    f = s.value.func
                    callee = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else "")
                    if callee == name:
                        doomed.append(_span(s))
            if not doomed:
                raise MutationError("no call to %r in %s" % (name, m["src"]))
            keep = [l for i, l in enumerate(lines) if not any(a <= i <= b for a, b in doomed)]
            out = "\n".join(keep)
            try:
                ast.parse(out)
            except SyntaxError:                      # the body was only those calls
                rows = sorted(doomed)
                a0 = rows[0][0]
                indent = _indent_of(lines, a0)
                keep = lines[:a0] + [indent + "pass"] + [l for i, l in enumerate(lines) if i > a0 and not any(a <= i <= b for a, b in doomed)]
                out = "\n".join(keep)
            return out
        if kind == "INHERITS":
            if not isinstance(src, ast.ClassDef):
                raise MutationError("an INHERITS edge leaves a class")
            bases = [ast.get_source_segment(text, b) for b in src.bases]
            if op == "ADD_EDGE":
                bases.append(m["base"])
            else:
                if m["base"] not in bases:
                    raise MutationError("%s has no base %r" % (m["src"], m["base"]))
                bases.remove(m["base"])
            row = src.lineno - 1
            line = lines[row]
            head = "class %s" % src.name
            i = line.index(head) + len(head)
            j = line.index(":", i)
            lines[row] = line[:i] + ("(%s)" % ", ".join(bases) if bases else "") + line[j:]
            return "\n".join(lines)
        raise MutationError("unknown edge kind %r" % kind)

    raise MutationError("unknown op %r" % op)
