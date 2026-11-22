"""G-384: a smolagents CodeAgent's steps become notebook cells (domvec/agent_step.py).

A real `CodeAgent` and its real local executor run; only the MODEL is
scripted (a 7B model has no place in a unit test). Planted
`PLANT_DROP_OBSERVATIONS`: the outputs vanish and the check must see it.
"""

import pytest

smolagents = pytest.importorskip("smolagents")
from smolagents import CodeAgent, Model, tool                       # noqa: E402
from smolagents.models import ChatMessage, MessageRole               # noqa: E402

from domvec import agent_step as ag                                 # noqa: E402
from domvec import dataflow as df                                   # noqa: E402


@tool
def search(query: str) -> list:
    """Ranked chunks for a query (a stand-in for the kernel's `search`).

    Args:
        query: what to look for
    """
    return ["chunk about %s" % query, "another on %s" % query]


class Scripted(Model):
    """Answers each step with the next scripted reply."""

    def __init__(self, replies):
        super().__init__(model_id="scripted")
        self.replies = list(replies)

    def generate(self, messages, stop_sequences=None, response_format=None, tools_to_call_from=None, **kw):
        return ChatMessage(role=MessageRole.ASSISTANT, content=self.replies.pop(0))


REPLIES = [
    "Thought: look it up.\n```python\nhits = search(\"radix trie\")\nprint(len(hits))\n```",
    "Thought: answer.\n```python\nfinal_answer(hits[0])\n```",
]


def _agent():
    return CodeAgent(tools=[search], model=Scripted(REPLIES), code_block_tags="markdown", max_steps=4)


def test_each_step_is_a_cell_with_its_output():
    note = ag.run_note(_agent(), "find the radix trie chunk")
    assert note.count("```python") == 2
    assert "hits = search(\"radix trie\")" in note
    assert note.count("<!-- nb-output ") == 2 and note.count("<!-- /nb-output -->") == 2
    assert "count=1 status=ok" in note and "count=2 status=ok" in note
    assert "\n2\n" in note                                   # the first step's print
    assert "'chunk about radix trie'" in note                # the final answer as the last output


def test_the_hash_is_the_plugins_exact_source_hash():
    cells = ag.step_cells(_run_steps())
    src = 'hits = search("radix trie")\nprint(len(hits))'
    assert "hash=" + ag.hash_cell(src) in "\n".join(cells)
    # the plugin's hashCell over the same bytes (sha256 hex), recomputed independently
    import hashlib
    assert ag.hash_cell(src) == hashlib.sha256(src.encode()).hexdigest()


def test_the_steps_are_a_dataflow_graph():
    g = df.graph(ag.run_note(_agent(), "find it"), known={"search", "final_answer"})
    assert g.edges[0] == {1}                                 # step 2 reads `hits` from step 1
    assert g.problems == []


def test_planted_dropped_observations_are_caught():
    ag.PLANT_DROP_OBSERVATIONS[0] = True
    try:
        note = ag.run_note(_agent(), "find it")
    finally:
        ag.PLANT_DROP_OBSERVATIONS[0] = False
    assert "\n2\n" not in note                               # the defect: the print is gone


def test_render_output_matches_the_plugin_form():
    lines = ag.render_output("a ```` b", None, None, "h", 3)
    assert lines[0] == "<!-- nb-output hash=h count=3 status=ok format=text -->"
    assert lines[1] == "`````text" and lines[-2] == "`````"      # one longer than the body's run
    assert ag.render_output("", None, None, "h", 1) == [
        "<!-- nb-output hash=h count=1 status=ok format=text -->", "<!-- /nb-output -->"]


def _run_steps():
    a = _agent()
    a.run("find it")
    return a.memory.steps
