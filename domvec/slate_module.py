"""A slate is a Python module written as a markdown tree (PLUGIN_GOAL 62, 63').

"treat our specialized code-node markdown integrations more like as a standard
python module with specialized markdown features, so things like
triple-repeating "results" would likely throw a syntax error" -- and, corrected
the same day, not as a third cell kind: "the markdown panels are extended to the
python syntax while still being markdown panels ... we keep this in jupyter
terms still as a "markdown" cell".

So the slate grammar (`domvec/slate.py`, `G-277`) gets Python's SEMANTICS:

* a field with children is a NAMESPACE, a field with a value is a BINDING;
  positional children (``- x``, ``1. x``) are a list's items, not names;
* a literal value is a Python literal (``8``, ``0.25``, ``true``/``false``,
  ``None``, a quoted string); anything else is a string; ``{ref}`` alone is a
  reference, ``{ref}`` inside text an interpolation;
* a ``{ref}`` -- dotted allowed, ``{search.results}`` -- resolves OUTWARD from
  the field's namespace to the module, as Python scoping would; failing that,
  to a name the note's python cells define (the interlace: names flow both
  ways between the markdown and the code cells), or to a name the caller says
  exists (the kernel's base objects, other notes);
* and its errors are raised as Python would raise them: the same name bound
  twice in one namespace (``SyntaxError``), a name defined as itself with
  nothing outer to mean (``NameError`` -- the cockpit's ``results {results}``),
  a circular definition, a reference to nothing.

`check(text)` gives the diagnostics, line by line, for the editor to draw;
`compile_module(text)` the Python source that builds the module's namespaces,
bindings in dependency order, for the note's kernel to run before a code cell.
"""

from __future__ import annotations

import ast
import keyword
import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Set, Tuple

REF = re.compile(r"\{([^{}]*)\}")
_MARKER = re.compile(r"^(- |\d+\. )")
_FENCE = re.compile(r"^\s*(`{3,}|~{3,})\s*(\S*)")


@dataclass
class Diagnostic:
    line: int              # 0-based, in the text given
    col_from: int
    col_to: int
    kind: str              # "SyntaxError" | "NameError"
    message: str

    def to_json(self) -> dict:
        return {"line": self.line, "from": self.col_from, "to": self.col_to, "kind": self.kind, "message": self.message}


@dataclass
class Node:
    key: str
    line: int
    col: int                       # where the key starts
    value: Optional[str] = None
    value_col: int = 0
    marker: str = ""
    parent: Optional["Node"] = None
    children: List["Node"] = field(default_factory=list)

    @property
    def path(self) -> List[str]:
        out, n = [], self
        while n is not None and n.parent is not None:
            out.append(n.key)
            n = n.parent
        return list(reversed(out))


def identifier(name: str) -> str:
    """A slate name as a Python identifier: names may hold spaces (G-277)."""
    s = re.sub(r"\W+", "_", name.strip())
    if not s or s[0].isdigit():
        s = "_" + s
    return s + "_" if keyword.iskeyword(s) else s


def is_slate_note(text: str) -> bool:
    return bool(re.match(r"^---\r?\n(?:.*\r?\n)*?domvec:\s*slate\s*\r?\n(?:.*\r?\n)*?---", text))


def trees_of(text: str) -> str:
    """The note's TREES, everything else blanked (line numbers kept): a slate
    note is all tree; any other markdown note -- the extended markdown cell
    (63') -- holds a tree wherever an unindented line is followed directly by
    tab-indented lines. Prose, lists, fences and the rest stay markdown."""
    if is_slate_note(text):
        return text
    lines = text.split("\n")
    keep = [False] * len(lines)
    fence = None
    i = 0
    while i < len(lines):
        m = _FENCE.match(lines[i])
        if m:
            fence = None if fence and lines[i].strip().startswith(fence) else (fence or m.group(1))
            i += 1
            continue
        if not fence and lines[i].strip() and not lines[i][:1].isspace() and i + 1 < len(lines) and lines[i + 1].startswith("\t"):
            j = i + 1
            while j < len(lines) and lines[j].startswith("\t"):
                j += 1
            for k in range(i, j):
                keep[k] = True
            i = j
            continue
        i += 1
    return "\n".join(l if keep[n] else "" for n, l in enumerate(lines))


def _body(text: str) -> List[Tuple[int, str]]:
    """The slate's lines with their numbers: frontmatter, fences and blanks out."""
    lines = text.split("\n")
    i, out = 0, []
    if lines and lines[0].strip() == "---":
        i = 1
        while i < len(lines) and lines[i].strip() != "---":
            i += 1
        i += 1
    fence = None
    for n in range(i, len(lines)):
        raw = lines[n]
        m = _FENCE.match(raw)
        if m:
            fence = None if fence and raw.strip().startswith(fence) else (fence or m.group(1))
            continue
        if fence or not raw.strip() or raw.lstrip().startswith("<!--"):
            continue
        out.append((n, raw))
    return out


def parse(text: str) -> Node:
    """The tree, with every key's line and column."""
    root = Node(key="", line=-1, col=0)
    stack: List[Tuple[int, Node]] = [(-1, root)]
    for n, raw in _body(text):
        lead = len(raw) - len(raw.lstrip("\t "))
        depth = raw[:lead].count("\t") + (raw[:lead].count(" ") // 4)
        body = raw[lead:]
        m = _MARKER.match(body)
        marker = m.group(1) if m else ""
        col = lead + len(marker)
        body = body[len(marker):]
        node = Node(key=body, line=n, col=col, marker=marker)
        if "\t" in body:
            k, v = body.split("\t", 1)
            node.key, node.value = k.rstrip(), v.lstrip("\t")
            node.value_col = col + len(body) - len(node.value)
        while stack and stack[-1][0] >= depth:
            stack.pop()
        parent = stack[-1][1]
        node.parent = parent
        parent.children.append(node)
        stack.append((depth, node))
    return root


def _walk(n: Node) -> Iterable[Node]:
    for c in n.children:
        yield c
        yield from _walk(c)


def python_names(text: str) -> Set[str]:
    """Names the note's python cells bind: assignments, defs, classes, imports."""
    names: Set[str] = set()
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        m = _FENCE.match(lines[i])
        if m and m.group(2).lower() in ("python", "py", "python3"):
            j = i + 1
            while j < len(lines) and not lines[j].strip().startswith(m.group(1)):
                j += 1
            try:
                tree = ast.parse("\n".join(lines[i + 1:j]))
            except SyntaxError:
                tree = None
            for node in ast.walk(tree) if tree else ():
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                    names.add(node.id)
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    names.add(node.name)
                elif isinstance(node, (ast.Import, ast.ImportFrom)):
                    for a in node.names:
                        names.add((a.asname or a.name).split(".")[0])
            i = j
        i += 1
    return names


def _resolve(n: Node, name: str) -> Optional[Node]:
    """`name` (dotted allowed) from `n`'s namespace outward, as Python scopes."""
    head, *rest = [p.strip() for p in name.split(".")]
    scope = n.parent
    while scope is not None:
        hit = next((c for c in scope.children if c.key == head and c is not n and not c.marker), None)
        if hit is not None:
            for part in rest:
                hit = next((c for c in hit.children if c.key == part and not c.marker), None)
                if hit is None:
                    return None
            return hit
        scope = scope.parent
    return None


def check(text: str, known: Iterable[str] = ()) -> List[Diagnostic]:
    """Python's errors over the slate: duplicates, self-definitions, cycles,
    references to nothing. `known`: names that exist outside the note."""
    root = parse(text)
    outer = set(known) | python_names(text)
    out: List[Diagnostic] = []
    for scope in [root, *_walk(root)]:
        seen: Dict[str, Node] = {}
        for c in scope.children:
            if c.marker or not c.key:
                continue
            if c.key in seen:
                first = seen[c.key]
                out.append(Diagnostic(c.line, c.col, c.col + len(c.key), "SyntaxError",
                                      "name '%s' is bound twice in %s (first at line %d)"
                                      % (c.key, "/".join(scope.path) or "the module", first.line + 1)))
            else:
                seen[c.key] = c
    deps: Dict[int, List[Node]] = {}
    for n in _walk(root):
        if n.value is None:
            continue
        for m in REF.finditer(n.value):
            name = m.group(1).strip()
            if not name:
                continue                                  # `{}`: the on-ramp, unbound
            a = n.value_col + m.start()
            hit = _resolve(n, name)
            if hit is not None:
                deps.setdefault(id(n), []).append(hit)
                continue
            if name.split(".")[0] in outer:
                continue
            # `Note#Heading`, `Note#cell 2#f` (PLUGIN_GOAL 159): a place
            # INSIDE a note -- known when the note is.
            if "#" in name and name.split("#", 1)[0].strip() in outer:
                continue
            # A trie ADDRESS (`code://...`, `vault://...`, `https://...`) names
            # something outside the module by where it is, as a cell's input
            # does -- resolved through the store, never a NameError here.
            if "://" in name:
                continue
            own = name.split(".")[0] == n.key
            out.append(Diagnostic(n.line, a, a + len(m.group(0)), "NameError",
                                  ("name '%s' is defined as itself -- nothing outside %s is called that"
                                   % (name, "/".join(n.path)))
                                  if own else "name '%s' is not defined" % name))
    # Circular definitions among bindings: a -> b -> a.
    nodes = {id(n): n for n in _walk(root)}
    state: Dict[int, int] = {}

    def visit(k: int, trail: List[Node]) -> None:
        state[k] = 1
        for d in deps.get(k, []):
            if state.get(id(d)) == 1:
                cyc = trail[trail.index(d):] + [d] if d in trail else [nodes[k], d]
                n0 = nodes[k]
                out.append(Diagnostic(n0.line, n0.col, n0.col + len(n0.key), "NameError",
                                      "circular definition: " + " -> ".join("/".join(x.path) for x in cyc)))
            elif state.get(id(d)) is None:
                visit(id(d), trail + [d])
        state[k] = 2

    for k in list(deps):
        if state.get(k) is None:
            visit(k, [nodes[k]])
    out.sort(key=lambda d: (d.line, d.col_from))
    return out


def _literal(v: str) -> str:
    s = v.strip()
    low = s.lower()
    if low in ("true", "false"):
        return "True" if low == "true" else "False"
    if low in ("none", "null", ""):
        return "None"
    try:
        lit = ast.literal_eval(s)
        if isinstance(lit, (int, float, complex, str, bytes, tuple, list, dict, set, bool)) or lit is None:
            return repr(lit)
    except (ValueError, SyntaxError):
        pass
    return repr(v)


def compile_module(text: str) -> str:
    """Python source that builds the slate's namespaces as `types.SimpleNamespace`
    -- each top-level tree a global under its title's identifier (`ego`,
    `params`), as a module's top-level names are -- bindings in dependency order.
    References resolve statically to their dotted path; a name the slate does
    not hold is left bare, for the kernel to resolve at run time (NameError if
    it does not, as Python would)."""
    root = parse(text)
    base = root

    def dotted(n: Node) -> str:
        return ".".join(identifier(p) for p in n.path)

    def expr(n: Node) -> str:
        v = n.value or ""
        whole = REF.fullmatch(v.strip())
        if whole and whole.group(1).strip():
            hit = _resolve(n, whole.group(1).strip())
            return dotted(hit) if hit is not None else ".".join(identifier(p) for p in whole.group(1).split("."))
        if REF.search(v):
            pieces, last = [], 0
            for m in REF.finditer(v):
                pieces.append(repr(v[last:m.start()]))
                hit = _resolve(n, m.group(1).strip()) if m.group(1).strip() else None
                ref = dotted(hit) if hit is not None else ".".join(identifier(p) for p in m.group(1).split("."))
                pieces.append("str(%s)" % ref if m.group(1).strip() else repr(""))
                last = m.end()
            pieces.append(repr(v[last:]))
            return " + ".join(p for p in pieces if p != "''") or "''"
        return _literal(v)

    lines = ["from types import SimpleNamespace as _NS"]
    later: List[Node] = []
    for n in _walk(base):
        if n.children and not n.marker:
            items = [c for c in n.children if c.marker]
            if items and len(items) == len(n.children):
                later.append(n)           # a list, built from its items below
            else:
                lines.append("%s = _NS()" % dotted(n))
    # Bindings: literals first, then references until every one is bound.
    binds = [n for n in _walk(base) if not n.children and not n.marker]
    lit = [n for n in binds if not REF.search(n.value or "")]
    refs = [n for n in binds if REF.search(n.value or "")]
    for n in lit:
        lines.append("%s = %s" % (dotted(n), _literal(n.value or "")))
    for n in later:
        lines.append("%s = [%s]" % (dotted(n), ", ".join(_literal(c.key) for c in n.children)))
    # In dependency order: a binding whose in-slate targets are all bound goes
    # next; what a cycle leaves is emitted last, to fail as Python would.
    bound = {id(n) for n in lit} | {id(n) for n in later}
    pending = list(refs)
    while pending:
        ready = [n for n in pending if all(
            (h is None or id(h) in bound or h.children)
            for h in (_resolve(n, m.group(1).strip()) for m in REF.finditer(n.value or "") if m.group(1).strip()))]
        for n in ready or pending:
            # A name from OUTSIDE the slate (a code cell's, the kernel's) may
            # not exist yet when an earlier cell runs: that binding waits
            # (unbound until the name exists) rather than failing the code
            # cell -- the markdown never blocks a cell; its static errors are
            # the editor's to show (`check`).
            outside = any(_resolve(n, m.group(1).strip()) is None
                          for m in REF.finditer(n.value or "") if m.group(1).strip())
            if outside:
                lines.append("try:\n    %s = %s\nexcept NameError:\n    pass" % (dotted(n), expr(n)))
            else:
                lines.append("%s = %s" % (dotted(n), expr(n)))
            bound.add(id(n))
        pending = [n for n in pending if id(n) not in bound]
    return "\n".join(lines) + "\n"
