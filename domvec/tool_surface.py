"""Tool surfaces held to their own definition (G-376, G-377; PLUGIN_GOAL 166-167).

"25 lines or so of python showing the full capability of the overall
toolspace" -- "python calls only with comments at the end, or something
equally minimal".

A surface is a ```python block: one call (or attribute read) per line, a
comment at the end of each. Each comment opens with ``exists`` or ``new``: a
claim about whether the call runs in a note's kernel today. This module checks
the form, and checks the claim against the kernel's own bootstrap
(`domvec/obsidian/kernel_objects.py`), read statically -- the bootstrap is
never executed here (the vault half changes the working directory).

So the count in the spec is computed, not kept: it was hand-counted once as
13/17 and corrected to 10/14 the same day.

In trie terms: each surface line is a call whose target is an address in the
store's route space; the check reads the spec and the kernel source, writes
nothing.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

MAX_LINES = 25            # "25 lines or so"
_BLOCK = re.compile(r"```python\n(.*?)```", re.S)


@dataclass
class Line:
    surface: str
    n: int                 # 1-based within the block
    code: str
    comment: str
    claim: Optional[str]   # "exists" | "new" | None
    target: Optional[str]  # `search`, `WebBrowser.go`, ...
    resolves: bool = False


@dataclass
class Surface:
    title: str
    lines: List[Line] = field(default_factory=list)
    problems: List[str] = field(default_factory=list)


def kernel_names() -> Dict[str, Set[str]]:
    """Each kernel global the boot defines -> the public members it carries
    (empty set for a plain function)."""
    from .obsidian import kernel_objects as ko
    src = ko.boot("http://127.0.0.1:0") + "\n" + ko.vault_boot("/vault", "note.md")
    tree = ast.parse(src)
    classes: Dict[str, Set[str]] = {}
    out: Dict[str, Set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            classes[node.name] = {b.name for b in node.body
                                  if isinstance(b, (ast.FunctionDef, ast.AsyncFunctionDef))
                                  and not b.name.startswith("_")}
            classes[node.name] |= {t.id for b in node.body if isinstance(b, ast.Assign)
                                   for t in b.targets if isinstance(t, ast.Name) and not t.id.startswith("_")}
            # attributes set in __init__ (`self.here = ...`)
            for b in node.body:
                if isinstance(b, ast.FunctionDef) and b.name == "__init__":
                    for s in ast.walk(b):
                        if isinstance(s, ast.Attribute) and isinstance(s.ctx, ast.Store) \
                                and isinstance(s.value, ast.Name) and s.value.id == "self" \
                                and not s.attr.startswith("_"):
                            classes[node.name].add(s.attr)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_") \
                and node.col_offset <= 4:
            out.setdefault(node.name, set())
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) \
                and isinstance(node.value.func, ast.Name) and node.value.func.id in classes:
            for t in node.targets:
                if isinstance(t, ast.Name) and not t.id.startswith("_"):
                    out[t.id] = classes[node.value.func.id]
    return out


def _target(expr: ast.expr) -> Optional[str]:
    e = expr.func if isinstance(expr, ast.Call) else expr
    if isinstance(e, ast.Name):
        return e.id
    if isinstance(e, ast.Attribute) and isinstance(e.value, ast.Name):
        return "%s.%s" % (e.value.id, e.attr)
    return None


def parse(block: str, names: Dict[str, Set[str]]) -> Surface:
    raw = block.rstrip("\n").split("\n")
    title = raw[0].lstrip("# ").strip() if raw and raw[0].lstrip().startswith("#") else "(untitled)"
    s = Surface(title)
    body = [l for l in raw[1:] if l.strip()] if raw and raw[0].lstrip().startswith("#") else [l for l in raw if l.strip()]
    if len(body) > MAX_LINES:
        s.problems.append("%d lines -- over the ~%d a surface is" % (len(body), MAX_LINES))
    for i, l in enumerate(body, 1):
        try:
            ast.parse(l)
            at = _comment_at(l)          # the '#' outside any string
            code = l[:at].rstrip() if at is not None else l
            comment = l[at + 1:].strip() if at is not None else ""
        except SyntaxError as e:
            s.problems.append("line %d: not Python (%s)" % (i, e.msg))
            continue
        ln = Line(s.title, i, code, comment, None, None)
        m = re.match(r"(exists|new)\b", comment)
        ln.claim = m.group(1) if m else None
        if not comment:
            s.problems.append("line %d: no comment at its end" % i)
        elif ln.claim is None:
            s.problems.append("line %d: comment does not say `exists` or `new`" % i)
        stmts = ast.parse(code).body
        if len(stmts) != 1 or not isinstance(stmts[0], ast.Expr) \
                or not isinstance(stmts[0].value, (ast.Call, ast.Attribute, ast.Name)):
            s.problems.append("line %d: not a single call or attribute read" % i)
        else:
            ln.target = _target(stmts[0].value)
            head, _, member = (ln.target or "").partition(".")
            ln.resolves = head in names and (not member or member in names[head])
            if ln.claim == "exists" and not ln.resolves:
                s.problems.append("line %d: claims `exists` but the kernel has no `%s`" % (i, ln.target))
            if ln.claim == "new" and ln.resolves:
                s.problems.append("line %d: claims `new` but the kernel already has `%s`" % (i, ln.target))
        s.lines.append(ln)
    return s


def _comment_at(line: str) -> Optional[int]:
    """Index of the '#' that starts the line's comment, strings respected."""
    import io
    import tokenize
    try:
        for t in tokenize.generate_tokens(io.StringIO(line + "\n").readline):
            if t.type == tokenize.COMMENT:
                return t.start[1]
    except (tokenize.TokenError, IndentationError):
        return None
    return None


def surfaces(markdown: str, section: str = "## 8.") -> List[Surface]:
    """Every surface in the spec's section (default: §8)."""
    start = markdown.find(section)
    if start < 0:
        return []
    end = markdown.find("\n## ", start + len(section))
    text = markdown[start:end if end > 0 else None]
    names = kernel_names()
    return [parse(b, names) for b in _BLOCK.findall(text)]


def count(found: List[Surface]) -> Dict[str, int]:
    lines = [l for s in found for l in s.lines]
    return {"surfaces": len(found), "lines": len(lines),
            "exists": sum(l.resolves for l in lines),
            "new": sum(not l.resolves for l in lines),
            "problems": sum(len(s.problems) for s in found)}


def main() -> int:
    import json
    from pathlib import Path
    md = (Path(__file__).resolve().parent.parent / "docs" / "COMPUTATION_GRAPH_EDITOR_SPEC.md").read_text(encoding="utf-8")
    found = surfaces(md)
    for s in found:
        print("%-45s %2d lines  %s" % (s.title[:45], len(s.lines), "; ".join(s.problems) or "ok"))
    print(json.dumps(count(found)))
    return 1 if any(s.problems for s in found) else 0


if __name__ == "__main__":
    raise SystemExit(main())
