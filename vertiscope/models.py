"""Local quantized models as typed graph entities (PLUGIN_GOAL 186a-c, 186j;
G-262, G-264; design `docs/GRAPH_WORKBENCH_DESIGN.md` §4).

Each model has a ROLE, and a role fixes its input and output types and the
parser that turns the model's natural output into them. The guarantee is
mechanical: a parser returns the role's type, or a `TypedResult` whose
`error` says why not -- an output that does not parse is never coerced.

  triplex   text + entity types + predicates -> entities and triples
            (`[1], CITY:San Francisco`, `[1] POPULATION [6]`), linked to the
            chunk the text came from
  chat      prompt -> markdown with code: a HYBRID -- its code blocks go to
            the compact code KG (`code_kg`), its prose may go to triplex
  jev       typed decisions (choice / score / yes-no) read from per-option
            scores -- needs logits, not text: not runnable through gpt4all
            (see the design, §4)

Models load from `MODEL_DIR` (where the sidecar's downloads install them).
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

MODEL_DIR = Path(os.environ.get("VERTISCOPE_MODEL_DIR") or (Path.home() / ".cache" / "gpt4all"))
#: The GPU by default: Triplex on a paragraph took 37-65 s on CPU and 1.8-3.2 s
#: on CUDA (RTX 4070 Laptop, 2026-10-18). A model that will not load there
#: (memory) falls back to CPU rather than failing the run.
MODEL_DEVICE = os.environ.get("VERTISCOPE_MODEL_DEVICE") or "cuda"

ROLES: Dict[str, Dict[str, Any]] = {
    "triplex": {"file": "triplex-Q4_K_M.gguf", "template": "<|user|>\n{msg}<|end|>\n<|assistant|>\n",
                "inputs": {"text": "str", "entity_types": "list[str]", "predicates": "list[str]"},
                "outputs": {"entities": "dict[int, {type, name}]", "triples": "list[{s, p, o}]"}},
    "chat": {"file": "deepseek-coder-6.7b-instruct.Q4_K_M.gguf",
             "template": "You are an AI programming assistant.\n### Instruction:\n{msg}\n### Response:\n",
             "inputs": {"prompt": "str"}, "outputs": {"prose": "str", "code": "list[{lang, text, kg?}]"}},
    "jev": {"file": "OpenJev-Flash-9B-Q4_K_M.gguf", "alt": "OpenJev-Q4_K_M.gguf",
            "inputs": {"state": "str", "questions": "dict[str, {type: choice|score|noul, instructions, criteria}]"},
            "outputs": {"answers": "dict[str, {option: probability}]"},
            "runnable": False, "why": "reads per-option scores at the first output position; gpt4all exposes no logits"},
}

TRIPLEX_INSTRUCTION = (
    "Perform Named Entity Recognition (NER) and extract knowledge graph triplets from the text. NER identifies "
    "named entities of given entity types, and triple extraction identifies relationships between entities using "
    "specified predicates.\n\n**Entity Types:**\n{entity_types}\n\n**Predicates:**\n{predicates}\n\n**Text:**\n{text}\n")


@dataclass
class TypedResult:
    role: str
    value: Optional[Dict[str, Any]] = None
    error: str = ""
    raw: str = ""
    notes: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.value is not None and not self.error

    def to_json(self) -> Dict[str, Any]:
        return {"role": self.role, "ok": self.ok, "value": self.value, "error": self.error, "notes": self.notes,
                "raw": self.raw[:4000]}


_ENTITY = re.compile(r"^\[(\d+)\],\s*([A-Za-z_][\w ]*?)\s*:\s*(.+)$")
_TRIPLE = re.compile(r"^\[(\d+)\]\s+([A-Za-z_][\w]*)\s+\[(\d+)\]$")


def parse_triplex(raw: str, predicates: Optional[List[str]] = None) -> TypedResult:
    """Triplex's output -> {entities, triples}. The JSON object is found
    inside a code fence or bare; every item is an entity (`[n], TYPE:name`)
    or a triple (`[a] PREDICATE [b]`). An id defined twice keeps its FIRST
    definition and is noted; an item that is neither, a triple naming an id
    never defined, or a predicate outside `predicates` is noted -- none is
    guessed at."""
    res = TypedResult("triplex", raw=raw or "")
    m = re.search(r"\{.*\}", raw or "", re.S)
    if not m:
        res.error = "no JSON object in the output"
        return res
    try:
        obj = json.loads(m.group(0))
    except ValueError as exc:
        res.error = "the JSON does not parse: %s" % exc
        return res
    items = obj.get("entities_and_triples") if isinstance(obj, dict) else None
    if not isinstance(items, list):
        res.error = "no `entities_and_triples` list"
        return res
    entities: Dict[int, Dict[str, str]] = {}
    pending = []
    for it in items:
        s = str(it).strip()
        e = _ENTITY.match(s)
        if e:
            i = int(e.group(1))
            if i in entities:
                res.notes.append("id [%d] defined again as %s:%s -- the first kept" % (i, e.group(2), e.group(3)))
                continue
            entities[i] = {"type": e.group(2).strip().upper(), "name": e.group(3).strip()}
            continue
        t = _TRIPLE.match(s)
        if t:
            pending.append((int(t.group(1)), t.group(2), int(t.group(3))))
            continue
        res.notes.append("not an entity or a triple: %r" % s[:80])
    triples = []
    allowed = {p.upper() for p in predicates} if predicates else None
    for a, p, b in pending:
        if a not in entities or b not in entities:
            res.notes.append("triple [%d] %s [%d] names an id never defined" % (a, p, b))
            continue
        if allowed is not None and p.upper() not in allowed:
            res.notes.append("predicate %s is not one asked for" % p)
            continue
        triples.append({"s": entities[a]["name"], "p": p.upper(), "o": entities[b]["name"], "s_id": a, "o_id": b,
                        "s_type": entities[a]["type"], "o_type": entities[b]["type"]})
    res.value = {"entities": {str(k): v for k, v in sorted(entities.items())}, "triples": triples}
    return res


_FENCE = re.compile(r"```([\w+-]*)\n(.*?)```", re.S)


def parse_chat(raw: str) -> TypedResult:
    """A chat model's answer -> its prose and its code blocks; a Python block
    that parses carries its compact code KG (the hybrid of 186j)."""
    import ast
    from .code_kg import compact
    res = TypedResult("chat", raw=raw or "")
    code = []
    for i, m in enumerate(_FENCE.finditer(raw or "")):
        lang, text = (m.group(1) or "").lower(), m.group(2)
        block = {"lang": lang, "text": text}
        if lang in ("", "python", "py"):
            try:
                ast.parse(text)
                block["kg"] = compact(text, "chat://answer", prefix="/answer/code[%d]" % (i + 1), qname="answer")["triples"]
            except SyntaxError as exc:
                if lang:
                    res.notes.append("python block %d does not parse: %s" % (i + 1, exc.msg))
        code.append(block)
    prose = _FENCE.sub("", raw or "").strip()
    res.value = {"prose": prose, "code": code}
    return res


_LOADED: Dict[str, Any] = {}


def _model(role: str, device: Optional[str] = None):
    from gpt4all import GPT4All
    spec = ROLES[role]
    device = device or MODEL_DEVICE
    key = "%s@%s" % (spec["file"], device)
    if key not in _LOADED:
        if not (MODEL_DIR / spec["file"]).exists():
            raise FileNotFoundError("%s is not installed in %s" % (spec["file"], MODEL_DIR))
        try:
            _LOADED[key] = GPT4All(spec["file"], model_path=str(MODEL_DIR), allow_download=False, device=device, n_ctx=4096)
        except Exception:                           # noqa: BLE001 -- no room on the GPU: the CPU
            if device == "cpu":
                raise
            return _model(role, "cpu")
    return _LOADED[key]


def plain(md: str) -> str:
    """A chunk's markdown as the prose a reader reads: link text kept, link
    targets, images, bare urls and wiki chrome ("Edit section: ...") dropped
    -- what Triplex is given, so a destination is never read as an entity."""
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", md or "")
    t = re.sub(r"\[(?:Edit section:[^\]]*|edit)\]\([^)]*\)", " ", t, flags=re.I)
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"<https?://[^>]+>|https?://\S+", " ", t)
    t = re.sub(r"[\[\]()`*_#>|]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def run_triplex(text: str, entity_types: List[str], predicates: List[str], device: Optional[str] = None,
                max_tokens: int = 800) -> TypedResult:
    msg = TRIPLEX_INSTRUCTION.format(entity_types=json.dumps({"entity_types": entity_types}),
                                     predicates=json.dumps({"predicates": predicates}), text=text)
    raw = _model("triplex", device).generate(ROLES["triplex"]["template"].format(msg=msg), max_tokens=max_tokens, temp=0.0)
    return parse_triplex(raw, predicates)


def run_chat(prompt: str, device: Optional[str] = None, max_tokens: int = 800) -> TypedResult:
    raw = _model("chat", device).generate(ROLES["chat"]["template"].format(msg=prompt), max_tokens=max_tokens, temp=0.0)
    return parse_chat(raw)


def installed() -> Dict[str, Dict[str, Any]]:
    """Each role: its file, whether it is on disk, its size, and its types."""
    out = {}
    for role, spec in ROLES.items():
        files = [spec["file"]] + ([spec["alt"]] if spec.get("alt") else [])
        on = {f: (MODEL_DIR / f).stat().st_size for f in files if (MODEL_DIR / f).exists()}
        out[role] = {"files": on, "inputs": spec["inputs"], "outputs": spec["outputs"],
                     "runnable": spec.get("runnable", True) and bool(on), "why": spec.get("why", "")}
    return out
