"""`{ref}` -> the node it names, through the trie's address space (G-279).

`docs/RESERVOIR_DESIGN.md` §3.2, §4: a `{ref}` names a node, and every node
here already has an address -- a stored page, a vault note, a code object. A
cell declares its inputs as `{ref}` tokens on its fence line
(```` ```python {Radix tree} {query} ````) -- not in the code, where braces are
Python's own -- and each is resolved here and bound into the note's kernel
as a variable named after it.

Resolution, in order: a vault note whose title is the name; a stored page
whose title is the name; retrieval's top hit for the name (the halo's
answer when the name is new). Case-insensitive on titles.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

#: Bound text is capped: a kernel variable is not the place for a corpus.
MAX_CHARS = 200_000


def var_name(name: str) -> str:
    """The Python variable a `{ref}` is bound to: `Radix tree` -> `radix_tree`."""
    v = re.sub(r"\W+", "_", (name or "").strip()).strip("_").lower() or "ref"
    return "_" + v if v[0].isdigit() else v


def _page_text(store, url: str):
    chunks = [c for c in store.chunks(url) if not c.redundant]
    chunks.sort(key=lambda c: (c.xpath, c.part))
    return "\n\n".join(c.md or "" for c in chunks)[:MAX_CHARS], [c.cid for c in chunks[:50]]


def resolve(workspace, name: str) -> Optional[Dict]:
    """The node `name` refers to, with its text: `{kind, url, cids, value}`."""
    want = (name or "").strip().lower()
    if not want:
        return None
    store = workspace.store
    titles = store.page_titles()
    # A vault note by its title (the file's name), then any page by its title.
    for url in titles:
        if url.startswith("vault://") and url.rsplit("/", 1)[-1].rsplit(".", 1)[0].lower() == want:
            text, cids = _page_text(store, url)
            return {"kind": "note", "url": url, "cids": cids, "value": text}
    for url, title in titles.items():
        if (title or "").strip().lower() == want:
            text, cids = _page_text(store, url)
            return {"kind": "page", "url": url, "cids": cids, "value": text}
    # The halo's answer: retrieval's top hit.
    try:
        hits = workspace.search(name, k=1)
    except Exception:                               # noqa: BLE001
        hits = []
    for h in hits or []:
        cid = getattr(h, "cid", None) or getattr(h, "chunk", "")
        c = store.chunk(cid) if cid else None
        if c is not None:
            return {"kind": "retrieved", "url": c.url, "cids": [cid], "value": (c.md or "")[:MAX_CHARS]}
    return None


def bind(workspace, names: List[str]) -> Dict:
    """The prelude that binds each named ref in a kernel, and what was bound."""
    lines, bound, inputs = [], [], []
    for name in dict.fromkeys(n for n in names if n and n.strip()):
        got = resolve(workspace, name)
        var = var_name(name)
        if got is None:
            bound.append({"name": name, "var": var, "kind": "unresolved"})
            continue
        lines.append("%s = %r" % (var, got["value"]))
        bound.append({"name": name, "var": var, "kind": got["kind"], "url": got["url"],
                      "chars": len(got["value"])})
        inputs += [(name, cid) for cid in got["cids"]]
    return {"prelude": "\n".join(lines), "bound": bound, "inputs": inputs}
