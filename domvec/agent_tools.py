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


# The editor's five calls as tools (G-384: "the editor's five calls (spec
# §11d) as tools"). An agent's code runs in smolagents' executor, not a note's
# kernel, so a call cannot ride a cell's reply the way a kernel's does
# (G-386). Each call is recorded as an ASK on the run; `/agent_status` hands
# the asks to the plugin, which carries them out by `EditorCalls.carry` -- the
# same methods the reader's gestures use. Planted `PLANT_NO_EDITOR_TOOLS`:
# the agent gets the read-only tools only.
PLANT_NO_EDITOR_TOOLS = [False]


def _ask_tool(tool_name: str, desc: str, ins: dict, make):
    class _T(Tool):
        name = tool_name
        description = desc
        inputs = ins
        output_type = "string"

        def __init__(self, asks):
            super().__init__()
            self._asks = asks

        def forward(self, **kw) -> str:
            self._asks.append({tool_name: make(**kw)})
            return "asked: %s" % tool_name

    # smolagents validates forward's signature against `inputs`.
    args = ", ".join(("%s=None" % k) if v.get("nullable") else k for k, v in ins.items())
    src = "def forward(self, %s):\n    return _T._call(self, %s)\n" % (args, ", ".join("%s=%s" % (k, k) for k in ins))
    ns = {"_T": _T}
    exec(src, ns)
    _T._call = _T.forward
    _T.forward = ns["forward"]
    return _T


_S = {"type": "string"}
_EDITOR = [
    ("create", "Make a card on the 2D plane: a note `name` holding `body` (kind 'notebook' for a python cell, else 'slate').",
     {"name": dict(_S, description="the card's name"), "body": dict(_S, description="its text or code"),
      "kind": dict(_S, description="'notebook' or 'slate'", nullable=True)},
     lambda name, body, kind=None: {"name": name, "body": body, "kind": kind or "notebook"}),
    ("link", "Link card a to card b with a compiled link (a cell in a reading b).",
     {"a": dict(_S, description="the reading card"), "b": dict(_S, description="the card read")},
     lambda a, b: [a, b]),
    ("invoke", "Run every python cell of a card, in order.",
     {"name": dict(_S, description="the card")}, lambda name: name),
    ("commit", "Compose cards into a new card whose one cell reads each member.",
     {"name": dict(_S, description="the new card"), "members": {"type": "array", "description": "the member cards' names"}},
     lambda name, members: {"name": name, "members": list(members)}),
    ("review", "Ask the reader a question on a card; their answer is written under it.",
     {"name": dict(_S, description="the card"), "question": dict(_S, description="the question")},
     lambda name, question: [name, question]),
]


def editor_tools(asks: list) -> List[Tool]:
    """The five editor calls, each recording its ask into `asks`."""
    if PLANT_NO_EDITOR_TOOLS[0]:
        return []
    return [_ask_tool(n, d, i, m)(asks) for n, d, i, m in _EDITOR]
