"""The kernel's tool panels as pages: searchable, embedded, placed in 3D (G-382; PLUGIN_GOAL 170 a, 172 [2]).

"yes" -- tool panels and subgraphs get vectors and a place in 3D, as mortegon
UR O.22 had it ("search over data space seamlessly blends with search over the
space of computational tasks"); and "yes" to their own address, `tool://`.

One panel per kernel object (`search`, `Database`, `WebBrowser`, `Agent`,
`Vault`), rendered from the kernel's own bootstrap (`kernel_objects`): each
line one call, a comment at its end -- the call's purpose, from the first line
of its docstring. The body behind a call is never shown (mortegon F.6; 167 c:
"no way of exploring the underlying codebase"). Every line is checked against
the kernel by `tool_surface.parse` before it is stored, so a panel cannot name
a call the kernel lacks.

In trie terms: each panel is a page at `tool://kernel/<Name>`, tagged like a
note (`vault.tag_note`) and ingested by the page path -- the same trie, chunks,
vectors and projection as any page. `python -m domvec.obsidian purge --prefix
tool://` removes them all.
"""

from __future__ import annotations

import ast
from typing import Dict, List, Tuple

ROOT = "tool://kernel/"
PLANT_UNCHECKED = [False]


def _first_line(doc: str) -> str:
    for line in (doc or "").strip().split("\n"):
        if line.strip():
            return line.strip().rstrip(".")
    return ""


def _sig(fn: ast.FunctionDef, skip_self: bool) -> str:
    """The parameters as written, defaults included: `query, k=5, where=""`."""
    args = fn.args.args[1:] if skip_self else fn.args.args
    defaults = [None] * (len(args) - len(fn.args.defaults)) + list(fn.args.defaults)
    return ", ".join(a.arg if d is None else "%s=%s" % (a.arg, ast.unparse(d)) for a, d in zip(args, defaults))


def _calls() -> Dict[str, List[Tuple[str, str]]]:
    """Kernel global -> [(call as written, purpose)], read from the bootstrap's AST."""
    from .obsidian import kernel_objects as ko
    tree = ast.parse(ko.boot("http://127.0.0.1:0") + "\n" + ko.vault_boot("/vault", "note.md"))
    classes: Dict[str, ast.ClassDef] = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
    out: Dict[str, List[Tuple[str, str]]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "search" and node.col_offset <= 4:
            out["search"] = [("search(%s)" % _sig(node, False),
                              "the store's ranking, the web's (through the browser cell), or both")]
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) \
                and isinstance(node.value.func, ast.Name) and node.value.func.id in classes:
            name = node.targets[0].id
            cls = classes[node.value.func.id]
            rows = []
            for b in cls.body:
                if not isinstance(b, ast.FunctionDef) or b.name.startswith("_"):
                    continue
                is_prop = any(isinstance(d, ast.Name) and d.id == "property" for d in b.decorator_list)
                call = "%s.%s" % (name, b.name) + ("" if is_prop else "(%s)" % _sig(b, True))
                rows.append((call, _first_line(ast.get_docstring(b) or "") or b.name.replace("_", " ")))
            if rows:
                out[name] = rows
    return out


def render() -> Dict[str, str]:
    """Panel name -> its markdown: a title line, then the surface as a python block."""
    from .tool_surface import kernel_names, parse
    names = kernel_names()
    panels: Dict[str, str] = {}
    for name, rows in _calls().items():
        width = max(len(c) for c, _ in rows) + 2
        lines = ["%s# exists: %s" % (c.ljust(width), purpose) for c, purpose in rows]
        surface = parse("# " + name + "\n" + "\n".join(lines) + "\n", names)
        if surface.problems and not PLANT_UNCHECKED[0]:
            raise ValueError("tool panel %s does not match the kernel: %s" % (name, surface.problems))
        panels[name] = "\n".join(["# %s" % name, "",
                                  "A tool panel: the calls a kernel cell or an agent makes on `%s`. "
                                  "Read-only; the code behind them is not shown." % name,
                                  "", "```python", *lines, "```", ""])
    return panels


def url_of(name: str) -> str:
    return ROOT + name


def index(workspace) -> List[dict]:
    """Every panel into the store as a page (the page path: trie, chunks, vectors)."""
    from .trie import AddressTrie
    from .vault import tag_note
    out = []
    for name, text in render().items():
        url = url_of(name)
        trie = AddressTrie.from_tags(tag_note(text), url)
        chunks, _ = workspace.ingest(url, trie, title="tool panel: %s" % name)
        out.append({"url": url, "chunks": len(chunks)})
    return out
