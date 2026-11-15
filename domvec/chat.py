"""The browser cell's chat -- `G-43`, `G-44`, `G-45` (PLUGIN_GOAL, O.2).

The verbatim: "a hoverable chat panel on the standalone browser window ...
that collects the right-click selected *full* markdowns as context
efficiently so that the same chunks are *never* re-sent to the context
window, meaning the delta-diff updates to the context window of the chat
works similar"; "the right-clicked elements after the most previous response
are included in the very next prompt"; "Chat outputs would be in a panel
below the web-selected markdown ... all in markdown".

So a conversation is a sequence of turns, and a turn's input is the reader's
prompt plus the chunks they pinned since the last reply -- each chunk's full
markdown, at most once per conversation. The rule is enforced HERE, at the
context window's edge, not only by the panel: a chunk already sent is
dropped from a turn and named in `resent_dropped`, so a panel that forgot
what it sent cannot put it in twice.

The model holds the conversation itself (GPT4All's `chat_session`: the
history lives in the model's context and each turn feeds only the new
message), so what crosses into the context window per turn is exactly the
turn's delta -- `delta_chars` measures it. Planted `PLANT_RESEND`: every turn
carries every chunk pinned so far, as a stateless chat would.

The model is L-1's: Nous Hermes 2 DPO (Mistral 7B, Q4_0), local, on CUDA.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

PLANT_RESEND = [False]

#: L-1 (`docs/PLUGIN_PRD.md`): Nous Hermes 2 DPO 7B, quantized, local CUDA.
MODEL_FILE = "Nous-Hermes-2-Mistral-7B-DPO.Q4_0.gguf"
SYSTEM = ("<|im_start|>system\nYou are a careful research assistant inside a web browser. The reader pins "
          "parts of web pages as markdown and asks about them. Answer in markdown, from the pinned material "
          "when it is relevant, and say so when it does not contain the answer.<|im_end|>\n")
TEMPLATE = "<|im_start|>user\n{0}<|im_end|>\n<|im_start|>assistant\n"
#: A chunk's markdown is sent whole (the verbatim's *full*), up to this many
#: characters -- the model's whole window is 8,192 tokens.
CHUNK_CAP = 6000


@dataclass
class Turn:
    prompt: str
    context: List[Dict[str, str]]
    reply: str = ""
    delta_chars: int = 0
    resent_dropped: List[str] = field(default_factory=list)
    ms: float = 0.0
    at: float = 0.0

    def to_json(self) -> Dict:
        return {"prompt": self.prompt, "context": [{k: c.get(k, "") for k in ("cid", "url", "head")} for c in self.context],
                "reply": self.reply, "delta_chars": self.delta_chars, "resent_dropped": self.resent_dropped,
                "ms": round(self.ms, 1), "at": self.at}


def message(prompt: str, context: List[Dict[str, str]]) -> str:
    """One turn's input: the newly pinned chunks, then the prompt."""
    parts = []
    for c in context:
        md = (c.get("markdown") or "")[:CHUNK_CAP]
        parts.append("Pinned from %s:\n\n%s" % (c.get("url") or "the page", md))
    if parts:
        parts.append("---")
    parts.append(prompt.strip())
    return "\n\n".join(parts)


class Conversation:
    """One browser cell's chat. `generate(text) -> reply` feeds ONE new
    message to a model that keeps the conversation; `reset()` starts over."""

    def __init__(self, session: str, generate: Callable[[str], str], reset: Optional[Callable[[], None]] = None):
        self.session = session
        self._generate = generate
        self._reset = reset
        self.sent: Dict[str, float] = {}
        self.pinned_ever: List[Dict[str, str]] = []
        self.turns: List[Turn] = []
        self.lock = threading.Lock()

    def ask(self, prompt: str, context: List[Dict[str, str]]) -> Turn:
        with self.lock:
            fresh, dropped = [], []
            for c in context:
                cid = str(c.get("cid") or "")
                if not cid:
                    continue
                if cid in self.sent or any(f.get("cid") == cid for f in fresh):
                    dropped.append(cid)
                else:
                    fresh.append(c)
            for c in fresh:
                self.pinned_ever.append(c)
            send = list(self.pinned_ever) if PLANT_RESEND[0] else fresh
            text = message(prompt, send)
            t0 = time.perf_counter()
            reply = self._generate(text)
            turn = Turn(prompt=prompt, context=fresh, reply=(reply or "").strip(), delta_chars=len(text),
                        resent_dropped=dropped, ms=(time.perf_counter() - t0) * 1000, at=time.time())
            now = time.time()
            for c in fresh:
                self.sent[str(c["cid"])] = now
            self.turns.append(turn)
            return turn

    def reset(self) -> None:
        with self.lock:
            self.sent.clear()
            self.pinned_ever.clear()
            self.turns.clear()
            if self._reset:
                self._reset()

    def to_json(self) -> Dict:
        return {"session": self.session, "turns": [t.to_json() for t in self.turns], "sent": sorted(self.sent),
                "plant_resend": bool(PLANT_RESEND[0])}


class HermesBackend:
    """L-1's model with one live `chat_session`: the conversation is kept in
    the model's context, so a turn feeds only its new message. One session at
    a time per model; a new conversation closes the previous one."""

    def __init__(self, model_dir: Optional[str] = None, device: Optional[str] = None, n_ctx: int = 8192,
                 max_tokens: int = 700):
        from . import models
        self.model_dir = str(model_dir or models.MODEL_DIR)
        self.device = device or models.MODEL_DEVICE
        self.n_ctx = n_ctx
        self.max_tokens = max_tokens
        self._model = None
        self._cm = None
        self.loaded_on = ""

    def _load(self):
        if self._model is None:
            from gpt4all import GPT4All
            try:
                self._model = GPT4All(MODEL_FILE, model_path=self.model_dir, allow_download=False,
                                      device=self.device, n_ctx=self.n_ctx)
                self.loaded_on = self.device
            except Exception:                       # noqa: BLE001 -- no room on the GPU: the CPU
                self._model = GPT4All(MODEL_FILE, model_path=self.model_dir, allow_download=False,
                                      device="cpu", n_ctx=self.n_ctx)
                self.loaded_on = "cpu"
        return self._model

    def open(self) -> None:
        self.close()
        m = self._load()
        self._cm = m.chat_session(SYSTEM, TEMPLATE)
        self._cm.__enter__()

    def close(self) -> None:
        if self._cm is not None:
            try:
                self._cm.__exit__(None, None, None)
            except Exception:                       # noqa: BLE001
                pass
            self._cm = None

    def generate(self, text: str) -> str:
        with GEN_LOCK:
            if self._cm is None:
                self.open()
            return self._load().generate(text, max_tokens=self.max_tokens, temp=0.3)


_CONVERSATIONS: Dict[str, Conversation] = {}
_BACKEND: List[Optional[HermesBackend]] = [None]
_ACTIVE: List[str] = [""]
_GLOBAL = threading.Lock()

#: ONE generation at a time on the shared model, whichever route asks: the
#: plane's chat cell (`/chat_stream`) and the browser cell (`/chat`) hold the
#: same `HermesBackend`, and gpt4all's model is not reentrant. Two turns at
#: once (2026-11-14 19:55) ended in "Windows fatal exception: access
#: violation" inside `prompt_model` and a worker that never exited. A second
#: turn WAITS for the first; it is never refused.
GEN_LOCK = threading.Lock()
#: Generations running right now, and the most seen at once -- read by the
#: live check, which plants the lock away and expects 2.
IN_FLIGHT = {"now": 0, "peak": 0}


def conversation(session: str, backend_factory: Callable[[], HermesBackend] = HermesBackend) -> Conversation:
    """The conversation for a browser cell. The model keeps ONE session; a
    different cell's conversation becoming active restarts the model's
    session and replays nothing -- its own record says what it was sent."""
    with _GLOBAL:
        if _BACKEND[0] is None:
            _BACKEND[0] = backend_factory()
        be = _BACKEND[0]
        conv = _CONVERSATIONS.get(session)
        if conv is None:
            conv = Conversation(session, be.generate, be.open)
            _CONVERSATIONS[session] = conv
        if _ACTIVE[0] != session:
            be.open()
            if _ACTIVE[0]:
                # The other cell's conversation lost its model session: its
                # record is cleared too, so nothing it holds claims to be in
                # a context window it is no longer in.
                other = _CONVERSATIONS.get(_ACTIVE[0])
                if other is not None:
                    other.sent.clear()
                    other.pinned_ever.clear()
            _ACTIVE[0] = session
        return conv
