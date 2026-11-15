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


# ---- the outline: a note's own recursion, unfolded one rank at a time ------
#
# PLUGIN_GOAL 159: unfolding black boxes "extended for the general compilation
# case ... any recursive structures that we have already in our database for
# code, markdowns, etc, but also including the notebook cells themselves". A
# note's recursion is its headings (`vault.py` addresses a heading as a
# section that holds what follows it) and its cells; a cell's is its inputs
# (the fence's `{ref}`s), its definitions and its output. Each rank names the
# next as a `{ref}` in Obsidian's own link grammar -- `{Note#Heading#Sub}`,
# `{Note#cell 2}`, `{Note#cell 2#f}` -- so a right-click opens it in place.
#
# MIRRORED BY HAND in `obsidian-plugin/src/outline.ts` (the plugin unfolds a
# vault note from its own text). Both are scored against one fixture:
# `tests/fixtures/outline_note.md` -> `outline_expected.json`.

_HEAD = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_CELL = re.compile(r"^cell\s+(\d+)$", re.I)
_FENCE_LINE = re.compile(r"^(\s*)(`{3,}|~{3,})\s*(\S*)(.*)$")
_OUT_OPEN = re.compile(r"^\s*<!--\s*nb-output\s+([^>]*?)\s*-->\s*$")
_OUT_CLOSE = re.compile(r"^\s*<!--\s*/nb-output\s*-->\s*$")
_DEF = re.compile(r"^(\s*)(async\s+def|def|class)\s+(\w+)")
_IMPORT = re.compile(r"^(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))")
_ASSIGN = re.compile(r"^([A-Za-z_]\w*)\s*(?::[^=]+)?=(?!=)")
_PY = {"python", "py", "python3", ""}
_QUOTES = ('"' * 3, "'" * 3)
#: Planted: a note unfolds flat (its first lines), as before the outline.
PLANT_FLAT_OUTLINE = [False]


def _clean(h: str) -> str:
    """A heading as an address segment: what would split or close a ref goes."""
    return re.sub(r"\s+", " ", re.sub(r"[#{}\[\]|^]", " ", h)).strip()


def _braces(t: str) -> str:
    """Code and output shown, not addressed: a brace would read as a `{ref}`."""
    return t.replace("{", "｛").replace("}", "｝")


def _cap(out: List[str], limit: int) -> List[str]:
    return out if len(out) <= limit else out[:limit - 1] + ["(+%d more)" % (len(out) - limit + 1)]


def _body(text: str) -> List[str]:
    NL = chr(10)
    body = (text or "").replace(chr(13), "")
    if body.startswith("---"):
        end = body.find(NL + "---", 3)
        if end >= 0:
            body = body[end + 4:]
    return body.split(NL)


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _scan(lines: List[str]):
    """Cells (fences that are not outputs), each with its output, and the
    headings outside both: `(cells, heads, skip)`."""
    cells, heads, skip = [], [], {}
    i, n = 0, len(lines)
    while i < n:
        f = _FENCE_LINE.match(lines[i])
        if f:
            marker, j = f.group(2), i + 1
            while j < n:
                c = _FENCE_LINE.match(lines[j])
                if c and c.group(2)[0] == marker[0] and len(c.group(2)) >= len(marker):
                    break
                j += 1
            close = min(j, n - 1)
            cell = {"n": len(cells) + 1, "open": i, "close": close, "lang": (f.group(3) or "").lower(),
                    "body": lines[i + 1:j], "out": None,
                    "refs": [r.strip() for r in re.findall(r"\{([^{}]+)\}", f.group(4) or "") if r.strip()]}
            for k in range(i, close + 1):
                skip[k] = cell
            cells.append(cell)
            i = close + 1
            # Its output (`outputs.ts`): the next non-blank line opens a marker
            # that has a closer.
            k = i
            while k < n and not lines[k].strip():
                k += 1
            if k < n and _OUT_OPEN.match(lines[k]):
                z = next((z for z in range(k + 1, n) if _OUT_CLOSE.match(lines[z])), None)
                if z is not None:
                    cell["out"] = lines[k + 1:z]
                    for q in range(k, z + 1):
                        skip[q] = "out"
                    i = z + 1
            continue
        h = _HEAD.match(lines[i])
        if h and _clean(h.group(2)):
            heads.append((i, len(h.group(1)), _clean(h.group(2))))
        i += 1
    return cells, heads, skip


def _section(lines, heads, skip, lo, hi, base, prefix, limit):
    hs = [h for h in heads if lo <= h[0] < hi]
    level = min((h[1] for h in hs), default=0)
    tops = [h for h in hs if h[1] == level]
    first = tops[0][0] if tops else hi
    lead_cap = 3 if tops else limit + 1
    out: List[str] = []
    k = lo
    while k < first and len(out) < lead_cap:
        c = skip.get(k)
        if isinstance(c, dict):
            out.append("cell %d%s\t{%s#cell %d}" % (c["n"], (" " + c["lang"]) if c["lang"] else "", base, c["n"]))
            k = c["close"] + 1
            continue
        t = lines[k].strip()
        if c is None and t and not t.startswith(("<!--", "|", "---")):
            out.append(t.lstrip("#> ").replace(chr(9), " ")[:120])
        k += 1
    for _, _, text in tops:
        out.append("%s\t{%s#%s}" % (text, prefix, text))
    return _cap(out, limit)


def _cell(c, prefix, rest, limit):
    out = [] if rest else ["input\t{%s}" % r for r in c["refs"]]
    code = list(c["body"])
    py = c["lang"] in _PY
    for name in rest:
        if not py:
            return None
        base = min((_indent(l) for l in code if l.strip()), default=0)
        hit = next((j for j, l in enumerate(code)
                    if (m := _DEF.match(l)) and len(m.group(1)) == base and m.group(3) == name), None)
        if hit is None:
            return None
        body = []
        for l in code[hit + 1:]:
            if l.strip() and _indent(l) <= base:
                break
            body.append(l)
        out = ["signature\t" + _braces(code[hit].strip().rstrip(":"))[:120]]
        k = next((j for j, l in enumerate(body) if l.strip()), None)
        if k is not None and body[k].strip()[:3] in _QUOTES:
            first = body[k].strip()
            doc = first[3:].split(first[:3])[0].strip()
            if doc:
                out.append("doc\t" + _braces(doc)[:120])
            body = body[:k] + body[k + 1:]
        code, prefix = body, prefix + "#" + name
    base = min((_indent(l) for l in code if l.strip()), default=0)
    rows = []
    if py:
        for l in code:
            if not l.strip() or _indent(l) != base:
                continue
            s = l.strip()
            m = _IMPORT.match(s)
            if m and not rest:
                rows.append("import\t" + (m.group(1) or m.group(2)))
                continue
            d = _DEF.match(s)
            if d:
                rows.append("%s %s\t{%s#%s}" % ("class" if d.group(2) == "class" else "def", d.group(3), prefix, d.group(3)))
                continue
            # A cell's top-level names are what it hands the cells after it.
            a = _ASSIGN.match(s)
            if a and not rest:
                rows.append("var\t" + a.group(1))
    if not rows:
        rows = [_braces(l[base:].rstrip().replace(chr(9), "    "))[:120] for l in code if l.strip()][:6]
    out += rows
    if not rest and c["out"] is not None:
        shown = next((l.strip() for l in c["out"] if l.strip() and not _FENCE_LINE.match(l)), "")
        out.append("output\t" + _braces(shown)[:120])
    return _cap(out, limit)


def outline(text: str, name: str, limit: int = 12) -> Optional[List[str]]:
    """The rank-1 lines of `name` -- `Note`, `Note#Heading#Sub`, `Note#cell N`,
    `Note#cell N#def` -- in `text`, Note's own text. None: the address names
    nothing in it (a heading or a cell that is not there)."""
    lines = _body(text)
    cells, heads, skip = _scan(lines)
    base, *segs = [s.strip() for s in (name or "").split("#")]
    lo, hi, prefix = 0, len(lines), base
    for i, seg in enumerate(segs):
        m = _CELL.match(seg)
        if m:
            n = int(m.group(1))
            if not 1 <= n <= len(cells):
                return None
            return _cell(cells[n - 1], base + "#cell %d" % n, segs[i + 1:], limit)
        hs = [h for h in heads if lo <= h[0] < hi]
        level = min((h[1] for h in hs), default=0)
        want = _clean(seg).lower()
        # The rank below first; then any deeper heading by that name, as an
        # Obsidian link skips levels (`Note#Insert` for `# Building / ## Insert`).
        hit = next((h for h in hs if h[1] == level and h[2].lower() == want), None) \
            or next((h for h in hs if h[2].lower() == want), None)
        if hit is None:
            return None
        end = next((h[0] for h in hs if h[0] > hit[0] and h[1] <= hit[1]), hi)
        lo, hi, prefix = hit[0] + 1, end, prefix + "#" + hit[2]
    return _section(lines, heads, skip, lo, hi, base, prefix, limit)


def rank1(text: str, limit: int = 12, name: str = "") -> List[str]:
    """A target's RANK-1 lines (UR O.1a, M.6; G-278): what internalizing a
    `{ref}` reveals. A slate's first level of fields (`key<TAB>value`, the
    title's children); any other text, its first lines -- headings and the
    starts of paragraphs -- each cut to 120 characters. Frontmatter skipped.
    Given the ref's `name`, any other text unfolds by its OUTLINE (above):
    headings and cells, each a `{ref}` to the next rank."""
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
    if name and not PLANT_FLAT_OUTLINE[0]:
        got = outline(text, name, limit)
        return got if got is not None else []
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
