"""Node definitions from the live namespace (G-409; PLUGIN_GOAL 187, UR M.3-M.5,
spec §13d').

The kernel, not a registry, says what nodes exist: every function and class a
note's cells DEFINE is published with its ports, by the rule ComfyUI's
`object_info` and mortegon's M.3 rows share --

* a primitive parameter (int, float, str, bool) with a default -> a WIDGET,
  edited in place;
* a `Literal[...]` parameter -> a CHOICE;
* anything a value cannot be typed into (an object type, no annotation and no
  primitive default) -> a SOCKET;
* the return -> an OUTPUT, its type from the annotation, else `None`
  ("inferred by wiring", M.5);
* a class: its `__init__` parameters as inputs, one output per public method
  (B7), and a `HasTraits` object's traits as widgets.

Imported names are not definitions: a function or class counts only when its
module is the note's own namespace (or its code was compiled from a cell),
and the kernel's base objects (`search`, `create`, ...: the boot, snapshotted
once by the sidecar as `_domvec_boot`) are not the note's.

In trie terms: reads the note kernel's namespace (the values a vault:// page's
cells produced) and writes nothing; the answer is a readout keyed by the note.
"""
from __future__ import annotations

import json

MARK = "\x1edomvec-defs\x1e"

# Runs INSIDE the note's kernel. Self-contained: it imports what it needs, binds
# nothing it leaves behind, and prints one marked JSON line.
SRC = r'''
def __domvec_defs(ns):
    import inspect, json, typing
    PRIM = (int, float, str, bool)
    home = ns.get("__name__", "builtins")
    def tname(t):
        if t is inspect.Parameter.empty or t is inspect.Signature.empty:
            return None
        return getattr(t, "__name__", None) or str(t).replace("typing.", "")
    def port(p, hints):
        t = hints.get(p.name, p.annotation)
        d = {"name": p.name, "type": tname(t)}
        if p.default is not inspect.Parameter.empty:
            try: json.dumps(p.default); d["default"] = p.default
            except Exception: d["default"] = repr(p.default)
        if typing.get_origin(t) is typing.Literal:
            d["kind"] = "choice"; d["options"] = list(typing.get_args(t)); return d
        prim = t in PRIM or (t is inspect.Parameter.empty and isinstance(p.default, PRIM))
        d["kind"] = "widget" if prim and "default" in d else "socket"
        if d["kind"] == "widget" and d["type"] is None:
            d["type"] = type(p.default).__name__
        return d
    def fn(f, skip_self=False):
        try: sig = inspect.signature(f)
        except (TypeError, ValueError): return None
        try: hints = typing.get_type_hints(f, ns)
        except Exception: hints = {}
        ps = [p for p in sig.parameters.values() if p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)]
        if skip_self and ps: ps = ps[1:]
        ret = hints.get("return", sig.return_annotation)
        return {"inputs": [port(p, hints) for p in ps],
                "output": {"type": tname(ret)}, "doc": (inspect.getdoc(f) or "").split("\n")[0]}
    boot = ns.get("_domvec_boot") or {}   # the kernel's base objects, not the note's
    out = []
    for name, obj in list(ns.items()):
        if name.startswith("_") or boot.get(name) == id(obj):
            continue
        if inspect.isfunction(obj) and (obj.__module__ == home or obj.__code__.co_filename == "<cell>"):
            d = fn(obj)
            if d: out.append(dict(d, name=name, node="function"))
        elif inspect.isclass(obj) and obj.__module__ == home:
            init = fn(obj.__init__, skip_self=True) if "__init__" in vars(obj) else {"inputs": [], "output": {}, "doc": ""}
            methods = [m for m, v in vars(obj).items() if inspect.isfunction(v) and not m.startswith("_")]
            outs = [dict({"name": m}, **(fn(getattr(obj, m), skip_self=True) or {})["output"]) for m in methods]
            traits = []
            if hasattr(obj, "class_traits"):
                try:
                    for tn, tr in obj.class_traits().items():
                        if not tn.startswith("_"):
                            traits.append({"name": tn, "kind": "widget", "type": type(tr).__name__, "default": tr.default_value if isinstance(tr.default_value, (int, float, str, bool)) else None})
                except Exception: pass
            out.append({"name": name, "node": "class", "inputs": init["inputs"], "outputs": outs,
                        "traits": traits, "doc": (inspect.getdoc(obj) or "").split("\n")[0]})
    return out
print(%r + __import__("json").dumps(__domvec_defs(globals()), default=repr))
del __domvec_defs
''' % MARK


def parse(reply: dict) -> dict:
    """The kernel's reply to SRC -> {"defs": [...]} or {"error": ...}."""
    if not reply.get("ok"):
        return {"error": reply.get("error") or "the kernel did not answer", "defs": []}
    for line in (reply.get("stdout") or "").split(chr(10)):  # not splitlines: it breaks on the 0x1e mark
        if line.startswith(MARK):
            return {"defs": json.loads(line[len(MARK):])}
    return {"error": "no definitions line", "defs": []}
