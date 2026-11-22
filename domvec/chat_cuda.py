"""The chat cell's model on CUDA, streamed and gated (G-385; PLUGIN_GOAL 171).

The plane's chat cell (`/chat_stream`, PLUGIN_GOAL 134) streams the same
Hermes GGUF it always has (`chat.MODEL_FILE`) -- but through llama.cpp
(`agent_model.LlamaCppModel`) rather than GPT4All, so it runs every layer on
CUDA and holds the GPU gate (`gpu_gate`) while it streams: the embedder
yields instead of cutting the stream to a third of its rate (measured,
`build_analytics/agent_stream.json`).

One copy resident. VRAM is 8 GB on this machine: before loading, the GPT4All
copy of the same model (the browser cell's chat, `chat._BACKEND`) is let go,
so two copies never contend for it.
"""

from __future__ import annotations

import gc
import threading
from typing import Iterator, Optional

from . import chat as _chat
from . import models as _models

_MODEL: list = [None]
_LOCK = threading.Lock()
STATS = {"loads": 0, "freed_gpt4all": 0}


def _system() -> str:
    """`chat.SYSTEM` without its ChatML wrapping: the GGUF's own chat template adds it."""
    s = _chat.SYSTEM
    for tag in ("<|im_start|>system\n", "<|im_end|>\n", "<|im_end|>"):
        s = s.replace(tag, "")
    return s.strip()


def _free_gpt4all() -> None:
    with _chat._GLOBAL:
        be = _chat._BACKEND[0]
        if be is not None and getattr(be, "_model", None) is not None:
            be.close()
            be._model = None
            be.loaded_on = ""
            _chat._ACTIVE[0] = ""
            STATS["freed_gpt4all"] += 1
    gc.collect()


def model(path: Optional[str] = None):
    with _LOCK:
        if _MODEL[0] is None:
            from .agent_model import LlamaCppModel
            _free_gpt4all()
            _MODEL[0] = LlamaCppModel(path or str(_models.MODEL_DIR / _chat.MODEL_FILE),
                                      grammar=None, temperature=0.3, n_ctx=8192)
            _MODEL[0]._load()
            STATS["loads"] += 1
        return _MODEL[0]


def stream(text: str, max_tokens: int = 400) -> Iterator[str]:
    """The reply to `text`, piece by piece as llama.cpp makes it."""
    from smolagents.models import ChatMessage, MessageRole
    m = model()
    m.max_tokens = int(max_tokens)
    msgs = [ChatMessage(role=MessageRole.SYSTEM, content=_system()),
            ChatMessage(role=MessageRole.USER, content=text)]
    for d in m.generate_stream(msgs):
        if d.content:
            yield d.content


def loaded_on() -> str:
    m = _MODEL[0]
    return "" if m is None else ("cuda" if m.n_gpu_layers != 0 else "cpu")
