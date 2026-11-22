"""Token streaming latency for the local agent model (PLUGIN_GOAL 171; G-384, G-385).

"make sure we maintain real-time output latency and live-streaming token
outputs with minimal most lag, and ensure the models can stream continuously
on CUDA unblocked by other GPU processes."

Measured from outside the agent, per CLAUDE.md rule 3, in arms:

* ``gpu``       -- every layer on CUDA, nothing added to the GPU: the NULL arm.
* ``gpu+load``  -- the same, while a second process embeds on CUDA without
                   pause (what the sidecar's embedder does during a scan): the
                   arm that answers "unblocked by other GPU processes".
* ``cpu``       -- the PLANTED arm, no layer on the GPU: it must come out
                   clearly slower, or the gpu figure is not measuring offload.
* ``agent``     -- through `CodeAgent.run(stream=True)`: the lag between the
                   model yielding a token and the agent handing it on, with
                   smolagents' console rendering on (``agent``) and off
                   (``agent-quiet``).

Per arm: time to first token, tokens/s, inter-token gaps (p50, p99, max) and
stalls (gaps over `STALL_MS`). Writes `build_analytics/agent_stream.json`.

    python -m domvec.analytics.agent_stream [--arms gpu,gpu+load,cpu,agent,agent-quiet]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List

STALL_MS = 100.0
PROMPT = ("Write a Python function `chunks(xs, n)` that splits a list into pieces of n, "
          "with a docstring and two doctests. Code only.")
OUT = Path(__file__).resolve().parents[2] / "build_analytics" / "agent_stream.json"


def _pct(xs: List[float], p: float) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    return round(s[min(len(s) - 1, int(round(p / 100 * (len(s) - 1))))], 2)


def summarise(t0: float, stamps: List[float]) -> Dict:
    gaps = [(b - a) * 1000 for a, b in zip(stamps, stamps[1:])]
    span = (stamps[-1] - stamps[0]) if len(stamps) > 1 else 0.0
    return {"tokens": len(stamps),
            "ttft_ms": round((stamps[0] - t0) * 1000, 1) if stamps else None,
            "tok_per_s": round((len(stamps) - 1) / span, 1) if span else None,
            "gap_p50_ms": _pct(gaps, 50), "gap_p99_ms": _pct(gaps, 99),
            "gap_max_ms": round(max(gaps), 1) if gaps else 0.0,
            "stalls": sum(1 for g in gaps if g > STALL_MS)}


def model_arm(model) -> Dict:
    from smolagents.models import ChatMessage, MessageRole
    msgs = [ChatMessage(role=MessageRole.USER, content=PROMPT)]
    t0 = time.perf_counter()
    stamps = [time.perf_counter() for d in model.generate_stream(msgs) if d.content]
    return summarise(t0, stamps)


def agent_arm(model, quiet: bool) -> Dict:
    """Model-side stamps vs the stamps at which the agent yields the same deltas."""
    from smolagents import CodeAgent
    from smolagents.monitoring import LogLevel
    from smolagents.models import ChatMessageStreamDelta
    model_t: List[float] = []
    inner = model.generate_stream

    def stamped(*a, **k):
        for d in inner(*a, **k):
            if d.content:
                model_t.append(time.perf_counter())
            yield d
    model.generate_stream = stamped
    try:
        agent = CodeAgent(tools=[], model=model, stream_outputs=True, code_block_tags="markdown", max_steps=1,
                          verbosity_level=LogLevel.OFF if quiet else LogLevel.INFO)
        agent_t: List[float] = []
        t0 = time.perf_counter()
        for ev in agent.run(PROMPT, stream=True):
            if isinstance(ev, ChatMessageStreamDelta) and ev.content:
                agent_t.append(time.perf_counter())
    finally:
        model.generate_stream = inner
    n = min(len(model_t), len(agent_t))
    lag = [(agent_t[i] - model_t[i]) * 1000 for i in range(n)]
    out = summarise(t0, agent_t)
    out.update({"relay_lag_p50_ms": _pct(lag, 50), "relay_lag_p99_ms": _pct(lag, 99),
                "relay_lag_max_ms": round(max(lag), 2) if lag else 0.0, "model_tokens": len(model_t)})
    return out


def load_worker(seconds: float) -> None:
    """Embed on CUDA without pause, through the sidecar's own embedder path
    (`EmbeddingService._safe_embed`), so the GPU gate applies as it does
    there. `DOMVEC_PLANT_NO_GATE=1`: the planted arm, the gate off."""
    from .. import gpu_gate
    from ..core.embedding_service import EmbeddingService
    gpu_gate.PLANT_NO_GATE[0] = os.environ.get("DOMVEC_PLANT_NO_GATE") == "1"
    e = EmbeddingService(device="cuda")
    batch = ["search_document: a paragraph of scanned page text about tries, number %d" % i for i in range(64)]
    end = time.time() + seconds
    n = 0
    while time.time() < end:
        e._safe_embed(batch)
        n += len(batch)
    print(json.dumps({"embedded": n, "gate": gpu_gate.STATS}), flush=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m domvec.analytics.agent_stream")
    ap.add_argument("--arms", default="gpu,gpu+load,gpu+load-nogate,cpu,agent,agent-quiet")
    ap.add_argument("--task", default="code")
    ap.add_argument("--max-tokens", type=int, default=200)
    ap.add_argument("--load-worker", type=float, default=0.0, help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    if a.load_worker:
        load_worker(a.load_worker)
        return 0
    from ..agent_model import LlamaCppModel
    arms = [x.strip() for x in a.arms.split(",") if x.strip()]
    report: Dict = {"task": a.task, "prompt": PROMPT, "stall_ms": STALL_MS, "arms": {},
                    "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    gpu = LlamaCppModel.for_task(a.task, grammar=None, temperature=0.0, max_tokens=a.max_tokens)
    for arm in arms:
        if arm == "gpu":
            model_arm(gpu)                                   # warm: load, first CUDA kernels
            report["arms"]["gpu"] = model_arm(gpu)
        elif arm in ("gpu+load", "gpu+load-nogate"):
            env = dict(os.environ, DOMVEC_PLANT_NO_GATE="1" if arm.endswith("nogate") else "0")
            w = subprocess.Popen([sys.executable, "-m", "domvec.analytics.agent_stream", "--load-worker", "25"],
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            time.sleep(10)                                   # the worker's model is loaded and embedding
            try:
                report["arms"][arm] = model_arm(gpu)
            finally:
                try:
                    out, _ = w.communicate(timeout=40)       # the worker ends itself; its line says what it embedded
                    report["arms"][arm]["worker"] = json.loads(out.strip().splitlines()[-1]) if out.strip() else None
                except (subprocess.TimeoutExpired, ValueError):
                    w.kill()
        elif arm == "cpu":
            cpu = LlamaCppModel.for_task(a.task, grammar=None, temperature=0.0, max_tokens=a.max_tokens,
                                         n_gpu_layers=0)
            report["arms"]["cpu"] = model_arm(cpu)
            del cpu
        elif arm in ("agent", "agent-quiet"):
            report["arms"][arm] = agent_arm(gpu, quiet=(arm == "agent-quiet"))
    g, c = report["arms"].get("gpu"), report["arms"].get("cpu")
    if g and c and g.get("tok_per_s") and c.get("tok_per_s"):
        report["planted_cpu_slower"] = c["tok_per_s"] < 0.6 * g["tok_per_s"]
    lg, ln = report["arms"].get("gpu+load"), report["arms"].get("gpu+load-nogate")
    if g and lg and ln and g.get("tok_per_s"):
        report["gated_keeps_rate"] = lg["tok_per_s"] >= 0.9 * g["tok_per_s"]
        report["planted_nogate_slower"] = ln["tok_per_s"] < 0.6 * g["tok_per_s"]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    raise SystemExit(main())
