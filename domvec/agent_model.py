"""A smolagents model over a GGUF on this machine (G-384; spec §10c, §11d).

The agent loop is smolagents' step (PLUGIN_GOAL 170 c). Its model is a local
quantized GGUF run by llama-cpp-python, because llama.cpp takes a GBNF grammar
per request and GPT4All (the chat path today) does not. For a 7B Q4 model the
grammar is what makes a step's FORM certain: one thought line, then exactly
one python block -- the cell the step becomes (`agent_step.py`).

Which file for which task is spec §10c's reading of each header
(`gguf_meta.describe`); `TASK_MODELS` names them. Nothing is downloaded.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from contextlib import nullcontext as _null

from smolagents import Model
from smolagents.models import ChatMessage, ChatMessageStreamDelta, MessageRole, get_clean_message_list
from smolagents.monitoring import TokenUsage

MODELS_DIR = Path(os.environ.get("DOMVEC_GGUF_DIR") or Path.home() / "AppData" / "Local" / "nomic.ai" / "GPT4All")

#: spec §10c -- the task -> the file on disk that suits it (a reading, not a measurement)
TASK_MODELS = {
    "code": "qwen2.5-coder-7b-instruct-q4_0.gguf",
    "chat": "Nous-Hermes-2-Mistral-7B-DPO.Q4_0.gguf",
    "plan": "DeepSeek-R1-Distill-Qwen-7B-Q4_0.gguf",
    "long": "Meta-Llama-3.1-8B-Instruct-128k-Q4_0.gguf",
}

#: One step, one cell: a thought line, then exactly one ```python block whose
#: lines never open with a backtick (so the block cannot be closed early).
CODE_STEP_GBNF = r'''
root     ::= "Thought: " thought "\n```python\n" code "```"
thought  ::= [^\n]+
code     ::= codeline+
codeline ::= [^`\n] [^\n]* "\n"
'''


class LlamaCppModel(Model):
    """`generate` over llama-cpp-python's chat completion, optionally under a grammar."""

    def __init__(self, path: str | Path, n_ctx: int = 8192, grammar: Optional[str] = CODE_STEP_GBNF,
                 max_tokens: int = 512, temperature: float = 0.2, n_gpu_layers: int = -1, **kwargs):
        super().__init__(model_id=Path(path).name, **kwargs)
        self.path = str(path)
        self.n_ctx = n_ctx
        self.grammar_text = grammar
        self.max_tokens = max_tokens
        self.temperature = temperature
        #: -1: every layer on CUDA (PLUGIN_GOAL 171 b). 0 is the CPU arm.
        self.n_gpu_layers = n_gpu_layers
        self._llm = None
        self._grammar = None

    @classmethod
    def for_task(cls, task: str, **kw) -> "LlamaCppModel":
        return cls(MODELS_DIR / TASK_MODELS[task], **kw)

    def _load(self):
        if self._llm is None:
            from llama_cpp import Llama, LlamaGrammar
            self._llm = Llama(model_path=self.path, n_ctx=self.n_ctx, n_gpu_layers=self.n_gpu_layers,
                              flash_attn=self.n_gpu_layers != 0, verbose=False)
            if self.grammar_text:
                self._grammar = LlamaGrammar.from_string(self.grammar_text, verbose=False)
        return self._llm

    def _request(self, messages, stop_sequences):
        # smolagents' own messages carry content as a list of text parts; a
        # bare string (a caller of our own) is wrapped to that form.
        messages = [ChatMessage(role=m.role, content=[{"type": "text", "text": m.content}])
                    if isinstance(m, ChatMessage) and isinstance(m.content, str) else m for m in messages]
        msgs = get_clean_message_list(
            messages, flatten_messages_as_text=True,
            role_conversions={MessageRole.TOOL_RESPONSE: MessageRole.USER, MessageRole.TOOL_CALL: MessageRole.ASSISTANT})
        # Under the grammar the block's own closing fence ends the step; a stop
        # sequence equal to it would cut it off and leave no closed block.
        stop = [s for s in (stop_sequences or []) if not (self._grammar and s.strip().startswith("```"))]
        return dict(messages=msgs, stop=stop or None, max_tokens=self.max_tokens,
                    temperature=self.temperature, grammar=self._grammar)

    def generate_stream(self, messages, stop_sequences=None, response_format=None, tools_to_call_from=None, **kw):
        """Token by token, as llama.cpp makes them (PLUGIN_GOAL 171 a): each
        delta is yielded the moment its chunk arrives -- nothing is buffered."""
        llm = self._load()
        n_out = 0
        from .gpu_gate import streaming
        # While this stream runs, GPU embedding in any process yields (G-385).
        with (streaming() if self.n_gpu_layers != 0 else _null()):
            for chunk in llm.create_chat_completion(stream=True, **self._request(messages, stop_sequences)):
                piece = ((chunk.get("choices") or [{}])[0].get("delta") or {}).get("content")
                if piece:
                    n_out += 1
                    yield ChatMessageStreamDelta(content=piece)
        yield ChatMessageStreamDelta(content="", token_usage=TokenUsage(input_tokens=0, output_tokens=n_out))

    def generate(self, messages, stop_sequences=None, response_format=None, tools_to_call_from=None, **kw):
        llm = self._load()
        out = llm.create_chat_completion(**self._request(messages, stop_sequences))
        text = out["choices"][0]["message"]["content"] or ""
        u = out.get("usage") or {}
        return ChatMessage(role=MessageRole.ASSISTANT, content=text, raw=out,
                           token_usage=TokenUsage(input_tokens=int(u.get("prompt_tokens") or 0),
                                                  output_tokens=int(u.get("completion_tokens") or 0)))
