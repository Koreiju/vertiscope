"""Python code intelligence for fenced markdown code cells and CodeView (`G-447`).

Uses the environment's installed `jedi` and `parso` packages plus lightweight
typed stubs for the kernel's base app tools (`Database`, `search`, `WebBrowser`,
`Agent`, `Vault`, `Chat`, `Terminal`, `Search`, and editor calls) to provide
VS Code-grade completions, call signatures, hover documentation, go-to-definition,
and syntax diagnostics across multi-cell markdown notes.

In trie terms: reads `vault://<vault>/<note>#cell <k>` source cells and resolves
symbols against earlier cells in the same note, installed Python modules, or the
workspace's `code://` CPG nodes (`GET /code_nodes`), while keeping app-tool
internals opaque per `COMPUTATION_GRAPH_EDITOR_SPEC` §13n boundary 2.
"""

from __future__ import annotations

import collections
import pathlib
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

#: Planted (G-447): `/code_intel` returns empty results, leaving fences bare.
PLANT_NO_CODE_INTEL = [False]

#: Auto-import suggestions for common stdlib / scientific symbols (`G-450`).
_AUTO_IMPORTS: List[Tuple[str, str, str]] = [
    ("np", "import numpy as np", "module numpy"),
    ("pd", "import pandas as pd", "module pandas"),
    ("nx", "import networkx as nx", "module networkx"),
    ("plt", "import matplotlib.pyplot as plt", "module matplotlib.pyplot"),
    ("Path", "from pathlib import Path", "class pathlib.Path"),
    ("dataclass", "from dataclasses import dataclass", "decorator dataclasses.dataclass"),
    ("defaultdict", "from collections import defaultdict", "class collections.defaultdict"),
    ("Counter", "from collections import Counter", "class collections.Counter"),
    (" deque", "from collections import deque", "class collections.deque"),
    ("json", "import json", "module json"),
    ("re", "import re", "module re"),
    ("math", "import math", "module math"),
    ("time", "import time", "module time"),
    ("asyncio", "import asyncio", "module asyncio"),
    ("Optional", "from typing import Optional", "typing.Optional"),
    ("Dict", "from typing import Dict", "typing.Dict"),
    ("List", "from typing import List", "typing.List"),
]

#: VS Code-style Python statement snippets (`G-450`).
_SNIPPETS: List[Dict[str, str]] = [
    {"label": "def", "apply": "def func(x):\n    ", "detail": "snippet · function definition", "type": "keyword"},
    {"label": "class", "apply": "class Model:\n    def __init__(self):\n        ", "detail": "snippet · class definition", "type": "keyword"},
    {"label": "for", "apply": "for item in items:\n    ", "detail": "snippet · for loop", "type": "keyword"},
    {"label": "with", "apply": "with open(path, \"r\", encoding=\"utf-8\") as f:\n    ", "detail": "snippet · context manager", "type": "keyword"},
    {"label": "try", "apply": "try:\n    pass\nexcept Exception as err:\n    ", "detail": "snippet · try/except", "type": "keyword"},
]

_JEDI_PROJECT: Any = None
_JEDI_LOCK = threading.Lock()
#: Receiver attribute completion LRU cache: `(imports_key, receiver_expr, want_private) -> List[dict]`.
_ATTR_CACHE: "collections.OrderedDict[Tuple[str, str, bool], List[Dict[str, Any]]]" = collections.OrderedDict()
_ATTR_CACHE_MAX = 256


def _get_jedi_project():
    global _JEDI_PROJECT
    if _JEDI_PROJECT is None:
        import jedi
        _JEDI_PROJECT = jedi.Project(path=pathlib.Path(__file__).resolve().parent.parent)
    return _JEDI_PROJECT


def _warm_jedi_bg() -> None:
    try:
        with _JEDI_LOCK:
            import jedi
            proj = _get_jedi_project()
            warm_src = "import math, json, pathlib\ntry:\n    import numpy as np\nexcept Exception:\n    pass\nnp."
            s = jedi.Script(code=warm_src, project=proj)
            _ = s.complete(5, 3)
    except Exception:  # noqa: BLE001
        pass


threading.Thread(target=_warm_jedi_bg, name="domvec-jedi-warm", daemon=True).start()

#: Typed stubs for the kernel's built-in app tools (`kernel_objects.py` BOOT),
#: so completions, hover docs, and parameter hints work even before a kernel boots.
_KERNEL_STUBS = '''
class _DomvecDatabase:
    """Read-only workspace store interface: search(query, k=5, where='') and cypher(query)."""
    def search(self, query: str, k: int = 5, where: str = "") -> list[dict]:
        """Return ranked chunks `{cid, url, text}` from the store."""
        ...
    def cypher(self, query: str) -> list:
        """Execute a read-only Cypher query over the workspace Kuzu store."""
        ...

class _DomvecBrowser:
    """Live Electron browser cell tool surface."""
    url: str = ""
    title: str = ""
    def go(self, url: str) -> str:
        """Navigate the active browser cell to `url`."""
        ...
    def chunks(self) -> list[dict]:
        """Stored chunks of the currently displayed page."""
        ...
    def pin(self, xpath: str) -> dict:
        """Pin the chunk at `xpath` onto the 2D plane."""
        ...
    def controls(self, cid: str = "") -> list[dict]:
        """Interactive affordances on the current page or chunk `cid`."""
        ...
    def act(self, address: str, value: object = None) -> dict:
        """Act on an interactive element in place via its trie address."""
        ...

class _DomvecVault:
    """Vault file reader/writer scoped strictly inside the Obsidian vault."""
    def read(self, path: str) -> str:
        """Read a vault markdown note by relative path (creates a compiled link)."""
        ...
    def write(self, path: str, text: str) -> str:
        """Write `text` to `path` inside the vault."""
        ...

class _DomvecAgent:
    """Local quantized language model interface."""
    def ask(self, prompt: str, context: list = []) -> str:
        """Ask the sidecar's local quantized model with optional context chunks."""
        ...

class _DomvecChat:
    """Live mirror of a note's conversation turns (`G-412`)."""
    def messages(self, note: str | None = None) -> list[dict]:
        """Return `[{'role': 'user'|'assistant', 'content': ...}]` turns of `note`."""
        ...

class _DomvecTerminal:
    """Live readout of the command terminal pane (`G-440`)."""
    def last(self, pane: str | None = None) -> dict:
        """Return `{command, output, exit_code}` of the last terminal command."""
        ...

class _DomvecSearch:
    """Live readout of the 3D search field (`G-441`)."""
    def last(self) -> dict:
        """Return `{query, hits}` of the most recent 3D search."""
        ...

Database = _DomvecDatabase()
WebBrowser = _DomvecBrowser()
Vault = _DomvecVault()
Agent = _DomvecAgent()
Chat = _DomvecChat()
Terminal = _DomvecTerminal()
Search = _DomvecSearch()

def search(query: str, db: bool = True, duckduckgo: bool = False, k: int = 8, where: str = "") -> list[dict]:
    """Search the workspace store (`db=True`), DuckDuckGo (`duckduckgo=True`), or both."""
    ...

def similar(cid: str, k: int = 8) -> list[dict]:
    """Return the `k` nearest neighbour chunks of `cid`."""
    ...

def chunk(cid: str) -> dict | None:
    """Return `{cid, url, lines}` for stored chunk `cid`."""
    ...

def page_form(cid: str) -> str | None:
    """Saved HTML snapshot of chunk `cid`, if captured."""
    ...

def resolve(url: str, xpath: str) -> dict | None:
    """Resolve `(url, xpath)` to the stored chunk covering that trie address."""
    ...

def focus(cid: str) -> str:
    """Fly the 3D camera to chunk or page `cid`."""
    ...

def unfold(url: str) -> list:
    """Unfold page `url` into its chunks in the 3D view."""
    ...

def pages(contains: str = "") -> list[str]:
    """Stored page URLs, optionally filtered by substring `contains`."""
    ...

def ego() -> dict:
    """Current ego computation-graph nodes and compiled links."""
    ...

def attach(cid: str) -> str:
    """Tag chunk `cid` into the ego graph."""
    ...

def view(mode: str = "third") -> str:
    """Switch camera between `'first'` and `'third'` person."""
    ...

def types(query: str = "") -> list[dict]:
    """Mined trie-path aggregate types matching `query`."""
    ...

def check(slate: str) -> list[dict]:
    """Check slate tree syntax for duplicate definitions or cycles."""
    ...

def create(name: str, body: str = "", kind: str = "notebook") -> str:
    """Create a panel card (`'notebook'` or `'slate'`) on the 2D plane."""
    ...

def link(a: str, b: str) -> str:
    """Create a compiled `Vault.read` link from note `a` to note `b`."""
    ...
'''.lstrip("\n")

_STUB_LINES = _KERNEL_STUBS.count("\n")
_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _assemble(cells: List[str], cell_index: int, line: int) -> Tuple[str, int, List[Tuple[int, int]]]:
    """Concatenate kernel stubs + all cells, returning `(vdoc, vline, spans)`.

    `spans[i]` is `(start_1based, end_1based)` in `vdoc` for `cells[i]`.
    """
    parts: List[str] = [_KERNEL_STUBS]
    cur_line = _STUB_LINES + 1
    spans: List[Tuple[int, int]] = []
    for idx, raw in enumerate(cells):
        body = str(raw or "").replace("\r\n", "\n")
        header = f"# --- domvec_cell_{idx} ---\n"
        parts.append(header)
        cur_line += 1
        n_lines = body.count("\n") + 1
        start = cur_line
        end = cur_line + n_lines - 1
        spans.append((start, end))
        parts.append(body + "\n")
        cur_line = end + 1
    safe_idx = max(0, min(cell_index, len(spans) - 1)) if spans else 0
    vline = (spans[safe_idx][0] + max(1, int(line)) - 1) if spans else _STUB_LINES + 1
    return "".join(parts), vline, spans


def _map_vline(vline: int, spans: List[Tuple[int, int]]) -> Optional[Tuple[int, int]]:
    """Map a 1-based line in `vdoc` back to `(cell_index, 1_based_cell_line)`."""
    if vline <= _STUB_LINES:
        return (-1, vline)
    for idx, (a, b) in enumerate(spans):
        if a <= vline <= b:
            return (idx, vline - a + 1)
    return None


def _short_sig(item: Any) -> str:
    try:
        sigs = item.get_signatures()
        if sigs:
            s = sigs[0]
            params = ", ".join(p.description.replace("param ", "") for p in s.params[:6])
            if len(s.params) > 6:
                params += ", …"
            return f"{s.name}({params})"
    except Exception:  # noqa: BLE001
        pass
    return str(getattr(item, "description", "") or "")


def _extract_imports_sig(vdoc: str) -> str:
    return "\n".join(
        ln.strip()
        for ln in vdoc.splitlines()
        if ln.lstrip().startswith(("import ", "from ", "def ", "class "))
    )


def _imported_module_attrs(vdoc: str, receiver: str, want_private: bool = False) -> List[Dict[str, Any]]:
    """Resolve `receiver` (e.g. `np` or `np.linalg`) against top-level `import` / `from ... import`
    aliases in `vdoc` so PEP-562 lazy/dynamic exports (`numpy.zeros`, `numpy.linalg`, `pandas.DataFrame`)
    appear alongside static Jedi completions (`G-450`)."""
    import ast
    import importlib

    alias_map: Dict[str, str] = {}
    for ln in vdoc.splitlines():
        s = ln.strip()
        if not s.startswith(("import ", "from ")):
            continue
        try:
            mod_node = ast.parse(s)
        except SyntaxError:
            continue
        for stmt in mod_node.body:
            if isinstance(stmt, ast.Import):
                for al in stmt.names:
                    bound = al.asname or al.name.split(".")[0]
                    alias_map[bound] = al.name if al.asname else al.name.split(".")[0]
            elif isinstance(stmt, ast.ImportFrom) and stmt.module:
                for al in stmt.names:
                    if al.name == "*":
                        continue
                    bound = al.asname or al.name
                    alias_map[bound] = f"{stmt.module}.{al.name}"

    parts = receiver.split(".")
    if not parts or parts[0] not in alias_map:
        return []
    target_path = alias_map[parts[0]]
    rest = parts[1:]
    try:
        obj: Any = importlib.import_module(target_path.split(".")[0])
        for seg in target_path.split(".")[1:] + rest:
            if hasattr(obj, seg):
                obj = getattr(obj, seg)
            else:
                obj = importlib.import_module(f"{obj.__name__}.{seg}")
        res: List[Dict[str, Any]] = []
        for name in dir(obj):
            if name.startswith("_") and not want_private:
                continue
            val = getattr(obj, name, None)
            kind = "module" if isinstance(val, type(ast)) else ("class" if isinstance(val, type) else ("function" if callable(val) else "property"))
            res.append({"label": name, "type": kind, "detail": f"{kind} {receiver}.{name}"[:90], "info": ""})
        return res
    except Exception:  # noqa: BLE001
        return []


def complete(
    cells: List[str],
    cell_index: int = 0,
    line: int = 1,
    col: int = 0,
    workspace: Any = None,
    limit: int = 120,
    kernel_pool: Any = None,
    note: str = "",
    external_defs: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    if PLANT_NO_CODE_INTEL[0] or not cells:
        return []
    import jedi

    vdoc, vline, _ = _assemble(cells, cell_index, line)
    lines = vdoc.split("\n")
    safe_line = max(1, min(vline, len(lines)))
    line_text = lines[safe_line - 1]
    safe_col = max(0, min(int(col), len(line_text)))
    before = line_text[:safe_col]

    # Prefix before cursor to decide whether dunder/private names were asked for,
    # and whether we are completing a member attribute (`receiver.prefix`).
    k = safe_col
    while k > 0 and (line_text[k - 1].isalnum() or line_text[k - 1] == "_"):
        k -= 1
    prefix = line_text[k:safe_col]
    want_private = prefix.startswith("_")
    is_attr = k > 0 and line_text[k - 1] == "."
    receiver = ""
    if is_attr:
        r_end = k - 1
        r_start = r_end
        while r_start > 0 and (line_text[r_start - 1].isalnum() or line_text[r_start - 1] in "._"):
            r_start -= 1
        receiver = line_text[r_start:r_end]

    # Fast path (`G-450`, < 2 ms): receiver attribute cache (`np.`, `np.ar`, etc.).
    cache_key: Optional[Tuple[str, str, bool]] = None
    if is_attr and receiver:
        cache_key = (_extract_imports_sig(vdoc), receiver, want_private)
        cached = _ATTR_CACHE.get(cache_key)
        if cached is not None:
            _ATTR_CACHE.move_to_end(cache_key)
            if not prefix:
                return cached[:limit]
            p_low = prefix.lower()
            starts = [it for it in cached if it["label"].lower().startswith(p_low)]
            contains = [it for it in cached if p_low in it["label"].lower() and not it["label"].lower().startswith(p_low)]
            return (starts + contains)[:limit]

    out: List[Dict[str, Any]] = []
    seen = set()

    try:
        with _JEDI_LOCK:
            proj = _get_jedi_project()
            # When completing `receiver.prefix`, query Jedi at `receiver.` (`k`) when
            # caching so ALL attributes of `receiver` are cached in one shot!
            query_col = k if cache_key is not None else safe_col
            script = jedi.Script(code=vdoc, project=proj)
            raw_items = script.complete(safe_line, query_col)
            max_collect = 800 if cache_key is not None else limit
            for c in raw_items:
                name = str(c.name or "")
                if not name or name.startswith("_Domvec") or name.startswith("_domvec"):
                    continue
                if name.startswith("_") and not want_private:
                    continue
                if name in seen:
                    continue
                seen.add(name)
                c_type = str(c.type or "variable")
                doc = ""
                det = c_type
                if len(out) < 14:
                    det = _short_sig(c)[:90] or c_type
                    try:
                        doc = (c.docstring(raw=False) or "").strip()[:300]
                    except Exception:  # noqa: BLE001
                        doc = ""
                out.append({
                    "label": name,
                    "type": c_type,
                    "detail": det,
                    "info": doc,
                })
                if len(out) >= max_collect:
                    break
    except Exception:  # noqa: BLE001
        pass

    # Augment imported modules with runtime `dir()` so PEP-562 dynamic exports (`np.zeros`, `np.linalg`) are complete (`G-450`).
    if is_attr and receiver:
        for it in _imported_module_attrs(vdoc, receiver, want_private=want_private):
            lb = it["label"]
            if lb not in seen:
                seen.add(lb)
                out.append(it)

    # Live kernel runtime fallback for dynamic objects (`df.`, `obj.`) in `note`'s kernel.
    if is_attr and receiver and not out and kernel_pool is not None and note:
        try:
            probe = (
                "import json as _dj\n"
                f"_do = eval({receiver!r}, globals())\n"
                "print('__DOMVEC_DIR__' + _dj.dumps(["
                "{'label': a, 'type': 'function' if callable(getattr(_do, a, None)) else 'property'} "
                "for a in dir(_do) if not a.startswith('_')"
                "][:200]))"
            )
            rep = kernel_pool.run(note, probe)
            for ln in (rep.get("stdout") or "").splitlines():
                if ln.startswith("__DOMVEC_DIR__"):
                    for it in __import__("json").loads(ln[len("__DOMVEC_DIR__"):]):
                        lb = str(it.get("label") or "")
                        if lb and lb not in seen:
                            seen.add(lb)
                            out.append({"label": lb, "type": it.get("type") or "property", "detail": f"{receiver}.{lb}", "info": ""})
        except Exception:  # noqa: BLE001
            pass

    if cache_key is not None and out:
        _ATTR_CACHE[cache_key] = list(out)
        if len(_ATTR_CACHE) > _ATTR_CACHE_MAX:
            _ATTR_CACHE.popitem(last=False)
        if prefix:
            p_low = prefix.lower()
            starts = [it for it in out if it["label"].lower().startswith(p_low)]
            contains = [it for it in out if p_low in it["label"].lower() and not it["label"].lower().startswith(p_low)]
            return (starts + contains)[:limit]
        return out[:800]

    # NEVER pollute dot-attribute completions (`np.`) with top-level symbols, snippets, or buffer words!
    if is_attr:
        return out[:limit]

    # Top-level completions: cross-notebook variables (`G-451`), auto-imports, snippets, and CPG symbols (`G-450`).
    p_low = prefix.lower()
    for ext in external_defs or []:
        nm = str(ext.get("name") or "")
        src_note = str(ext.get("note") or "")
        if nm and nm not in seen and (not p_low or nm.lower().startswith(p_low)):
            seen.add(nm)
            out.insert(0, {
                "label": nm,
                "type": "variable",
                "detail": f"from {src_note}",
                "info": f"Cross-notebook variable defined in `{src_note}` (compiled automatically in DAG order).",
            })

    stmt_head = before.lstrip()
    if prefix and stmt_head == prefix:
        for sn in _SNIPPETS:
            if sn["label"].startswith(p_low):
                key_sn = sn["label"] + "…"
                if key_sn not in seen:
                    seen.add(key_sn)
                    out.append({
                        "label": sn["label"],
                        "apply": sn["apply"],
                        "type": "keyword",
                        "detail": sn["detail"],
                        "info": "",
                    })

    if prefix:
        for sym, imp_stmt, det in _AUTO_IMPORTS:
            s_clean = sym.strip()
            if s_clean not in seen and s_clean.lower().startswith(p_low) and imp_stmt not in vdoc:
                seen.add(s_clean)
                out.append({
                    "label": s_clean,
                    "type": "module" if imp_stmt.startswith("import ") else "class",
                    "detail": f"auto-import · {imp_stmt}",
                    "info": det,
                    "auto_import": imp_stmt,
                })

    if workspace is not None and len(prefix) >= 2 and len(out) < limit:
        try:
            rows = workspace.store._rows(
                "MATCH (n:CodeNode) WHERE lower(n.name) STARTS WITH $q "
                "RETURN n.kind, n.name, n.qname LIMIT 12",
                {"q": p_low},
            )
            for kind, name, qname in rows:
                nm = str(name or "")
                if nm and nm not in seen:
                    seen.add(nm)
                    out.append({
                        "label": nm,
                        "type": "class" if kind == "class" else ("function" if kind in ("function", "method") else "variable"),
                        "detail": f"{kind} {qname or nm}"[:90],
                        "info": "",
                    })
        except Exception:  # noqa: BLE001
            pass
    return out[:limit]


def signature(cells: List[str], cell_index: int = 0, line: int = 1, col: int = 0) -> List[Dict[str, Any]]:
    if PLANT_NO_CODE_INTEL[0] or not cells:
        return []
    import jedi

    vdoc, vline, _ = _assemble(cells, cell_index, line)
    lines = vdoc.split("\n")
    safe_line = max(1, min(vline, len(lines)))
    safe_col = max(0, min(int(col), len(lines[safe_line - 1])))
    out: List[Dict[str, Any]] = []
    try:
        script = jedi.Script(code=vdoc)
        for s in script.get_signatures(safe_line, safe_col):
            doc = ""
            try:
                doc = (s.docstring(raw=False) or "").strip()[:360]
            except Exception:  # noqa: BLE001
                doc = ""
            out.append({
                "name": str(s.name or ""),
                "index": s.index if s.index is not None else 0,
                "params": [p.description.replace("param ", "") for p in s.params],
                "docstring": doc,
            })
    except Exception:  # noqa: BLE001
        pass
    return out


def hover(cells: List[str], cell_index: int = 0, line: int = 1, col: int = 0) -> Optional[Dict[str, Any]]:
    if PLANT_NO_CODE_INTEL[0] or not cells:
        return None
    import jedi

    vdoc, vline, _ = _assemble(cells, cell_index, line)
    lines = vdoc.split("\n")
    safe_line = max(1, min(vline, len(lines)))
    safe_col = max(0, min(int(col), len(lines[safe_line - 1])))
    try:
        script = jedi.Script(code=vdoc)
        items = script.help(safe_line, safe_col) or script.infer(safe_line, safe_col)
        for it in items:
            name = str(it.name or "")
            if not name or name.startswith("_Domvec"):
                continue
            doc = ""
            try:
                doc = (it.docstring(raw=False) or "").strip()[:600]
            except Exception:  # noqa: BLE001
                doc = ""
            sig = _short_sig(it)
            if not doc and not sig and it.type in ("keyword", "operator"):
                continue
            return {
                "name": name,
                "type": str(it.type or ""),
                "signature": sig[:140],
                "docstring": doc,
            }
    except Exception:  # noqa: BLE001
        pass
    return None


def goto(
    cells: List[str],
    cell_index: int = 0,
    line: int = 1,
    col: int = 0,
    workspace: Any = None,
) -> Optional[Dict[str, Any]]:
    if PLANT_NO_CODE_INTEL[0] or not cells:
        return None
    import jedi

    vdoc, vline, spans = _assemble(cells, cell_index, line)
    lines = vdoc.split("\n")
    safe_line = max(1, min(vline, len(lines)))
    safe_col = max(0, min(int(col), len(lines[safe_line - 1])))
    try:
        script = jedi.Script(code=vdoc)
        defs = script.goto(safe_line, safe_col, follow_imports=True)
        for d in defs:
            if d.module_path is None and d.line is not None:
                mapped = _map_vline(int(d.line), spans)
                if mapped is None:
                    continue
                c_idx, c_line = mapped
                if c_idx < 0:
                    # Spec §13n boundary 2: app tools are read-only surfaces,
                    # never opening internal app implementation source.
                    return {"kind": "app_tool", "name": str(d.name or "")}
                return {
                    "kind": "cell",
                    "cell_index": c_idx,
                    "line": c_line,
                    "column": int(d.column or 0),
                    "name": str(d.name or ""),
                }
            if d.module_path is not None:
                mp = pathlib.Path(d.module_path).resolve()
                # Boundary 2: do not expose domvec's own internal package files.
                try:
                    rel = mp.relative_to(_REPO_ROOT)
                    if rel.parts and rel.parts[0] == "domvec":
                        return {"kind": "app_tool", "name": str(d.name or "")}
                except ValueError:
                    pass
                # Check if CPG holds a `code://` URL for this symbol.
                url = ""
                if workspace is not None and d.name:
                    try:
                        rows = workspace.store._rows(
                            "MATCH (n:CodeNode) WHERE n.name = $nm RETURN n.url, n.line LIMIT 1",
                            {"nm": str(d.name)},
                        )
                        if rows:
                            url = f"{rows[0][0]}#L{rows[0][1] or d.line or 1}"
                    except Exception:  # noqa: BLE001
                        pass
                return {
                    "kind": "external",
                    "name": str(d.name or ""),
                    "module": str(d.full_name or d.module_name or ""),
                    "path": str(mp),
                    "line": int(d.line or 1),
                    "url": url,
                }
    except Exception:  # noqa: BLE001
        pass
    return None


def diagnostics(cells: List[str]) -> List[Dict[str, Any]]:
    if PLANT_NO_CODE_INTEL[0] or not cells:
        return []
    import parso

    grammar = parso.load_grammar()
    out: List[Dict[str, Any]] = []
    for idx, raw in enumerate(cells):
        src = str(raw or "").replace("\r\n", "\n")
        if not src.strip():
            continue
        try:
            tree = grammar.parse(src, error_recovery=True)
            for err in grammar.iter_errors(tree):
                ln, col = err.start_pos
                end_ln, end_col = err.end_pos
                out.append({
                    "cell_index": idx,
                    "line": int(ln),
                    "col": int(col),
                    "end_line": int(end_ln),
                    "end_col": int(end_col),
                    "message": str(err.message or "Syntax error"),
                })
        except Exception:  # noqa: BLE001
            pass
    return out


def handle(
    body: Dict[str, Any],
    workspace: Any = None,
    kernel_pool: Any = None,
) -> Dict[str, Any]:
    op = str(body.get("op") or "complete").strip().lower()
    cells = [str(c) for c in (body.get("cells") or [])]
    if not cells and "code" in body:
        cells = [str(body.get("code") or "")]
    cell_index = int(body.get("cell_index") or 0)
    line = int(body.get("line") or 1)
    col = int(body.get("col") or 0)
    note = str(body.get("note") or "")
    ext_defs = body.get("external_defs") if isinstance(body.get("external_defs"), list) else None

    if op == "complete":
        return {
            "items": complete(
                cells,
                cell_index,
                line,
                col,
                workspace=workspace,
                kernel_pool=kernel_pool,
                note=note,
                external_defs=ext_defs,
            )
        }
    if op == "signature":
        return {"signatures": signature(cells, cell_index, line, col)}
    if op == "hover":
        return {"hover": hover(cells, cell_index, line, col)}
    if op == "goto":
        return {"target": goto(cells, cell_index, line, col, workspace=workspace)}
    if op == "diagnostics":
        return {"diagnostics": diagnostics(cells)}
    return {"error": f"unknown op: {op}"}
