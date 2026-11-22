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

And not resident for ever: after `IDLE_S` with no turn in flight the copy is
closed and its VRAM given back; the next turn loads it again (~2-3 s). Seen
2026-11-22: the reader started a game at 01:31 and the GPU ran at 7.8 of 8.2
GB, 100%, the sidecar's idle chat model holding ~4.5 GB of it -- "unblocked by
other GPU processes" (171 c) has a converse: ours must not block theirs.
Planted `PLANT_NEVER_RELEASE`: resident until the process ends, as before.
"""

from __future__ import annotations

import gc
import threading
from typing import Iterator, Optional

from . import chat as _chat
from . import models as _models

_MODEL: list = [None]
_LOCK = threading.Lock()
STATS = {"loads": 0, "freed_gpt4all": 0, "released": 0}
#: Seconds idle before the model's VRAM is given back.
IDLE_S = 300.0
PLANT_NEVER_RELEASE = [False]
_IN_USE = [0]
_LAST_USE = [0.0]
_REAPER: list = [None]


def release_if_idle(now: Optional[float] = None) -> bool:
    """Close the resident model when no turn is in flight and it has sat
    idle `IDLE_S`; True if it was released."""
    import time
    now = time.time() if now is None else now
    if PLANT_NEVER_RELEASE[0]:
        return False
    with _LOCK:
        m = _MODEL[0]
        if m is None or _IN_USE[0] > 0 or now - _LAST_USE[0] < IDLE_S:
            return False
        try:
            llm = getattr(m, "_llm", None)
            if llm is not None and hasattr(llm, "close"):
                llm.close()
        finally:
            m._llm = None
            _MODEL[0] = None
            STATS["released"] += 1
    gc.collect()
    return True


def _reap() -> None:
    import time
    while True:
        time.sleep(15)
        try:
            release_if_idle()
        except Exception:                         # noqa: BLE001
            pass


def _start_reaper() -> None:
    if _REAPER[0] is None:
        _REAPER[0] = threading.Thread(target=_reap, name="domvec-chat-reaper", daemon=True)
        _REAPER[0].start()


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
            _start_reaper()
        import time
        _LAST_USE[0] = time.time()
        return _MODEL[0]


def stream(text: str, max_tokens: int = 400) -> Iterator[str]:
    """The reply to `text`, piece by piece as llama.cpp makes it."""
    import time
    from smolagents.models import ChatMessage, MessageRole
    with _LOCK:
        _IN_USE[0] += 1                      # held from before the load: the reaper waits
    try:
        m = model()
        m.max_tokens = int(max_tokens)
        msgs = [ChatMessage(role=MessageRole.SYSTEM, content=_system()),
                ChatMessage(role=MessageRole.USER, content=text)]
        for d in m.generate_stream(msgs):
            if d.content:
                yield d.content
    finally:
        with _LOCK:
            _IN_USE[0] -= 1
            _LAST_USE[0] = time.time()


def loaded_on() -> str:
    m = _MODEL[0]
    return "" if m is None else ("cuda" if m.n_gpu_layers != 0 else "cpu")
