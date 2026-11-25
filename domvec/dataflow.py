"""Marimo-style dataflow over a note's cells (G-380; PLUGIN_GOAL 167 f).

"marimo style" -- the reader's answer to how cells depend on each other. The
rules are marimo's, read from its documentation (COMPUTATION_GRAPH_EDITOR_SPEC
§5a), applied to the slate dialect (G-379) rather than to marimo's own file
format, so the note stays a markdown tree with python fences:

* a cell's DEFS are the global names it binds at its top level (assignment,
  ``def``, ``class``, ``import``, ``for``/``with`` targets, a walrus, a
  ``global`` declared in a function and assigned there);
* its REFS are the global names it reads and does not itself define;
* a name starting with ``_`` is local to its cell: neither def nor ref;
* one definition per global: two cells defining one name is an error;
* a cycle among cells is an error;
* running a cell makes every cell that reads its defs -- transitively -- stale.

A slate tree is a cell too: each top-level tree defines its title's identifier
(``ego``, ``params``), and its ``{ref}`` values that resolve outside the tree
are its refs. So names flow both ways between the markdown and the code, as
the slate's own interlace already allows (`slate_module.check`).

Mutation is invisible to this, as it is to marimo: ``xs.append(1)`` in another
cell is not a def of ``xs``. And the store changes nothing here (capture,
purge, pin are not names) -- the known edge the G-380 row records.

In trie terms: a cell is addressed ``vault://<note>#cell <n>`` (2026-11-11
159), and the graph built here is edges between those addresses -- read from
the note's text, written nowhere.
"""

from __future__ import annotations

import ast
import builtins
import re
import symtable
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Set, Tuple

from . import slate_module as sm

_FENCE = re.compile(r"^\s*(`{3,}|~{3,})\s*(\S*)")
_PY = ("python", "py", "python3")
_BUILTINS = frozenset(dir(builtins))


@dataclass
class Cell:
    index: int                 # 0-based, in document order
    kind: str                  # "python" | "slate"
    line: int                  # 0-based first line of its body
    source: str
    defs: Set[str] = field(default_factory=set)
    refs: Set[str] = field(default_factory=set)
    error: Optional[str] = None    # a SyntaxError in the cell itself

    def to_json(self) -> dict:
        return {"index": self.index, "kind": self.kind, "line": self.line,
                "defs": sorted(self.defs), "refs": sorted(self.refs), "error": self.error}


@dataclass
class Problem:
    kind: str                  # "MultipleDefinitionError" | "CycleError" | "SyntaxError"
    cells: List[int]
    name: str
    message: str

    def to_json(self) -> dict:
        return {"kind": self.kind, "cells": self.cells, "name": self.name, "message": self.message}


def _local(name: str) -> bool:
    return name.startswith("_")


def _top_stores(tree: ast.Module) -> Tuple[Set[str], Set[str]]:
    """Names bound at the cell's top level, and names bound only as
    comprehension targets (Python 3.12+ inlines comprehensions into the
    enclosing symbol table -- PEP 709 -- so symtable alone cannot tell them
    apart from a top-level binding)."""
    top: Set[str] = set()
    comp: Set[str] = set()

    def visit(n: ast.AST, in_comp: bool) -> None:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            top.add(n.name)
            for d in n.decorator_list:
                visit(d, in_comp)
            return                                # its body is its own scope
        if isinstance(n, ast.Lambda):
            return
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                if a.name != "*":
                    top.add((a.asname or a.name).split(".")[0])
            return
        if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            (comp if in_comp else top).add(n.id)
            return
        if isinstance(n, ast.NamedExpr):
            top.add(n.target.id)                  # a walrus binds in the enclosing scope
            visit(n.value, in_comp)
            return
        comp_here = isinstance(n, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp))
        for c in ast.iter_child_nodes(n):
            visit(c, in_comp or comp_here)

    visit(tree, False)
    return top, comp - top


def python_defs_refs(source: str) -> Tuple[Set[str], Set[str]]:
    """The global names one python cell defines and reads. Raises SyntaxError."""
    tree = ast.parse(source)
    defs, comp = _top_stores(tree)
    table = symtable.symtable(source, "<cell>", "exec")
    reads: Set[str] = {s.get_name() for s in table.get_symbols() if s.is_referenced()}

    def inner(t: symtable.SymbolTable) -> None:
        for c in t.get_children():
            for s in c.get_symbols():
                n = s.get_name()
                if s.is_declared_global() and s.is_assigned():
                    defs.add(n)                       # `global x; x = 1`
                elif s.is_global() and s.is_referenced():
                    reads.add(n)                      # a nested scope reading a global
            inner(c)

    inner(table)
    defs = {n for n in defs if not _local(n)}
    refs = {n for n in reads if not _local(n) and n not in defs and n not in comp and n not in _BUILTINS}
    return defs, refs


def cells_of(text: str) -> List[Cell]:
    """The note's cells in order: each python fence, and each top-level slate tree."""
    lines = text.split("\n")
    found: List[Tuple[int, Cell]] = []
    i = 0
    while i < len(lines):
        m = _FENCE.match(lines[i])
        if m:
            j = i + 1
            while j < len(lines) and not lines[j].strip().startswith(m.group(1)):
                j += 1
            if m.group(2).lower() in _PY:
                found.append((i, Cell(0, "python", i + 1, "\n".join(lines[i + 1:j]))))
            i = j + 1
            continue
        i += 1
    root = sm.parse(sm.trees_of(text))
    for tree in root.children:
        if tree.marker or not tree.key:
            continue
        last = max([tree.line] + [n.line for n in sm._walk(tree)])
        src = "\n".join(lines[tree.line:last + 1])
        c = Cell(0, "slate", tree.line, src)
        c.defs = {sm.identifier(tree.key)}
        for n in sm._walk(tree):
            for r in sm.REF.finditer(n.value or ""):
                name = r.group(1).strip()
                if not name or "://" in name or "#" in name:
                    continue
                if sm._resolve(n, name) is not None:
                    continue                      # resolved inside the slate
                head = sm.identifier(name.split(".")[0])
                if not _local(head) and head not in c.defs:
                    c.refs.add(head)
        found.append((tree.line, c))
    found.sort(key=lambda p: p[0])
    out = []
    for k, (_, c) in enumerate(found):
        c.index = k
        if c.kind == "python":
            try:
                c.defs, c.refs = python_defs_refs(c.source)
            except SyntaxError as e:
                c.error = "%s (line %s)" % (e.msg, (e.lineno or 0))
        out.append(c)
    return out


@dataclass
class Graph:
    cells: List[Cell]
    edges: Dict[int, Set[int]]          # definer -> readers
    problems: List[Problem]
    outside: Dict[int, Set[str]]        # refs no cell defines: the kernel's, other notes'

    def to_json(self) -> dict:
        return {"cells": [c.to_json() for c in self.cells],
                "edges": {str(k): sorted(v) for k, v in self.edges.items() if v},
                "problems": [p.to_json() for p in self.problems],
                "outside": {str(k): sorted(v) for k, v in self.outside.items() if v}}

    def descendants(self, index: int) -> List[int]:
        """Every cell that goes stale when `index` runs, in run order."""
        seen: Set[int] = set()
        stack = [index]
        while stack:
            for r in self.edges.get(stack.pop(), ()):
                if r not in seen and r != index:
                    seen.add(r)
                    stack.append(r)
        return [i for i in self.order() if i in seen]

    def order(self) -> List[int]:
        """A topological run order; cells on a cycle keep document order, last."""
        indeg = {c.index: 0 for c in self.cells}
        for a, rs in self.edges.items():
            for r in rs:
                indeg[r] += 1
        ready = sorted(i for i, d in indeg.items() if d == 0)
        out: List[int] = []
        while ready:
            i = ready.pop(0)
            out.append(i)
            for r in sorted(self.edges.get(i, ())):
                indeg[r] -= 1
                if indeg[r] == 0:
                    ready.append(r)
            ready.sort()
        return out + [c.index for c in self.cells if c.index not in out]


def graph(text: str, known: Iterable[str] = ()) -> Graph:
    """The note's dataflow graph. `known`: names that exist outside the note
    (the kernel's base objects: `search`, `Database`, `WebBrowser`, ...)."""
    cells = cells_of(text)
    known = set(known)
    problems: List[Problem] = []
    for c in cells:
        if c.error:
            problems.append(Problem("SyntaxError", [c.index], "", c.error))
    definer: Dict[str, int] = {}
    for c in cells:
        for n in sorted(c.defs):
            if n in definer:
                problems.append(Problem("MultipleDefinitionError", [definer[n], c.index], n,
                                        "'%s' is defined by cell %d and cell %d -- one definition per name"
                                        % (n, definer[n] + 1, c.index + 1)))
            else:
                definer[n] = c.index
    edges: Dict[int, Set[int]] = {c.index: set() for c in cells}
    outside: Dict[int, Set[str]] = {}
    for c in cells:
        for n in c.refs:
            d = definer.get(n)
            if d is None:
                if n not in known:
                    outside.setdefault(c.index, set()).add(n)
            elif d != c.index:
                edges[d].add(c.index)
    # Cycles: Tarjan over the cell graph.
    idx: Dict[int, int] = {}
    low: Dict[int, int] = {}
    on: Set[int] = set()
    st: List[int] = []
    counter = [0]

    def strong(v: int) -> None:
        idx[v] = low[v] = counter[0]
        counter[0] += 1
        st.append(v)
        on.add(v)
        for w in edges[v]:
            if w not in idx:
                strong(w)
                low[v] = min(low[v], low[w])
            elif w in on:
                low[v] = min(low[v], idx[w])
        if low[v] == idx[v]:
            comp = []
            while True:
                w = st.pop()
                on.discard(w)
                comp.append(w)
                if w == v:
                    break
            if len(comp) > 1:
                comp.sort()
                problems.append(Problem("CycleError", comp, "",
                                        "cells %s read each other's names in a cycle"
                                        % " -> ".join(str(i + 1) for i in comp)))

    for c in cells:
        if c.index not in idx:
            strong(c.index)
    return Graph(cells, edges, problems, outside)


#: Planted (G-380): the plan names no readers, so a run leaves them stale.
PLANT_NO_READERS = [False]


def rerun_plan(text: str, open_line: int, known: Iterable[str] = ()) -> dict:
    """What running the python cell whose fence opens at `open_line` makes stale,
    as the cells to re-run after it, in run order (marimo's reactive run, 167 f).

    Only python cells are re-run: the note's slate trees are compiled into the
    kernel before every cell, so a tree is never stale. A cell that is part of
    a problem (a name defined twice, a cycle) is refused rather than run around
    -- the problem is returned for the editor to show.
    """
    g = graph(text, known)
    cell = next((c for c in g.cells if c.kind == "python" and c.line == open_line + 1), None)
    if cell is None:
        return {"cell": None, "rerun": [], "problems": [], "error": "no python cell opens at line %d" % open_line}
    by = {c.index: c for c in g.cells}
    # Each problem's fences, by their opening line, for the editor to draw.
    mine = [dict(p.to_json(), open_lines=[by[i].line - 1 for i in p.cells if i in by])
            for p in g.problems if cell.index in p.cells]
    if mine:
        return {"cell": cell.index, "rerun": [], "problems": mine}
    after = [] if PLANT_NO_READERS[0] else g.descendants(cell.index)
    rerun = [{"index": i, "open_line": by[i].line - 1, "source": by[i].source,
              "reads": sorted(by[i].refs & cell.defs)}
             for i in after if by[i].kind == "python" and not any(i in p.cells for p in g.problems)]
    return {"cell": cell.index, "defs": sorted(cell.defs), "rerun": rerun, "problems": []}
