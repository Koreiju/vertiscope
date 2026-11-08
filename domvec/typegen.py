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
    accessor = (accessor or "text").split("|", 1)[0]
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


def instances(rows: Iterable[Tuple[str, str, str, str]], pattern: str) -> Dict[Tuple[str, str], Dict[str, List[str]]]:
    """(url, instance xpath) -> field -> values, from address rows."""
    rx = pattern_regex(pattern)
    out: Dict[Tuple[str, str], Dict[str, List[str]]] = {}
    for url, xpath, accessor, value in rows:
        m = rx.match(xpath or "")
        if not m:
            continue
        inst = (url, m.group(0))
        f = field_name(xpath[m.end():], accessor)
        out.setdefault(inst, {}).setdefault(f, []).append(value or "")
    return out


def model(rows: Iterable[Tuple[str, str, str, str]], pattern: str, name: str = "Item") -> Dict:
    """The pydantic model the pattern generates, and what it was made from.

    A field every instance holds is required; any other is Optional.
    """
    inst = instances(rows, pattern)
    n = len(inst)
    counts: Dict[str, int] = {}
    values: Dict[str, List[str]] = {}
    for fields in inst.values():
        for f, vs in fields.items():
            counts[f] = counts.get(f, 0) + 1
            values.setdefault(f, []).extend(vs)
    cls = re.sub(r"\W", "", name.title().replace(" ", "")) or "Item"
    lines = ["from typing import Optional", "from pydantic import BaseModel, HttpUrl", "", "",
             f"class {cls}(BaseModel):",
             f'    """{n} instances of {pattern}"""']
    fields = sorted(counts, key=lambda f: (-counts[f], f))
    kept = fields
    for f in kept:
        t = _type_of(values[f])
        if counts[f] == n:
            lines.append(f"    {f}: {t}")
        else:
            lines.append(f"    {f}: Optional[{t}] = None")
    if not kept:
        lines.append("    pass")
    pages = len({u for u, _ in inst})
    return {"pattern": pattern, "class": cls, "instances": n, "pages": pages, "fields": len(kept),
            "required": sum(1 for f in kept if counts[f] == n), "source": "\n".join(lines) + "\n"}
