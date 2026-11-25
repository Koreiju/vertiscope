"""An agent's run written as notebook cells (G-384; PLUGIN_GOAL 170 c, spec §11d).

"smolagents 'step' if only architectural ambiguity" -- smolagents' step is the
agent loop. Each `ActionStep` of a `CodeAgent` is one cell of the note: its
code a ```` ```python ```` fence, its observation that cell's output in the
notebook's own on-disk form (`obsidian-plugin/src/outputs.ts`):

    ```python
    hits = search("radix trie")
    ```
    <!-- nb-output hash=<sha256 of the exact source> count=1 status=ok format=text -->
    ````text
    ...
    ````
    <!-- /nb-output -->

So an agent's run reads as cells the reader's own runs read as -- the plugin's
outline, rewind and staleness see it with no new path -- and `dataflow.graph`
gives the edges between its steps: the agent's work appears in panel form and
graph form alike (spec §11b). The hash is the exact source, as `hashCell`
computes it (CLAUDE.md 5b), so a reader's edit to a step's code marks its
output stale.

In trie terms: each step becomes `vault://<note>#cell <n>`; this module writes
text, and the note's ingest is what puts it in the trie.
"""

from __future__ import annotations

import hashlib
import re
from typing import Iterable, List, Optional

PLANT_DROP_OBSERVATIONS = [False]


def cell_source(raw: str) -> str:
    """`fences.cellSource`: CRLF to LF, trailing newlines off."""
    return re.sub(r"\n+$", "", raw.replace("\r\n", "\n"))


def hash_cell(source: str) -> str:
    """`outputs.hashCell`: SHA-256 of the exact source, hex."""
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _fence_for(body: str) -> str:
    longest = max([len(r) for r in re.findall(r"`+", body)] or [0])
    return "`" * max(4, longest + 1)


def render_output(stdout: str, error: Optional[str], value: Optional[str], src_hash: str, count: int) -> List[str]:
    """`outputs.renderOutput`, line for line."""
    parts = []
    if stdout and stdout.strip():
        parts.append(stdout.rstrip("\n"))
    if error:
        parts.append(error.rstrip("\n"))
    elif value:
        parts.append(value)
    status = "error" if error else "ok"
    head = "<!-- nb-output hash=%s count=%d status=%s format=text -->" % (src_hash, count, status)
    if not parts:
        return [head, "<!-- /nb-output -->"]
    body = "\n".join(parts)
    fence = _fence_for(body)
    return [head, fence + "text", *body.split("\n"), fence, "<!-- /nb-output -->"]


def step_cells(steps: Iterable, start_count: int = 1) -> List[str]:
    """Each smolagents `ActionStep` that ran code, as a cell plus its output."""
    out: List[str] = []
    n = start_count
    for s in steps:
        code = getattr(s, "code_action", None)
        if not code:
            continue
        src = cell_source(code)
        obs = "" if PLANT_DROP_OBSERVATIONS[0] else (getattr(s, "observations", None) or "")
        err = getattr(s, "error", None)
        final = getattr(s, "action_output", None) if getattr(s, "is_final_answer", False) else None
        out += ["```python", *src.split("\n"), "```"]
        out += render_output(obs, str(err) if err else None,
                             None if final is None else repr(final), hash_cell(src), n)
        out.append("")
        n += 1
    return out


def run_note(agent, task: str, title: str = "") -> str:
    """Run `agent` on `task`; the run as a note: the task, then one cell per step."""
    agent.run(task)
    head = ["# " + (title or task[:60]), "", "> " + task.replace("\n", "\n> "), ""]
    return "\n".join(head + step_cells(agent.memory.steps)) + "\n"


def run_into(agent, task: str, path, title: str = "", pace_s: float = 0.0) -> int:
    """Run `agent` on `task` with the run APPEARING as it goes (G-384: "Not
    built: the run appearing live in the app"): the note at `path` is written
    with the task first, then each step's cell and output appended the moment
    smolagents yields it (`run(stream=True)`), so the reader's open note grows
    step by step. Returns the steps written. `pace_s` holds between steps (the
    dry check's way to be seen growing). Planted `PLANT_WRITE_AT_END`: one
    write when the run is over, as `run_note` does.

    In trie terms: each append is a write to vault://<note>; the note's ingest
    puts each new cell in the trie as it lands.
    """
    import time
    from pathlib import Path
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    head = ["# " + (title or task[:60]), "", "> " + task.replace("\n", "\n> "), ""]
    p.write_text("\n".join(head) + "\n", encoding="utf-8")
    steps = []
    n = 0
    for st in agent.run(task, stream=True):
        if not getattr(st, "code_action", None):
            continue
        steps.append(st)
        if PLANT_WRITE_AT_END[0]:
            continue
        with p.open("a", encoding="utf-8") as fh:
            fh.write("\n".join(step_cells([st], start_count=n + 1)) + "\n")
        n += 1
        if pace_s:
            time.sleep(pace_s)
    if PLANT_WRITE_AT_END[0]:
        with p.open("a", encoding="utf-8") as fh:
            fh.write("\n".join(step_cells(steps)) + "\n")
        n = len(steps)
    return n


PLANT_WRITE_AT_END = [False]


def scripted_model(replies):
    """A smolagents Model answering each step with the next scripted reply --
    the dry arm the live check drives a real CodeAgent with."""
    from smolagents import Model
    from smolagents.models import ChatMessage, MessageRole

    class _Scripted(Model):
        def __init__(self):
            super().__init__(model_id="scripted")
            self.replies = list(replies)

        def generate(self, messages, stop_sequences=None, response_format=None, tools_to_call_from=None, **kw):
            return ChatMessage(role=MessageRole.ASSISTANT, content=self.replies.pop(0))

    return _Scripted()
