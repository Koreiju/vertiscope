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
