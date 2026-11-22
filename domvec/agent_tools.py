"""The kernel's tool panels as smolagents tools (G-384, G-378; spec §8, §11d).

The agent calls exactly what a note's kernel calls: the objects are built
from the kernel's own bootstrap (`kernel_objects.boot`), so a tool here IS
the tool panel -- read-only on the store, its body never shown to the model
(mortegon F.6: `read_only`, `no_datablock`, a pointer to the live callable).
Only each call's signature and one-line purpose reach the prompt, which is
the ~25-line tool surface's job (G-377).

In trie terms: every call reads the store through the sidecar's routes;
nothing here writes it.
"""

from __future__ import annotations

from typing import Dict, List

from smolagents import Tool


def kernel(base: str) -> Dict:
    """The kernel's objects, bound to the sidecar at `base` (no request is made)."""
    from .obsidian import kernel_objects as ko
    ns: Dict = {}
    exec(compile(ko.boot(base), "<kernel boot>", "exec"), ns)
    return ns


class _Search(Tool):
    name = "search"
    description = "Ranked chunks from the store for a query: a list of {cid, url, text}."
    inputs = {"query": {"type": "string", "description": "what to look for"},
              "k": {"type": "integer", "description": "how many results", "nullable": True}}
    output_type = "array"

    def __init__(self, ns):
        super().__init__()
        self._ns = ns

    def forward(self, query: str, k: int = 5) -> List[dict]:
        return self._ns["search"](query, k=int(k or 5))


class _Cypher(Tool):
    name = "cypher"
    description = "A read-only Cypher query over the store's graph; writes are refused. Returns rows."
    inputs = {"query": {"type": "string", "description": "e.g. MATCH (p:Page) RETURN count(p)"}}
    output_type = "array"

    def __init__(self, ns):
        super().__init__()
        self._ns = ns

    def forward(self, query: str) -> list:
        return self._ns["Database"].cypher(query)


class _Chunks(Tool):
    name = "page_chunks"
    description = "The chunk ids the store holds for one page url."
    inputs = {"url": {"type": "string", "description": "a stored page's url"}}
    output_type = "array"

    def __init__(self, ns):
        super().__init__()
        self._ns = ns

    def forward(self, url: str) -> list:
        return self._ns["WebBrowser"].chunks(url)


def tools(base: str) -> List[Tool]:
    ns = kernel(base)
    return [_Search(ns), _Cypher(ns), _Chunks(ns)]
