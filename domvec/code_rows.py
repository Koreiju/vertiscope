"""A regular code artifact as typed rows, and a row edit written back (G-378).

PLUGIN_GOAL 167 c: a REGULAR code artifact "would have the full capabilities
of exploring and graph editing"; a TOOL PANEL is read-only (`tool_panels.py`).
Mortegon M.2-M.5 (spec §11b): "Python programs enter BOTH faces as trees of
typed rows" -- the panel form is `name: Type = {ref}` rows (M.3).

`rows(source)` reads a python cell's module-level bindings as rows: name,
annotation, value, the names the value reads, and the 1-based line. A class
or a function is a row whose value is its kind, with its own rows beneath
(`children`) -- the class unfolds into its fields (M.4).

`set_value`, `set_type` and `rename` write an edit made on a row back into
the source with LibCST, which reprints everything it did not touch exactly:
comments, blank lines, quotes, spacing. A rename rewrites every READ of the
name at module level too, so the cell still means the same thing.

In trie terms: a python cell is a fence in a `vault://` page; a row is
addressable as that cell plus the binding's name, and an edit is a write to
the note's text, which re-indexes the page as any edit does.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Set

import libcst as cst
from libcst.metadata import MetadataWrapper, PositionProvider

#: Planted: write-back through `ast.unparse` instead of LibCST -- comments and
#: formatting are lost, which the round-trip tests must catch.
PLANT_AST_UNPARSE = [False]


@dataclass
class Row:
    name: str
    type: str = ""
    value: str = ""
    reads: List[str] = field(default_factory=list)
    line: int = 0
    kind: str = "value"          # "value" | "function" | "class"
    children: List["Row"] = field(default_factory=list)

    def to_json(self) -> dict:
        return {"name": self.name, "type": self.type, "value": self.value, "reads": self.reads,
                "line": self.line, "kind": self.kind, "children": [c.to_json() for c in self.children]}


def _code(node: cst.CSTNode) -> str:
    return cst.Module(body=[]).code_for_node(node)


def _reads(node: Optional[cst.CSTNode]) -> List[str]:
    if node is None:
        return []
    out: Set[str] = set()

    class V(cst.CSTVisitor):
        def visit_Name(self, n: cst.Name) -> None:
            out.add(n.value)

        def visit_Attribute(self, n: cst.Attribute) -> bool:
            n.value.visit(self)              # `a.b` reads `a`, not `b`
            return False

        def visit_Arg(self, n: cst.Arg) -> bool:
            n.value.visit(self)              # `f(k=v)` reads `v`, not the keyword `k`
            return False

    node.visit(V())
    return sorted(out)


def _rows_of(body, pos) -> List[Row]:
    rows: List[Row] = []
    for stmt in body:
        line = pos[stmt].start.line if stmt in pos else 0
        if isinstance(stmt, cst.SimpleStatementLine):
            for s in stmt.body:
                if isinstance(s, cst.AnnAssign) and isinstance(s.target, cst.Name):
                    rows.append(Row(s.target.value, _code(s.annotation.annotation),
                                    _code(s.value) if s.value is not None else "", _reads(s.value), line))
                elif isinstance(s, cst.Assign):
                    for t in s.targets:
                        if isinstance(t.target, cst.Name):
                            rows.append(Row(t.target.value, "", _code(s.value), _reads(s.value), line))
        elif isinstance(stmt, cst.FunctionDef):
            ret = _code(stmt.returns.annotation) if stmt.returns else ""
            params = [Row(p.name.value, _code(p.annotation.annotation) if p.annotation else "",
                          _code(p.default) if p.default else "", _reads(p.default), line, "param")
                      for p in stmt.params.params]
            rows.append(Row(stmt.name.value, ret, "function", [], line, "function", params))
        elif isinstance(stmt, cst.ClassDef):
            inner = stmt.body.body if isinstance(stmt.body, cst.IndentedBlock) else []
            rows.append(Row(stmt.name.value, "", "class", [], line, "class", _rows_of(inner, pos)))
    return rows


def rows(source: str) -> List[Row]:
    """The cell's module-level bindings as typed rows, in source order."""
    wrapper = MetadataWrapper(cst.parse_module(source))
    pos = wrapper.resolve(PositionProvider)
    return _rows_of(wrapper.module.body, pos)


class _SetRow(cst.CSTTransformer):
    def __init__(self, name: str, value: Optional[str], type_: Optional[str]) -> None:
        self.name, self.value, self.type_ = name, value, type_
        self.hits = 0

    def leave_AnnAssign(self, orig, node):
        if isinstance(node.target, cst.Name) and node.target.value == self.name:
            self.hits += 1
            if self.value is not None:
                node = node.with_changes(value=cst.parse_expression(self.value))
            if self.type_ is not None:
                node = node.with_changes(annotation=cst.Annotation(cst.parse_expression(self.type_)))
        return node

    def leave_Assign(self, orig, node):
        if len(node.targets) == 1 and isinstance(node.targets[0].target, cst.Name) \
                and node.targets[0].target.value == self.name:
            self.hits += 1
            if self.type_ is not None:
                # a plain binding gains a type: `x = 1` -> `x: int = 1`
                return cst.AnnAssign(target=node.targets[0].target,
                                     annotation=cst.Annotation(cst.parse_expression(self.type_)),
                                     value=cst.parse_expression(self.value) if self.value is not None else node.value)
            if self.value is not None:
                node = node.with_changes(value=cst.parse_expression(self.value))
        return node

    # module level only: a function's or class's own bindings are its rows' business
    def visit_FunctionDef(self, node) -> bool:
        return False

    def visit_ClassDef(self, node) -> bool:
        return False


def _write(module: cst.Module, source: str) -> str:
    if PLANT_AST_UNPARSE[0]:
        import ast
        return ast.unparse(ast.parse(module.code)) + "\n"
    return module.code


def set_value(source: str, name: str, value: str) -> str:
    """The row `name` given a new value expression; everything else reprinted exactly."""
    cst.parse_expression(value)                     # a bad value is refused before anything is written
    t = _SetRow(name, value, None)
    out = cst.parse_module(source).visit(t)
    if t.hits != 1:
        raise KeyError("%s binds %d times at module level; a row needs exactly one" % (name, t.hits))
    return _write(out, source)


def set_type(source: str, name: str, type_: str) -> str:
    """The row `name` given a type annotation."""
    cst.parse_expression(type_)
    t = _SetRow(name, None, type_)
    out = cst.parse_module(source).visit(t)
    if t.hits != 1:
        raise KeyError("%s binds %d times at module level; a row needs exactly one" % (name, t.hits))
    return _write(out, source)


class _Rename(cst.CSTTransformer):
    """Every module-level use of a name; a function's or class's own scope only
    where the name is not rebound there (a parameter or local of the same name
    is a different variable)."""

    def __init__(self, old: str, new: str) -> None:
        self.old, self.new = old, new
        self.shadow = [False]
        self.hits = 0

    def _bound_in(self, node) -> bool:
        names = {p.name.value for p in node.params.params} if isinstance(node, cst.FunctionDef) else set()

        class B(cst.CSTVisitor):
            def visit_AssignTarget(self, t):
                if isinstance(t.target, cst.Name):
                    names.add(t.target.value)
        node.body.visit(B())
        return self.old in names

    def visit_FunctionDef(self, node) -> bool:
        self.shadow.append(self.shadow[-1] or self._bound_in(node))
        return True

    def leave_FunctionDef(self, orig, node):
        self.shadow.pop()
        if node.name.value == self.old and not self.shadow[-1]:
            self.hits += 1
            node = node.with_changes(name=cst.Name(self.new))
        return node

    def visit_ClassDef(self, node) -> bool:
        self.shadow.append(self.shadow[-1])
        return True

    def leave_ClassDef(self, orig, node):
        self.shadow.pop()
        if node.name.value == self.old and not self.shadow[-1]:
            self.hits += 1
            node = node.with_changes(name=cst.Name(self.new))
        return node

    # `obj.old` and `f(old=1)` name an attribute and a keyword, not this
    # variable: their names are put back as they were.
    def leave_Attribute(self, orig, node):
        if orig.attr.value == self.old and node.attr.value != self.old:
            self.hits -= 1
        return node.with_changes(attr=orig.attr)

    def leave_Arg(self, orig, node):
        if orig.keyword is not None and orig.keyword.value == self.old and node.keyword is not None and node.keyword.value != self.old:
            self.hits -= 1
        return node.with_changes(keyword=orig.keyword)

    def leave_Name(self, orig, node):
        if node.value == self.old and not self.shadow[-1]:
            self.hits += 1
            return node.with_changes(value=self.new)
        return node


def rename(source: str, old: str, new: str) -> str:
    """A row renamed, and every read of it with it."""
    if not new.isidentifier():
        raise ValueError("%r is not a name" % new)
    if any(r.name == new for r in rows(source)):
        raise ValueError("%s is already a row of this cell" % new)
    t = _Rename(old, new)
    out = cst.parse_module(source).visit(t)
    if t.hits == 0:
        raise KeyError("no row %s" % old)
    return _write(out, source)
