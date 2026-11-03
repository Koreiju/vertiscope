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


#: The reader's vault: [folder, name], told by the plugin (`POST /vault_root`).
VAULT = ["", ""]
#: Planted (G-277): a vault note's text from the store's chunks, as before.
PLANT_STORED_NOTE = [False]


def _note_text(url: str):
    """A vault note's OWN text, when the vault is reachable: the store's chunks
    flatten a slate's tabs and lines, so a `{ref}` to one revealed one line."""
    root, name = VAULT
    if PLANT_STORED_NOTE[0] or not root or not url.startswith("vault://"):
        return None
    rest = url[len("vault://"):]
    vname, _, rel = rest.partition("/")
    if name and vname != name:
        return None
    from pathlib import Path
    base = Path(root).resolve()
    p = (base / rel).resolve()
    if base not in p.parents or not p.is_file():
        return None
    try:
        return p.read_text(encoding="utf-8")[:MAX_CHARS]
    except OSError:
        return None


def _page_text(store, url: str):
    chunks = [c for c in store.chunks(url) if not c.redundant]
    chunks.sort(key=lambda c: (c.xpath, c.part))
    return "\n\n".join(c.md or "" for c in chunks)[:MAX_CHARS], [c.cid for c in chunks[:50]]


def titled(workspace, name: str) -> bool:
    """Is there an artifact CALLED `name` in the store -- a vault note by its
    file name, a page by its title (or the title's head, "Radix tree" for
    "Radix tree - Wikipedia")? What a slate's `{ref}` may name besides its own
    module (G-297: a reference to NOTHING is the error, not one to the store)."""
    want = (name or "").strip().lower()
    if not want:
        return False
    for url, title in workspace.store.page_titles().items():
        if url.startswith("vault://") and url.rsplit("/", 1)[-1].rsplit(".", 1)[0].lower() == want:
            return True
        t = (title or "").strip().lower()
        if t == want or t.startswith(want + " -") or t.startswith(want + " |") or t.startswith(want + " —"):
            return True
    return False


def resolve(workspace, name: str, allow=None, search=None) -> Optional[Dict]:
    """The node `name` refers to, with its text: `{kind, url, cids, value}`.

    `allow(url, cid)` (PLUGIN_GOAL 79): which artifacts a ref may resolve to --
    the ego's alone, or the web's -- as the cell's note toggles it. None:
    any, as before."""
    ok = allow or (lambda url, cid: True)
    want = (name or "").strip().lower()
    if not want:
        return None
    store = workspace.store
    titles = store.page_titles()
    # A vault note by its title (the file's name), then any page by its title.
    for url in titles:
        if url.startswith("vault://") and url.rsplit("/", 1)[-1].rsplit(".", 1)[0].lower() == want and ok(url, ""):
            text, cids = _page_text(store, url)
            own = _note_text(url)
            return {"kind": "note", "url": url, "cids": cids, "value": own if own is not None else text}
    for url, title in titles.items():
        if (title or "").strip().lower() == want and ok(url, ""):
            text, cids = _page_text(store, url)
            return {"kind": "page", "url": url, "cids": cids, "value": text}
    # The halo's answer: retrieval's top hit.
    # A search racing a live write can raise (the index mid-swap); that is
    # not "nothing is called that" -- asked again once it settles (G-283's
    # anchored plan read a transient failure as an unresolved name).
    hits = []
    for attempt in range(3):
        try:
            # `search`: the ranking to ask -- the ego's own, under `maps: ego`.
            hits = search(name) if search is not None else workspace.search(name, k=1 if allow is None else 32)
            break
        except Exception as e:                      # noqa: BLE001
            import sys, time
            print(f"[refs] search {name!r} failed ({type(e).__name__}: {e}); retry {attempt + 1}", file=sys.stderr)
            time.sleep(0.25 * (attempt + 1))
    for h in hits or []:
        cid = getattr(h, "cid", None) or getattr(h, "chunk", "")
        c = store.chunk(cid) if cid else None
        if c is not None and ok(c.url, cid):
            return {"kind": "retrieved", "url": c.url, "cids": [cid], "value": (c.md or "")[:MAX_CHARS]}
    return None


def rank1(text: str, limit: int = 12) -> List[str]:
    """A target's RANK-1 lines (UR O.1a, M.6; G-278): what internalizing a
    `{ref}` reveals. A slate's first level of fields (`key<TAB>value`, the
    title's children); any other text, its first lines -- headings and the
    starts of paragraphs -- each cut to 120 characters. Frontmatter skipped."""
    NL, TAB = chr(10), chr(9)
    body = (text or "").replace(chr(13), "")
    if body.startswith("---"):
        end = body.find(NL + "---", 3)
        if end >= 0:
            body = body[end + 4:]
    from domvec.slate import parse_slate
    try:
        fields = parse_slate(body.strip(NL), False)
    except Exception:                               # noqa: BLE001
        fields = []
    if len(fields) == 1 and fields[0].children:
        out = []
        for f in fields[0].children[:limit]:
            v = f.value if isinstance(f.value, str) else ("{%s}" % f.key if f.children else "")
            out.append((f.key + (TAB + v if v else "")).replace(NL, " ")[:120])
        return out
    out = []
    for line in body.splitlines():
        t = line.strip()
        if t and not t.startswith(("<!--", "```", "~~~", "|", "---")):
            out.append(t.lstrip("#> ").replace(TAB, " ")[:120])
        if len(out) >= limit:
            break
    return out


def bind(workspace, names: List[str], sample: Optional[int] = None, allow=None, search=None) -> Dict:
    """The prelude that binds each named ref in a kernel, and what was bound.

    `sample` (G-283, the rollout; RESERVOIR_DESIGN §4: "a cell whose `{ref}`
    points at an iterable runs once per sample on play ... Only an external
    `{ref}` iterates"): the FIRST ref is the iterable -- bound to its
    `sample`-th chunk alone, its input that one chunk -- and the reply says
    how many samples it has. The other refs bind whole, as always.
    """
    lines, bound, inputs = [], [], []
    for k, name in enumerate(dict.fromkeys(n for n in names if n and n.strip())):
        got = resolve(workspace, name, allow, search)
        var = var_name(name)
        if got is None:
            bound.append({"name": name, "var": var, "kind": "unresolved"})
            continue
        if k == 0 and sample is not None:
            cids = got["cids"]
            n = len(cids)
            if 0 <= int(sample) < n:
                c = workspace.store.chunk(cids[int(sample)])
                value = (c.md or "") if c is not None else ""
                lines.append("%s = %r" % (var, value))
                bound.append({"name": name, "var": var, "kind": got["kind"], "url": got["url"],
                              "chars": len(value), "sample": int(sample), "samples": n})
                inputs.append((name, cids[int(sample)]))
            else:
                bound.append({"name": name, "var": var, "kind": got["kind"], "url": got["url"],
                              "sample": int(sample), "samples": n, "done": True})
            continue
        lines.append("%s = %r" % (var, got["value"]))
        bound.append({"name": name, "var": var, "kind": got["kind"], "url": got["url"],
                      "chars": len(got["value"])})
        inputs += [(name, cid) for cid in got["cids"]]
    return {"prelude": chr(10).join(lines), "bound": bound, "inputs": inputs}
