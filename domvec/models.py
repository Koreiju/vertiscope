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
            scores -- needs logits, not text: runs through llama-cpp-python,
            never gpt4all (see the design, §4; `run_jev`)

Models load from `MODEL_DIR` (where the sidecar's downloads install them).
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

MODEL_DIR = Path(os.environ.get("DOMVEC_MODEL_DIR") or (Path.home() / ".cache" / "gpt4all"))
#: GPT4All's own app directory, where the agent's models were installed
#: (`agent_model.MODELS_DIR`). Searched second: ONE table, two places a file
#: may be (THROUGH_STACK_SYNTHESIS 1b).
APP_DIR = Path(os.environ.get("DOMVEC_GGUF_DIR") or Path.home() / "AppData" / "Local" / "nomic.ai" / "GPT4All")
MODEL_DIRS = [MODEL_DIR, APP_DIR]


def find(file: str) -> Optional[Path]:
    """Where a model file is on this machine, or None. Nothing is downloaded."""
    for d in MODEL_DIRS:
        p = Path(d) / file
        if p.exists():
            return p
    return None
#: The GPU by default: Triplex on a paragraph took 37-65 s on CPU and 1.8-3.2 s
#: on CUDA (RTX 4070 Laptop, 2026-10-18). A model that will not load there
#: (memory) falls back to CPU rather than failing the run.
MODEL_DEVICE = os.environ.get("DOMVEC_MODEL_DEVICE") or "cuda"

#: THE model table (THROUGH_STACK_SYNTHESIS 1b, PLUGIN_GOAL 181): every role
#: the system runs a local model for, one file each. It replaced three that
#: disagreed: this one had chat = DeepSeek-Coder, `agent_model.TASK_MODELS`
#: and `chat.MODEL_FILE` had chat = Nous Hermes 2 DPO (L-1, the chat cell).
#: Chat is Hermes; DeepSeek-Coder keeps its own role, `coder` (item 166).
#: `agent_model` and `chat` read their files from here.
ROLES: Dict[str, Dict[str, Any]] = {
    "triplex": {"file": "triplex-Q4_K_M.gguf", "template": "<|user|>\n{msg}<|end|>\n<|assistant|>\n",
                "inputs": {"text": "str", "entity_types": "list[str]", "predicates": "list[str]"},
                "outputs": {"entities": "dict[int, {type, name}]", "triples": "list[{s, p, o}]"}},
    "chat": {"file": "Nous-Hermes-2-Mistral-7B-DPO.Q4_0.gguf",
             "template": "<|im_start|>user\n{msg}<|im_end|>\n<|im_start|>assistant\n",
             "inputs": {"prompt": "str"}, "outputs": {"prose": "str", "code": "list[{lang, text, kg?}]"}},
    "coder": {"file": "deepseek-coder-6.7b-instruct.Q4_K_M.gguf",
              "template": "You are an AI programming assistant.\n### Instruction:\n{msg}\n### Response:\n",
              "inputs": {"prompt": "str"}, "outputs": {"prose": "str", "code": "list[{lang, text, kg?}]"}},
    "code": {"file": "qwen2.5-coder-7b-instruct-q4_0.gguf",
             "template": "<|im_start|>user\n{msg}<|im_end|>\n<|im_start|>assistant\n",
             "inputs": {"prompt": "str"}, "outputs": {"prose": "str", "code": "list[{lang, text, kg?}]"}},
    "plan": {"file": "DeepSeek-R1-Distill-Qwen-7B-Q4_0.gguf",
             "template": "<｜User｜>{msg}<｜Assistant｜>",
             "inputs": {"prompt": "str"}, "outputs": {"prose": "str", "code": "list[{lang, text, kg?}]"}},
    "long": {"file": "Meta-Llama-3.1-8B-Instruct-128k-Q4_0.gguf",
             "template": "<|start_header_id|>user<|end_header_id|>\n\n{msg}<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n",
             "inputs": {"prompt": "str"}, "outputs": {"prose": "str", "code": "list[{lang, text, kg?}]"}},
    "jev": {"file": "OpenJev-Flash-9B-Q4_K_M.gguf", "alt": "OpenJev-Q4_K_M.gguf",
            "inputs": {"state": "str", "questions": "dict[str, {type: choice|score|noul, instructions, criteria}]"},
            "outputs": {"answers": "dict[str, {option: probability}]"},
            # Runs through llama-cpp-python, NOT gpt4all: the answer is the
            # first output position's logits, which gpt4all does not expose.
            "runtime": "llama_cpp"},
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
        path = find(spec["file"])
        if path is None:
            raise FileNotFoundError("%s is not installed in %s" % (spec["file"], " or ".join(map(str, MODEL_DIRS))))
        try:
            _LOADED[key] = GPT4All(spec["file"], model_path=str(path.parent), allow_download=False, device=device, n_ctx=4096)
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


def run_chat(prompt: str, device: Optional[str] = None, max_tokens: int = 800, role: str = "chat") -> TypedResult:
    """A prompt -> prose + code role (chat, coder, code, plan, long), parsed to its type."""
    if ROLES.get(role, {}).get("outputs", {}).get("code") is None:
        return TypedResult(role, error="%s is not a prompt -> prose + code role" % role)
    raw = _model(role, device).generate(ROLES[role]["template"].format(msg=prompt), max_tokens=max_tokens, temp=0.0)
    res = parse_chat(raw)
    res.role = role                                 # the role RUN, not the parser's name
    return res


# --- jev: typed decisions read from first-position logits (G-237) ----------
#
# The request and readout follow the publisher's helper (openjev/openjev
# `helper/shim.py`, `serve/SERVE.md`): one user turn, thinking off; options
# lettered A-Z then a-z; ONE forward pass; each option's score is the
# log-probability of its letter at the first output position; calibrated with
# the constants SERVE.md reports its measurements under (T 0.85; yes/no slope
# 1.829074, bias 0). Those were fitted on the vLLM path -- that they carry to
# this GGUF is an assumption, stated in every answer's notes.

JEV_LETTERS = [chr(65 + i) for i in range(26)] + [chr(97 + i) for i in range(26)]
JEV_T = 0.85
JEV_NOUL_T = 1.829074
JEV_NOUL_BIAS = 0.0
JEV_TEMPLATE = "<|im_start|>user\n{msg}<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"
#: Planted (G-237): option i is scored by letter i+1's logit -- the readout
#: is shifted one place, so an obvious question's answer moves.
PLANT_JEV_LETTER_SHIFT = [False]


def jev_options(q: Dict[str, Any]):
    """A question -> (kind, instructions text, [(key, description)]), or
    raises ValueError naming what is malformed. Never guesses a type."""
    kind = str(q.get("type") or "")
    instr = q.get("instructions") or ""
    instr = instr if isinstance(instr, str) else str(instr)   # pyrepr: the wording it was trained on
    crit = q.get("criteria")
    if kind == "choice":
        if not isinstance(crit, dict) or not crit:
            raise ValueError("a choice needs criteria: {option: description}")
        opts = [(str(k), "" if v is None else str(v)) for k, v in crit.items()]
    elif kind == "score":
        if not isinstance(crit, list) or len(crit) < 2:
            raise ValueError("a score needs criteria: at least two levels, lowest first")
        opts = [(str(i), str(v)) for i, v in enumerate(crit)]
        instr = (instr + " Rate along the ordered levels below (lowest first).").strip()
    elif kind == "noul":
        crit = crit if isinstance(crit, dict) else {}
        opts = [("yes", str(crit.get("true") or "The statement is true.")),
                ("no", str(crit.get("false") or "The statement is false."))]
    else:
        raise ValueError("type is one of choice, score, noul -- not %r" % kind)
    if len(opts) > len(JEV_LETTERS):
        raise ValueError("%d options; one pass reads at most %d" % (len(opts), len(JEV_LETTERS)))
    return kind, instr, opts


def jev_prompt(state: Any, instr: str, opts) -> str:
    st = state if isinstance(state, str) else json.dumps(state, ensure_ascii=False)
    lines = "\n".join("[%s] %s: %s" % (JEV_LETTERS[i], k, d) for i, (k, d) in enumerate(opts))
    msg = "State:\n%s\n\nQuestion: %s\nOptions:\n%s\n\nAnswer with the letter of the best option only." % (st, instr, lines)
    return JEV_TEMPLATE.format(msg=msg)


def jev_readout(kind: str, opts, logprobs: List[float]) -> Dict[str, Any]:
    """Per-option letter log-probabilities -> the typed, calibrated answer."""
    import math
    if kind == "noul":
        a, b = logprobs[0], logprobs[1]
        m = max(a, b)
        py = math.exp(a - m) / (math.exp(a - m) + math.exp(b - m))
        py = min(max(py, 1e-4), 1 - 1e-4)
        z = math.log(py / (1 - py)) / JEV_NOUL_T + JEV_NOUL_BIAS
        return {"type": "noul", "noul": round(1 / (1 + math.exp(-z)), 4)}
    z = [lp / JEV_T for lp in logprobs]
    m = max(z)
    e = [math.exp(v - m) for v in z]
    tot = sum(e)
    p = [v / tot for v in e]
    n = len(p)
    probs = {k: round(p[i], 4) for i, (k, _) in enumerate(opts)}
    best = max(range(n), key=lambda i: p[i])
    if kind == "choice":
        return {"type": "choice", "choice": opts[best][0], "probabilities": probs,
                "confidence": round((p[best] - 1.0 / n) / (1 - 1.0 / n), 4)}
    mid = (n - 1) / 2.0
    umad = sum(abs(i - mid) for i in range(n)) / n or 1.0
    dist = sum(p[i] * abs(i - best) for i in range(n))
    return {"type": "score", "score": round(sum(i * p[i] for i in range(n)), 4),
            "legend": {k: d for k, d in opts}, "probabilities": probs,
            "confidence": round(max(0.0, 1 - dist / umad), 4)}


_JEV: List[Any] = [None]


def _jev_llm():
    """OpenJev through llama-cpp-python. CPU by default: the 5.6 GB file does
    not fit beside what this 8 GB GPU already holds; `DOMVEC_JEV_GPU_LAYERS`
    offloads layers where it does."""
    if _JEV[0] is None:
        from llama_cpp import Llama
        path = find(ROLES["jev"]["file"]) or find(ROLES["jev"].get("alt") or "")
        if path is None:
            raise FileNotFoundError("%s is not installed in %s" % (ROLES["jev"]["file"], " or ".join(map(str, MODEL_DIRS))))
        _JEV[0] = Llama(str(path), n_ctx=4096, n_gpu_layers=int(os.environ.get("DOMVEC_JEV_GPU_LAYERS") or 0),
                        logits_all=False, verbose=False)
    return _JEV[0]


def _first_logprobs(llm, prompt: str, letter_ids: List[int]) -> List[float]:
    import numpy as np
    toks = llm.tokenize(prompt.encode("utf-8"), add_bos=False, special=True)
    llm.reset()
    llm.eval(toks)
    # The LAST position's logits, from the context's own buffer. NOT
    # `llm.scores`: without `logits_all` llama-cpp-python 0.3 never writes
    # them there, and the row read as all zeros -- every option 1/3, which
    # the planted shift could not move (run 94). `logits_all` would hold
    # n_ctx x 248k floats (~4 GB) to read one row.
    ptr = llm._ctx.get_logits()
    n = llm.n_vocab()
    row = np.array(ptr[:n] if isinstance(ptr, (list, np.ndarray)) else np.ctypeslib.as_array(ptr, shape=(n,)),
                   dtype=np.float64)
    if not row.any():
        raise RuntimeError("the first output position's logits are all zero -- nothing was read")
    m = row.max()
    lse = m + np.log(np.exp(row - m).sum())
    return [float(row[i] - lse) for i in letter_ids]


def run_jev(state: Any, questions: Dict[str, Dict[str, Any]], llm=None) -> TypedResult:
    """jev: {state, questions} -> {answers}: each question's calibrated
    distribution over ITS options, read from one forward pass. A malformed
    question is refused by name; nothing is coerced."""
    if not isinstance(questions, dict) or not questions:
        return TypedResult("jev", error="questions: {name: {type, instructions, criteria}}")
    parsed = {}
    for name, q in questions.items():
        try:
            parsed[name] = jev_options(q if isinstance(q, dict) else {})
        except ValueError as exc:
            return TypedResult("jev", error="%s: %s" % (name, exc))
    llm = llm or _jev_llm()
    ids = [llm.tokenize(L.encode("utf-8"), add_bos=False, special=False)[0] for L in JEV_LETTERS]
    notes = ["calibration: SERVE.md's vLLM constants (T %.2f, yes/no slope %.3f), assumed to carry to this GGUF"
             % (JEV_T, JEV_NOUL_T)]
    answers = {}
    for name, (kind, instr, opts) in parsed.items():
        n = len(opts)
        use = ids[1:n + 1] if PLANT_JEV_LETTER_SHIFT[0] else ids[:n]
        answers[name] = jev_readout(kind, opts, _first_logprobs(llm, jev_prompt(state, instr, opts), use))
    return TypedResult("jev", value={"answers": answers}, notes=notes)


def installed() -> Dict[str, Dict[str, Any]]:
    """Each role: its file, whether it is on disk, its size, and its types."""
    out = {}
    for role, spec in ROLES.items():
        files = [spec["file"]] + ([spec["alt"]] if spec.get("alt") else [])
        on = {f: find(f).stat().st_size for f in files if find(f) is not None}
        out[role] = {"files": on, "inputs": spec["inputs"], "outputs": spec["outputs"],
                     "runnable": spec.get("runnable", True) and bool(on), "why": spec.get("why", "")}
    return out
