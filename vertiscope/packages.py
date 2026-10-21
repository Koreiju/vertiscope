"""Installed packages, and this codebase, as code pages in the trie (G-104).

Addendum IX: "render each python package as a tree-structured UMAP projection
on the chunked comments/code docs, and show the full dependencies on variables
to modules to directories". A module is already a page (`code://<root>/<path>`,
`vertiscope.source`): its trie holds its classes, functions, docstrings and its
imports -- the variable a module binds, addressed where it is bound -- and an
import becomes a link to the imported module's page whenever the store holds
it (`LinksTo`). What this adds:

* `index_tree` / `index_package` -- every source file under a folder, or an
  installed package's folder, through `Workspace.index_source`, so the module
  pages, their chunks and their import links enter the store by the page path;
* `code_tree_edges` -- the DIRECTORY tree over module pages: each module hangs
  under its folder's package module (`__init__.py`), each package under the
  nearest held package above it. Those edges and the import links are the
  dependencies from variable to module to directory.

In trie terms: reads each file into a `code://` trie (one page per module) and
writes it through `ingest`; the tree edges are a function of the urls alone.
"""

from __future__ import annotations

import importlib.util
import pathlib
from posixpath import dirname
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from .source import iter_sources, source_path_of


def package_dir(name: str) -> Optional[pathlib.Path]:
    """The folder an installed package imports from, or None (a module that
    is a single file has no tree to draw)."""
    try:
        spec = importlib.util.find_spec(name)
    except (ImportError, ValueError):
        return None
    if spec is None or not spec.submodule_search_locations:
        return None
    for loc in spec.submodule_search_locations:
        p = pathlib.Path(loc)
        if p.is_dir():
            return p
    return None


def index_tree(workspace, folder, root: str, *, limit: int = 0,
               max_bytes: int = 400_000, relink: bool = True,
               step: Optional[Callable[[str], None]] = None) -> Dict:
    """Every source file under `folder` into the store as `code://<root>/...`.

    `step` runs before each file (the sidecar stands aside for the reader
    there). A file over `max_bytes` is skipped and counted, not cut: a cut
    module would be addressed as if it were whole.
    """
    done, skipped, chunks, failed = 0, 0, 0, []
    for path, rel in iter_sources(folder):
        if limit and done >= limit:
            break
        try:
            if path.stat().st_size > max_bytes:
                skipped += 1
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            skipped += 1
            continue
        if step is not None:
            step(rel)
        try:
            got = workspace.index_source(text, rel, root=root)
            done += 1
            chunks += int(getattr(got, "chunks", 0) or 0)
        except Exception as exc:                    # noqa: BLE001
            failed.append("%s: %s" % (rel, str(exc)[:120]))
    # A link resolves against the pages held when it is written, so an
    # importer indexed before what it imports has no edge yet: one relink
    # after the folder turns those on (`test_source_corpus`: 96 -> 223 edges
    # on this codebase).
    relinked = {}
    if done and relink:
        try:
            relinked = workspace.store.relink()
        except Exception as exc:                    # noqa: BLE001
            relinked = {"error": str(exc)[:160]}
    return {"root": root, "modules": done, "chunks": chunks, "skipped": skipped,
            "failed": failed[:10], "failed_n": len(failed), "relink": relinked}


def index_package(workspace, name: str, **kw) -> Dict:
    """An installed package, as `code://pypi/<name>/...`."""
    folder = package_dir(name)
    if folder is None:
        return {"root": "pypi/%s" % name, "error": "no installed package folder for %r" % name}
    got = index_tree(workspace, folder, "pypi/%s" % name, **kw)
    got["folder"] = str(folder)
    return got


def code_tree_edges(urls: Iterable[str]) -> List[Tuple[str, str]]:
    """(module url, parent url): the directory tree over the code pages held.

    A module's parent is its own folder's `__init__.py` (a package's
    `__init__` hangs from the folder above); when that is not held, the
    nearest held one further up. A module with no held package above it is a
    root. Only urls in `urls` are named, so the edges never point at a page
    the store does not have.
    """
    held = set(urls)
    by_root: Dict[str, set] = {}
    for u in held:
        got = source_path_of(u)
        if got:
            by_root.setdefault(got[0], set()).add(got[1])
    out: List[Tuple[str, str]] = []
    for root, paths in by_root.items():
        for rel in paths:
            folder = dirname(rel)
            if rel.endswith("/__init__.py") or rel == "__init__.py":
                folder = dirname(folder)
            while True:
                cand = (folder + "/__init__.py") if folder else "__init__.py"
                if cand != rel and cand in paths:
                    out.append(("code://%s/%s" % (root, rel), "code://%s/%s" % (root, cand)))
                    break
                if not folder:
                    break
                folder = dirname(folder)
    return out
