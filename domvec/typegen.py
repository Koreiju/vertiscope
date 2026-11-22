"""Types from trie-path PATTERNS (PLUGIN_GOAL 186f, ruling T-15, 2026-11-08).

"we can then create new nodes as ontologies and aggregates of multiple
patricia trie paths that themselves access a multitude of pages, which then
give way to auto-rendered strict pydantic aggregate types" (PG 4168-4171).

Ruling T-15: the unit is a PATTERN over the trie. An xpath with ``[*]``
steps, e.g. ``/html/body/main/article[*]``: every address whose xpath has a
prefix matching it is part of one INSTANCE (the matched prefix, per page);
the rest of its path, with its indices generalised to ``[*]``, plus its
accessor, is a FIELD. A field's type is inferred from the values every
instance holds there. The output is the source of a pydantic model.

Reads from the trie (addresses: url, xpath, accessor, value); writes
nothing. Pure functions over rows, so the sidecar and the tests share them.
"""
from __future__ import annotations

import keyword
import re
from typing import Dict, Iterable, List, Optional, Tuple

#: Planted: fields keyed on the exact remainder (indices kept), so instances
#: whose items differ only in position never share a field.
PLANT_NO_GENERALISE = [False]

_IDX = re.compile(r"\[\d+\]")
_PIECE = re.compile(r"~\d+(?=\||$)")
_AT = re.compile(r"@\d+")


def pattern_regex(pattern: str) -> re.Pattern:
    """`[*]` matches any index; an unindexed step matches only index 1 or none."""
    out = []
    for step in pattern.strip("/").split("/"):
        if step.endswith("[*]"):
            out.append(re.escape(step[:-3]) + r"\[\d+\]")
        elif "[" in step:
            out.append(re.escape(step))
        else:
            out.append(re.escape(step) + r"(?:\[1\])?")
    return re.compile("^/" + "/".join(out) + r"(?=/|$)")


def prefix_of(pattern: str) -> str:
    """The literal part before the first wildcard (for a store-side filter)."""
    head = pattern.split("[*]", 1)[0]
    return head[: head.rfind("/") + 1] if "/" in head else head


def field_name(rest: str, accessor: str) -> str:
    # A piece mark (`text()~1196`, `ContentAddress.whole`): a long leaf split
    # at character 1196 is still ONE leaf, so one field. Left in, one
    # paragraph became seven Optional fields on the live store (G-388,
    # 2026-11-22). Stripped wherever it sits, before or after the `|`.
    accessor = _PIECE.sub("", accessor or "text").split("|", 1)[0]
    if not PLANT_NO_GENERALISE[0]:
        # `text()@1196` is the sensor's leaf for a URL found at offset 1196
        # of a text (address.py `whole`): a leaf of its own, so a field of
        # its own -- but the offset is a position, as `[n]` is. Seen live:
        # one paragraph's URLs became seven fields, one per offset.
        accessor = _AT.sub("@url", _IDX.sub("", accessor))
    rest = rest if PLANT_NO_GENERALISE[0] else _IDX.sub("", rest)
    parts = [p for p in re.split(r"[/\[\]@|.:\-\s]+", rest + "_" + (accessor or "text")) if p]
    name = "_".join(parts).lower() or "value"
    name = re.sub(r"_+", "_", re.sub(r"\W", "_", name)).strip("_") or "value"
    if name[0].isdigit() or keyword.iskeyword(name):
        name = "f_" + name
    return name


def _type_of(values: List[str]) -> str:
    vs = [v.strip() for v in values if v is not None and v.strip()]
    if not vs:
        return "str"
    if all(re.fullmatch(r"-?\d+", v) for v in vs):
        return "int"
    if all(re.fullmatch(r"-?\d+(?:\.\d+)?", v.replace(",", "")) for v in vs):
        return "float"
    if all(re.match(r"https?://", v) for v in vs):
        return "HttpUrl"
    return "str"


def instances(rows: Iterable[Tuple[str, str, str, str]], pattern: str,
              provenance: Optional[Dict[str, Tuple[str, str, str]]] = None) -> Dict[Tuple[str, str], Dict[str, List[str]]]:
    """(url, instance xpath) -> field -> values, from address rows.

    `provenance`, when given, is filled with one address per field -- (url,
    xpath, accessor) -- so a field leads back to the trie leaf it was read
    from rather than only to the name made of it.
    """
    rx = pattern_regex(pattern)
    out: Dict[Tuple[str, str], Dict[str, List[str]]] = {}
    for url, xpath, accessor, value in rows:
        m = rx.match(xpath or "")
        if not m:
            continue
        inst = (url, m.group(0))
        f = field_name(xpath[m.end():], accessor)
        out.setdefault(inst, {}).setdefault(f, []).append(value or "")
        if provenance is not None and f not in provenance:
            provenance[f] = (url, xpath, accessor or "")
    return out


def model(rows: Iterable[Tuple[str, str, str, str]], pattern: str, name: str = "Item") -> Dict:
    """The pydantic model the pattern generates, and what it was made from.

    A field every instance holds is required; any other is Optional.
    """
    prov: Dict[str, Tuple[str, str, str]] = {}
    inst = instances(rows, pattern, prov)
    n = len(inst)
    counts: Dict[str, int] = {}
    values: Dict[str, List[str]] = {}
    for fields in inst.values():
        for f, vs in fields.items():
            counts[f] = counts.get(f, 0) + 1
            values.setdefault(f, []).extend(vs)
    cls = re.sub(r"\W", "", name.title().replace(" ", "")) or "Item"
    lines = ["from typing import Optional", "from pydantic import BaseModel, ConfigDict, HttpUrl", "", "",
             f"class {cls}(BaseModel):",
             f'    """{n} instances of {pattern}"""',
             # G-388: STRICT. An agent handing "12" where an int was mined is
             # told so, not silently coerced; `objects()` does the one
             # conversion from the trie's string values, by the mined type.
             '    model_config = ConfigDict(strict=True, extra="forbid")']
    fields = sorted(counts, key=lambda f: (-counts[f], f))
    kept = fields
    for f in kept:
        t = _type_of(values[f])
        if counts[f] == n:
            lines.append(f"    {f}: {t}")
        else:
            lines.append(f"    {f}: Optional[{t}] = None")
    pages = len({u for u, _ in inst})
    return {"pattern": pattern, "class": cls, "instances": n, "pages": pages, "fields": len(kept),
            "required": sum(1 for f in kept if counts[f] == n), "source": "\n".join(lines) + "\n",
            "types": {f: _type_of(values[f]) for f in kept},
            "provenance": {f: list(prov[f]) for f in kept}}


# ---------------------------------------------------------------------------
# G-388: patterns MINED, not typed in. T-15 answers "what type does THIS
# pattern make"; the reader had to know the pattern. The miner reads every
# address row and proposes the patterns whose record root repeats on two or
# more pages with a shared shape -- the "aggregates of multiple patricia trie
# paths that themselves access a multitude of pages" of 186f.
# ---------------------------------------------------------------------------

#: Planted: every repeated root is a type, shared shape or not, and one page
#: is enough -- so a list repeated on a single page, and a pattern whose
#: instances share no field, both come back. The tests assert they do.
PLANT_NO_SHAPE = [False]

_STEP_IDX = re.compile(r"^([A-Za-z][\w:.-]*)\[(\d+)\]$")


def wildcard(xpath: str) -> str:
    """Every positional index made `[*]`: the pattern an address belongs to."""
    return _IDX.sub("[*]", xpath or "")


def mine(rows: Iterable[Tuple[str, str, str, str]], min_pages: int = 2,
         min_instances: int = 3, share: float = 0.5, min_fields: int = 2,
         limit: int = 50) -> List[Dict]:
    """Patterns that are types, best first.

    A ROOT is an element step that carries an explicit index (`li[3]`): a
    position among siblings of one tag, which is what a repeated record looks
    like in an xpath. Its pattern is the prefix up to and including it with
    every index made `[*]`; an INSTANCE is the concrete prefix on one page; a
    FIELD is the rest of an address path past it, generalised, plus its
    accessor -- named by `field_name`, exactly as `model()` names it, so a
    mined pattern re-run through `model()` yields the same fields.

    A pattern is a type when its instances span `min_pages` pages, number at
    least `min_instances`, and share at least `min_fields` fields each held
    by `share` of them. The shape test is what makes this a type and not
    merely a repeat: a page's nth `<div>` children are instances of `div[*]`
    whether or not they have anything in common.
    """
    by_pat: Dict[str, Dict[Tuple[str, str], set]] = {}
    # Names and patterns memoised for this call only (a plant flipped
    # between calls must still be seen): the same remainder recurs under
    # every instance, and naming it is the regex work that dominated (9.1 s
    # of 9.7 on the 245k-row store before this).
    names: Dict[Tuple[str, str], str] = {}
    pats: Dict[str, str] = {}
    for url, xpath, accessor, _value in rows:
        if not xpath:
            continue
        steps = xpath.split("/")
        for i in range(1, len(steps) - 1):
            if not _STEP_IDX.match(steps[i]):
                continue
            concrete = "/".join(steps[: i + 1])
            key = ("/" + "/".join(steps[i + 1:]), accessor or "")
            f = names.get(key)
            if f is None:
                f = names[key] = field_name(key[0], accessor)
            pat = pats.get(concrete)
            if pat is None:
                pat = pats[concrete] = wildcard(concrete)
            by_pat.setdefault(pat, {}).setdefault((url, concrete), set()).add(f)
    plant = PLANT_NO_SHAPE[0]
    out = []
    for pat, inst in by_pat.items():
        pages = len({u for u, _ in inst})
        n = len(inst)
        if n < min_instances or (not plant and pages < min_pages):
            continue
        counts: Dict[str, int] = {}
        for fields in inst.values():
            for f in fields:
                counts[f] = counts.get(f, 0) + 1
        shared = sorted((f for f, c in counts.items() if c >= share * n),
                        key=lambda f: (-counts[f], f))
        if not plant and len(shared) < min_fields:
            continue
        out.append({"pattern": pat, "instances": n, "pages": pages,
                    "fields": shared, "score": n * max(1, len(shared))})
    out.sort(key=lambda r: (-r["score"], r["pattern"]))
    return out[:limit]


def load(source: str):
    """The class a `model()` source defines -- what an agent operates on."""
    from pydantic import BaseModel
    ns: Dict = {}
    exec(compile(source, "<typegen>", "exec"), ns)  # noqa: S102 -- source generated above, not read in
    cls = next(v for v in ns.values()
               if isinstance(v, type) and issubclass(v, BaseModel) and v is not BaseModel)
    # The class was defined in a bare namespace, not a module, so pydantic
    # cannot find `HttpUrl`/`Optional` by the module it names; hand it them.
    cls.model_rebuild(_types_namespace=ns)
    return cls


def _coerce(value: str, t: str):
    v = (value or "").strip()
    if t == "int":
        return int(v)
    if t == "float":
        return float(v.replace(",", ""))
    return v


def objects(rows: Iterable[Tuple[str, str, str, str]], pattern: str, name: str = "Item") -> Dict:
    """Every instance as a validated strict object, and every one that is not.

    The trie holds strings; the mined type says what each field is. The one
    conversion is here, by that type, so the strict model sees an int where an
    int was mined and refuses anything else.
    """
    rows = list(rows)
    m = model(rows, pattern, name)
    cls = load(m["source"])
    good, bad = [], []
    for (url, root), fields in sorted(instances(rows, pattern).items()):
        try:
            data = {f: _coerce(next((v for v in vs if (v or "").strip()), vs[0]), m["types"][f])
                    for f, vs in fields.items() if f in m["types"]}
            good.append({"url": url, "root": root, "object": cls.model_validate(data)})
        except Exception as exc:                    # noqa: BLE001
            bad.append({"url": url, "root": root, "error": str(exc)[:200]})
    return {"model": m, "cls": cls, "objects": good, "rejected": bad}
