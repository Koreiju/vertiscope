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

import hashlib
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

PLANT_RESEND = [False]
#: Planted (G-444): `/chat_stream` runs one-shot -- no prior turns kept, pins re-sent.
PLANT_CHAT_ONESHOT = [False]
#: Planted (G-452): `/chat_stream` ignores ego/cell system prompts and falls back to bare prompt.
PLANT_NO_CHAT_SYSTEM = [False]

#: L-1 (`docs/PLUGIN_PRD.md`): Nous Hermes 2 DPO 7B, quantized, local CUDA --
#: read from the one model table (`models.ROLES["chat"]`).
from . import models as _models_table
MODEL_FILE = _models_table.ROLES["chat"]["file"]
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
                # Replay prior turns of `conv` into the reopened GPT4All session
                # when switching back to an existing conversation (G-444).
                if not PLANT_CHAT_ONESHOT[0] and conv.turns and hasattr(be._model, "current_chat_session"):
                    for t in conv.turns[-16:]:
                        u_msg = message(t.prompt, t.context)
                        be._model.current_chat_session.append({"role": "user", "content": u_msg})
                        be._model.current_chat_session.append({"role": "assistant", "content": t.reply})
                _ACTIVE[0] = session
        return conv


def default_stream_system() -> str:
    """Default system prompt for notebook chat cells (`G-452`), carrying ego cell/tool instructions."""
    if PLANT_NO_CHAT_SYSTEM[0]:
        return "You are an assistant."
    from . import tool_cells
    return (
        "You are a careful research and coding assistant inside an Obsidian computation-graph notebook. "
        "Answer concisely in Markdown, grounded in the pinned web chunks and notebook cells provided.\n\n"
        + tool_cells.DEFAULT_EGO_SYSTEM_PROMPT
    )


class StreamSession:
    """Multi-turn streaming session for a quantized chat cell (`G-444`).

    Keyed by the host note's `vault://` path (or explicit session key). Mirrors
    the note's turns (`seed_history` when cold after a restart, spec F-82) and
    tracks sent pinned-chunk digests (`sent_pins`) plus context-block digests
    (`sent_blocks`) so each pinned web chunk or cell block enters the model's
    context window in O(delta) -- at most once per digest unless edited.
    """

    def __init__(self, session: str) -> None:
        self.session = session
        self.turns: List[Dict[str, str]] = []
        self.sent_pins: Dict[str, str] = {}
        self.sent_blocks: Dict[str, str] = {}
        self.last_meta: Dict = {}
        self.lock = threading.Lock()

    def reset(self) -> None:
        with self.lock:
            self.turns.clear()
            self.sent_pins.clear()
            self.sent_blocks.clear()
            self.last_meta = {}

    @staticmethod
    def _digest(text: str) -> str:
        return hashlib.sha1(text.encode("utf-8", errors="replace")).hexdigest()

    def prepare(
        self,
        prompt: str,
        context: Optional[List[str]] = None,
        pins: Optional[List[Dict[str, str]]] = None,
        history: Optional[List[Dict[str, str]]] = None,
        system_prompt: Optional[str] = None,
        max_ctx_chars: int = 20000,
    ) -> Tuple[List[Dict[str, str]], Dict]:
        """Build `[system, *prior_turns, user]` messages and delta metadata."""
        sys_clean = "You are an assistant." if PLANT_NO_CHAT_SYSTEM[0] else (system_prompt or default_stream_system())
        for tag in ("<|im_start|>system\n", "<|im_end|>\n", "<|im_end|>"):
            sys_clean = sys_clean.replace(tag, "")
        sys_clean = sys_clean.strip()

        raw_blocks = [str(c).strip() for c in (context or []) if str(c).strip()]
        raw_pins = [p for p in (pins or []) if isinstance(p, dict) and str(p.get("markdown") or "").strip()]
        oneshot = bool(PLANT_CHAT_ONESHOT[0])
        resend = bool(PLANT_RESEND[0]) or oneshot

        with self.lock:
            if not oneshot and isinstance(history, list):
                valid_hist = [
                    {"user": str(h.get("user") or "").strip(), "assistant": str(h.get("assistant") or "").strip()}
                    for h in history
                    if isinstance(h, dict) and str(h.get("user") or "").strip() and str(h.get("assistant") or "").strip()
                ]
                if not self.turns and valid_hist:
                    self.turns = valid_hist[-24:]
                elif len(valid_hist) == 0 and self.turns and history is not None:
                    # Note history cleared by the reader: clear mirrored session.
                    self.turns.clear()
                    self.sent_pins.clear()
                    self.sent_blocks.clear()

            fresh_pins: List[Tuple[str, str, Dict[str, str]]] = []
            dropped_pins: List[str] = []
            seen_now = set()
            for p in raw_pins:
                md = str(p.get("markdown") or "")[:CHUNK_CAP]
                cid = str(p.get("cid") or p.get("url") or self._digest(md)[:12])
                dig = self._digest(md)
                if not resend and (cid in seen_now or self.sent_pins.get(cid) == dig):
                    dropped_pins.append(cid)
                else:
                    seen_now.add(cid)
                    fresh_pins.append((cid, dig, p))

            fresh_blocks: List[Tuple[str, str]] = []
            dropped_blocks = 0
            for b in raw_blocks:
                clipped = b[:CHUNK_CAP]
                bdig = self._digest(clipped)
                if not resend and self.turns and bdig in self.sent_blocks:
                    dropped_blocks += 1
                else:
                    fresh_blocks.append((bdig, clipped))

            parts: List[str] = []
            for _cid, _dig, p in fresh_pins:
                label = p.get("title") or p.get("head") or p.get("url") or "pinned chunk"
                url = p.get("url") or ""
                head = f"{label} ({url})" if url and url != label else str(label)
                parts.append(f"Pinned chunk from {head}:\n\n{str(p.get('markdown') or '')[:CHUNK_CAP]}")
            if fresh_blocks:
                parts.append("Context, the cells beside/above this one:\n\n" + "\n\n---\n\n".join(b for _, b in fresh_blocks))
            if parts:
                parts.append("---")
            parts.append(prompt.strip())
            user_text = "\n\n".join(parts)

            prior: List[Dict[str, str]] = []
            if not oneshot and self.turns:
                budget = max(2000, max_ctx_chars - len(user_text) - len(sys_clean))
                used = 0
                kept: List[Dict[str, str]] = []
                for t in reversed(self.turns):
                    cost = len(t["user"]) + len(t["assistant"])
                    if kept and used + cost > budget:
                        break
                    kept.append(t)
                    used += cost
                for t in reversed(kept):
                    prior.append({"role": "user", "content": t["user"]})
                    prior.append({"role": "assistant", "content": t["assistant"]})

            msgs = [{"role": "system", "content": sys_clean}, *prior, {"role": "user", "content": user_text}]
            meta = {
                "session": self.session,
                "oneshot": oneshot,
                "history_turns": len(prior) // 2,
                "stored_turns": len(self.turns),
                "fresh_pins": [cid for cid, _, _ in fresh_pins],
                "dropped_pins": dropped_pins,
                "fresh_blocks": len(fresh_blocks),
                "dropped_blocks": dropped_blocks,
                "delta_chars": len(user_text),
                "system_chars": len(sys_clean),
                "system_head": sys_clean[:160],
                "_commit_tokens": (user_text, [(cid, dig) for cid, dig, _ in fresh_pins], [bdig for bdig, _ in fresh_blocks]),
            }
            return msgs, meta

    def commit(self, meta: Dict, reply: str) -> None:
        clean_reply = (reply or "").strip()
        if not clean_reply or bool(PLANT_CHAT_ONESHOT[0]):
            with self.lock:
                self.last_meta = {k: v for k, v in meta.items() if not k.startswith("_")}
            return
        user_text, pin_digs, block_digs = meta.get("_commit_tokens") or ("", [], [])
        with self.lock:
            for cid, dig in pin_digs:
                self.sent_pins[cid] = dig
            for bdig in block_digs:
                self.sent_blocks[bdig] = bdig
            if user_text:
                self.turns.append({"user": user_text, "assistant": clean_reply})
                del self.turns[:-40]
            self.last_meta = {
                **{k: v for k, v in meta.items() if not k.startswith("_")},
                "stored_turns": len(self.turns),
            }

    def to_json(self) -> Dict:
        with self.lock:
            return {
                "session": self.session,
                "turns": len(self.turns),
                "sent_pins": sorted(self.sent_pins.keys()),
                "sent_blocks": len(self.sent_blocks),
                "last": dict(self.last_meta),
                "plant_oneshot": bool(PLANT_CHAT_ONESHOT[0]),
                "plant_resend": bool(PLANT_RESEND[0]),
            }


_STREAM_SESSIONS: Dict[str, StreamSession] = {}


def stream_session(session: str = "default") -> StreamSession:
    key = (session or "default").strip() or "default"
    with _GLOBAL:
        s = _STREAM_SESSIONS.get(key)
        if s is None:
            s = StreamSession(key)
            _STREAM_SESSIONS[key] = s
        return s
